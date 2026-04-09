# Agent Instructions & Best Practices

## Operational Reminders
- **README Updates:** Ensure `README.md` is updated anytime a new file or CLI argument is created.
- **Git Commits:** Make descriptive and atomic git commits for milestone changes. 
- **Documentation & Tracking:** 
  - Consult and update `docs/Core/ROADMAP.md` before and after major feature additions to stay aligned on forward-looking goals.
  - For historical tracking and error prevention, log significant changes, bug fixes, or "things that haven't worked" in `docs/Progress_Summaries/lessons_learned.md`.
  - Log any new feature additions in `docs/Progress_Summaries/` with a timestamped file when completing a major phase.
  - The architectural documentation (`index.md` files) utilizes a hybrid approach. If you add, modify, or delete core scripts, you MUST run the documentation sync workflow via the `/6_docs_maintenance` slash command, or manually run `python scripts/sync_docs.py`. After doing so, verify that the manual qualitative summaries at the top of the `index.md` files are still accurate regarding the new code.
  - **Command Tracking (CRITICAL):** Track all aspects of using the command line in your reasoning (if commands work, fail, what they do, etc.). Most importantly, if any *new* commands are researched or utilized, they must IMMEDIATELY be added to `docs/Core/execution_manual.md`.
- **Environment Variables:** All secrets and API keys (e.g., Alpaca keys) must reside in `.env`. Never commit them to source control.

## System Workflows
- **Execution Commands:** When tasked with running a subsystem, backtest, or data pipeline, do NOT guess python script pathways. Explicitly consult `docs/Core/execution_manual.md` for the exact, approved CLI execution syntax.
- **Idea Ingestion:** If the user shares unstructured thoughts or requests brainstorming for new features, use the `docs/Core/Ideas_Pipeline/` modules to extract and evaluate those concepts before touching core logic. See `ideas_backlog.md` for the exact semantic processing rules.
- **UI Architecture:** `cockpit/dashboard/` is an obsolete legacy directory. All active UI development, analytical tabs, and reactive callbacks must be executed exclusively within `cockpit/dashboard_v2/`.

## Coding Best Practices
- **Modularity:** Keep functions small and single-purpose. Prefer `def` functions over inline Dash callbacks where possible. Avoid mixing UI logic with data processing.
- **Graceful Degradation:** The UI and data pipelines should gracefully degrade if offline or missing credentials (e.g., fallback to local CSVs if Alpaca is unavailable).
- **Type Hinting:** Use proper Python typography and docstrings for all new functions.
- **Dynamic Best Practices:** We do not want these rules to stagnate. If you discover or implement a better operational practice (e.g., a significantly faster serialization format than Parquet), you must log the change in `docs/Progress_Summaries/lessons_learned.md` and *update this `agent_instructions.md` file* so the new best practice becomes the standard.
- **Performance:** Use `pandas` and vectorization wherever possible instead of `for` loops. Write data to `Parquet` instead of `CSV` where speed and scale are concerned.
- **Data Schemas:** Maintain consistent data normalization rules across the Data Manager (UTC timestamps, standardized OHLCV columns).
- **AI Operating Constraints:** Extreme, brutal realism about system flaws is ALWAYS prioritized over blind code generation or taking shortcuts.
