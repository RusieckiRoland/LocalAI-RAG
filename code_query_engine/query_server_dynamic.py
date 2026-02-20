from __future__ import annotations

import logging
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, abort, jsonify, request, send_file, g
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
    from jwt.exceptions import InvalidTokenError as _JwtInvalidTokenError  # type: ignore
    from jwt.exceptions import PyJWKClientError as _JwtPyJwkClientError  # type: ignore
except Exception:
    _pyjwt = None
    _PyJWKClient = None
    _JwtExpiredSignatureError = Exception
    _JwtInvalidTokenError = Exception
    _JwtPyJwkClientError = Exception



# ------------------------------------------------------------
# Paths / constants
# ------------------------------------------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

RUNTIME_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
FRONTEND_HTML_PATH = os.path.join(PROJECT_ROOT, "frontend", "Rag.html")

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


def _load_runtime_cfg() -> dict:
    return _load_json_file(RUNTIME_CONFIG_PATH) or {}


_runtime_cfg = _load_runtime_cfg()
_development_raw = _runtime_cfg.get("developement", _runtime_cfg.get("development", True))
_development_enabled = bool(_development_raw)
_development_env = (os.getenv("APP_DEVELOPMENT") or "").strip().lower()
if _development_env in ("1", "true", "yes", "on"):
    _development_enabled = True
elif _development_env in ("0", "false", "no", "off"):
    _development_enabled = False


# ------------------------------------------------------------
# Logging (source of truth: config.json)
# ------------------------------------------------------------

_logging_cfg = logging_config_from_runtime_config(_runtime_cfg)
configure_logging(_logging_cfg)


def _validate_security_consistency(*, runtime_cfg: dict, client: Any | None) -> None:
    security = runtime_cfg.get("permissions") or {}
    if not isinstance(security, dict):
        py_logger.warning("permissions config missing or invalid; security checks skipped")
        return

    if not security.get("security_enabled", False):
        py_logger.warning("permissions.security_enabled is false; system will not enforce security filters")
        if client is not None:
            try:
                coll = client.collections.get("RagNode")
                cfg = coll.config.get()
                props = [p.name for p in (cfg.properties or [])]
                if "classification_labels" in props or "doc_level" in props:
                    py_logger.warning(
                        "permissions: security_enabled is false but RagNode schema contains security fields (classification_labels/doc_level)"
                    )
            except Exception:
                py_logger.exception("permissions: failed to validate RagNode schema when security is disabled")
        return

    model = security.get("security_model") or {}
    kind = str(model.get("kind") or "").strip()
    if kind not in ("clearance_level", "labels_universe_subset", "classification_labels"):
        py_logger.warning("security.enabled is true but security_model.kind is missing/invalid")
        return

    # Validate Weaviate schema (best-effort).
    if client is not None:
        try:
            coll = client.collections.get("RagNode")
            cfg = coll.config.get()
            props = [p.name for p in (cfg.properties or [])]
            if bool(security.get("acl_enabled", True)) and "acl_allow" not in props:
                py_logger.warning("permissions: acl_enabled is true but 'acl_allow' is missing in RagNode schema")
            if kind == "clearance_level":
                field = str((model.get("clearance_level") or {}).get("doc_level_field") or "doc_level")
                if field not in props:
                    py_logger.warning("permissions: doc_level field '%s' not found in RagNode schema", field)
            if kind in ("labels_universe_subset", "classification_labels"):
                field = str((model.get("labels_universe_subset") or model.get("classification_labels") or {}).get("doc_labels_field") or "classification_labels")
                if field not in props:
                    py_logger.warning("permissions: classification labels field '%s' not found in RagNode schema", field)
        except Exception:
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
                    py_logger.warning("permissions: claim_group_mappings refers to unknown group '%s'", group)
            for _k, group in (list_map or {}).items():
                if str(group) not in group_ids:
                    py_logger.warning("permissions: claim_group_mappings refers to unknown group '%s'", group)

        if kind == "clearance_level":
            if not any(p.user_level is not None for p in policies.values()):
                py_logger.warning("permissions: clearance_level enabled but no group has user_level in auth_policies")
        if kind in ("labels_universe_subset", "classification_labels"):
            universe = (model.get("labels_universe_subset") or model.get("classification_labels") or {}).get("classification_labels_universe") or []
            universe_set = set(str(x).strip() for x in universe if str(x).strip())
            if not universe_set:
                py_logger.warning("permissions: labels_universe_subset enabled but classification_labels_universe is empty")
            for gid, policy in policies.items():
                for label in policy.classification_labels_all or []:
                    if label not in universe_set:
                        py_logger.warning(
                            "permissions: group '%s' has classification label '%s' outside universe",
                            gid,
                            label,
                        )
    except Exception:
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
    raw = runtime_cfg.get("identity_provider") or {}
    if not isinstance(raw, dict):
        raw = {}

    env_enabled = (os.getenv("IDP_AUTH_ENABLED") or "").strip().lower()
    if env_enabled in ("1", "true", "yes", "on"):
        enabled = True
    elif env_enabled in ("0", "false", "no", "off"):
        enabled = False
    else:
        enabled = bool(raw.get("enabled", True))

    issuer = str(raw.get("issuer") or "").strip()
    jwks_url = str(raw.get("jwks_url") or "").strip()
    audience = str(raw.get("audience") or "").strip()

    algorithms_raw = raw.get("algorithms") or ["RS256"]
    algorithms = tuple(str(x).strip() for x in algorithms_raw if str(x).strip())
    if not algorithms:
        algorithms = ("RS256",)

    required_raw = raw.get("required_claims") or ["sub", "exp", "iss", "aud"]
    required_claims = tuple(str(x).strip() for x in required_raw if str(x).strip())

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

_conversation_history_service = build_conversation_history_service(session_backend=_history_backend)


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


_server_llm = bool(_runtime_cfg.get("serverLLM"))


def _load_llm_servers() -> tuple[dict[str, "ServerLLMConfig"], str]:
    path = os.path.join(PROJECT_ROOT, "ServersLLM.json")
    if not os.path.isfile(path):
        raise ValueError(f"ServersLLM.json not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
    servers_raw = data.get("servers") or []
    if not isinstance(servers_raw, list) or not servers_raw:
        raise ValueError("ServersLLM.json: 'servers' must be a non-empty list")
    servers: dict[str, ServerLLMConfig] = {}
    default_candidates: list[str] = []
    for item in servers_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        base_url = str(item.get("base_url") or "").strip()
        if not name or not base_url:
            continue
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
        print(f"WARNING: {msg}")
    return servers, default_candidates[0]

_model = None
if not _server_llm:
    # NOTE: your Model wrapper is outside the uploaded set; keep as-is in repo.
    from .model import Model  # noqa: E402

    _model = Model(
        _resolve_cfg_path(str(_runtime_cfg.get("model_path_analysis") or "")),
        default_max_tokens=int(_runtime_cfg.get("model_max_tokens", 1500) or 1500),
        n_ctx=int(_runtime_cfg.get("model_context_window", 4096) or 4096),
    )
else:
    from .llm_server_client import ServerLLMClient, ServerLLMConfig, ThrottleConfig  # noqa: E402

    try:
        servers, default_name = _load_llm_servers()
        _model = ServerLLMClient(servers=servers, default_name=default_name)
        py_logger.warning("serverLLM=true: local model initialization skipped (using server '%s').", default_name)
    except Exception as e:
        py_logger.error("serverLLM=true but failed to load ServersLLM.json: %s", e)
        print(f"ERROR: serverLLM=true but failed to load ServersLLM.json: {e}")
        raise

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

if _skip_weaviate_init:
    py_logger.warning("degraded-mode: skipping Weaviate init (test mode)")
    _validate_security_consistency(runtime_cfg=_runtime_cfg, client=None)
else:
    try:
        _weaviate_settings = get_weaviate_settings()
        _weaviate_client = create_weaviate_client(_weaviate_settings)
    except Exception:
        py_logger.exception("fatal: cannot initialize Weaviate client (vector_db/weaviate_client.py)")
        raise

    _validate_security_consistency(runtime_cfg=_runtime_cfg, client=_weaviate_client)

    _embed_model_path = _resolve_cfg_path(str(_runtime_cfg.get("model_path_embd") or ""))
    _security_cfg = _runtime_cfg.get("permissions") or {}
    _classification_universe = []
    try:
        _sec_model = (_security_cfg.get("security_model") or {}) if isinstance(_security_cfg, dict) else {}
        _labels_cfg = _sec_model.get("labels_universe_subset") or {}
        _classification_universe = _labels_cfg.get("classification_labels_universe") or []
        if isinstance(_classification_universe, str):
            _classification_universe = [s.strip() for s in _classification_universe.split(",") if s.strip()]
    except Exception:
        py_logger.exception("soft-failure: failed to resolve classification_labels_universe from permissions config")
    _doc_level_field = "doc_level"
    _doc_labels_field = "classification_labels"
    try:
        _sec_model = (_security_cfg.get("security_model") or {}) if isinstance(_security_cfg, dict) else {}
        _kind = str(_sec_model.get("kind") or "").strip()
        if _kind == "clearance_level":
            _doc_level_field = str((_sec_model.get("clearance_level") or {}).get("doc_level_field") or _doc_level_field)
        if _kind == "labels_universe_subset":
            _doc_labels_field = str((_sec_model.get("labels_universe_subset") or {}).get("doc_labels_field") or _doc_labels_field)
    except Exception:
        py_logger.exception("soft-failure: failed to resolve security model fields from config")
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


def _resolve_snapshot_id_from_set(*, snapshot_set_id: str, repository: str | None) -> str:
    if not _snapshot_registry:
        return ""
    return _snapshot_registry.resolve_snapshot_id(snapshot_set_id=snapshot_set_id, repository=repository)


def _dev_endpoints_enabled() -> bool:
    return _development_enabled


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
        return jsonify({"ok": False, "error": "unauthorized"}), 401

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
        return jsonify({"ok": False, "error": "token expired"}), 401
    except _JwtInvalidTokenError:
        _log_security_abuse(reason="invalid_token", status_code=401)
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    except _JwtPyJwkClientError as ex:
        _log_security_abuse(reason="jwks_unavailable", status_code=503)
        py_logger.warning("idp jwks error: %s", ex)
        return jsonify({"ok": False, "error": "identity provider unavailable"}), 503
    except Exception:
        _log_security_abuse(reason="idp_validation_error", status_code=503)
        py_logger.exception("idp token validation failed unexpectedly")
        return jsonify({"ok": False, "error": "identity provider unavailable"}), 503


def _require_prod_bearer(auth_header: str):
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


register_work_callback_routes(
    app,
    dev_enabled_fn=_dev_endpoints_enabled,
    require_prod_bearer_fn=_require_prod_bearer,
)
register_cancel_routes(
    app,
    dev_enabled_fn=_dev_endpoints_enabled,
    require_prod_bearer_fn=_require_prod_bearer,
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
    return send_file(FRONTEND_HTML_PATH)


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

@app.route("/app-config/dev", methods=["GET"])
def app_config_dev():
    if not _dev_endpoints_enabled():
        abort(404)
    return _handle_app_config_request(require_bearer_auth=False)


@app.route("/app-config/prod", methods=["GET"])
def app_config_prod():
    return _handle_app_config_request(require_bearer_auth=True)


def _handle_app_config_request(*, require_bearer_auth: bool):
    auth_header = (request.headers.get("Authorization") or "").strip()
    if require_bearer_auth:
        auth_error = _require_prod_bearer(auth_header)
        if auth_error is not None:
            return auth_error

    session_id = _valid_session_id(request.headers.get("X-Session-ID") or "app-config")
    cfg = dict(_runtime_cfg)
    cfg["project_root"] = PROJECT_ROOT
    cfg["repositories_root"] = REPOSITORIES_ROOT
    return jsonify(
        _app_config_service.build_app_config(
            runtime_cfg=cfg,
            session_id=session_id,
            auth_header=auth_header,
        )
    )


# ------------------------------------------------------------
# Query endpoint (contract: query/consultant/pipelineName/branches[0..2])
# Backward-compat: still accept legacy branchA/branchB.
# ------------------------------------------------------------

def _handle_query_request(*, require_bearer_auth: bool):
    auth_header = (request.headers.get("Authorization") or "").strip()
    if require_bearer_auth:
        auth_error = _require_prod_bearer(auth_header)
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

    session_id = _valid_session_id(request.headers.get("X-Session-ID") or _get_str_field(payload, "session_id", ""))

    # Resolve access context (dev-only auth for now).
    raw_user_id = _valid_user_id(_get_str_field(payload, "user_id", ""))
    access_ctx: UserAccessContext = _user_access_provider.resolve(
        user_id=raw_user_id,
        token=auth_header,
        session_id=session_id,
        claims=getattr(g, "idp_claims", {}) or {},
    )
    user_id = _valid_user_id(access_ctx.user_id)

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
    if isinstance(security_cfg, dict):
        acl_enabled = bool(security_cfg.get("acl_enabled", True))
    acl_tags_any = list(getattr(access_ctx, "acl_tags_any", None) or getattr(access_ctx, "acl_tags_all", None) or [])
    if acl_enabled and acl_tags_any:
        retrieval_filters_override["acl_tags_any"] = acl_tags_any
    classification_labels_all = list(getattr(access_ctx, "classification_labels_all", None) or [])
    if classification_labels_all:
        retrieval_filters_override["classification_labels_all"] = classification_labels_all
    user_level = getattr(access_ctx, "user_level", None)
    if user_level is not None:
        retrieval_filters_override["user_level"] = int(user_level)
    owner_id = str(getattr(access_ctx, "owner_id", "") or "").strip()
    if owner_id:
        retrieval_filters_override["owner_id"] = owner_id
    if source_system_id:
        retrieval_filters_override["source_system_id"] = source_system_id
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
    out["session_id"] = session_id
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


@app.route("/query/dev", methods=["POST"])
@app.route("/search/dev", methods=["POST"])
def query_dev_explicit():
    if not _dev_endpoints_enabled():
        abort(404)
    return _handle_query_request(require_bearer_auth=False)


@app.route("/query/prod", methods=["POST"])
@app.route("/search/prod", methods=["POST"])
def query_prod():
    return _handle_query_request(require_bearer_auth=True)


@app.route("/auth-check/prod", methods=["GET"])
def auth_check_prod():
    auth_header = (request.headers.get("Authorization") or "").strip()
    auth_error = _require_prod_bearer(auth_header)
    if auth_error is not None:
        return auth_error
    return jsonify({"ok": True, "mode": "prod", "auth": "bearer"})
