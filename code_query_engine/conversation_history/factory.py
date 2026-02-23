from __future__ import annotations

import os
from typing import Optional

from history.history_backend import HistoryBackend

from .durable_store_memory import InMemoryUserConversationStore
from .ports import IConversationHistoryService, IUserConversationStore
from .service import ConversationHistoryService
from .session_store_kv import KvSessionConversationStore


def build_conversation_history_service(
    *,
    session_backend: HistoryBackend,
    durable_store: Optional[IUserConversationStore] = None,
) -> IConversationHistoryService:
    """
    Default wiring:
    - session store: HistoryBackend (Redis or in-memory mock) via KvSessionConversationStore
    - durable store: in-memory mock unless a real SQL store is injected

    Env knobs:
    - APP_CONV_HIST_TTL_S: optional session TTL seconds
    - APP_CONV_HIST_MAX_TURNS: optional session hard cap (default 200)
    """

    ttl_raw = (os.getenv("APP_CONV_HIST_TTL_S") or "").strip()
    ttl_s = int(ttl_raw) if ttl_raw else None

    max_turns_raw = (os.getenv("APP_CONV_HIST_MAX_TURNS") or "").strip()
    max_turns = int(max_turns_raw) if max_turns_raw else 200

    session_store = KvSessionConversationStore(backend=session_backend, ttl_s=ttl_s, max_turns=max_turns)
    durable = durable_store or InMemoryUserConversationStore()

    return ConversationHistoryService(session_store=session_store, durable_store=durable)

