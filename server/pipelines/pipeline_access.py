from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PipelineAccessService:
    """
    Filters UI consultants based on allowed pipeline list.
    """

    def filter_consultants(
        self,
        templates: Dict[str, Any],
        *,
        allowed_pipelines: Optional[List[str]],
    ) -> Tuple[List[Dict[str, Any]], str]:
        consultants = []
        default_consultant_id = ""

        if isinstance(templates, dict):
            consultants = templates.get("consultants") or []

            # None => no restriction (legacy/default-all mode)
            # []   => explicit deny-all (fail-closed)
            if allowed_pipelines is not None:
                allowed = set(allowed_pipelines)
                consultants = [
                    c
                    for c in consultants
                    if isinstance(c, dict) and str(c.get("pipelineName") or "").strip() in allowed
                ]

            default_consultant_id = str(templates.get("defaultConsultantId") or "")
            if default_consultant_id:
                if not any(str(c.get("id") or "") == default_consultant_id for c in consultants if isinstance(c, dict)):
                    default_consultant_id = ""

            if not default_consultant_id and consultants:
                default_consultant_id = str(consultants[0].get("id") or "")

        return consultants, default_consultant_id
