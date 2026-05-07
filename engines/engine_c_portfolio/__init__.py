"""Engine C — State & Allocation (Accountant + PM).

See ``docs/Core/engine_charters.md`` § Engine C for the full charter.
Two-layer engine: C.1 Ledger + C.2 Allocation, with a hard wall between them.
"""

__version__ = "0.2.0"
__charter_status__ = "drift: CLOSED 2026-05-09 night — C.1 Ledger + C.2 Allocation both active (BacktestController._prepare_orders:508 was wired all along); HRP+TurnoverPenalty correctly placed in composer.py via C-engines-1 (cae2002)"
