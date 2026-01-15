# File: code_query_engine/pipeline/providers/fakes.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from .ports import IModelClient, IRetriever


@dataclass
class ModelCall:
    """
    Unified call log for both manual prompt mode and native chat mode.

    Notes:
    - CallModelAction.ask_manual_prompt_llm calls:
        model.ask(prompt=..., system_prompt=None, **model_kwargs)
    - CallModelAction.ask_chat_mode_llm calls:
        model.ask_chat(prompt=..., history=..., system_prompt=..., **model_kwargs)
    """

    consultant: str
    prompt: str
    system_prompt: Optional[str]
    mode: str  # "manual" | "chat"
    history: Optional[List[Dict[str, str]]] = None
    model_kwargs: Optional[Dict[str, Any]] = None


class FakeModelClient(IModelClient):
    """
    Deterministic model fake:
    - If resolver is provided: returns resolver(call).
    - Else returns scripted outputs per consultant in FIFO order.

    Contract compatibility:
    - Supports model.ask(prompt=..., system_prompt=..., **kwargs)
    - Supports model.ask_chat(prompt=..., history=..., system_prompt=..., **kwargs)
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

    def _pop_output(self, consultant: str) -> str:
        if consultant in self._outputs_by_consultant:
            q = self._outputs_by_consultant[consultant]
            return str(q.pop(0) if q else "")
        return str(self._outputs.pop(0) if self._outputs else "")

    def ask(
        self,
        *,
        prompt: str,
        system_prompt: Optional[str] = None,
        consultant: Optional[str] = None,
        **model_kwargs: Any,
    ) -> str:
        # Production CallModelAction does NOT pass consultant to model.ask(...).
        eff_consultant = str(consultant or "e2e_smoke")

        call = ModelCall(
            consultant=eff_consultant,
            prompt=str(prompt or ""),
            system_prompt=system_prompt,
            mode="manual",
            history=None,
            model_kwargs=dict(model_kwargs or {}),
        )
        self.calls.append(call)

        if self._resolver is not None:
            return str(self._resolver(call) or "")
        return self._pop_output(eff_consultant)

    def ask_chat(
        self,
        *,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        consultant: Optional[str] = None,
        **model_kwargs: Any,
    ) -> str:
        eff_consultant = str(consultant or "e2e_smoke")

        call = ModelCall(
            consultant=eff_consultant,
            prompt=str(prompt or ""),
            system_prompt=system_prompt,
            mode="chat",
            history=list(history or []),
            model_kwargs=dict(model_kwargs or {}),
        )
        self.calls.append(call)

        if self._resolver is not None:
            return str(self._resolver(call) or "")
        return self._pop_output(eff_consultant)


class FakeRetriever(IRetriever):
    """
    Deterministic retriever fake:
    - If resolver is provided: returns resolver(query, top_k, filters).
    - Else returns scripted results.

    Contract compatibility:
    - search(query, *, top_k, settings, filters) -> List[Dict[str, Any]]
    - Records calls to self.calls for assertions.
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

    def search(
        self,
        query: str,
        *,
        top_k: int,
        settings=None,
        filters=None,
    ) -> List[Dict[str, Any]]:
        self.calls.append(
            {
                "query": str(query or ""),
                "top_k": int(top_k) if top_k is not None else None,
                "settings": dict(settings or {}) if isinstance(settings, dict) else settings,
                "filters": dict(filters or {}) if isinstance(filters, dict) else filters,
            }
        )

        if top_k is None or top_k <= 0:
            return []

        if self._resolver is not None:
            return list(self._resolver(str(query or ""), int(top_k), filters) or [])[: int(top_k)]

        q = str(query or "")
        if q in self._results_by_query and self._results_by_query[q]:
            batch = self._results_by_query[q].pop(0) or []
            return list(batch)[: int(top_k)]

        return list(self._results)[: int(top_k)]
