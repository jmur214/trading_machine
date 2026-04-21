<p align="center">
  <img src="https://img.shields.io/badge/Status-Active_Development-blue.svg" alt="Status">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Broker-Alpaca_Markets-FFDC00.svg" alt="Broker">
  <img src="https://img.shields.io/badge/Architecture-6_Engine_Quant_System-00C853.svg" alt="Architecture">
  <img src="https://img.shields.io/badge/License-Private-lightgrey.svg" alt="License">
</p>

# ArchonDEX

An adaptive, self-evolving algorithmic trading system that discovers market edges, manages risk with institutional-grade guardrails, and autonomously learns what works — using a multi-engine architecture inspired by how real hedge fund teams operate.

> **This is not a script that runs a strategy.** It is a _system_ that discovers, validates, deploys, and retires strategies — while managing the capital those strategies trade on, in real time.

---

## The Concept

Most algorithmic trading codebases are built around a single idea: take a signal, size a trade, place an order. ArchonDEX is built around a different premise:

**No single person runs a hedge fund alone.** The best-performing market organizations divide cognitive labor across specialized roles — a researcher, a risk manager, a portfolio manager, a macro analyst, and a performance reviewer — each with strict authority boundaries and clear accountability.

ArchonDEX models this. It decomposes the trading process into **6 independent engines**, each mapped to a real-world market professional, communicating through explicit contracts and never overstepping their mandate.

---

## Architecture — The 6-Engine System

```
┌──────────────────────────────────────────────────────────────────────┐
│                        DATA MANAGER (The Librarian)                  │
│         OHLCV • ATR • Fundamentals • Caching • Normalization         │
└──────────────┬──────────────────┬──────────────────┬─────────────────┘
               │                  │                  │
               ▼                  ▼                  ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐
│  ENGINE E        │  │  ENGINE A        │  │  ENGINE B                │
│  Regime Intel    │─▶│  Forecast        │─▶│  Trade Construction      │
│  (Macro Thinker) │  │  (The Researcher)│  │  (The Risk Manager)      │
│                  │  │                  │  │                          │
│  "What kind of   │  │  "What's a good  │  │  "How do we survive if   │
│   market is it?" │  │   opportunity?"  │  │   the researcher is      │
│                  │  │                  │  │   wrong?"                │
└────────┬─────────┘  └────────▲─────────┘  └────────────┬─────────────┘
         │                     │ weights                  │
         │ regime context      │                          ▼
         │                ┌────┴─────────────┐  ┌──────────────────────────┐
         │                │  ENGINE F        │  │  ENGINE C                │
         ▼                │  Strategy        │  │  Portfolio State          │
┌──────────────────┐      │  Governance      │  │  (Accountant + Allocator)│
│  ENGINE D        │      │  (Perf Reviewer) │  │                          │
│  Discovery &     │      │                  │  │  "What do we own and     │
│  Evolution       │─────▶│  "Which edges    │  │   where should capital   │
│  (The Lab)       │edges │   earned trust?" │  │   go?"                   │
│                  │      └──────────────────┘  └──────────────────────────┘
│  "What new edges │
│   can we find?"  │
└──────────────────┘
```

| Engine | Role | Core Question |
|--------|------|---------------|
| **Engine A — Forecast** | The Researcher | *"Given market data, what is the directional forecast and how strongly do I believe it?"* |
| **Engine B — Trade Construction** | The Risk Manager | *"How do we express this trade without risking ruin?"* |
| **Engine C — Portfolio State** | The Accountant + PM | *"What do we actually own, and where should capital be allocated?"* |
| **Engine D — Discovery & Evolution** | The Edge Hunter | *"What new patterns, strategies, and edges can we find?"* |
| **Engine E — Regime Intelligence** | The Macro Thinker | *"What kind of market environment are we operating in?"* |
| **Engine F — Strategy Governance** | The Performance Reviewer | *"Which edges are earning trust, and which should be retired?"* |

### The Golden Rule
> **No engine is allowed to do another engine's job.** A identifies opportunities. B makes them safe. C tracks the books. D grades performance. E reads the weather. If A starts making risk decisions or B starts predicting returns, the system architecture has failed.

---

## Key Capabilities

### Edge-Based Signal Generation
The system doesn't rely on a single strategy. It runs multiple independent "edges" — statistical, technical, fundamental, and behavioral — simultaneously. Each edge is a pluggable module that produces normalized directional scores.

**7 Edge Categories (15+ active edges):**
- **Technical** — RSI bounces, Bollinger breakouts, ATR breakout, momentum, SMA cross
- **Fundamental** — PE/PS/PB/PFCF ratio screening, value trap detection
- **News / Event-Driven** — Sentiment analysis, earnings vol compression/drift (PEAD)
- **Statistical / Quant** — Calendar seasonality, overnight gap fill, volume spike reversal, volume dry-up breakout
- **Behavioral** — Multi-condition panic detection, cross-sectional herding contrarian, pre/post-earnings volatility
- **Grey** — Politician trade tracking, non-public-but-legal information edges (planned)
- **Evolutionary** — GA-evolved composite genomes combining genes from any category above

### Institutional Risk Management
- ATR-based dynamic position sizing
- Hard exposure caps (gross, net, sector)
- Liquidity-aware order filtering (ADV limits)
- Trailing stop lifecycle management
- Automatic circuit breakers

### Adaptive Portfolio Construction
- Mean-Variance Optimization (MVO)
- Adaptive Inverse-Volatility weighting
- Drift monitoring & rebalance triggers
- Strict double-entry accounting ledger (equity always reconciles)

### Autonomous Discovery & Evolution (Engine D)
Engine D autonomously discovers new edges and evolves existing ones:
- Two-stage ML pipeline: LightGBM feature screening -> decision tree rule extraction
- Genetic algorithm evolution of composite edge genomes (selection, crossover, mutation, elitism)
- 40+ engineered features across 7 categories (technical, fundamental, calendar, microstructure, inter-market, regime, cross-sectional)
- 4-gate validation pipeline: backtest -> PBO robustness -> WFO degradation -> Monte Carlo significance
- Discovery activity logged to JSONL for full audit trail

### Autonomous Governance (Engine F)
Engine F continuously evaluates edge performance across market regimes:
- Rolling Sharpe, Win Rate, Max Drawdown per edge
- Regime-conditioned attribution (was the edge bad, or just out of phase?)
- Autonomous weight adjustment with strong hysteresis to prevent overfitting
- Full edge lifecycle management (candidate -> active -> paused -> retired)

### Full-Spectrum Data Pipeline
- Alpaca Markets API integration (historical + live streaming)
- Parquet + CSV dual-format caching with automatic normalization
- Async multi-ticker prefetching
- Offline mode with full local cache fallback
- Synthetic ticker support (`SYNTH-*`) for rapid offline testing

---

## Dashboard

A real-time, dark-themed Plotly Dash control center with:

| Tab | What It Shows |
|-----|---------------|
| **Mode** | Paper vs. Backtest vs. Live account summaries |
| **Dashboard** | Equity curve, drawdown, real-time KPIs |
| **Performance** | Rolling Sharpe, edge correlation matrix |
| **Analytics** | Cumulative PnL by edge, benchmark comparison, PnL heatmap |
| **Governor** | Edge weight evolution, trust map, strategy scorecards |
| **Intel** | Market news sentiment, macro intelligence |

---

## Project Structure

```
archondex/
├── engines/
│   ├── engine_a_alpha/       # Signal generation & edge aggregation
│   ├── engine_b_risk/        # Position sizing, stops, exposure limits
│   ├── engine_c_portfolio/   # Ledger, allocation policies, state
│   ├── engine_d_discovery/    # Edge hunting (LightGBM+DTree), GA evolution, 4-gate validation
│   ├── engine_e_regime/       # Market regime detection & classification
│   ├── engine_f_governance/   # Edge lifecycle, weight management, performance scoring
│   └── data_manager/          # OHLCV ingestion, caching, normalization
│
├── backtester/               # Walk-forward backtesting framework
├── brokers/                  # Alpaca broker adapter
├── cockpit/                  # Dash dashboard (V2)
├── analytics/                # Edge feedback & performance analysis
├── intelligence/             # News sentiment & market intel
├── live_trader/              # Live/paper execution gateway
├── orchestration/            # Mode controller (backtest/paper/live)
├── scripts/                  # CLI tools (backtest, diagnostics, fetch)
├── config/                   # Universe definitions, edge configs
├── tests/                    # Test suite
│
├── docs/
│   ├── Core/                 # AI command center (GOAL, ROADMAP, etc.)
│   │   └── Ideas_Pipeline/   # 3-stage idea → roadmap promotion system
│   ├── Audit/                # Functional audits & engine charters
│   └── Progress_Summaries/   # Lessons learned & phase completion logs
│
└── .agent/workflows/         # Slash-command automation workflows
```

> Each `engines/` subdirectory contains an `index.md` with both human-written architectural narrative and auto-generated code reference tables.

---

## Quick Start

### Prerequisites
- Python 3.10+
- [Alpaca Markets](https://alpaca.markets/) account (free, paper trading supported)

### Installation

```bash
# Clone the repository
git clone https://github.com/jmur214/archondex.git
cd archondex

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create a `.env` file at the project root:

```env
APCA_API_KEY_ID=your_alpaca_api_key
APCA_API_SECRET_KEY=your_alpaca_secret_key
APCA_API_BASE_URL=https://paper-api.alpaca.markets
APCA_API_DATA_URL=https://data.alpaca.markets
```

> ⚠️ **Never commit your `.env` file.** It is already listed in `.gitignore`.

### Running the System

```bash
# Run a full backtest with fresh data
python scripts/run_backtest.py --fresh --alpha-debug

# Run system health diagnostics
python -m scripts.run_diagnostics

# Launch the dashboard
python -m cockpit.dashboard_v2.app --port 8050

# Run the full autonomous cycle
python scripts/run_autonomous_cycle.py
```

> For the complete command reference, see [`docs/Core/execution_manual.md`](docs/Core/execution_manual.md).

---

## Documentation System

This project uses a structured, AI-native documentation system designed to maintain context across long-running development sessions. The full guide is available in [`DOCUMENTATION_SYSTEM.md`](DOCUMENTATION_SYSTEM.md).

**Key documents:**

| Document | Purpose |
|----------|---------|
| [`GOAL.md`](docs/Core/GOAL.md) | AI entry point — north star orientation |
| [`PROJECT_CONTEXT.md`](docs/Core/PROJECT_CONTEXT.md) | Architecture brief & philosophy |
| [`human-system_explanation.md`](docs/Core/Human/human-system_explanation.md) | Plain-English project overview (3 audience levels) |
| [`ROADMAP.md`](docs/Core/ROADMAP.md) | Phased development plan |
| [`execution_manual.md`](docs/Core/execution_manual.md) | Every CLI command in one place |
| [`agent_instructions.md`](docs/Core/agent_instructions.md) | AI operating rules & coding standards |
| [`Ideas_Pipeline/`](docs/Core/Ideas_Pipeline/) | 3-stage idea intake system |

---

## Development Philosophy

1. **Divide cognitive labor.** No engine does another engine's job. Boundaries are enforced through explicit input/output contracts.

2. **Archive, never delete.** Legacy code goes to `Archive/`, not the trash. Institutional memory is preserved.

3. **Gate ideas from becoming code.** Raw thoughts → structured backlog → evaluated analysis → roadmap → implementation. Each stage requires human approval.

4. **Brutal realism over optimism.** The system is designed to ask "what could kill us?" before "how much can we make?" Every trade has an explicit rejection or approval reason.

5. **Self-evolving documentation.** The AI is instructed to update documentation as it discovers better practices. Hybrid `index.md` files combine human narrative with auto-generated code reference tables.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Data Processing | Pandas, NumPy |
| Data Storage | Parquet, CSV, JSON |
| Broker API | Alpaca Markets (alpaca-py) |
| Dashboard | Dash, Plotly |
| ML / Statistics | scikit-learn, LightGBM, scipy |
| Async / Streaming | asyncio, WebSocket |
| Config | python-dotenv, JSON/YAML |

---

## Security

- All API credentials are loaded from environment variables via `python-dotenv`
- `.env` and `config/alpaca_keys.json` are excluded from version control
- The system defaults to **paper trading** endpoints — live execution requires explicit configuration
- No hardcoded secrets exist anywhere in the codebase

---
<p align="center"><i>
The edge isn't in the signal. It's in the system that finds it, sizes it, survives being wrong about it,<br>
and learns which signals to trust next.
</i></p>

---

<p align="center"><sub>
<b>Disclaimer:</b> This software is for educational and research purposes. It is not financial advice. Trading involves substantial risk of loss. Past performance does not guarantee future results. Always test extensively in paper trading before allocating real capital.
</sub></p>
