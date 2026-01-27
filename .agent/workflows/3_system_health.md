---
description: Run system diagnostics and health checks
---

# System Health Workflow

Run this to verify the integrity of the trading machine.

1.  **Run Diagnostics**
    *   Execute the full system health check:
        ```bash
        // turbo
        python -m scripts.run_diagnostics
        ```
    *   Check for any `FAIL` or `WARNING` messages in the output.

2.  **Sandbox Feedback Loop**
    *   Run the edge feedback mechanism in sandbox mode to ensure the Governor logic is working without affecting production weights:
        ```bash
        // turbo
        python -m analytics.edge_feedback --mode sandbox
        ```

3.  **Continuous Validation (Optional)**
    *   If you need to run a quick validation pass:
        ```bash
        python -m scripts.continuous_validation --once
        ```
