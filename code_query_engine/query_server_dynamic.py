import os
import json
import re
import uuid
from typing import Any

import torch
from flask import Flask, request, jsonify
from flask_cors import CORS
from sentence_transformers import SentenceTransformer

from common.semantic_keyword_rerank_search import SemanticKeywordRerankSearch
from common.utils import parse_bool
from common.search_engine import index, metadata, chunks, dependencies
from common.markdown_translator_en_pl import MarkdownTranslator
from common.translator_pl_en import Translator
from history.history_manager import HistoryManager
from history.mock_redis import InMemoryMockRedis
from integrations.plant_uml.plantuml_check import add_plant_link
from code_query_engine.model import Model
from code_query_engine.log_utils import InteractionLogger
from code_query_engine.dynamic_pipeline import DynamicPipelineRunner
import constants


# ======================
#  CONFIG / ENV SETUP
# ======================

# Runtime knobs
os.environ["LLAMA_SET_ROWS"] = "1"
script_dir = os.path.dirname(os.path.abspath(__file__))

# Configuration
config_path = os.path.join(script_dir, "..", "config.json")
with open(config_path, encoding="utf-8") as f:
    cfg = json.load(f)

base_dir = os.path.abspath(os.path.join(script_dir, ".."))
MODEL_PATH = os.path.join(base_dir, cfg["model_path_analysis"])
EMBED_MODEL_PATH = os.path.join(base_dir, cfg["model_path_embd"])
MODEL_TRANSLATION_EN_PL = os.path.join(base_dir, cfg["model_translation_en_pl"])

branch_name = (cfg.get("branch") or "").strip()
output_dir = cfg["output_dir"]
branch_output_dir = os.path.join(output_dir, branch_name) if branch_name else output_dir

METADATA_PATH = os.path.join(base_dir, branch_output_dir, "metadata.json")

# Flask app (dynamic pipeline server)
app = Flask(__name__)

# --- SECURITY ---
secret_key = os.getenv("APP_SECRET_KEY")
if not secret_key:
    raise RuntimeError(
        "Missing APP_SECRET_KEY environment variable. "
        "For security reasons, the secret key must be provided via environment."
    )
app.secret_key = secret_key


def _parse_env_list(var_name: str):
    raw = os.getenv(var_name)
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


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

API_TOKEN = os.getenv("API_TOKEN")


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


# Input validation defaults
MAX_QUERY_LEN = int(os.getenv("APP_MAX_QUERY_LEN", "8000"))
MAX_FIELD_LEN = int(os.getenv("APP_MAX_FIELD_LEN", "128"))

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _has_disallowed_control_chars(s: str) -> bool:
    """Return True if string contains dangerous control chars."""
    return bool(_CONTROL_CHARS_RE.search(s))


_SAFE_SLUG_RE = re.compile(r"^[\w\-.]{1,128}$", re.UNICODE)


def _sanitize_or_default(text: str, default: str, max_len: int = MAX_FIELD_LEN) -> str:
    """Sanitize simple slug-like values (consultant, branch, etc.)."""
    text = (text or "").strip()
    if not text or len(text) > max_len or not _SAFE_SLUG_RE.match(text):
        return default
    return text


def _valid_session_id(value: str) -> str:
    """Validate session id or generate a new UUID."""
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

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

mock_redis = InMemoryMockRedis()
main_model = Model(MODEL_PATH)
embed_model = SentenceTransformer(EMBED_MODEL_PATH).to(device)
markdown_translator = MarkdownTranslator(MODEL_TRANSLATION_EN_PL)
translator_pl_en = Translator(model_name="Helsinki-NLP/opus-mt-pl-en")
logger = InteractionLogger.instance()

searcher = SemanticKeywordRerankSearch(
    index=index,
    metadata=metadata,
    chunks=chunks,
    dependencies=dependencies,
    embed_model=embed_model,
)

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
user_contexts: dict[str, list[str]] = {}


# ==================
#   API ENDPOINTS
# ==================

@app.route("/dynamic/search", methods=["POST", "OPTIONS"])
def dynamic_search() -> Any:
    """Search endpoint using YAML-driven dynamic pipeline."""
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
        return jsonify(
            {"error": "Pipeline not found for consultant.", "details": str(fnf)}
        ), 400
    except Exception as ex:
        return jsonify(
            {"error": "Internal error during search.", "details": str(ex)}
        ), 500

    if consultant == constants.UML_CONSULTANT:
        result = add_plant_link(result, consultant)

    return jsonify(
        {
            "results": result,
            "session_id": session_id,
            "translated": model_input_en,
            "query_type": query_type,
            "steps_used": steps_used,
        }
    )


@app.route("/dynamic/branch", methods=["GET"])
def dynamic_get_branch() -> Any:
    """Return configured branch name from config.json (dynamic server)."""
    return jsonify({"branch": cfg.get("branch", "")})


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "5001"))  
    app.run(host=host, port=port)
