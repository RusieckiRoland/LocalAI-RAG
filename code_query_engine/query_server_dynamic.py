from __future__ import annotations

import logging
import ast
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from common.logging_setup import LoggingConfig, configure_logging, logging_config_from_runtime_config
from common.markdown_translator_en_pl import MarkdownTranslator
from common.translator_pl_en import Translator

from vector_db.semantic_searcher import load_semantic_search
from vector_db.bm25_searcher import load_bm25_search

from .dynamic_pipeline import DynamicPipelineRunner
from history.redis_backend import RedisBackend
from history.mock_redis import InMemoryMockRedis
from .log_utils import InteractionLogger

py_logger = logging.getLogger(__name__)

_logged_branch_literal_eval_error = False


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


# ------------------------------------------------------------
# Logging (source of truth: config.json)
# ------------------------------------------------------------

_logging_cfg = logging_config_from_runtime_config(_runtime_cfg)
configure_logging(_logging_cfg)


# ------------------------------------------------------------
# History backend (Redis / mock)
# ------------------------------------------------------------

def _make_history_backend() -> Any:
    use_redis = (os.getenv("APP_USE_REDIS") or "").strip().lower() in ("1", "true", "yes", "y", "on")
    if not use_redis:
        return InMemoryMockRedis()
    return RedisBackend()


_history_backend = _make_history_backend()


# ------------------------------------------------------------
# Searchers (Semantic + BM25)
# ------------------------------------------------------------

_active_index_id = str(_runtime_cfg.get("active_index_id") or "").strip()

_semantic_searcher = None
_semantic_searcher_error: Optional[str] = None

_bm25_searcher = None
_bm25_searcher_error: Optional[str] = None

try:
    # SemanticSearcher implements IRetriever-like contract:
    #   search(query, top_k, filters=...)
    _semantic_searcher = load_semantic_search(_active_index_id or None)
except Exception as e:
    py_logger.exception("soft-failure: load_semantic_search failed; semantic retrieval will be disabled (fallback mode)")
    _semantic_searcher = None
    _semantic_searcher_error = str(e)

try:
    # BM25Searcher implements IRetriever-like contract:
    #   search(query, top_k, filters=...)
    _bm25_searcher = load_bm25_search(_active_index_id or None)
except Exception as e:
    py_logger.exception("soft-failure: load_bm25_search failed; bm25 retrieval will be disabled (fallback mode)")
    _bm25_searcher = None
    _bm25_searcher_error = str(e)


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


# NOTE: your Model wrapper is outside the uploaded set; keep as-is in repo.
from .model import Model  # noqa: E402


_model = Model(_resolve_cfg_path(str(_runtime_cfg.get("model_path_analysis") or "")))
_markdown_translator = MarkdownTranslator(_resolve_cfg_path(str(_runtime_cfg.get("model_translation_en_pl") or "")))
_translator_pl_en = Translator(_resolve_cfg_path(str(_runtime_cfg.get("model_translation_pl_en") or "")))

_interaction_logger = InteractionLogger(cfg=_logging_cfg)

_runner = DynamicPipelineRunner(
    pipelines_root=os.path.join(PROJECT_ROOT, "pipelines"),
    model=_model,
    searcher=_semantic_searcher,
    bm25_searcher=_bm25_searcher,
    markdown_translator=_markdown_translator,
    translator_pl_en=_translator_pl_en,
    logger=_interaction_logger,
)


# ------------------------------------------------------------
# Flask app
# ------------------------------------------------------------

app = Flask(__name__)
CORS(app, origins=ALLOWED_ORIGINS)


def _auth_ok() -> bool:
    if not API_TOKEN:
        return True
    hdr = (request.headers.get("Authorization") or "").strip()
    return hdr == f"Bearer {API_TOKEN}"


@app.route("/health", methods=["GET"])
def health():
    # Keep backward-compatible keys for existing tests/UI:
    # - searcher_ok/searcher_error reflect the semantic searcher (the "default" retriever).
    return jsonify(
        {
            "ok": True,
            "active_index_id": _active_index_id,
            # Backward-compat (tests expect these keys)
            "searcher_ok": _semantic_searcher is not None,
            "searcher_error": _semantic_searcher_error,
            # Clearer, explicit status
            "semantic_ok": _semantic_searcher is not None,
            "semantic_error": _semantic_searcher_error,
            "bm25_ok": _bm25_searcher is not None,
            "bm25_error": _bm25_searcher_error,
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
        "pipelineName",
        "templateId",
        "language",
        "consultant",
        "session_id",
        "user_id",
    ):
        if k == "branches":
            raw = payload.get("branches")
            if isinstance(raw, list):
                for i, item in enumerate(raw):
                    v = str(item or "")
                    if len(v) > MAX_FIELD_LEN:
                        return False, f"field 'branches[{i}]' too long (>{MAX_FIELD_LEN})"
            else:
                v = str(raw or "")
                if len(v) > MAX_FIELD_LEN:
                    return False, f"field 'branches' too long (>{MAX_FIELD_LEN})"
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
        return {
            "results": final_answer,
            "query_type": query_type,
            "steps_used": steps_used,
            "translated": model_input_en,
        }
    return {"results": "", "translated": ""}


# ------------------------------------------------------------
# UI templates + branches (Option A)
# ------------------------------------------------------------

def _list_repositories() -> List[str]:
    try:
        out: List[str] = []
        if not os.path.isdir(REPOSITORIES_ROOT):
            return out
        for name in sorted(os.listdir(REPOSITORIES_ROOT)):
            p = os.path.join(REPOSITORIES_ROOT, name)
            if os.path.isdir(p):
                out.append(name)
        return out
    except Exception:
        py_logger.exception("soft-failure: failed to list repositories under %s", REPOSITORIES_ROOT)
        return []


def _load_ui_templates() -> dict:
    # minimal, but keep: ui_contracts/... if present
    candidates = [
        os.path.join(PROJECT_ROOT, "ui_contracts", "templates.json"),
        os.path.join(PROJECT_ROOT, "ui_contracts", "frontend_requirements", "templates.json"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return _load_json_file(p) or {}
    return {}


def _read_active_index_branches(cfg: dict) -> List[str]:
    try:
        root = str(cfg.get("vector_indexes_root") or "").strip()
        active = str(cfg.get("active_index_id") or "").strip()
        if not root or not active:
            return []

        manifest_path = os.path.join(root, active, "manifest.json")
        if not os.path.isfile(manifest_path):
            return []

        manifest = _load_json_file(manifest_path) or {}
        raw = manifest.get("branches") or []

        def _extract_name(x: Any) -> Optional[str]:
            if isinstance(x, dict):
                bn = str(x.get("branch_name") or x.get("branch") or "").strip()
                return bn or None

            if isinstance(x, str):
                s = x.strip()

                # legacy: python-literal dict string
                if s.startswith("{") and "branch_name" in s:
                    try:
                        d = ast.literal_eval(s)
                        if isinstance(d, dict):
                            bn2 = str(d.get("branch_name") or d.get("branch") or "").strip()
                            if bn2:
                                return bn2
                    except Exception:
                        global _logged_branch_literal_eval_error
                        if not _logged_branch_literal_eval_error:
                            _logged_branch_literal_eval_error = True
                            py_logger.exception(
                                "soft-failure: failed to parse branch literal via ast.literal_eval; value=%r", s
                            )
                        pass

                # already a plain branch string
                return s or None

            return None

        out: List[str] = []
        for item in raw:
            bn = _extract_name(item)
            if bn:
                out.append(bn)

        # stable order + dedupe
        seen = set()
        uniq: List[str] = []
        for b in out:
            if b not in seen:
                seen.add(b)
                uniq.append(b)
        return uniq
    except Exception:
        py_logger.exception("soft-failure: failed to resolve branches list; returning empty list")
        return []


def _pick_default_branch(branches: List[str], cfg: dict) -> str:
    # prefer config.active_index_id or empty, but simplest: first branch
    if branches:
        return branches[0]
    return ""


@app.route("/app-config", methods=["GET"])
def app_config():
    cfg = _runtime_cfg
    templates = _load_ui_templates()

    repos = _list_repositories()
    repo_name = str(cfg.get("repo_name") or "").strip() or (repos[0] if repos else "")

    branches = _read_active_index_branches(cfg)
    default_branch = _pick_default_branch(branches, cfg)

    consultants = []
    default_consultant_id = ""
    if isinstance(templates, dict):
        consultants = templates.get("consultants") or []
        default_consultant_id = str(templates.get("defaultConsultantId") or "")

    return jsonify(
        {
            "repositories": repos,
            "defaultRepository": repo_name,
            "branches": branches,
            "defaultBranch": default_branch,
            "consultants": consultants,
            "defaultConsultantId": default_consultant_id,
            "templates": templates,
            "translateChat": True,
        }
    )


# ------------------------------------------------------------
# Query endpoint (contract: query/consultant/pipelineName/branches[0..2])
# Backward-compat: still accept legacy branchA/branchB.
# ------------------------------------------------------------

@app.route("/query", methods=["POST"])
@app.route("/search", methods=["POST"])
def query():
    if not _auth_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

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
            templates = _load_ui_templates() or {}
            if isinstance(templates, dict):
                for t in (templates.get("consultants") or []):
                    if isinstance(t, dict) and str(t.get("id") or "") == consultant_id:
                        pipeline_name = str(t.get("pipelineName") or "").strip()
                        break
        except Exception:
            py_logger.exception("soft-failure: failed to resolve pipelineName from templates; consultant_id=%s", consultant_id)
            pipeline_name = ""

    repository = _get_str_field(payload, "repository", str(_runtime_cfg.get("repo_name") or ""))

    session_id = _valid_session_id(request.headers.get("X-Session-ID") or _get_str_field(payload, "session_id", ""))
    user_id = _valid_user_id(_get_str_field(payload, "user_id", ""))

    overrides: Dict[str, Any] = {}
    if branch_b:
        overrides["branch_b"] = branch_b

    try:
        mm = _runner.model if hasattr(_runner, "model") else None
        print("model type:", type(mm))
        print("callable:", callable(mm))
        print("has generate:", hasattr(mm, "generate"))
        print("has ask:", hasattr(mm, "ask"))
        
        runner_result = _runner.run(
            user_query=original_query,
            session_id=session_id,
            user_id=user_id,
            consultant=consultant_id,
            branch=branch,
            translate_chat=translate_chat,
            pipeline_name=pipeline_name or None,
            repository=repository or None,
            active_index=_active_index_id or None,
            overrides=overrides or None,
            mock_redis=_history_backend,
        )
    except Exception as e:
        py_logger.exception("Unhandled exception in /query")
        return jsonify({"ok": False, "error": str(e)}), 500

    out = _normalize_runner_result(runner_result)

    out["ok"] = True
    out["session_id"] = session_id
    out["consultant"] = consultant_id
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
