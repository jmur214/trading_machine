"""Tests for `core.observability.leakage_detector`.

Coverage targets:
- Negative-shift catches `df['close'].shift(-1)` and `shift(-3)`
- Forward-return catches the divide-and-subtract idiom
- Unsafe-resample catches `.resample('D').last()` without left-closed kwargs
- Future-index-slice catches `df.loc[t + 1:]`
- Clean feature passes silently
- `scan_callable` works on a real function (decorated and plain)
- Syntax error in source returns [] without raising
- Decorator integration: a leaky @feature still registers (advisory)
"""
from __future__ import annotations

import logging
import os
import sys
import textwrap
from datetime import date
from pathlib import Path
from typing import Optional

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.observability.leakage_detector import (
    LeakagePattern,
    LeakageWarning,
    scan_callable,
    scan_source,
)


# ---------------------------------------------------------------------------
# Pattern detection — synthetic source
# ---------------------------------------------------------------------------


def test_negative_shift_is_flagged() -> None:
    src = textwrap.dedent("""\
        def feat(ticker, dt):
            import pandas as pd
            df = pd.DataFrame({'close': [1, 2, 3]})
            return df['close'].shift(-1).iloc[-1]
    """)
    warnings = scan_source(src, log_warnings=False)
    patterns = [w.pattern for w in warnings]
    assert LeakagePattern.NEGATIVE_SHIFT in patterns


def test_positive_shift_is_clean() -> None:
    src = textwrap.dedent("""\
        def feat(ticker, dt):
            import pandas as pd
            df = pd.DataFrame({'close': [1, 2, 3]})
            return df['close'].shift(1).iloc[-1]
    """)
    warnings = scan_source(src, log_warnings=False)
    assert not any(w.pattern == LeakagePattern.NEGATIVE_SHIFT for w in warnings)


def test_zero_shift_is_clean() -> None:
    src = "df['close'].shift(0)"
    warnings = scan_source(src, log_warnings=False)
    assert not any(w.pattern == LeakagePattern.NEGATIVE_SHIFT for w in warnings)


def test_forward_return_pattern_is_flagged() -> None:
    src = textwrap.dedent("""\
        def fwd_ret(ticker, dt):
            import pandas as pd
            df = pd.DataFrame({'close': [1, 2, 3]})
            return df['close'].shift(-1) / df['close'] - 1
    """)
    warnings = scan_source(src, log_warnings=False)
    patterns = [w.pattern for w in warnings]
    # We expect both a NEGATIVE_SHIFT and a FORWARD_RETURN
    assert LeakagePattern.FORWARD_RETURN in patterns
    assert LeakagePattern.NEGATIVE_SHIFT in patterns


def test_unsafe_resample_last_is_flagged() -> None:
    src = textwrap.dedent("""\
        def feat(ticker, dt):
            import pandas as pd
            df = pd.DataFrame()
            return df.resample('D').last()
    """)
    warnings = scan_source(src, log_warnings=False)
    assert any(w.pattern == LeakagePattern.UNSAFE_RESAMPLE for w in warnings)


def test_safe_resample_with_both_kwargs_is_clean() -> None:
    src = textwrap.dedent("""\
        def feat(ticker, dt):
            import pandas as pd
            df = pd.DataFrame()
            return df.resample('D', closed='left', label='left').last()
    """)
    warnings = scan_source(src, log_warnings=False)
    assert not any(w.pattern == LeakagePattern.UNSAFE_RESAMPLE for w in warnings)


def test_resample_with_only_closed_left_still_flagged() -> None:
    """closed='left' alone is not enough — label defaults to right."""
    src = textwrap.dedent("""\
        def feat(ticker, dt):
            return df.resample('D', closed='left').last()
    """)
    warnings = scan_source(src, log_warnings=False)
    assert any(w.pattern == LeakagePattern.UNSAFE_RESAMPLE for w in warnings)


def test_future_index_slice_is_flagged() -> None:
    src = textwrap.dedent("""\
        def feat(ticker, dt):
            return df.loc[t + 1:]
    """)
    warnings = scan_source(src, log_warnings=False)
    assert any(w.pattern == LeakagePattern.FUTURE_INDEX_SLICE for w in warnings)


def test_clean_feature_emits_no_warnings() -> None:
    """A reasonable backward-looking feature must not trigger anything."""
    src = textwrap.dedent("""\
        def momentum_12_1(ticker, dt):
            import pandas as pd
            df = pd.DataFrame({'close': [1, 2, 3, 4]})
            twelve = df['close'].shift(252)
            one = df['close'].shift(21)
            return (one / twelve - 1)
    """)
    warnings = scan_source(src, log_warnings=False)
    assert warnings == []


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_syntax_error_returns_empty_list(caplog) -> None:
    """Bad source must not raise — detector is advisory."""
    with caplog.at_level("WARNING"):
        warnings = scan_source("def feat(:::", log_warnings=False)
    assert warnings == []
    assert any("cannot parse" in r.message for r in caplog.records)


def test_warning_format_is_human_readable() -> None:
    src = "df['close'].shift(-2)"
    warnings = scan_source(src, log_warnings=False, filename="my.py")
    assert len(warnings) == 1
    formatted = warnings[0].format()
    assert "my.py" in formatted
    assert "negative_shift" in formatted
    assert "shift(-2)" in formatted or "snippet" in formatted


def test_log_warnings_emits_at_warning_level(caplog) -> None:
    src = "df['close'].shift(-1)"
    with caplog.at_level(logging.WARNING, logger="core.observability.leakage_detector"):
        scan_source(src, log_warnings=True)
    records = [
        r for r in caplog.records
        if r.name == "core.observability.leakage_detector"
    ]
    assert any(r.levelno == logging.WARNING for r in records)


# ---------------------------------------------------------------------------
# scan_callable on real functions
# ---------------------------------------------------------------------------


def _leaky_func(ticker: str, dt: date) -> Optional[float]:
    """A function with an obvious leak — used by scan_callable test."""
    import pandas as pd
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
    return float(df["close"].shift(-1).iloc[-1])


def _clean_func(ticker: str, dt: date) -> Optional[float]:
    import pandas as pd
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
    return float(df["close"].shift(1).iloc[-1])


def test_scan_callable_flags_leaky_function() -> None:
    warnings = scan_callable(_leaky_func, log_warnings=False)
    assert any(w.pattern == LeakagePattern.NEGATIVE_SHIFT for w in warnings)


def test_scan_callable_passes_clean_function() -> None:
    warnings = scan_callable(_clean_func, log_warnings=False)
    assert not any(w.pattern == LeakagePattern.NEGATIVE_SHIFT for w in warnings)


# ---------------------------------------------------------------------------
# Decorator integration — a leaky @feature still registers
# ---------------------------------------------------------------------------


def test_decorator_registers_leaky_feature_with_warning(caplog) -> None:
    """The detector is ADVISORY this round: registration must succeed
    even when the feature contains a leak. Warnings are logged.
    """
    from core.feature_foundry import feature, get_feature_registry

    registry = get_feature_registry()
    fid = "test_leaky_feature_for_advisory_unit_test"
    # Clean any prior registration from a previous run
    if registry.get(fid) is not None:
        registry.clear()

    with caplog.at_level(logging.WARNING):
        @feature(
            feature_id=fid,
            tier="B",
            horizon=1,
            license="public",
            source="synthetic",
        )
        def my_leaky(ticker: str, dt: date) -> Optional[float]:
            import pandas as pd
            df = pd.DataFrame({"close": [1.0, 2.0]})
            return float(df["close"].shift(-1).iloc[-1])

    assert registry.get(fid) is not None, "Feature must register despite leak"
    # Warning should mention the feature_id
    foundry_warns = [
        r for r in caplog.records
        if r.name == "core.feature_foundry.feature"
        and r.levelno == logging.WARNING
    ]
    assert any(fid in r.message for r in foundry_warns)
    # Cleanup
    registry.clear()
