#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ACL_TAGS = ["finance", "security", "hr", "ops", "legal", "integration"]
CLASSIFICATION_LABELS = ["public", "internal", "secret", "restricted"]
CLEARANCE_LEVELS = {
    "public": 0,
    "internal": 10,
    "restricted": 20,
    "critical": 30,
    "secret": 20,
}


@dataclass
class CorpusItem:
    item_id: str
    title: str
    text: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", s.strip()).strip("_") or "item"


def _extract_code_blocks(text: str) -> List[Tuple[int, int, str]]:
    blocks = []
    for m in re.finditer(r"```[a-zA-Z0-9_+-]*\r?\n(.*?)\r?\n```", text, re.DOTALL):
        blocks.append((m.start(), m.end(), m.group(1)))
    return blocks


def _find_nearest_heading(text: str, pos: int) -> str:
    prefix = text[:pos]
    for line in reversed(prefix.splitlines()):
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if stripped.lower().startswith("item") or stripped.lower().startswith("sample"):
            return stripped
    return ""


def parse_corpus_md(path: Path, *, default_prefix: str) -> List[CorpusItem]:
    raw = path.read_text(encoding="utf-8")

    # Try JSON code block
    for m in re.finditer(r"```json\\n(.*?)\\n```", raw, re.DOTALL):
        try:
            payload = json.loads(m.group(1))
            if isinstance(payload, list):
                out: List[CorpusItem] = []
                for i, item in enumerate(payload, start=1):
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("text") or item.get("body") or "").strip()
                    if not text:
                        continue
                    item_id = str(item.get("id") or item.get("key") or f"{default_prefix}{i:03d}")
                    title = str(item.get("title") or item.get("name") or item_id)
                    out.append(CorpusItem(item_id=item_id, title=title, text=text))
                if out:
                    return out
        except Exception:
            pass

    blocks = _extract_code_blocks(raw)
    if blocks:
        out: List[CorpusItem] = []
        for i, (start, _end, body) in enumerate(blocks, start=1):
            heading = _find_nearest_heading(raw, start)
            item_id = f"{default_prefix}{i:03d}"
            title = heading or item_id
            out.append(CorpusItem(item_id=item_id, title=title, text=body.strip()))
        return out

    # Fallback: split by headings
    parts = re.split(r"^#{2,}\\s+", raw, flags=re.MULTILINE)
    out: List[CorpusItem] = []
    for i, part in enumerate(parts, start=1):
        text = part.strip()
        if not text:
            continue
        item_id = f"{default_prefix}{i:03d}"
        title = text.splitlines()[0][:80]
        out.append(CorpusItem(item_id=item_id, title=title, text=text))
    return out


def _assign_acl(idx: int) -> List[str]:
    # Integration tests (round-2/3) apply user filters: ACL in {"finance","security"}
    # and either clearance_level<=10 or classification label subset. Some golden anchor
    # docs for NLog-related queries would otherwise be filtered out entirely, causing
    # "no seed nodes" failures. We pin a couple of known anchor items to an allowed ACL.
    if idx in (29, 45):
        return ["security"]
    return [ACL_TAGS[idx % len(ACL_TAGS)]]


def _assign_labels(idx: int) -> List[str]:
    return [CLASSIFICATION_LABELS[idx % len(CLASSIFICATION_LABELS)]]


def _assign_clearance_level(idx: int) -> int:
    labels = _assign_labels(idx)
    return int(CLEARANCE_LEVELS.get(labels[0], 0))


def _build_cs_chunk(item: CorpusItem, idx: int, *, include_acl: bool, include_labels: bool, include_clearance_level: bool) -> Dict[str, object]:
    cls_name = f"CorpusItem{idx:03d}"
    file_path = f"src/FakeEnterprise.Corpus/CSharp/{cls_name}.cs"
    payload: Dict[str, object] = {
        "Id": f"C{idx:04d}",
        "File": file_path,
        "RepoRelativePath": file_path,
        "ProjectName": "FakeEnterprise",
        "Class": cls_name,
        "Member": "Sample",
        "Type": "Snippet",
        "ChunkPart": 1,
        "ChunkTotal": 1,
        "Text": item.text.strip(),
        "source_system_id": "code.csharp",
        "acl_allow": [],
    }
    if include_acl:
        payload["acl_allow"] = _assign_acl(idx)
    if include_labels:
        payload["classification_labels_all"] = _assign_labels(idx)
    if include_clearance_level:
        payload["clearance_level"] = _assign_clearance_level(idx)
    return payload


def _build_sql_body(item: CorpusItem, idx: int, *, include_acl: bool, include_labels: bool, include_clearance_level: bool) -> Dict[str, object]:
    name = f"proc_Corpus_{idx:03d}"
    key = f"SQL:dbo.{name}"
    file_path = f"db/procs/{name}.sql"
    payload: Dict[str, object] = {
        "key": key,
        "kind": "Procedure",
        "schema": "dbo",
        "name": name,
        "file": file_path,
        "body": item.text.strip(),
        "data_type": "sql_code",
        "file_type": "sql",
        "domain": "sql",
        "source_system_id": "code.sql",
        "acl_allow": [],
    }
    if include_acl:
        payload["acl_allow"] = _assign_acl(idx)
    if include_labels:
        payload["classification_labels_all"] = _assign_labels(idx)
    if include_clearance_level:
        payload["clearance_level"] = _assign_clearance_level(idx)
    return payload


def _build_sql_nodes_rows(items: List[CorpusItem]) -> List[List[str]]:
    rows = [["key", "kind", "name", "schema", "file", "batch", "domain", "body_path"]]
    for i, _item in enumerate(items, start=1):
        name = f"proc_Corpus_{i:03d}"
        key = f"SQL:dbo.{name}"
        file_path = f"db/procs/{name}.sql"
        rows.append([key, "PROCEDURE", name, "dbo", file_path, "fake-enterprise", "sql", ""])
    return rows


def _build_sql_edges_rows(items: List[CorpusItem]) -> List[List[str]]:
    rows = [["from", "to", "relation", "to_kind", "file", "batch"]]
    for i in range(1, len(items)):
        frm = f"SQL:dbo.proc_Corpus_{i:03d}"
        to = f"SQL:dbo.proc_Corpus_{i+1:03d}"
        file_path = f"db/procs/proc_Corpus_{i:03d}.sql"
        rows.append([frm, to, "Calls", "PROCEDURE", file_path, "fake-enterprise"])
    return rows


def _rows_to_csv(rows: List[List[str]]) -> str:
    return "\n".join([",".join(r) for r in rows]) + "\n"


def _build_cs_dependencies(count: int) -> Dict[str, List[str]]:
    deps: Dict[str, List[str]] = {}
    for i in range(1, count + 1):
        src = f"C{i:04d}"
        if i < count:
            deps[src] = [f"C{i+1:04d}"]
        else:
            deps[src] = []
    return deps


def _write_bundle(
    *,
    out_zip: Path,
    release: str,
    repo: str,
    bundle_prefix: str,
    cs_items: List[CorpusItem],
    sql_items: List[CorpusItem],
    include_acl: bool,
    include_labels: bool,
    include_clearance_level: bool,
) -> None:
    prefix = ""
    branch = f"release-{release}"
    head_sha = _sha1(f"{repo}:{release}:{len(cs_items)}:{len(sql_items)}")
    snapshot_id = head_sha
    generated_at = _utc_now()

    repo_meta = {
        "RepoName": repo,
        "Branch": branch,
        "HeadSha": head_sha,
        "RepositoryRoot": f"D:/{repo}",
        "FolderFingerprint": None,
        "GeneratedAtUtc": generated_at,
    }

    cs_chunks = [
        _build_cs_chunk(item, idx, include_acl=include_acl, include_labels=include_labels, include_clearance_level=include_clearance_level)
        for idx, item in enumerate(cs_items, start=1)
    ]
    cs_deps = _build_cs_dependencies(len(cs_chunks))

    sql_bodies = [
        _build_sql_body(item, idx, include_acl=include_acl, include_labels=include_labels, include_clearance_level=include_clearance_level)
        for idx, item in enumerate(sql_items, start=1)
    ]
    nodes_csv = _rows_to_csv(_build_sql_nodes_rows(sql_items))
    edges_csv = _rows_to_csv(_build_sql_edges_rows(sql_items))

    manifest = {
        "release": release,
        "repo": repo,
        "source_system_id": "code",
        "notes": "Generated from corpora for retrieval integration tests.",
    }

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(prefix + "repo_meta.json", json.dumps(repo_meta, indent=2))
        zf.writestr(prefix + "regular_code_bundle/", "")
        zf.writestr(prefix + "regular_code_bundle/chunks.json", json.dumps(cs_chunks, ensure_ascii=False, indent=2))
        zf.writestr(prefix + "regular_code_bundle/dependencies.json", json.dumps(cs_deps, ensure_ascii=False, indent=2))
        zf.writestr(prefix + "regular_code_bundle/README_WSL.txt", "Generated bundle for retrieval integration tests.")
        zf.writestr(prefix + "sql_code_bundle/", "")
        zf.writestr(prefix + "sql_code_bundle/manifest.json", json.dumps(manifest, indent=2))
        zf.writestr(prefix + "sql_code_bundle/docs/", "")
        zf.writestr(prefix + "sql_code_bundle/docs/sql_bodies.jsonl", "\n".join(json.dumps(x, ensure_ascii=False) for x in sql_bodies) + "\n")
        zf.writestr(prefix + "sql_code_bundle/graph/", "")
        zf.writestr(prefix + "sql_code_bundle/graph/nodes.csv", nodes_csv)
        zf.writestr(prefix + "sql_code_bundle/graph/edges.csv", edges_csv)


CORPUS_DIR = Path("tests/integration/fake_data")
CS_CORPUS_PATH = CORPUS_DIR / "csharp_corpus_100_items_with_queries.md"
SQL_CORPUS_PATH = CORPUS_DIR / "sql_corpus_100_items_with_queries.md"
RESULTS_PATH = CORPUS_DIR / "retrieval_results_top5_corpus1_corpus2.md"
OUT_DIR = Path("tests/repositories/fake")
REPO_NAME = "Fake"
BUNDLE_PREFIX = "FAKE_ENTERPRISE"


def main() -> int:
    if not CS_CORPUS_PATH.exists():
        raise SystemExit(f"Missing C# corpus file: {CS_CORPUS_PATH}")
    if not SQL_CORPUS_PATH.exists():
        raise SystemExit(f"Missing SQL corpus file: {SQL_CORPUS_PATH}")

    cs_items = parse_corpus_md(CS_CORPUS_PATH, default_prefix="CS")
    sql_items = parse_corpus_md(SQL_CORPUS_PATH, default_prefix="SQL")

    if len(cs_items) < 10 or len(sql_items) < 10:
        raise SystemExit("Corpus parsing failed: expected at least 10 items per corpus.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    bundles = [
        # set 1: no ACL, no clearance_level, no classification_labels
        ("1.0", False, False, False),
        ("1.1", False, False, False),
        # set 2: ACL + clearance_level, no classification_labels
        ("2.0", True, False, True),
        ("2.1", True, False, True),
        # set 3: ACL + classification_labels, no clearance_level
        ("3.0", True, True, False),
        ("3.1", True, True, False),
        # set 4: ACL only
        ("4.0", True, False, False),
        ("4.1", True, False, False),
    ]

    for release, include_acl, include_labels, include_clearance_level in bundles:
        out_zip = OUT_DIR / f"Release_{BUNDLE_PREFIX}_{release}.zip"
        _write_bundle(
            out_zip=out_zip,
            release=release,
            repo=REPO_NAME,
            bundle_prefix=BUNDLE_PREFIX,
            cs_items=cs_items,
            sql_items=sql_items,
            include_acl=include_acl,
            include_labels=include_labels,
            include_clearance_level=include_clearance_level,
        )

    print("Generated bundles in", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
