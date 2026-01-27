---
description: Research and validate a specific trading edge
---

# Edge Research Workflow

This workflow helps you research, parameter-sweep, and validate a single edge.

1.  **Identify Edge**
    *   Ask the user which edge they want to research (e.g., `MomentumAlpha`, `MeanReversion`).

2.  **Run Edge Harness**
    *   Run the harness with a walk-forward validation:
        ```bash
        python -m research.edge_harness \
          --edge <EDGE_NAME> \
          --param-grid config/grids/<EDGE_NAME>.json \
          --walk-forward "2023-01-01:2025-01-01"
        ```
    *   *Note: Replace `<EDGE_NAME>` with the actual edge name.*

3.  **Inspect Results**
    *   View the output in `data/research/edge_results.parquet` (or the summary printed to console).
    *   If the results are promising, suggest running a full backtest with this edge enabled.

4.  **View Database**
    *   Optionally, inspect the global research database:
        ```bash
        python -m research.edge_db_viewer
        ```
