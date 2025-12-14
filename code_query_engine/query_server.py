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


# === Main search logic ===
def search_logic(query: str, translate_chat: bool, session_id: str, consultant: str, branch: str):
    max_steps = 8
    do_not_translate = not translate_chat
    followup = None
    answer = None
    used = set()
    context_blocks = []
    steps_used = 0
    query_type = "unknown"
    response = None
    history_manager = HistoryManager(mock_redis, session_id)
    context_blocks = history_manager.get_context_blocks()
    current = query

    model_input_en = translator_pl_en.translate(query) if translate_chat else query
    history_manager.start_user_query(model_input_en, query)

    for step in range(max_steps):
        steps_used = step + 1
        context_str = "\n---\n".join(context_blocks)
        print(f"Debug: Step {steps_used} - Prompt: {current[:200]}...")
        response = main_model.ask(context_str, model_input_en, consultant)
        print(f"Debug: Step {steps_used} - LLM: {response[:200]}...")

        if response.startswith(constants.ANSWER_PREFIX):
            answer = response.replace(constants.ANSWER_PREFIX, "").strip()
            query_type = "direct answer"
            break
        elif not response.startswith(constants.FOLLOWUP_PREFIX):
            cleaned = response.strip()
            if len(cleaned) > 20:
                answer = cleaned
                query_type = "direct answer (heuristic)"
                break

        match = re.search(rf"{constants.FOLLOWUP_PREFIX}\s*(.+)", response)
        if match:
            followup = extract_followup(response)
            print(f"Debug: Step {steps_used} - Follow-up query: {followup}")

            if followup in used:
                answer = (
                    "Proces przerwany. Model powtarza te same pytania do FaissDB. "
                    "Spróbuj zadać pytanie inaczej."
                )
                query_type = "abort: repeated query"
                do_not_translate = True
                break

            used.add(followup)

            context_text = build_compressed_context_from_faiss(
                followup, searcher, history_manager,
                top_k=5, mode="snippets", token_budget=1200,
                window=18, max_chunks=8, language="csharp",
                per_chunk_hard_cap=240, include_related=True,
            )
            context_blocks.append(context_text)
            current = query
            query_type = "vector query"

            logger.log_interaction(
                original_question=query,
                model_input_en=model_input_en,
                codellama_response=response,
                followup_query=followup,
                query_type=query_type,
                final_answer=answer,
                context_blocks=context_blocks,
                next_codellama_prompt=current,
            )
        else:
            answer = "Unrecognized response from model."
            query_type = "fallback error"
            break

    # === Final answer logging ===
    if answer is not None:
        logger.log_interaction(
            original_question=query,
            model_input_en=model_input_en,
            codellama_response=response,
            followup_query=followup,
            query_type=query_type,
            final_answer=answer,
            context_blocks=context_blocks,
            next_codellama_prompt=current,
        )

        if (not do_not_translate) and (consultant != constants.UML_CONSULTANT):
            answer_pl = markdown_translator.translate_markdown(answer)
            final_answer = answer_pl
        else:
            answer_pl = None
            final_answer = answer

        history_manager.set_final_answer(answer, answer_pl)
        final_answer = add_plant_link(final_answer, consultant)

        return final_answer, query_type, steps_used, model_input_en

    # Error path
    logger.log_interaction(
        original_question=query,
        model_input_en=model_input_en,
        codellama_response=response,
        followup_query=followup,
        query_type=query_type,
        final_answer=answer,
        context_blocks=context_blocks,
        next_codellama_prompt=current,
    )
    return "Error: No valid response generated.", "error", steps_used, model_input_en


# Session memory (future use)
user_contexts = {}


# === API endpoints ===
@app.route('/search', methods=['POST', 'OPTIONS'])
def search():
    if request.method == 'OPTIONS':
        return ('', 204)

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
        result, query_type, steps_used, model_input_en = search_logic(
            original_query, translate_chat, session_id, consultant, branch
        )
    except Exception as ex:
        return jsonify({"error": "Internal error during search.", "details": str(ex)}), 500

    return jsonify({
        "results": result,
        "session_id": session_id,
        "translated": model_input_en,
        "query_type": query_type,
        "steps_used": steps_used
    })


@app.route("/branch", methods=["GET"])
def get_branch():
    return jsonify({"branch": cfg.get("branch", "")})


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "5000"))
    app.run(host=host, port=port)
