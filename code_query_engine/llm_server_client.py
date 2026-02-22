from __future__ import annotations

import json
import logging
import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, TypeVar, Iterable, Tuple

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
    allowed_doc_level: Optional[int] = None
    allowed_acl_labels: Tuple[str, ...] = ()
    allowed_classification_labels: Tuple[str, ...] = ()
    is_trusted_server: bool = False
    is_trusted_for_all_acl: bool = False


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
    supports_security_context = True

    def __init__(
        self,
        *,
        servers: Dict[str, ServerLLMConfig],
        default_name: str,
        ordered_names: Optional[list[str]] = None,
    ) -> None:
        self._servers = dict(servers or {})
        self._default_name = (default_name or "").strip()
        self._ordered_names = list(ordered_names or [])
        self._throttles: dict[str, OpenAIThrottle] = {}
        if not self._default_name:
            raise ValueError("ServerLLMClient: default_name is required")
        if self._default_name not in self._servers:
            raise ValueError(f"ServerLLMClient: default server '{self._default_name}' not found")
        if not self._ordered_names:
            self._ordered_names = list(self._servers.keys())

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
        security_context: Optional[dict[str, Any]] = None,
    ) -> str:
        server, notice_kind = self._select_server(server_name, security_context=security_context)
        if server is None:
            self._apply_security_notice(security_context, notice_kind or "no_server")
            return ""
        if notice_kind:
            self._apply_security_notice(security_context, notice_kind)
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
        security_context: Optional[dict[str, Any]] = None,
    ) -> str:
        server, notice_kind = self._select_server(server_name, security_context=security_context)
        if server is None:
            self._apply_security_notice(security_context, notice_kind or "no_server")
            return ""
        if notice_kind:
            self._apply_security_notice(security_context, notice_kind)
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

    def _select_server(
        self,
        name: Optional[str],
        *,
        security_context: Optional[dict[str, Any]] = None,
    ) -> tuple[Optional[ServerLLMConfig], Optional[str]]:
        preferred = (name or "").strip() or self._default_name
        ordered = [x for x in self._ordered_names if x in self._servers]
        if preferred and preferred not in ordered:
            ordered = [preferred] + ordered

        candidates: list[str] = []
        if preferred:
            candidates.append(preferred)
        for n in ordered:
            if n not in candidates:
                candidates.append(n)

        if not security_context:
            key = preferred or self._default_name
            server = self._servers.get(key)
            if server is None:
                raise ValueError(f"ServerLLMClient: server '{key}' not found")
            return server, None

        first = True
        for key in candidates:
            server = self._servers.get(key)
            if server is None:
                continue
            if self._server_allows_security(server, security_context):
                if first:
                    return server, None
                return server, "override"
            first = False

        return None, "no_server"

    @staticmethod
    def _normalize_labels(values: Iterable[Any]) -> set[str]:
        out: set[str] = set()
        for v in values or []:
            s = str(v or "").strip().lower()
            if s:
                out.add(s)
        return out

    def _server_allows_security(self, server: ServerLLMConfig, security_context: dict[str, Any]) -> bool:
        if server.is_trusted_server:
            return True
        doc_level_max = security_context.get("doc_level_max")
        acl_labels_union = self._normalize_labels(security_context.get("acl_labels_union", []))
        classification_labels_union = self._normalize_labels(security_context.get("classification_labels_union", []))

        if doc_level_max is not None:
            if server.allowed_doc_level is None:
                return False
            try:
                if int(server.allowed_doc_level) < int(doc_level_max):
                    return False
            except Exception:
                return False

        if acl_labels_union:
            allowed_acl = self._normalize_labels(server.allowed_acl_labels)
            if allowed_acl:
                if not acl_labels_union.issubset(allowed_acl):
                    return False
            else:
                if not server.is_trusted_for_all_acl:
                    return False

        if classification_labels_union:
            allowed_cls = self._normalize_labels(server.allowed_classification_labels)
            if not classification_labels_union.issubset(allowed_cls):
                return False

        return True

    @staticmethod
    def _resolve_notice_message(
        security_context: Optional[dict[str, Any]],
        *,
        kind: str,
    ) -> str:
        if not security_context:
            return ""
        translate_chat = bool(security_context.get("translate_chat", False))
        pipeline_settings = security_context.get("pipeline_settings") or {}
        custom = pipeline_settings.get("llm_server_security_messages") or {}
        defaults = pipeline_settings.get("llm_server_security_messages_default") or {}

        def _pick(bundle: Any) -> str:
            if not isinstance(bundle, dict):
                return ""
            key = "translated" if translate_chat else "neutral"
            val = bundle.get(key)
            if val:
                return str(val)
            fallback_key = "neutral" if key == "translated" else "translated"
            fallback = bundle.get(fallback_key)
            return str(fallback) if fallback else ""

        if kind == "override":
            msg = _pick(custom.get("override_notice") or {})
            if msg:
                return msg
            msg = _pick(defaults.get("override_notice") or {})
            return msg

        if kind == "no_server":
            msg = _pick(custom.get("no_server_notice") or {})
            if msg:
                return msg
            msg = _pick(defaults.get("no_server_notice") or {})
            return msg

        return ""

    def _apply_security_notice(self, security_context: Optional[dict[str, Any]], kind: str) -> None:
        if not security_context:
            return
        state = security_context.get("state")
        if state is None:
            return
        msg = self._resolve_notice_message(security_context, kind=kind)
        if not msg:
            if kind == "override":
                msg = "LLM server was changed because the default server does not satisfy security policy."
            else:
                msg = "Analysis was not performed because no LLM server satisfies security policy."
        try:
            setattr(state, "llm_server_security_override_notice", msg)
        except Exception:
            return


class HybridLLMClient:
    """
    Routes calls to server LLMs when allowed; otherwise falls back to local model.
    """
    supports_server_name = True
    supports_security_context = True

    def __init__(
        self,
        *,
        local_model: Any,
        server_client: ServerLLMClient,
    ) -> None:
        self._local = local_model
        self._server = server_client
        self.supports_cancel_check = bool(getattr(local_model, "supports_cancel_check", False))
        self.default_max_tokens = getattr(local_model, "default_max_tokens", None)
        self.n_ctx = getattr(local_model, "n_ctx", None)
        self.llm = getattr(local_model, "llm", None)

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
        cancel_check: Optional[Callable[[], None]] = None,
        security_context: Optional[dict[str, Any]] = None,
    ) -> str:
        server, notice_kind = self._server._select_server(server_name, security_context=security_context)
        if server is not None:
            if notice_kind:
                self._server._apply_security_notice(security_context, notice_kind)
            return self._server.ask(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                repeat_penalty=repeat_penalty,
                top_k=top_k,
                top_p=top_p,
                server_name=server.name,
                security_context=security_context,
            )

        # No server allowed; try local model if present.
        if self._local is None:
            self._server._apply_security_notice(security_context, "no_server")
            return ""

        # If we got here, we are explicitly falling back to local due to security policy.
        self._server._apply_security_notice(security_context, "override")
        return self._local.ask(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            repeat_penalty=repeat_penalty,
            top_k=top_k,
            top_p=top_p,
            cancel_check=cancel_check,
        )

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
        cancel_check: Optional[Callable[[], None]] = None,
        security_context: Optional[dict[str, Any]] = None,
    ) -> str:
        server, notice_kind = self._server._select_server(server_name, security_context=security_context)
        if server is not None:
            if notice_kind:
                self._server._apply_security_notice(security_context, notice_kind)
            return self._server.ask_chat(
                prompt=prompt,
                history=history,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                repeat_penalty=repeat_penalty,
                top_k=top_k,
                top_p=top_p,
                server_name=server.name,
                security_context=security_context,
            )

        if self._local is None:
            self._server._apply_security_notice(security_context, "no_server")
            return ""

        self._server._apply_security_notice(security_context, "override")
        return self._local.ask_chat(
            prompt=prompt,
            history=history,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            repeat_penalty=repeat_penalty,
            top_k=top_k,
            top_p=top_p,
            cancel_check=cancel_check,
        )

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
