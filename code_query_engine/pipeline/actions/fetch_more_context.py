# File: code_query_engine/pipeline/actions/fetch_more_context.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime
from ..providers.retrieval import RetrievalDecision


def _merge_filters(settings: Dict[str, Any], state: PipelineState) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    filters.update(state.retrieval_filters or {})

    # Allow pipeline settings defaults to enforce branch/repo scoping if desired.
    branch = settings.get("branch") or settings.get("active_index") or None
    if branch and "branch" not in filters:
        filters["branch"] = branch

    # Optional: repository
    repo = settings.get("repository") or None
    if repo and "repository" not in filters:
        filters["repository"] = repo

    return filters


class FetchMoreContextAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        raw = step.raw or {}
        settings = runtime.pipeline_settings or {}

        mode = (state.retrieval_mode or "semantic").strip().lower()
        query = (state.followup_query or state.retrieval_query or "").strip()

        if not query:
            return None

        dispatcher = runtime.get_retrieval_dispatcher()

        top_k = int(settings.get("top_k", 12))
        filters = _merge_filters(settings, state) if settings else dict(state.retrieval_filters or {})

        results = dispatcher.search(
            RetrievalDecision(mode=mode, query=query),
            top_k=top_k,
            settings=settings,
            filters=filters or None,
        )

        # Store chunks as strings to keep the rest of pipeline stable.
        blocks: List[str] = []
        for r in results or []:
            path = r.get("path") or r.get("file") or ""
            content = r.get("content") or r.get("text") or ""
            start = r.get("start_line")
            end = r.get("end_line")

            header = f"File: {path}".strip()
            if start is not None and end is not None:
                header += f" (lines {start}-{end})"

            blocks.append(f"{header}\n{content}".strip())

        if blocks:
            state.context_blocks.extend(blocks)

        # Make history manager aware of the iteration (if it cares)
        try:
            runtime.history_manager.add_iteration(query, results)
        except Exception:
            pass

        return None
