# Human Ideas Ledger (Backlog)

*This is a strict, structured repository. The AI reads `docs/Core/human.md`, extracts the core premises, and categorizes them here as concise bullet points. The AI provides NO OPINIONS or analysis in this file.*

> **AI Workflow Rule (Stage 1: Ingestion)**: The human brainstorms raw thoughts in `docs/Core/Ideas_Pipeline/human.md` under `# 📥 NEW INBOX`. When instructed to process new ideas, you must read ONLY that top section, extract core concepts, organize them structurally into this `ideas_backlog.md` ledger, and assign them an explicit tracking ID (e.g. `- [ ] **#ML-1:**`). CUT the processed text from `human.md` into `# 🗄️ PROCESSED ARCHIVE`.
> You **MUST STOP HERE** and ask the user to review `ideas_backlog.md`. The user will leave revision comments in the `# 💬 User Scratchpad / Revisions` at the bottom of this file. You must read those comments, update the items above, and clear the scratchpad until the user marks the items with an explicit `[x]`. ONLY THEN can you use your Cognitive Lenses to draft a deep-dive analysis of those ideas and promote them to `idea_evaluations.md`.


## [Machine Learning & Prediction]
- [ ] **#ML-1:** Incorporate ML algorithms for short-term prediction.
- [ ] **#ML-2:** Implement Market Regime Detection as its own engine (using ML algorithms, Markov chains, Kalman filters, etc.).
- [ ] **#ML-3:** Build systems to understand when signals should be ignored based on regime context.

## [Alternative Data & Scraping]
- [ ] **#DATA-1:** News and geopolitical event scraping to trigger edge setups or alert the system of policy impact.
- [ ] **#DATA-2:** Incorporating 13F filings, repo markets (SOFR rates, Fed repo facility), yield curves, OpenBB, and international markets.
- [ ] **#DATA-3:** Unconventional metrics (e.g., adult entertainment index, prediction markets).

## [Risk Management & Portfolio Defense]
- [ ] **#RISK-1:** Short term/intraday trading purely as a hedging mechanism against downturns in long-term swing positions.
- [ ] **#RISK-2:** Improve drawdown stops to be dynamic rather than rigid.
- [ ] **#RISK-3:** Utilize options (e.g., call spreads) and leveraged ETFs (intraday only) for hedging and compounding returns with low capital.

## [System Architecture & Agentic Workflows]
- [ ] **#ARCH-1:** Implement ChatGPT directly into the trading folder for insight generation.
- [ ] **#ARCH-2:** Build a multi-agent system where a "manager" agent ingests a file and assigns sub-agents to specific aspects of the task (reference: *Dexter* on GitHub).
- [ ] **#ARCH-3:** Differentiate between Workflows (static steps) and Agents (dynamic loops) to improve automation. 

## [Portfolio Management (Engine C & Governor)]
- [ ] **#PORT-1:** Develop true "Portfolio Sleeves" to divide capital into sub-accounts managed independently for specific strategies, asset classes, or managers (e.g., isolating legacy stocks vs blending investment styles).
- [ ] **#PORT-2:** Implement Kelly Criterion for dynamic position sizing.
- [ ] **#PORT-3:** Continuous Learning Loop: Optimizing not just edges, but entry/exit points, diversification metrics, and hedging timing dynamically.
- [ ] **#PORT-4:** System requires uncorrelated strategies and a specific mechanism to identify fundamentally explosive stocks (combining intrinsic value with technical breakouts).

## [Testing & Live Infrastructure]
- [ ] **#TEST-1:** Dual Paper Trader setup: One paper trader tests new/raw strategies, the other exclusively runs proven, validated strategies before they are authorized for real money.



---
# 💬 User Scratchpad / Revisions
*Leave comments below referencing the ID (e.g., "For `#ML-1`, make sure to focus on Random Forests first"). The AI will read this, update the items above, and clear your comment. When you approve an idea, change `[ ]` to `[x]`.*