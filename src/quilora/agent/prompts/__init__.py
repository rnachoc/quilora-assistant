"""Prompt templates live next to the code that uses them and are versioned with it.

Templates are store-agnostic: everything that belongs to one shop (name, description,
languages, catalog language, support hours) is filled in from the store profile.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from quilora.store.profile import StoreProfile

_DIR = Path(__file__).parent

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "it": "Italian",
                  "pt": "Portuguese", "de": "German", "nl": "Dutch", "sv": "Swedish"}


def _language_list(codes: list[str]) -> str:
    """'Spanish and English' from ['es', 'en']."""
    names = [LANGUAGE_NAMES.get(c, c) for c in codes]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def render(name: str, *, today: date, store: StoreProfile) -> str:
    """Load a prompt template by name and fill in today's date and the store's details."""
    template = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    values = {
        "today": today.isoformat(),
        "timezone": store.timezone,
        "store_name": store.name,
        "store_description": store.description,
        "languages": _language_list(store.languages),
        "catalog_language": LANGUAGE_NAMES.get(store.catalog.language, store.catalog.language),
        "support_hours": store.contact.hours,
    }
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template
