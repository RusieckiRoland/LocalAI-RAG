import numpy as np
import pytest

m = pytest.importorskip("common.semantic_keyword_rerank_search")
SearchEngineClass = getattr(m, "SemanticKeywordRerankSearch")

pytestmark = pytest.mark.unit


class EmptyIndex:
    """Stub returning an empty FAISS result (0 neighbors)."""
    def search(self, vectors, k):
        return np.zeros((1, 0), dtype=np.float32), np.zeros((1, 0), dtype=np.int64)


class TiedIndex:
    """Stub with tied distances to verify deterministic sorting and cleanup."""
    def __init__(self):
        self._dist = np.array([[0.2, 0.2, 0.9]], dtype=np.float32)
        self._idx = np.array([[0, 1, 2]], dtype=np.int64)

    def search(self, vectors, k):
        return self._dist, self._idx


class DummyEmbed:
    def encode(self, texts, **kwargs):
        v = np.zeros((1, 384), dtype=np.float32)
        convert = kwargs.get("convert_to_numpy", True)
        return v if convert else v.tolist()


def _fixtures():
    # Use string Ids to match dependencies map and avoid mismatches in _get_related().
    chunks = [
        {"Id": "0", "File": "A.cs", "Text": "order service create update"},
        {"Id": "1", "File": "B.cs", "Text": "customer service; order history"},
        {"Id": "2", "File": "C.cs", "Text": "helper utils and config"},
    ]
    metadata = [{"Id": "0"}, {"Id": "1"}, {"Id": "2"}]
    deps = {"0": ["1"], "1": ["2"]}
    return metadata, chunks, deps


def _mk(index):
    meta, chunks, deps = _fixtures()
    return SearchEngineClass(index=index, metadata=meta, chunks=chunks, dependencies=deps, embed_model=DummyEmbed())


def test_alpha_zero_path_keyword_only():
    hs = _mk(TiedIndex())
    # alpha=0 => ignore embedding score; keyword-only ranking among FAISS candidates
    out = hs.search("order service", top_k=2, alpha=0.0, beta=1.0, widen=3)
    assert len(out) == 2
    assert out[0]["Rank"] == 1 and out[1]["Rank"] == 2
    assert out[0]["File"] == "A.cs"
    assert out[1]["File"] == "B.cs"


def test_beta_zero_path_embedding_only():
    hs = _mk(TiedIndex())
    # beta=0 => ignore keyword score; embedding-only ranking
    out = hs.search("order service", top_k=2, alpha=1.0, beta=0.0, widen=3)
    assert len(out) == 2
    # Related should be present for all results (even if sometimes empty)
    assert all("Related" in r for r in out)


def test_empty_index_results_are_handled_gracefully():
    hs = _mk(EmptyIndex())
    # Empty FAISS result => should return [] without exceptions
    out = hs.search("anything", top_k=5, alpha=0.5, beta=0.5, widen=5)
    assert out == []


def test_tie_breaker_and_temp_fields_removed():
    hs = _mk(TiedIndex())
    out = hs.search("order", top_k=2, alpha=0.5, beta=0.5, widen=3)
    assert len(out) == 2
    for r in out:
        for tmp in ["_emb_score", "_kw_raw", "_kw_norm", "_final_score"]:
            assert tmp not in r
