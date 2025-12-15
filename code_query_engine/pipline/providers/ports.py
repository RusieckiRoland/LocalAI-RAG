# File: code_query_engine/pipeline/providers/ports.py

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple


class IModelClient(Protocol):
    def ask(self, *, context: str, question: str, consultant: str) -> str:
        ...


class ITranslatorPlEn(Protocol):
    def translate(self, text: str) -> str:
        ...


class IMarkdownTranslatorEnPl(Protocol):
    def translate_markdown(self, text: str) -> str:
        ...


class ITokenCounter(Protocol):
    def estimate(self, text: str) -> int:
        ...


class IHistoryStore(Protocol):
    def load_turns(self) -> List[Dict[str, str]]:
        ...

    def load_summary_state(self) -> Tuple[str, int]:
        ...

    def persist_turn(self, *, question_original: str, question_en: str, answer_en: str, router_mode: str, router_query: str) -> None:
        ...

    def persist_summary_state(self, *, summary: str, last_included_turn_index: int) -> None:
        ...


class IRetriever(Protocol):
    def search(self, query: str, *, top_k: int, filters: Optional[Dict[str, List[str]]] = None) -> List[Dict[str, Any]]:
        ...


class IGraphProvider(Protocol):
    def expand(
        self,
        *,
        retrieved_hits: List[Dict[str, Any]],
        max_depth: int,
        max_nodes: int,
        edge_allowlist: List[str],
    ) -> List[str]:
        ...

    def fetch_node_texts(self, *, node_ids: List[str], top_n: int) -> List[Dict[str, Any]]:
        ...
