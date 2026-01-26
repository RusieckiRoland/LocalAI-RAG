from __future__ import annotations

import logging
import csv
import json
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, DefaultDict, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .ports import IGraphProvider

py_logger = logging.getLogger(__name__)



def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for x in items:
        v = (x or "").strip()
        if not v:
            continue
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _strip_part_suffix(node_id: str) -> str:
    """
    Convert "<key>:part=<n>" into "<key>" (common for db_code chunk ids).
    If no suffix is present, return the input unchanged.
    """
    v = (node_id or "").strip()
    if not v:
        return v
    if ":part=" in v:
        return v.split(":part=", 1)[0]
    return v

def _strip_branch_namespace(node_id: str, repo: str, branch: str) -> str:
    """
    Convert canonical ids back into local ids for filesystem bundle lookups.

    Canonical format:
        <repo>::<branch>::<local_id>

    If the node_id is already local, it is returned unchanged.
    """
    v = (node_id or "").strip()
    if not v:
        return v
    r = (repo or "").strip()
    b = (branch or "").strip()
    if not r or not b:
        return v
    prefix = f"{r}::{b}::"
    if v.startswith(prefix):
        return v[len(prefix) :]
    return v


def _make_canonical_id(repo: str, branch: str, local_id: str) -> str:
    """
    Canonical, globally unique node id. See _strip_branch_namespace() for inverse.
    """
    r = (repo or "").strip()
    b = (branch or "").strip()
    lid = (local_id or "").strip()
    if not r or not b or not lid:
        raise ValueError("_make_canonical_id: repo, branch and local_id are required")
    return f"{r}::{b}::{lid}"



@dataclass(frozen=True)
class _BundlePaths:
    branch_root: str
    chunks_json: str
    dependencies_json: str
    sql_bodies_jsonl: str
    sql_edges_csv: str


class FileSystemGraphProvider(IGraphProvider):
    """
    Minimal, file-system based graph provider.

    Expected repository layout (see HOW_TO_PREPARE_REPO.md):

    repositories/
      <repo>/
        branches/
          <branch>/
            regular_code_bundle/
              chunks.json
              dependencies.json
            sql_bundle/                # preferred
              docs/sql_bodies.jsonl
              graph/edges.csv
            sql_code_bundle/           # legacy (also supported)
              docs/sql_bodies.jsonl
              graph/edges.csv
        indexes/
          <active_index>/   # not required by this provider (kept for scoping consistency)
    """

    def __init__(self, *, repositories_root: str = "repositories") -> None:
        self.repositories_root = repositories_root

        # Caches keyed by (repo, branch)
        self._chunks_cache: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
        self._sql_cache: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
        self._adj_cache: Dict[Tuple[str, str], Dict[str, List[Tuple[str, str]]]] = {}

    # ------------------------------ #
    # Path resolution
    # ------------------------------ #

    def _resolve_paths(self, *, repository: str, branch: str) -> _BundlePaths:
        repo_root = os.path.join(self.repositories_root, repository)
        branch_root = os.path.join(repo_root, "branches", branch)

        # Backward compatibility:
        # Some old zips were extracted into branches/<branch>/<branch>/...
        direct_code = os.path.join(branch_root, "regular_code_bundle")
        nested_root = os.path.join(branch_root, branch)
        nested_code = os.path.join(nested_root, "regular_code_bundle")

        if os.path.isdir(direct_code):
            effective_root = branch_root
        elif os.path.isdir(nested_code):
            effective_root = nested_root
        else:
            effective_root = branch_root

        chunks_json = os.path.join(effective_root, "regular_code_bundle", "chunks.json")
        dependencies_json = os.path.join(effective_root, "regular_code_bundle", "dependencies.json")

        # Prefer sql_bundle if either bodies OR edges exist.
        sql_bundle_bodies = os.path.join(effective_root, "sql_bundle", "docs", "sql_bodies.jsonl")
        sql_bundle_edges = os.path.join(effective_root, "sql_bundle", "graph", "edges.csv")

        # Legacy fallback: sql_code_bundle (also if either bodies OR edges exist there).
        sql_code_bodies = os.path.join(effective_root, "sql_code_bundle", "docs", "sql_bodies.jsonl")
        sql_code_edges = os.path.join(effective_root, "sql_code_bundle", "graph", "edges.csv")

        if os.path.isfile(sql_bundle_bodies) or os.path.isfile(sql_bundle_edges):
            sql_bodies_jsonl = sql_bundle_bodies
            sql_edges_csv = sql_bundle_edges
        elif os.path.isfile(sql_code_bodies) or os.path.isfile(sql_code_edges):
            sql_bodies_jsonl = sql_code_bodies
            sql_edges_csv = sql_code_edges
        else:
            # Default to preferred layout even if files are missing (deterministic paths).
            sql_bodies_jsonl = sql_bundle_bodies
            sql_edges_csv = sql_bundle_edges

        return _BundlePaths(
            branch_root=effective_root,
            chunks_json=chunks_json,
            dependencies_json=dependencies_json,
            sql_bodies_jsonl=sql_bodies_jsonl,
            sql_edges_csv=sql_edges_csv,
        )


    # ------------------------------ #
    # Loaders
    # ------------------------------ #

    def _load_chunks(self, *, repository: str, branch: str) -> Dict[str, Dict[str, Any]]:
        key = (repository, branch)
        if key in self._chunks_cache:
            return self._chunks_cache[key]

        paths = self._resolve_paths(repository=repository, branch=branch)
        chunks_by_id: Dict[str, Dict[str, Any]] = {}

        if os.path.isfile(paths.chunks_json):
            try:
                with open(paths.chunks_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for c in data:
                        if not isinstance(c, dict):
                            continue
                        cid = c.get("Id")
                        if cid is None:
                            continue
                        chunks_by_id[str(cid)] = c
            except Exception:
                py_logger.exception(
                    "soft-failure: failed to load chunks.json (repository=%s branch=%s path=%s)",
                    repository,
                    branch,
                    paths.chunks_json,
                )
                # Stay resilient; return empty mapping on any parsing error.
                chunks_by_id = {}

        self._chunks_cache[key] = chunks_by_id
        return chunks_by_id

    def _load_sql_bodies(self, *, repository: str, branch: str) -> Dict[str, Dict[str, Any]]:
        key = (repository, branch)
        if key in self._sql_cache:
            return self._sql_cache[key]

        paths = self._resolve_paths(repository=repository, branch=branch)
        by_key: Dict[str, Dict[str, Any]] = {}

        if os.path.isfile(paths.sql_bodies_jsonl):
            try:
                with open(paths.sql_bodies_jsonl, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(obj, dict):
                            continue
                        k = obj.get("key") or obj.get("Key")
                        if not k:
                            continue
                        by_key[str(k)] = obj
            except Exception:
                py_logger.exception(
                    "soft-failure: failed to load sql_bodies.jsonl (repository=%s branch=%s path=%s)",
                    repository,
                    branch,
                    paths.sql_bodies_jsonl,
                )
                by_key = {}

        self._sql_cache[key] = by_key
        return by_key

    def _build_adjacency(self, *, repository: str, branch: str) -> Dict[str, List[Tuple[str, str]]]:
        key = (repository, branch)
        if key in self._adj_cache:
            return self._adj_cache[key]

        paths = self._resolve_paths(repository=repository, branch=branch)

        adj: DefaultDict[str, List[Tuple[str, str]]] = defaultdict(list)

        # 1) Regular code dependency graph (chunk_id -> [chunk_id])
        if os.path.isfile(paths.dependencies_json):
            try:
                with open(paths.dependencies_json, "r", encoding="utf-8") as f:
                    deps = json.load(f)
                if isinstance(deps, dict):
                    for frm, tos in deps.items():
                        frm_id = str(frm)
                        if isinstance(tos, list):
                            for to in tos:
                                to_id = str(to)
                                if not to_id:
                                    continue
                                adj[frm_id].append(("calls", to_id))
                                # Make it undirected by default (useful for "what references this?")
                                adj[to_id].append(("calls", frm_id))
            except Exception:
                py_logger.exception(
                    "soft-failure: failed to load dependencies.json (repository=%s branch=%s path=%s)",
                    repository,
                    branch,
                    paths.dependencies_json,
                )
                pass

        # 2) SQL graph edges (Key -> Key) + potentially cross edges
        if os.path.isfile(paths.sql_edges_csv):
            try:
                with open(paths.sql_edges_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        frm = (row.get("from") or row.get("From") or "").strip()
                        to = (row.get("to") or row.get("To") or "").strip()
                        rel = (row.get("relation") or row.get("Relation") or "sql_edge").strip()
                        if not frm or not to:
                            continue
                        adj[frm].append((rel, to))
                        # Include reverse link (helps traversing "used by")
                        adj[to].append((rel, frm))
            except Exception:
                py_logger.exception(
                    "soft-failure: failed to load sql_edges.csv (repository=%s branch=%s path=%s)",
                    repository,
                    branch,
                    paths.sql_edges_csv,
                )
                pass

        self._adj_cache[key] = dict(adj)
        return self._adj_cache[key]

    # ------------------------------ #
    # IGraphProvider API (Option A)
    # ------------------------------ #

    def expand_dependency_tree(
        self,
        *,
        seed_nodes: List[str],
        max_depth: int = 2,
        max_nodes: int = 200,
        edge_allowlist: Optional[List[str]] = None,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        active_index: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # active_index kept for scoping consistency; provider is branch-bundle based for now.
        _ = active_index

        repo = (repository or "").strip()
        br = (branch or "").strip()
        seeds = _dedupe_preserve_order(
            _strip_part_suffix(_strip_branch_namespace(str(s), repo, br)) for s in (seed_nodes or [])
        )

        if not seeds:
            return {"nodes": [], "edges": []}

        # Branch is REQUIRED for graph back-search scoping.
        if not repo:
            raise ValueError("Missing required 'repository' for graph expansion.")
        if not br:
            raise ValueError("Missing required 'branch' for graph expansion.")

        allow = {str(x).strip().lower() for x in (edge_allowlist or []) if str(x).strip()}
        allow_all = (not allow) or ("*" in allow)

        adj = self._build_adjacency(repository=repo, branch=br)

        chunks_by_id = self._load_chunks(repository=repo, branch=br)
        sql_by_key = self._load_sql_bodies(repository=repo, branch=br)

        # Accept nodes that exist in the graph even if their bodies are not present.
        # This is required for minimal SQL-bundle tests that provide only edges.csv.
        known_ids: Set[str] = set(chunks_by_id.keys()) | set(sql_by_key.keys()) | set(adj.keys())
        for _src, _tos in adj.items():
            for _to in _tos:
                known_ids.add(_to)

        missing_seeds = [s for s in seeds if s not in known_ids]
        if missing_seeds:
            sample = ", ".join(missing_seeds[:10])
            raise ValueError(
                "Graph bundle inconsistency: seed node ids not found in branch bundle "
                f"(repository={repo} branch={br} missing_seeds={len(missing_seeds)} sample={sample})"
            )


        # Fail-fast: if graph points to ids missing in the branch bundle, the bundle is inconsistent.
        missing_edges: List[Tuple[str, str]] = []

        visited: Set[str] = set()
        q: Deque[Tuple[str, int]] = deque()

        for s in seeds:
            visited.add(s)
            q.append((s, 0))

        edges_out: List[Dict[str, Any]] = []
        ordered_nodes: List[str] = list(seeds)

        while q and len(visited) < max_nodes:
            node, depth = q.popleft()
            if depth >= max_depth:
                continue

            for rel, to in adj.get(node, []):
                rel_l = (rel or "").strip().lower()
                if not allow_all and rel_l not in allow:
                    continue

                to_norm = _strip_part_suffix(_strip_branch_namespace(str(to), repo, br))
                from_id = _make_canonical_id(repo, br, node)
                to_id = _make_canonical_id(repo, br, to_norm)
                edges_out.append({"from": from_id, "to": to_id, "type": rel, "depth": depth + 1})

                if to_norm not in known_ids:
                    missing_edges.append((node, to_norm))
                    continue

                if to_norm in visited:
                    continue

                visited.add(to_norm)
                ordered_nodes.append(to_norm)

                if len(visited) >= max_nodes:
                    break

                q.append((to_norm, depth + 1))

        if missing_edges:
            sample = ", ".join([f"{a}->{b}" for a, b in missing_edges[:10]])
            raise ValueError(
                "Graph bundle inconsistency: dependencies.json contains edges to missing nodes "
                f"(repository={repo} branch={br} missing_edges={len(missing_edges)} sample={sample})"
            )

        return {"nodes": [_make_canonical_id(repo, br, n) for n in ordered_nodes], "edges": edges_out}

    def fetch_node_texts(
            self,
            *,
            node_ids: List[str],
            repository: Optional[str] = None,
            branch: Optional[str] = None,
            active_index: Optional[str] = None,
            max_chars: int = 50_000,
        ) -> List[Dict[str, Any]]:
            # active_index kept for scoping consistency; provider is branch-bundle based for now.
            _ = active_index

            repo = (repository or "").strip()
            br = (branch or "").strip()

            raw_ids = _dedupe_preserve_order(str(n).strip() for n in (node_ids or []) if str(n).strip())

            # Preserve requested ids (canonical) for the output mapping, but resolve content using local ids.
            pairs: List[Tuple[str, str]] = [
                (rid, _strip_part_suffix(_strip_branch_namespace(rid, repo, br))) for rid in raw_ids
            ]
            picked = _dedupe_preserve_order(local_id for _, local_id in pairs)
            if not picked:
                return []

            # Branch is REQUIRED for fetching node texts (path is branch-scoped).
            if not repo:
                raise ValueError("Missing required 'repository' for graph node fetch.")
            if not br:
                raise ValueError("Missing required 'branch' for graph node fetch.")

            used = 0
            out: List[Dict[str, Any]] = []

            chunks = self._load_chunks(repository=repo, branch=br)
            sql = self._load_sql_bodies(repository=repo, branch=br)

            # Resolve each unique local node id once, then map back to requested ids.
            text_by_local: Dict[str, str] = {}

            for nid in picked:
                t = ""

                # C# chunk (by chunk Id)
                if nid in chunks:
                    c = chunks[nid]
                    file_path = c.get("File") or c.get("file") or ""
                    body = c.get("Text") or c.get("Content") or ""
                    body = str(body or "").strip()
                    if file_path:
                        t = f"### File: {file_path}\n{body}".strip()
                    else:
                        t = str(body or "")

                # SQL node (by Key)
                elif nid in sql:
                    s = sql[nid]
                    kind = s.get("kind") or s.get("Kind") or "Object"
                    schema = s.get("schema") or s.get("Schema") or "dbo"
                    name = s.get("name") or s.get("Name") or ""
                    body = s.get("body") or s.get("Body") or ""
                    header = f"[SQL {kind}] {schema}.{name}".strip()
                    t = f"{header}\n{body}".strip()

                if t:
                    remaining = max(0, int(max_chars) - used)
                    if remaining <= 0:
                        break
                    if len(t) > remaining:
                        t = t[:remaining]
                    used += len(t)

                text_by_local[nid] = t

                if used >= max_chars:
                    break

            for requested_id, local_id in pairs:
                t = text_by_local.get(local_id, "")
                out.append({"id": requested_id, "text": t})

            return out

