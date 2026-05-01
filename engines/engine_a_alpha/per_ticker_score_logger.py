"""engines/engine_a_alpha/per_ticker_score_logger.py
======================================================
Phase 2.11 prep: per-bar per-ticker per-edge score capture.

The per-ticker meta-learner (Phase 2.11 proper) needs training data
that doesn't exist in the current backtester. Trade logs only record
fills — they don't say "edge X scored +0.42 on AAPL on 2024-03-15
but didn't fire." For per-ticker meta-learner training we need every
edge's score on every ticker on every bar, so the model can learn
ticker-specific weighting from the full signal/no-signal distribution.

Schema (one row per (timestamp, ticker, edge) where the edge produced
a score for that ticker that bar):

  timestamp        : datetime64[ns]
  ticker           : string
  edge_id          : string
  raw_score        : float64    raw output from edge.compute_signals
  norm_score       : float64    normalized [-1, 1] post-signal-processor
  weight           : float64    edge weight at this bar (post regime_gate /
                                 soft-pause / governor multipliers, as
                                 applied by SignalProcessor)
  aggregate_score  : float64    final per-ticker aggregate score that
                                 flows into formatter.to_side_and_strength
  regime_summary   : string     advisory regime_summary (e.g. "benign",
                                 "stressed", "crisis"), best-effort from
                                 regime_meta if present
  fired            : bool       did this edge appear in the per-ticker
                                 signal's edges_triggered list this bar
                                 (i.e. did its weighted contribution
                                 clear cfg.min_edge_contribution)

Output: parquet at `data/research/per_ticker_scores/{run_uuid}.parquet`.

Sizing: a 1-year backtest on 100 tickers × 17 edges × 252 bars =
~430k rows. Memory budget at ~120 bytes/row is under 60 MB — safe to
buffer in-memory and flush once at run end.

Design principles:
- **Optional and off by default.** AlphaEngine constructs the logger
  lazily; without the CLI flag, no logger is created and there's zero
  cost on the hot path.
- **Defensive append.** log_bar is wrapped so a malformed proc dict
  doesn't crash the backtest — losing a bar of training data is
  preferable to losing a backtest run.
- **Pure data layer.** This module does NOT import any backtester or
  governor code. It only consumes the proc dict shape that
  AlphaEngine.generate_signals already computes.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

log = logging.getLogger("PerTickerScoreLogger")


SCHEMA_COLUMNS: List[str] = [
    "timestamp",
    "ticker",
    "edge_id",
    "raw_score",
    "norm_score",
    "weight",
    "aggregate_score",
    "regime_summary",
    "fired",
]


def _resolve_regime_summary(regime_meta: Optional[Dict[str, Any]]) -> str:
    """Best-effort extraction of regime_summary from a regime_meta dict.

    Real backtests pass a regime_meta with `advisory.regime_summary`
    populated by Engine E. Synthetic / fallback paths may pass the
    minimal dict in alpha_engine.generate_signals which has no advisory
    block; we return a sensible default in that case rather than failing.
    """
    if not isinstance(regime_meta, dict):
        return "unknown"
    advisory = regime_meta.get("advisory")
    if isinstance(advisory, dict):
        rs = advisory.get("regime_summary")
        if isinstance(rs, str) and rs:
            return rs
    # Fallback: top-level "regime" or compose from trend+volatility
    rs = regime_meta.get("regime")
    if isinstance(rs, str) and rs:
        return rs
    return "unknown"


_EDGE_ID_VERSION_SUFFIX = re.compile(r"_v\d+$")


def _resolve_edge_id(edge_detail: Dict[str, Any]) -> str:
    """Resolve a stable edge_id from a SignalProcessor edges_detail item.

    Modern path: `edge_id` is set explicitly → use it verbatim.

    Legacy / fallback path: only `edge` is set. SignalProcessor populates
    `edge` from the registry key (e.g. `momentum_edge_v1`), so it usually
    already carries the `_v1` version suffix and IS the canonical edge_id.
    Some older paths pass the bare module name (e.g. `momentum_edge`); for
    those we synthesize the `_v1`. The regex check prevents the
    double-suffix bug seen in the first smoke run (`momentum_edge_v1_v1`).
    """
    eid = edge_detail.get("edge_id")
    if isinstance(eid, str) and eid:
        return eid
    name = edge_detail.get("edge")
    if isinstance(name, str) and name:
        if _EDGE_ID_VERSION_SUFFIX.search(name):
            return name
        return f"{name}_v1"
    return "unknown_edge_v1"


class PerTickerScoreLogger:
    """Buffers per-bar score rows in memory and flushes a parquet at run end.

    Construction:
        logger = PerTickerScoreLogger(
            run_uuid="abc123...",
            out_dir=Path("data/research/per_ticker_scores"),
        )

    Usage:
        # Inside AlphaEngine.generate_signals after `proc` is computed:
        logger.log_bar(timestamp=now, proc=proc, signals=signals,
                       regime_meta=regime_meta)

    Flush:
        logger.flush()  # writes <out_dir>/<run_uuid>.parquet

    The logger never raises through the public API. Bar-level failures
    are logged as warnings; flush failures fall back to CSV so training
    data isn't lost.
    """

    def __init__(
        self,
        run_uuid: str,
        out_dir: Path | str = "data/research/per_ticker_scores",
    ) -> None:
        self.run_uuid: str = str(run_uuid) if run_uuid else "unknown_run"
        self.out_dir: Path = Path(out_dir)
        self._rows: List[Dict[str, Any]] = []

    # ----------------------------- public API ----------------------------- #

    def log_bar(
        self,
        timestamp: pd.Timestamp,
        proc: Dict[str, Dict[str, Any]],
        signals: Optional[List[Dict[str, Any]]] = None,
        regime_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append rows for one bar.

        Parameters
        ----------
        timestamp : pd.Timestamp
            The bar's timestamp (i.e. AlphaEngine.generate_signals' `now`).
        proc : dict
            SignalProcessor output: ticker -> {aggregate_score, regimes,
            edges_detail: [{edge, raw, norm, weight, ...}]}.
        signals : list[dict] or None
            The list of signals AlphaEngine emitted this bar — used to
            compute the `fired` flag. Can be passed BEFORE downstream
            cooldown / fill-share-cap mutations as long as it carries
            `meta.edges_triggered` per ticker.
        regime_meta : dict or None
            The same regime_meta passed to generate_signals (top-level
            advisory dict from Engine E, or fallback skeleton).
        """
        if not isinstance(proc, dict) or not proc:
            return

        try:
            regime_summary = _resolve_regime_summary(regime_meta)

            # Build per-ticker fired-edge map from signals once per bar.
            # Use edge_id if present, else fall back to edge name.
            fired_by_ticker: Dict[str, set] = {}
            if signals:
                for sig in signals:
                    if not isinstance(sig, dict):
                        continue
                    ticker = sig.get("ticker")
                    if not isinstance(ticker, str):
                        continue
                    triggered = (
                        sig.get("meta", {}).get("edges_triggered", [])
                        if isinstance(sig.get("meta"), dict) else []
                    )
                    fired_set: set = set()
                    for tr in triggered:
                        if not isinstance(tr, dict):
                            continue
                        eid = tr.get("edge_id") or tr.get("edge")
                        if isinstance(eid, str) and eid:
                            fired_set.add(eid)
                            # Also tag the bare edge name so per-edge dicts
                            # without explicit edge_id still match.
                            if "_v" not in eid:
                                fired_set.add(f"{eid}_v1")
                    fired_by_ticker[ticker] = fired_set

            ts = pd.Timestamp(timestamp)

            for ticker, info in proc.items():
                if not isinstance(info, dict):
                    continue
                edges_detail = info.get("edges_detail")
                if not isinstance(edges_detail, list):
                    continue
                aggregate_score = float(info.get("aggregate_score", 0.0) or 0.0)
                fired_set = fired_by_ticker.get(ticker, set())

                for ed in edges_detail:
                    if not isinstance(ed, dict):
                        continue
                    edge_id = _resolve_edge_id(ed)
                    name = ed.get("edge")
                    fired = (
                        edge_id in fired_set
                        or (isinstance(name, str) and name in fired_set)
                    )
                    self._rows.append({
                        "timestamp": ts,
                        "ticker": str(ticker),
                        "edge_id": edge_id,
                        "raw_score": float(ed.get("raw", 0.0) or 0.0),
                        "norm_score": float(ed.get("norm", 0.0) or 0.0),
                        "weight": float(ed.get("weight", 0.0) or 0.0),
                        "aggregate_score": aggregate_score,
                        "regime_summary": regime_summary,
                        "fired": bool(fired),
                    })
        except Exception as exc:
            log.warning(
                "[PerTickerScoreLogger] log_bar failed silently for "
                f"timestamp={timestamp!r}: {exc}"
            )

    def n_rows(self) -> int:
        """Current buffered row count — useful for tests + smoke checks."""
        return len(self._rows)

    def flush(self) -> Optional[Path]:
        """Write the buffer to parquet at <out_dir>/<run_uuid>.parquet.

        Returns the output path on success, None if nothing was written
        (empty buffer). Falls back to CSV if parquet engine missing.
        """
        if not self._rows:
            log.info("[PerTickerScoreLogger] flush() called with empty buffer")
            return None

        df = pd.DataFrame(self._rows, columns=SCHEMA_COLUMNS)
        # Stable schema regardless of buffer-row dict ordering
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])
        df["ticker"] = df["ticker"].astype("string")
        df["edge_id"] = df["edge_id"].astype("string")
        df["regime_summary"] = df["regime_summary"].astype("string")
        df["fired"] = df["fired"].astype(bool)
        for c in ("raw_score", "norm_score", "weight", "aggregate_score"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")

        self.out_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.out_dir / f"{self.run_uuid}.parquet"
        try:
            df.to_parquet(out_path, index=False)
            log.info(
                f"[PerTickerScoreLogger] wrote {len(df):,} rows → {out_path}"
            )
            return out_path
        except Exception as exc:
            # Fall back to CSV — never lose training data because the
            # parquet engine isn't installed.
            csv_path = out_path.with_suffix(".csv")
            try:
                df.to_csv(csv_path, index=False)
                log.warning(
                    f"[PerTickerScoreLogger] parquet write failed ({exc}); "
                    f"wrote {len(df):,} rows → {csv_path} as fallback"
                )
                return csv_path
            except Exception as exc2:
                log.error(
                    f"[PerTickerScoreLogger] flush failed completely: "
                    f"parquet={exc} csv={exc2}"
                )
                return None


__all__ = ["PerTickerScoreLogger", "SCHEMA_COLUMNS"]
