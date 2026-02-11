from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from .retrieval_backend_contract import SearchRequest, SearchResponse


class IInteractionLogger(Protocol):
    def log_interaction(
        self,
        *,
        session_id: str,
        pipeline_name: str,
        step_id: str,
        action: str,
        data: Dict[str, Any],
    ) -> None:
        ...


class IModelClient(Protocol):
    def ask(
        self,
        *,
        prompt: str,
        consultant: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        ...


class IRetriever(Protocol):
    def search(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        ...


class IRetrievalBackend(Protocol):
    def search(self, req: SearchRequest) -> SearchResponse:
        ...

    def fetch_texts(
        self,
        *,
        node_ids: List[str],
        repository: str,
        snapshot_id: Optional[str],
        retrieval_filters: Dict[str, Any],
    ) -> Dict[str, str]:
        ...


class IMarkdownTranslatorEnPl(Protocol):
    def translate(self, text: str) -> str:
        ...


class ITranslatorPlEn(Protocol):
    def translate(self, text: str) -> str:
        ...


class IHistoryManager(Protocol):
    def start_user_query(self, question_en: str, question_pl: Optional[str]) -> None:
        ...

    def add_iteration(self, query: str, results: List[Dict[str, Any]]) -> None:
        ...

    def set_final_answer(self, answer_en: str, answer_translated: Optional[str] = None) -> None:
        ...

    def get_context_blocks(self) -> List[str]:
        ...


class ITokenCounter(Protocol):
    def count_tokens(self, text: str) -> int:
        ...


class IGraphProvider(Protocol):
    def expand_dependency_tree(
        self,
        *,
        seed_nodes: List[str],
        max_depth: int = 2,
        max_nodes: int = 200,
        edge_allowlist: Optional[List[str]] = None,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ...

    def filter_by_permissions(
        self,
        *,
        node_ids: List[str],
        retrieval_filters: Optional[Dict[str, Any]] = None,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        snapshot_id: Optional[str] = None,
    ) -> List[str]:
        ...

    
