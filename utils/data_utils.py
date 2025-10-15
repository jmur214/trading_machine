from pathlib import Path

def ensure_dirs(*dirs: str):
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)