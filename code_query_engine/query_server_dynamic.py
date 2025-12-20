import os
import json
import re
import uuid
from typing import Any

from flask import Flask, request, jsonify
from flask_cors import CORS

from common.utils import parse_bool
from vector_db.unified_index_loader import load_unified_search
from vector_search.unified_search import UnifiedSearchAdapter

from common.markdown_translator_en_pl import MarkdownTranslator
from common.translator_pl_en import Translator
from history.mock_redis import InMemoryMockRedis
from integrations.plant_uml.plantuml_check import add_plant_link
from code_query_engine.model import Model
from common.logging_setup import configure_logging, InteractionLogger
from code_query_engine.dynamic_pipeline import DynamicPipelineRunner
import constants


# ======================
#  CONFIG / ENV SETUP
# ======================

# Runtime knobs
os.environ["LLAMA_SET_ROWS"] = "1"
script_dir = os.path.dirname(os.path.abspath(__file__))

# Configuration (config.json is one level above /code_query_engine)
config_path = os.path.join(script_dir, "..", "config.json")
with open(config_path, encoding="utf-8") as f:
    cfg = json.load(f)
configure_logging(cfg)
base_dir = os.path.abspath(os.path.join(script_dir, ".."))
MODEL_PATH = os.path.join(base_dir, cfg["model_path_analysis"])
MODEL_TRANSLATION_EN_PL = os.path.join(base_dir, cfg["model_translation_en_pl"])

branch_name = (cfg.get("branch") or "").strip()
output_dir = cfg["output_dir"]
branch_output_dir = os.path.join(output_dir, branch_name) if branch_name else output_dir

# Flask app (dynamic pipeline server)
app = Flask(__name__)

# --- SECURITY ---
secret_key = os.getenv("APP_SECRET_KEY")
if not secret_key:
    # Server can run without it (dev), but warn loudly.
    print("[query_server_dynamic] Warning: APP_SECRET_KEY is not set.")
else:
    app.secret_key = secret_key

API_TOKEN = os.getenv("API_TOKEN")


def _parse_env_list(name: str) -> list[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


ALLOWED_ORIGINS = _parse_env_list("ALLOWED_ORIGINS") or [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "null",
]

CORS(
    app,
    supports_credentials=True,
    resources={r"/*": {"origins": ALLOWED_ORIGINS}},
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Session-ID", "X-Auth-Token", "Authorization"],
)

# Limits (optional)
MAX_QUERY_LEN = int(os.getenv("APP_MAX_QUERY_LEN", "8000"))
MAX_FIELD_LEN = int(os.getenv("APP_MAX_FIELD_LEN", "128"))


def _is_authorized(req) -> bool:
    """Basic token-based authorization check."""
    if not API_TOKEN:
        return True
    header_token = req.headers.get("X-Auth-Token")
    if header_token and header_token == API_TOKEN:
        return True
    auth = req.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        bearer = auth[len("Bearer "):].strip()
        if bearer == API_TOKEN:
            return True
    return False


_SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _has_disallowed_control_chars(s: str) -> bool:
    return bool(_CONTROL_CHARS_RE.search(s or ""))


def _sanitize_or_default(value: str, default: str) -> str:
    v = (value or "").strip()
    if not v:
        return default
    if len(v) > MAX_FIELD_LEN:
        return default
    if _SAFE_SLUG_RE.match(v):
        return v
    return default


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


# ==============
#  MODELS / RAG
# ==============

mock_redis = InMemoryMockRedis()
main_model = Model(MODEL_PATH)
markdown_translator = MarkdownTranslator(MODEL_TRANSLATION_EN_PL)
translator_pl_en = Translator(model_name="Helsinki-NLP/opus-mt-pl-en")
logger = InteractionLogger()

# Unified index loader (FAISS + metadata)
unified_search = load_unified_search()
searcher = UnifiedSearchAdapter(unified_search)

# Dynamic pipeline runner based on YAML
pipelines_dir = os.path.join(base_dir, "pipelines")
dynamic_runner = DynamicPipelineRunner(
    pipelines_dir=pipelines_dir,
    main_model=main_model,
    searcher=searcher,
    markdown_translator=markdown_translator,
    translator_pl_en=translator_pl_en,
    logger=logger,
)

# Session memory (future use)
user_contexts: dict[str, list[dict[str, Any]]] = {}


# ==================
#  ENDPOINTS
# ==================

@app.route("/search", methods=["POST", "OPTIONS"])
@app.route("/dynamic/search", methods=["POST", "OPTIONS"])
def dynamic_search() -> Any:
    """Main RAG endpoint (canonical: /search). /dynamic/search is an alias."""
    if request.method == "OPTIONS":
        return ("", 204)

    if not _is_authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    original_query = body.get("query")

    if original_query is None:
        return jsonify({"error": "Query cannot be empty."}), 400
    if not isinstance(original_query, str):
        return jsonify({"error": "Query must be a string."}), 400

    original_query = original_query.strip()
    if len(original_query) == 0:
        return jsonify({"error": "Query cannot be empty."}), 400
    if len(original_query) > MAX_QUERY_LEN:
        return jsonify({"error": f"Query too long (>{MAX_QUERY_LEN})."}), 400
    if _has_disallowed_control_chars(original_query):
        return jsonify({"error": "Query contains disallowed control characters."}), 400

    consultant_raw = body.get("consultant") or ""
    branch_raw = body.get("branch") or "stable"
    translate_chat = parse_bool(body.get("translateChat"), default=False)

    consultant = _sanitize_or_default(consultant_raw.strip(), default="general")
    branch = _sanitize_or_default(branch_raw.strip(), default="stable")

    session_id = _valid_session_id(request.headers.get("X-Session-ID"))
    user_contexts.setdefault(session_id, [])

    try:
        result, query_type, steps_used, model_input_en = dynamic_runner.run(
            original_query,
            session_id=session_id,
            consultant=consultant,
            branch=branch,
            translate_chat=translate_chat,
            mock_redis=mock_redis,
        )
    except FileNotFoundError as fnf:
        return jsonify({"error": "Pipeline not found for consultant.", "details": str(fnf)}), 400
    except Exception as ex:
        return jsonify({"error": "Internal error during search.", "details": str(ex)}), 500

    # NOTE: pipeline already decides translation behavior for most flows;
    # keep this only if your pipeline returns EN answers when translateChat=true.
    if translate_chat and consultant != constants.UML_CONSULTANT and isinstance(result, str) and result:
        result = markdown_translator.translate_markdown(result)

    if consultant == constants.UML_CONSULTANT and isinstance(result, str):
        result = add_plant_link(result, consultant)

    return jsonify(
        {
            "results": result,
            "translated": model_input_en,
            "query_type": query_type,
            "session_id": session_id,
            "steps_used": steps_used,
        }
    )


@app.route("/branch", methods=["GET"])
@app.route("/dynamic/branch", methods=["GET"])
def dynamic_get_branch() -> Any:
    """Return configured branch name from config.json (canonical: /branch)."""
    return jsonify({"branch": cfg.get("branch", "")})


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "5001"))
    app.run(host=host, port=port)
