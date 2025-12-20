import os
import re
import uuid
from typing import Any, Dict, Optional, Tuple

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

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "null",
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


def _get_bool_field(payload: Dict[str, Any], key: str, default: bool = False) -> bool:
    v = payload.get(key, default)
    return bool(v)


def _get_str_field(payload: Dict[str, Any], key: str, default: str = "") -> str:
    v = payload.get(key, default)
    if v is None:
        return default
    s = str(v)
    if len(s) > MAX_QUERY_LEN and key == "query":
        return s[:MAX_QUERY_LEN]
    if len(s) > MAX_FIELD_LEN and key != "query":
        return s[:MAX_FIELD_LEN]
    return s


def _build_runner() -> DynamicPipelineRunner:
    pipelines_root = os.getenv("PIPELINES_ROOT", "pipelines")
    return DynamicPipelineRunner(
        pipelines_root=pipelines_root,
        main_model=None,   # wired by runtime config in real deployment
        searcher=None,     # wired by runtime config in real deployment
        markdown_translator=None,
        translator_pl_en=None,
        logger=None,
        allow_test_pipelines=False,
    )


def _build_history_backend():
    if USE_REDIS:
        return RedisBackend(host=REDIS_HOST, port=REDIS_PORT)
    return InMemoryMockRedis()


runner = _build_runner()
mock_redis = _build_history_backend()

# Optional local per-session cache (kept as-is)
user_contexts: Dict[str, list[str]] = {}


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "use_redis": USE_REDIS})


@app.route("/query", methods=["POST", "OPTIONS"])
def query():
    if request.method == "OPTIONS":
        return ("", 204)

    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}

    original_query = _get_str_field(payload, "query", "")
    consultant = _get_str_field(payload, "consultant", "rejewski")
    branch = _get_str_field(payload, "branch", "develop")
    translate_chat = _get_bool_field(payload, "translate_chat", False)

    if not original_query.strip():
        return jsonify({"error": "Empty query"}), 400

    session_id = _valid_session_id(request.headers.get("X-Session-ID"))
    user_id = _valid_user_id(request.headers.get("X-User-ID"))
    user_contexts.setdefault(session_id, [])

    try:
        result, query_type, steps_used, model_input_en = runner.run(
            original_query,
            session_id=session_id,
            user_id=user_id,
            consultant=consultant,
            branch=branch,
            translate_chat=translate_chat,
            mock_redis=mock_redis,
        )
    except FileNotFoundError as ex:
        return jsonify({"error": str(ex)}), 404
    except PermissionError as ex:
        return jsonify({"error": str(ex)}), 403
    except Exception as ex:
        return jsonify({"error": f"Server error: {ex}"}), 500

    return jsonify(
        {
            "session_id": session_id,
            "user_id": user_id,
            "query_type": query_type,
            "steps_used": steps_used,
            "model_input_en": model_input_en,
            "result": result,
        }
    )
