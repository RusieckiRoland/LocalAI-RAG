# File: history/history_backend.py
from abc import ABC, abstractmethod
from typing import Optional


class HistoryBackend(ABC):
    """
    Interface for a history storage backend (e.g., Redis, SQL, in-memory mock).

    Implementations are expected to behave like a simple string key–value store.
    """

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Return the value for `key`, or None if the key does not exist."""
        ...

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        """Set `key` to `value` (overwrites any existing value)."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove `key` and its value; no-op if the key does not exist."""
        ...
