# code_query_engine/pipeline/actions/fetch_more_context.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..definitions import StepDef
from ..engine import PipelineRuntime
from ..providers.retrieval import RetrievalDecision
from ..state import PipelineState


def _merge_filters(settings: Dict[str, Any], state: PipelineState) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    filters.update(state.retrieval_filters or {})

    repo = (state.repository or settings.get("repository") or "").strip()
    branch = (state.branch or settings.get("branch") or "").strip()

    # Tests expect plain strings here (not lists)
    if repo:
        filters["repository"] = repo
    if branch:
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
                **{k: v for k, v in r.items() if k not in {"path", "file", "File", "content", "Content", "text"}},
            }
        )
    return normalized


class FetchMoreContextAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        settings = runtime.pipeline_settings or {}

        mode = (state.retrieval_mode or "semantic").strip().lower()
        query = (state.followup_query or state.retrieval_query or "").strip()
        if not query:
            return None

        dispatcher = runtime.get_retrieval_dispatcher()

        top_k = int(settings.get("top_k", 12))
        filters = _merge_filters(settings, state) if settings else dict(state.retrieval_filters or {})

        decision = RetrievalDecision(mode=mode, query=query)
        results = dispatcher.search(decision, top_k=top_k, settings=settings, filters=filters)
        results = _normalize_results(results)

        # This step defines the seed set for the graph expansion step.
        state.retrieval_seed_nodes = []

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
            pass

        return None
