Trading Machine Repository Audit Report

Overview

This audit focuses on the Trading Machine repository*, particularly the subsystems involved in edge signal generation, collection, processing and propagation through the Alpha→Risk→Execution→Governor feedback loop.  The goal was to identify why valid edge logs (e.g., “[EDGE][DEBUG] Generated 3 signals”) produce no actionable signals for the AlphaEngine and consequently result in empty trades and no learning in the Governor.  The audit examined the code base, reproduced the failure and traced the flow of data through the relevant modules.

*The audited commit was the current main branch at the time of inspection.  All line references point to the repository on GitHub using raw file links.

System Data‑Flow Map

The Trading Machine’s Engine A performs the following steps when generate_signals() is called on the AlphaEngine:
	1.	Normalize Data – _normalize_dataframe standardises input data (data_map) into OHLC columns.
	2.	Collect Raw Scores – SignalCollector.collect() iterates over every active edge.  For each edge it tries to call (in order) compute_signals, generate_signals, generate or instantiates the edge class and calls its compute_signals.  Whatever result is returned is immediately converted into a Python dict via dict(result or {}) ￼.  The collector then iterates over this dictionary, normalises ticker keys and aggregates the values into raw_scores (a nested dict ticker → {edge: score}) ￼.
	3.	Process Scores – SignalProcessor.process() normalises the raw scores to the range [–1, 1], applies regime checks (trend/volatility gates), applies ensemble shrinkage and hygiene checks, and outputs per‑ticker summaries containing an aggregate_score and edges_detail ￼ ￼.  These per‑ticker summaries are keyed by ticker.
	4.	Format Discrete Signals – SignalFormatter.to_side_and_strength() converts each aggregate score into a discrete side (long, short or None) and a strength.  Signals below exit_threshold are discarded and those above enter_threshold are emitted ￼.
	5.	Governor Integration – Each emitted signal includes metadata about its contributing edges.  After execution, the Governor uses trade logs and performance metrics to update edge weights.
    (no figure 1 available)
    Figure 1 – Simplified data‑flow: edges produce signals → SignalCollector normalises → SignalProcessor aggregates → SignalFormatter discretises → Risk/Execution/Governor.

Compatibility Matrix – Expected vs. Actual Edge APIs
Edge module | Expected compute_signals output | Actual behaviour | Notes
rsi_mean_reversion | Returns dict[ticker → float] from module‑level compute_signals (raw RSI‑based score) | Correct.  Also implements RSIMeanReversionEdge.generate_signals() which yields rich signal dictionaries. | Compatible with both numeric and rich interfaces.
xsec_meanrev | Returns dict[ticker → float] and accepts either a DataFrame or a dict[str, DataFrame] | Correct.  Handles cross‑sectional input and scales weights .
xsec_momentum | Should return raw scores but instead its compute_signals returns a list of signal dictionaries (each with keys ticker, side, confidence, etc.) | Incompatible.  When the collector calls compute_signals, Python coerces this list to a dict by using its elements as keys (dict(list_of_dicts)), producing a malformed dictionary with only the last entry.  Subsequent normalization fails silently.  Furthermore, compute_signals expects a pd.DataFrame but the collector passes a data_map dict, leading to an exception ('dict' object has no attribute 'loc').
momentum_edge | Only defines generate_signals (list of dicts) | Collector converts list of dicts into a dict incorrectly; the signal side/strength information is lost and entries are skipped.
rsi_bounce | Defines generate returning {“signal”: float, “weight”: float} | Collector treats the returned value as a dict of floats; because keys are not tickers, they are filtered out as invalid tickers, resulting in no usable signals.
atr_breakout, atr_squeeze, bollinger_breakout, momentum_trend, sma_crossover, volume_spike and others | Many only implement generate_signals() or generate() and return lists or dicts of non‑numeric objects | Inconsistent API leads to dropping of signals by the collector.

Observed Consequences
	1.	Collector Discards Non‑Numeric Results:  SignalCollector.collect() converts the result of each edge call to a dict.  It expects the values to be numeric floats but many edges return nested dictionaries.  When a non‑numeric value is encountered, it is silently skipped ￼.
	2.	Wrong Input Type for Cross‑Sectional Edges:  xsec_momentum.compute_signals expects a DataFrame (prices.loc[:as_of]), but the collector always passes the entire data_map.  This mismatch generates an 'dict' object has no attribute 'loc' exception, as observed during reproduction.
	3.	List‑to‑Dict Conversion Bug:  The collector calls dict(result or {}) regardless of the original type ￼.  Passing a list of dictionaries into dict() uses each element as a key, which is invalid; this results in either a malformed dictionary or a runtime exception.
	4.	Empty raw_scores → No Signals:  Because the collector often returns an empty raw_scores dictionary, the processor produces no summaries and the fallback aggregator in the AlphaEngine is never reached.  Consequently the AlphaEngine logs No signals generated and the Governor receives no data.

Root Causes of Signal Loss
	1.	Inconsistent Edge Interfaces – Some edges follow the new BaseEdge pattern (returning rich signal objects via generate_signals), whereas others follow an older pattern where compute_signals returns a numeric dictionary.  The collector assumes the latter and discards non‑numeric results ￼.
	2.	Collector’s Rigid Normalisation – The collector normalises tickers and values assuming signals is a simple dict[ticker → float] ￼.  It does not support lists of signals or nested structures, and it silently drops invalid items.
	3.	Cross‑Sectional Edges Expect DataFrames – The cross‑sectional momentum edge calls .loc on prices, but the collector passes a dict instead.  This mismatch generates exceptions and results in empty data being collected.
	4.	List‑to‑Dict Conversion – Returning a list from an edge and passing it into dict() is semantically wrong.  The code uses dict(result or {}) ￼ without type checking, which either yields meaningless results or errors.
	5.	Overly Restrictive Ticker Pattern – Tick symbols must match the regex [A‑Z0‑9.\-]{1,12}.  Edges returning keys like 'signal' or 'weight' (as in the rsi_bounce edge) never match and are thrown away.  Multi‑asset edges returning tuples of tickers are also mishandled.

Proposed Fixes

1. Enforce a Unified Edge API
	•	Design: All edge modules should expose two methods:
	•	compute_signals(data_map, now) → dict[str, float]: returns raw, real‑valued scores per ticker for use by the collector.  For cross‑sectional edges, the method should accept data_map and internally build the necessary combined DataFrame.
	•	generate_signals(data_map, now) → list[dict] (optional): returns rich signal objects (ticker, side, confidence, meta).  This will be used directly by the risk engine or the dashboard.
	•	Refactor edges:
	•	Update xsec_momentum.compute_signals so it returns a numeric dictionary of weights instead of a list of dicts.  The existing logic that produces signals at the end can be moved to generate_signals.  For example:
    def compute_signals(self, data_map: Dict[str, pd.DataFrame], as_of: pd.Timestamp) -> Dict[str, float]:
        # Build cross-sectional DataFrame from data_map
        combined = pd.concat({t: df['Close'] for t, df in data_map.items()}, axis=1)
        weights = self._compute_weights(combined.loc[:as_of])
        return weights
    def generate_signals(self, data_map, as_of):
        weights = self.compute_signals(data_map, as_of)
        signals = []
        for t, w in weights.items():
            signals.append({'ticker': t,
                            'side': 'long' if w > 0 else 'short',
                            'confidence': abs(w),
                            'edge_id': self.EDGE_ID,
                            'category': self.CATEGORY,
                            'meta': {'weight': w}})
        return signals
    •	Make similar changes to momentum_edge, rsi_bounce and other edges that currently only return lists or nested dictionaries.  They should implement compute_signals returning a float per ticker; generate_signals can wrap the result into side/confidence dictionaries.

2. Make the Collector Type‑Aware

Extend SignalCollector.collect() so that it properly handles different return types:
result = self._call_edge(edge_obj, data_map, now)
if isinstance(result, dict):
    # as today
    m = result
elif isinstance(result, list):
    # list of signal dicts → convert to ticker→score mapping
    m = {}
    for item in result:
        t = item.get('ticker')
        if not t:
            continue
        # determine a numeric score
        if 'score' in item:
            score = float(item['score'])
        elif 'signal' in item:
            score = float(item['signal'])
        else:
            # derive from side & confidence
            side = item.get('side')
            conf = float(item.get('confidence', item.get('strength', 1.0)))
            score = conf if side == 'long' else (-conf if side == 'short' else 0.0)
        m[t] = score
else:
    m = {}

This mapping can then be normalised as today.  This change prevents silent dropping of edges returning lists and supports both new and legacy edges.

3. Build a Cross‑Sectional DataFrame in the Collector

When an edge’s compute_signals expects a single DataFrame (checked via function signature or by catching an exception), the collector should assemble a DataFrame from the data_map:
try:
    return fn(data_map, now)
except AttributeError as e:
    if "'dict' object has no attribute 'loc'" in str(e):
        # build combined DataFrame
        combined = pd.concat({t: df['Close'] for t, df in data_map.items()}, axis=1)
        return fn(combined, now)
    else:
        raise
This allows cross‑sectional strategies to run correctly without modifying the edges themselves.

4. Relax Ticker Pattern and Key‑Extraction Logic

The current regex restricts tickers to [A‑Z0‑9.\-]{1,12}.  Edges that return nested dictionaries (with keys like 'signal' or 'weight') are treated as tickers and therefore dropped.  After introducing the type‑aware conversion above, tickers will be derived from explicit fields, and the regex can be simplified to permit lower‑case or non‑standard tickers where appropriate.

5. Enhance Diagnostics

Add explicit warnings when an edge returns an unsupported type.  For example, in the collector:
if not isinstance(result, (dict, list)):
    print(f"[COLLECTOR][WARN] Edge {edge_name} returned unsupported type {type(result).__name__}")
Similarly, logging raw keys and values under ALPHA_DEBUG should help detect mis‑formatted signals.

6. Update Unit Tests and Harness

The diagnostic plan in the prompt outlines a comprehensive test suite.  Once the above changes are applied, the tests should be updated to cover:
	•	Edge unit tests – Verify that every edge’s compute_signals returns a dict[str, float] and that all values are finite numbers.
	•	Collector integration tests – Provide sample data_map and check that the collector normalises keys correctly, handles lists of signals and averages multiple entries per ticker.
	•	AlphaEngine signal flow tests – Use a small synthetic data_map with a cross‑sectional edge to ensure that the collector passes a DataFrame when required.
	•	Processor & formatter consistency – Confirm that the SignalProcessor and SignalFormatter handle scores as expected given different thresholds and hygiene settings.
	•	Governor & feedback loop tests – Simulate trades and verify that the Governor updates edge weights according to performance metrics.

These tests will help prevent regression of the signal pipeline.

Verification Plan

After implementing the fixes above, the following scenario should produce non‑empty signals and trades:
	1.	Create a synthetic price history for several tickers.
	2.	Initialise the AlphaEngine with a mix of single‑asset and cross‑sectional edges (e.g., rsi_mean_reversion, xsec_momentum).
	3.	Call alpha_engine.generate_signals(data_map, now).  The collector should convert lists of signals into a dict of raw scores, build a cross‑sectional DataFrame for cross‑sectional edges, and normalise tickers correctly.  The processor should produce aggregate scores and the formatter should emit discrete signals when above threshold.
	4.	Pass signals into the RiskEngine and Execution simulator; verify that trades are created with the correct edge IDs and weights.
	5.	Feed the trade log into the Governor; check that edge weights are updated in data/governor/edges.yml and that the Governor does not crash on new schemas.

Refactor Proposal for Long‑Term Maintainability
	1.	Unify Edge Base Classes:  Define a single abstract base (EdgeBase) specifying compute_signals() returning raw floats and optional generate_signals() returning rich signals.  Deprecate generate() and other ad‑hoc functions.
	2.	Registry‑Driven Discovery:  Replace hard‑coded imports in AlphaEngine with a registry listing active edges (data/governor/edges.yml).  The registry could include metadata such as category, version, default parameters and whether the edge is cross‑sectional.  This makes enabling/disabling edges trivial and avoids import errors.
	3.	Typed Data Structures:  Adopt dataclasses or pydantic models for signal objects (ticker, side, confidence, meta) and for raw scores to enforce schema consistency throughout the pipeline.
	4.	Configurable Collector:  Allow edges to declare whether they need a combined DataFrame (cross‑sectional) or a per‑ticker DataFrame.  The collector can then pass the appropriate structure.
	5.	Dashboard & Explainability:  Ensure that meta fields from edges are propagated all the way into the cockpit dashboard.  This includes the explain string and the list of edges_triggered with per‑edge contributions.

Blueprint for Edge Evaluation & Scoring

To complete the adaptive learning loop, each run should compute quantitative metrics for each edge and store them in a research database.  Metrics such as Sharpe ratio, hit rate, max drawdown, correlation between edges and information coefficient can be computed from the trade log.  The Governor can then:
	1.	Reinforce high‑performing edges by increasing their weights.
	2.	Down‑weight underperforming edges.
	3.	Explore new edges or parameter variants when performance deteriorates.
	4.	Provide transparency by exposing the metrics and weight updates in the cockpit dashboard.

Future Extensions

The current architecture can be extended beyond technical indicators:
	•	Macro & Fundamental Data:  Integrate macroeconomic indicators or fundamental metrics (e.g., earnings surprises) as new data sources in the DataManager.  Edges can then use these features to compute signals.
	•	Sentiment Analysis:  Add edges that process news, social media or analyst sentiment.  Natural‑language‑processing models can output a sentiment score per ticker which can be fed into compute_signals.
	•	Reinforcement‑Learning Agent:  Build a Governor that uses reinforcement learning to adjust edge weights directly based on cumulative reward.  This agent would observe the current state (portfolio, market regime, past performance) and output new weights for edges.

Summary

The absence of actionable signals in the Trading Machine is primarily due to mismatched interfaces between edge modules and the AlphaEngine’s SignalCollector.  Many edges return lists of rich signal objects or nested dictionaries, whereas the collector expects a simple dict[ticker → float].  Additionally, cross‑sectional edges expect a pd.DataFrame but are passed a dictionary, causing runtime errors.  By unifying the edge API, making the collector type‑aware, and assembling cross‑sectional DataFrames when needed, the signal pipeline can be repaired.  Comprehensive unit tests and a refactored architecture will help the system evolve toward the envisioned self‑learning trading engine.