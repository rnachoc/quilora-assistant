"""Text embeddings for semantic policy search.

Anthropic does not offer an embeddings endpoint. Options considered (ADR 0009): a hosted
API (e.g. Voyage AI) or a small local model. We use a local multilingual model through
`fastembed` (ONNX runtime, no PyTorch), so embeddings are free, private and reproducible,
and Spanish queries can match English policy text.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Local ONNX model. Downloaded on first use (~0.2 GB) into ./models_cache."""

    def __init__(self, model_name: str, cache_dir: str = "models_cache") -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # optional dependency
            raise RuntimeError(
                "Vector search needs the optional dependency: pip install -e '.[embeddings]'"
            ) from exc
        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dimensions = len(self.embed_query("dimension probe"))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.embed([text]))).tolist()


class HashingEmbedder:
    """Deterministic bag-of-words hashing embedder for TESTS ONLY (no semantics)."""

    model_name = "test-hashing"

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for word in re.findall(r"\w+", text.lower()):
            digest = hashlib.md5(word.encode(), usedforsecurity=False).digest()
            vec[int.from_bytes(digest[:4], "little") % self.dimensions] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def to_pgvector(vector: list[float]) -> str:
    """pgvector accepts the text form '[0.1,0.2,...]'; avoids an extra adapter dependency."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
