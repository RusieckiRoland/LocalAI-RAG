# File: code_query_engine/pipeline/providers/fakes.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from .ports import IModelClient, IRetriever


@dataclass
class ModelCall:
    context: str
    question: str
    consultant: str


class FakeModelClient(IModelClient):
    """
    Deterministic model fake:
    - If resolver is provided: returns resolver(call).
    - Else returns scripted outputs per consultant in FIFO order.
    """

    def __init__(
        self,
        *,
        outputs_by_consultant: Optional[Dict[str, Sequence[str]]] = None,
        outputs: Optional[Sequence[str]] = None,
        resolver: Optional[Callable[[ModelCall], str]] = None,
    ) -> None:
        self._outputs_by_consultant = {k: list(v) for k, v in (outputs_by_consultant or {}).items()}
        self._outputs = list(outputs or [])
        self._resolver = resolver
        self.calls: List[ModelCall] = []

    def ask(self, *, context: str, question: str, consultant: str) -> str:
        call = ModelCall(context=context, question=question, consultant=consultant)
        self.calls.append(call)

        if self._resolver is not None:
            return str(self._resolver(call) or "")

        if consultant in self._outputs_by_consultant:
            q = self._outputs_by_consultant[consultant]
            return q.pop(0) if q else ""

        return self._outputs.pop(0) if self._outputs else ""


class FakeRetriever(IRetriever):
    """
    Deterministic retriever fake:
    - If resolver is provided: returns resolver(query, top_k, filters).
    - Else returns scripted results per query in FIFO order.
    """

    def __init__(
        self,
        *,
        results_by_query: Optional[Dict[str, Sequence[List[Dict[str, Any]]]]] = None,
        results: Optional[List[Dict[str, Any]]] = None,
        resolver: Optional[Callable[[str, int, Optional[Dict[str, Any]]], List[Dict[str, Any]]]] = None,
    ) -> None:
        self._results_by_query = {k: list(v) for k, v in (results_by_query or {}).items()}
        self._results = list(results or [])
        self._resolver = resolver
        self.calls: List[Dict[str, Any]] = []

    def search(self, query: str, *, top_k: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self.calls.append({"query": query, "top_k": top_k, "filters": filters or {}})

        if self._resolver is not None:
            return list(self._resolver(query, top_k, filters))

        if query in self._results_by_query:
            q = self._results_by_query[query]
            return q.pop(0) if q else []

        # Default scripted results (repeat same results)
        return list(self._results)
