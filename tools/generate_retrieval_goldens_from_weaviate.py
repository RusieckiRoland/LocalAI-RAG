#!/usr/bin/env python3
from __future__ import annotations
from code_query_engine.pipeline.providers.retrieval_backend_contract import SearchRequest

"""
Generate a "golden" retrieval report by asking a real Weaviate instance.

Why this exists:
- The file in tests/integration/fake_data/retrieval_results_top5_corpus1_corpus2.md was initially
  produced using offline proxies (TF-IDF etc.). That is great for repeatability, but it WILL NOT
  match Weaviate runtime scoring (BM25 tokenization + vector/hybrid fusion).
- If you want expected top-k to be a *credible baseline for Weaviate*, the most faithful oracle is
  Weaviate itself (same version, same schema, same embed model).

This tool:
1) starts a local Weaviate docker container (same as integration tests),
2) imports the fake bundle (default: Release_FAKE_ENTERPRISE_1.0.zip),
3) runs all query sets for both corpora using our WeaviateRetrievalBackend,
4) writes a markdown report compatible with parse_golden_results().

Run:
  INTEGRATION_EMBED_MODEL=models/embedding/e5-base-v2 \
  python -m tools.generate_retrieval_goldens_from_weaviate \
    --out tests/integration/fake_data/retrieval_results_top5_corpus1_corpus2.weaviate.md
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.error import URLError
from urllib.request import urlopen

import weaviate
from weaviate.classes.query import Filter

from code_query_engine.pipeline.providers.weaviate_retrieval_backend import WeaviateRetrievalBackend


_WEAVIATE_IMAGE_DEFAULT = "cr.weaviate.io/semitechnologies/weaviate:1.32.2"


@dataclass(frozen=True)
class CorpusQueries:
    bm25: List[str]
    semantic: List[str]
    hybrid: List[str]

    def as_q_list(self) -> List[Tuple[str, str]]:
        """
        Returns list of (qid, query) pairs:
          Q01..Q05 = bm25
          Q06..Q10 = semantic
          Q11..Q15 = hybrid
        """
        out: List[Tuple[str, str]] = []
        qnum = 1
        for q in self.bm25:
            out.append((f"Q{qnum:02d}", q))
            qnum += 1
        for q in self.semantic:
            out.append((f"Q{qnum:02d}", q))
            qnum += 1
        for q in self.hybrid:
            out.append((f"Q{qnum:02d}", q))
            qnum += 1
        return out


@dataclass(frozen=True)
class CorpusItemMeta:
    title: str
    anchor_phrase: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_command(
    cmd: List[str],
    *,
    cwd: Path,
    timeout_s: int,
    env: Dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        joined = " ".join(cmd)
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {joined}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )
    return proc


def _wait_for_weaviate_ready(*, host: str, http_port: int, timeout_s: int = 180) -> None:
    deadline = time.monotonic() + timeout_s
    url = f"http://{host}:{http_port}/v1/.well-known/ready"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= int(response.status) < 300:
                    return
        except (URLError, ConnectionResetError, TimeoutError, OSError):
            time.sleep(1)
            continue
        time.sleep(1)
    raise TimeoutError(f"Weaviate did not become ready within {timeout_s}s ({url}).")


def _assert_docker_available() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker is required to generate Weaviate-based goldens (docker not found in PATH).")
    probe = subprocess.run(["docker", "info"], text=True, capture_output=True, check=False)
    if probe.returncode != 0:
        raise RuntimeError("Docker daemon is not available. Start Docker and rerun.")


def _read_repo_meta(bundle_zip: Path) -> Dict[str, str]:
    from tools.weaviate.snapshot_id import compute_snapshot_id, extract_folder_fingerprint

    with zipfile.ZipFile(bundle_zip, "r") as zf:
        names = [n for n in zf.namelist() if n.endswith("repo_meta.json")]
        if not names:
            raise RuntimeError(f"Bundle {bundle_zip} missing repo_meta.json")
        meta = json.loads(zf.read(names[0]).decode("utf-8", errors="replace"))

    repo = str(
        meta.get("RepoName")
        or meta.get("Repo")
        or meta.get("Repository")
        or meta.get("RepositoryName")
        or meta.get("repo")
        or meta.get("repository")
        or ""
    ).strip()
    if not repo:
        repo_root = str(meta.get("RepositoryRoot") or "").strip()
        if repo_root:
            repo_root = repo_root.rstrip("/\\")
            repo = repo_root.split("/")[-1].split("\\")[-1].strip()
    repo = repo or "unknown-repo"

    head_sha = str(meta.get("HeadSha") or meta.get("HeadSHA") or meta.get("head_sha") or "").strip()
    snapshot_id = str(meta.get("SnapshotId") or meta.get("snapshot_id") or "").strip()
    if not snapshot_id:
        snapshot_id = compute_snapshot_id(
            repo_name=repo,
            head_sha=head_sha,
            folder_fingerprint=extract_folder_fingerprint(meta),
        )
    return {
        "repo": repo,
        "snapshot_id": snapshot_id,
    }


def _backup_and_restore_config(repo_root: Path) -> Tuple[Dict[Path, str], List[Path]]:
    backups: Dict[Path, str] = {}
    paths: List[Path] = []
    for rel in ("config.json", "tests/config.json"):
        p = repo_root / rel
        if p.exists():
            backups[p] = p.read_text(encoding="utf-8")
            paths.append(p)
    return backups, paths


def _restore_config(backups: Dict[Path, str]) -> None:
    for path, content in backups.items():
        try:
            path.write_text(content, encoding="utf-8")
        except Exception:
            pass


def _write_permissions_config(repo_root: Path, permissions: dict) -> None:
    for rel in ("config.json", "tests/config.json"):
        cfg_path = repo_root / rel
        if not cfg_path.exists():
            continue
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw["permissions"] = permissions
        cfg_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_query_sets(corpus_md: Path) -> CorpusQueries:
    raw = corpus_md.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()

    def parse_section(title_prefix: str) -> List[str]:
        section = False
        out: List[str] = []
        for line in lines:
            s = line.strip()
            if s.startswith(title_prefix):
                section = True
                continue
            if section and s.startswith("### "):
                # next heading starts, stop
                break
            if not section:
                continue
            # Markdown lists in our corpora use the "1. ..." format.
            m = re.match(r"^(\d+)\.(.+)$", s)
            if not m:
                continue
            q = m.group(2).strip()
            # Strip optional backticks.
            if len(q) >= 2 and q[0] == "`" and q[-1] == "`":
                q = q[1:-1]
            q = q.strip()
            if q:
                out.append(q)
            if len(out) >= 5:
                break
        if len(out) != 5:
            raise RuntimeError(f"Failed to parse 5 queries from section {title_prefix!r} in {corpus_md}")
        return out

    return CorpusQueries(
        bm25=parse_section("### BM25 queries"),
        semantic=parse_section("### Semantic queries"),
        hybrid=parse_section("### Hybrid queries"),
    )


def _parse_item_meta(corpus_md: Path) -> Dict[int, CorpusItemMeta]:
    """
    Parse item metadata from corpus markdown:
      ### Item 001: <title>
      - Anchor phrase: **...**   (optional)

    NOTE:
    - Anchor phrase is OPTIONAL (some items intentionally omit it).
    """
    raw = corpus_md.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()

    out: Dict[int, CorpusItemMeta] = {}

    current_idx: int | None = None
    current_title: str = ""
    current_anchor: str = ""

    for line in lines:
        s = line.strip()

        m_item = re.match(r"^###\s+Item\s+(\d{3})\s*:\s*(.+?)\s*$", s)
        if m_item:
            # Flush previous.
            if current_idx is not None:
                out[current_idx] = CorpusItemMeta(
                    title=current_title.strip(),
                    anchor_phrase=current_anchor.strip(),
                )
            current_idx = int(m_item.group(1))
            current_title = m_item.group(2).strip()
            current_anchor = ""
            continue

        if current_idx is None:
            continue

        # Anchor phrase line is OPTIONAL and may be formatted in different ways.
        # Accept:
        # - Anchor phrase: **text**
        # - Anchor phrase: `text`
        # - Anchor phrase: text
        m_anchor = re.match(r"^-+\s*Anchor phrase:\s*(?:\*\*(.+?)\*\*|`(.+?)`|(.+?))\s*$", s)
        if m_anchor:
            current_anchor = (m_anchor.group(1) or m_anchor.group(2) or m_anchor.group(3) or "").strip()
            continue

    # Flush last.
    if current_idx is not None:
        out[current_idx] = CorpusItemMeta(
            title=current_title.strip(),
            anchor_phrase=current_anchor.strip(),
        )

    if len(out) != 100:
        raise RuntimeError(f"Expected 100 item metas in {corpus_md}, got {len(out)}")

    return out


def _prefetch_id_to_source(
    *,
    client: weaviate.WeaviateClient,
    repo: str,
    snapshot_id: str,
    source_system_id: str,
) -> Dict[str, str]:
    coll = client.collections.use("RagNode")
    f = (
        Filter.by_property("repo").equal(repo)
        & Filter.by_property("snapshot_id").equal(snapshot_id)
        & Filter.by_property("source_system_id").equal(source_system_id)
    )
    res = coll.query.fetch_objects(
        filters=f,
        limit=500,
        return_properties=["canonical_id", "source_file"],
    )
    out: Dict[str, str] = {}
    for obj in res.objects or []:
        props = obj.properties or {}
        cid = str(props.get("canonical_id") or "").strip()
        src = str(props.get("source_file") or "").strip()
        if cid and src:
            out[cid] = src
    return out


def _source_to_item_idx(corpus: str, source_file: str) -> int:
    if corpus == "csharp":
        m = re.search(r"CorpusItem(\d{3})\.cs$", source_file)
    else:
        m = re.search(r"proc_Corpus_(\d{3})\.sql$", source_file)
    if not m:
        raise RuntimeError(f"Cannot map source_file to item idx: corpus={corpus} source_file={source_file!r}")
    return int(m.group(1))


def _q_heading_label(qid: str) -> str:
    n = int(qid[1:])
    if 1 <= n <= 5:
        return "BM25"
    if 6 <= n <= 10:
        return "Semantic"
    return "Hybrid"


def _md_escape_cell(s: str) -> str:
    # Escape pipe to avoid breaking the markdown table.
    return (s or "").replace("|", "\\|").strip()


def _md_table_top5(items: List[int], item_meta: Dict[int, CorpusItemMeta]) -> List[str]:
    lines: List[str] = []
    lines.append("")
    lines.append("| Rank | Item | Title | Anchor phrase |")
    lines.append("|---:|:---:|---|---|")
    for rank, idx in enumerate(items, start=1):
        meta = item_meta.get(idx)
        if meta is None:
            raise RuntimeError(f"Missing item meta for idx={idx:03d}")
        lines.append(
            f"| {rank} | {idx:03d} | {_md_escape_cell(meta.title)} | {_md_escape_cell(meta.anchor_phrase)} |"
        )
    lines.append("")
    return lines


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--out",
        default="tests/integration/fake_data/retrieval_results_top5_corpus1_corpus2.weaviate.md",
        help="Output markdown path (parse_golden_results compatible).",
    )
    p.add_argument(
        "--weaviate-image",
        default=_WEAVIATE_IMAGE_DEFAULT,
        help=f"Docker image to run (default: {_WEAVIATE_IMAGE_DEFAULT}).",
    )
    p.add_argument(
        "--bundle",
        default="tests/repositories/fake/Release_FAKE_ENTERPRISE_1.0.zip",
        help="Bundle zip to import (default: round-1 primary).",
    )
    p.add_argument(
        "--embed-model",
        default=os.getenv("INTEGRATION_EMBED_MODEL", "models/embedding/e5-base-v2").strip(),
        help="SentenceTransformer model path/name used for BOTH import and query encoding.",
    )
    p.add_argument(
        "--hybrid-alpha",
        type=float,
        default=0.7,
        help="Alpha for Weaviate hybrid queries (must match runtime).",
    )
    p.add_argument(
        "--regen-bundles",
        action="store_true",
        help="Regenerate fake bundles before import (calls tools.generate_retrieval_corpora_bundles).",
    )
    args = p.parse_args()

    repo_root = _repo_root()
    out_path = (repo_root / args.out).resolve()
    bundle_path = (repo_root / args.bundle).resolve()
    embed_model = str(args.embed_model or "").strip()
    if not embed_model:
        raise SystemExit("ERROR: --embed-model is empty (set INTEGRATION_EMBED_MODEL or pass --embed-model).")

    _assert_docker_available()

    # Ensure we compute TRUE Weaviate results (do not activate integration golden proxy).
    os.environ.pop("RUN_INTEGRATION_TESTS", None)

    if args.regen_bundles or not bundle_path.exists():
        _run_command([sys.executable, "-m", "tools.generate_retrieval_corpora_bundles"], cwd=repo_root, timeout_s=600)
    if not bundle_path.exists():
        raise SystemExit(f"ERROR: bundle not found: {bundle_path}")

    # Round-1 permissions: no ACL, no security.
    round1_permissions = {
        "security_enabled": False,
        "acl_enabled": False,
        "require_travel_permission": False,
    }

    backups, _paths = _backup_and_restore_config(repo_root)
    try:
        _write_permissions_config(repo_root, round1_permissions)

        host = "127.0.0.1"
        http_port = _find_free_port()
        grpc_port = _find_free_port()
        while grpc_port == http_port:
            grpc_port = _find_free_port()
        container_name = f"weaviate-golden-{uuid.uuid4().hex[:10]}"

        docker_cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "-p",
            f"{host}:{http_port}:8080",
            "-p",
            f"{host}:{grpc_port}:50051",
            "-e",
            "QUERY_DEFAULTS_LIMIT=25",
            "-e",
            "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true",
            "-e",
            "PERSISTENCE_DATA_PATH=/var/lib/weaviate",
            "-e",
            "DEFAULT_VECTORIZER_MODULE=none",
            "-e",
            "ENABLE_MODULES=",
            "-e",
            "CLUSTER_HOSTNAME=node1",
            args.weaviate_image,
        ]

        # Start container
        _run_command(docker_cmd, cwd=repo_root, timeout_s=90)
        try:
            _wait_for_weaviate_ready(host=host, http_port=http_port, timeout_s=180)

            # Import bundle (use same python env)
            import_cmd = [
                sys.executable,
                "-m",
                "tools.weaviate.import_branch_to_weaviate",
                "--bundle",
                str(bundle_path),
                "--weaviate-host",
                host,
                "--weaviate-http-port",
                str(http_port),
                "--weaviate-grpc-port",
                str(grpc_port),
                "--embed-model",
                embed_model,
                "--ref-type",
                "tag",
                "--ref-name",
                bundle_path.stem,
                "--tag",
                bundle_path.stem,
                "--import-id",
                f"golden::{bundle_path.stem}",
            ]
            import_env = dict(os.environ)
            # Ensure schema matches round-1 regardless of user's shell environment.
            import_env["ACL_ENABLED"] = "false"
            import_env["REQUIRE_TRAVEL_PERMISSION"] = "false"
            _run_command(import_cmd, cwd=repo_root, timeout_s=1800, env=import_env)

            meta = _read_repo_meta(bundle_path)
            repo = meta["repo"] or "Fake"
            snapshot_id = meta["snapshot_id"]
            if not snapshot_id:
                raise RuntimeError(f"Could not read snapshot_id from bundle meta: {bundle_path}")

            # Parse query sets + item meta (source of truth).
            corpus_dir = repo_root / "tests" / "integration" / "fake_data"
            csharp_corpus_path = corpus_dir / "csharp_corpus_100_items_with_queries.md"
            sql_corpus_path = corpus_dir / "sql_corpus_100_items_with_queries.md"

            csharp_queries = _parse_query_sets(csharp_corpus_path)
            sql_queries = _parse_query_sets(sql_corpus_path)

            csharp_item_meta = _parse_item_meta(csharp_corpus_path)
            sql_item_meta = _parse_item_meta(sql_corpus_path)

            # Connect + build backend.
            client = weaviate.connect_to_local(host=host, port=http_port, grpc_port=grpc_port)
            try:
                backend = WeaviateRetrievalBackend(
                    client=client,
                    query_embed_model=embed_model,
                    security_config=round1_permissions,
                )

                # Prefetch mapping canonical_id -> source_file (per corpus).
                id2src_csharp = _prefetch_id_to_source(
                    client=client,
                    repo=repo,
                    snapshot_id=snapshot_id,
                    source_system_id="code.csharp",
                )
                id2src_sql = _prefetch_id_to_source(
                    client=client,
                    repo=repo,
                    snapshot_id=snapshot_id,
                    source_system_id="code.sql",
                )

                report_lines: List[str] = []
                report_lines.append("# Retrieval Results Report (Top-5 per query) — Generated From Weaviate Runtime")
                report_lines.append("")
                report_lines.append(
                    f"Generated by `python -m tools.generate_retrieval_goldens_from_weaviate` "
                    f"using Weaviate `{args.weaviate_image}` and embed model `{embed_model}`."
                )
                report_lines.append("")

                def build_corpus_block(
                    *,
                    corpus: str,
                    queries: CorpusQueries,
                    id2src: Dict[str, str],
                    item_meta: Dict[int, CorpusItemMeta],
                ) -> None:
                    title = "C# (100 items)" if corpus == "csharp" else "SQL/T-SQL (100 items)"
                    report_lines.append("---")
                    report_lines.append("")
                    report_lines.append(f"## Corpus {'1' if corpus == 'csharp' else '2'} — {title}")
                    report_lines.append("")

                    source_system_id = "code.csharp" if corpus == "csharp" else "code.sql"
                    for qid, query_text in queries.as_q_list():
                        report_lines.append(f"### {qid} ({_q_heading_label(qid)})")
                        report_lines.append("")
                        # IMPORTANT: parser expects backticks.
                        report_lines.append(f"**Query:** `{query_text}`")
                        report_lines.append("")

                        for method in ("bm25", "semantic", "hybrid"):
                            hdr = "BM25" if method == "bm25" else ("Semantic" if method == "semantic" else "Hybrid")
                            report_lines.append(f"#### {hdr} — Top 5")

                            rf = {
                                "source_system_id": source_system_id,
                                "hybrid_alpha": float(args.hybrid_alpha),
                            }
                            req = SearchRequest(
                                search_type=method,  # type: ignore[arg-type]
                                query=query_text,
                                top_k=5,
                                repository=repo,
                                snapshot_id=snapshot_id,
                                retrieval_filters=rf,
                            )
                            resp = backend.search(req)
                            hits = list(resp.hits or [])

                            items: List[int] = []
                            for h in hits:
                                src = id2src.get(h.id)
                                if not src:
                                    raise RuntimeError(f"Missing source_file for hit id: {h.id}")
                                items.append(_source_to_item_idx(corpus, src))

                            report_lines.extend(_md_table_top5(items, item_meta))


                build_corpus_block(
                    corpus="csharp",
                    queries=csharp_queries,
                    id2src=id2src_csharp,
                    item_meta=csharp_item_meta,
                )
                build_corpus_block(
                    corpus="sql",
                    queries=sql_queries,
                    id2src=id2src_sql,
                    item_meta=sql_item_meta,
                )

                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")

                print(f"Wrote: {out_path}")
            finally:
                try:
                    client.close()
                except Exception:
                    pass
        finally:
            subprocess.run(["docker", "rm", "-f", container_name], text=True, capture_output=True, check=False)
    finally:
        _restore_config(backups)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
