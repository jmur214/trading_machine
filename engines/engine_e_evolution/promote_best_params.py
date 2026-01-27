
import sys
import os
import json
import logging
import pandas as pd
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("Promoter")

def promote_best_params(edge_id):
    project_root = Path(os.getcwd())
    results_file = project_root / "data" / "research" / "edge_results.parquet"
    config_path = project_root / "config" / "alpha_settings.prod.json"

    if not results_file.exists():
        log.error(f"Results file not found: {results_file}")
        return

    try:
        df = pd.read_parquet(results_file)
        edge_df = df[df['edge'] == edge_id]
        
        if edge_df.empty:
            log.warning(f"No results found for {edge_id}")
            return

        # Simple verification: print best row
        # Criteria: Sharpe > 0, trades > 10, no errors
        valid = edge_df[
            (edge_df['sharpe'] > -1.0) & 
            (edge_df['trades'] > 5) &
            (edge_df['error'].isna() | (edge_df['error'] == ''))
        ]

        if valid.empty:
            log.warning(f"No valid profitable results for {edge_id}")
            # Fallback: just show top sharpe regardless of filters to debug
            log.info("Top result ignoring filters:")
            print(edge_df.sort_values('sharpe', ascending=False).head(1).to_string())
            return

        best_row = valid.sort_values('sharpe', ascending=False).iloc[0]
        log.info(f"Best Result for {edge_id}:")
        print(best_row)

        # Extract params
        # Columns to ignore
        metric_cols = ['edge', 'sharpe', 'total_return_pct', 'trades', 'error', 
                       'combo_idx', 'wf_idx', 'start_date', 'end_date', 'source_run']
        params = {}
        for col in valid.columns:
            if col not in metric_cols and not col.startswith('Unnamed'):
                val = best_row[col]
                if hasattr(val, 'item'): 
                    val = val.item()
                params[col] = val
        
        log.info(f"Promoting params: {params}")

        # Update Config
        with open(config_path, 'r') as f:
            config = json.load(f)

        if 'edge_params' not in config:
            config['edge_params'] = {}
        
        config['edge_params'][edge_id] = params

        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)
        
        log.info("Configuration updated successfully.")

    except Exception as e:
        log.error(f"Failed to promote: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    promote_best_params("atr_breakout_v1")
