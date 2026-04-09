# AI Idea Evaluations & Research Memos

*This is the AI's whiteboard. It takes the raw, unstructured concepts from the `ideas_backlog.md` ledger and expands on them using its Cognitive Lenses. Ideas are grouped and scored on Feasibility and Impact.*

> **AI Workflow Rule (Stage 2: Evaluation)**: Once the user explicitly approves an idea with an `[x]` in `ideas_backlog.md`, REMOVE it from the backlog and PROMOTE it here. Adopt the appropriate Cognitive Lens and provide: 1) The Core Concept, 2) Technical Feasibility (Low/Med/High), 3) Potential Impact (Low/Med/High), 4) Strict Execution Rules/Risks. Flag ideas with 🟢 (High Conviction), 🟡 (Evaluating), 🔴 (High Risk), or ⚠️ (Needs Clarification).

> **Promotion Rule (Stage 3: Roadmap)**: When the user explicitly approves an evaluation here, REMOVE it from this file. Synthesize it into a main bullet point, followed by a list of formal, actionable sub-steps and inject it into the appropriate Phase in `docs/Core/ROADMAP.md`.

---

## 🟢 [High Priority] Codebase Consolidation for AI Context (#DOCS-3)
**Cognitive Lens:** Infrastructure Optimization Architect
- **Core Concept:** Relentlessly archiving legacy folders and dead scripts specifically to maximize context-window clarity for AI agents during operations.
- **Feasibility:** High.
- **Impact:** High. Directly eliminates hallucination vectors and coding errors caused by AI confusion.
- **Execution Risks:** Accidental deletion of valuable legacy logic (Mitigation: Enforce unified `Archive/` protocols rather than deletion).

## 🟢 [High Priority] Market Regime Detection Engine
**Cognitive Lens:** Macro & Regime Analyst
- **Core Concept:** Building a dedicated engine to detect whether the market is trending, chopping, or transitioning (using Markov Chains or Kalman filters), allowing the Governor to turn off failing mean-reversion edges before they bleed capital.
- **Feasibility:** Medium. (Requires robust mathematical modeling and out-of-sample data, but Python libraries like `hmmlearn` or `pykalman` exist to support this).
- **Impact:** **Massive**. This solves the #1 reason algorithmic systems blow up (failing to adapt to new regimes).
- **Execution Risks:** Beware of lagging indicators. If the system only identifies a regime *after* a massive 20% drawdown, it is useless. The detection must be forward-looking.

## 🟡 [Evaluating] Dual Paper-Trader Segregation
**Cognitive Lens:** Risk & Ops Manager (Engine B)
- **Core Concept:** Running 2 live Paper Traders. PT-A tests experimental, newly discovered edges. PT-B is the "Gold Standard" account running only statistically significant, proven edges. Only PT-B graduates to live capital.
- **Feasibility:** High.
- **Impact:** High. Dramatically increases safety.
- **Execution Risks:** Requires isolating state files so PT-A's erratic trades don't infect PT-B's portfolio records.

## 🔴 [High Risk] Leveraged ETFs & Options for Hedging
**Cognitive Lens:** Quantitative / Edge Analyst
- **Core Concept:** Utilizing leveraged ETFs (intraday only) and call/put spreads to hedge the long-term portfolio during high-volatility drawdowns.
- **Feasibility:** Low/Medium. (Options data is notoriously difficult and expensive to backtest due to Greeks and bid/ask spreads. Leveraged ETFs suffer from volatility decay).
- **Impact:** Medium.
- **Execution Risks:** If the hedging algorithm fails, leveraging during a plunge can double the loss rather than stopping it. The AI strongly recommends mastering pure equity rotation/cash-shifting before introducing leveraged derivatives.

## ⚠️ [Needs Clarification] Agentic Manager Workflow
**Cognitive Lens:** Machine Learning & Integration Architect
- **Core Concept:** Implementing a "Dexter-like" multi-agent pipeline where a single manager AI delegates coding tasks and strategy generation to specialized sub-agents.
- **Question for Human:** Are you proposing we build this multi-agent framework *into* the trading machine's automated execution loop (e.g., AIs trading by themselves), or just as a development pipeline to help you write code faster?
