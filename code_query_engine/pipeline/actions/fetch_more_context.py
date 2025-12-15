# code_query_engine/pipeline/actions/fetch_more_context.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from dotnet_sumarizer.code_compressor import compress_chunks

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


def _build_compressed_context_from_faiss(
    *,
    followup: str,
    searcher: Any,
    history_manager: Any,
    logger: Any,
    top_k: int = 5,
    mode: str = "snippets",
    token_budget: int = 1200,
    window: int = 18,
    max_chunks: int = 8,
    language: str = "csharp",
    per_chunk_hard_cap: int = 240,
    include_related: bool = True,
) -> str:
    faiss_results = searcher.search(followup, top_k=top_k) or []
    try:
        history_manager.add_iteration(followup, faiss_results)
    except Exception:
        pass

    source_chunks: List[Dict[str, Any]] = []
    for r in faiss_results:
        if not r:
            continue
        source_chunks.append({
            "path": r.get("File") or r.get("path"),
            "content": r.get("Content") or r.get("content") or "",
            "member": r.get("Member") or r.get("member"),
            "namespace": r.get("Namespace") or r.get("namespace"),
            "class": r.get("Class") or r.get("class"),
            "hit_lines": r.get("HitLines") or r.get("hit_lines"),
            "rank": r.get("Rank"),
            "distance": r.get("Distance"),
        })
        if include_related:
            for rel in (r.get("Related") or []):
                source_chunks.append({
                    "path": rel.get("File") or rel.get("path"),
                    "content": rel.get("Content") or rel.get("content") or "",
                    "member": rel.get("Member") or rel.get("member"),
                    "namespace": rel.get("Namespace") or rel.get("namespace"),
                    "class": rel.get("Class") or rel.get("class"),
                    "hit_lines": rel.get("HitLines") or rel.get("hit_lines"),
                    "rank": 999,
                    "distance": 1.0,
                })

    try:
        debug_payload = {
            "followup": followup,
            "top_k": top_k,
            "mode": mode,
            "token_budget": token_budget,
            "window": window,
            "max_chunks": max_chunks,
            "language": language,
            "per_chunk_hard_cap": per_chunk_hard_cap,
            "include_related": include_related,
            "source_chunks": source_chunks,
        }
        logger.logger.info(
            "FAISS debug - input for compression:\n%s",
            json.dumps(debug_payload, ensure_ascii=False, indent=2),
        )
    except Exception:
        pass

    return compress_chunks(
        source_chunks,
        mode=mode,
        token_budget=token_budget,
        window=window,
        max_chunks=max_chunks,
        language=language,
        per_chunk_hard_cap=per_chunk_hard_cap,
    )


class FetchMoreContextAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        settings = runtime.pipeline_settings or {}

        # Decide query to retrieve
        q = (state.followup_query or state.retrieval_query or "").strip()
        if not q:
            # No query => deterministic no-op
            return None

        if q in state.used_followups:
            state.answer_en = (
                "Proces przerwany. Model powtarza te same pytania do bazy. "
                "Spróbuj zadać pytanie inaczej."
            )
            state.query_type = "abort: repeated query"
            return step.raw.get("next")  # continue; finalize_heuristic will handle

        state.used_followups.add(q)

        # Retrieval mode dispatch: for now we keep deterministic behavior using existing searcher.
        mode = (state.retrieval_mode or "semantic_rerank").strip().lower()

        # Semantic-only => alpha=1 beta=0
        if mode == "semantic":
            # SemanticKeywordRerankSearch supports alpha/beta; use it to force embedding-only.
            results = runtime.searcher.search(q, top_k=5, alpha=1.0, beta=0.0) or []
            # Use the same compression path (via "searcher.search" already done); rebuild with helper for consistency:
            context_text = _build_compressed_context_from_faiss(
                followup=q,
                searcher=runtime.searcher,
                history_manager=runtime.history_manager,
                logger=runtime.logger,
            )
        elif mode in ("semantic_rerank", "hybrid"):
            context_text = _build_compressed_context_from_faiss(
                followup=q,
                searcher=runtime.searcher,
                history_manager=runtime.history_manager,
                logger=runtime.logger,
            )
        elif mode == "bm25":
            raise NotImplementedError("BM25 mode is not wired yet in this repo runtime.")
        else:
            # Deterministic fallback
            context_text = _build_compressed_context_from_faiss(
                followup=q,
                searcher=runtime.searcher,
                history_manager=runtime.history_manager,
                logger=runtime.logger,
            )

        state.context_blocks.append(context_text)
        return None
