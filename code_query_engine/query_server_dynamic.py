# File: code_query_engine/query_server_dynamic.py
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

from history.mock_redis import InMemoryMockRedis
from history.redis_backend import RedisBackend

from .dynamic_pipeline import DynamicPipelineRunner


# Load .env if present
load_dotenv()

API_TOKEN = os.getenv("API_TOKEN", "").strip()

# If set to "true", use Redis history backend; otherwise use in-memory mock
USE_REDIS = os.getenv("APP_USE_REDIS", "false").strip().lower() == "true"

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Repositories root for listing repositories/branches (used by UI)
REPOSITORIES_ROOT = os.path.abspath(os.getenv("REPOSITORIES_ROOT", "repositories"))

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app = Flask(__name__)

# CORS (session id header + optional user id header)
CORS(
    app,
    supports_credentials=True,
    resources={r"/*": {"origins": ALLOWED_ORIGINS}},
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Session-ID", "X-User-ID", "X-Auth-Token", "Authorization"],
)

# Limits (optional)
MAX_QUERY_LEN = int(os.getenv("APP_MAX_QUERY_LEN", "8000"))
MAX_FIELD_LEN = int(os.getenv("APP_MAX_FIELD_LEN", "128"))


def _is_authorized(req) -> bool:
    """Basic token-based authorization check."""
    if not API_TOKEN:
        return True  # token disabled
    auth = (req.headers.get("Authorization") or "").strip()
    token = (req.headers.get("X-Auth-Token") or "").strip()
    if auth.startswith("Bearer "):
        auth = auth[len("Bearer ") :].strip()
    return (auth == API_TOKEN) or (token == API_TOKEN)


_SAFE_SLUG_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")
# Repository/branch names are folder names; allow dot and plus (e.g. Release_4.90, release_490+release_460)
_SAFE_REPO_BRANCH_RE = re.compile(r"^[a-zA-Z0-9_\-\.\+]{1,128}$")


def _valid_session_id(value: str | None) -> str:
    """
    If client does not send X-Session-ID, we generate one.
    IMPORTANT: client must persist and resend it, otherwise history will reset.
    """
    v = (value or "").strip()
    if _SAFE_SLUG_RE.match(v):
        return v
    try:
        uuid.UUID(v)
        return v
    except Exception:
        return str(uuid.uuid4())


def _valid_user_id(value: str | None) -> str | None:
    """Validate optional X-User-ID. Returns None if missing/invalid."""
    v = (value or "").strip()
    if not v:
        return None
    if _SAFE_SLUG_RE.match(v):
        return v
    try:
        uuid.UUID(v)
        return v
    except Exception:
        return None


def _valid_repo_or_branch(value: str, *, field: str) -> str:
    """Validate repository/branch name used as a directory name (no path separators)."""
    v = (value or "").strip()
    if not v:
        raise ValueError(f"Missing required '{field}'.")
    if "/" in v or "\\" in v:
        raise ValueError(f"Invalid '{field}': path separators are not allowed.")
    if not _SAFE_REPO_BRANCH_RE.match(v):
        raise ValueError(
            f"Invalid '{field}': allowed chars are letters, digits, '_', '-', '.', '+'. Max 128."
        )
    return v


def _get_str_field(payload: Dict[str, Any], key: str, default: str = "") -> str:
    v = payload.get(key, default)
    if v is None:
        return default
    s = str(v)
    if len(s) > MAX_FIELD_LEN:
        s = s[:MAX_FIELD_LEN]
    return s.strip()


def _get_bool_field(payload: Dict[str, Any], key: str, default: bool = False) -> bool:
    v = payload.get(key, default)
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _get_int_field(payload: Dict[str, Any], key: str, default: int) -> int:
    v = payload.get(key, default)
    try:
        return int(v)
    except Exception:
        return default


def _list_repositories() -> List[str]:
    """List repository directory names under REPOSITORIES_ROOT."""
    root = REPOSITORIES_ROOT
    if not os.path.isdir(root):
        return []
    out: List[str] = []
    for name in os.listdir(root):
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue
        if name.startswith("."):
            continue
        out.append(name)
    out.sort(key=lambda x: x.lower())
    return out


def _is_valid_branch_dir(branch_dir: str, branch_name: str) -> bool:
    """
    A branch is considered 'available' if it looks like an extracted bundle.
    Supports both layouts:
      branches/<branch>/regular_code_bundle/...
      branches/<branch>/<branch>/regular_code_bundle/...  (legacy nested)
    Also accepts SQL-only branches (sql_bundle or sql_code_bundle).
    """
    if not os.path.isdir(branch_dir):
        return False

    direct_code = os.path.join(branch_dir, "regular_code_bundle")
    nested_root = os.path.join(branch_dir, branch_name)
    nested_code = os.path.join(nested_root, "regular_code_bundle")

    direct_sql = os.path.join(branch_dir, "sql_bundle")
    nested_sql = os.path.join(nested_root, "sql_bundle")

    direct_sql_legacy = os.path.join(branch_dir, "sql_code_bundle")
    nested_sql_legacy = os.path.join(nested_root, "sql_code_bundle")

    return (
        os.path.isdir(direct_code)
        or os.path.isdir(nested_code)
        or os.path.isdir(direct_sql)
        or os.path.isdir(nested_sql)
        or os.path.isdir(direct_sql_legacy)
        or os.path.isdir(nested_sql_legacy)
    )


def _list_branches(repository: str) -> List[str]:
    """List extracted branch directory names under repositories/<repo>/branches."""
    repo_root = os.path.join(REPOSITORIES_ROOT, repository)
    branches_root = os.path.join(repo_root, "branches")
    if not os.path.isdir(branches_root):
        return []

    out: List[str] = []
    for name in os.listdir(branches_root):
        full = os.path.join(branches_root, name)
        if not os.path.isdir(full):
            continue
        if name.startswith("."):
            continue
        # Ignore accidental folders that are not extracted branch bundles
        if not _is_valid_branch_dir(full, name):
            continue
        out.append(name)

    out.sort(key=lambda x: x.lower())
    return out


def _make_history_backend():
    if USE_REDIS:
        return RedisBackend(host=REDIS_HOST, port=REDIS_PORT)
    return InMemoryMockRedis()


_history_backend = _make_history_backend()
_runner = DynamicPipelineRunner(history_backend=_history_backend)


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "ok": True,
            "use_redis": USE_REDIS,
            "repositories_root": REPOSITORIES_ROOT,
        }
    )


@app.route("/repos", methods=["GET"])
def list_repos():
    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"repositories": _list_repositories()})


@app.route("/repos/<repo>/branches", methods=["GET"])
def list_repo_branches(repo: str):
    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        repo_name = _valid_repo_or_branch(repo, field="repository")
    except Exception as ex:
        return jsonify({"error": str(ex)}), 400

    return jsonify(
        {
            "repository": repo_name,
            "branches": _list_branches(repo_name),
        }
    )


@app.route("/query", methods=["POST", "OPTIONS"])
def query():
    if request.method == "OPTIONS":
        return ("", 204)

    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    session_id = _valid_session_id(request.headers.get("X-Session-ID"))
    user_id = _valid_user_id(request.headers.get("X-User-ID"))

    payload = request.get_json(silent=True) or {}

    # Required: repository + branch (for all searches and graph back-search scoping).
    try:
        repository = _valid_repo_or_branch(_get_str_field(payload, "repository", ""), field="repository")
        branch = _valid_repo_or_branch(_get_str_field(payload, "branch", ""), field="branch")
    except Exception as ex:
        return jsonify({"error": str(ex)}), 400

    original_query = _get_str_field(payload, "query", "")
    if not original_query:
        return jsonify({"error": "Missing query."}), 400
    if len(original_query) > MAX_QUERY_LEN:
        return jsonify({"error": f"Query too long (>{MAX_QUERY_LEN})."}), 400

    active_index = _get_str_field(payload, "active_index", "")
    pipeline_name = _get_str_field(payload, "pipeline_name", "")
    translate_chat = _get_bool_field(payload, "translate_chat", False)

    # Optional overrides (if caller wants)
    top_k = _get_int_field(payload, "top_k", 10)

    try:
        result = _runner.run(
            user_query=original_query,
            session_id=session_id,
            user_id=user_id,
            repository=repository,
            branch=branch,
            active_index=active_index or None,
            pipeline_name=pipeline_name or None,
            translate_chat=translate_chat,
            overrides={"top_k": top_k},
        )
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

    # Ensure session id is returned so client can persist it.
    result_out = dict(result or {})
    result_out["session_id"] = session_id
    if user_id:
        result_out["user_id"] = user_id
    result_out["repository"] = repository
    result_out["branch"] = branch
    if active_index:
        result_out["active_index"] = active_index

    return jsonify(result_out)
