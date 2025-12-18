from __future__ import annotations

from typing import Any, Dict, List, Optional

import dotnet_sumarizer.code_compressor as code_compressor

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


def _build_compressed_context_from_faiss(
    *,
    followup: str,
    searcher: Any,
    filters: Any | None = None,
    history_manager: Any,
    logger: Any,
    top_k: int = 5,
    mode: str = "snippets",
    token_budget: int = 1200,
    window: int = 18,
    max_chunks: int = 8,
    language: str = "csharp",
    per_chunk_hard_cap: int = 240,
) -> str:
    faiss_results = searcher.search(followup, top_k=top_k, filters=filters) or []
    try:
        history_manager.add_iteration(followup, faiss_results)
    except Exception:
        pass

    source_chunks: List[Dict[str, Any]] = []

    for r in faiss_results:
        if not r:
            continue

        source_chunks.append(
            {
                "path": r.get("File") or r.get("path"),
                "content": r.get("Content") or r.get("content") or "",
                "member": r.get("Member") or r.get("member"),
                "namespace": r.get("Namespace") or r.get("namespace"),
                "class": r.get("Class") or r.get("class"),
                "hit_lines": r.get("HitLines") or r.get("hit_lines"),
                "score": r.get("Score") or r.get("score"),
                "meta": r,
            }
        )

    if not source_chunks:
        return ""

    # IMPORTANT: call via module so tests can monkeypatch dotnet_sumarizer.code_compressor.compress_chunks
    compressed = code_compressor.compress_chunks(
        source_chunks,
        mode=mode,
        token_budget=token_budget,
        window=window,
        max_chunks=max_chunks,
        language=language,
        per_chunk_hard_cap=per_chunk_hard_cap,
    )

    return compressed or ""


class FetchMoreContextAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        # Decide query to retrieve
        q = (state.followup_query or state.retrieval_query or "").strip()
        if not q:
            return None

        if q in state.used_followups:
            state.answer_en = (
                "Proces przerwany. Model powtarza te same pytania do bazy. "
                "Spróbuj zadać pytanie inaczej."
            )
            state.query_type = "abort: repeated query"
            return step.raw.get("next")

        state.used_followups.add(q)

        # Hard filters (from UI / request)
        hard_filters: Dict[str, Any] = {}
        if state.branch:
            hard_filters["branch"] = [state.branch]

        # Soft filters (from router scope)
        soft_filters: Dict[str, Any] = state.retrieval_filters or {}

        # Effective filters: hard AND soft (soft can be relaxed in fallbacks, hard never)
        effective_filters: Dict[str, Any] = {**hard_filters, **soft_filters}

        mode = (state.retrieval_mode or "semantic_rerank").strip().lower()

        if mode == "bm25":
            raise NotImplementedError("BM25 mode is not wired yet in this repo runtime.")

        # First attempt: scoped (hard + soft)
        context_text = _build_compressed_context_from_faiss(
            followup=q,
            searcher=runtime.searcher,
            history_manager=runtime.history_manager,
            logger=runtime.logger,
            filters=effective_filters,
        )

        # Fallback: if too little signal, relax ONLY soft filters (keep branch hard filter)
        if not context_text or len(context_text.strip()) < 200:
            relaxed_filters = dict(hard_filters)
            context_text = _build_compressed_context_from_faiss(
                followup=q,
                searcher=runtime.searcher,
                history_manager=runtime.history_manager,
                logger=runtime.logger,
                filters=relaxed_filters,
            )

        state.context_blocks.append(context_text)
        return None
