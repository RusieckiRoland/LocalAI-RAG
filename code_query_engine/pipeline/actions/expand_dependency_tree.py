# code_query_engine/pipeline/actions/expand_dependency_tree.py
from __future__ import annotations

from typing import Optional

from ..definitions import StepDef
from ..state import PipelineState
from ..engine import PipelineRuntime


class ExpandDependencyTreeAction:
    def execute(self, step: StepDef, state: PipelineState, runtime: PipelineRuntime) -> Optional[str]:
        # Placeholder (graph provider is planned). Deterministic no-op.
        return None
