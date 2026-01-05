# code_query_engine/pipeline/providers/graph_provider.py
from __future__ import annotations

import csv
import logging
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional, Set, Tuple

from .file_system_graph_provider import FileSystemGraphProvider, _BundlePaths

py_logger = logging.getLogger(__name__)


def _canon_relation(rel: str) -> str:
    """
    Canonicalize relation labels so YAML allowlist can remain stable.

    - "ForeignKey" <-> "FK" => always emit "FK"
    """
    r = (rel or "").strip()
    rl = r.lower()
    if rl in ("foreignkey", "fk"):
        return "FK"
    return r


class GraphProvider(FileSystemGraphProvider):
    """
    Default graph provider used by DynamicPipeline.

    It is intentionally a thin adapter over FileSystemGraphProvider, but adds:
    - FK canonicalization ("ForeignKey" => "FK")
    - synthetic "ReferencedBy(C#)" edges from SQL nodes to C# nodes
      (created from edges where 'from' startswith "csharp:")
    """

    def _build_adjacency(self, *, repository: str, branch: str) -> Dict[str, List[Tuple[str, str]]]:
        """
        Build adjacency with small, controlled semantic upgrades:
        - normalize FK edges to "FK"
        - add "ReferencedBy(C#)" edges: SQL -> C# (based on any C# -> SQL edge)
        """
        key = f"{repository}::{branch}"
        if key in self._adj_cache:
            return self._adj_cache[key]

        paths: _BundlePaths = self._resolve_paths(repository=repository, branch=branch)

        # adjacency: node -> list[(relation, neighbor)]
        adj: DefaultDict[str, List[Tuple[str, str]]] = defaultdict(list)

        # -------- load dependencies.json (C# chunk graph) --------
        try:
            deps = self._load_dependencies(repository=repository, branch=branch)
            # deps: { "node_id": [{ "to": "...", "type": "calls" }, ...], ... }  (shape used by your bundles)
            for frm, links in (deps or {}).items():
                if not frm:
                    continue
                if not isinstance(links, list):
                    continue
                for e in links:
                    if not isinstance(e, dict):
                        continue
                    to = (e.get("to") or "").strip()
                    rel = (e.get("type") or "").strip()
                    if not to or not rel:
                        continue
                    rel2 = _canon_relation(rel)
                    adj[frm].append((rel2, to))
                    # reverse link (helps "used by" traversal)
                    adj[to].append((rel2, frm))
        except Exception:
            py_logger.exception(
                "soft-failure: failed to load dependencies.json (repository=%s branch=%s path=%s)",
                repository,
                branch,
                paths.dependencies_json,
            )

        # -------- load sql_edges.csv (SQL/EF/MIGRATION graph) --------
        try:
            if paths.sql_edges_csv:
                with open(paths.sql_edges_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        frm = (row.get("from") or row.get("From") or "").strip()
                        to = (row.get("to") or row.get("To") or "").strip()
                        rel = (row.get("relation") or row.get("Relation") or "").strip()

                        if not frm or not to:
                            continue

                        rel2 = _canon_relation(rel or "")

                        # normal directed edge + reverse (same as base provider)
                        if rel2:
                            adj[frm].append((rel2, to))
                            adj[to].append((rel2, frm))

                        # synthetic: SQL object is referenced by C# node
                        # This is intentionally a separate relation so YAML allowlist can control it.
                        if frm.lower().startswith("csharp:"):
                            adj[to].append(("ReferencedBy(C#)", frm))
        except Exception:
            py_logger.exception(
                "soft-failure: failed to load sql_edges.csv (repository=%s branch=%s path=%s)",
                repository,
                branch,
                paths.sql_edges_csv,
            )

        self._adj_cache[key] = dict(adj)
        return self._adj_cache[key]
