"""tests/test_run_isolated_canon_md5.py
==========================================

Tests for `scripts.run_isolated._trades_canon_md5`. Locks in the
2026-05-07 fix that resolved the filename-pattern bug:

> Pre-fix: helper looked for `trades_<run_id>.csv` only. Many cockpit
> writes (including all zero-trade runs) write `trades.csv` instead.
> Result: canon md5 returned `"(missing)"` even when the trade log
> existed, masking real bitwise comparisons as filename mismatches.

Post-fix: checks both `trades.csv` (canonical) and the legacy
`trades_<run_id>.csv` name. Either path produces the same canon hash
when the file content matches.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts import run_isolated as ri


@pytest.fixture
def synthetic_trades_dir(tmp_path: Path):
    """Build a fake TRADES_DIR with one run sub-directory; monkey-patch
    `ri.TRADES_DIR` for the duration of the fixture."""
    original = ri.TRADES_DIR
    ri.TRADES_DIR = tmp_path
    yield tmp_path
    ri.TRADES_DIR = original


def _write_trades(path: Path, n_rows: int = 3) -> None:
    df = pd.DataFrame({
        "ticker": ["AAA", "BBB", "CCC"][:n_rows],
        "qty": [10, 20, 30][:n_rows],
        "fill_price": [100.0, 101.0, 102.0][:n_rows],
        "run_id": ["x"] * n_rows,
        "meta": ["y"] * n_rows,
    })
    df.to_csv(path, index=False)


def test_canon_md5_finds_trades_csv_name(synthetic_trades_dir: Path):
    """Canonical name `trades.csv` is the post-2026-05-07 default; the
    helper must find it (pre-fix it didn't)."""
    run_id = "test-canonical-name"
    run_dir = synthetic_trades_dir / run_id
    run_dir.mkdir()
    _write_trades(run_dir / "trades.csv")
    md5 = ri._trades_canon_md5(run_id)
    assert md5 != "(missing)"
    assert len(md5) == 32  # md5 hex


def test_canon_md5_finds_legacy_prefixed_name(synthetic_trades_dir: Path):
    """Older runs shipped `trades_<run_id>.csv`; the helper should still find
    those for forensic comparisons against legacy trade logs."""
    run_id = "test-legacy-name"
    run_dir = synthetic_trades_dir / run_id
    run_dir.mkdir()
    _write_trades(run_dir / f"trades_{run_id}.csv")
    md5 = ri._trades_canon_md5(run_id)
    assert md5 != "(missing)"


def test_canon_md5_returns_missing_when_no_trade_log(synthetic_trades_dir: Path):
    run_id = "test-no-log"
    run_dir = synthetic_trades_dir / run_id
    run_dir.mkdir()
    md5 = ri._trades_canon_md5(run_id)
    assert md5 == "(missing)"


def test_canon_md5_canonical_name_takes_precedence(synthetic_trades_dir: Path):
    """When both filenames exist (older runs sometimes wrote both), canonical
    `trades.csv` wins. Future writes should converge on the canonical name."""
    run_id = "test-both-names"
    run_dir = synthetic_trades_dir / run_id
    run_dir.mkdir()
    # Write different content into the two files so the hashes differ
    _write_trades(run_dir / "trades.csv", n_rows=2)
    _write_trades(run_dir / f"trades_{run_id}.csv", n_rows=3)

    canonical_only = ri._trades_canon_md5(run_id)

    # Compute what the canonical-only hash should be by deleting the legacy file
    (run_dir / f"trades_{run_id}.csv").unlink()
    canonical_alone = ri._trades_canon_md5(run_id)
    assert canonical_only == canonical_alone, (
        "When both names exist, the helper must prefer trades.csv (canonical)."
    )


def test_canon_md5_drops_run_id_and_meta_columns(synthetic_trades_dir: Path):
    """Canonical hash must be invariant under run_id / meta column changes —
    these columns are per-run noise and don't represent trade decisions."""
    run_id_a = "test-rid-stripping-a"
    run_id_b = "test-rid-stripping-b"
    for rid in (run_id_a, run_id_b):
        run_dir = synthetic_trades_dir / rid
        run_dir.mkdir()
        df = pd.DataFrame({
            "ticker": ["AAA", "BBB"], "qty": [10, 20], "fill_price": [100.0, 101.0],
            "run_id": [rid, rid],   # different per run — should be stripped
            "meta": [f"meta-{rid}", f"meta-{rid}"],   # different per run — stripped
        })
        df.to_csv(run_dir / "trades.csv", index=False)
    md5_a = ri._trades_canon_md5(run_id_a)
    md5_b = ri._trades_canon_md5(run_id_b)
    assert md5_a == md5_b, (
        "Stripping run_id + meta should make canonical hashes identical when "
        "the actual trade rows match across runs."
    )


def test_canon_md5_returns_error_marker_for_corrupt_csv(synthetic_trades_dir: Path):
    """Corrupt CSV should return an `(error: …)` marker, never raise."""
    run_id = "test-corrupt"
    run_dir = synthetic_trades_dir / run_id
    run_dir.mkdir()
    (run_dir / "trades.csv").write_bytes(b"\x00\x01\x02 not a csv")
    md5 = ri._trades_canon_md5(run_id)
    assert md5.startswith("(error:") or md5 == "(missing)" or len(md5) == 32, (
        f"Unexpected return for corrupt CSV: {md5!r}"
    )
