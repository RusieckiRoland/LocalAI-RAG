# code_query_engine/pipeline/actions/fetch_node_texts.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class FetchNodeTextsAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        # Placeholder (graph node lookup planned). Deterministic no-op.
        return None
