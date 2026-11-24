"""Read settings from a .env file without extra dependencies."""
from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """Load KEY=value lines into os.environ (real env vars win)."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.split(" #", 1)[0].strip().strip("\"'")
            if value:
                os.environ.setdefault(key.strip(), value)
