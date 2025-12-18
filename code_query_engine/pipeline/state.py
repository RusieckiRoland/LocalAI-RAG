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

    # Language / normalization
    user_question_en: Optional[str] = None

    # History
    history_blocks: List[str] = field(default_factory=list)
    history_summary: Optional[str] = None

    # Router decision
    router_raw: Optional[str] = None
    retrieval_mode: Optional[str] = None
    retrieval_query: Optional[str] = None

    # NEW (safe extensions for routing/filters; won't break existing tests)
    retrieval_scope: Optional[str] = None  # CS | SQL | ANY
    retrieval_filters: Dict[str, Any] = field(default_factory=dict)  # soft filters (e.g. data_type)

    # Retrieval / evidence
    context_blocks: List[str] = field(default_factory=list)  # evidence blocks appended
    used_followups: Set[str] = field(default_factory=set)

    # Follow-up loop
    turn_loop_counter: int = 0
    followup_query: Optional[str] = None

    # Model I/O
    last_model_response: Optional[str] = None

    # Final answer
    answer_en: Optional[str] = None
    answer_pl: Optional[str] = None
    final_answer: Optional[str] = None

    # Logging / diagnostics
    query_type: str = "unknown"
    steps_used: int = 0
    next_codellama_prompt: Optional[str] = None
    budget_debug: Dict[str, Any] = field(default_factory=dict)

    def model_input_en_or_fallback(self) -> str:
        return self.user_question_en or self.user_query

    def history_for_prompt(self) -> str:
        blocks = list(self.history_blocks)
        if self.history_summary:
            blocks = [f"[HistorySummary]\n{self.history_summary}"] + blocks
        return "\n---\n".join([b for b in blocks if (b or "").strip()])

    def composed_context_for_prompt(self) -> str:
        return "\n---\n".join([b for b in self.context_blocks if (b or "").strip()])
