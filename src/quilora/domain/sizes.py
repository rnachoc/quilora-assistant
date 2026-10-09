"""Size label normalisation across shops and languages.

Shops write the same size in different ways: "XXL" / "2XL", "XXS" / "2XS",
"Talla única" / "One size" / "U", "38" / "EU 38". Matching a customer's "XXL" against a
catalog that says "2XL" must not fail, so every comparison goes through `canonical_size`.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import re
import unicodedata

_ALIASES = {
    "XXS": "2XS", "XXXS": "3XS", "XXL": "2XL", "XXXL": "3XL", "XXXXL": "4XL", "XXXXXL": "5XL",
    "EXTRA SMALL": "XS", "SMALL": "S", "MEDIUM": "M", "MEDIANA": "M", "PEQUENA": "S",
    "LARGE": "L", "GRANDE": "L", "EXTRA LARGE": "XL",
    "ONE SIZE": "ONE SIZE", "ONESIZE": "ONE SIZE", "OS": "ONE SIZE", "U": "ONE SIZE",
    "UNICA": "ONE SIZE", "TALLA UNICA": "ONE SIZE", "TU": "ONE SIZE", "UNIQUE": "ONE SIZE",
}


def _plain(text: str) -> str:
    """Upper-case without accents, so 'Única' and 'UNICA' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper().strip()


def canonical_size(label: str) -> str:
    """Canonical form of a size label: 'xxl' -> '2XL', 'EU 38' -> '38', 'Única' -> 'ONE SIZE'."""
    value = _plain(label)
    value = re.sub(r"^(TALLA|SIZE|EU|EUR)\s+", "", value)
    value = re.sub(r"\s+", " ", value)
    return _ALIASES.get(value, value)


def match_size(requested: str, available: list[str]) -> str | None:
    """The catalog's own label for a requested size, or None if the product lacks it."""
    wanted = canonical_size(requested)
    return next((s for s in available if canonical_size(s) == wanted), None)


def equivalent_labels(requested: str) -> list[str]:
    """All upper-case spellings that mean the same size (for SQL filters)."""
    wanted = canonical_size(requested)
    labels = {wanted, _plain(requested)}
    labels.update(alias for alias, canon in _ALIASES.items() if canon == wanted)
    return sorted(labels)


_LETTER_ORDER = ["5XS", "4XS", "3XS", "2XS", "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL",
                 "5XL", "6XL"]


def size_sort_key(label: str) -> tuple:
    """Order sizes naturally: letter sizes small to large, then numbers, then the rest."""
    canon = canonical_size(label)
    if canon in _LETTER_ORDER:
        return (0, _LETTER_ORDER.index(canon), "")
    number = re.match(r"^(\d+(?:[.,]\d+)?)", canon)
    if number:
        return (1, float(number.group(1).replace(",", ".")), canon)
    return (2, 0, canon)
