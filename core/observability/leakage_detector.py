"""Leakage Detector — static-analysis advisor for @feature functions.

Scans source code for common look-ahead / forward-shift patterns that
silently produce inflated backtest results. **Advisory this round**:
warnings are emitted via ``logging.WARNING`` and returned to the caller,
but feature loading is not blocked. The next round upgrades to a CI gate
once the false-positive rate is understood.

Patterns flagged today (see ``LeakagePattern``):

1. ``df['close'].shift(-N)`` — any negative shift on a price/return
   series is a forward read. The most common backtest leak.
2. Future-dated index slicing — ``df.loc[t + offset:]`` where ``offset``
   is positive (heuristic, may produce false positives on join logic).
3. ``df.resample(...).last()`` without ``closed='left'`` and
   ``label='left'`` — the resample default is ``right``-closed, which
   includes the bar's own close in the output of an "as of" query at
   the bar's open. The classic intraday-leak source.
4. Returns computed forward: ``(close.shift(-N) / close - 1)`` or any
   division/subtraction whose numerator references a negative shift.

The detector is AST-based, not regex-based, so it tolerates variable
names, parens, and whitespace. It only inspects code reachable from the
provided source; it does NOT chase imports.

Public API:

    >>> from core.observability import scan_source, scan_callable
    >>> warnings = scan_source(source_code_string, filename="my_feat.py")
    >>> warnings = scan_callable(my_feature_func)
"""
from __future__ import annotations

import ast
import inspect
import logging
import textwrap
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


class LeakagePattern(str, Enum):
    """Closed vocabulary of the patterns this detector recognises."""

    NEGATIVE_SHIFT = "negative_shift"
    FUTURE_INDEX_SLICE = "future_index_slice"
    UNSAFE_RESAMPLE = "unsafe_resample"
    FORWARD_RETURN = "forward_return"


@dataclass(frozen=True)
class LeakageWarning:
    """One suspicious pattern detected at a specific line."""

    pattern: LeakagePattern
    lineno: int
    col_offset: int
    snippet: str
    reason: str
    filename: str = "<source>"

    def format(self) -> str:
        """Single-line human-readable rendering for log output."""
        return (
            f"{self.filename}:{self.lineno}:{self.col_offset}: "
            f"[{self.pattern.value}] {self.reason} | snippet: {self.snippet}"
        )


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _shift_arg_value(call: ast.Call) -> Optional[Any]:
    """Return the first positional or ``periods=`` keyword argument of a
    ``.shift(...)`` call, or ``None`` if it isn't a literal we can read.

    We deliberately avoid evaluating the AST — only literal constants
    (positive or negative ints / floats unary-negated) are inspected.
    Anything dynamic (variables, expressions) returns ``None`` and is
    skipped, accepting a false-negative rather than risking eval.
    """
    if call.args:
        arg = call.args[0]
        return _literal_int(arg)
    for kw in call.keywords:
        if kw.arg == "periods":
            return _literal_int(kw.value)
    return None


def _literal_int(node: ast.AST) -> Optional[int]:
    """Best-effort extraction of an int literal, including ``-N``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return int(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal_int(node.operand)
        return -inner if inner is not None else None
    return None


def _is_shift_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "shift"
    )


def _is_resample_chain(node: ast.AST) -> Optional[ast.Call]:
    """Return the ``resample(...)`` Call within a ``.resample(...).last()``
    or similar chain, or ``None`` if the outer call isn't on a
    leak-prone aggregator.

    We only care about aggregators that "look back" by default —
    ``.last()``, ``.max()``, ``.min()``, ``.first()``, ``.agg()``.
    """
    leaky_aggs = {"last", "max", "min", "first", "agg"}
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr not in leaky_aggs:
        return None
    inner = node.func.value
    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
        if inner.func.attr == "resample":
            return inner
    return None


def _resample_has_safe_kwargs(call: ast.Call) -> bool:
    """``resample(...)`` is safe when caller passed both
    ``closed='left'`` and ``label='left'``.

    Either keyword alone leaves the door open. We require both because
    the pandas default is right-closed/right-labelled, which is the
    leakage shape.
    """
    closed_left = False
    label_left = False
    for kw in call.keywords:
        if kw.arg == "closed" and isinstance(kw.value, ast.Constant):
            if kw.value.value == "left":
                closed_left = True
        if kw.arg == "label" and isinstance(kw.value, ast.Constant):
            if kw.value.value == "left":
                label_left = True
    return closed_left and label_left


def _expression_contains_negative_shift(node: ast.AST) -> bool:
    """Walk an expression looking for any nested ``.shift(<negative>)``."""
    for sub in ast.walk(node):
        if _is_shift_call(sub):
            assert isinstance(sub, ast.Call)
            v = _shift_arg_value(sub)
            if v is not None and v < 0:
                return True
    return False


# ---------------------------------------------------------------------------
# Public scan API
# ---------------------------------------------------------------------------


def scan_source(
    source: str,
    filename: str = "<source>",
    log_warnings: bool = True,
) -> List[LeakageWarning]:
    """Scan a string of Python source for leakage patterns.

    Returns a list of ``LeakageWarning`` (possibly empty). On a syntax
    error, returns an empty list and logs a single WARNING — we do not
    re-raise because the detector must never block its caller.

    ``log_warnings`` controls whether each finding is also emitted to
    the module logger at WARNING level. Tests typically set ``False``
    to keep output clean.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        logger.warning(
            "leakage_detector: cannot parse %s: %s", filename, exc
        )
        return []

    warnings: List[LeakageWarning] = []
    source_lines = source.splitlines()

    def snippet_at(lineno: int) -> str:
        """1-indexed line lookup with safe fallback."""
        if 1 <= lineno <= len(source_lines):
            return source_lines[lineno - 1].strip()
        return ""

    for node in ast.walk(tree):
        # 1) Negative shift on any series
        if _is_shift_call(node):
            assert isinstance(node, ast.Call)
            v = _shift_arg_value(node)
            if v is not None and v < 0:
                warnings.append(LeakageWarning(
                    pattern=LeakagePattern.NEGATIVE_SHIFT,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    snippet=snippet_at(node.lineno),
                    reason=(
                        f"shift({v}) reads {abs(v)} bar(s) into the future "
                        f"— forbidden in any feature evaluated at time t"
                    ),
                    filename=filename,
                ))

        # 2) Forward-return expression: BinOp whose subtree contains a
        # negative shift (e.g. ``close.shift(-1) / close - 1``).
        if isinstance(node, ast.BinOp):
            if _expression_contains_negative_shift(node):
                warnings.append(LeakageWarning(
                    pattern=LeakagePattern.FORWARD_RETURN,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    snippet=snippet_at(node.lineno),
                    reason=(
                        "binary expression contains a negative-shift term — "
                        "looks like a forward return computed from t to t+N"
                    ),
                    filename=filename,
                ))

        # 3) Unsafe resample().last() / .max() etc.
        resample_call = _is_resample_chain(node)
        if resample_call is not None:
            if not _resample_has_safe_kwargs(resample_call):
                warnings.append(LeakageWarning(
                    pattern=LeakagePattern.UNSAFE_RESAMPLE,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    snippet=snippet_at(node.lineno),
                    reason=(
                        "resample(...) without closed='left' and label='left' "
                        "is right-closed by default — the bar's own close "
                        "leaks into queries at the bar's open"
                    ),
                    filename=filename,
                ))

        # 4) Future-dated index slicing — heuristic. We flag any
        # ``.loc[expr:]`` where ``expr`` is a BinOp adding a positive
        # constant to something. Catches ``df.loc[t + 1:]`` style.
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
            if node.value.attr in {"loc", "iloc"}:
                slice_node = node.slice
                # Slice can be a Slice or a tuple containing one
                slices: List[ast.AST] = []
                if isinstance(slice_node, ast.Slice):
                    slices.append(slice_node)
                elif isinstance(slice_node, ast.Tuple):
                    for elt in slice_node.elts:
                        if isinstance(elt, ast.Slice):
                            slices.append(elt)
                for sl in slices:
                    if isinstance(sl, ast.Slice) and sl.lower is not None:
                        if _is_future_offset_expr(sl.lower):
                            warnings.append(LeakageWarning(
                                pattern=LeakagePattern.FUTURE_INDEX_SLICE,
                                lineno=node.lineno,
                                col_offset=node.col_offset,
                                snippet=snippet_at(node.lineno),
                                reason=(
                                    "index slice lower bound looks like "
                                    "t + positive_offset — reads ahead of "
                                    "the evaluation timestamp"
                                ),
                                filename=filename,
                            ))

    if log_warnings:
        for w in warnings:
            logger.warning("leakage_detector: %s", w.format())

    return warnings


def _is_future_offset_expr(node: ast.AST) -> bool:
    """True iff ``node`` is a BinOp ``X + positive_constant``.

    Heuristic only — ``X + 1`` could legitimately be a row count, not a
    time offset. Acceptable as advisory: false positives are surfaced as
    WARNING, not errors.
    """
    if not isinstance(node, ast.BinOp):
        return False
    if not isinstance(node.op, ast.Add):
        return False
    # Right side must be a positive int literal (or wrap one).
    rhs = _literal_int(node.right)
    if rhs is None:
        return False
    return rhs > 0


def scan_callable(
    func: Callable[..., Any],
    log_warnings: bool = True,
) -> List[LeakageWarning]:
    """Scan a Python callable's source for leakage patterns.

    Works on plain functions and ``Feature`` instances (the Foundry
    decorator stores the original function as ``.func``). On built-ins
    or C-implemented callables where source is unavailable, returns an
    empty list and logs at INFO (not a problem worth a WARNING).
    """
    target = getattr(func, "func", func)  # unwrap Feature.func
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError) as exc:
        logger.info(
            "leakage_detector: source unavailable for %r: %s",
            getattr(target, "__name__", target), exc,
        )
        return []
    # ``inspect.getsource`` returns the function with its original
    # indentation, which fails ``ast.parse`` for nested defs. Dedent.
    source = textwrap.dedent(source)
    filename = inspect.getfile(target) if not _is_lambda(target) else "<lambda>"
    return scan_source(source, filename=filename, log_warnings=log_warnings)


def _is_lambda(func: Any) -> bool:
    return getattr(func, "__name__", "") == "<lambda>"
