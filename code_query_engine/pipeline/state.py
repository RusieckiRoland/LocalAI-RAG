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

    # Optional identity
    user_id: Optional[str] = None
    repository: Optional[str] = None

    # Router outputs / parse artifacts
    router_raw: Optional[str] = None
    retrieval_mode: str = ""
    retrieval_scope: Optional[str] = None
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

    # Answer fields expected by multiple actions/engine
    draft_answer_en: Optional[str] = None
    draft_answer_pl: Optional[str] = None
    answer_en: Optional[str] = None
    answer_pl: Optional[str] = None

    # Translation artifacts
    user_question_en: Optional[str] = None
    user_question_pl: Optional[str] = None

    # Diagnostics
    step_trace: List[str] = field(default_factory=list)
    steps_used: int = 0

    # Graph-related (kept for planned dependency expansion)
    retrieval_seed_nodes: List[str] = field(default_factory=list)
    graph_seed_nodes: List[str] = field(default_factory=list)
    graph_expanded_nodes: List[str] = field(default_factory=list)
    graph_edges: List[Dict[str, Any]] = field(default_factory=list)
    graph_debug: Dict[str, Any] = field(default_factory=dict)
    turn_loop_counter: int = 0

    # Final answer (optional convenience)
    final_answer: Optional[str] = None

    # Model input (logged)
    model_input_en: Optional[str] = None

    # Additional: used by some actions/tests
    seen_chunk_ids: Set[str] = field(default_factory=set)

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
