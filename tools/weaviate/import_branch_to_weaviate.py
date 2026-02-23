#!/usr/bin/env python3
from __future__ import annotations

"""
Import LocalAI-RAG branch bundle into Weaviate (BYOV: you compute embeddings, Weaviate stores vectors + text + metadata).

Variant A (agreed):
- ACL lives on NODES (RagNode).
- Graph edges (RagEdge) do NOT carry ACL.

Supports BOTH bundle layouts:
A) Newer layout (jsonl bodies):
   - regular_code_bundle/chunks.json
   - regular_code_bundle/dependencies.json (optional)
   - sql_bundle/docs/sql_bodies.jsonl  (or sql_code_bundle/docs/sql_bodies.jsonl)
   - sql_bundle/graph/edges.csv        (optional)

B) Older/legacy SQL layout (nodes.csv + docs/bodies/*):
   - sql_code_bundle/graph/nodes.csv (body_path column)
   - sql_code_bundle/graph/edges.csv (optional)
   - sql_code_bundle/docs/bodies/<...>.sql files referenced by body_path

Partitioning rule (agreed):
- Every query is scoped to a concrete snapshot_id.
- We store repo + branch + snapshot_id on every object.
- head_sha (if present) is stored as optional metadata.
"""

import argparse
import csv
import io
import json
import logging
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import weaviate
import weaviate.classes as wvc
from vector_db.weaviate_client import create_client, get_settings, load_dotenv
from weaviate.util import generate_uuid5

from tools.weaviate.snapshot_id import compute_snapshot_id, extract_folder_fingerprint

try:
    from sentence_transformers import SentenceTransformer
except Exception as ex:  # pragma: no cover
    raise SystemExit("ERROR: sentence-transformers is required. Install: pip install -U sentence-transformers") from ex


LOG = logging.getLogger("weaviate_import")


def _load_security_cfg() -> Dict[str, Any]:
    try:
        project_root = Path(__file__).resolve().parents[2]
        cfg_path = project_root / "config.json"
        if not cfg_path.exists():
            return {}
        return json.loads(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        LOG.exception("import: failed to load config.json for security settings")
        return {}


def _is_acl_enabled() -> bool:
    env_val = (os.getenv("ACL_ENABLED") or "").strip().lower()
    if env_val in ("1", "true", "yes", "on"):
        return True
    if env_val in ("0", "false", "no", "off"):
        return False
    cfg = _load_security_cfg()
    sec = cfg.get("permissions") or {}
    if isinstance(sec, dict):
        return bool(sec.get("acl_enabled", True))
    return True


_ACL_ENABLED = _is_acl_enabled()


def _load_security_settings() -> Dict[str, Any]:
    cfg = _load_security_cfg()
    sec = cfg.get("permissions") or {}
    return sec if isinstance(sec, dict) else {}


_SECURITY_CFG = _load_security_settings()
_SECURITY_ENABLED = bool(_SECURITY_CFG.get("security_enabled", False))
_SECURITY_MODEL = _SECURITY_CFG.get("security_model") or {}
_SECURITY_KIND = str(_SECURITY_MODEL.get("kind") or "").strip()

# ---- Weaviate collections ----
COL_IMPORT = "ImportRun"
COL_NODE = "RagNode"
COL_EDGE = "RagEdge"


@dataclass(frozen=True)
class RepoMeta:
    repo: str
    branch: str
    snapshot_id: str
    head_sha: str
    generated_at_utc: str


@dataclass
class ImportCounts:
    # Raw = how many records we read from the bundle
    # Unique = how many unique objects we actually inserted (after dedupe)
    # Dupes = raw - unique (note: malformed/skipped are not counted as dupes)
    raw: int = 0
    unique: int = 0
    dupes: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {"raw": self.raw, "unique": self.unique, "dupes": self.dupes}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_id(repo: str, snapshot_id: str, kind: str, local_id: str) -> str:
    # Stable & user-visible ID format used across the system.
    return f"{repo}::{snapshot_id}::{kind}::{local_id}"


# ------------------------------
# Weaviate connect + schema
# ------------------------------

def connect_weaviate(host: str, http_port: int, grpc_port: int, api_key: str = "") -> "weaviate.WeaviateClient":
    # Centralized Weaviate connect (config + env + optional API key).
    overrides = {
        "host": host.strip() if host else "",
        "http_port": int(http_port) if http_port else 0,
        "grpc_port": int(grpc_port) if grpc_port else 0,
        "api_key": api_key.strip() if api_key else "",
    }
    settings = get_settings(overrides={k: v for k, v in overrides.items() if v})
    return create_client(settings)


def ensure_schema(client: "weaviate.WeaviateClient") -> None:
    existing = set(client.collections.list_all(simple=True))

    # ImportRun is an operational log (no vectors needed). We still use self_provided() for simplicity.
    if COL_IMPORT not in existing:
        client.collections.create(
            name=COL_IMPORT,
            vector_config=wvc.config.Configure.Vectors.self_provided(),
            properties=[
                wvc.config.Property(name="import_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="repo", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="branch", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="snapshot_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="head_sha", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="ref_type", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="ref_name", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="tag", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="friendly_name", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="status", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="started_utc", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="finished_utc", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="error", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="stats_json", data_type=wvc.config.DataType.TEXT),
            ],
        )
        LOG.info("Created collection: %s", COL_IMPORT)

    # Nodes: text + metadata + vector
    if COL_NODE not in existing:
        acl_enabled = _ACL_ENABLED
        security_enabled = _SECURITY_ENABLED
        security_kind = _SECURITY_KIND
        if not acl_enabled:
            LOG.warning("ACL disabled via config/env. 'acl_allow' field will NOT be created in RagNode schema.")
        if not security_enabled:
            LOG.warning("Security disabled via config/env. 'classification_labels' and 'doc_level' will NOT be created in RagNode schema.")
        client.collections.create(
            name=COL_NODE,
            vector_config=wvc.config.Configure.Vectors.self_provided(),
            inverted_index_config=wvc.config.Configure.inverted_index(index_null_state=True),
            multi_tenancy_config=wvc.config.Configure.multi_tenancy(enabled=True),
            properties=[
                # Partition / identity
                wvc.config.Property(name="canonical_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="import_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="repo", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="branch", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="snapshot_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="head_sha", data_type=wvc.config.DataType.TEXT),

                # Filters (apply BEFORE ranking)
                wvc.config.Property(name="data_type", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="file_type", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="domain", data_type=wvc.config.DataType.TEXT),

                # Optional code metadata
                wvc.config.Property(name="source_file", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="repo_relative_path", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="project_name", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="class_name", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="member_name", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="symbol_type", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="signature", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="chunk_part", data_type=wvc.config.DataType.INT),
                wvc.config.Property(name="chunk_total", data_type=wvc.config.DataType.INT),

                # Optional SQL metadata
                wvc.config.Property(name="sql_kind", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="sql_schema", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="sql_name", data_type=wvc.config.DataType.TEXT),

                # Variant A: ACL on nodes (optional)
                *(
                    [wvc.config.Property(name="acl_allow", data_type=wvc.config.DataType.TEXT_ARRAY)]
                    if acl_enabled
                    else []
                ),
                *(
                    [wvc.config.Property(name="classification_labels", data_type=wvc.config.DataType.TEXT_ARRAY)]
                    if security_enabled and security_kind in ("labels_universe_subset", "classification_labels")
                    else []
                ),
                *(
                    [wvc.config.Property(name="doc_level", data_type=wvc.config.DataType.INT)]
                    if security_enabled and security_kind == "clearance_level"
                    else []
                ),
                wvc.config.Property(name="owner_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="source_system_id", data_type=wvc.config.DataType.TEXT),

                # Content
                wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT),
            ],
        )
        LOG.info("Created collection: %s", COL_NODE)

    # Edges: from/to + type
    if COL_EDGE not in existing:
        client.collections.create(
            name=COL_EDGE,
            vector_config=wvc.config.Configure.Vectors.self_provided(),
            multi_tenancy_config=wvc.config.Configure.multi_tenancy(enabled=True),
            properties=[
                wvc.config.Property(name="import_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="repo", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="snapshot_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="head_sha", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="edge_type", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="from_canonical_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="to_canonical_id", data_type=wvc.config.DataType.TEXT),
            ],
        )
        LOG.info("Created collection: %s", COL_EDGE)


def _ensure_tenant(client: "weaviate.WeaviateClient", *, collection_name: str, tenant: str) -> None:
    # Ensure tenant exists (idempotent enough for imports).
    coll = client.collections.use(collection_name)
    try:
        coll.tenants.create([wvc.tenants.Tenant(name=tenant)])
    except Exception:
        # If it already exists, ignore; otherwise re-raise.
        try:
            existing = coll.tenants.get()
            for t in existing:
                name = getattr(t, "name", None) or (t if isinstance(t, str) else None)
                if name == tenant:
                    return
        except Exception:
            pass
        raise


def upsert_import_run(
    client: "weaviate.WeaviateClient",
    *,
    import_id: str,
    meta: RepoMeta,
    status: str,
    started_utc: str,
    finished_utc: str = "",
    error: str = "",
    stats: Optional[Dict[str, Any]] = None,
    ref_type: str = "branch",
    ref_name: str = "",
    tag: str = "",
) -> None:
    coll = client.collections.use(COL_IMPORT)

    friendly = tag if tag else f"{meta.repo}:{meta.snapshot_id[:12]}"
    props = {
        "import_id": import_id,
        "repo": meta.repo,
        "branch": meta.branch,
        "snapshot_id": meta.snapshot_id,
        "head_sha": meta.head_sha,
        "ref_type": ref_type,
        "ref_name": ref_name or meta.branch,
        "tag": tag,
        "friendly_name": friendly,
        "status": status,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "error": error,
        "stats_json": json.dumps(stats or {}, ensure_ascii=False),
    }

    run_uuid = generate_uuid5(f"{meta.repo}::{meta.snapshot_id}::{import_id}")
    try:
        coll.data.insert(uuid=run_uuid, properties=props, vector=[0.0])
    except Exception:
        # Insert can fail with 422 if object exists; update is fine and expected.
        coll.data.update(uuid=run_uuid, properties=props)


# ------------------------------
# Bundle open helpers (folder OR zip)
# ------------------------------

class BundleReader:
    def __init__(self, root: Path, zf: Optional[zipfile.ZipFile]) -> None:
        self.root = root
        self.zf = zf

    def exists(self, rel: str) -> bool:
        if self.zf:
            try:
                self.zf.getinfo(str(self.root / rel).replace("\\", "/"))
                return True
            except KeyError:
                return False
        return (self.root / rel).is_file()

    def read_text(self, rel: str, encoding: str = "utf-8") -> str:
        if self.zf:
            data = self.zf.read(str(self.root / rel).replace("\\", "/"))
            return data.decode(encoding, errors="replace")
        return (self.root / rel).read_text(encoding=encoding, errors="replace")

    def open_bytes(self, rel: str):
        if self.zf:
            return self.zf.open(str(self.root / rel).replace("\\", "/"), "r")
        return open(self.root / rel, "rb")


def open_bundle(path: str) -> Tuple[BundleReader, RepoMeta]:
    p = Path(path)
    if p.is_dir():
        root = p
        zf = None
        meta_path = root / "repo_meta.json"
        if not meta_path.is_file():
            raise FileNotFoundError(f"repo_meta.json not found in folder: {root}")
        meta_raw = meta_path.read_text(encoding="utf-8", errors="replace")
    elif p.is_file() and p.suffix.lower() == ".zip":
        zf = zipfile.ZipFile(p, "r")
        # Determine top-level folder inside zip if present, else root="."
        names = [n for n in zf.namelist() if not n.endswith("/")]
        root_name = ""
        if names and all("/" in n for n in names):
            roots = {n.split("/", 1)[0] for n in names}
            if len(roots) == 1:
                root_name = list(roots)[0]
        root = Path(root_name) if root_name else Path(".")
        meta_rel = str(root / "repo_meta.json").replace("\\", "/")
        meta_raw = zf.read(meta_rel).decode("utf-8", errors="replace")
    else:
        raise FileNotFoundError(f"Bundle path must be a folder or .zip: {path}")

    meta_json = json.loads(meta_raw)

    # repo name resolution:
    # 1) explicit fields if present
    repo_name = str(
        meta_json.get("RepoName")
        or meta_json.get("Repo")
        or meta_json.get("Repository")
        or meta_json.get("RepositoryName")
        or meta_json.get("repo")
        or meta_json.get("repository")
        or ""
    ).strip()

    # 2) fallback: infer from RepositoryRoot (e.g. D:/TrainingCode/Nop/nopCommerce -> nopCommerce)
    if not repo_name:
        repo_root = str(meta_json.get("RepositoryRoot") or "").strip()
        if repo_root:
            repo_root = repo_root.rstrip("/\\")
            repo_name = repo_root.split("/")[-1].split("\\")[-1].strip()

    if not repo_name:
        repo_name = "unknown-repo"

    branch = str(meta_json.get("Branch") or meta_json.get("branch") or "").strip()
    generated_at = str(meta_json.get("GeneratedAtUtc") or meta_json.get("GeneratedAtUTC") or "").strip()

    head_sha_raw = meta_json.get("HeadSha") or meta_json.get("HeadSHA") or meta_json.get("head_sha")
    head_sha = str(head_sha_raw or "").strip()

    folder_fingerprint = extract_folder_fingerprint(meta_json)

    if not branch:
        branch = "(unknown)"

    # snapshot_id (requested):
    # - UUID5("RepoName:HeadSha") if HeadSha present
    # - else UUID5("RepoName:FolderFingerprint")
    snapshot_id = compute_snapshot_id(repo_name=repo_name, head_sha=head_sha, folder_fingerprint=folder_fingerprint)

    meta = RepoMeta(
        repo=repo_name,
        branch=branch,
        snapshot_id=snapshot_id,
        head_sha=head_sha,
        generated_at_utc=generated_at,
    )

    return BundleReader(root, zf), meta


# ------------------------------
# Normalization helpers
# ------------------------------

def _normalize_list_field(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        cleaned = [str(x).strip() for x in value if str(x).strip()]
        return cleaned
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    return []


def _normalize_int_field(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip()
        if not s:
            return None
        return int(float(s))
    except Exception:
        return None


# ------------------------------
# Readers: nodes
# ------------------------------

def iter_cs_nodes(bundle: BundleReader, meta: RepoMeta) -> Iterator[Dict[str, Any]]:
    candidates = [
        "regular_code_bundle/chunks.json",
        "code/chunks.json",
    ]
    chunks_rel = None
    for c in candidates:
        if bundle.exists(c):
            chunks_rel = c
            break
    if not chunks_rel:
        raise FileNotFoundError("chunks.json not found (expected regular_code_bundle/chunks.json).")

    raw = bundle.read_text(chunks_rel)
    items = json.loads(raw)
    for d in items:
        local_id = str(d.get("Id") or d.get("id") or "")
        if not local_id:
            continue
        cid = canonical_id(meta.repo, meta.snapshot_id, "cs", local_id)
        acl_allow = _normalize_list_field(d.get("acl_allow") or d.get("acl_tags_any"))
        classification_labels = _normalize_list_field(d.get("classification_labels") or d.get("classification_labels_all"))
        doc_level_raw = d.get("doc_level") or d.get("clearance_level")
        doc_level = _normalize_int_field(doc_level_raw)
        if doc_level_raw is not None and doc_level is None:
            LOG.warning("Invalid doc_level value (expected int). canonical_id=%s value=%r", cid, doc_level_raw)
        if doc_level is not None and doc_level < 0:
            LOG.warning("Negative doc_level coerced to None. canonical_id=%s value=%r", cid, doc_level)
            doc_level = None
        props = {
            "canonical_id": cid,
            "data_type": "regular_code",
            "file_type": "cs",
            "domain": "code",
            "source_file": str(d.get("File") or d.get("source_file") or ""),
            "repo_relative_path": str(d.get("RepoRelativePath") or d.get("repo_relative_path") or ""),
            "project_name": str(d.get("ProjectName") or ""),
            "class_name": str(d.get("Class") or d.get("class") or ""),
            "member_name": str(d.get("Member") or d.get("member") or ""),
            "symbol_type": str(d.get("Type") or d.get("type") or ""),
            "signature": str(d.get("Signature") or d.get("signature") or ""),
            "chunk_part": int(d.get("ChunkPart") or d.get("chunk_part") or 0),
            "chunk_total": int(d.get("ChunkTotal") or d.get("chunk_total") or 1),
            "sql_kind": "",
            "sql_schema": "",
            "sql_name": "",
            "acl_allow": (acl_allow if acl_allow else None),
            "classification_labels": (classification_labels if classification_labels else None),
            "doc_level": doc_level,
            "owner_id": str(d.get("owner_id") or "").strip(),
            "source_system_id": str(d.get("source_system_id") or "code").strip() or "code",
            "text": str(d.get("Text") or d.get("text") or ""),
        }
        if not _ACL_ENABLED:
            props.pop("acl_allow", None)
        if not _SECURITY_ENABLED:
            props.pop("classification_labels", None)
            props.pop("doc_level", None)
        elif _SECURITY_KIND == "clearance_level":
            props.pop("classification_labels", None)
        elif _SECURITY_KIND in ("labels_universe_subset", "classification_labels"):
            props.pop("doc_level", None)
        yield props


def _iter_sql_nodes_from_jsonl(bundle: BundleReader, meta: RepoMeta, jsonl_rel: str) -> Iterator[Dict[str, Any]]:
    with bundle.open_bytes(jsonl_rel) as f:
        for raw in f:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            d = json.loads(line)
            key = str(d.get("key") or d.get("Key") or "")
            if not key:
                continue
            cid = canonical_id(meta.repo, meta.snapshot_id, "sql", key)
            acl_allow = _normalize_list_field(d.get("acl_allow") or d.get("acl_tags_any"))
            classification_labels = _normalize_list_field(d.get("classification_labels") or d.get("classification_labels_all"))
            doc_level_raw = d.get("doc_level") or d.get("clearance_level")
            doc_level = _normalize_int_field(doc_level_raw)
            if doc_level_raw is not None and doc_level is None:
                LOG.warning("Invalid doc_level value (expected int). canonical_id=%s value=%r", cid, doc_level_raw)
            if doc_level is not None and doc_level < 0:
                LOG.warning("Negative doc_level coerced to None. canonical_id=%s value=%r", cid, doc_level)
                doc_level = None
            props = {
                "canonical_id": cid,
                "data_type": str(d.get("data_type") or "sql_code"),
                "file_type": str(d.get("file_type") or "sql"),
                "domain": str(d.get("domain") or "sql"),
                "source_file": str(d.get("file") or ""),
                "repo_relative_path": str(d.get("file") or ""),
                "project_name": "",
                "class_name": "",
                "member_name": "",
                "symbol_type": "",
                "signature": "",
                "chunk_part": 0,
                "chunk_total": 1,
                "sql_kind": str(d.get("kind") or ""),
                "sql_schema": str(d.get("schema") or ""),
                "sql_name": str(d.get("name") or ""),
                "acl_allow": (acl_allow if acl_allow else None),
                "classification_labels": (classification_labels if classification_labels else None),
                "doc_level": doc_level,
                "owner_id": str(d.get("owner_id") or "").strip(),
                "source_system_id": str(d.get("source_system_id") or "code").strip() or "code",
                "text": str(d.get("body") or d.get("text") or ""),
            }
            if not _ACL_ENABLED:
                props.pop("acl_allow", None)
            if not _SECURITY_ENABLED:
                props.pop("classification_labels", None)
                props.pop("doc_level", None)
            elif _SECURITY_KIND == "clearance_level":
                props.pop("classification_labels", None)
            elif _SECURITY_KIND in ("labels_universe_subset", "classification_labels"):
                props.pop("doc_level", None)
            yield props


def _iter_sql_nodes_from_nodes_csv(bundle: BundleReader, meta: RepoMeta, nodes_csv_rel: str) -> Iterator[Dict[str, Any]]:
    raw = bundle.read_text(nodes_csv_rel)
    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        key = (row.get("key") or "").strip().strip('"')
        if not key:
            continue

        body_path = (row.get("body_path") or "").strip().strip('"')
        body = ""
        if body_path:
            if bundle.exists(body_path):
                body = bundle.read_text(body_path)
            else:
                alt = f"sql_code_bundle/{body_path}".lstrip("/")
                if bundle.exists(alt):
                    body = bundle.read_text(alt)

        cid = canonical_id(meta.repo, meta.snapshot_id, "sql", key)
        props = {
            "canonical_id": cid,
            "data_type": "sql_code",
            "file_type": "sql",
            "domain": (row.get("domain") or "sql").strip().strip('"'),
            "source_file": (row.get("file") or "").strip().strip('"'),
            "repo_relative_path": (row.get("file") or "").strip().strip('"'),
            "project_name": "",
            "class_name": "",
            "member_name": "",
            "symbol_type": "",
            "signature": "",
            "chunk_part": 0,
            "chunk_total": 1,
            "sql_kind": (row.get("kind") or "").strip().strip('"'),
            "sql_schema": (row.get("schema") or "").strip().strip('"'),
            "sql_name": (row.get("name") or "").strip().strip('"'),
            "acl_allow": [],
            "classification_labels": [],
            "doc_level": None,
            "owner_id": "",
            "source_system_id": "code",
            "text": body.strip(),
        }
        if not _ACL_ENABLED:
            props.pop("acl_allow", None)
        if not _SECURITY_ENABLED:
            props.pop("classification_labels", None)
            props.pop("doc_level", None)
        elif _SECURITY_KIND == "clearance_level":
            props.pop("classification_labels", None)
        elif _SECURITY_KIND in ("labels_universe_subset", "classification_labels"):
            props.pop("doc_level", None)
        yield props


def iter_sql_nodes(bundle: BundleReader, meta: RepoMeta) -> Iterator[Dict[str, Any]]:
    candidates = [
        "sql_bundle/docs/sql_bodies.jsonl",
        "sql_code_bundle/docs/sql_bodies.jsonl",
        "docs/sql_bodies.jsonl",
    ]
    for c in candidates:
        if bundle.exists(c):
            yield from _iter_sql_nodes_from_jsonl(bundle, meta, c)
            return

    legacy_nodes = [
        "sql_code_bundle/graph/nodes.csv",
        "sql_bundle/graph/nodes.csv",
        "graph/nodes.csv",
    ]
    for c in legacy_nodes:
        if bundle.exists(c):
            yield from _iter_sql_nodes_from_nodes_csv(bundle, meta, c)
            return

    return


# ------------------------------
# Readers: edges
# ------------------------------

def iter_cs_edges(bundle: BundleReader, meta: RepoMeta) -> Iterator[Tuple[str, str, str]]:
    candidates = [
        "regular_code_bundle/dependencies.json",
        "code/dependencies.json",
    ]
    dep_rel = None
    for c in candidates:
        if bundle.exists(c):
            dep_rel = c
            break
    if not dep_rel:
        return

    raw = bundle.read_text(dep_rel)
    deps = json.loads(raw)
    for from_local, to_list in deps.items():
        from_cid = canonical_id(meta.repo, meta.snapshot_id, "cs", str(from_local))
        for to_local in to_list or []:
            to_cid = canonical_id(meta.repo, meta.snapshot_id, "cs", str(to_local))
            yield ("cs_dep", from_cid, to_cid)


def _iter_edges_from_edges_csv(bundle: BundleReader, meta: RepoMeta, edges_rel: str) -> Iterator[Tuple[str, str, str]]:
    raw = bundle.read_text(edges_rel)
    reader = csv.DictReader(io.StringIO(raw))

    def pick(row: Dict[str, str], keys: List[str]) -> str:
        for k in keys:
            v = (row.get(k) or "").strip().strip('"')
            if v:
                return v
        return ""

    for row in reader:
        frm = pick(row, ["from_id", "from", "From"])
        to = pick(row, ["to_id", "to", "To"])
        rel = pick(row, ["edge_type", "relation", "Relation", "type"])
        if not frm or not to:
            continue
        from_cid = canonical_id(meta.repo, meta.snapshot_id, "sql", frm)
        to_cid = canonical_id(meta.repo, meta.snapshot_id, "sql", to)
        yield (f"sql_{rel or 'edge'}", from_cid, to_cid)


def iter_sql_edges(bundle: BundleReader, meta: RepoMeta) -> Iterator[Tuple[str, str, str]]:
    candidates = [
        "sql_bundle/graph/edges.csv",
        "sql_code_bundle/graph/edges.csv",
        "graph/edges.csv",
    ]
    for c in candidates:
        if bundle.exists(c):
            yield from _iter_edges_from_edges_csv(bundle, meta, c)
            return
    return


# ------------------------------
# Insert helpers
# ------------------------------

def load_embedder(model_path_or_name: str) -> SentenceTransformer:
    LOG.info("Loading embedding model: %s", model_path_or_name)
    return SentenceTransformer(model_path_or_name)


def embed_texts(model: SentenceTransformer, texts: List[str], batch_size: int) -> List[List[float]]:
    vecs = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return [v.astype("float32").tolist() for v in vecs]


def insert_nodes(
    client: "weaviate.WeaviateClient",
    *,
    meta: RepoMeta,
    import_id: str,
    model: SentenceTransformer,
    nodes: Iterable[Dict[str, Any]],
    embed_batch: int,
    weaviate_batch: int,
) -> ImportCounts:
    coll = client.collections.use(COL_NODE).with_tenant(meta.snapshot_id)

    counts = ImportCounts()
    seen_canonical: set[str] = set()

    buf_props: List[Dict[str, Any]] = []
    buf_text: List[str] = []

    def flush() -> None:
        nonlocal buf_props, buf_text, counts
        if not buf_props:
            return

        vectors = embed_texts(model, buf_text, batch_size=embed_batch)
        objs: List[wvc.data.DataObject] = []

        for props, vec in zip(buf_props, vectors):
            p = dict(props)
            p["import_id"] = import_id
            p["repo"] = meta.repo
            p["branch"] = meta.branch
            p["snapshot_id"] = meta.snapshot_id
            p["head_sha"] = meta.head_sha

            obj_uuid = generate_uuid5(p["canonical_id"])
            objs.append(wvc.data.DataObject(uuid=obj_uuid, properties=p, vector=vec))

        res = coll.data.insert_many(objs)
        if res.has_errors:
            first = res.errors[0] if res.errors else "unknown error"
            raise RuntimeError(f"insert_many(nodes) failed; first error: {first}")

        counts.unique += len(objs)
        buf_props = []
        buf_text = []

    for n in nodes:
        counts.raw += 1

        cid = (n.get("canonical_id") or "").strip()
        if not cid:
            continue

        if cid in seen_canonical:
            counts.dupes += 1
            continue

        seen_canonical.add(cid)

        buf_props.append(n)
        buf_text.append((n.get("text") or "").strip())

        if len(buf_props) >= weaviate_batch:
            flush()

    flush()
    return counts


def insert_edges(
    client: "weaviate.WeaviateClient",
    *,
    meta: RepoMeta,
    import_id: str,
    edges: Iterable[Tuple[str, str, str]],
    weaviate_batch: int,
) -> ImportCounts:
    coll = client.collections.use(COL_EDGE).with_tenant(meta.snapshot_id)

    counts = ImportCounts()
    seen_edge_keys: set[str] = set()

    buf: List[wvc.data.DataObject] = []

    def flush() -> None:
        nonlocal buf, counts
        if not buf:
            return
        res = coll.data.insert_many(buf)
        if res.has_errors:
            first = res.errors[0] if res.errors else "unknown error"
            raise RuntimeError(f"insert_many(edges) failed; first error: {first}")

        counts.unique += len(buf)
        buf = []

    for edge_type, from_cid, to_cid in edges:
        counts.raw += 1

        edge_key = f"{edge_type}::{from_cid}-->{to_cid}"
        if edge_key in seen_edge_keys:
            counts.dupes += 1
            continue
        seen_edge_keys.add(edge_key)

        props = {
            "import_id": import_id,
            "repo": meta.repo,
            "snapshot_id": meta.snapshot_id,
            "head_sha": meta.head_sha,
            "edge_type": edge_type,
            "from_canonical_id": from_cid,
            "to_canonical_id": to_cid,
        }
        edge_uuid = generate_uuid5(f"{meta.repo}::{meta.snapshot_id}::{edge_key}")
        buf.append(wvc.data.DataObject(uuid=edge_uuid, properties=props, vector=[0.0]))

        if len(buf) >= weaviate_batch:
            flush()

    flush()
    return counts


# ------------------------------
# Main import
# ------------------------------

def run_import(
    *,
    bundle_path: str,
    weaviate_host: str,
    weaviate_http_port: int,
    weaviate_grpc_port: int,
    weaviate_api_key: str,
    embed_model: str,
    embed_batch: int,
    weaviate_batch: int,
    import_id: str,
    ref_type: str,
    ref_name: str,
    tag: str,
) -> None:
    started = utc_now_iso()
    bundle, meta = open_bundle(bundle_path)

    client = connect_weaviate(weaviate_host, weaviate_http_port, weaviate_grpc_port, api_key=weaviate_api_key)
    try:
        ensure_schema(client)

        _ensure_tenant(client, collection_name=COL_NODE, tenant=meta.snapshot_id)
        _ensure_tenant(client, collection_name=COL_EDGE, tenant=meta.snapshot_id)

        upsert_import_run(
            client,
            import_id=import_id,
            meta=meta,
            status="running",
            started_utc=started,
            ref_type=ref_type,
            ref_name=ref_name,
            tag=tag,
        )

        model = load_embedder(embed_model)

        LOG.info("Importing nodes: C# ...")
        cs_nodes = insert_nodes(
            client,
            meta=meta,
            import_id=import_id,
            model=model,
            nodes=iter_cs_nodes(bundle, meta),
            embed_batch=embed_batch,
            weaviate_batch=weaviate_batch,
        )
        LOG.info(
            "Imported C# nodes: raw=%d unique=%d dupes=%d",
            cs_nodes.raw, cs_nodes.unique, cs_nodes.dupes
        )

        LOG.info("Importing nodes: SQL ...")
        sql_nodes = insert_nodes(
            client,
            meta=meta,
            import_id=import_id,
            model=model,
            nodes=iter_sql_nodes(bundle, meta),
            embed_batch=embed_batch,
            weaviate_batch=weaviate_batch,
        )
        LOG.info(
            "Imported SQL nodes: raw=%d unique=%d dupes=%d",
            sql_nodes.raw, sql_nodes.unique, sql_nodes.dupes
        )

        LOG.info("Importing edges: C# dependencies ...")
        cs_edges = insert_edges(
            client,
            meta=meta,
            import_id=import_id,
            edges=iter_cs_edges(bundle, meta),
            weaviate_batch=weaviate_batch,
        )
        LOG.info(
            "Imported C# edges: raw=%d unique=%d dupes=%d",
            cs_edges.raw, cs_edges.unique, cs_edges.dupes
        )

        LOG.info("Importing edges: SQL graph ...")
        sql_edges = insert_edges(
            client,
            meta=meta,
            import_id=import_id,
            edges=iter_sql_edges(bundle, meta),
            weaviate_batch=weaviate_batch,
        )
        LOG.info(
            "Imported SQL edges: raw=%d unique=%d dupes=%d",
            sql_edges.raw, sql_edges.unique, sql_edges.dupes
        )

        finished = utc_now_iso()
        stats = {
            "nodes_cs": cs_nodes.as_dict(),
            "nodes_sql": sql_nodes.as_dict(),
            "edges_cs": cs_edges.as_dict(),
            "edges_sql": sql_edges.as_dict(),
            "nodes_total": {
                "raw": cs_nodes.raw + sql_nodes.raw,
                "unique": cs_nodes.unique + sql_nodes.unique,
                "dupes": cs_nodes.dupes + sql_nodes.dupes,
            },
            "edges_total": {
                "raw": cs_edges.raw + sql_edges.raw,
                "unique": cs_edges.unique + sql_edges.unique,
                "dupes": cs_edges.dupes + sql_edges.dupes,
            },
        }

        upsert_import_run(
            client,
            import_id=import_id,
            meta=meta,
            status="completed",
            started_utc=started,
            finished_utc=finished,
            stats=stats,
            ref_type=ref_type,
            ref_name=ref_name,
            tag=tag,
        )

        LOG.info(
            "DONE: repo=%s branch=%s snapshot_id=%s head_sha=%s import_id=%s",
            meta.repo, meta.branch, meta.snapshot_id, meta.head_sha, import_id
        )

    except Exception as ex:
        LOG.exception("IMPORT FAILED: %s", ex)
        try:
            upsert_import_run(
                client,
                import_id=import_id,
                meta=meta,
                status="failed",
                started_utc=started,
                finished_utc=utc_now_iso(),
                error=str(ex),
                ref_type=ref_type,
                ref_name=ref_name,
                tag=tag,
            )
        except Exception:
            pass
        raise
    finally:
        if bundle.zf:
            try:
                bundle.zf.close()
            except Exception:
                pass
        client.close()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import LocalAI-RAG branch bundle into Weaviate (BYOV).")
    p.add_argument("--bundle", required=True, help="Path to branch folder OR .zip")
    p.add_argument("--weaviate-host", default="", help="Optional. Default from config/env.")
    p.add_argument("--weaviate-http-port", type=int, default=0, help="Optional. Default from config/env.")
    p.add_argument("--weaviate-grpc-port", type=int, default=0, help="Optional. Default from config/env.")
    p.add_argument("--weaviate-api-key", default="", help="Optional. Overrides env/config. Prefer WEAVIATE_API_KEY env in production.")
    p.add_argument("--env", action="store_true", help="Load .env from project root before reading config/env (does not override existing env vars).")
    p.add_argument("--embed-model", required=True, help="SentenceTransformer model path or name (e.g. models/embedding/e5-base-v2)")
    p.add_argument("--embed-batch", type=int, default=64)
    p.add_argument("--weaviate-batch", type=int, default=128)
    p.add_argument("--import-id", default="", help="Optional. Default: auto")
    p.add_argument("--ref-type", default="branch", help="branch|tag|detached")
    p.add_argument("--ref-name", default="", help="e.g. develop or v4.90.0")
    p.add_argument("--tag", default="", help="Tag name if applicable")
    p.add_argument("--log-level", default="INFO")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Optional: load .env for this CLI process (does not override existing env vars).
    if getattr(args, "env", False):
        project_root = Path(__file__).resolve().parents[2]
        load_dotenv(project_root / ".env", override=False)

    import_id = args.import_id.strip() or f"import::{utc_now_iso()}"
    run_import(
        bundle_path=args.bundle,
        weaviate_host=args.weaviate_host,
        weaviate_http_port=args.weaviate_http_port,
        weaviate_grpc_port=args.weaviate_grpc_port,
        weaviate_api_key=args.weaviate_api_key,
        embed_model=args.embed_model,
        embed_batch=args.embed_batch,
        weaviate_batch=args.weaviate_batch,
        import_id=import_id,
        ref_type=args.ref_type,
        ref_name=args.ref_name,
        tag=args.tag,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
