# File: history/history_manager.py
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from .history_backend import HistoryBackend


class HistoryManager:
    """
    High-level manager that stores and retrieves conversational history
    for a single session. It serializes history to JSON and delegates
    persistence to a pluggable `HistoryBackend`.

    Requirements implemented:
    - Persist ONLY:
        * the user's original query
        * the model's final answer
      (no intermediate retrieval chunks / follow-up iterations in history)
    - Keep `session_id` as the primary key, but also store `user_id` metadata
      (reserved for future authenticated users).

    Notes
    -----
    - `ttl` (in seconds) is optional and only used if the backend supports it.
      If the backend does not accept a `ttl` argument, the call gracefully
      falls back to a plain `set(key, value)`.
    """

    def __init__(
        self,
        backend: HistoryBackend,
        session_id: Optional[str] = None,
        ttl: Optional[int] = None,
        user_id: Optional[str] = None,
    ):
        self.session_id: str = session_id or str(uuid.uuid4())
        self.backend = backend
        self.ttl = ttl  # optional TTL in seconds; used only if the backend supports it
        self._user_id: Optional[str] = user_id

        # Persist initial user_id if provided (best effort).
        if user_id:
            self.set_user_id(user_id)

    # ------------------------------
    # Backend I/O
    # ------------------------------
    @property
    def _meta_key(self) -> str:
        return f"{self.session_id}:meta"

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

    def _save_meta(self, meta: dict[str, Any]) -> None:
        data = json.dumps(meta, ensure_ascii=False)
        try:
            self.backend.set(self._meta_key, data, ttl=self.ttl)  # type: ignore[call-arg]
        except TypeError:
            self.backend.set(self._meta_key, data)

    def _load_meta(self) -> dict[str, Any]:
        raw = self.backend.get(self._meta_key)
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        return {}

    # ------------------------------
    # Public API: session metadata
    # ------------------------------
    def set_user_id(self, user_id: str) -> None:
        """
        Store user_id as session metadata.

        This does NOT change session_id-based routing today.
        It's reserved for future: authenticated users → list/restore sessions.
        """
        self._user_id = user_id
        meta = self._load_meta()
        meta["user_id"] = user_id
        meta["updated_at"] = time.time()
        if "created_at" not in meta:
            meta["created_at"] = time.time()
        self._save_meta(meta)

    def get_user_id(self) -> Optional[str]:
        if self._user_id:
            return self._user_id
        meta = self._load_meta()
        u = meta.get("user_id")
        return u if isinstance(u, str) and u.strip() else None

    # ------------------------------
    # Public API: history operations
    # ------------------------------
    def start_user_query(self, en: str, pl: Optional[str] = None, user_id: Optional[str] = None) -> None:
        """
        Start a new user query entry (appends to the session history).

        Parameters
        ----------
        en : str
            English version of the user's question. If empty, `pl` is used.
        pl : Optional[str]
            Polish version of the user's question (optional).
        user_id : Optional[str]
            User identifier (reserved for future authenticated sessions).
        """
        if user_id:
            self.set_user_id(user_id)

        history = self._load_history()
        question_en = (en or pl or "")  # keep non-None string

        # IMPORTANT: keep history compact: only original question and final answer.
        history.append(
            {
                "timestamp": time.time(),
                "user_query": {"pl": pl, "en": question_en},
                "final_answer": None,
            }
        )
        self._save_history(history)

    def add_iteration(self, codellama_query: str, faiss_results: list[dict[str, Any]]) -> None:
        """
        Legacy API kept for compatibility with pipeline actions/tests.

        Intentionally NO-OP:
        we no longer persist intermediate follow-ups / retriever chunks in session history,
        because it quickly explodes context size and pollutes future prompts.
        """
        return

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
        """Delete the entire session history for the current session id (and its metadata)."""
        self.backend.delete(self.session_id)
        self.backend.delete(self._meta_key)

    def get_context_blocks(self) -> list[str]:
        """
        Build a list of compact, human-readable context blocks summarizing the session.

        Returns
        -------
        list[str]
            A sequence of text blocks containing ONLY:
            - user question (EN)
            - final answer (EN)
        """
        history = self.get_history()
        blocks: list[str] = []

        for entry in history:
            question_en = entry.get("user_query", {}).get("en", "") or ""
            if question_en.strip():
                blocks.append(f"User asked: {question_en}")

            final_answer = entry.get("final_answer", {}) or {}
            ans_en = final_answer.get("en") if isinstance(final_answer, dict) else None
            if isinstance(ans_en, str) and ans_en.strip():
                blocks.append(f"Final answer: {ans_en}")

        return blocks
