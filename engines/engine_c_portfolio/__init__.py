"""Engine C — State & Allocation (Accountant + PM).

See ``docs/Core/engine_charters.md`` § Engine C for the full charter.
Two-layer engine: C.1 Ledger + C.2 Allocation, with a hard wall between them.
"""

__version__ = "0.1.0"
__charter_status__ = "drift: C.1 Ledger LOW (operating); C.2 Allocation CRITICAL (compute_target_allocations defined but never called)"
