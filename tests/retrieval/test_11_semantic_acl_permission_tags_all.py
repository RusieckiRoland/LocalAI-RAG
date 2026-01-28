# tests/retrieval/test_11_semantic_acl_permission_tags_all.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from vector_search.models import VectorSearchFilters, VectorSearchRequest
from vector_search.unified_search import metadata_matches_filters, search_unified


pytestmark = pytest.mark.unit


class DummyFlatIndex:
    """
    Minimal IndexFlatIP-like stub for strict ACL path:
    - exposes .xb and .d
    - .search() exists but SHOULD NOT be called in strict ACL mode
    """
    def __init__(self, vectors: np.ndarray) -> None:
        assert vectors.dtype == np.float32
        assert vectors.ndim == 2
        self.d = int(vectors.shape[1])
        self.ntotal = int(vectors.shape[0])
        # store as flat buffer; unified_search supports numpy xb explicitly
        self.xb = vectors.reshape(-1).astype(np.float32, copy=False)

    def search(self, vectors: Any, k: int) -> Tuple[np.ndarray, np.ndarray]:
        raise AssertionError("index.search() must NOT be called in strict ACL mode")


class DummyEmbed:
    def __init__(self, vec: np.ndarray) -> None:
        self._vec = vec.astype(np.float32, copy=False)

    def encode(self, texts: Any, convert_to_numpy: bool = True) -> np.ndarray:
        return self._vec.reshape(1, -1).astype(np.float32, copy=False)


def test_11_metadata_matches_filters_enforces_permission_tags_all() -> None:
    meta = {"permission_tags_all": ["Public", "TeamA"]}

    assert metadata_matches_filters(meta, VectorSearchFilters(permission_tags_all=["Public"])) is True
    assert metadata_matches_filters(meta, VectorSearchFilters(permission_tags_all=["Public", "TeamA"])) is True
    assert metadata_matches_filters(meta, VectorSearchFilters(permission_tags_all=["Public", "Nope"])) is False

    # Also verify dict-style input
    assert metadata_matches_filters(meta, {"permission_tags_all": ["Public"]}) is True
    assert metadata_matches_filters(meta, {"permission_tags_all": ["Nope"]}) is False


def test_11_semantic_search_filters_by_acl_tags_hard_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    HARD PROOF (ACL is enforced):

    We construct vectors so that:
      - Internal docs would score highest for the query
      - Public docs score lower
    With ACL filter permission_tags_all=["Public"], results MUST be Public only.
    """
    import vector_search.unified_search as us
    monkeypatch.setattr(us.faiss, "normalize_L2", lambda x: None, raising=True)

    # Query vector points along [1,0,0,0]
    embed = DummyEmbed(vec=np.array([1, 0, 0, 0], dtype=np.float32))

    # Vectors for 6 docs in 4D:
    # docs 0..3 (Internal) are VERY similar to query
    # docs 4..5 (Public) are less similar
    vectors = np.array(
        [
            [1.00, 0.00, 0.00, 0.00],  # d0 Internal (best)
            [0.99, 0.01, 0.00, 0.00],  # d1 Internal
            [0.98, 0.02, 0.00, 0.00],  # d2 Internal
            [0.97, 0.03, 0.00, 0.00],  # d3 Internal
            [0.60, 0.40, 0.00, 0.00],  # d4 Public (worse)
            [0.59, 0.41, 0.00, 0.00],  # d5 Public (worse)
        ],
        dtype=np.float32,
    )

    index = DummyFlatIndex(vectors=vectors)

    metadata: List[Dict[str, Any]] = [
        {"id": "d0", "source_file": "a.cs", "permission_tags_all": ["Internal"], "text": "x"},
        {"id": "d1", "source_file": "b.cs", "permission_tags_all": ["Internal"], "text": "x"},
        {"id": "d2", "source_file": "c.cs", "permission_tags_all": ["Internal"], "text": "x"},
        {"id": "d3", "source_file": "d.cs", "permission_tags_all": ["Internal"], "text": "x"},
        {"id": "d4", "source_file": "e.cs", "permission_tags_all": ["Public"], "text": "x"},
        {"id": "d5", "source_file": "f.cs", "permission_tags_all": ["Public"], "text": "x"},
    ]

    req = VectorSearchRequest(
        text_query="anything",
        top_k=2,
        oversample_factor=10,
        filters=VectorSearchFilters(permission_tags_all=["Public"]),
        include_text_preview=False,
    )

    out = search_unified(index=index, metadata=metadata, embed_model=embed, request=req)

    assert len(out) == 2
    assert [r["Id"] for r in out] == ["d4", "d5"]
    assert all("Public" in (r["Metadata"].get("permission_tags_all") or []) for r in out)
