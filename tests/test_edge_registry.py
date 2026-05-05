"""
tests/test_edge_registry.py
============================
Enforce the `edges.yml` Write Contract documented in
`docs/Core/PROJECT_CONTEXT.md`:

> D writes: New entries (candidate specs, params, metadata, source info)
> F writes: `status` field changes (candidate → active → paused → retired)
> Neither engine deletes the other's fields.

These tests exist because of the 2026-04-25 registry-status-stomp bug:
`EdgeRegistry.ensure()` was silently overriding `status` on every import,
which let auto-register-on-import code (e.g. `momentum_edge.py:64`)
revert lifecycle pause/retire decisions on every backtest startup. The
contract was documented but not enforced. The bug was invisible for
weeks. This file is the executable enforcement.

Methodology: documented contracts decay into folklore unless tests assert
them. See `docs/State/lessons_learned.md` 2026-04-25 entry.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec


@pytest.fixture
def tmp_registry(tmp_path: Path) -> EdgeRegistry:
    """Fresh empty registry on a temp file. Isolated from real data."""
    store = tmp_path / "edges.yml"
    return EdgeRegistry(store_path=store)


# ---------------------------------------------------------------------------
# Core Write Contract: ensure() does NOT touch status on existing specs.
# ---------------------------------------------------------------------------

def test_ensure_creates_new_spec_with_provided_status(tmp_registry):
    """ensure() on a NEW edge_id should register it with the provided status."""
    spec = EdgeSpec(edge_id="new_edge", category="technical",
                    module="m", version="1.0.0", status="active")
    tmp_registry.ensure(spec)
    got = tmp_registry.get("new_edge")
    assert got is not None
    assert got.status == "active"


def test_ensure_does_not_overwrite_paused_status(tmp_registry):
    """The 2026-04-25 bug: ensure() reverted paused→active on import.

    This test fixes the bug class permanently — regression coverage.
    """
    # F-side: lifecycle pauses an edge
    initial = EdgeSpec(edge_id="bug_repro", category="technical",
                       module="m", version="1.0.0", status="active")
    tmp_registry.ensure(initial)
    tmp_registry.set_status("bug_repro", "paused")
    assert tmp_registry.get("bug_repro").status == "paused"

    # D/A-side: edge module re-imports, re-registers itself with status="active"
    # (this is exactly what momentum_edge.py:64 does on every backtest startup)
    re_register = EdgeSpec(edge_id="bug_repro", category="technical",
                           module="m", version="1.0.0", status="active")
    tmp_registry.ensure(re_register)

    # Status MUST remain paused. Anything else is a Write Contract violation.
    assert tmp_registry.get("bug_repro").status == "paused", (
        "ensure() must not overwrite the lifecycle's status on existing specs. "
        "If this fails, the registry is letting auto-register-on-import code "
        "revert lifecycle pause/retire decisions — the exact bug fixed 2026-04-25."
    )


def test_ensure_does_not_overwrite_retired_status(tmp_registry):
    """Same contract for retired status."""
    spec = EdgeSpec(edge_id="retired_edge", category="technical",
                    module="m", version="1.0.0", status="active")
    tmp_registry.ensure(spec)
    tmp_registry.set_status("retired_edge", "retired")
    tmp_registry.ensure(spec)  # re-registration attempt
    assert tmp_registry.get("retired_edge").status == "retired"


def test_ensure_does_not_overwrite_failed_status(tmp_registry):
    """Discovery / validation marks edges as failed; that must persist."""
    spec = EdgeSpec(edge_id="failed_edge", category="technical",
                    module="m", version="1.0.0", status="active")
    tmp_registry.ensure(spec)
    tmp_registry.set_status("failed_edge", "failed")
    tmp_registry.ensure(spec)
    assert tmp_registry.get("failed_edge").status == "failed"


# ---------------------------------------------------------------------------
# ensure() merges non-status fields (allowed by contract).
# ---------------------------------------------------------------------------

def test_ensure_merges_module_field(tmp_registry):
    initial = EdgeSpec(edge_id="merge_test", category="technical",
                       module="old_module", version="1.0.0", status="active")
    tmp_registry.ensure(initial)
    tmp_registry.set_status("merge_test", "paused")

    updated = EdgeSpec(edge_id="merge_test", category="technical",
                       module="new_module", version="1.0.0", status="active")
    tmp_registry.ensure(updated)

    got = tmp_registry.get("merge_test")
    assert got.module == "new_module"        # non-status field updated
    assert got.status == "paused"            # status preserved


def test_ensure_merges_params_when_provided(tmp_registry):
    initial = EdgeSpec(edge_id="params_test", category="technical",
                       module="m", version="1.0.0", params={"lookback": 10},
                       status="active")
    tmp_registry.ensure(initial)
    tmp_registry.set_status("params_test", "paused")

    updated = EdgeSpec(edge_id="params_test", category="technical",
                       module="m", version="1.0.1",
                       params={"lookback": 20}, status="active")
    tmp_registry.ensure(updated)

    got = tmp_registry.get("params_test")
    assert got.params == {"lookback": 20}
    assert got.version == "1.0.1"
    assert got.status == "paused"


def test_ensure_does_not_clobber_params_with_empty(tmp_registry):
    """If a re-register passes `params={}`, the existing params should remain."""
    initial = EdgeSpec(edge_id="params_keep", category="technical",
                       module="m", version="1.0.0",
                       params={"lookback": 14, "threshold": 3.0},
                       status="active")
    tmp_registry.ensure(initial)

    updated = EdgeSpec(edge_id="params_keep", category="technical",
                       module="m", version="1.0.0", params={},  # empty
                       status="active")
    tmp_registry.ensure(updated)

    got = tmp_registry.get("params_keep")
    # Existing params preserved when caller passes empty/falsy
    assert got.params == {"lookback": 14, "threshold": 3.0}


# ---------------------------------------------------------------------------
# set_status() is the explicit owned API for status changes (F/lifecycle).
# ---------------------------------------------------------------------------

def test_set_status_transitions_through_lifecycle(tmp_registry):
    """The full candidate → active → paused → retired path."""
    spec = EdgeSpec(edge_id="lifecycle", category="technical",
                    module="m", version="1.0.0", status="candidate")
    tmp_registry.ensure(spec)
    assert tmp_registry.get("lifecycle").status == "candidate"

    tmp_registry.set_status("lifecycle", "active")
    assert tmp_registry.get("lifecycle").status == "active"

    tmp_registry.set_status("lifecycle", "paused")
    assert tmp_registry.get("lifecycle").status == "paused"

    tmp_registry.set_status("lifecycle", "active")  # revival
    assert tmp_registry.get("lifecycle").status == "active"

    tmp_registry.set_status("lifecycle", "retired")
    assert tmp_registry.get("lifecycle").status == "retired"


def test_set_status_persists_to_disk(tmp_registry, tmp_path):
    spec = EdgeSpec(edge_id="persist", category="technical",
                    module="m", version="1.0.0", status="active")
    tmp_registry.ensure(spec)
    tmp_registry.set_status("persist", "paused")

    # Re-load from disk in a fresh registry instance
    reloaded = EdgeRegistry(store_path=tmp_path / "edges.yml")
    assert reloaded.get("persist").status == "paused"


# ---------------------------------------------------------------------------
# list / list_modules / list_tradeable filters.
# ---------------------------------------------------------------------------

def test_list_tradeable_includes_active_and_paused_only(tmp_registry):
    """Soft-pause: paused edges trade at reduced weight, so list_tradeable
    must include them. Failed/retired/candidate should NOT trade."""
    for eid, status in [
        ("active_e", "active"),
        ("paused_e", "paused"),
        ("retired_e", "retired"),
        ("failed_e", "failed"),
        ("candidate_e", "candidate"),
        ("archived_e", "archived"),
    ]:
        tmp_registry.ensure(EdgeSpec(edge_id=eid, category="technical",
                                     module="m", version="1.0.0", status=status))

    tradeable_ids = {s.edge_id for s in tmp_registry.list_tradeable()}
    assert tradeable_ids == {"active_e", "paused_e"}


def test_list_with_statuses_multi_filter(tmp_registry):
    """The `statuses=` argument allows multi-match filtering."""
    for eid, status in [
        ("a1", "active"), ("a2", "active"),
        ("p1", "paused"),
        ("r1", "retired"),
    ]:
        tmp_registry.ensure(EdgeSpec(edge_id=eid, category="technical",
                                     module="m", version="1.0.0", status=status))

    got = {s.edge_id for s in tmp_registry.list(statuses=["active", "retired"])}
    assert got == {"a1", "a2", "r1"}


# ---------------------------------------------------------------------------
# Real-world repro: simulate the actual import-time stomp scenario
# ---------------------------------------------------------------------------

def test_repro_momentum_edge_import_does_not_revive_paused(tmp_registry):
    """End-to-end repro of the 2026-04-25 bug.

    Simulates the exact sequence that broke autonomy:
    1. momentum_edge_v1 starts as `active`
    2. Lifecycle pauses it (Engine F write)
    3. Backtest startup imports momentum_edge.py, which does
       `reg.ensure(EdgeSpec(edge_id="momentum_edge_v1", ..., status="active"))`
    4. Subsequent reads of edges.yml must show `paused`, not `active`.

    Pre-fix this test would fail. Post-fix it passes.
    """
    # 1. Initial registration via auto-register-on-import (status="active")
    tmp_registry.ensure(EdgeSpec(
        edge_id="momentum_edge_v1",
        category="technical",
        module="engines.engine_a_alpha.edges.momentum_edge",
        version="1.0.0",
        params={},
        status="active",
    ))

    # 2. Lifecycle (Engine F) pauses based on evidence
    tmp_registry.set_status("momentum_edge_v1", "paused")
    assert tmp_registry.get("momentum_edge_v1").status == "paused"

    # 3. Next backtest startup re-imports the module → re-registers with status="active"
    tmp_registry.ensure(EdgeSpec(
        edge_id="momentum_edge_v1",
        category="technical",
        module="engines.engine_a_alpha.edges.momentum_edge",
        version="1.0.0",
        params={},
        status="active",
    ))

    # 4. The lifecycle decision MUST have survived
    assert tmp_registry.get("momentum_edge_v1").status == "paused", (
        "Status was reverted by re-registration — the registry-stomp bug is back. "
        "See docs/State/lessons_learned.md 2026-04-25."
    )
