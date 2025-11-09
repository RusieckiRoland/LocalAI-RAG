from typing import Optional
from .history_backend import HistoryBackend

class InMemoryMockRedis(HistoryBackend):
    """Prosty mock backend historii w pamięci."""
    def __init__(self):
        self.storage: dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self.storage.get(key)

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        """Ustawia wartość w pamięci, TTL jest ignorowany w mocku."""
        self.storage[key] = value

    def delete(self, key: str) -> None:
        self.storage.pop(key, None)

