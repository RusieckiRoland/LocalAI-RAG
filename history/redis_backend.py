import redis
from typing import Optional
from .history_backend import HistoryBackend

class RedisBackend(HistoryBackend):
    """Backend historii korzystający z prawdziwego Redis."""
    def __init__(self, host: str = "localhost", port: int = 6379):
        self.client = redis.Redis(host=host, port=port, decode_responses=True)

    def get(self, key: str) -> Optional[str]:
        return self.client.get(key)

    def set(self, key: str, value: str) -> None:
        self.client.set(key, value)

    def delete(self, key: str) -> None:
        self.client.delete(key)
