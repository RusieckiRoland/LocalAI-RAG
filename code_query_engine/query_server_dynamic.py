# code_query_engine/query_server_dynamic.py

import os
import re
import uuid
import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from dotenv import load_dotenv

from common.markdown_translator_en_pl import MarkdownTranslator
from common.translator_pl_en import Translator
from vector_db.unified_index_loader import load_unified_search

from .log_utils import InteractionLogger
from .model import Model
from history.mock_redis import InMemoryMockRedis
from history.redis_backend import RedisBackend

from .dynamic_pipeline import DynamicPipelineRunner

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN", "").strip()

# If set to "true", use Redis history backend; otherwise use in-memory mock
USE_REDIS = os.getenv("APP_USE_REDIS", "false").strip().lower() == "true"

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Repositories root for listing repositories/branches (used by UI)
REPOSITORIES_ROOT = os.path.abspath(os.getenv("REPOSITORIES_ROOT", "repositories"))

# Frontend contracts (JSON)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UI_CONTRACTS_DIR = os.path.join(PROJECT_ROOT, "ui_contracts", "frontend_requirements")
UI_TEMPLATES_PATH = os.path.join(UI_CONTRACTS_DIR, "templates.json")

# Runtime config.json (repo root)
RUNTIME_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

# Frontend HTML (served by Flask)
FRONTEND_HTML_PATH = os.path.join(PROJECT_ROOT, "frontend", "Rag.html")

# Security/limits
MAX_QUERY_LEN = int(os.getenv("APP_MAX_QUERY_LEN", "8000"))
MAX_FIELD_LEN = int(os.getenv("APP_MAX_FIELD_LEN", "128"))

_json_cache_lock = Lock()
_json_cache: dict[str, tuple[float, dict]] = {}

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # Node mock (if used)
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    # Opening HTML directly from disk (file://) => Origin: null
    "null",
]

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": ALLOWED_ORIGINS}},
    supports_credentials=True,
)


@app.get("/")
def ui_index():
    # Serve the single-file frontend UI from the Flask server.
    if not os.path.isfile(FRONTEND_HTML_PATH):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Frontend file not found.",
                    "path": FRONTEND_HTML_PATH,
                }
            ),
            404,
        )
    return send_file(FRONTEND_HTML_PATH)


def _is_authorized(req) -> bool:
    if not API_TOKEN:
        return True
    header = (req.headers.get("Authorization") or "").strip()
    if not header:
        return False
    if header.startswith("Bearer "):
        token = header.replace("Bearer ", "", 1).strip()
        return token == API_TOKEN
    return header == API_TOKEN


def _valid_session_id(value: str | None) -> str:
    v = (value or "").strip()
    if not v:
        return uuid.uuid4().hex
    v = v[:MAX_FIELD_LEN]
    if not re.match(r"^[a-zA-Z0-9_\-]+$", v):
        return uuid.uuid4().hex
    return v


def _valid_user_id(value: str | None) -> str | None:
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
            txt = Path(path).read_text(encoding="utf-8")
            data = json.loads(txt)
        except Exception:
            data = {}

        _json_cache[path] = (mtime, data)
        return data


def _load_runtime_config() -> dict:
    """Load runtime config.json from repository root."""
    return _load_json_file(RUNTIME_CONFIG_PATH)


def _resolve_cfg_path(value: str) -> str:
    """Resolve config-relative paths against PROJECT_ROOT."""
    v = (value or "").strip()
    if not v:
        return ""
    if os.path.isabs(v):
        return v
    return os.path.join(PROJECT_ROOT, v)


def _load_ui_templates() -> dict:
    """Load UI templates (consultants) from ui_contracts."""
    return _load_json_file(UI_TEMPLATES_PATH)


def _derive_branch_from_active_index(active_index_id: str | None) -> str | None:
    """Extract branch name from index id like '2025-12-14__develop'."""
    v = (active_index_id or "").strip()
    if "__" not in v:
        return None
    parts = v.split("__", 1)
    if len(parts) != 2:
        return None
    branch = parts[1].strip()
    return branch or None


def _pick_default_branch(available: list[str], cfg: dict) -> str:
    """Choose a default branch for UI based on config.active_index_id or available list."""
    if not available:
        return "develop"
    active_index_id = str(cfg.get("active_index_id") or "").strip()
    derived = _derive_branch_from_active_index(active_index_id)
    if derived and derived in available:
        return derived
    return available[0]


def _find_pipeline_for_consultant(consultant_id: str, templates: dict) -> str:
    """Map consultant id to pipelineName from templates.json."""
    consultants = templates.get("consultants") if isinstance(templates, dict) else None
    if isinstance(consultants, list):
        for c in consultants:
            if isinstance(c, dict) and str(c.get("id") or "") == consultant_id:
                return str(c.get("pipelineName") or "").strip()
    return ""


def _normalize_runner_result(result):
    """Support both dict and tuple outputs from different runner versions."""
    if isinstance(result, dict):
        return result
    if isinstance(result, (list, tuple)):
        final_answer = result[0] if len(result) > 0 else ""
        model_input_en = result[3] if len(result) > 3 else ""
        return {"results": final_answer, "translated": model_input_en}
    return {"results": "", "translated": ""}


def _list_repositories() -> List[str]:
    try:
        out: List[str] = []
        if not os.path.isdir(REPOSITORIES_ROOT):
            return out
        for name in os.listdir(REPOSITORIES_ROOT):
            full = os.path.join(REPOSITORIES_ROOT, name)
            if os.path.isdir(full):
                out.append(name)
        out.sort(key=lambda x: x.lower())
        return out
    except Exception:
        return []


def _read_active_index_branches(cfg: dict) -> List[str]:
    """
    Option A: branches come from active unified index manifest.json.

    Expected config keys:
    - vector_indexes_root: path to indexes root
    - active_index_id: active unified index id (folder name)
    """
    try:
        indexes_root = _resolve_cfg_path(str(cfg.get("vector_indexes_root") or "").strip())
        index_id = str(cfg.get("active_index_id") or "").strip()
        if not indexes_root or not index_id:
            return []

        manifest_path = os.path.join(indexes_root, index_id, "manifest.json")
        manifest = _load_json_file(manifest_path)
        branches = manifest.get("branches") if isinstance(manifest, dict) else None
        if not isinstance(branches, list):
            return []

        out: List[str] = []
        for b in branches:
            if not isinstance(b, dict):
                continue
            name = str(b.get("branch_name") or "").strip()
            if name:
                out.append(name)

        return sorted(set(out), key=lambda x: x.lower())
    except Exception:
        return []


def _make_history_backend():
    if USE_REDIS:
        return RedisBackend(host=REDIS_HOST, port=REDIS_PORT)
    return InMemoryMockRedis()


class _NullRetriever:
    """
    Safe fallback when unified index can't be loaded at startup.
    It keeps the server running and lets DIRECT-style pipelines work.
    """

    def search(self, query: str, *, top_k: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return []


_history_backend = _make_history_backend()

# --- Core runtime wiring (model/search/translators/logger) ---
_runtime_cfg = _load_runtime_config()

_main_model = Model(_resolve_cfg_path(str(_runtime_cfg.get("model_path_analysis") or "")))

_active_index_id = str(_runtime_cfg.get("active_index_id") or "").strip() or None
_searcher_startup_error: str | None = None
try:
    # IMPORTANT: pass index id positionally to avoid parameter-name drift across versions.
    _searcher = load_unified_search(_active_index_id)
except Exception as ex:
    _searcher = _NullRetriever()
    _searcher_startup_error = str(ex)

_markdown_translator = MarkdownTranslator(_resolve_cfg_path(str(_runtime_cfg.get("model_translation_en_pl") or "")))
_translator_pl_en = Translator(_resolve_cfg_path(str(_runtime_cfg.get("model_translation_pl_en") or "")))

_interaction_logger = InteractionLogger(_resolve_cfg_path(str(_runtime_cfg.get("log_path") or "log/ai_interaction.log")))

_runner = DynamicPipelineRunner(
    pipelines_root=os.path.join(PROJECT_ROOT, "pipelines"),
    main_model=_main_model,
    searcher=_searcher,
    markdown_translator=_markdown_translator,
    translator_pl_en=_translator_pl_en,
    logger=_interaction_logger,
)


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "ok": True,
            "use_redis": USE_REDIS,
            "active_index_id": _active_index_id,
            "searcher_ok": _searcher_startup_error is None,
            "searcher_error": _searcher_startup_error,
        }
    )


@app.route("/app-config", methods=["GET"])
def app_config():
    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    cfg = _load_runtime_config()
    templates = _load_ui_templates()

    repos = _list_repositories()
    repo_name = str(cfg.get("repo_name") or "").strip() or (repos[0] if repos else "")

    # Option A: branches come from active index manifest (source of truth).
    branches = _read_active_index_branches(cfg)

    default_branch = _pick_default_branch(branches, cfg)

    return jsonify(
        {
            "repositories": repos,
            "defaultRepository": repo_name,
            "branches": branches,
            "defaultBranch": default_branch,
            "consultants": templates.get("consultants") if isinstance(templates, dict) else [],
        }
    )


@app.route("/search", methods=["POST"])
def search():
    """
    Single entrypoint (no legacy): dynamic pipeline runner behind POST /search.
    """
    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    cfg = _load_runtime_config()
    templates = _load_ui_templates()

    repo_name = str(cfg.get("repo_name") or "").strip() or "repo"

    branches = _read_active_index_branches(cfg)
    default_branch = _pick_default_branch(branches, cfg)

    # UI sends session in header (X-Session-ID). Support also body fields as fallback.
    session_in = (request.headers.get("X-Session-ID") or "").strip()
    if not session_in:
        session_in = _get_str_field(payload, "session_id", _get_str_field(payload, "sessionId", ""))

    session_id = _valid_session_id(session_in)

    user_id = _valid_user_id(_get_str_field(payload, "user_id", _get_str_field(payload, "userId", "")))

    consultant_id = _get_str_field(payload, "consultant", _get_str_field(payload, "consultantId", ""))
    if not consultant_id:
        return jsonify({"error": "Missing consultant."}), 400

    pipeline_name = _get_str_field(payload, "pipeline_name", _find_pipeline_for_consultant(consultant_id, templates))

    translate_chat = _get_bool_field(payload, "translateChat", False)

    original_query = _get_str_field(payload, "query", _get_str_field(payload, "text", ""))
    if not original_query:
        return jsonify({"error": "Missing query."}), 400
    if len(original_query) > MAX_QUERY_LEN:
        return jsonify({"error": f"Query too long (>{MAX_QUERY_LEN})."}), 400

    branch_a = _get_str_field(payload, "branchA", "") or _get_str_field(payload, "branch", "") or default_branch
    branch_b = _get_str_field(payload, "branchB", "") or ""

    overrides: dict[str, Any] = {}
    if branch_b:
        overrides["branch_b"] = branch_b

    try:
        result = _runner.run(
            user_query=original_query,
            session_id=session_id,
            consultant=consultant_id,
            branch=branch_a,
            translate_chat=translate_chat,
            user_id=user_id,
            pipeline_name=pipeline_name or None,
            repository=repo_name,
            active_index=_active_index_id,
            overrides=(overrides or None),
            mock_redis=_history_backend,
        )
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

    out = _normalize_runner_result(result)
    out["session_id"] = session_id
    if user_id:
        out["user_id"] = user_id
    out["repository"] = repo_name
    out["branch"] = branch_a
    if branch_b:
        out["branchB"] = branch_b
    if pipeline_name:
        out["pipeline_name"] = pipeline_name
    out["consultant"] = consultant_id

    return jsonify(out)
