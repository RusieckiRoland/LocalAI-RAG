from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class ConversationTurn:
    """
    Canonical stored unit: one user question + one final answer.

    Conceptual language model:
    - neutral: language-neutral canonical representation (currently English in this project)
    - translated: optional user/UI language representation (currently Polish in this project)
    """

    turn_id: str
    session_id: str
    request_id: str
    created_at_utc: str

    identity_id: Optional[str] = None
    finalized_at_utc: Optional[str] = None

    question_neutral: str = ""
    answer_neutral: Optional[str] = None

    question_translated: Optional[str] = None
    answer_translated: Optional[str] = None
    answer_translated_is_fallback: Optional[bool] = None

    metadata: dict[str, Any] = field(default_factory=dict)

