"""Prompt templates live next to the code that uses them and are versioned with it.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

_DIR = Path(__file__).parent


def render(name: str, *, today: date) -> str:
    """Load a prompt template by name and fill in today's date."""
    template = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    return template.replace("{today}", today.isoformat())
