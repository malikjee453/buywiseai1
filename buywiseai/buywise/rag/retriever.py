"""Hybrid retrieval: BM25 + dense embeddings -> reciprocal rank fusion -> cross-encoder rerank.

Every heavy component degrades gracefully: no sentence-transformers => BM25 only.
"""
from __future__ import annotations

import logging
import re
import threading

import numpy as np

from buywise.rag.store import InMemoryVectorStore

log = logging.getLogger(__name__)

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge query instruction

_models: dict = {}
_lock = threading.Lock()
_emb_cache: dict[str, np.ndarray] = {}


def _load(kind: str):
    """Lazy, process-wide model cache. Returns None if unavailable."""
    with _lock:
        if kind in _models:
            return _models[kind]
        try:
            if kind == "embed":
                from sentence_transformers import SentenceTransformer

                _models[kind] = SentenceTransformer(EMBED_MODEL)
            else:
                from sentence_transformers import CrossEncoder

                _models[kind] = CrossEncoder(RERANK_MODEL)
        except Exception as e:
            log.warning("Could not load %s model (%s); feature disabled", kind, e)
            _models[kind] = None
        return _models[kind]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion over several ranked index lists."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return scores


class HybridRetriever:
    def __init__(self, use_dense: bool = True, use_reranker: bool = True, rerank_top: int = 150):
        self.use_dense = use_dense
        self.use_reranker = use_reranker
        self.rerank_top = rerank_top
        self.mode = "bm25"

    @staticmethod
    def _doc(l) -> str:
        return f"{l.title}. {l.snippet}".strip()

    def _bm25_ranking(self, query: str, docs: list[str]) -> list[int]:
        from rank_bm25 import BM25Okapi

        bm25 = BM25Okapi([_tokens(d) or ["_"] for d in docs])
        scores = bm25.get_scores(_tokens(query))
        return [int(i) for i in np.argsort(-scores)]

    def _dense_ranking(self, query: str, docs: list[str]) -> list[int] | None:
        model = _load("embed") if self.use_dense else None
        if model is None:
            return None
        missing = [d for d in docs if d not in _emb_cache]
        if missing:
            for d, v in zip(missing, model.encode(missing, normalize_embeddings=True, batch_size=32)):
                _emb_cache[d] = v
        store = InMemoryVectorStore()
        store.add(np.stack([_emb_cache[d] for d in docs]))
        qv = model.encode([_QUERY_PREFIX + query], normalize_embeddings=True)[0]
        return [i for i, _ in store.search(qv, k=len(docs))]

    def rank(self, query: str, listings: list) -> list:
        """Score listings in place (.relevance, .score) and return them best-first."""
        if not listings:
            return []
        docs = [self._doc(l) for l in listings]
        rankings = [self._bm25_ranking(query, docs)]
        mode = ["bm25"]
        dense = self._dense_ranking(query, docs)
        if dense is not None:
            rankings.append(dense)
            mode.append("dense")
        fused = rrf(rankings)
        order = sorted(fused, key=fused.get, reverse=True)
        top_fused = max(fused.values()) or 1.0
        for i, l in enumerate(listings):
            l.score = fused.get(i, 0.0) / top_fused           # 0..1 fallback score
            l.relevance = l.score
        reranker = _load("rerank") if self.use_reranker else None
        if reranker is not None:
            head = order[: self.rerank_top]
            ce = reranker.predict([(query, docs[i]) for i in head])
            for i, s in zip(head, ce):
                listings[i].relevance = float(s)               # raw logit (~ -11..+10)
                listings[i].score = 1.0 + float(s)             # keeps reranked items above the rest
            for i in order[self.rerank_top:]:
                listings[i].relevance = -99.0
                listings[i].score = -99.0
            mode.append("rerank")
        self.mode = "+".join(mode)
        return sorted(listings, key=lambda l: l.score, reverse=True)
