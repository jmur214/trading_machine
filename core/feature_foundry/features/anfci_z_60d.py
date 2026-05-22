"""anfci_z_60d — ANFCI z-score against trailing 60-day window.

For date `dt`, compute `(ANFCI(t) - mean_60d) / std_60d`. The Chicago
Fed's Adjusted National Financial Conditions Index aggregates 105
weekly financial-conditions measures into a single index. Negative
values = easier-than-average conditions; positive = tighter-than-
average.

The 60-day z-score (~12 weeks of weekly publication carried forward
to daily bars) captures the SHIFT in conditions rather than the level
— more actionable for regime detection per the T-052 research
ensemble.

**FRED current-vintage look-ahead caveat** (per T-052 brief open
question #2 + 4 research dives' concurrence): the FRED API serves the
CURRENT-VINTAGE value of ANFCI for each historical date, which
incorporates revisions made AFTER that date. Strictly point-in-time
analysis requires ALFRED (the archival FRED variant) which stores the
revision-time vintage. This feature uses current-vintage with an
EXPLICIT CAVEAT — known as the FRED current-vintage bias. The
ALFRED migration is candidate T-047 / T-048 (separate workstream).

Data source: FRED weekly series ANFCI. **NOT YET in the project's
macro cache** as of T-052 ship — feature returns None until the FRED
backfill is run (see `scripts/backfill_t052_macro_data.py`).

Returns None when ANFCI is missing or fewer than 60 trailing values
are available.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import numpy as np

from ..feature import feature
from ..sources.fred_macro import series

logger = logging.getLogger(__name__)


_ANFCI_MISSING_LOGGED = False


def _log_missing_once() -> None:
    """ANFCI missing-from-cache warning emitted at most once per process.
    Documents the FRED-current-vintage caveat to surface the look-ahead-
    bias warning to anyone running Discovery."""
    global _ANFCI_MISSING_LOGGED
    if _ANFCI_MISSING_LOGGED:
        return
    _ANFCI_MISSING_LOGGED = True
    logger.warning(
        "[FOUNDRY] anfci_z_60d: FRED series 'ANFCI' not in "
        "data/macro/ANFCI.parquet — run scripts/backfill_t052_macro_data.py "
        "to populate. CAVEAT: FRED current-vintage values incorporate "
        "post-publication revisions; ALFRED migration (T-047 candidate) "
        "is the correct point-in-time fix."
    )


@feature(
    feature_id="anfci_z_60d",
    tier="A",
    horizon=21,
    license="public",
    source="fred_macro",
    description=(
        "60-day z-score of ANFCI (Chicago Fed's Adjusted National "
        "Financial Conditions Index). Weekly publication carry-forward "
        "to daily bars. T-052 ensemble. CAVEAT: FRED current-vintage "
        "bias — ALFRED migration candidate."
    ),
)
def anfci_z_60d(ticker: str, dt: date) -> Optional[float]:
    s = series("ANFCI")
    if s is None or s.empty:
        _log_missing_once()
        return None
    s = s[s.index <= dt]
    if len(s) < 60:
        return None
    window = s.iloc[-60:].astype(float).values
    mean = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    if std <= 0:
        return None
    v_now = float(window[-1])
    return (v_now - mean) / std
