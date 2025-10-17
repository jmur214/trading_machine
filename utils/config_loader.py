# utils/config_loader.py
import json
from pathlib import Path
from typing import Any, Dict


def load_json(path: str) -> Dict[str, Any]:
    """
    Safely load and validate a JSON configuration file.
    Returns an empty dict if file is missing or malformed.

    Features:
      - Automatic expansion of '~' and relative paths.
      - Prints clear error messages instead of crashing.
      - Ensures returned data is always a dict.
    """
    path_obj = Path(path).expanduser().resolve()
    if not path_obj.exists():
        print(f"[CONFIG][WARN] Missing config file: {path_obj}")
        return {}

    try:
        with open(path_obj, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                print(f"[CONFIG][ERROR] Config file must contain a JSON object (dict): {path_obj}")
                return {}
            return data
    except json.JSONDecodeError as e:
        print(f"[CONFIG][ERROR] Invalid JSON format in {path_obj}: {e}")
        return {}
    except Exception as e:
        print(f"[CONFIG][ERROR] Unexpected error reading {path_obj}: {e}")
        return {}


def save_json(path: str, data: Dict[str, Any]) -> None:
    """
    Write dictionary data safely to JSON file.
    Creates parent directories if needed.
    """
    path_obj = Path(path).expanduser().resolve()
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(path_obj, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, sort_keys=True)
        print(f"[CONFIG] Saved config to {path_obj}")
    except Exception as e:
        print(f"[CONFIG][ERROR] Could not save JSON to {path_obj}: {e}")