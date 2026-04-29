---
name: Macro tilt edges - full-history threshold vs window-data mismatch
description: Macro edges that auto-threshold on full FRED history won't fire on modern (post-2010) data because pre-2010 stress events distort the distribution
type: feedback
---

`macro_credit_spread_v1` thresholds at `mean ± 1*std` of the full BAA-AAA series. Full-history mean is 0.99% with std 0.40%, which encodes 1980s stagflation, 2008 GFC, and 2020 COVID. The "wide" threshold of 1.40% has not been touched since 2020. Result: edge fires 0% of days in 2021-2024 = it does not exist in production.

**Why:** Same shape applies to `macro_real_rate_v1` (DFII10), `macro_unemployment_momentum_v1` (UNRATE 3m change), and any future macro tilt edge that auto-thresholds on full series statistics. Modern macro is mean-reverting around a different level than the 1970-2024 mean.

**How to apply:**
1. Macro tilt thresholds should be computed on a **rolling window** of recent history (e.g., trailing 5-10 years) — long enough to capture cycle, short enough that 1980s pre-Volcker doesn't dominate.
2. Alternatively, use **percentile-based** thresholds — fire on top/bottom decile of trailing window — which is automatically self-normalizing.
3. When validating a macro edge, always compute fire-rate on the production backtest window before promoting; it's the same trap as Engine D's PBO check but for environmental data instead of price.
4. Do not trust `mean ± k*std` over 50+ year financial series. The series isn't stationary.
