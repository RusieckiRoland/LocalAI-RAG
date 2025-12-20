# code_query_engine/pipeline/state.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class PipelineState:
    # Request identity (EXPECTED BY TESTS)
    user_query: str
    session_id: str
    consultant: str
    branch: str
    translate_chat: bool

    # Translation
    user_question_en: Optional[str] = None

    # Pipeline execution bookkeeping
    pipeline_name: Optional[str] = None
    steps_used: int = 0
    step_trace: List[str] = field(default_factory=list)
    budget_debug: Dict[str, Any] = field(default_factory=dict)
    turn_loop_counter: int = 0

    # Retrieval outputs
    retrieval_mode: str = ""
    retrieval_query: str = ""
    retrieval_filters: Dict[str, Any] = field(default_factory=dict)
    followup_query: Optional[str] = None
    query_type: Optional[str] = None

    # Context
    history_blocks: List[str] = field(default_factory=list)
    context_blocks: List[str] = field(default_factory=list)

    # Model outputs        
    next_codellama_prompt: Optional[str] = None
    last_model_response: Optional[str] = None
    model_input_en: Optional[str] = None
    router_raw: Optional[str] = None

    draft_answer_en: Optional[str] = None
    answer_en: Optional[str] = None
    answer_pl: Optional[str] = None
    final_answer: Optional[str] = None

    # Optional misc flags/diagnostics
    flags: Set[str] = field(default_factory=set)

    # Backward-compat aliases used by some newer code
    @property
    def original_question(self) -> str:
        return self.user_query

    def history_for_prompt(self) -> str:
        return "\n\n".join([x for x in self.history_blocks if x])

    def composed_context_for_prompt(self) -> str:
        blocks: List[str] = []
        blocks.extend([x for x in self.history_blocks if x])
        blocks.extend([x for x in self.context_blocks if x])
        return "\n\n".join(blocks)

    def model_input_en_or_fallback(self) -> str:
        if self.model_input_en:
            return self.model_input_en
        if self.user_question_en:
            return self.user_question_en
        return self.user_query
