import json
from pathlib import Path

def load_json(path: str):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with p.open("r") as f:
        return json.load(f)