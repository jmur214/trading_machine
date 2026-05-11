"""
engines/engine_d_discovery/gate1_signal_cache.py
================================================

Gate 1 signal-collector caching (T-2026-05-11-023).

Per-cycle in-memory cache for the baseline ensemble's per-edge
`compute_signals(data_map, now)` outputs, used by
`DiscoveryEngine.validate_candidate`'s Gate 1.

Mechanism (Option 1 from the brief):
- Wrap each baseline edge in a `CachedEdgeWrapper`.
- The wrapper delegates `compute_signals(data_map, now)` to the wrapped
  edge ONCE per distinct `now` timestamp, then memoizes the returned
  `Dict[ticker, score]` for all subsequent calls with the same `now`.
- Wrappers persist across candidates within a Discovery cycle (held on
  `DiscoveryEngine` instance state, reset between cycles).
- The candidate edge itself is NEVER wrapped — its `compute_signals`
  runs fresh on every call because each candidate is a new edge.

Speedup: each candidate's "with-candidate" backtest iterates over the
same trading dates that the baseline ensemble already touched. Without
caching, each candidate redo's the baseline edges' compute (6× per bar
+ 1× candidate compute). With caching, baseline edges return from
memory (6× cache lookups) and only the candidate computes fresh
(1× per bar).

Determinism guard: the wrapper returns a fresh shallow copy of the
cached `Dict[ticker, score]` on every call, so downstream code cannot
mutate the cached result and contaminate a subsequent call. The
underlying compute is deterministic by construction (edges are pure
functions of (data_map, now, params) per the `EdgeBase.compute_signals`
contract).

Invalidation: the cache is per-`DiscoveryEngine` instance. When
`mode_controller.run_backtest` creates a fresh `DiscoveryEngine` per
Discovery cycle (or `clear()` is called explicitly), the cache is
reset. Cross-cycle reuse is intentionally NOT supported — different
cycles may have different universes, windows, or active-edge sets,
each of which would silently invalidate cached signals.

This module touches nothing outside engine_d_discovery. No changes
to Engine A, B, C, mode_controller, or backtest_controller.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Hashable, Optional

import pandas as pd

logger = logging.getLogger("Gate1SignalCache")


_PROGRAMMER_ERRORS = (TypeError, AttributeError, NameError, AssertionError, ImportError)


class CachedEdgeWrapper:
    """Memoizing wrapper around an EdgeBase-shaped object.

    Exposes the same `compute_signals(data_map, now) -> Dict[ticker, float]`
    contract that `SignalCollector` expects. Caches results by `now`
    timestamp; the wrapper is single-edge, single-cycle (same wrapper
    instance reused across all candidates in one Discovery cycle).

    Limitations (intentional, per scope discipline):
    - Does NOT cache across `data_map` changes. If the underlying
      data_map mutates between calls, the cache becomes stale. Within
      a single Discovery cycle, data_map is constant by convention
      (loaded once by `mode_controller.run_backtest`'s `--discover`
      path and passed by reference). Cycle-end clears the cache.
    - Does NOT cache `generate_signals` or `generate` fallback method
      names — only `compute_signals`. The other two fallbacks in
      `SignalCollector._call_edge` are legacy; modern edges use
      `compute_signals` exclusively.
    - Does NOT mutate the wrapped edge's internal state. The
      wrapper's `__getattr__` proxies attribute access for everything
      else (params, EDGE_ID, etc.) so consumers that introspect the
      edge still see the underlying object.
    """

    __slots__ = ("_wrapped", "_cache", "_edge_id", "_hits", "_misses")

    def __init__(self, wrapped_edge: Any, edge_id: str) -> None:
        self._wrapped = wrapped_edge
        self._cache: Dict[Hashable, Dict[str, float]] = {}
        self._edge_id = edge_id
        self._hits = 0
        self._misses = 0

    @property
    def edge_id(self) -> str:
        return self._edge_id

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    def __getattr__(self, name: str) -> Any:
        # Proxy attribute access to the wrapped edge for everything
        # other than the wrapper's own slots. This keeps the wrapper
        # transparent to code that introspects the edge (EDGE_ID,
        # CATEGORY, params, set_params, etc.). Note __getattr__ is
        # only called when standard lookup fails, so __slots__ and
        # @property attrs above take precedence.
        return getattr(self._wrapped, name)

    @staticmethod
    def _key_for(now: Any) -> Hashable:
        """Cache key for a `now` argument.

        BacktestController passes a `pd.Timestamp` for every bar.
        Cast to `pd.Timestamp` (hashable + comparable) and return.
        Falls back to `str(now)` for unusual call sites.
        """
        if isinstance(now, pd.Timestamp):
            return now
        try:
            return pd.Timestamp(now)
        except Exception:
            return str(now)

    def compute_signals(
        self, data_map: Dict[str, pd.DataFrame], now: Any,
    ) -> Dict[str, float]:
        """Delegated + memoized version of the wrapped edge's
        `compute_signals`. Hits return a shallow copy of the cached
        dict so downstream mutation cannot poison the cache.
        """
        key = self._key_for(now)
        cached = self._cache.get(key)
        if cached is not None:
            self._hits += 1
            # Shallow copy: cached dict's values are floats (immutable),
            # so .copy() is sufficient. Downstream cannot mutate floats.
            return dict(cached)

        self._misses += 1
        try:
            result = self._wrapped.compute_signals(data_map, now)
        except _PROGRAMMER_ERRORS:
            raise
        except Exception as e:
            logger.warning(
                "[%s] compute_signals failed at %s: %s: %s",
                self._edge_id, now, type(e).__name__, e,
            )
            result = {}
        if not isinstance(result, dict):
            result = dict(result or {})
        # Store a defensive copy so a downstream mutation never
        # changes future cached returns.
        self._cache[key] = dict(result)
        return dict(result)

    def cache_stats(self) -> Dict[str, int]:
        return {
            "edge_id": self._edge_id,
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
        }


class Gate1SignalCache:
    """Per-cycle registry of `CachedEdgeWrapper`s keyed by edge_id.

    `validate_candidate` calls `wrap_edges(baseline_edges)` at the top
    of each candidate's run; the same wrapper instances are returned
    across candidates within one Discovery cycle, so the cache
    populated during candidate 1's baseline backtest is reused by
    candidates 2..N.

    Invalidation:
    - `clear()` drops all wrappers. Call between cycles.
    - `invalidate_on_universe_change(...)` and
      `invalidate_on_window_change(...)` are explicit invalidation
      hooks the orchestrator can call when scope changes. They both
      simply call `clear()` — the semantics is "any change invalidates
      everything." Keeping them as separate methods makes call-site
      intent explicit and supports finer-grained invalidation later
      without API breakage.
    """

    def __init__(self) -> None:
        self._wrappers: Dict[str, CachedEdgeWrapper] = {}
        self._fingerprint: Optional[str] = None

    def wrap_edges(
        self, edges: Dict[str, Any], *, fingerprint: Optional[str] = None,
    ) -> Dict[str, CachedEdgeWrapper]:
        """Return wrapped versions of the supplied edges.

        Edges already in the cache return the existing wrapper (so its
        memoization persists across candidates). New edges get a fresh
        wrapper. Wrappers whose edge_id is NOT in the new `edges` dict
        are NOT removed — keeping them is harmless and supports
        candidate sets that include an edge in some cycles but not
        others.

        `fingerprint`: optional caller-supplied tag (universe + window
        + ensemble hash). If supplied and DIFFERENT from the previously
        seen fingerprint, the cache auto-clears before re-wrapping.
        This is the primary invalidation hook for cross-cycle reuse;
        with the per-cycle DiscoveryEngine lifecycle, it's a belt-and-
        suspenders guard.
        """
        if fingerprint is not None and self._fingerprint is not None:
            if fingerprint != self._fingerprint:
                logger.info(
                    "Gate1SignalCache: fingerprint changed (%s -> %s); clearing.",
                    self._fingerprint, fingerprint,
                )
                self.clear()
        self._fingerprint = fingerprint

        out: Dict[str, CachedEdgeWrapper] = {}
        for eid, edge in edges.items():
            if isinstance(edge, CachedEdgeWrapper):
                # Idempotent: passing in already-wrapped edges returns
                # the same wrapper (don't double-wrap).
                out[eid] = edge
                self._wrappers.setdefault(eid, edge)
                continue
            existing = self._wrappers.get(eid)
            if existing is None:
                existing = CachedEdgeWrapper(edge, edge_id=eid)
                self._wrappers[eid] = existing
            elif existing._wrapped is not edge:
                # Same edge_id but a different underlying instance.
                # Safest interpretation: caller rebuilt the edge (params
                # changed, registry reload, etc.). Drop the old wrapper
                # to avoid serving stale results.
                logger.info(
                    "Gate1SignalCache: edge %s underlying instance changed; "
                    "evicting cached wrapper.", eid,
                )
                existing = CachedEdgeWrapper(edge, edge_id=eid)
                self._wrappers[eid] = existing
            out[eid] = existing
        return out

    def clear(self) -> None:
        self._wrappers.clear()
        self._fingerprint = None

    def invalidate_on_universe_change(self) -> None:
        self.clear()

    def invalidate_on_window_change(self) -> None:
        self.clear()

    def __len__(self) -> int:
        return len(self._wrappers)

    def stats(self) -> Dict[str, Any]:
        return {
            "n_wrappers": len(self._wrappers),
            "fingerprint": self._fingerprint,
            "per_edge": {eid: w.cache_stats() for eid, w in self._wrappers.items()},
        }


__all__ = ["CachedEdgeWrapper", "Gate1SignalCache"]
