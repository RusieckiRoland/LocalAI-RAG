from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


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


class ServerLLMClient:
    """
    Minimal OpenAI-compatible HTTP client for llama.cpp (or similar servers).
    """
    supports_server_name = True
    supports_cancel_check = False

    def __init__(self, *, servers: Dict[str, ServerLLMConfig], default_name: str) -> None:
        self._servers = dict(servers or {})
        self._default_name = (default_name or "").strip()
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
        if top_k is not None:
            payload["top_k"] = int(top_k)
        if repeat_penalty is not None:
            payload["repeat_penalty"] = float(repeat_penalty)

        url = self._join(server.base_url, server.completions_path)
        res = self._post_json(url, payload, server=server)
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
        if top_k is not None:
            payload["top_k"] = int(top_k)
        if repeat_penalty is not None:
            payload["repeat_penalty"] = float(repeat_penalty)

        url = self._join(server.base_url, server.chat_completions_path)
        res = self._post_json(url, payload, server=server)
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

    def _post_json(self, url: str, payload: Dict[str, Any], *, server: ServerLLMConfig) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if server.api_key:
            req.add_header("Authorization", f"Bearer {server.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=server.timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)
        except Exception as e:
            logger.error("ServerLLMClient request failed: %s", e)
            raise

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
