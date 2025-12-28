import os
import re
import uuid
import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request
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


def _valid_repo_or_branch(value: str, *, field: str) -> str:
    v = (value or "").strip()
    if not v:
        raise ValueError(f"Missing required field '{field}'.")
    v = v[:MAX_FIELD_LEN]
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
        raise ValueError(f"Invalid '{field}'.")
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


def _get_int_field(payload: Dict[str, Any], key: str, default: int) -> int:
    v = payload.get(key, default)
    try:
        return int(v)
    except Exception:
        return int(default)


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


def _is_valid_branch_dir(branch_dir: str, branch_name: str) -> bool:
    """
    Validate if a branch directory is an extracted branch bundle:
    - must be a directory
    - must contain at least one of known marker files
    """
    full = os.path.join(branch_dir, branch_name)
    if not os.path.isdir(full):
        return False

    # Common marker files in extracted bundles
    markers = ["_manifest.json", "manifest.json", "repo_manifest.json", "graph.json", "nodes.csv"]
    for m in markers:
        if os.path.exists(os.path.join(full, m)):
            return True

    # Or any jsonl/sql_bodies etc (best-effort)
    for m in ["sql_bodies.jsonl", "cs_bodies.jsonl", "bodies.jsonl"]:
        if os.path.exists(os.path.join(full, m)):
            return True

    return False


def _list_branches(repository: str) -> List[str]:
    branch_root = os.path.join(REPOSITORIES_ROOT, repository, "branches")
    try:
        out: List[str] = []
        if not os.path.isdir(branch_root):
            return out

        for name in os.listdir(branch_root):
            # Ignore accidental folders that are not extracted branch bundles
            if not _is_valid_branch_dir(branch_root, name):
                continue
            out.append(name)

        out.sort(key=lambda x: x.lower())
        return out
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

    branches = _list_branches(repo_name) if repo_name else []
    default_branch = _pick_default_branch(branches, cfg)

    # Return only what UI needs; keep it stable for the mock/server combo
    return jsonify(
        {
            "repositories": repos,
            "defaultRepository": repo_name,
            "branches": branches,
            "defaultBranch": default_branch,
            "consultants": templates.get("consultants") if isinstance(templates, dict) else [],
        }
    )


@app.route("/query", methods=["POST"])
@app.route("/search", methods=["POST"])
def query_legacy():
    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    cfg = _load_runtime_config()
    templates = _load_ui_templates()

    repo_name = str(cfg.get("repo_name") or "").strip() or "repo"
    branches = _list_branches(repo_name)
    default_branch = _pick_default_branch(branches, cfg)

    session_id = _valid_session_id(_get_str_field(payload, "session_id", _get_str_field(payload, "sessionId", "")))
    user_id = _valid_user_id(_get_str_field(payload, "user_id", _get_str_field(payload, "userId", "")))

    consultant_id = _get_str_field(payload, "consultant", _get_str_field(payload, "consultantId", ""))
    pipeline_name = _get_str_field(payload, "pipeline_name", _find_pipeline_for_consultant(consultant_id, templates))

    translate_chat = _get_bool_field(payload, "translateChat", False)

    original_query = _get_str_field(payload, "query", _get_str_field(payload, "text", ""))
    if not original_query:
        return jsonify({"error": "Missing query."}), 400
    if len(original_query) > MAX_QUERY_LEN:
        return jsonify({"error": f"Query too long (>{MAX_QUERY_LEN})."}), 400

    branch_a = _get_str_field(payload, "branchA", "") or _get_str_field(payload, "branch", "") or default_branch

    try:
        result = _runner.run(
            user_query=original_query,
            session_id=session_id,
            user_id=user_id,
            repository=repo_name,
            branch=branch_a,
            pipeline_name=pipeline_name or None,
            translate_chat=translate_chat,
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
    if pipeline_name:
        out["pipeline_name"] = pipeline_name
    out["consultant"] = consultant_id

    return jsonify(out)


@app.route("/list-repos", methods=["GET"])
def list_repos():
    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"repositories": _list_repositories()})


@app.route("/list-branches/<repo>", methods=["GET"])
def list_repo_branches(repo: str):
    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401
    repo_name = _valid_repo_or_branch(repo, field="repository")
    return jsonify({"repository": repo_name, "branches": _list_branches(repo_name)})


@app.route("/query-v2", methods=["POST"])
def query():
    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    cfg = _load_runtime_config()
    templates = _load_ui_templates()

    repo_name = str(cfg.get("repo_name") or "").strip() or "repo"
    branches = _list_branches(repo_name)
    default_branch = _pick_default_branch(branches, cfg)

    session_id = _valid_session_id(_get_str_field(payload, "session_id", _get_str_field(payload, "sessionId", "")))
    user_id = _valid_user_id(_get_str_field(payload, "user_id", _get_str_field(payload, "userId", "")))

    consultant_id = _get_str_field(payload, "consultant", _get_str_field(payload, "consultantId", ""))
    pipeline_name = _get_str_field(payload, "pipeline_name", _find_pipeline_for_consultant(consultant_id, templates))

    translate_chat = _get_bool_field(payload, "translateChat", False)

    original_query = _get_str_field(payload, "query", "")
    if not original_query:
        return jsonify({"error": "Missing query."}), 400
    if len(original_query) > MAX_QUERY_LEN:
        return jsonify({"error": f"Query too long (>{MAX_QUERY_LEN})."}), 400

    branch_a = _get_str_field(payload, "branchA", "") or _get_str_field(payload, "branch", "") or default_branch

    try:
        result = _runner.run(
            user_query=original_query,
            session_id=session_id,
            user_id=user_id,
            repository=repo_name,
            branch=branch_a,
            pipeline_name=pipeline_name or None,
            translate_chat=translate_chat,
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
    if pipeline_name:
        out["pipeline_name"] = pipeline_name
    out["consultant"] = consultant_id

    return jsonify(out)
