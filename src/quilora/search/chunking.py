"""Split policy Markdown files into citable chunks, one per `## N. Title` section.

Why sections? They are the unit a human would cite ("Returns Policy, section 1"), they
are short enough for small embedding models, and they keep one idea per chunk.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_DOC_ID = re.compile(r"<!--\s*doc_id:\s*([A-Z]+)")
_SECTION = re.compile(r"^##\s+(\d+)\.\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class PolicyChunk:
    """One numbered section of a policy document, the unit we search and cite."""
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


def parse_policy(markdown: str) -> list[PolicyChunk]:
    """Split one policy Markdown file into section chunks with stable IDs."""
    title_match = _TITLE.search(markdown)
    doc_match = _DOC_ID.search(markdown)
    if not title_match or not doc_match:
        raise ValueError("Policy file needs a '# Title' and a '<!-- doc_id: XXX -->' marker")
    doc_title, doc_id = title_match.group(1).strip(), doc_match.group(1)

    sections = list(_SECTION.finditer(markdown))
    chunks = []
    for i, match in enumerate(sections):
        end = sections[i + 1].start() if i + 1 < len(sections) else len(markdown)
        body = " ".join(markdown[match.end() : end].split())
        number = int(match.group(1))
        chunks.append(
            PolicyChunk(
                id=f"{doc_id}-{number}",
                doc_id=doc_id,
                doc_title=doc_title,
                section_no=number,
                section_title=match.group(2).strip(),
                content=body,
            )
        )
    return chunks


def load_policies(directory: Path) -> list[PolicyChunk]:
    """Parse every policy file in a directory."""
    chunks: list[PolicyChunk] = []
    for file in sorted(directory.glob("*.md")):
        chunks.extend(parse_policy(file.read_text(encoding="utf-8")))
    return chunks
