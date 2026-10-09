"""Minimal `.env` loader.

Written by hand instead of adding python-dotenv: we only need KEY=VALUE lines, comments
and blank lines. Variables already present in the environment win, so Docker/CI settings
are never overridden by a local file.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file without overriding existing variables."""
    file = Path(path)
    if not file.is_file():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
