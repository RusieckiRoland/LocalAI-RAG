from __future__ import annotations

import logging
import json
import os
import re
import time
import uuid
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request, send_file, send_from_directory, g, Response
from flask_cors import CORS

from common.logging_setup import LoggingConfig, configure_logging, logging_config_from_runtime_config
from common.markdown_translator_en_pl import MarkdownTranslator
from common.translator_pl_en import Translator


from .dynamic_pipeline import DynamicPipelineRunner
from history.redis_backend import RedisBackend
from history.mock_redis import InMemoryMockRedis
from .log_utils import InteractionLogger
from vector_db.weaviate_client import get_settings as get_weaviate_settings, create_client as create_weaviate_client
from code_query_engine.pipeline.providers.weaviate_retrieval_backend import WeaviateRetrievalBackend
from code_query_engine.pipeline.providers.weaviate_graph_provider import WeaviateGraphProvider
from server.auth import get_default_user_access_provider, UserAccessContext
from server.auth.policies_provider import default_json_provider
from server.app_config import AppConfigService, default_templates_store
from server.pipelines import PipelineAccessService, PipelineSnapshotStore
from server.snapshots import SnapshotRegistry
from code_query_engine.conversation_history.types import ConversationTurn
from code_query_engine.conversation_history.ports import IUserConversationStore
from code_query_engine.work_callback import (
    get_work_callback_broker,
    register_cancel_routes,
    register_work_callback_routes,
    resolve_callback_policy,
)
from code_query_engine.pipeline.cancellation import PipelineCancelled


py_logger = logging.getLogger(__name__)

try:
    import jwt as _pyjwt  # type: ignore
    from jwt import PyJWKClient as _PyJWKClient  # type: ignore
    from jwt.exceptions import ExpiredSignatureError as _JwtExpiredSignatureError  # type: ignore
    from jwt.exceptions import InvalidAudienceError as _JwtInvalidAudienceError  # type: ignore
    from jwt.exceptions import InvalidTokenError as _JwtInvalidTokenError  # type: ignore
    from jwt.exceptions import PyJWKClientError as _JwtPyJwkClientError  # type: ignore
except Exception:
    _pyjwt = None
    _PyJWKClient = None
    _JwtExpiredSignatureError = Exception
    _JwtInvalidAudienceError = Exception
    _JwtInvalidTokenError = Exception
    _JwtPyJwkClientError = Exception



# ------------------------------------------------------------
# Paths / constants
# ------------------------------------------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

RUNTIME_CONFIG_DEFAULT_PATH = os.path.join(PROJECT_ROOT, "config.json")
RUNTIME_CONFIG_DEV_PATH = os.path.join(PROJECT_ROOT, "config.dev.json")
RUNTIME_CONFIG_PROD_PATH = os.path.join(PROJECT_ROOT, "config.prod.json")
RUNTIME_CONFIG_TEST_PATH = os.path.join(PROJECT_ROOT, "config.test.json")
FRONTEND_HTML_PATH = os.path.join(PROJECT_ROOT, "frontend", "production", "Rag.html")
FRONTEND_ASSETS_DIR = os.path.join(PROJECT_ROOT, "frontend", "production", "assets")

REPOSITORIES_ROOT = os.path.join(PROJECT_ROOT, "repositories")

MAX_QUERY_LEN = int(os.getenv("APP_MAX_QUERY_LEN", "8000"))
MAX_FIELD_LEN = int(os.getenv("APP_MAX_FIELD_LEN", "128"))

API_TOKEN = (os.getenv("API_TOKEN") or "").strip()

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "null",
]

_json_cache_lock = Lock()
_json_cache: dict[str, tuple[float, dict]] = {}

_user_access_provider = get_default_user_access_provider()


# ------------------------------------------------------------
# JSON config (cached)
# ------------------------------------------------------------

def _load_json_file(path: str) -> dict:
    with _json_cache_lock:
        try:
            mtime = os.path.getmtime(path)
        except FileNotFoundError:
            return {}

        cached = _json_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]

        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            py_logger.exception("soft-failure: failed to load/parse JSON file: %s", path)
            data = {}

        _json_cache[path] = (mtime, data)
        return data


def _parse_env_bool(raw: Optional[str]) -> Optional[bool]:
    val = str(raw or "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return None


def _resolve_app_profile() -> str:
    raw = str(os.getenv("APP_PROFILE") or "").strip().lower()
    if not raw:
        return "prod"
    if raw in ("production",):
        return "prod"
    if raw in ("development",):
        return "dev"
    if raw in ("dev", "prod", "test"):
        return raw
    raise ValueError("Invalid APP_PROFILE. Allowed values: dev, prod, test.")


_app_profile = _resolve_app_profile()
os.environ.setdefault("APP_PROFILE", _app_profile)

_dev_allow_no_auth = _parse_env_bool(os.getenv("DEV_ALLOW_NO_AUTH")) is True
if _app_profile == "prod" and _dev_allow_no_auth:
    raise RuntimeError("DEV_ALLOW_NO_AUTH=true is forbidden when APP_PROFILE=prod.")

_auth_required = not _dev_allow_no_auth


def _resolve_runtime_config_path() -> str:
    explicit = str(os.getenv("APP_CONFIG_PATH") or "").strip()
    if explicit:
        return explicit if os.path.isabs(explicit) else os.path.join(PROJECT_ROOT, explicit)

    # Default by APP_PROFILE.
    if _app_profile == "dev" and os.path.exists(RUNTIME_CONFIG_DEV_PATH):
        return RUNTIME_CONFIG_DEV_PATH
    if _app_profile == "prod" and os.path.exists(RUNTIME_CONFIG_PROD_PATH):
        return RUNTIME_CONFIG_PROD_PATH
    if _app_profile == "test" and os.path.exists(RUNTIME_CONFIG_TEST_PATH):
        return RUNTIME_CONFIG_TEST_PATH
    return RUNTIME_CONFIG_DEFAULT_PATH


RUNTIME_CONFIG_PATH = _resolve_runtime_config_path()


def _load_runtime_cfg() -> dict:
    cfg = _load_json_file(RUNTIME_CONFIG_PATH) or {}
    if cfg:
        return cfg
    if RUNTIME_CONFIG_PATH != RUNTIME_CONFIG_DEFAULT_PATH:
        py_logger.warning(
            "runtime config not found at '%s'; falling back to '%s'",
            RUNTIME_CONFIG_PATH,
            RUNTIME_CONFIG_DEFAULT_PATH,
        )
        return _load_json_file(RUNTIME_CONFIG_DEFAULT_PATH) or {}
    return {}


_runtime_cfg = _load_runtime_cfg()
if "developement" in _runtime_cfg:
    py_logger.error("runtime config: invalid key 'developement' (typo). Use 'development' instead.")
    raise ValueError("runtime config contains invalid key 'developement' (typo). Use 'development'.")

_development_raw = _runtime_cfg.get("development", True)
_development_enabled = bool(_development_raw)
_development_env = _parse_env_bool(os.getenv("APP_DEVELOPMENT"))
if _development_env is True:
    _development_enabled = True
elif _development_env is False:
    _development_enabled = False

_mock_sql_raw = _runtime_cfg.get("mockSqlServer", False)
_mock_sql_enabled = bool(_mock_sql_raw) and _development_enabled
_mock_sql_ttl_hours_raw = _runtime_cfg.get("mockSqlTtlHours", 24 * 60)
try:
    _mock_sql_ttl_hours = float(_mock_sql_ttl_hours_raw)
except Exception:
    _mock_sql_ttl_hours = float(24 * 60)
_mock_sql_ttl_ms = int(max(0.0, _mock_sql_ttl_hours) * 3600 * 1000)
if _mock_sql_raw and not _development_enabled:
    py_logger.warning("mockSqlServer is enabled in config, but development mode is off; mock SQL history is disabled.")


def _load_fake_users(runtime_cfg: dict) -> dict[str, dict]:
    raw = runtime_cfg.get("fake_users") or []
    if not isinstance(raw, list):
        return {}
    out: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("id") or "").strip()
        if not uid:
            continue
        claims = item.get("claims") or {}
        if not isinstance(claims, dict):
            claims = {}
        out[uid] = {
            "id": uid,
            "userName": str(item.get("userName") or uid).strip() or uid,
            "claims": claims,
        }
    return out


_fake_users_by_id: dict[str, dict] = _load_fake_users(_runtime_cfg)


# ------------------------------------------------------------
# Logging (source of truth: config.json)
# ------------------------------------------------------------

_logging_cfg = logging_config_from_runtime_config(_runtime_cfg)
configure_logging(_logging_cfg)


def _warn_or_raise_security(message: str, *, strict: bool) -> None:
    if strict:
        raise ValueError(message)
    py_logger.warning(message)


def _validate_security_consistency(*, runtime_cfg: dict, client: Any | None, strict: bool) -> None:
    security = runtime_cfg.get("permissions") or {}
    if not isinstance(security, dict):
        _warn_or_raise_security("permissions config missing or invalid; security checks skipped", strict=strict)
        return

    if not security.get("security_enabled", False):
        _warn_or_raise_security(
            "permissions.security_enabled is false; system will not enforce security filters",
            strict=strict,
        )
        if client is not None:
            try:
                coll = client.collections.get("RagNode")
                cfg = coll.config.get()
                props = [p.name for p in (cfg.properties or [])]
                if "classification_labels" in props or "doc_level" in props:
                    _warn_or_raise_security(
                        "permissions: security_enabled is false but RagNode schema contains security fields (classification_labels/doc_level)",
                        strict=strict,
                    )
            except Exception:
                if strict:
                    raise RuntimeError("permissions: failed to validate RagNode schema when security is disabled")
                py_logger.exception("permissions: failed to validate RagNode schema when security is disabled")
        return

    model = security.get("security_model") or {}
    kind = str(model.get("kind") or "").strip()
    if kind not in ("clearance_level", "labels_universe_subset", "classification_labels"):
        _warn_or_raise_security("security.enabled is true but security_model.kind is missing/invalid", strict=strict)
        return

    # Validate Weaviate schema (best-effort).
    if client is not None:
        try:
            coll = client.collections.get("RagNode")
            cfg = coll.config.get()
            props = [p.name for p in (cfg.properties or [])]
            if bool(security.get("acl_enabled", True)) and "acl_allow" not in props:
                _warn_or_raise_security(
                    "permissions: acl_enabled is true but 'acl_allow' is missing in RagNode schema",
                    strict=strict,
                )
            if kind == "clearance_level":
                field = str((model.get("clearance_level") or {}).get("doc_level_field") or "doc_level")
                if field not in props:
                    _warn_or_raise_security(
                        f"permissions: doc_level field '{field}' not found in RagNode schema",
                        strict=strict,
                    )
            if kind in ("labels_universe_subset", "classification_labels"):
                field = str((model.get("labels_universe_subset") or model.get("classification_labels") or {}).get("doc_labels_field") or "classification_labels")
                if field not in props:
                    _warn_or_raise_security(
                        f"permissions: classification labels field '{field}' not found in RagNode schema",
                        strict=strict,
                    )
        except Exception:
            if strict:
                raise RuntimeError("permissions: failed to validate Weaviate schema for RagNode")
            py_logger.exception("permissions: failed to validate Weaviate schema for RagNode")

    # Validate auth policies and mappings.
    try:
        provider = default_json_provider()
        policies, claim_group_mappings = provider.load()
        group_ids = set(policies.keys())

        for rule in claim_group_mappings:
            if not isinstance(rule, dict):
                continue
            value_map = rule.get("value_map") or {}
            list_map = rule.get("list_map") or {}
            for _k, group in (value_map or {}).items():
                if str(group) not in group_ids:
                    _warn_or_raise_security(
                        f"permissions: claim_group_mappings refers to unknown group '{group}'",
                        strict=strict,
                    )
            for _k, group in (list_map or {}).items():
                if str(group) not in group_ids:
                    _warn_or_raise_security(
                        f"permissions: claim_group_mappings refers to unknown group '{group}'",
                        strict=strict,
                    )

        if kind == "clearance_level":
            if not any(p.user_level is not None for p in policies.values()):
                _warn_or_raise_security(
                    "permissions: clearance_level enabled but no group has user_level in auth_policies",
                    strict=strict,
                )
        if kind in ("labels_universe_subset", "classification_labels"):
            universe = (model.get("labels_universe_subset") or model.get("classification_labels") or {}).get("classification_labels_universe") or []
            universe_set = set(str(x).strip() for x in universe if str(x).strip())
            if not universe_set:
                _warn_or_raise_security(
                    "permissions: labels_universe_subset enabled but classification_labels_universe is empty",
                    strict=strict,
                )
            for gid, policy in policies.items():
                for label in policy.classification_labels_all or []:
                    if label not in universe_set:
                        _warn_or_raise_security(
                            f"permissions: group '{gid}' has classification label '{label}' outside universe",
                            strict=strict,
                        )
    except Exception:
        if strict:
            raise RuntimeError("permissions: failed to validate auth_policies consistency")
        py_logger.exception("permissions: failed to validate auth_policies consistency")


@dataclass(frozen=True)
class IdpAuthSettings:
    enabled: bool
    issuer: str
    jwks_url: str
    audience: str
    algorithms: tuple[str, ...]
    required_claims: tuple[str, ...]


def _load_idp_auth_settings(runtime_cfg: Dict[str, Any]) -> IdpAuthSettings:
    # New pattern: auth.oidc.resource_server (JWT validation for API).
    auth = runtime_cfg.get("auth") or {}
    if not isinstance(auth, dict):
        auth = {}
    oidc = auth.get("oidc") or {}
    if not isinstance(oidc, dict):
        oidc = {}
    rs = oidc.get("resource_server") or {}
    if not isinstance(rs, dict):
        rs = {}

    # Legacy fallback (deprecated): identity_provider.
    raw = runtime_cfg.get("identity_provider") or {}
    if not isinstance(raw, dict):
        raw = {}

    env_enabled = (os.getenv("IDP_AUTH_ENABLED") or "").strip().lower()
    if env_enabled in ("1", "true", "yes", "on"):
        enabled = True
    elif env_enabled in ("0", "false", "no", "off"):
        enabled = False
    else:
        enabled = bool(rs.get("enabled", oidc.get("enabled", raw.get("enabled", True))))

    issuer = str(oidc.get("issuer") or rs.get("issuer") or raw.get("issuer") or "").strip()
    jwks_url = str(rs.get("jwks_url") or raw.get("jwks_url") or "").strip()
    audience = str(rs.get("audience") or raw.get("audience") or "").strip()

    algorithms_raw = rs.get("algorithms") or raw.get("algorithms") or ["RS256"]
    algorithms = tuple(str(x).strip() for x in algorithms_raw if str(x).strip())
    if not algorithms:
        algorithms = ("RS256",)

    required_raw = rs.get("required_claims") or raw.get("required_claims") or ["sub", "exp", "iss", "aud"]
    required_claims = tuple(str(x).strip() for x in required_raw if str(x).strip())

    # If OIDC is enabled, require a complete and strict resource-server config.
    if enabled:
        missing = []
        if not issuer:
            missing.append("auth.oidc.issuer")
        if not jwks_url:
            missing.append("auth.oidc.resource_server.jwks_url")
        if not audience:
            missing.append("auth.oidc.resource_server.audience")
        if missing:
            raise RuntimeError("OIDC resource_server config is incomplete (missing: %s)" % ", ".join(missing))

    return IdpAuthSettings(
        enabled=enabled,
        issuer=issuer,
        jwks_url=jwks_url,
        audience=audience,
        algorithms=algorithms,
        required_claims=required_claims,
    )


_idp_auth_settings = _load_idp_auth_settings(_runtime_cfg)
_idp_jwk_client = None


# ------------------------------------------------------------
# History backend (Redis / mock)
# ------------------------------------------------------------

def _make_history_backend() -> Any:
    use_redis = (os.getenv("APP_USE_REDIS") or "").strip().lower() in ("1", "true", "yes", "y", "on")
    if not use_redis:
        return InMemoryMockRedis()
    return RedisBackend()


_history_backend = _make_history_backend()

from code_query_engine.conversation_history.factory import build_conversation_history_service  # noqa: E402

# ------------------------------------------------------------
# Mock SQL history store (development only)
# ------------------------------------------------------------

_history_sessions: dict[str, dict] = {}
_history_messages: dict[str, list[dict]] = {}


class _ReadOnlyMockSqlHistoryStore(IUserConversationStore):
    def upsert_session_link(self, *, identity_id: str, session_id: str) -> None:
        return

    def insert_turn(self, *, turn: ConversationTurn) -> None:
        return

    def upsert_turn_final(
        self,
        *,
        identity_id: str,
        session_id: str,
        turn_id: str,
        answer_neutral: str,
        answer_translated: str | None,
        answer_translated_is_fallback: bool | None,
        finalized_at_utc: str | None,
        meta: dict[str, Any] | None,
    ) -> None:
        return

    def list_recent_finalized_turns_by_session(
        self,
        *,
        session_id: str,
        limit: int,
    ) -> list[ConversationTurn]:
        sid = str(session_id or "").strip()
        if not sid:
            return []
        lim = int(limit or 0)
        if lim <= 0:
            lim = 20

        # Messages are keyed per (tenant, user, session) to prevent cross-user collisions.
        # During request handling we can resolve the key precisely; outside request context
        # we fall back to the legacy session_id bucket.
        msgs_src: list[dict] = []
        try:
            from flask import has_request_context  # type: ignore
        except Exception:
            has_request_context = None  # type: ignore
        if has_request_context and has_request_context():
            try:
                tenant_id = _history_tenant_id()
                user_id = _history_user_id()
                k = _history_resolve_session_key(tenant_id=tenant_id, user_id=user_id, session_id=sid)
                if k:
                    msgs_src = _history_messages.get(k) or []
                else:
                    msgs_src = _history_messages.get(_history_key(tenant_id=tenant_id, user_id=user_id, session_id=sid)) or []
            except Exception:
                msgs_src = _history_messages.get(sid) or []
        else:
            msgs_src = _history_messages.get(sid) or []

        msgs = [m for m in msgs_src if not m.get("deletedAt")]
        if not msgs:
            return []
        msgs.sort(key=lambda m: m.get("ts") or 0)
        msgs = msgs[-lim:]

        out: list[ConversationTurn] = []
        for m in msgs:
            ts = int(m.get("ts") or 0)
            created_at = datetime.fromtimestamp(ts / 1000.0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            out.append(
                ConversationTurn(
                    turn_id=str(m.get("messageId") or ""),
                    session_id=sid,
                    request_id="",
                    created_at_utc=created_at,
                    identity_id=None,
                    finalized_at_utc=created_at,
                    question_neutral=str(m.get("q") or ""),
                    answer_neutral=str(m.get("a") or ""),
                    question_translated=None,
                    answer_translated=None,
                    answer_translated_is_fallback=None,
                    metadata={},
                )
            )
        return out


# Durable store is safe to always wire: it reads from the in-memory mock SQL structures.
# When mock SQL is disabled, history endpoints won't persist data anyway, so reads return empty.
_durable_store: IUserConversationStore | None = _ReadOnlyMockSqlHistoryStore()
_conversation_history_service = build_conversation_history_service(
    session_backend=_history_backend,
    durable_store=_durable_store,
)


# ------------------------------------------------------------
# Searchers (Semantic + BM25)
# ------------------------------------------------------------





# ------------------------------------------------------------
# Models / translators
# ------------------------------------------------------------

def _resolve_cfg_path(p: str) -> str:
    v = (p or "").strip()
    if not v:
        return ""
    if os.path.isabs(v):
        return v
    return os.path.join(PROJECT_ROOT, v)

_env_var_pattern = re.compile(r"^\s*\$\{([A-Z0-9_]+)\}\s*$")

def _resolve_env_var(raw: str) -> str:
    if not raw:
        return ""
    m = _env_var_pattern.match(raw)
    if not m:
        return raw
    return (os.getenv(m.group(1)) or "").strip()


_server_llm_enabled = bool(_runtime_cfg.get("serverLLM"))
_local_model_enabled = bool(_runtime_cfg.get("enable_model_path_analysis", True))


def _load_llm_servers() -> tuple[dict[str, "ServerLLMConfig"], str, list[str]]:
    path = os.path.join(PROJECT_ROOT, "ServersLLM.json")
    if not os.path.isfile(path):
        raise ValueError(f"ServersLLM.json not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
    servers_raw = data.get("servers") or []
    if not isinstance(servers_raw, list) or not servers_raw:
        raise ValueError("ServersLLM.json: 'servers' must be a non-empty list")
    servers: dict[str, ServerLLMConfig] = {}
    ordered_names: list[str] = []
    default_candidates: list[str] = []
    for item in servers_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        base_url = str(item.get("base_url") or "").strip()
        if not name or not base_url:
            continue
        ordered_names.append(name)
        if bool(item.get("default")):
            default_candidates.append(name)
        throttling_raw = item.get("throttling")
        throttling_enabled = False
        throttling_cfg = None
        if isinstance(throttling_raw, bool):
            throttling_enabled = throttling_raw
            throttling_cfg = ThrottleConfig()
        elif isinstance(throttling_raw, dict):
            throttling_enabled = bool(throttling_raw.get("enabled", False))
            retry_on_status = throttling_raw.get("retry_on_status")
            if isinstance(retry_on_status, list):
                retry_on_status = tuple(int(x) for x in retry_on_status)
            else:
                retry_on_status = None
            throttling_cfg = ThrottleConfig(
                max_concurrency=int(throttling_raw.get("max_concurrency", 1)),
                max_retries=int(throttling_raw.get("max_retries", 8)),
                base_backoff_seconds=float(throttling_raw.get("base_backoff_seconds", 1.0)),
                max_backoff_seconds=float(throttling_raw.get("max_backoff_seconds", 30.0)),
                jitter_seconds=float(throttling_raw.get("jitter_seconds", 0.25)),
                retry_on_status=retry_on_status or ThrottleConfig().retry_on_status,
            )

        allowed_doc_level = item.get("allowed_doc_level")
        if allowed_doc_level is not None:
            try:
                allowed_doc_level = int(allowed_doc_level)
            except Exception:
                allowed_doc_level = None
        allowed_acl_labels = item.get("allowed_acl_labels")
        if not isinstance(allowed_acl_labels, list):
            allowed_acl_labels = []
        allowed_classification_labels = item.get("allowed_classification_labels")
        if not isinstance(allowed_classification_labels, list):
            allowed_classification_labels = []

        servers[name] = ServerLLMConfig(
            name=name,
            base_url=base_url,
            api_key=_resolve_env_var(str(item.get("api_key") or "").strip()),
            timeout_seconds=int(item.get("timeout_seconds") or 120),
            mode=str(item.get("mode") or "openai").strip(),
            model=str(item.get("model") or "").strip(),
            completions_path=str(item.get("completions_path") or "/v1/completions").strip(),
            chat_completions_path=str(item.get("chat_completions_path") or "/v1/chat/completions").strip(),
            throttling_enabled=throttling_enabled,
            throttling=throttling_cfg,
            allowed_doc_level=allowed_doc_level,
            allowed_acl_labels=tuple(str(x) for x in allowed_acl_labels if str(x).strip()),
            allowed_classification_labels=tuple(str(x) for x in allowed_classification_labels if str(x).strip()),
            is_trusted_server=bool(item.get("is_trusted_server", False)),
            is_trusted_for_all_acl=bool(item.get("is_trusted_for_all_acl", False)),
        )
    if not servers:
        raise ValueError("ServersLLM.json: no valid servers found")
    if not default_candidates:
        raise ValueError("ServersLLM.json: no server with default:true")
    if len(default_candidates) > 1:
        msg = (
            "ServersLLM.json: multiple servers with default:true; "
            f"using first: {default_candidates[0]} (candidates: {default_candidates})"
        )
        py_logger.warning(msg)
    return servers, default_candidates[0], ordered_names

_model = None
_local_model = None
_server_client = None

if _local_model_enabled:
    # NOTE: your Model wrapper is outside the uploaded set; keep as-is in repo.
    from .model import Model  # noqa: E402

    _local_model = Model(
        _resolve_cfg_path(str(_runtime_cfg.get("model_path_analysis") or "")),
        default_max_tokens=int(_runtime_cfg.get("model_max_tokens", 1500) or 1500),
        n_ctx=int(_runtime_cfg.get("model_context_window", 4096) or 4096),
        use_gpu=bool(_runtime_cfg.get("use_gpu", True)),
        n_gpu_layers=_runtime_cfg.get("model_n_gpu_layers", _runtime_cfg.get("n_gpu_layers")),
    )
else:
    py_logger.warning("local model disabled: enable_model_path_analysis=false")

if _server_llm_enabled:
    from .llm_server_client import (  # noqa: E402
        ServerLLMClient,
        ServerLLMConfig,
        ThrottleConfig,
        HybridLLMClient,
    )

    try:
        servers, default_name, ordered_names = _load_llm_servers()
        _server_client = ServerLLMClient(
            servers=servers,
            default_name=default_name,
            ordered_names=ordered_names,
        )
    except Exception as e:
        py_logger.error("serverLLM=true but failed to load ServersLLM.json: %s", e)
        raise

if _server_client is not None and _local_model is not None:
    _model = HybridLLMClient(local_model=_local_model, server_client=_server_client)
    py_logger.info("LLM routing: hybrid (server-first, local fallback).")
elif _server_client is not None:
    _model = _server_client
    py_logger.info("LLM routing: server-only.")
elif _local_model is not None:
    _model = _local_model
    py_logger.info("LLM routing: local-only.")
else:
    raise RuntimeError("No LLM configured: both serverLLM and enable_model_path_analysis are disabled.")

try:
    _llm = getattr(_model, "llm", None) if _model is not None else None
    _n_ctx = None
    if _llm is not None:
        v = getattr(_llm, "n_ctx", None)
        _n_ctx = v() if callable(v) else v
    py_logger.info(
        "Model defaults loaded from config.json: model_max_tokens=%s (output), model_context_window=%s (context window), llm_n_ctx=%s",
        getattr(_model, "default_max_tokens", None),
        getattr(_model, "n_ctx", None),
        _n_ctx,
    )
except Exception:
    py_logger.exception("soft-failure: failed to log model defaults; continuing")
_markdown_translator = MarkdownTranslator(_resolve_cfg_path(str(_runtime_cfg.get("model_translation_en_pl") or "")))
_translator_pl_en = Translator(_resolve_cfg_path(str(_runtime_cfg.get("model_translation_pl_en") or "")))

_interaction_logger = InteractionLogger(cfg=_logging_cfg)

from code_query_engine.pipeline.token_counter import LlamaCppTokenCounter, ApproxTokenCounter, require_token_counter

token_counter = None

try:
    llm = getattr(_model, "llm", None)
    if llm is None:
        token_counter = ApproxTokenCounter()
        py_logger.warning("degraded-mode: model has no .llm; using approximate token counter")
    else:
        token_counter = LlamaCppTokenCounter(llama=llm)
except Exception as e:
    py_logger.exception("soft-failure: token counter init failed; continuing without token counter")
    token_counter = None

_weaviate_client = None
_retrieval_backend = None
_graph_provider = None

_skip_weaviate_init = (os.getenv("WEAVIATE_SKIP_INIT") or "").strip().lower() in ("1", "true", "yes", "on")
_skip_weaviate_init = _skip_weaviate_init or bool(os.getenv("PYTEST_CURRENT_TEST"))
_strict_security_validation = not bool(_development_enabled)

if _skip_weaviate_init:
    py_logger.warning("degraded-mode: skipping Weaviate init (test mode)")
    _validate_security_consistency(
        runtime_cfg=_runtime_cfg,
        client=None,
        strict=_strict_security_validation,
    )
else:
    try:
        _weaviate_settings = get_weaviate_settings()
        _weaviate_client = create_weaviate_client(_weaviate_settings)
    except Exception:
        py_logger.exception("fatal: cannot initialize Weaviate client (vector_db/weaviate_client.py)")
        raise

    _validate_security_consistency(
        runtime_cfg=_runtime_cfg,
        client=_weaviate_client,
        strict=_strict_security_validation,
    )

    _embed_model_path = _resolve_cfg_path(str(_runtime_cfg.get("model_path_embd") or ""))
    _security_cfg = _runtime_cfg.get("permissions") if isinstance(_runtime_cfg.get("permissions"), dict) else {}
    _sec_model = _security_cfg.get("security_model") if isinstance(_security_cfg.get("security_model"), dict) else {}
    _labels_cfg = _sec_model.get("labels_universe_subset") if isinstance(_sec_model.get("labels_universe_subset"), dict) else {}
    _classification_universe_raw = _labels_cfg.get("classification_labels_universe")
    if isinstance(_classification_universe_raw, list):
        _classification_universe = [str(s).strip() for s in _classification_universe_raw if str(s).strip()]
    elif isinstance(_classification_universe_raw, str):
        _classification_universe = [s.strip() for s in _classification_universe_raw.split(",") if s.strip()]
    else:
        _classification_universe = []
    _doc_level_field = "doc_level"
    _doc_labels_field = "classification_labels"
    _kind = str(_sec_model.get("kind") or "").strip()
    _clearance_cfg = _sec_model.get("clearance_level") if isinstance(_sec_model.get("clearance_level"), dict) else {}
    _labels_or_cls_cfg = (
        _sec_model.get("labels_universe_subset")
        if isinstance(_sec_model.get("labels_universe_subset"), dict)
        else (
            _sec_model.get("classification_labels")
            if isinstance(_sec_model.get("classification_labels"), dict)
            else {}
        )
    )
    if _kind == "clearance_level":
        _doc_level_field = str(_clearance_cfg.get("doc_level_field") or _doc_level_field)
    if _kind in ("labels_universe_subset", "classification_labels"):
        _doc_labels_field = str(_labels_or_cls_cfg.get("doc_labels_field") or _doc_labels_field)
    _retrieval_backend = WeaviateRetrievalBackend(
        client=_weaviate_client,
        query_embed_model=_embed_model_path,
        classification_labels_property=_doc_labels_field,
        doc_level_property=_doc_level_field,
        classification_labels_universe=_classification_universe,
        security_config=_security_cfg,
    )
    _graph_provider = WeaviateGraphProvider(
        client=_weaviate_client,
        classification_property=_doc_labels_field,
        doc_level_property=_doc_level_field,
        classification_labels_universe=_classification_universe,
        security_config=_security_cfg,
    )

_templates_store = default_templates_store(PROJECT_ROOT)
_pipeline_access = PipelineAccessService()
_snapshot_registry = SnapshotRegistry(_weaviate_client) if _weaviate_client else None
_pipeline_settings_by_name = {}
try:
    from code_query_engine.pipeline.loader import PipelineLoader
    from code_query_engine.pipeline.validator import PipelineValidator
    _loader = PipelineLoader(pipelines_root=os.path.join(PROJECT_ROOT, "pipelines"))
    _validator = PipelineValidator()
    for name in _loader.list_pipeline_names():
        try:
            pipe = _loader.load_by_name(name)
            _validator.validate(pipe)
            _pipeline_settings_by_name[name] = dict(pipe.settings or {})
        except Exception:
            py_logger.exception("soft-failure: failed to load pipeline settings for %s", name)
except Exception:
    py_logger.exception("soft-failure: failed to build pipeline settings registry")

_pipeline_snapshot_store = PipelineSnapshotStore(_pipeline_settings_by_name)
_snapshot_policy = str(_runtime_cfg.get("snapshot_policy") or "single").strip() or "single"
_app_config_service = AppConfigService(
    templates_store=_templates_store,
    access_provider=_user_access_provider,
    pipeline_access=_pipeline_access,
    snapshot_registry=_snapshot_registry,
    pipeline_snapshot_store=_pipeline_snapshot_store,
    snapshot_policy=_snapshot_policy,
)

_runner = DynamicPipelineRunner(
    pipelines_root=os.path.join(PROJECT_ROOT, "pipelines"),
    model=_model,
    retrieval_backend=_retrieval_backend,   
    markdown_translator=_markdown_translator,
    translator_pl_en=_translator_pl_en,
    token_counter=token_counter,
    logger=_interaction_logger,
    graph_provider=_graph_provider,
    conversation_history_service=_conversation_history_service,
    limits_policy=(
        (os.getenv("PIPELINE_LIMITS_POLICY") or "").strip().lower()
        or ("fail_fast" if _development_enabled else "auto_clamp")
    ),
)


# ------------------------------------------------------------
# Flask app
# ------------------------------------------------------------

app = Flask(__name__)
CORS(app, origins=ALLOWED_ORIGINS)

def _history_unavailable():
    return jsonify({
        "error": "history_persistence_unavailable",
        "message": "History persistence is not available. Enable development mode and mockSqlServer in config.",
    }), 503


def _history_user_id() -> str:
    # Preferred: authenticated identity (fake user or IdP claims).
    try:
        fake_uid = getattr(g, "fake_user_id", None)
        if fake_uid:
            v = _safe_id_component(fake_uid)
            return v or "anon"
    except Exception:
        pass

    try:
        claims = getattr(g, "idp_claims", None)
        if isinstance(claims, dict) and claims:
            # Prefer human/stable identifiers when available.
            for key in ("preferred_username", "sub", "email"):
                v = _safe_id_component(claims.get(key))
                if v:
                    return v
    except Exception:
        pass

    # Backward-compatible dev token parsing (when routes are called without auth helpers).
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer dev-user:"):
        v = _safe_id_component(auth.split(":", 1)[1])
        return v or "anon"

    # Legacy fallback for older internal callers/tests.
    v = _safe_id_component(request.headers.get("X-User-ID") or "")
    return v or "anon"


def _history_tenant_id() -> str:
    return (request.headers.get("X-Tenant-ID") or "tenant-default").strip() or "tenant-default"


def _history_key(*, tenant_id: str, user_id: str, session_id: str) -> str:
    # Composite key prevents collisions when different users reuse the same sessionId
    # (the UI stores sessionId in localStorage).
    t = (tenant_id or "").strip() or "tenant-default"
    u = (user_id or "").strip() or "anon"
    s = (session_id or "").strip()
    return f"{t}::{u}::{s}"


def _history_resolve_session_key(*, tenant_id: str, user_id: str, session_id: str) -> str | None:
    """
    Resolve in-memory key for a (tenant, user, sessionId).

    Backward-compatible with the older in-memory layout where the dicts were keyed by sessionId only.
    If a legacy entry is found and matches the same tenant/user, it is migrated.
    """
    sid = (session_id or "").strip()
    if not sid:
        return None
    internal = _history_key(tenant_id=tenant_id, user_id=user_id, session_id=sid)
    if internal in _history_sessions:
        # If a legacy entry also exists for the same sessionId (old dict layout keyed by sessionId only),
        # merge messages and remove the legacy bucket. This prevents "empty history" after migrations.
        legacy_session = _history_sessions.get(sid)
        if legacy_session and str(legacy_session.get("tenantId") or "") == str(tenant_id or "") and str(legacy_session.get("userId") or "") == str(user_id or ""):
            internal_msgs = list(_history_messages.get(internal) or [])
            legacy_msgs = list(_history_messages.get(sid) or [])
            if legacy_msgs:
                if internal_msgs:
                    seen_ids = {str(m.get("messageId") or "") for m in internal_msgs if isinstance(m, dict)}
                    for m in legacy_msgs:
                        if not isinstance(m, dict):
                            continue
                        mid = str(m.get("messageId") or "")
                        if mid and mid in seen_ids:
                            continue
                        internal_msgs.append(m)
                    internal_msgs.sort(key=lambda m: int((m or {}).get("ts") or 0))
                else:
                    internal_msgs = legacy_msgs
                _history_messages[internal] = internal_msgs
                _history_messages.pop(sid, None)
                try:
                    s = _history_sessions.get(internal) or {}
                    s["messageCount"] = len([m for m in internal_msgs if isinstance(m, dict) and not m.get("deletedAt")])
                    s["updatedAt"] = max(int(s.get("updatedAt") or 0), int(legacy_session.get("updatedAt") or 0), int((internal_msgs[-1] or {}).get("ts") or 0))
                    if s.get("createdAt") is None:
                        s["createdAt"] = legacy_session.get("createdAt")
                except Exception:
                    pass
            _history_sessions.pop(sid, None)
        return internal

    # Pipeline session ids are namespaced per user: "u_<userId>__<clientSessionId>".
    # Chat-history endpoints keep the client-visible sessionId, so here we map pipeline session ids
    # back to the client session id when possible.
    if "__" in sid and sid.startswith("u_"):
        prefix, client_sid = sid.split("__", 1)
        expected_prefix = f"u_{(user_id or '').strip()}"
        if prefix == expected_prefix and client_sid:
            # Try resolving the underlying client session id.
            internal2 = _history_key(tenant_id=tenant_id, user_id=user_id, session_id=client_sid)
            if internal2 in _history_sessions:
                return internal2
            legacy2 = _history_sessions.get(client_sid)
            if legacy2 and str(legacy2.get("tenantId") or "") == str(tenant_id or "") and str(legacy2.get("userId") or "") == str(user_id or ""):
                _history_sessions[internal2] = legacy2
                _history_messages[internal2] = _history_messages.get(client_sid) or []
                _history_sessions.pop(client_sid, None)
                _history_messages.pop(client_sid, None)
                return internal2

    legacy = sid
    legacy_session = _history_sessions.get(legacy)
    if not legacy_session:
        return None
    if str(legacy_session.get("tenantId") or "") != str(tenant_id or ""):
        return None
    if str(legacy_session.get("userId") or "") != str(user_id or ""):
        return None

    # Migrate legacy bucket into the internal key.
    if internal not in _history_sessions:
        _history_sessions[internal] = legacy_session
        legacy_msgs = _history_messages.get(legacy) or []
        _history_messages[internal] = legacy_msgs
    _history_sessions.pop(legacy, None)
    _history_messages.pop(legacy, None)
    return internal


def _history_now_ms() -> int:
    return int(time.time() * 1000)


def _history_is_anon(user_id: str) -> bool:
    return (user_id or "").strip() == "anon"


def _history_list_sessions(*, tenant_id: str, user_id: str, limit: int, cursor: str | None, q: str | None) -> dict:
    _history_prune()
    # Migrate any legacy (sessionId-keyed) sessions for this tenant/user to prevent duplicates and message loss.
    try:
        candidate_sids = {
            str(s.get("sessionId") or "").strip()
            for s in _history_sessions.values()
            if s.get("tenantId") == tenant_id and s.get("userId") == user_id and not s.get("deletedAt") and not s.get("softDeletedAt")
        }
        for sid in list(candidate_sids):
            if sid:
                _history_resolve_session_key(tenant_id=tenant_id, user_id=user_id, session_id=sid)
    except Exception:
        pass

    sessions = [
        s for s in _history_sessions.values()
        if s.get("tenantId") == tenant_id and s.get("userId") == user_id and not s.get("deletedAt") and not s.get("softDeletedAt")
    ]
    sessions.sort(key=lambda s: s.get("updatedAt") or 0, reverse=True)

    if q:
        qn = q.lower()
        sessions = [s for s in sessions if (s.get("title") or "").lower().find(qn) >= 0]

    start_idx = 0
    if cursor:
        for i, s in enumerate(sessions):
            if str(s.get("updatedAt")) == str(cursor):
                start_idx = i + 1
                break

    items = sessions[start_idx:start_idx + limit]
    next_cursor = str(items[-1].get("updatedAt")) if len(items) == limit else None
    return {"items": items, "next_cursor": next_cursor}


def _history_prune() -> None:
    if _mock_sql_ttl_ms <= 0:
        return
    cutoff = _history_now_ms() - _mock_sql_ttl_ms
    expired = [k for k, s in _history_sessions.items() if (s.get("updatedAt") or 0) < cutoff]
    for k in expired:
        _history_sessions.pop(k, None)
        _history_messages.pop(k, None)


def _resolve_snapshot_id_from_set(*, snapshot_set_id: str, repository: str | None) -> str:
    if not _snapshot_registry:
        return ""
    return _snapshot_registry.resolve_snapshot_id(snapshot_set_id=snapshot_set_id, repository=repository)


def _log_security_abuse(
    *,
    reason: str,
    status_code: int,
    user_id: Optional[str] = None,
    pipeline: str = "",
    snapshot_set_id: str = "",
    snapshot_id: str = "",
) -> None:
    py_logger.warning(
        "[security_abuse] reason=%s status=%s path=%s remote=%s session_id=%s user_id=%s pipeline=%s snapshot_set_id=%s snapshot_id=%s",
        reason,
        status_code,
        request.path,
        request.remote_addr,
        request.headers.get("X-Session-ID") or "",
        user_id or "",
        pipeline,
        snapshot_set_id,
        snapshot_id,
    )


def _is_valid_api_bearer(auth_header: str) -> bool:
    if not API_TOKEN:
        return False
    return auth_header == f"Bearer {API_TOKEN}"


def _extract_bearer_token(auth_header: str) -> str:
    if not auth_header:
        return ""
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return ""
    return auth_header[len(prefix):].strip()


def _extract_dev_user_id(auth_header: str) -> str:
    token = _extract_bearer_token(auth_header)
    if not token.startswith("dev-user:"):
        return ""
    return token[len("dev-user:") :].strip()

def _decode_jwt_payload_unverified(token: str) -> dict[str, Any]:
    # Debug-only helper: decode JWT payload without verifying signature.
    # Never log the token itself.
    try:
        parts = (token or "").split(".")
        if len(parts) < 2:
            return {}
        b64 = parts[1].replace("-", "+").replace("_", "/")
        b64 += "=" * (-len(b64) % 4)
        raw = base64.b64decode(b64.encode("ascii"))
        obj = json.loads(raw.decode("utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _idp_auth_is_active() -> bool:
    s = _idp_auth_settings
    return bool(s.enabled and s.issuer and s.jwks_url and s.audience)


def _get_idp_jwk_client():
    global _idp_jwk_client
    if _idp_jwk_client is None:
        if _PyJWKClient is None:
            raise RuntimeError("PyJWT with JWK support is not installed.")
        _idp_jwk_client = _PyJWKClient(_idp_auth_settings.jwks_url)
    return _idp_jwk_client


def _validate_idp_bearer(auth_header: str):
    token = _extract_bearer_token(auth_header)
    if not token:
        _log_security_abuse(reason="missing_or_invalid_bearer", status_code=401)
        return jsonify({"ok": False, "error": "missing_or_invalid_bearer"}), 401

    if _pyjwt is None:
        return jsonify({"ok": False, "error": "idp auth dependency missing (install pyjwt[crypto])"}), 503

    try:
        jwk_client = _get_idp_jwk_client()
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        claims = _pyjwt.decode(
            token,
            signing_key.key,
            algorithms=list(_idp_auth_settings.algorithms),
            audience=_idp_auth_settings.audience,
            issuer=_idp_auth_settings.issuer,
            options={"require": list(_idp_auth_settings.required_claims)},
        )
        g.idp_claims = claims if isinstance(claims, dict) else {}
        return None
    except _JwtExpiredSignatureError:
        _log_security_abuse(reason="expired_token", status_code=401)
        return jsonify({"ok": False, "error": "expired_token"}), 401
    except _JwtInvalidAudienceError:
        _log_security_abuse(reason="invalid_audience", status_code=401)
        return jsonify({"ok": False, "error": "invalid_audience"}), 401
    except _JwtInvalidTokenError as ex:
        _log_security_abuse(reason="invalid_token", status_code=401)
        p = _decode_jwt_payload_unverified(token)
        # Log only non-sensitive routing/validation hints.
        py_logger.warning(
            "idp invalid token: %s iss=%s aud=%s azp=%s typ=%s",
            str(ex),
            str(p.get("iss") or ""),
            str(p.get("aud") or ""),
            str(p.get("azp") or ""),
            str(p.get("typ") or ""),
        )
        return jsonify({"ok": False, "error": "invalid_token"}), 401
    except _JwtPyJwkClientError as ex:
        _log_security_abuse(reason="jwks_unavailable", status_code=503)
        py_logger.warning("idp jwks error: %s", ex)
        return jsonify({"ok": False, "error": "identity provider unavailable"}), 503
    except Exception:
        _log_security_abuse(reason="idp_validation_error", status_code=503)
        py_logger.exception("idp token validation failed unexpectedly")
        return jsonify({"ok": False, "error": "identity provider unavailable"}), 503


def _require_bearer_strict(auth_header: str):
    if _idp_auth_is_active():
        return _validate_idp_bearer(auth_header)

    if not API_TOKEN:
        _log_security_abuse(reason="prod_auth_not_configured", status_code=503)
        return jsonify({"ok": False, "error": "server auth is not configured"}), 503
    if not _is_valid_api_bearer(auth_header):
        _log_security_abuse(reason="invalid_api_token", status_code=401)
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    g.idp_claims = {}
    return None


_require_prod_bearer = _require_bearer_strict  # backward-compatible alias


def _require_bearer_if_needed(auth_header: str):
    if _auth_required:
        return _require_bearer_strict(auth_header)
    # DEV_ALLOW_NO_AUTH mode still requires a fake login token.
    dev_user_id = _extract_dev_user_id(auth_header)
    if not dev_user_id:
        _log_security_abuse(reason="login_required", status_code=401)
        return jsonify({"ok": False, "error": "login_required"}), 401
    if dev_user_id not in (_fake_users_by_id or {}):
        _log_security_abuse(reason="unknown_fake_user", status_code=401)
        return jsonify({"ok": False, "error": "login_required"}), 401
    g.fake_user_id = dev_user_id
    g.idp_claims = dict((_fake_users_by_id.get(dev_user_id) or {}).get("claims") or {})
    return None


def _build_public_bootstrap_config() -> dict[str, Any]:
    fake_login_required = bool(_dev_allow_no_auth and _app_profile != "prod")
    fake_users: list[dict[str, str]] = []
    if fake_login_required:
        fake_users = [{"id": u["id"], "userName": u["userName"]} for u in (_fake_users_by_id or {}).values()]
        fake_users.sort(key=lambda x: x.get("userName") or x.get("id") or "")

    # New pattern: auth.oidc.client (SPA login: Authorization Code + PKCE).
    auth = _runtime_cfg.get("auth") or {}
    if not isinstance(auth, dict):
        auth = {}
    oidc = auth.get("oidc") or {}
    if not isinstance(oidc, dict):
        oidc = {}
    client = oidc.get("client") or {}
    if not isinstance(client, dict):
        client = {}

    # Legacy fallback (deprecated): oidc at top-level.
    raw_oidc = _runtime_cfg.get("oidc") or {}
    if not isinstance(raw_oidc, dict):
        raw_oidc = {}
    if (not oidc) and raw_oidc:
        oidc = raw_oidc
        client = raw_oidc

    scopes_raw = client.get("scopes") or ["openid", "profile", "email"]
    scopes = [str(x).strip() for x in (scopes_raw if isinstance(scopes_raw, list) else []) if str(x).strip()]
    if not scopes:
        scopes = ["openid", "profile", "email"]

    extra_auth_params = client.get("extra_auth_params") or {}
    if not isinstance(extra_auth_params, dict):
        extra_auth_params = {}
    extra_token_params = client.get("extra_token_params") or {}
    if not isinstance(extra_token_params, dict):
        extra_token_params = {}

    oidc_public = {
        "enabled": bool(oidc.get("enabled", False)),
        "issuer": str(oidc.get("issuer") or "").strip(),
        "client": {
            "client_id": str(client.get("client_id") or "").strip(),
            "scopes": scopes,
            "redirect_path": str(client.get("redirect_path") or "/").strip() or "/",
            "post_logout_redirect_path": str(client.get("post_logout_redirect_path") or "/").strip() or "/",
            "authorization_endpoint": str(client.get("authorization_endpoint") or "").strip(),
            "token_endpoint": str(client.get("token_endpoint") or "").strip(),
            "end_session_endpoint": str(client.get("end_session_endpoint") or "").strip(),
            "extra_auth_params": {str(k): str(v) for k, v in extra_auth_params.items() if str(k).strip() and v is not None},
            "extra_token_params": {str(k): str(v) for k, v in extra_token_params.items() if str(k).strip() and v is not None},
        },
    }

    return {
        "fake_login_required": bool(fake_login_required),
        "fake_users": fake_users,
        "app_profile": _app_profile,
        "auth": {"oidc": oidc_public},
    }


def _render_ui_html() -> Response:
    html = Path(FRONTEND_HTML_PATH).read_text(encoding="utf-8")
    bootstrap_payload = _build_public_bootstrap_config()
    bootstrap_script = (
        "<script>"
        f"window.__RAG_PUBLIC_CONFIG__ = {json.dumps(bootstrap_payload, ensure_ascii=False)};"
        "</script>"
    )
    if "</head>" in html:
        html = html.replace("</head>", f"{bootstrap_script}\n</head>", 1)
    return Response(html, mimetype="text/html")


register_work_callback_routes(
    app,
    require_bearer_fn=_require_bearer_if_needed,
)
register_cancel_routes(
    app,
    require_bearer_fn=_require_bearer_if_needed,
)


@app.route("/health", methods=["GET"])
def health():
    # Keep backward-compatible keys for existing tests/UI:
    # - searcher_ok/searcher_error reflect the semantic searcher (the "default" retriever).
    return jsonify(
        {
            "ok": True,
        }
    )


@app.get("/")
def ui_index():
    if not os.path.isfile(FRONTEND_HTML_PATH):
        return jsonify({"ok": False, "error": "Frontend file not found.", "path": FRONTEND_HTML_PATH}), 404
    return _render_ui_html()


@app.get("/assets/<path:filename>")
def ui_assets(filename: str):
    if not os.path.isdir(FRONTEND_ASSETS_DIR):
        return jsonify({"ok": False, "error": "Assets directory not found.", "path": FRONTEND_ASSETS_DIR}), 404
    return send_from_directory(FRONTEND_ASSETS_DIR, filename)


# ------------------------------------------------------------
# Helpers (limits / fields / session)
# ------------------------------------------------------------

def _ensure_limits(payload: dict) -> tuple[bool, str]:
    q = str(payload.get("query") or payload.get("question") or payload.get("text") or "")
    if len(q) > MAX_QUERY_LEN:
        return False, f"query too long (>{MAX_QUERY_LEN})"

    for k in (
        "repository",
        "branch",
        "branchA",
        "branchB",
        "branches",  # NEW contract: list[0..2]
        "snapshots",  # NEW contract: list[0..2]
        "snapshot_id",
        "snapshot_id_b",
        "snapshot_set_id",
        "source_system_id",
        "pipelineName",
        "templateId",
        "language",
        "consultant",
        "session_id",
        "user_id",
    ):
        if k in ("branches", "snapshots"):
            raw = payload.get("branches")
            if k == "snapshots":
                raw = payload.get("snapshots")
            if isinstance(raw, list):
                for i, item in enumerate(raw):
                    v = str(item or "")
                    if len(v) > MAX_FIELD_LEN:
                        return False, f"field '{k}[{i}]' too long (>{MAX_FIELD_LEN})"
            else:
                v = str(raw or "")
                if len(v) > MAX_FIELD_LEN:
                    return False, f"field '{k}' too long (>{MAX_FIELD_LEN})"
            continue

        v = str(payload.get(k) or "")
        if len(v) > MAX_FIELD_LEN:
            return False, f"field '{k}' too long (>{MAX_FIELD_LEN})"

    return True, ""


def _valid_session_id(value: Optional[str]) -> str:
    v = (value or "").strip()
    if not v:
        return uuid.uuid4().hex
    v = v[:MAX_FIELD_LEN]
    if not re.match(r"^[a-zA-Z0-9_\-]+$", v):
        return uuid.uuid4().hex
    return v


def _valid_trace_run_id(value: Optional[str]) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    v = v[: (MAX_FIELD_LEN * 4)]
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
        return ""
    return v


def _valid_user_id(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        return None
    v = v[:MAX_FIELD_LEN]
    if not re.match(r"^[a-zA-Z0-9_\-]+$", v):
        return None
    return v


def _safe_id_component(value: object, *, max_len: int = 64) -> str:
    """
    Convert an arbitrary identifier into a stable, safe component used in keys.
    Keeps only [a-zA-Z0-9_-], collapses everything else to '_'.
    """
    s = str(value or "").strip()
    if not s:
        return ""
    out = []
    for ch in s:
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        else:
            out.append("_")
    safe = "".join(out).strip("_")
    safe = safe[: int(max_len or 64)]
    return safe


def _migrate_conversation_kv_for_namespaced_session(
    *,
    backend: Any,
    src_session_id: str,
    dst_session_id: str,
    user_id: Optional[str],
) -> None:
    """
    Best-effort migration for the session-scoped KV history used by:
    - HistoryManager (keys: "<sid>" and "<sid>:meta")
    - ConversationHistoryService session store (key: "conv_hist:<sid>")

    We only migrate when we can prove the source belongs to the same user_id,
    to avoid cross-user leaks from older deployments that keyed by session_id only.
    """
    try:
        src = str(src_session_id or "").strip()
        dst = str(dst_session_id or "").strip()
        uid = str(user_id or "").strip()
        if not src or not dst or src == dst or not uid:
            return
        if not hasattr(backend, "get") or not hasattr(backend, "set"):
            return
    except Exception:
        return

    # 1) Migrate HistoryManager history only when meta.user_id matches.
    try:
        meta_src_key = f"{src}:meta"
        meta_dst_key = f"{dst}:meta"
        meta_src_raw = backend.get(meta_src_key)
        if meta_src_raw and not backend.get(meta_dst_key):
            try:
                meta_obj = json.loads(meta_src_raw)
            except Exception:
                meta_obj = None
            meta_uid = ""
            if isinstance(meta_obj, dict):
                meta_uid = str(meta_obj.get("user_id") or "").strip()
            if meta_uid == uid:
                backend.set(meta_dst_key, meta_src_raw)
                hist_src_raw = backend.get(src)
                if hist_src_raw and not backend.get(dst):
                    backend.set(dst, hist_src_raw)
    except Exception:
        pass

    # 2) Migrate session conversation turns (conv_hist) filtered by identity_id.
    try:
        conv_src_key = f"conv_hist:{src}"
        conv_dst_key = f"conv_hist:{dst}"
        if backend.get(conv_dst_key):
            return
        conv_src_raw = backend.get(conv_src_key)
        if not conv_src_raw:
            return
        try:
            obj = json.loads(conv_src_raw)
        except Exception:
            return
        if not isinstance(obj, dict):
            return
        turns = obj.get("turns")
        if not isinstance(turns, list) or not turns:
            return
        filtered: list[dict[str, Any]] = []
        for t in turns:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("identity_id") or "").strip()
            if tid and tid == uid:
                filtered.append(t)
        if not filtered:
            return
        payload = {"by_request": {}, "turns": filtered}
        backend.set(conv_dst_key, json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def _get_str_field(payload: Dict[str, Any], key: str, default: str = "") -> str:
    v = payload.get(key, default)
    if v is None:
        return default
    if not isinstance(v, str):
        v = str(v)
    v = v.strip()
    if len(v) > MAX_QUERY_LEN:
        v = v[:MAX_QUERY_LEN]
    return v


def _get_bool_field(payload: Dict[str, Any], key: str, default: bool = False) -> bool:
    v = payload.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return default


def _normalize_runner_result(result: Any) -> Dict[str, Any]:
    """Support both dict and tuple outputs from different runner versions."""
    if isinstance(result, dict):
        return result
    if isinstance(result, (list, tuple)):
        final_answer = result[0] if len(result) > 0 else ""
        query_type = result[1] if len(result) > 1 else None
        steps_used = result[2] if len(result) > 2 else None
        model_input_en = result[3] if len(result) > 3 else ""
        out = {
            "results": final_answer,
            "query_type": query_type,
            "steps_used": steps_used,
            "translated": model_input_en,
        }
        if len(result) > 4 and result[4]:
            out["pipeline_run_id"] = result[4]
        return out
    return {"results": "", "translated": ""}


def _enforce_custom_access_policies(
    *,
    access_ctx: UserAccessContext,
    pipeline_name: str,
    consultant_id: str,
    snapshot_set_id: str,
    snapshot_id: str,
    snapshot_id_b: str,
    repository: str,
):
    # 1) Pipeline authorization
    if access_ctx.allowed_pipelines:
        effective_pipeline = pipeline_name or consultant_id
        if effective_pipeline not in access_ctx.allowed_pipelines:
            _log_security_abuse(
                reason="pipeline_not_allowed",
                status_code=403,
                user_id=access_ctx.user_id,
                pipeline=effective_pipeline,
                snapshot_set_id=snapshot_set_id,
                snapshot_id=snapshot_id,
            )
            return jsonify({"ok": False, "error": "pipeline not allowed for this user"}), 403

    # 2) Snapshot membership in snapshot set
    if snapshot_set_id and (snapshot_id or snapshot_id_b):
        if not _snapshot_registry:
            return jsonify({"ok": False, "error": "snapshot validation unavailable"}), 503
        try:
            allowed = _snapshot_registry.list_snapshots(
                snapshot_set_id=snapshot_set_id,
                repository=repository or None,
            )
        except Exception as ex:
            return jsonify({"ok": False, "error": str(ex)}), 400

        allowed_ids = {s.id for s in allowed}
        if snapshot_id and snapshot_id not in allowed_ids:
            _log_security_abuse(
                reason="snapshot_not_in_snapshot_set",
                status_code=400,
                user_id=access_ctx.user_id,
                pipeline=(pipeline_name or consultant_id),
                snapshot_set_id=snapshot_set_id,
                snapshot_id=snapshot_id,
            )
            return jsonify({"ok": False, "error": "snapshot_id is not allowed in snapshot_set_id"}), 400
        if snapshot_id_b and snapshot_id_b not in allowed_ids:
            _log_security_abuse(
                reason="snapshot_b_not_in_snapshot_set",
                status_code=400,
                user_id=access_ctx.user_id,
                pipeline=(pipeline_name or consultant_id),
                snapshot_set_id=snapshot_set_id,
                snapshot_id=snapshot_id_b,
            )
            return jsonify({"ok": False, "error": "snapshot_id_b is not allowed in snapshot_set_id"}), 400

    return None


# ------------------------------------------------------------
# UI templates + branches (Option A)
# ------------------------------------------------------------

@app.route("/app-config", methods=["GET"])
def app_config():
    return _handle_app_config_request()


def _handle_app_config_request():
    auth_header = (request.headers.get("Authorization") or "").strip()
    auth_error = _require_bearer_if_needed(auth_header)
    if auth_error is not None:
        return auth_error

    session_id = _valid_session_id(request.headers.get("X-Session-ID") or "app-config")
    cfg = dict(_runtime_cfg)
    cfg["project_root"] = PROJECT_ROOT
    cfg["repositories_root"] = REPOSITORIES_ROOT
    claims = getattr(g, "idp_claims", {}) or {}
    app_cfg = _app_config_service.build_app_config(
        runtime_cfg=cfg,
        session_id=session_id,
        auth_header=auth_header,
        claims=claims,
    )
    try:
        consultants = app_cfg.get("consultants") or []
        if not consultants:
            access_ctx = _user_access_provider.resolve(
                user_id=None,
                token=auth_header,
                session_id=session_id,
                claims=claims if isinstance(claims, dict) else {},
            )
            py_logger.warning(
                "app-config empty consultants: user_id=%s groups=%s allowed_pipelines=%s claims_keys=%s",
                str(getattr(access_ctx, "user_id", "") or ""),
                list(getattr(access_ctx, "group_ids", []) or []),
                list(getattr(access_ctx, "allowed_pipelines", []) or []),
                sorted([str(k) for k in (claims or {}).keys()]) if isinstance(claims, dict) else [],
            )
    except Exception:
        pass
    return jsonify(app_cfg)


# ------------------------------------------------------------
# Query endpoint (contract: query/consultant/pipelineName/branches[0..2])
# Backward-compat: still accept legacy branchA/branchB.
# ------------------------------------------------------------

def _handle_query_request():
    auth_header = (request.headers.get("Authorization") or "").strip()
    auth_error = _require_bearer_if_needed(auth_header)
    if auth_error is not None:
        return auth_error

    payload = request.get_json(silent=True) or {}
    ok, err = _ensure_limits(payload)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    original_query = _get_str_field(payload, "query", _get_str_field(payload, "question", _get_str_field(payload, "text", "")))
    if not original_query:
        return jsonify({"ok": False, "error": "missing 'query'"}), 400

    consultant_id = _get_str_field(payload, "consultant", "")
    if not consultant_id:
        return jsonify({"ok": False, "error": "missing 'consultant'"}), 400

    translate_chat = _get_bool_field(payload, "translateChat", False)
    enable_trace = _get_bool_field(payload, "enableTrace", _get_bool_field(payload, "enable_trace", False))
    client_trace_run_id = _valid_trace_run_id(
        _get_str_field(payload, "pipeline_run_id", _get_str_field(payload, "run_id", ""))
    )

    # NEW contract: "branches": [] | ["A"] | ["A","B"]
    # Backward-compat: accept legacy branchA/branchB/branch.
    branches_raw = payload.get("branches")
    branch_a = ""
    branch_b = ""

    if isinstance(branches_raw, list):
        cleaned: List[str] = []
        for item in branches_raw:
            s = str(item or "").strip()
            if s:
                cleaned.append(s)

        if len(cleaned) > 2:
            return jsonify({"ok": False, "error": "too many branches (max 2)"}), 400

        if len(cleaned) == 2 and cleaned[0] == cleaned[1]:
            return jsonify({"ok": False, "error": "compare requires two different branches"}), 400

        if len(cleaned) >= 1:
            branch_a = cleaned[0]
        if len(cleaned) == 2:
            branch_b = cleaned[1]
    else:
        branch_a = _get_str_field(payload, "branchA", _get_str_field(payload, "branch", ""))
        branch_b = _get_str_field(payload, "branchB", "")

    branch = branch_a

    pipeline_name = _get_str_field(payload, "pipelineName", "")
    if not pipeline_name:
        # resolve from templates if possible
        try:
            templates = _templates_store.load() or {}
            if isinstance(templates, dict):
                for t in (templates.get("consultants") or []):
                    if isinstance(t, dict) and str(t.get("id") or "") == consultant_id:
                        pipeline_name = str(t.get("pipelineName") or "").strip()
                        break
        except Exception:
            py_logger.exception("soft-failure: failed to resolve pipelineName from templates; consultant_id=%s", consultant_id)
            pipeline_name = ""

    pipeline_settings = dict(_pipeline_settings_by_name.get(pipeline_name) or {})
    if "development" not in pipeline_settings:
        pipeline_settings["development"] = bool(_development_enabled)
    if "llm_server_security_messages_default" not in pipeline_settings:
        defaults = _runtime_cfg.get("llm_server_security_messages_default")
        if isinstance(defaults, dict):
            pipeline_settings["llm_server_security_messages_default"] = defaults
    callback_policy = resolve_callback_policy(runtime_cfg=_runtime_cfg, pipeline_settings=pipeline_settings)
    effective_trace_enabled = bool(enable_trace and callback_policy.enabled)

    repository = _get_str_field(payload, "repository", str(_runtime_cfg.get("repo_name") or ""))
    snapshot_id = _get_str_field(payload, "snapshot_id", _get_str_field(payload, "snapshotId", ""))
    snapshot_id_b = _get_str_field(payload, "snapshot_id_b", _get_str_field(payload, "snapshotIdB", ""))
    snapshots_raw = payload.get("snapshots")
    if isinstance(snapshots_raw, list):
        snapshots_clean = [str(x or "").strip() for x in snapshots_raw if str(x or "").strip()]
        if len(snapshots_clean) > 2:
            return jsonify({"ok": False, "error": "too many snapshots (max 2)"}), 400
        if len(snapshots_clean) == 2 and snapshots_clean[0] == snapshots_clean[1]:
            return jsonify({"ok": False, "error": "compare requires two different snapshots"}), 400
        # Contract-friendly: if frontend sends snapshots[], first item is the active snapshot_id.
        if not snapshot_id and snapshots_clean:
            snapshot_id = snapshots_clean[0]
        # Compare-friendly: optional second snapshot id is stored explicitly.
        if not snapshot_id_b and len(snapshots_clean) > 1:
            snapshot_id_b = snapshots_clean[1]

    snapshot_set_id = _get_str_field(payload, "snapshot_set_id", _get_str_field(payload, "snapshotSetId", ""))
    source_system_id = _get_str_field(payload, "source_system_id", _get_str_field(payload, "sourceSystemId", ""))
    if _pipeline_snapshot_store and _snapshot_registry:
        exists, pipeline_snapshot_set_id = _pipeline_snapshot_store.get_snapshot_set_id(pipeline_name)
        if not exists:
            return jsonify({"ok": False, "error": f"pipeline '{pipeline_name}' not found in loaded pipeline settings"}), 400

        if pipeline_snapshot_set_id:
            # Ensure snapshot set exists in Weaviate.
            rec = _snapshot_registry.fetch_snapshot_set(
                snapshot_set_id=pipeline_snapshot_set_id,
                repository=repository or None,
            )
            if rec is None:
                return jsonify({"ok": False, "error": f"unknown snapshot_set_id '{pipeline_snapshot_set_id}'"}), 400

            if snapshot_set_id and snapshot_set_id != pipeline_snapshot_set_id:
                return jsonify({"ok": False, "error": "snapshot_set_id mismatch for selected pipeline"}), 400
            snapshot_set_id = pipeline_snapshot_set_id
        else:
            if snapshot_set_id:
                return jsonify({"ok": False, "error": "pipeline has no snapshot_set_id configured"}), 400

    if not snapshot_id and snapshot_set_id:
        snapshot_id = _resolve_snapshot_id_from_set(snapshot_set_id=snapshot_set_id, repository=repository or None)

    snapshot_friendly_names: Dict[str, str] = {}
    if _snapshot_registry:
        try:
            if snapshot_set_id:
                snapshots = _snapshot_registry.list_snapshots(
                    snapshot_set_id=snapshot_set_id,
                    repository=repository or None,
                )
                snapshot_friendly_names = {s.id: s.label for s in (snapshots or []) if s.id and s.label}
            else:
                if snapshot_id:
                    label = _snapshot_registry.resolve_snapshot_label(
                        repository=repository or "",
                        snapshot_id=snapshot_id,
                    )
                    if label:
                        snapshot_friendly_names[snapshot_id] = label
                if snapshot_id_b:
                    label_b = _snapshot_registry.resolve_snapshot_label(
                        repository=repository or "",
                        snapshot_id=snapshot_id_b,
                    )
                    if label_b:
                        snapshot_friendly_names[snapshot_id_b] = label_b
        except Exception:
            py_logger.exception("soft-failure: resolve snapshot friendly names")

    client_session_id = _valid_session_id(request.headers.get("X-Session-ID") or _get_str_field(payload, "session_id", ""))

    # Resolve access context (dev-only auth for now).
    raw_user_id = _valid_user_id(_get_str_field(payload, "user_id", ""))
    access_ctx: UserAccessContext = _user_access_provider.resolve(
        user_id=raw_user_id,
        token=auth_header,
        session_id=client_session_id,
        claims=getattr(g, "idp_claims", {}) or {},
    )
    user_id = _valid_user_id(access_ctx.user_id)

    # IMPORTANT: isolate conversational context per user even if the frontend reuses the same sessionId
    # across identities (sessionId is stored in localStorage).
    # We keep the client-visible session_id unchanged in responses and in chat-history endpoints,
    # but internally namespace the pipeline session_id to avoid cross-user context leaks.
    ns_user_id = user_id or "anon"
    try:
        # For IdP/OIDC tokens prefer stable `sub` for the namespace (user_id may vary by claim mapping).
        if not auth_header.lower().startswith("bearer dev-user:"):
            claims = getattr(g, "idp_claims", {}) or {}
            if isinstance(claims, dict):
                sub_raw = str(claims.get("sub") or "").strip()
                if sub_raw:
                    ns_user_id = _safe_id_component(sub_raw) or ns_user_id
    except Exception:
        pass

    session_id = _valid_session_id(f"u_{ns_user_id}__{client_session_id}")
    _migrate_conversation_kv_for_namespaced_session(
        backend=_history_backend,
        src_session_id=client_session_id,
        dst_session_id=session_id,
        user_id=user_id,
    )

    trace_run_id = client_trace_run_id
    if effective_trace_enabled and not trace_run_id:
        trace_run_id = f"{int(datetime.now(timezone.utc).timestamp() * 1000)}_{uuid.uuid4().hex[:12]}"
    if trace_run_id:
        broker = get_work_callback_broker()
        broker.configure_run(trace_run_id, policy=callback_policy)

    overrides: Dict[str, Any] = {}
    if effective_trace_enabled:
        overrides["trace_enabled"] = True
        if trace_run_id:
            overrides["pipeline_run_id"] = trace_run_id
    if branch_b:
        overrides["branch_b"] = branch_b
    retrieval_filters_override: Dict[str, Any] = {}
    security_cfg = _runtime_cfg.get("permissions") or {}
    acl_enabled = True
    security_enabled = False
    security_kind = ""
    if isinstance(security_cfg, dict):
        acl_enabled = bool(security_cfg.get("acl_enabled", True))
        security_enabled = bool(security_cfg.get("security_enabled", False))
        security_kind = str((security_cfg.get("security_model") or {}).get("kind") or "")
    acl_tags_any = list(getattr(access_ctx, "acl_tags_any", None) or getattr(access_ctx, "acl_tags_all", None) or [])
    if acl_enabled and acl_tags_any:
        retrieval_filters_override["acl_tags_any"] = acl_tags_any
    classification_labels_all = list(getattr(access_ctx, "classification_labels_all", None) or [])
    if security_enabled and security_kind in ("labels_universe_subset", "classification_labels") and classification_labels_all:
        retrieval_filters_override["classification_labels_all"] = classification_labels_all
    user_level = getattr(access_ctx, "user_level", None)
    if security_enabled and security_kind == "clearance_level" and user_level is not None:
        retrieval_filters_override["user_level"] = int(user_level)
    owner_id = str(getattr(access_ctx, "owner_id", "") or "").strip()
    if owner_id:
        retrieval_filters_override["owner_id"] = owner_id
    if source_system_id:
        retrieval_filters_override["source_system_id"] = source_system_id
    # Drop empty filters to avoid polluting state.
    if retrieval_filters_override:
        overrides["retrieval_filters"] = retrieval_filters_override
    if access_ctx.allowed_commands:
        overrides["allowed_commands"] = list(access_ctx.allowed_commands)
    if snapshot_friendly_names:
        overrides["snapshot_friendly_names"] = snapshot_friendly_names
    if "model_context_window" not in pipeline_settings and "model_context_window" not in overrides:
        try:
            mcw = int(_runtime_cfg.get("model_context_window", 0) or 0)
        except Exception:
            mcw = 0
        if mcw > 0:
            overrides["model_context_window"] = mcw

    custom_auth_error = _enforce_custom_access_policies(
        access_ctx=access_ctx,
        pipeline_name=pipeline_name,
        consultant_id=consultant_id,
        snapshot_set_id=snapshot_set_id,
        snapshot_id=snapshot_id,
        snapshot_id_b=snapshot_id_b,
        repository=repository,
    )
    if custom_auth_error is not None:
        return custom_auth_error

    request_id = (request.headers.get("X-Request-ID") or "").strip() or str(uuid.uuid4())

    try:
        runner_result = _runner.run(
            user_query=original_query,
            session_id=session_id,
            user_id=user_id,
            request_id=request_id,
            consultant=consultant_id,
            branch=branch,
            translate_chat=translate_chat,
            pipeline_name=pipeline_name or None,
            repository=repository or None,
            snapshot_id=snapshot_id or None,
            snapshot_id_b=snapshot_id_b or None,
            snapshot_set_id=snapshot_set_id or None,
            overrides=overrides or None,
            mock_redis=_history_backend,
        )
    except PipelineCancelled as e:
        py_logger.info("Pipeline cancelled: run_id=%s reason=%s", e.run_id, e.reason)
        return jsonify({"ok": False, "cancelled": True, "error": "cancelled", "pipeline_run_id": e.run_id}), 200
    except Exception as e:
        py_logger.exception("Unhandled exception in /query")
        return jsonify({"ok": False, "error": str(e)}), 500

    out = _normalize_runner_result(runner_result)
    if not effective_trace_enabled:
        out.pop("pipeline_run_id", None)
    elif trace_run_id and not out.get("pipeline_run_id"):
        out["pipeline_run_id"] = trace_run_id

    out["ok"] = True
    out["session_id"] = client_session_id
    out["consultant"] = consultant_id
    out["trace_enabled"] = bool(effective_trace_enabled)
    if pipeline_name:
        out["pipelineName"] = pipeline_name
    if repository:
        out["repository"] = repository

    # Keep legacy fields (safe for older UI)
    if branch_a:
        out["branchA"] = branch_a
    if branch_b:
        out["branchB"] = branch_b

    # New field (preferred by new UI)
    if branch_a and branch_b:
        out["branches"] = [branch_a, branch_b]
    elif branch_a:
        out["branches"] = [branch_a]

    return jsonify(out)


@app.route("/query", methods=["POST"])
@app.route("/search", methods=["POST"])
def query():
    return _handle_query_request()


@app.route("/auth-check", methods=["GET"])
def auth_check():
    auth_header = (request.headers.get("Authorization") or "").strip()
    auth_error = _require_bearer_if_needed(auth_header)
    if auth_error is not None:
        return auth_error
    if _auth_required:
        return jsonify({"ok": True, "profile": _app_profile, "auth": "bearer"})
    return jsonify({"ok": True, "profile": _app_profile, "auth": "optional"})


# ------------------------------------------------------------
# Chat history (mock SQL store)
# ------------------------------------------------------------

@app.route("/chat-history/sessions", methods=["GET", "POST"])
def chat_history_sessions():
    if not _mock_sql_enabled:
        return _history_unavailable()
    auth_header = (request.headers.get("Authorization") or "").strip()
    auth_error = _require_bearer_if_needed(auth_header)
    if auth_error is not None:
        return auth_error

    if request.method == "GET":
        _history_prune()
        tenant_id = _history_tenant_id()
        user_id = _history_user_id()
        if _history_is_anon(user_id):
            return jsonify({"items": [], "next_cursor": None})
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(200, limit))
        cursor = request.args.get("cursor")
        q = request.args.get("q")
        return jsonify(_history_list_sessions(
            tenant_id=tenant_id,
            user_id=user_id,
            limit=limit,
            cursor=cursor,
            q=q,
        ))

    payload = request.get_json(silent=True) or {}
    tenant_id = _history_tenant_id()
    user_id = _history_user_id()
    now = _history_now_ms()
    session_id = _valid_session_id(str(payload.get("sessionId") or payload.get("session_id") or uuid.uuid4().hex))

    # Idempotent create: the frontend may call createSession again after reload
    # (loaded sessions do not carry the local `_persisted` marker). Never wipe messages.
    if not _history_is_anon(user_id):
        # Ensure legacy (sessionId-keyed) entries are migrated/merged before we check existence.
        key = _history_resolve_session_key(tenant_id=tenant_id, user_id=user_id, session_id=session_id) or _history_key(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id
        )
        existing = _history_sessions.get(key)
        if isinstance(existing, dict) and not existing.get("deletedAt") and not existing.get("softDeletedAt"):
            title_new = str(payload.get("title") or payload.get("firstQuestion") or "").strip()
            if title_new:
                title_old = str(existing.get("title") or "").strip()
                if (not title_old) or (title_old.lower() in ("new chat", "nowy czat")):
                    existing["title"] = title_new
            consultant_new = str(payload.get("consultantId") or payload.get("consultant") or "").strip()
            if consultant_new and not str(existing.get("consultantId") or "").strip():
                existing["consultantId"] = consultant_new
            existing["updatedAt"] = now
            if key not in _history_messages:
                _history_messages[key] = []
            return jsonify(existing)

    session = {
        "sessionId": session_id,
        "tenantId": tenant_id,
        "userId": user_id,
        "title": str(payload.get("title") or payload.get("firstQuestion") or "New chat"),
        "consultantId": str(payload.get("consultantId") or payload.get("consultant") or ""),
        "createdAt": now,
        "updatedAt": now,
        "messageCount": 0,
        "deletedAt": None,
        "softDeletedAt": None,
        "status": "active",
    }
    if not _history_is_anon(user_id):
        key = _history_key(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
        _history_sessions[key] = session
        if key not in _history_messages:
            _history_messages[key] = []
    return jsonify(session)


@app.route("/chat-history/sessions/<session_id>", methods=["GET", "PATCH", "DELETE"])
def chat_history_session(session_id: str):
    if not _mock_sql_enabled:
        return _history_unavailable()
    auth_header = (request.headers.get("Authorization") or "").strip()
    auth_error = _require_bearer_if_needed(auth_header)
    if auth_error is not None:
        return auth_error

    _history_prune()
    tenant_id = _history_tenant_id()
    user_id = _history_user_id()
    if _history_is_anon(user_id):
        return jsonify({"error": "not_found"}), 404
    key = _history_resolve_session_key(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
    if not key:
        return jsonify({"error": "not_found"}), 404
    session = _history_sessions.get(key)
    if not session or session.get("tenantId") != tenant_id or session.get("userId") != user_id or session.get("deletedAt") or session.get("softDeletedAt"):
        return jsonify({"error": "not_found"}), 404

    if request.method == "GET":
        return jsonify(session)

    if request.method == "DELETE":
        now = _history_now_ms()
        session["softDeletedAt"] = now
        session["status"] = "soft_deleted"
        session["updatedAt"] = now
        return jsonify({"ok": True, "sessionId": session_id})

    payload = request.get_json(silent=True) or {}
    if "title" in payload and payload["title"] is not None:
        session["title"] = str(payload["title"])
    if "consultantId" in payload and payload["consultantId"] is not None:
        session["consultantId"] = str(payload["consultantId"])
    if "important" in payload:
        session["important"] = bool(payload["important"])
    if "softDeleted" in payload:
        if payload["softDeleted"]:
            session["softDeletedAt"] = _history_now_ms()
            session["status"] = "soft_deleted"
        else:
            session["softDeletedAt"] = None
            session["status"] = "active"
    session["updatedAt"] = _history_now_ms()
    return jsonify(session)


@app.route("/chat-history/sessions/<session_id>/messages", methods=["GET", "POST"])
def chat_history_messages(session_id: str):
    if not _mock_sql_enabled:
        return _history_unavailable()
    auth_header = (request.headers.get("Authorization") or "").strip()
    auth_error = _require_bearer_if_needed(auth_header)
    if auth_error is not None:
        return auth_error

    _history_prune()
    tenant_id = _history_tenant_id()
    user_id = _history_user_id()
    session_id = _valid_session_id(session_id)
    if _history_is_anon(user_id):
        if request.method == "GET":
            return jsonify({"items": [], "next_cursor": None})
        # Accept but do not persist
        msg = {
            "messageId": uuid.uuid4().hex,
            "sessionId": session_id,
            "ts": _history_now_ms(),
            "q": "",
            "a": "",
            "meta": None,
            "deletedAt": None,
        }
        return jsonify(msg)
    key = _history_resolve_session_key(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
    if not key:
        if request.method == "GET":
            return jsonify({"error": "not_found"}), 404
        # Fallback: auto-create session on first message if the client did not create it in time.
        now = _history_now_ms()
        key = _history_key(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
        _history_sessions[key] = {
            "sessionId": session_id,
            "tenantId": tenant_id,
            "userId": user_id,
            "title": "New chat",
            "consultantId": "",
            "createdAt": now,
            "updatedAt": now,
            "messageCount": 0,
            "deletedAt": None,
            "softDeletedAt": None,
            "status": "active",
        }
        _history_messages.setdefault(key, [])

    session = _history_sessions.get(key)
    if not session or session.get("tenantId") != tenant_id or session.get("userId") != user_id or session.get("deletedAt"):
        return jsonify({"error": "not_found"}), 404

    if request.method == "GET":
        limit = int(request.args.get("limit", 100))
        limit = max(1, min(200, limit))
        before = request.args.get("before")
        before_ts = int(before) if before else None
        all_msgs = [m for m in _history_messages.get(key, []) if not m.get("deletedAt")]
        if before_ts:
            all_msgs = [m for m in all_msgs if int(m.get("ts") or 0) < before_ts]
        items = all_msgs[-limit:]
        next_cursor = str(items[0].get("ts")) if len(items) == limit else None
        return jsonify({"items": items, "next_cursor": next_cursor})

    payload = request.get_json(silent=True) or {}
    now = _history_now_ms()
    msg = {
        "messageId": str(payload.get("messageId") or payload.get("message_id") or uuid.uuid4().hex),
        "sessionId": session_id,
        "ts": now,
        "q": "" if payload.get("q") is None else str(payload.get("q")),
        "a": "" if payload.get("a") is None else str(payload.get("a")),
        "meta": payload.get("meta"),
        "deletedAt": None,
    }
    msgs = _history_messages.get(key, [])
    msgs.append(msg)
    _history_messages[key] = msgs
    session["updatedAt"] = now
    session["messageCount"] = len(msgs)
    # Use the first question as the session title when the session still has the default title.
    try:
        title = str(session.get("title") or "").strip()
        if (not title) or title.lower() in ("new chat", "nowy czat"):
            q0 = str(msg.get("q") or "").strip()
            if q0:
                session["title"] = q0.replace("\n", " ").strip()[:64]
    except Exception:
        pass
    return jsonify(msg)
