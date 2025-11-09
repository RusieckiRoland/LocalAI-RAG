# File: history/history_manager.py
from __future__ import annotations

import uuid
import json
import time
from typing import Optional, Any

from .history_backend import HistoryBackend


class HistoryManager:
    """
    High-level manager that stores and retrieves conversational history
    for a single session. It serializes history to JSON and delegates
    persistence to a pluggable `HistoryBackend`.

    Notes
    -----
    - `ttl` (in seconds) is optional and only used if the backend supports it.
      If the backend does not accept a `ttl` argument, the call gracefully
      falls back to a plain `set(key, value)`.
    """

    def __init__(self, backend: HistoryBackend, session_id: Optional[str] = None, ttl: Optional[int] = None):
        self.session_id: str = session_id or str(uuid.uuid4())
        self.backend = backend
        self.ttl = ttl  # optional TTL in seconds; used only if the backend supports it

    # ------------------------------
    # Backend I/O
    # ------------------------------
    def _load_history(self) -> list[dict[str, Any]]:
        """
        Load the full session history from the backend.
        Returns an empty list if the key does not exist or if the payload is invalid.
        """
        raw = self.backend.get(self.session_id)
        if raw:
            try:
                data = json.loads(raw)
                # Ensure the shape is a list of dicts
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
            except json.JSONDecodeError:
                pass
        return []

    def _save_history(self, history: list[dict[str, Any]]) -> None:
        """
        Serialize and persist the history. If the backend supports a `ttl` argument,
        it will be used; otherwise we silently ignore it.
        """
        data = json.dumps(history, ensure_ascii=False)
        try:
            # Some backends may support TTL: set(key, value, ttl=...)
            self.backend.set(self.session_id, data, ttl=self.ttl)  # type: ignore[call-arg]
        except TypeError:
            # Fallback to the interface contract: set(key, value)
            self.backend.set(self.session_id, data)

    # ------------------------------
    # Public API: history operations
    # ------------------------------
    def start_user_query(self, en: str, pl: Optional[str] = None) -> None:
        """
        Start a new user query entry (appends to the session history).

        Parameters
        ----------
        en : str
            English version of the user's question. If empty, `pl` is used.
        pl : Optional[str]
            Polish version of the user's question (optional).
        """
        history = self._load_history()
        question_en = (en or pl or "")  # keep non-None string
        history.append({
            "timestamp": time.time(),
            "user_query": {"pl": pl, "en": question_en},
            "iterations": [],
            "final_answer": None,
        })
        self._save_history(history)

    def add_iteration(self, codellama_query: str, faiss_results: list[dict[str, Any]]) -> None:
        """
        Append an iteration record to the latest user query.

        Parameters
        ----------
        codellama_query : str
            The follow-up/search query sent to CodeLlama (controller decision).
        faiss_results : list[dict[str, Any]]
            A list of FAISS search results (already serialized to plain dicts).
        """
        history = self._load_history()
        if not history:
            raise RuntimeError("No user query to attach iteration.")
        history[-1]["iterations"].append({
            "timestamp": time.time(),
            "codellama_query": codellama_query,
            "faiss_results": faiss_results,
        })
        self._save_history(history)

    def set_final_answer(self, en: str, pl: Optional[str] = None) -> None:
        """
        Set the final answer for the latest user query.

        Parameters
        ----------
        en : str
            Final English answer (required).
        pl : Optional[str]
            Final Polish answer (optional). If not provided, falls back to `en`.
        """
        history = self._load_history()
        if not history:
            raise RuntimeError("No user query to attach final answer.")
        history[-1]["final_answer"] = {"en": en, "pl": (pl or en)}
        self._save_history(history)

    def get_history(self) -> list[dict[str, Any]]:
        """Return the entire session history as a list of dicts."""
        return self._load_history()

    def clear_history(self) -> None:
        """Delete the entire session history for the current session id."""
        self.backend.delete(self.session_id)

    def get_context_blocks(self) -> list[str]:
        """
        Build a list of compact, human-readable context blocks summarizing the session.

        Returns
        -------
        list[str]
            A sequence of text blocks combining user queries, iterations and final answers.
        """
        history = self.get_history()
        blocks: list[str] = []

        for entry in history:
            # Add the user's (English) question
            question_en = entry.get("user_query", {}).get("en", "") or ""
            blocks.append(f"User asked: {question_en}")

            # Add CodeLlama iterations and FAISS results
            for iteration in entry.get("iterations", []):
                q = iteration.get("codellama_query", "") or ""
                faiss_results_list = iteration.get("faiss_results", []) or []
                faiss_results = "\n".join(
                    json.dumps(r, ensure_ascii=False) for r in faiss_results_list
                )
                blocks.append(f"CodeLlama asked: {q}\n{faiss_results}")

            # Add the final (English) answer if present
            final_answer = entry.get("final_answer", {}) or {}
            if final_answer.get("en"):
                blocks.append(f"Final answer: {final_answer['en']}")

        return blocks
