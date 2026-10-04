"""Tiny in-memory vector store (cosine similarity via numpy).

For a few hundred listings per search a FAISS/Chroma index adds dependencies but no
benefit; the interface (add / search) is the same, so swapping one in later is easy.
"""
from __future__ import annotations

import numpy as np


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._vecs: np.ndarray | None = None

    def add(self, vectors: np.ndarray) -> None:
        v = np.asarray(vectors, dtype="float32")
        norms = np.linalg.norm(v, axis=1, keepdims=True)
        self._vecs = v / np.clip(norms, 1e-9, None)

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        if self._vecs is None or len(self._vecs) == 0:
            return []
        q = np.asarray(query_vec, dtype="float32")
        q = q / max(float(np.linalg.norm(q)), 1e-9)
        sims = self._vecs @ q
        idx = np.argsort(-sims)[:k]
        return [(int(i), float(sims[i])) for i in idx]
