from __future__ import annotations

import json
import logging
import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, TypeVar

from code_query_engine.llm_query_logger import log_llm_query, LLMCallTimer


logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class ServerLLMConfig:
    name: str
    base_url: str
    api_key: str = ""
    timeout_seconds: int = 120
    mode: str = "openai"
    model: str = ""
    completions_path: str = "/v1/completions"
    chat_completions_path: str = "/v1/chat/completions"
    throttling_enabled: bool = False
    throttling: Optional["ThrottleConfig"] = None


@dataclass(frozen=True)
class ThrottleConfig:
    max_concurrency: int = 1
    max_retries: int = 8
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    jitter_seconds: float = 0.25
    retry_on_status: tuple[int, ...] = (429, 503, 502, 504)


class OpenAIThrottle:
    """
    Thread-safe throttler:
    - Limits concurrency via semaphore
    - Retries with exponential backoff (+ jitter)
    - Honors Retry-After header when present
    """

    def __init__(self, cfg: ThrottleConfig):
        self._cfg = cfg
        self._sem = threading.Semaphore(cfg.max_concurrency)

    def call(self, fn: Callable[[], T]) -> T:
        with self._sem:
            attempt = 0
            while True:
                try:
                    return fn()
                except urllib.error.HTTPError as e:
                    if e.code not in self._cfg.retry_on_status:
                        raise

                    attempt += 1
                    if attempt > self._cfg.max_retries:
                        raise

                    retry_after = self._parse_retry_after(e)
                    sleep_s = self._compute_sleep(attempt, retry_after)
                    time.sleep(sleep_s)

    def _parse_retry_after(self, e: urllib.error.HTTPError) -> Optional[float]:
        ra = None
        try:
            ra = e.headers.get("Retry-After")
        except Exception:
            ra = None

        if not ra:
            return None

        try:
            return float(ra)
        except ValueError:
            return None

    def _compute_sleep(self, attempt: int, retry_after: Optional[float]) -> float:
        if retry_after is not None:
            return max(0.0, min(self._cfg.max_backoff_seconds, retry_after))

        exp = self._cfg.base_backoff_seconds * (2 ** (attempt - 1))
        exp = min(self._cfg.max_backoff_seconds, exp)
        jitter = random.random() * self._cfg.jitter_seconds
        return exp + jitter


class ServerLLMClient:
    """
    Minimal OpenAI-compatible HTTP client for llama.cpp (or similar servers).
    """
    supports_server_name = True
    supports_cancel_check = False

    def __init__(self, *, servers: Dict[str, ServerLLMConfig], default_name: str) -> None:
        self._servers = dict(servers or {})
        self._default_name = (default_name or "").strip()
        self._throttles: dict[str, OpenAIThrottle] = {}
        if not self._default_name:
            raise ValueError("ServerLLMClient: default_name is required")
        if self._default_name not in self._servers:
            raise ValueError(f"ServerLLMClient: default server '{self._default_name}' not found")

    def ask(
        self,
        *,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        repeat_penalty: float = 1.2,
        top_k: int = 40,
        top_p: Optional[float] = None,
        server_name: Optional[str] = None,
    ) -> str:
        server = self._select_server(server_name)
        if system_prompt:
            prompt = f"{system_prompt}\n\n{prompt}"

        payload: Dict[str, Any] = {
            "prompt": prompt,
        }
        if server.model:
            payload["model"] = server.model
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if top_p is not None:
            payload["top_p"] = float(top_p)
        if server.mode != "openai":
            if top_k is not None:
                payload["top_k"] = int(top_k)
            if repeat_penalty is not None:
                payload["repeat_penalty"] = float(repeat_penalty)

        url = self._join(server.base_url, server.completions_path)
        res = self._post_json(url, payload, server=server, op="server_completion")
        return self._extract_completion_text(res)

    def ask_chat(
        self,
        *,
        prompt: str,
        history: Optional[list[tuple[str, str]]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        repeat_penalty: float = 1.2,
        top_k: int = 40,
        top_p: Optional[float] = None,
        server_name: Optional[str] = None,
    ) -> str:
        server = self._select_server(server_name)
        messages: list[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for user_msg, assistant_msg in history:
                messages.append({"role": "user", "content": user_msg})
                messages.append({"role": "assistant", "content": assistant_msg})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "messages": messages,
        }
        if server.model:
            payload["model"] = server.model
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if top_p is not None:
            payload["top_p"] = float(top_p)
        if server.mode != "openai":
            if top_k is not None:
                payload["top_k"] = int(top_k)
            if repeat_penalty is not None:
                payload["repeat_penalty"] = float(repeat_penalty)

        url = self._join(server.base_url, server.chat_completions_path)
        res = self._post_json(url, payload, server=server, op="server_chat")
        return self._extract_chat_text(res)

    def _select_server(self, name: Optional[str]) -> ServerLLMConfig:
        key = (name or "").strip() or self._default_name
        server = self._servers.get(key)
        if server is None:
            raise ValueError(f"ServerLLMClient: server '{key}' not found")
        return server

    @staticmethod
    def _join(base: str, path: str) -> str:
        return base.rstrip("/") + "/" + path.lstrip("/")

    def _post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        *,
        server: ServerLLMConfig,
        op: str,
    ) -> Dict[str, Any]:
        timer = LLMCallTimer()

        def _do_request() -> Dict[str, Any]:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            if server.api_key:
                req.add_header("Authorization", f"Bearer {server.api_key}")
            with urllib.request.urlopen(req, timeout=server.timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)
        try:
            if server.throttling_enabled:
                throttle = self._get_throttle(server)
                res = throttle.call(_do_request)
            else:
                res = _do_request()
            log_llm_query(
                op=op,
                request={
                    "url": url,
                    "server": server.name,
                    "mode": server.mode,
                    "payload": payload,
                },
                response=res,
                duration_ms=timer.ms(),
            )
            return res
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                body = "<unreadable>"
            log_llm_query(
                op=op,
                request={
                    "url": url,
                    "server": server.name,
                    "mode": server.mode,
                    "payload": payload,
                },
                response=body,
                error=str(e),
                duration_ms=timer.ms(),
            )
            logger.error("ServerLLMClient request failed: %s body=%s", e, body)
            raise
        except Exception as e:
            log_llm_query(
                op=op,
                request={
                    "url": url,
                    "server": server.name,
                    "mode": server.mode,
                    "payload": payload,
                },
                response=None,
                error=str(e),
                duration_ms=timer.ms(),
            )
            logger.error("ServerLLMClient request failed: %s", e)
            raise

    def _get_throttle(self, server: ServerLLMConfig) -> OpenAIThrottle:
        existing = self._throttles.get(server.name)
        if existing is not None:
            return existing
        cfg = server.throttling or ThrottleConfig()
        throttle = OpenAIThrottle(cfg)
        self._throttles[server.name] = throttle
        return throttle

    @staticmethod
    def _extract_completion_text(res: Dict[str, Any]) -> str:
        try:
            return (res.get("choices") or [{}])[0].get("text", "").strip()
        except Exception:
            return ""

    @staticmethod
    def _extract_chat_text(res: Dict[str, Any]) -> str:
        try:
            choice = (res.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            text = msg.get("content") or choice.get("text") or ""
            return str(text).strip()
        except Exception:
            return ""
