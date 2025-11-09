# File: common/sqlrag_core.py
import os
import json
import csv
import faiss
import numpy as np
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from sentence_transformers import SentenceTransformer

"""
SQL RAG core utilities.

This module loads:
- FAISS index with SQL object embeddings,
- object metadata (JSON),
- optional dependency graph (CSV with directed edges).

It exposes a small API:
- SqlRagCore.search(...)       -> top-K nearest neighbors with optional graph expansion
- SqlRagCore.neighbors(key)    -> immediate graph neighbors (radius=1)
- SqlRagCore.get_body(key)     -> source body (lazy-read with a small in-memory cache)

Notes:
- All messages and docstrings are in English to keep the public repository professional.
- Keys returned in result dictionaries intentionally keep their original casing (e.g., "Key", "Kind").
"""


# ===============================
# Core: load FAISS + graph, search, neighborhood
# ===============================

class SqlRagCore:
    def __init__(
        self,
        base_path: str,
        model_path: str,
        use_gpu: bool = True,
        faiss_filename: str = "sql_index.faiss",
        meta_filename: str = "sql_metadata.json",
        bodies_filename: str = "sql_bodies.jsonl",
        edges_csv_relpath: Optional[str] = None,
    ) -> None:
        """
        Parameters
        ----------
        base_path : str
            Can point to either:
            - a `docs/` directory (where `sql_bodies.jsonl` lives), OR
            - a branch directory that contains `sql_bundle/docs/` and `sql_bundle/graph/`.
        model_path : str
            Path to a SentenceTransformer model (as in your config).
        use_gpu : bool
            Whether GPU should be used for embeddings (the FAISS index here uses CPU; adjust if needed).
        faiss_filename : str
            Filename of the FAISS index inside the resolved docs directory.
        meta_filename : str
            Filename of the metadata JSON adjacent to the FAISS index.
        bodies_filename : str
            JSONL file with bodies (one object per line).
        edges_csv_relpath : Optional[str]
            Path to the CSV with graph edges. If relative, it will be resolved under the graph directory.
        """
        self.base_path = os.path.abspath(base_path)
        self.model_path = model_path
        self.use_gpu = use_gpu

        self.docs_dir, self.graph_dir = self._resolve_dirs(self.base_path)
        self.faiss_path = os.path.join(self.docs_dir, faiss_filename)
        self.meta_path = os.path.join(self.docs_dir, meta_filename)
        self.bodies_path = os.path.join(self.docs_dir, bodies_filename)
        self.edges_csv_path = (
            edges_csv_relpath
            if edges_csv_relpath and os.path.isabs(edges_csv_relpath)
            else (
                os.path.join(self.graph_dir, edges_csv_relpath)
                if edges_csv_relpath
                else os.path.join(self.graph_dir, "edges.csv")
            )
        )

        # Embedding model
        self.model = SentenceTransformer(self.model_path)

        # FAISS
        self.index = self._load_faiss(self.faiss_path)

        # Metadata
        self.metadata = self._load_metadata(self.meta_path)
        if len(self.metadata) != self.index.ntotal:
            raise RuntimeError(f"Mismatch: metadata={len(self.metadata)} vs index.ntotal={self.index.ntotal}")

        # Graph (optional)
        self.edges_out, self.edges_in = self._load_edges(self.edges_csv_path)

        # Body cache (small, lazily filled)
        self._body_cache: Dict[str, str] = {}
        self._body_cache_cap = 128

    # ---------- path resolution ----------
    def _resolve_dirs(self, base: str) -> Tuple[str, str]:
        """
        Resolve the effective docs/ and graph/ directories starting from `base`.

        Returns
        -------
        Tuple[str, str]
            (docs_dir, graph_dir)

        Raises
        ------
        FileNotFoundError
            If a docs directory with `sql_bodies.jsonl` cannot be located.
        """
        # If user points directly at docs/, also check common alternatives
        cand_docs = [
            base,
            os.path.join(base, "sql_bundle", "docs"),
            os.path.join(base, "docs"),
        ]
        for d in cand_docs:
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, "sql_bodies.jsonl")):
                # try "graph" next to docs
                graph_dir = (
                    os.path.join(os.path.dirname(d), "graph")
                    if os.path.basename(d) == "docs"
                    else os.path.join(os.path.dirname(os.path.dirname(d)), "graph")
                )
                if not os.path.isdir(graph_dir):
                    # fallback: probe one level up
                    maybe = os.path.join(os.path.dirname(d), "graph")
                    graph_dir = maybe if os.path.isdir(maybe) else os.path.dirname(d)
                return d, graph_dir
        raise FileNotFoundError(f"Could not find docs/sql_bodies.jsonl starting from: {base}")

    # ---------- loaders ----------
    def _load_faiss(self, faiss_path: str):
        """
        Load a FAISS index from disk.

        Notes
        -----
        - GPU should only be enabled if you really need it for your workflow.
          For typical query workloads a CPU index is sufficient.
        """
        if not os.path.isfile(faiss_path):
            raise FileNotFoundError(f"FAISS index not found: {faiss_path}")
        idx = faiss.read_index(faiss_path)
        # NOTE: currently returning a CPU index; adapt if you need a GPU index
        return idx

    def _load_metadata(self, meta_path: str) -> List[dict]:
        """Load metadata JSON (list with per-vector objects)."""
        if not os.path.isfile(meta_path):
            raise FileNotFoundError(f"Metadata file not found: {meta_path}")
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_edges(self, edges_csv_path: str):
        """
        Load directed edges from CSV into two adjacency maps:
        - edges_out[from][relation] -> set(to)
        - edges_in[to][relation]    -> set(from)
        """
        edges_out = defaultdict(lambda: defaultdict(set))  # from -> rel -> {to}
        edges_in = defaultdict(lambda: defaultdict(set))   # to   -> rel -> {from}
        if not edges_csv_path or not os.path.isfile(edges_csv_path):
            return edges_out, edges_in
        with open(edges_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                frm = (row.get("from") or row.get("From") or "").strip()
                to = (row.get("to") or row.get("To") or "").strip()
                rel = (row.get("relation") or row.get("Relation") or "").strip()
                if not frm or not to:
                    continue
                edges_out[frm][rel].add(to)
                edges_in[to][rel].add(frm)
        return edges_out, edges_in

    # ---------- helpers ----------
    @staticmethod
    def _prefer_tables_from_query(q: str) -> bool:
        """
        Heuristic: favor TABLE objects when the query mentions table/storage terms.

        Includes both English and Polish tokens to work well with bilingual queries.
        """
        ql = q.lower()
        tokens = [
            # Polish
            "tabela", "tabeli", "przechowywan",
            # English
            "table", "storage", "store",
        ]
        return any(t in ql for t in tokens)

    def _kind_of_meta(self, meta: dict) -> str:
        """Return metadata kind in uppercase (supports 'Kind' and 'kind' keys)."""
        return (meta.get("Kind") or meta.get("kind") or "").upper()

    # ---------- public API ----------
    def search(
        self,
        query: str,
        top_k: int = 5,
        oversample: int = 6,
        prefer_tables: Optional[bool] = None,
        expand: bool = True
    ) -> List[dict]:
        """
        Return a ranked list of results:
        [{ Key, Kind, Schema, Name, Score, Part, Parts, Neighbors? }]

        Parameters
        ----------
        query : str
            Natural language query.
        top_k : int
            Number of results to return.
        oversample : int
            Multiply `top_k` to gather a larger candidate set before re-ranking/boosting.
        prefer_tables : Optional[bool]
            If None, inferred via `_prefer_tables_from_query`. If True, TABLEs get a small score boost.
        expand : bool
            If True, attach one-hop graph neighbors under "Neighbors".
        """
        if prefer_tables is None:
            prefer_tables = self._prefer_tables_from_query(query)

        emb = self.model.encode([query], convert_to_numpy=True).astype("float32")
        faiss.normalize_L2(emb)

        k = max(top_k * oversample, top_k)
        scores, ids = self.index.search(emb, k)
        cand = []
        for idx, sc in zip(ids[0].tolist(), scores[0].tolist()):
            m = self.metadata[idx]
            kind = self._kind_of_meta(m)
            boost = 0.05 if (prefer_tables and kind == "TABLE") else 0.0
            adj_score = sc + boost
            cand.append((adj_score, idx))

        cand.sort(key=lambda x: x[0], reverse=True)
        picked = cand[:top_k]

        results = []
        for adj_score, idx in picked:
            m = self.metadata[idx]
            item = {
                "Key": m["Key"],
                "Kind": self._kind_of_meta(m),
                "Schema": m.get("Schema"),
                "Name": m.get("Name"),
                "File": m.get("File"),
                "Score": adj_score,
                "Part": m.get("Part"),
                "Parts": m.get("Parts"),
            }
            if expand:
                item["Neighbors"] = self.neighbors(m["Key"])  # radius=1
            results.append(item)
        return results

    def neighbors(self, key: str) -> dict:
        """
        Return one-hop neighbors for a given key:

            {
              "out": { relation: [to_keys...] },
              "in" : { relation: [from_keys...] }
            }
        """
        out_rel = {rel: sorted(list(tos)) for rel, tos in self.edges_out.get(key, {}).items()}
        in_rel = {rel: sorted(list(frs)) for rel, frs in self.edges_in.get(key, {}).items()}
        return {"out": out_rel, "in": in_rel}

    def get_body(self, key: str) -> Optional[str]:
        """
        Retrieve the body for a given key from `sql_bodies.jsonl`.

        Uses a tiny in-memory cache (simple LRU by eviction of the oldest inserted
        entry when the capacity is exceeded).
        """
        if key in self._body_cache:
            return self._body_cache[key]
        if not os.path.isfile(self.bodies_path):
            return None
        body = None
        with open(self.bodies_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                k = obj.get("key") or obj.get("Key")
                if k == key:
                    body = obj.get("body") or obj.get("Body")
                    break
        if body is not None:
            # simple LRU: cut the cache if capacity is exceeded
            if len(self._body_cache) >= self._body_cache_cap:
                self._body_cache.pop(next(iter(self._body_cache)))
            self._body_cache[key] = body
        return body
