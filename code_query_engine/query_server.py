import os
import json
import re
import uuid
from typing import Any, Dict, List

from common.semantic_keyword_rerank_search import SemanticKeywordRerankSearch
from common.utils import extract_followup, parse_bool
import torch
from flask import Flask, request, jsonify
from flask_cors import CORS
from sentence_transformers import SentenceTransformer

from code_query_engine.model import Model
from history.history_manager import HistoryManager
from history.mock_redis import InMemoryMockRedis
from integrations.plant_uml.plantuml_check import add_plant_link
from common.search_engine import query_faiss, format_results_as_text
from common.markdown_translator_en_pl import MarkdownTranslator
from common.translator_pl_en import Translator
import constants
from .log_utils import InteractionLogger
from common.search_engine import index, metadata, chunks, dependencies
from dotnet_sumarizer.code_compressor import compress_chunks

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
MODEL_TRANSLATION_EN_PL = os.path.join(base_dir, cfg["model_translation_en_pl"])  # corrected key in config

branch_name = (cfg.get("branch") or "").strip()
output_dir = cfg["output_dir"]
branch_output_dir = os.path.join(output_dir, branch_name) if branch_name else output_dir

METADATA_PATH = os.path.join(base_dir, branch_output_dir, "metadata.json")

# Flask app
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
    return bool(_CONTROL_CHARS_RE.search(s))


_SAFE_SLUG_RE = re.compile(r"^[\w\-.]{1,128}$", re.UNICODE)


def _sanitize_or_default(text: str, default: str, max_len: int = MAX_FIELD_LEN) -> str:
    text = (text or "").strip()
    if not text or len(text) > max_len or not _SAFE_SLUG_RE.match(text):
        return default
    return text


def _valid_session_id(value: str) -> str:
    v = (value or "").strip()
    if _SAFE_SLUG_RE.match(v):
        return v
    try:
        uuid.UUID(v)
        return v
    except Exception:
        return str(uuid.uuid4())


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Models
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


# === Helper: FAISS → compressed context ===
def build_compressed_context_from_faiss(
    followup: str,
    searcher: Any,
    history_manager: Any,
    *,
    top_k: int = 5,
    mode: str = "snippets",
    token_budget: int = 1200,
    window: int = 18,
    max_chunks: int = 8,
    language: str = "csharp",
    per_chunk_hard_cap: int = 240,
    include_related: bool = True,
) -> str:
    """FAISS search → compressed context string."""
    faiss_results = searcher.search(followup, top_k=top_k) or []
    try:
        history_manager.add_iteration(followup, faiss_results)
    except Exception:
        # History must never break the main flow
        pass

    source_chunks: List[Dict[str, Any]] = []
    for r in faiss_results:
        if not r:
            continue
        source_chunks.append({
            "path": r.get("File") or r.get("path"),
            "content": r.get("Content") or r.get("content") or "",
            "member": r.get("Member") or r.get("member"),
            "namespace": r.get("Namespace") or r.get("namespace"),
            "class": r.get("Class") or r.get("class"),
            "hit_lines": r.get("HitLines") or r.get("hit_lines"),
            "rank": r.get("Rank"),
            "distance": r.get("Distance"),
        })
        if include_related:
            for rel in (r.get("Related") or []):
                source_chunks.append({
                    "path": rel.get("File") or rel.get("path"),
                    "content": rel.get("Content") or rel.get("content") or "",
                    "member": rel.get("Member") or rel.get("member"),
                    "namespace": rel.get("Namespace") or rel.get("namespace"),
                    "class": rel.get("Class") or rel.get("class"),
                    "hit_lines": rel.get("HitLines") or rel.get("hit_lines"),
                    "rank": 999,
                    "distance": 1.0,
                })

    # ------- FAISS debug logging (before compression) -------
    try:
        debug_payload = {
            "followup": followup,
            "top_k": top_k,
            "mode": mode,
            "token_budget": token_budget,
            "window": window,
            "max_chunks": max_chunks,
            "language": language,
            "per_chunk_hard_cap": per_chunk_hard_cap,
            "include_related": include_related,
            "source_chunks": source_chunks,
        }
        # NOTE: using the shared InteractionLogger instance's underlying logger
        logger.logger.info(
            "FAISS debug - input for compression:\n%s",
            json.dumps(debug_payload, ensure_ascii=False, indent=2),
        )
    except Exception:
        # Logging must never break the main flow
        pass
    # --------------------------------------------------------

    context_text = compress_chunks(
        source_chunks,
        mode=mode,
        token_budget=token_budget,
        window=window,
        max_chunks=max_chunks,
        language=language,
        per_chunk_hard_cap=per_chunk_hard_cap,
    )
    return context_text




# Session memory (future use)
user_contexts = {}


@app.route("/branch", methods=["GET"])
def get_branch():
    return jsonify({"branch": cfg.get("branch", "")})


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "5000"))
    app.run(host=host, port=port)
