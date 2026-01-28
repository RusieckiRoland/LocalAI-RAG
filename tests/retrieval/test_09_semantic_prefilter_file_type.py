# tests/retrieval/test_09_semantic_prefilter_file_type.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from vector_search.models import VectorSearchFilters, VectorSearchRequest
from vector_search.unified_search import search_unified


pytestmark = pytest.mark.unit


class DummyIndex:
    """
    FAISS-like stub.
    We return a fixed (scores, ids) list regardless of query vector.
    Also records the 'k' requested by the caller.
    """

    def __init__(self, scores: List[float], ids: List[int]) -> None:
        assert len(scores) == len(ids)
        self._scores = np.array([scores], dtype=np.float32)
        self._ids = np.array([ids], dtype=np.int64)
        self.last_k: int | None = None

    def search(self, vectors: Any, k: int) -> Tuple[np.ndarray, np.ndarray]:
        self.last_k = int(k)
        # Return exactly first k items from our prepared stream
        return self._scores[:, :k], self._ids[:, :k]


class DummyEmbed:
    """Minimal encoder that returns the right shape for FAISS."""
    def encode(self, texts: Any, convert_to_numpy: bool = True) -> np.ndarray:
        v = np.zeros((1, 8), dtype=np.float32)
        return v


def _make_metadata(doc_count: int, *, sql_until: int) -> List[Dict[str, Any]]:
    """
    Build metadata aligned with FAISS row indices.
    Rows [0..sql_until-1] are SQL, the rest are CS.
    """
    out: List[Dict[str, Any]] = []
    for i in range(doc_count):
        ft = "sql" if i < sql_until else "cs"
        out.append(
            {
                "id": f"doc_{i}",
                "file_type": ft,
                "source_file": f"Db{i}.sql" if ft == "sql" else f"Code{i}.cs",
                "text": f"{ft} content {i}",
            }
        )
    return out


def test_09_semantic_filter_is_applied_before_topk_truncation_not_post_filtering(monkeypatch: Any) -> None:
    """
    HARD PROOF test for semantic (vector) retrieval behavior:

    We simulate FAISS returning raw_k candidates where:
      - the first TOP_K items are all SQL
      - CS items exist only AFTER TOP_K but WITHIN raw_k

    If implementation did: take TOP_K first, then filter => CS would be EMPTY => FAIL.
    Current implementation does: take raw_k, then filter, then take TOP_K => CS is NON-EMPTY => PASS.

    This proves: filtering happens BEFORE final top_k truncation (no starvation by post-filtering).
    """
    # Make faiss.normalize_L2 a no-op for this unit test (we don't test FAISS math here).
    import vector_search.unified_search as us
    monkeypatch.setattr(us.faiss, "normalize_L2", lambda x: None, raising=True)

    top_k = 3
    oversample = 5
    raw_k = top_k * oversample  # 15

    # Prepare FAISS stream: 0..14 returned in this exact order.
    ids = list(range(raw_k))

    # Scores: strictly decreasing, so unfiltered top_k becomes ids 0,1,2 (all SQL).
    scores = [1.0 - (i * 0.001) for i in range(raw_k)]

    # Metadata: first 10 are SQL, last 5 are CS (ids 10..14).
    metadata = _make_metadata(doc_count=raw_k, sql_until=10)

    index = DummyIndex(scores=scores, ids=ids)
    embed = DummyEmbed()

    # Sanity: unfiltered results should be SQL-only at top_k.
    req_global = VectorSearchRequest(
        text_query="foo bar",
        top_k=top_k,
        oversample_factor=oversample,
        filters=VectorSearchFilters(),
        include_text_preview=False,
    )
    global_hits = search_unified(index=index, metadata=metadata, embed_model=embed, request=req_global)
    assert global_hits, "Global semantic search returned empty results (unexpected)."
    assert all((h.get("Metadata") or {}).get("file_type") == "sql" for h in global_hits), (
        "Expected global top_k to be SQL-only for the constructed FAISS stream.\n"
        f"Got: {[ (h.get('Id'), (h.get('Metadata') or {}).get('file_type')) for h in global_hits ]}"
    )

    # HARD ASSERT: filtered results must still exist (CS is present within raw_k).
    req_filtered = VectorSearchRequest(
        text_query="foo bar",
        top_k=top_k,
        oversample_factor=oversample,
        filters=VectorSearchFilters(file_type=["cs"]),
        include_text_preview=False,
    )
    cs_hits = search_unified(index=index, metadata=metadata, embed_model=embed, request=req_filtered)
    assert cs_hits, (
        "Expected non-empty results for file_type=cs.\n"
        "If this is empty, you are effectively truncating to top_k BEFORE filtering (BUG)."
    )
    assert all((h.get("Metadata") or {}).get("file_type") == "cs" for h in cs_hits), (
        f"Filtered hits must be CS-only. Got: {[ (h.get('Id'), (h.get('Metadata') or {}).get('file_type')) for h in cs_hits ]}"
    )
    assert len(cs_hits) <= top_k


def test_09_semantic_requests_raw_k_equal_topk_times_oversample(monkeypatch: Any) -> None:
    """
    Locks the contract that semantic retrieval asks FAISS for raw_k = top_k * oversample_factor
    BEFORE filtering. This is the built-in anti-starvation mechanism for semantic filters.
    """
    import vector_search.unified_search as us
    monkeypatch.setattr(us.faiss, "normalize_L2", lambda x: None, raising=True)

    top_k = 2
    oversample = 7
    raw_k = top_k * oversample  # 14

    ids = list(range(raw_k))
    scores = [1.0 - (i * 0.001) for i in range(raw_k)]
    metadata = _make_metadata(doc_count=raw_k, sql_until=7)

    index = DummyIndex(scores=scores, ids=ids)
    embed = DummyEmbed()

    req = VectorSearchRequest(
        text_query="anything",
        top_k=top_k,
        oversample_factor=oversample,
        filters=VectorSearchFilters(file_type=["cs"]),
        include_text_preview=False,
    )
    _ = search_unified(index=index, metadata=metadata, embed_model=embed, request=req)

    assert index.last_k == raw_k, f"Expected FAISS k={raw_k}, got {index.last_k}"
