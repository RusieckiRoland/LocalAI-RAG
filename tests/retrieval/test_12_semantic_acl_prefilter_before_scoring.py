# tests/retrieval/test_12_semantic_acl_prefilter_before_scoring.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from vector_search.models import VectorSearchFilters, VectorSearchRequest
from vector_search.unified_search import search_unified


class DummyFlatIndex:
    """
    Minimal IndexFlatIP-like object for strict prefilter path:
    - exposes .xb and .d like IndexFlat
    - .search() must NOT be called (we want prefilter-before-scoring proof)
    """
    def __init__(self, vectors: np.ndarray):
        assert vectors.dtype == np.float32
        assert vectors.ndim == 2
        self.d = int(vectors.shape[1])
        self.ntotal = int(vectors.shape[0])

        # store vectors in a "faiss-like" flat buffer; faiss.vector_to_array can read it
        # In practice, faiss.IndexFlat stores this internally. For unit test, we mimic it.
        self._flat = vectors.reshape(-1).astype(np.float32, copy=False)
        self.xb = self._flat  # works with faiss.vector_to_array in real runtime

    def search(self, vectors: Any, k: int) -> Tuple[np.ndarray, np.ndarray]:
        raise AssertionError("index.search() must NOT be called when filters are present (strict prefilter required)")


class DummyEmbed:
    def __init__(self, vec: np.ndarray):
        self._vec = vec.astype(np.float32, copy=False)

    def encode(self, texts: Any, convert_to_numpy: bool = True) -> np.ndarray:
        return self._vec.reshape(1, -1).astype(np.float32, copy=False)


def test_12_semantic_acl_is_applied_before_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    HARD PROOF:
    - If implementation calls index.search() first -> test FAILS (AssertionError in DummyFlatIndex.search)
    - Correct behavior: filter first -> score only allowed subset via flat vectors
    """
    import vector_search.unified_search as us

    # normalize_L2 is irrelevant for this proof; keep deterministic
    monkeypatch.setattr(us.faiss, "normalize_L2", lambda x: None, raising=True)

    # Build 6 vectors in 4D:
    # Make Public docs (4,5) very similar to query, Internal docs (0..3) also similar,
    # but we only want Public to survive.
    vectors = np.array(
        [
            [1, 0, 0, 0],  # 0 Internal
            [0.9, 0.1, 0, 0],  # 1 Internal
            [0.8, 0.2, 0, 0],  # 2 Internal
            [0.7, 0.3, 0, 0],  # 3 Internal
            [1, 0, 0, 0],  # 4 Public
            [0.95, 0.05, 0, 0],  # 5 Public
        ],
        dtype=np.float32,
    )

    index = DummyFlatIndex(vectors=vectors)

    metadata: List[Dict[str, Any]] = [
        {"id": "d0", "permission_tags_all": ["Internal"], "text": "x"},
        {"id": "d1", "permission_tags_all": ["Internal"], "text": "x"},
        {"id": "d2", "permission_tags_all": ["Internal"], "text": "x"},
        {"id": "d3", "permission_tags_all": ["Internal"], "text": "x"},
        {"id": "d4", "permission_tags_all": ["Public"], "text": "x"},
        {"id": "d5", "permission_tags_all": ["Public"], "text": "x"},
    ]

    # Query vector points along [1,0,0,0]
    embed = DummyEmbed(vec=np.array([1, 0, 0, 0], dtype=np.float32))

    req = VectorSearchRequest(
        text_query="anything",
        top_k=2,
        oversample_factor=5,
        filters=VectorSearchFilters(permission_tags_all=["Public"]),
        include_text_preview=False,
    )

    out = search_unified(index=index, metadata=metadata, embed_model=embed, request=req)

    assert [r["Id"] for r in out] == ["d4", "d5"]
    assert all("Public" in (r["Metadata"].get("permission_tags_all") or []) for r in out)
