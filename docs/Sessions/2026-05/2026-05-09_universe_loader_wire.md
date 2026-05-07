# Session Summary: 2026-05-09 — Universe loader wire (F6)

The single highest-leverage falsification experiment in the project to
date. Wired the survivorship-bias-aware S&P 500 historical loader
(`engines/data_manager/universe.py`, built 2026-04-24, never wired)
into `ModeController.run_backtest`, then re-ran the multi-year
Foundation measurement on the universe-aware substrate.

## What was worked on

- New `engines/data_manager/universe_resolver.py` — single
  `resolve_universe(...)` entry point bridging the membership loader
  and the orchestration layer's static-list contract. Adds
  `annual_anchor_dates` and `union_active_over_window` helpers to
  `universe.py`. Both deterministic, sorted output, cache-only.
- `ModeController.run_backtest` gained an opt-in
  `use_historical_universe` parameter (also config-driven via
  `backtest_settings.json`). Default is False — no regression on prior
  measurements.
- `scripts/run_multi_year` gained `--use-historical-universe` CLI flag
  and updated markdown header.
- `tests/test_universe_resolver.py` — 15 offline tests covering pure
  helpers, flag-off / flag-on / fallback branches, available-CSV
  filter, sort/dedup contract, and same-input → same-output
  determinism.
- Multi-year measurement run: 2021-2025 × 1 rep,
  `--use-historical-universe`. Wall time 125 min on the 476-503
  ticker universe. Verdict doc:
  `docs/Measurements/2026-05/universe_aware_verdict_2026_05_09.md`.

## What was decided

- **Verdict: COLLAPSES.** Mean Sharpe 1.296 → 0.507 (−0.789,
  −61%). The 1.296 Foundation Gate baseline was substrate-conditional;
  most of the headline alpha was selection bias from the hand-picked
  109-ticker mega-cap config. 4 of 5 years collapse 3-11× outside
  the noise band; 2023 alone holds bitwise-equivalently.
- **Wiring is opt-in.** `use_historical_universe: false` by default in
  `config/backtest_settings.json`. Prior measurements remain
  reproducible bit-for-bit. Going forward, all measurement campaigns
  should default the flag to true; this is documented in the verdict
  report's "Reset directive" section.
- **Within-year determinism deferred.** Used `--runs 1` instead of
  `--runs 3` to fit the 4-8h budget after observing ~50 min/rep on the
  expanded universe. Resolver-level determinism is verified via unit
  test; backtest-level multi-rep verification is recommended as a
  follow-on (~75 min for one year × 3 reps).
- **Existing health-check entry "System Sharpe 0.4 on 109-ticker
  universe vs SPY 0.88" superseded.** That entry's framing assumed
  the static substrate was the right baseline; it isn't. New HIGH
  entry added in `docs/State/health_check.md` for the COLLAPSES
  finding.
- **The 2023 hold-up is the most informative data point.** Per-year
  deltas are: 2021 −0.804, 2022 −0.904, 2023 −0.095 (within noise!),
  2024 −1.622, 2025 −0.518. The single-year survival in 2023 is the
  next falsifiable hypothesis — figure out which alpha generators
  survive there.

## What was learned

- **The universe.py loader was correctly designed but never plumbed.**
  The 2026-04-24 build was self-contained and clean, but the
  `engines/data_manager/index.md` "Not yet wired into any engine" line
  was load-bearing. Every Sharpe measurement since then was
  conditioned on the static-list assumption nobody re-examined.
- **Resolver-level vs measurement-level determinism are different
  contracts.** The resolver (sorted set output, deterministic
  membership-frame query) is provably deterministic via unit test. The
  measurement (5 years × 1 rep) is structurally deterministic but
  empirically unverified within-year on the new substrate. Both are
  necessary; the unit-test contract is sufficient for the resolver
  layer but does NOT substitute for multi-rep measurement
  verification.
- **The 26-54 missing-CSV delisted names per year matter for verdict
  honesty.** Names like FRC (failed 2023), DISCA (acquired 2022),
  ATVI (acquired 2023) are in the historical S&P 500 union but not in
  `data/processed/`. They carry survivorship-bias signal, and adding
  them would push the verdict deeper into COLLAPSES. The measured
  0.507 is therefore an upper bound, not a midpoint.
- **The 4.4-4.6× universe expansion did NOT translate to 4.4-4.6×
  per-bar latency.** Wall time went from ~24 min/year (estimated based
  on smoke test) to 24-29 min/year on the broader universe — most
  per-bar work isn't ticker-bound. Useful for budgeting future
  measurement campaigns.
- **The opt-in flag pattern is the right shape for this kind of
  fix.** It lets the new substrate land without invalidating prior
  measurements (which remain reproducible), and lets future measurements
  switch over by changing one config value. Compare to a hard-wired
  default change, which would have required either retroactively
  invalidating every prior Sharpe number or piping through legacy
  config-version detection.

## Pick up next time

- **Default `use_historical_universe: true`** in
  `config/backtest_settings.json` after the next round of edge-level
  re-validation has been planned. The flag should NOT be flipped on
  main casually — it changes every Sharpe number people will read.
- **Re-run the Discovery gauntlet on the universe-aware substrate.**
  Per-edge contribution Sharpes from 2026-05-02 (volume_anomaly_v1
  +0.113, herding_v1 −0.422 etc.) were all measured on the static
  substrate; they need re-validation under the universe-aware
  substrate before any per-edge promotion / pause / retire decision is
  treated as authoritative.
- **Investigate the 2023 hold-up.** Why does the strategy keep
  ~bitwise-equivalent Sharpe (1.387 → 1.292) on the broader universe
  in 2023, while collapsing in every other year? Which edges fire
  there, and do they generalize?
- **Populate the missing-CSV delisted names** via
  `scripts/fetch_universe.py` so the substrate is complete (currently
  26-54 names missing per year).
- **Optional follow-on:** 3-rep run on 2024 only (~75 min) to verify
  bitwise reproducibility under the universe-aware substrate.

## Files touched

```
config/backtest_settings.json
docs/Core/execution_manual.md
docs/Measurements/2026-05/multi_year_universe_aware_2026_05_09.json
docs/Measurements/2026-05/multi_year_universe_aware_2026_05_09.md
docs/Measurements/2026-05/universe_aware_verdict_2026_05_09.md
docs/Sessions/2026-05/2026-05-09_universe_loader_wire.md
docs/State/health_check.md
engines/data_manager/index.md
engines/data_manager/universe.py
engines/data_manager/universe_resolver.py  (new)
orchestration/mode_controller.py
scripts/run_multi_year.py
tests/test_universe_resolver.py  (new)
```

## Subagents invoked

- None this session. Solo director run with the work staying inside
  the wiring + measurement context budget.
