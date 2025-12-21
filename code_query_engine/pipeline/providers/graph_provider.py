from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class GraphEdge:
    src: str
    dst: str
    kind: str = ""


class GraphProvider:
    """
    File-based graph provider.

    It resolves a graph directory under repositories_root and supports two inputs:
      - edges.csv (preferred): a CSV with at least (from,to) columns (aliases supported).
      - dependencies.json (fallback): a mapping { "<node_id>": ["<node_id>", ...], ... }.

    This provider is intentionally conservative:
      - never reaches outside repositories_root,
      - fails gracefully when artifacts are missing.
    """

    def __init__(self, *, repositories_root: str = "repositories") -> None:
        self._repositories_root = Path(repositories_root)

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
        graph_dir = self._resolve_graph_dir(repository=repository, branch=branch, active_index=active_index)
        if graph_dir is None:
            return {"nodes": list(seed_nodes), "edges": []}

        edges = self._load_edges(graph_dir)

        if edge_allowlist:
            allow: Set[str] = {x.strip() for x in edge_allowlist if str(x).strip()}
            edges = [e for e in edges if (e.kind or "") in allow]

        adj: Dict[str, List[GraphEdge]] = {}
        for e in edges:
            adj.setdefault(e.src, []).append(e)

        # deterministic iteration
        for k in list(adj.keys()):
            adj[k] = sorted(adj[k], key=lambda x: (x.dst, x.kind))

        visited: Set[str] = set()
        out_nodes: List[str] = []
        out_edges: List[Dict[str, Any]] = []

        frontier: List[Tuple[str, int]] = [(s, 0) for s in seed_nodes]
        while frontier:
            node, depth = frontier.pop(0)
            if node in visited:
                continue
            visited.add(node)
            out_nodes.append(node)

            if len(out_nodes) >= max_nodes:
                break

            if depth >= max_depth:
                continue

            for e in adj.get(node, []):
                out_edges.append({"from": e.src, "to": e.dst, "type": e.kind})
                if e.dst not in visited:
                    frontier.append((e.dst, depth + 1))

                if len(out_nodes) + len(frontier) >= max_nodes:
                    frontier = frontier[: max(0, max_nodes - len(out_nodes))]
                    break

        out_nodes = sorted(set(out_nodes))
        out_edges = sorted(out_edges, key=lambda x: (x.get("from", ""), x.get("to", ""), x.get("type", "")))

        return {"nodes": out_nodes, "edges": out_edges}

    def fetch_node_texts(
        self,
        *,
        node_ids: List[str],
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        active_index: Optional[str] = None,
        max_chars: int = 50_000,
    ) -> List[Dict[str, Any]]:
        graph_dir = self._resolve_graph_dir(repository=repository, branch=branch, active_index=active_index)
        if graph_dir is None:
            return [{"id": str(nid), "text": ""} for nid in node_ids]

        nodes_json = graph_dir / "nodes.json"
        if not nodes_json.exists():
            return [{"id": str(nid), "text": ""} for nid in node_ids]

        try:
            data = json.loads(nodes_json.read_text(encoding="utf-8"))
        except Exception:
            return [{"id": str(nid), "text": ""} for nid in node_ids]

        by_id: Dict[str, str] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    by_id[str(k)] = v
                elif isinstance(v, dict):
                    txt = v.get("text") or v.get("Text") or ""
                    if isinstance(txt, str):
                        by_id[str(k)] = txt
        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                nid = item.get("id") or item.get("Id")
                txt = item.get("text") or item.get("Text") or ""
                if nid and isinstance(txt, str):
                    by_id[str(nid)] = txt

        out: List[Dict[str, Any]] = []
        used = 0
        for nid in node_ids:
            t = by_id.get(str(nid), "")
            if t and used + len(t) > max_chars:
                t = t[: max(0, max_chars - used)]
            used += len(t)

            out.append({"id": str(nid), "text": t})

            if used >= max_chars:
                break

        return out

    def _resolve_graph_dir(
        self,
        *,
        repository: Optional[str],
        branch: Optional[str],
        active_index: Optional[str],
    ) -> Optional[Path]:
        repo_root = self._repositories_root

        env_root = os.getenv("RAG_REPOSITORIES_ROOT")
        if env_root:
            repo_root = Path(env_root)

        if repository:
            base = repo_root / repository
        else:
            base = repo_root

        snapshot = active_index or branch
        candidates: List[Path] = []
        if snapshot:
            candidates.append(base / "branches" / snapshot / "sql_bundle" / "graph")
            candidates.append(base / snapshot / "sql_bundle" / "graph")
        candidates.append(base / "sql_bundle" / "graph")

        for c in candidates:
            if c.exists() and c.is_dir():
                return c

        return None

    def _load_edges(self, graph_dir: Path) -> List[GraphEdge]:
        edges_csv = graph_dir / "edges.csv"
        if edges_csv.exists():
            return self._load_edges_csv(edges_csv)

        deps_json = graph_dir / "dependencies.json"
        if deps_json.exists():
            return self._load_edges_deps_json(deps_json)

        return []

    def _load_edges_csv(self, path: Path) -> List[GraphEdge]:
        try:
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                edges: List[GraphEdge] = []
                for row in reader:
                    src = (
                        row.get("from")
                        or row.get("From")
                        or row.get("source")
                        or row.get("Source")
                        or row.get("src")
                        or row.get("Src")
                    )
                    dst = (
                        row.get("to")
                        or row.get("To")
                        or row.get("target")
                        or row.get("Target")
                        or row.get("dst")
                        or row.get("Dst")
                    )
                    kind = row.get("type") or row.get("Type") or row.get("edge_type") or row.get("EdgeType") or ""
                    if not src or not dst:
                        continue
                    edges.append(GraphEdge(src=str(src), dst=str(dst), kind=str(kind or "")))
                return edges
        except Exception:
            return []

    def _load_edges_deps_json(self, path: Path) -> List[GraphEdge]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        edges: List[GraphEdge] = []
        for k, v in data.items():
            if not isinstance(v, list):
                continue
            for dst in v:
                if dst is None:
                    continue
                edges.append(GraphEdge(src=str(k), dst=str(dst), kind="dependency"))
        return edges
