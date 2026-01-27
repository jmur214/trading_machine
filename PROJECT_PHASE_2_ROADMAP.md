# Phase 2 Roadmap: Intelligence & Robustness

**Goal:** Transform the system from a "functioning machine" into a "smart, self-maintaining laboratory" that generates robust profit.

---

## 🟢 Phase 1: Ecosystem Hygiene (Scale Management) [COMPLETED]
**Objective:** Prevent "Evolutionary Bloat" (disk usage/compute).
*   **Delivered:** `StrategyPruner`, Gene Hashing in `EdgeGenerator`.

## 🔵 Phase 2: Context-Aware Intelligence (Regimes) [COMPLETED]
**Objective:** "Know When to Fold 'Em". Use math principles dynamically based on Market Regime.
*   **Delivered:** `RegimeDetector` (Bull/Bear/Neutral), `EdgeGenerator` support for Regime Gates, `CompositeEdge` interpretation of new Math Genes (SMA, Rank, Residual).

## 🟣 Phase 3: Advanced Portfolio Math & Paradoxes [COMPLETED]
**Objective:** Non-Correlated Returns & Parrondo's Principle.
*   **Delivered:**
    *   **StrategyGovernor:** Correlation Penalty Logic (Rewarding Hedges).
    *   **PortfolioPolicy:** Parrondo Fixed Rebalancing Mode (Periodic Allocation).
    *   **DiscoveryEngine:** Logic to generate Short/Hedge strategies using `direction="short"`.
    *   **Validation:** Confirmed Rebalancing and Correlation logic works in `system_validity_check.py`.

## 🟠 Phase 4: Reality Calibration (Robustness)
**Objective:** Verify "True Profit" vs "Overfitting".
*   **Solution:**
    *   **Walk-Forward Validation (WFO):** Implement a strict train/test split harness.
    *   **The "Luck Test":** Run the exact same evolution cycle on `SYNTH-A` (Random Walk). If the machine claims "Profit" on random data, it is broken (hallucinating alpha).
    *   **OOS Holdout:** Lock away the most recent 6 months.

## 🔴 Phase 5: Dashboard 2.0 (The Cockpit)
**Objective:** Visual Proof.
*   **Updates:**
    *   **Evolution Tab:** Tree view of generated strategies (Gen 1 -> Gen 2).
    *   **Regime Dial:** Visual indicator of "Are we in Bull or Bear?".
    *   **Correlation Heatmap:** Visual matrix of active edges.

---

## Execution Order
We are currently at **Phase 4 (Reality Calibration)**.
**Next Step:** Execute Walk-Forward Validation logic (to be built) and "Luck Test".
