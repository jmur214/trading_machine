"""tests/test_anchor_no_stale_composites.py
=============================================
Regression test for T-2026-05-12-037 anchor cleanup.

The B-worktree's OLD anchor `data/governor/_isolated_anchor/edges.yml`
(md5 `818330dc05e5e58804fa5cace7973640`) was found in T-026 to contain
74 stale `composite_gen0_*` / `composite_gen1_*` specs at
status='candidate'/'failed'/'error'. These pre-empted Discovery's GA
`seed_from_foundry` path because `seed_from_registry` found them in
the restored registry first.

T-037 archived those 74 specs to `edges_archive_pre_t037.yml` and
removed them from the live anchor. This test pins the cleaned state
so a future hand-edit or `--save-anchor` against a contaminated tree
fails loudly here instead of silently re-introducing the bug class.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ANCHOR = (
    Path(__file__).resolve().parents[1]
    / "data" / "governor" / "_isolated_anchor" / "edges.yml"
)

STALE_STATUSES = frozenset({"candidate", "failed", "error"})
COMPOSITE_PATTERN = re.compile(r"^composite_gen\d+_")


def _load_anchor_edges():
    if not ANCHOR.exists():
        pytest.skip(f"Anchor file not present at {ANCHOR}")
    payload = yaml.safe_load(ANCHOR.read_text()) or {}
    return payload.get("edges", []) or []


def test_anchor_has_no_stale_composite_candidates():
    """The anchor must not contain `composite_gen*` specs at
    `status='candidate'`. These survive across `isolated()` restores
    and pre-empt GA seed-from-foundry (the T-026 BLOCK root cause)."""
    edges = _load_anchor_edges()
    stale = [
        e for e in edges
        if COMPOSITE_PATTERN.match(e.get("edge_id", ""))
        and e.get("status") == "candidate"
    ]
    assert not stale, (
        f"Anchor regression: {len(stale)} composite specs at "
        f"status='candidate' detected. Examples: "
        f"{[e['edge_id'] for e in stale[:5]]}. Archive them via the "
        f"T-037 cleanup helper and re-save the anchor before merging."
    )


def test_anchor_has_no_stale_composite_failed_or_errored():
    """Same regression guard for status='failed' and 'error' —
    Discovery's GA path doesn't distinguish them from candidates when
    seeding population.
    """
    edges = _load_anchor_edges()
    stale = [
        e for e in edges
        if COMPOSITE_PATTERN.match(e.get("edge_id", ""))
        and e.get("status") in {"failed", "error"}
    ]
    assert not stale, (
        f"Anchor regression: {len(stale)} composite specs at "
        f"status in {{failed, error}} detected. Examples: "
        f"{[e['edge_id'] for e in stale[:5]]}. These also need to be "
        f"archived."
    )


def test_anchor_active_and_paused_intact_after_cleanup():
    """Sanity: the cleanup only removed stale composites. Active +
    paused + retired + archived (non-composite) specs must remain.
    Pre-cleanup the anchor had 283 entries; post-cleanup 209 (74
    composites archived). Active set was 6; verify >= 6."""
    edges = _load_anchor_edges()
    active = [e for e in edges if e.get("status") == "active"]
    assert len(active) >= 6, (
        f"Cleanup over-pruned: only {len(active)} active edges remain, "
        f"expected at least 6 from the 2026-05 active set."
    )
    paused = [e for e in edges if e.get("status") == "paused"]
    assert len(paused) >= 10, (
        f"Cleanup over-pruned: only {len(paused)} paused edges remain, "
        f"expected at least 10 from the 2026-05-09 expansion."
    )


def test_archive_file_exists_and_has_metadata():
    """The cleanup must produce an archive file with traceable
    metadata (CLAUDE.md: archive, never delete)."""
    archive_path = ANCHOR.parent / "edges_archive_pre_t037.yml"
    if not archive_path.exists():
        pytest.skip(
            "Archive file not present — only run after T-037 cleanup "
            "has shipped"
        )
    payload = yaml.safe_load(archive_path.read_text()) or {}
    assert payload.get("_archived_by") == "T-2026-05-12-037"
    assert "_archived_at" in payload
    assert "_archived_from_md5" in payload
    assert isinstance(payload.get("edges"), list)
    assert len(payload["edges"]) >= 1, (
        "Archive must contain at least one archived spec; an empty "
        "archive means the cleanup either over- or under-ran."
    )
