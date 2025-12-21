from __future__ import annotations

import csv
import json
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, DefaultDict, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .ports import IGraphProvider


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
            sql_bundle/
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

        # Some zips are extracted into branches/<branch>/<branch>/...
        # Prefer the direct layout, fallback to the nested one.
        direct_code = os.path.join(branch_root, "regular_code_bundle")
        nested_root = os.path.join(branch_root, branch)
        nested_code = os.path.join(nested_root, "regular_code_bundle")
        if os.path.isdir(direct_code):
            effective_root = branch_root
        elif os.path.isdir(nested_code):
            effective_root = nested_root
        else:
            # Keep deterministic: point to direct layout; loader will treat missing files as empty.
            effective_root = branch_root

        chunks_json = os.path.join(effective_root, "regular_code_bundle", "chunks.json")
        dependencies_json = os.path.join(effective_root, "regular_code_bundle", "dependencies.json")
        sql_bodies_jsonl = os.path.join(effective_root, "sql_bundle", "docs", "sql_bodies.jsonl")
        sql_edges_csv = os.path.join(effective_root, "sql_bundle", "graph", "edges.csv")

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
                                adj[frm_id].append(("code_dep", to_id))
                                # Make it undirected by default (useful for "what references this?")
                                adj[to_id].append(("code_dep", frm_id))
            except Exception:
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
    ) -> Dict[str, Any]:
        # active_index kept for scoping consistency; provider is branch-bundle based for now.
        _ = active_index

        repo = (repository or "").strip()
        br = (branch or "").strip()
        seeds = _dedupe_preserve_order(_strip_part_suffix(s) for s in (seed_nodes or []))

        if not repo or not br or not seeds:
            return {"nodes": seeds, "edges": []}

        allow = {str(x).strip().lower() for x in (edge_allowlist or []) if str(x).strip()}
        allow_all = (not allow) or ("*" in allow)

        adj = self._build_adjacency(repository=repo, branch=br)

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

                to_norm = _strip_part_suffix(to)
                edges_out.append({"from": node, "to": to_norm, "type": rel, "depth": depth + 1})

                if to_norm in visited:
                    continue

                visited.add(to_norm)
                ordered_nodes.append(to_norm)

                if len(visited) >= max_nodes:
                    break

                q.append((to_norm, depth + 1))

        return {"nodes": ordered_nodes, "edges": edges_out}

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

        picked = _dedupe_preserve_order(_strip_part_suffix(str(n)) for n in (node_ids or []))
        if not repo or not br or not picked:
            return [{"id": nid, "text": ""} for nid in picked]

        chunks = self._load_chunks(repository=repo, branch=br)
        sql = self._load_sql_bodies(repository=repo, branch=br)

        out: List[Dict[str, Any]] = []
        used = 0

        for nid in picked:
            t = ""

            # C# chunk (by chunk Id)
            if nid in chunks:
                c = chunks[nid]
                file_path = (c.get("File") or "").strip()
                body = c.get("Text") or ""
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

            out.append({"id": nid, "text": t})

            if used >= max_chars:
                break

        return out
