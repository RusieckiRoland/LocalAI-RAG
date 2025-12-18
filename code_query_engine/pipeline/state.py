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

    # History (from HistoryManager)
    history_blocks: List[str] = field(default_factory=list)
    history_summary: Optional[str] = None

    # Retrieved evidence (from vector/graph search)
    context_blocks: List[str] = field(default_factory=list)

    # Router / retrieval fields
    router_raw: Optional[str] = None
    retrieval_mode: Optional[str] = None  # semantic / bm25 / hybrid / semantic_rerank
    retrieval_scope: Optional[str] = None  # CS / SQL / ANY
    retrieval_query: Optional[str] = None
    retrieval_filters: Dict[str, Any] = field(default_factory=dict)

    # Answer + followup (simple pipeline)
    answer_en: Optional[str] = None
    answer_pl: Optional[str] = None
    final_answer: Optional[str] = None
    followup_query: Optional[str] = None
    query_type: Optional[str] = None

    # Assessment pipeline: draft answer (kept OUTSIDE history/evidence on purpose)
    draft_answer_en: Optional[str] = None

    # Loop guard helpers
    used_followups: Set[str] = field(default_factory=set)
    turn_loop_counter: int = 0

    # Debug / telemetry
    steps_used: int = 0
    next_codellama_prompt: Optional[str] = None
    budget_debug: Dict[str, Any] = field(default_factory=dict)

    # Raw last output from model (whatever the last call produced)
    last_model_response: Optional[str] = None

    def model_input_en_or_fallback(self) -> str:
        return (self.user_question_en or self.user_query or "").strip()

    def history_for_prompt(self) -> str:
        blocks = list(self.history_blocks)
        if self.history_summary and self.history_summary.strip():
            blocks = [f"[HistorySummary]\n{self.history_summary.strip()}"] + blocks
        return "\n---\n".join([b for b in blocks if (b or "").strip()])

    def composed_context_for_prompt(self) -> str:
        return "\n---\n".join([b for b in self.context_blocks if (b or "").strip()])

    def answer_context_for_prompt(self) -> str:
        history = self.history_for_prompt().strip() or "(none)"
        evidence = self.composed_context_for_prompt().strip() or "(none)"
        return f"### History:\n{history}\n\n### Evidence:\n{evidence}"

    def assessor_context_for_prompt(self) -> str:
        base = self.answer_context_for_prompt()
        draft = (self.draft_answer_en or "").strip() or "(none)"
        return f"{base}\n\n### DraftAnswer:\n{draft}"
