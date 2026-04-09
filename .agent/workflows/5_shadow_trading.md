---
description: Run the Shadow Trading Loop (Phase 2 Validation)
---

# Shadow Trading Workflow

This workflow executes the "Shadow Realm" process, running candidate strategies in a virtual environment alongside live trading.

## 1. Update Data
Ensure we have the latest market data to run the shadow simulation against.

```bash
python scripts/update_data.py
```

## 2. Run Shadow Loop
Execute the shadow trading script. This will:
- Load the ticker universe and data.
- Compute technical and fundamental features.
- Run candidate strategies (e.g. Hunter Rules).
- Execute virtual trades via `ShadowBroker`.
- Log results to `data/shadow/`.

```bash
python scripts/run_shadow_paper.py
```

## 3. Review Performance
Check the shadow account status and trade logs.

```bash
cat data/shadow/account.csv
cat data/shadow/trades.csv
```
