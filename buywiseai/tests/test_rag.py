from buywise.rag.retriever import rrf
from buywise.rag.store import InMemoryVectorStore
import numpy as np


def test_rrf_prefers_items_ranked_well_by_both():
    fused = rrf([[0, 1, 2], [0, 2, 1]])
    assert max(fused, key=fused.get) == 0
    assert fused[1] < fused[0] and fused[2] < fused[0]


def test_rrf_handles_item_missing_from_one_ranking():
    fused = rrf([[0, 1], [1]])
    assert set(fused) == {0, 1}


def test_vector_store_cosine_search():
    store = InMemoryVectorStore()
    store.add(np.array([[1, 0], [0, 1], [1, 1]], dtype="float32"))
    hits = store.search(np.array([1, 0.1], dtype="float32"), k=2)
    assert hits[0][0] == 0 and len(hits) == 2
