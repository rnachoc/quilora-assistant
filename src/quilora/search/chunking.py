"""Split policy documents into short, citable chunks.

Why sections? They are the unit a human would cite ("Returns Policy, section 1"), they
are short enough for small embedding models, and they keep one idea per chunk.

Real shops do not write policies in one format, so the parser accepts:
  * "## 1. Title" numbered sections (cited with their own number),
  * "## Title" sections without numbers (numbered in order),
  * no sections at all (split into paragraphs, grouped up to MAX_WORDS),
and sections longer than MAX_WORDS are split into consecutive parts with the same number.
The document ID comes from a `<!-- doc_id: XXX -->` marker or, failing that, the file name.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_WORDS = 80  # small multilingual embedding models truncate at ~128 tokens

_TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_DOC_ID = re.compile(r"<!--\s*doc_id:\s*([A-Z0-9_]+)")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SECTION = re.compile(r"^##\s+(?:(\d+)\.\s+)?(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class PolicyChunk:
    """One section (or part of a section) of a policy document, the unit we search and cite."""

    id: str
    doc_id: str
    doc_title: str
    section_no: int
    section_title: str
    content: str

    @property
    def citation(self) -> str:
        """Human-readable citation, e.g. 'Returns Policy §1 (Return window)'."""
        return f"{self.doc_title} §{self.section_no} ({self.section_title})"


def _split_words(text: str, limit: int = MAX_WORDS) -> list[str]:
    """Split text into parts of at most `limit` words, preferring sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    parts, current = [], []
    for sentence in sentences:
        words = sentence.split()
        if current and len(current) + len(words) > limit:
            parts.append(" ".join(current))
            current = []
        current.extend(words)
        while len(current) > limit:  # a single very long sentence
            parts.append(" ".join(current[:limit]))
            current = current[limit:]
    if current:
        parts.append(" ".join(current))
    return parts


def _doc_id_from_name(name: str) -> str:
    """'refund-policy' -> 'REFUND_POLICY' for documents without a doc_id marker."""
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "POLICY"


def parse_policy(markdown: str, default_id: str = "POLICY",
                 default_title: str = "Policy") -> list[PolicyChunk]:
    """Split one policy document into chunks with stable IDs (DOC-3, or DOC-3-2 for parts)."""
    title_match = _TITLE.search(markdown)
    doc_match = _DOC_ID.search(markdown)
    doc_title = title_match.group(1).strip() if title_match else default_title
    doc_id = doc_match.group(1) if doc_match else default_id
    text = _COMMENT.sub("", markdown)
    if title_match:
        text = text.replace(title_match.group(0), "", 1)

    sections = list(_SECTION.finditer(text))
    raw: list[tuple[int, str, str]] = []
    if sections:
        for i, match in enumerate(sections):
            end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
            number = int(match.group(1)) if match.group(1) else i + 1
            raw.append((number, match.group(2).strip(), text[match.end():end]))
    else:
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        groups = _split_words(" ".join(paragraphs))
        raw = [(i, f"Part {i}", body) for i, body in enumerate(groups, start=1)]

    chunks = []
    for number, title, body in raw:
        parts = _split_words(body)
        for k, part in enumerate(parts, start=1):
            suffix = f"-{k}" if len(parts) > 1 else ""
            chunks.append(PolicyChunk(id=f"{doc_id}-{number}{suffix}", doc_id=doc_id,
                                      doc_title=doc_title, section_no=number,
                                      section_title=title, content=part))
    return chunks


def load_policies(directory: Path) -> list[PolicyChunk]:
    """Parse every policy file (.md or .txt) in a directory."""
    chunks: list[PolicyChunk] = []
    files = sorted([*directory.glob("*.md"), *directory.glob("*.txt")])
    for file in files:
        chunks.extend(parse_policy(
            file.read_text(encoding="utf-8"),
            default_id=_doc_id_from_name(file.stem),
            default_title=file.stem.replace("-", " ").replace("_", " ").title(),
        ))
    ids = [c.id for c in chunks]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate policy chunk IDs (check doc_id markers): {duplicates}")
    return chunks
