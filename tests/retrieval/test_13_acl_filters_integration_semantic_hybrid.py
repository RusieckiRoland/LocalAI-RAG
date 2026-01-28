# tests/retrieval/test_13_acl_filters_integration_semantic_hybrid.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pytest

import faiss  # type: ignore

from vector_db.build_vector_index import load_config, resolve_path
from vector_db.bm25_searcher import Bm25Searcher, load_tf_index
from vector_search.unified_search import (
    VectorSearchFilters,
    VectorSearchRequest,
    search_unified,
)


# --------------------------------------------------------------------------------------
# This file is an INTEGRATION test suite against REAL unified index artifacts produced
# for the fake repo. It intentionally uses tests/config.json (picked by load_config()).
#
# HARD PROOF idea:
# - Force query embedding to match a DISALLOWED document vector.
# - Use top_k=1 and oversample_factor=1 (raw_k = 1).
#   If ACL were applied AFTER search truncation -> we'd return empty results.
# - Expectation: we still get an ALLOWED result => ACL applied BEFORE ranking/truncation.
# --------------------------------------------------------------------------------------


ACL_TAG = "Security"


def _get_test_index_context() -> Tuple[Dict[str, Any], str, str, str, Path]:
    """
    Load config via vector_db.build_vector_index.load_config().
    That function is expected to prefer tests/config.json automatically.

    Returns:
      config, config_dir, repo_name, index_id, index_dir(Path)
    """
    config, config_dir = load_config()

    repo_name = str(config.get("repo_name", "") or "").strip()
    index_id = str(config.get("active_index_id", "") or "").strip()
    vector_root = resolve_path(str(config.get("vector_indexes_root", "vector_indexes")), config_dir)

    if not repo_name:
        raise AssertionError("Config is missing 'repo_name'. Expected tests/config.json to define it.")
    if not index_id:
        raise AssertionError("Config is missing 'active_index_id'. Expected tests/config.json to define it.")

    index_dir = Path(os.path.join(vector_root, index_id))
    return config, config_dir, repo_name, index_id, index_dir


def _assert_artifacts_exist(index_dir: Path) -> None:
    required = [
        index_dir / "unified_index.faiss",
        index_dir / "unified_metadata.json",
        index_dir / "tf_vocab.json",
        index_dir / "tf_offsets.npy",
        index_dir / "tf_doc_ids.npy",
        index_dir / "tf_tfs.npy",
        index_dir / "tf_df.npy",
        index_dir / "tf_doc_len.npy",
        index_dir / "tf_index_meta.json",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    assert not missing, (
        "Missing index artifacts for integration ACL tests.\n"
        f"Index dir: {index_dir}\n"
        "Missing:\n  - " + "\n  - ".join(missing)
    )


def _load_index_and_metadata() -> Tuple[Any, List[Dict[str, Any]]]:
    _, _, _, _, index_dir = _get_test_index_context()
    _assert_artifacts_exist(index_dir)

    index_path = str(index_dir / "unified_index.faiss")
    meta_path = index_dir / "unified_metadata.json"

    index = faiss.read_index(index_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(meta, list), "unified_metadata.json must be a JSON list"
    return index, meta


def _load_bm25(index_dir: Path, meta: List[Dict[str, Any]]) -> Bm25Searcher:
    tf = load_tf_index(str(index_dir))
    return Bm25Searcher(index_dir=str(index_dir), tf_index=tf, metadata=meta)


def _meta_by_id(meta: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for m in meta:
        mid = str(m.get("id") or m.get("Id") or "")
        if mid:
            out[mid] = m
    return out


def _has_acl_tag(m: Dict[str, Any], tag: str) -> bool:
    tags = m.get("permission_tags_all")
    if isinstance(tags, list):
        return tag in [str(x) for x in tags]
    return False


def _first_allowed_and_disallowed_positions(
    meta: List[Dict[str, Any]],
    tag: str,
) -> Tuple[int, int]:
    allowed_pos: Optional[int] = None
    disallowed_pos: Optional[int] = None

    for i, m in enumerate(meta):
        if _has_acl_tag(m, tag):
            if allowed_pos is None:
                allowed_pos = i
        else:
            if disallowed_pos is None:
                disallowed_pos = i

        if allowed_pos is not None and disallowed_pos is not None:
            break

    assert allowed_pos is not None, f"No metadata rows with permission_tags_all containing '{tag}'"
    assert disallowed_pos is not None, f"All metadata rows contain '{tag}' (need at least one disallowed row)"
    return disallowed_pos, allowed_pos


@dataclass
class _FixedVectorEmbed:
    """
    A deterministic embedding stub: always returns the same vector.
    We use it to force the "global top1" to be a known FAISS row.
    """

    vec: np.ndarray

    def encode(self, texts: Any, **kwargs: Any) -> np.ndarray:
        # SentenceTransformer.encode accepts str or List[str].
        # unified_search should accept any embed model exposing encode().
        v = self.vec.astype(np.float32, copy=False)
        if v.ndim == 1:
            v = v.reshape(1, -1)
        return v


def _extract_hit_id(hit: Dict[str, Any]) -> str:
    # Support multiple shapes.
    for k in ("Id", "id", "_id"):
        if k in hit and hit[k]:
            return str(hit[k])
    md = hit.get("Metadata")
    if isinstance(md, dict):
        mid = md.get("id") or md.get("Id")
        if mid:
            return str(mid)
    return ""


def _search_semantic_unified(
    *,
    index: Any,
    meta: List[Dict[str, Any]],
    embed: _FixedVectorEmbed,
    top_k: int,
    oversample: int,
    tag: str,
) -> List[Dict[str, Any]]:
    req = VectorSearchRequest(
        text_query="proof",
        top_k=int(top_k),
        oversample_factor=int(oversample),
        filters=VectorSearchFilters(permission_tags_all=[tag]),
        include_text_preview=False,
    )
    return search_unified(index=index, metadata=meta, embed_model=embed, request=req)


def _find_bm25_proof_term(
    *,
    bm25: Bm25Searcher,
    meta: List[Dict[str, Any]],
    tag: str,
    max_terms: int = 2000,
) -> str:
    """
    Find a single-token query term such that:
      - BM25 top1 WITHOUT ACL is DISALLOWED (no tag)
      - BM25 top1 WITH ACL is ALLOWED (has tag)
    """
    by_id = _meta_by_id(meta)

    # tf_vocab.json is part of the TF artifacts.
    vocab_path = Path(bm25.index_dir) / "tf_vocab.json"
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    assert isinstance(vocab, dict), "tf_vocab.json must be a JSON object(term->id)"

    checked = 0
    for term in vocab.keys():
        if not isinstance(term, str) or not term:
            continue

        checked += 1
        if checked > max_terms:
            break

        # Global top1
        g = bm25.search(term, top_k=1, filters=None)
        if not g:
            continue
        gid = _extract_hit_id(g[0])
        gm = by_id.get(gid) or {}
        if _has_acl_tag(gm, tag):
            continue  # not disallowed => no proof

        # ACL top1
        f = bm25.search(term, top_k=1, filters={"permission_tags_all": [tag]})
        if not f:
            continue
        fid = _extract_hit_id(f[0])
        fm = by_id.get(fid) or {}
        if not _has_acl_tag(fm, tag):
            continue

        return term

    raise AssertionError(
        f"Could not find a BM25 proof term within first {min(max_terms, len(vocab))} vocab entries. "
        "Increase max_terms or rebuild the fake index with clearer ACL-separated tokens."
    )


def _rrf_fuse_top1(
    sem_hits: List[Dict[str, Any]],
    bm25_hits: List[Dict[str, Any]],
    *,
    rrf_k: int = 60,
) -> Tuple[str, float]:
    """
    Deterministic RRF fusion for top1 only.
    Returns (id, score).
    """
    scores: Dict[str, float] = {}

    def add(hits: List[Dict[str, Any]]) -> None:
        for rank0, h in enumerate(hits):
            hid = _extract_hit_id(h)
            if not hid:
                continue
            rank = rank0 + 1
            scores[hid] = scores.get(hid, 0.0) + (1.0 / float(rrf_k + rank))

    add(sem_hits)
    add(bm25_hits)

    assert scores, "RRF fusion got no ids at all (unexpected)."

    # Deterministic: sort by score desc, then by id asc.
    best_id = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return best_id[0], best_id[1]


def test_14_semantic_acl_is_applied_before_ranking_hard_proof_real_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    HARD PROOF (integration, REAL DATA, SEMANTIC):
    - Force query embedding = vector of a DISALLOWED doc (global top1).
    - Use top_k=1 and oversample_factor=1.
      If ACL filtering were applied AFTER truncation, we'd get empty result.
    Expectation: we still get an ALLOWED hit => filtering happened before ranking/truncation.
    """
    import vector_search.unified_search as us

    # Make faiss.normalize_L2 a no-op for unit-test determinism.
    monkeypatch.setattr(us.faiss, "normalize_L2", lambda x: None, raising=True)

    index, meta = _load_index_and_metadata()
    by_id = _meta_by_id(meta)

    disallowed_pos, _allowed_pos = _first_allowed_and_disallowed_positions(meta, ACL_TAG)

    # Force query embedding vector to be exactly the disallowed row vector.
    v = np.zeros((index.d,), dtype=np.float32)
    index.reconstruct(int(disallowed_pos), v)

    embed = _FixedVectorEmbed(vec=v)

    # This is the "starvation detector" setup:
    # - raw_k = top_k * oversample = 1
    # - if filter applied after truncation -> empty
    hits = _search_semantic_unified(index=index, meta=meta, embed=embed, top_k=1, oversample=1, tag=ACL_TAG)

    assert hits, "Expected a non-empty result when ACL is applied before ranking/truncation."
    hid = _extract_hit_id(hits[0])
    assert hid, "Hit id is missing in semantic output shape."
    hm = by_id.get(hid) or {}

    assert _has_acl_tag(hm, ACL_TAG), (
        "Semantic result is not ACL-allowed. "
        "This indicates ACL filtering was NOT applied before ranking/truncation."
    )


def test_15_hybrid_acl_is_applied_before_ranking_hard_proof_real_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    HARD PROOF (integration, REAL DATA, HYBRID):
    - Find a BM25 single-term query where BM25 top1 WITHOUT ACL is DISALLOWED,
      but BM25 top1 WITH ACL is ALLOWED for top_k=1.
    - Force semantic "global top1" to be DISALLOWED via embedding override.
    - Run semantic(top_k=1, oversample=1, ACL) and bm25(top_k=1, ACL), then fuse.
    Expectation: fused top1 is ALLOWED (no starvation / no disallowed ids).
    """
    import vector_search.unified_search as us

    monkeypatch.setattr(us.faiss, "normalize_L2", lambda x: None, raising=True)

    _, _, _, _, index_dir = _get_test_index_context()
    index, meta = _load_index_and_metadata()
    by_id = _meta_by_id(meta)

    bm25 = _load_bm25(index_dir=index_dir, meta=meta)
    proof_term = _find_bm25_proof_term(bm25=bm25, meta=meta, tag=ACL_TAG)

    # Force semantic query vector to match a DISALLOWED row.
    disallowed_pos, _allowed_pos = _first_allowed_and_disallowed_positions(meta, ACL_TAG)
    v = np.zeros((index.d,), dtype=np.float32)
    index.reconstruct(int(disallowed_pos), v)
    embed = _FixedVectorEmbed(vec=v)

    sem_hits = _search_semantic_unified(index=index, meta=meta, embed=embed, top_k=1, oversample=1, tag=ACL_TAG)
    assert sem_hits, "Expected semantic ACL prefilter to return a hit for hybrid proof."

    bm_hits = bm25.search(proof_term, top_k=1, filters={"permission_tags_all": [ACL_TAG]})
    assert bm_hits, "Expected BM25 ACL prefilter to return a hit for hybrid proof."

    fused_id, _score = _rrf_fuse_top1(sem_hits=sem_hits, bm25_hits=bm_hits, rrf_k=60)
    fm = by_id.get(fused_id) or {}

    assert _has_acl_tag(fm, ACL_TAG), (
        "Hybrid fused top1 is not ACL-allowed. "
        "This indicates ACL filtering is not respected before ranking/truncation in at least one backend."
    )
