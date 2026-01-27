
import json
import os
from pathlib import Path

class StrategyPruner:
    """
    The 'Reaper' of the Trading Machine.
    Cleans up strategies that have been rejected or are redundant.
    """
    
    def __init__(self, registry_path="data/governor/genome_registry.json", metrics_path="data/governor/edge_metrics.json"):
        self.registry_path = Path(registry_path)
        self.metrics_path = Path(metrics_path)
        
    def prune(self, dry_run=False):
        if not self.registry_path.exists():
            print("No registry found.")
            return

        with open(self.registry_path, "r") as f:
            registry = json.load(f)
            
        # Mock Metrics Load (In reality, load from metrics_path)
        # For now, we assume we want to prune anything with 'status': 'rejected'
        # Or we can pass a list of IDs to prune.
        
        # Let's say we prune based on file existence check first to clean ghost entries
        # And specifically prune IDs starting with "autogen_value_rsi" for this test.
        
        keys_to_remove = []
        
        print(f"[PRUNER] Scanning {len(registry)} registered strategies...")
        
        for genome_hash, entry in registry.items():
            edge_id = entry.get("edge_id")
            file_path = Path(entry.get("path"))
            
            # CRITERIA: Example - Prune the test files we just made
            if "test" in edge_id or "duplicate" in edge_id:
                print(f"[PRUNER] Marked for deletion: {edge_id}")
                
                # Mark registry key for removal
                keys_to_remove.append(genome_hash)

                if not dry_run:
                    # 1. Delete File
                    if file_path.exists():
                        try:
                            file_path.unlink()
                            print(f"  - Deleted {file_path}")
                        except Exception as e:
                            print(f"  - Error deleting {file_path}: {e}")
                    else:
                        print(f"  - File already gone: {file_path}")
                    
        # Archive before delete
        if not dry_run and keys_to_remove:
            self._archive_rejected(keys_to_remove, registry)
            
            for k in keys_to_remove:
                del registry[k]
                
            with open(self.registry_path, "w") as f:
                json.dump(registry, f, indent=4)
            print(f"[PRUNER] Removed {len(keys_to_remove)} entries from registry.")
        elif dry_run:
            print(f"[PRUNER] Dry run complete. {len(keys_to_remove)} strategies would be removed (and archived).")

    def _archive_rejected(self, keys, registry):
        """Save the definition of rejected strategies to a permanent graveyard."""
        archive_path = self.metrics_path.parent / "rejected_genomes.json"
        
        if archive_path.exists():
            try:
                with open(archive_path, "r") as f:
                    archive = json.load(f)
            except:
                archive = {}
        else:
            archive = {}
            
        count = 0
        for k in keys:
            if k in registry:
                # We save the genes and the hash, but NOT the file path (since we delete it)
                item = registry[k]
                archive[k] = {
                    "edge_id": item.get("edge_id"),
                    "genes": item.get("genes"),
                    "archived_at": "now" # TODO: use timestamp
                }
                count += 1
        
        with open(archive_path, "w") as f:
            json.dump(archive, f, indent=4)
        print(f"[PRUNER] Archived {count} genomes to {archive_path}")

    def clean_logs(self, keep_last_n=10, dry_run=False):
        """
        Removes old backtest log folders from data/trade_logs.
        Keeps the N most recent runs.
        """
        log_dir = Path("data/trade_logs")
        if not log_dir.exists():
            return
            
        # List all run directories
        runs = []
        for d in log_dir.iterdir():
            if d.is_dir() and len(d.name) > 10: # Rough UUID check
                # Get modification time
                mtime = d.stat().st_mtime
                runs.append((mtime, d))
        
        # Sort by time desc
        runs.sort(key=lambda x: x[0], reverse=True)
        
        # Keep top N
        to_delete = runs[keep_last_n:]
        
        print(f"[LOG_CLEANER] Found {len(runs)} logs. Keeping {keep_last_n}. Deleting {len(to_delete)}.")
        
        for _, d in to_delete:
            print(f"  - Marking log for deletion: {d.name}")
            if not dry_run:
                try:
                    import shutil
                    shutil.rmtree(d)
                    print(f"    Deleted.")
                except Exception as e:
                    print(f"    Error: {e}")

if __name__ == "__main__":
    pruner = StrategyPruner()
    print("--- Strategy Pruning (Dry Run) ---")
    pruner.prune(dry_run=True)
    print("\n--- Log Cleaning (Dry Run) ---")
    pruner.clean_logs(keep_last_n=5, dry_run=True)
