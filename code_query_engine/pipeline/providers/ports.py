# code_query_engine/pipeline/providers/ports.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple


class IModelClient(Protocol):
    def ask(self, *, context: str, question: str, consultant: str) -> str:
        ...


class ITranslatorPlEn(Protocol):
    def translate(self, text: str) -> str:
        ...


class IMarkdownTranslatorEnPl(Protocol):
    def translate(self, markdown_en: str) -> str:
        ...


class IInteractionLogger(Protocol):
    def log_interaction(
        self,
        *,
        original_question: str,
        model_input_en: str,
        codellama_response: str,
        followup_query: Optional[str],
        query_type: Optional[str],
        final_answer: Optional[str],
        context_blocks: Sequence[str],
        next_codellama_prompt: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...


class IHistoryManager(Protocol):
    def get_context_blocks(self) -> List[str]:
        ...

    def add_iteration(self, followup: str, faiss_results: Sequence[Dict[str, Any]]) -> None:
        ...

    def set_final_answer(self, answer_en: str, answer_pl: Optional[str]) -> None:
        ...


class ITokenCounter(Protocol):
    def estimate(self, text: str) -> int:
        ...


class IHistoryStore(Protocol):
    def load_turns(self) -> List[Dict[str, str]]:
        ...

    def load_summary_state(self) -> Tuple[str, int]:
        ...

    def persist_turn(
        self,
        *,
        question_original: str,
        question_en: str,
        answer_en: str,
        answer_pl: str,
        used_context: str,
        retrieval_mode: str,
        retrieval_query: str,
        metadata: Dict[str, Any],
    ) -> None:
        ...

    def persist_summary_state(self, summary_text: str, last_turn_idx: int) -> None:
        ...


class IRetriever(Protocol):
    def search(self, query: str, *, top_k: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        ...


class IGraphProvider(Protocol):
    def expand(
        self,
        *,
        repository: str,
        active_index: str,
        seed_nodes: Sequence[str],
        max_depth: int,
        max_nodes: int,
        edge_allowlist: Sequence[str],
    ) -> Dict[str, Any]:
        ...

    def fetch_node_texts(
        self,
        *,
        repository: str,
        active_index: str,
        node_ids: Sequence[str],
        top_n: int,
    ) -> List[Dict[str, Any]]:
        ...
