# code_query_engine/pipeline/actions/fetch_more_context.py

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..providers.retrieval import RetrievalDecision
from ..state import PipelineState
from .base_action import PipelineActionBase

py_logger = logging.getLogger(__name__)



def _merge_filters(settings: Dict[str, Any], state: PipelineState) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    filters.update(state.retrieval_filters or {})

    repo = (state.repository or settings.get("repository") or "").strip()
    branch = (state.branch or settings.get("branch") or "").strip()

    # Branch is REQUIRED for all searches (including graph back-search scoping).
    if not branch:
        raise ValueError("Missing required 'branch' (state.branch or pipeline settings['branch']).")

    # Repository may be provided either by state/settings OR implicitly by the retriever implementation.
    # Keep it optional to avoid breaking test harnesses and single-repo deployments.
    if repo:
        filters["repository"] = repo

    # Tests and downstream retrievers expect plain strings here (not lists).
    filters["branch"] = branch

    return filters


def _normalize_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for r in results or []:
        if not isinstance(r, dict):
            continue

        # Accept both styles: {path/content} and {File/Content}
        path = r.get("path") or r.get("File") or r.get("file") or ""
        content = r.get("content") or r.get("Content") or r.get("text") or ""
        start_line = r.get("start_line")
        end_line = r.get("end_line")

        normalized.append(
            {
                "path": path,
                "content": content,
                "start_line": start_line,
                "end_line": end_line,
                # Keep original fields (e.g., Id) for seed extraction & debugging
                **{k: v for k, v in r.items() if k not in {"path", "file", "File", "content", "Content", "text"}},
            }
        )
    return normalized


def _extract_seed_nodes(results: List[Dict[str, Any]]) -> List[str]:
    # Deterministic: preserve first occurrence order
    seen = set()
    out: List[str] = []

    for r in results or []:
        if not isinstance(r, dict):
            continue

        # Common id fields across retrievers
        nid = r.get("Id") or r.get("id") or r.get("node_id") or r.get("nodeId")
        if nid is None:
            continue

        v = str(nid).strip()
        if not v:
            continue

        if v in seen:
            continue
        seen.add(v)
        out.append(v)

    return out


class FetchMoreContextAction(PipelineActionBase):
    @property
    def action_id(self) -> str:
        return "fetch_more_context"

    def log_in(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Dict[str, Any]:
        settings = runtime.pipeline_settings or {}
        mode = (state.retrieval_mode or "semantic").strip().lower()
        query = (state.followup_query or state.retrieval_query or "").strip()

        top_k = int(settings.get("top_k", 12))
        filters = _merge_filters(settings, state) if settings else dict(state.retrieval_filters or {})

        return {
            "mode": mode,
            "query": query,
            "top_k": top_k,
            "filters": filters,
        }

    def log_out(
        self,
        step: StepDef,
        state: PipelineState,
        runtime: PipelineRuntime,
        *,
        next_step_id: Optional[str],
        error: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "next_step_id": next_step_id,
            "retrieval_seed_nodes": list(getattr(state, "retrieval_seed_nodes", []) or []),
            "context_blocks_count": len(getattr(state, "context_blocks", []) or []),
        }

    def do_execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        settings = runtime.pipeline_settings or {}

        mode = (state.retrieval_mode or "semantic").strip().lower()
        query = (state.followup_query or state.retrieval_query or "").strip()
        if not query:
            return None

        dispatcher = runtime.get_retrieval_dispatcher()

        top_k = int(settings.get("top_k", 12))
        filters = _merge_filters(settings, state) if settings else dict(state.retrieval_filters or {})

        decision = RetrievalDecision(mode=mode, query=query)

        search_fn = getattr(dispatcher, "search", None)
        if callable(search_fn):
            results = search_fn(decision, top_k=top_k, settings=settings, filters=filters)
        else:
            # E2E tests may pass a dummy dispatcher that only wraps a retriever.
            retriever = getattr(dispatcher, "retriever", None) or getattr(dispatcher, "_retriever", None)
            retr_search = getattr(retriever, "search", None) if retriever is not None else None
            if callable(retr_search):
                results = retr_search(query, top_k=top_k, filters=filters)
            else:
                results = []

        results = _normalize_results(results)

        # This step defines the seed set for the graph expansion step.
        state.retrieval_seed_nodes = _extract_seed_nodes(results)

        blocks: List[str] = []
        for r in results:
            path = (r.get("path") or "").strip()
            content = (r.get("content") or "").strip()
            if not content:
                continue

            start = r.get("start_line")
            end = r.get("end_line")

            header = f"### File: {path}" if path else "### File"
            if start is not None and end is not None:
                header += f" (lines {start}-{end})"

            blocks.append(f"{header}\n{content}".strip())

        if blocks:
            state.context_blocks.extend(blocks)

        try:
            runtime.history_manager.add_iteration(query, results)
        except Exception:
            py_logger.exception("soft-failure: history_manager.add_iteration failed; continuing")
            pass

        return None
