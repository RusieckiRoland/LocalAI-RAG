# File: common/hybrid_search.py
import re
from typing import Any, Dict, List, Optional


class SemanticKeywordRerankSearch:
    def __init__(
        self,
        *,
        index,
        metadata: list,
        chunks: list,
        dependencies: dict,
        embed_model
    ):
        """
        All dependencies are injected:

        - index: FAISS-like index, already loaded; must expose `search(vectors, k)`.
        - metadata: list of metadata entries aligned with FAISS rows (index -> meta).
                    Each meta should contain at least {"Id": <chunk-id>}.
        - chunks: list of chunk objects (from chunks.json), each with:
                  {"Id", "File", "Text", optional: "Member", "Type", ...}
        - dependencies: dict mapping str(Id) -> list[str] (related chunk Ids).
        - embed_model: embedding model compatible with SentenceTransformer.encode.
        """
        self.index = index
        self.metadata = metadata
        self.chunks = chunks
        self.dependencies = dependencies
        self.embed_model = embed_model

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _get_related(self, chunk_id: int | str) -> List[Dict[str, Any]]:
        """
        Return related chunks (neighbors) for the given `chunk_id` using the
        precomputed `dependencies` map.
        """
        rel_ids = self.dependencies.get(str(chunk_id), [])
        out: List[Dict[str, Any]] = []

        # Local id->chunk map for O(1) lookups; keep it local to avoid
        # altering constructor behavior.
        id_map = {c["Id"]: c for c in self.chunks}

        for rid in rel_ids:
            c = id_map.get(rid)
            if c:
                out.append(
                    {
                        "File": c["File"],
                        "Member": c.get("Member", "Unknown"),
                        "Type": c.get("Type", "Unknown"),
                        "Content": c["Text"],
                    }
                )

        out.sort(key=lambda x: x["File"])
        return out

    # --------------------------------------------------------------------- #
    # Embedding (FAISS) search
    # --------------------------------------------------------------------- #

    def _embedding_search(self, query: str, k: int, filters: Optional[Dict[str, List[str]]] = None):
        """
        Query the vector index and return up to `k` results with metadata.

        Output items:
        {
            "Rank", "File", "Id", "Content", "Distance", "Related": [...]
        }
        """
        # 1) Embed query
        emb = self.embed_model.encode([f"query: {query}"], convert_to_numpy=True)
        distances, indices = self.index.search(emb, k)

        results: List[Dict[str, Any]] = []
        seen: set[int] = set()
        id_map = {c["Id"]: c for c in self.chunks}

        for i, idx in enumerate(indices[0]):
            if idx == -1 or idx in seen:
                continue
            seen.add(idx)

            # 2) Metadata entry
            meta = self.metadata[idx]
            cid = meta.get("Id")
            if cid is None:
                continue

            chunk = id_map.get(cid)
            if not chunk:
                continue

            # ---------------------------------------------
            # 3) NEW: Apply metadata filtering
            # ---------------------------------------------
            if filters:
                if not self._chunk_passes_filters(chunk, filters):
                    continue

            # 4) Append filtered result
            results.append(
                {
                    "Rank": len(results) + 1,
                    "File": chunk["File"],
                    "Id": cid,
                    "Content": chunk["Text"],
                    "Distance": float(distances[0][i]),
                    "Related": self._get_related(cid),
                }
            )

        return results
   
   
    # --------------------------------------------------------------------- #
    # Keyword search (lightweight, no extra index)
    # --------------------------------------------------------------------- #

    def _keyword_search(self, query: str, top_k: int):
        """
        Simple keyword filter over `chunks` (case-insensitive, alnum tokens >=3).
        """
        toks = [t for t in re.findall(r"\w+", query.lower()) if len(t) >= 3]
        if not toks:
            return []

        hits: List[Dict[str, Any]] = []
        for c in self.chunks:
            txt = c["Text"].lower()
            if all(t in txt for t in toks):
                hits.append(
                    {
                        "Rank": None,
                        "File": c["File"],
                        "Id": c["Id"],
                        "Content": c["Text"],
                        "Distance": 1.0,  # no embedding distance available here
                        "Related": self._get_related(c["Id"]),
                    }
                )

        def score_kw(x: Dict[str, Any]) -> int:
            txt = x["Content"].lower()
            return sum(txt.count(t) for t in toks)

        hits.sort(key=score_kw, reverse=True)
        return hits[:top_k]

    # --------------------------------------------------------------------- #
    # Hybrid: FAISS wide → local rerank by keywords → trim to top_k
    # --------------------------------------------------------------------- #

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        widen: int | None = None,
        alpha: float = 0.8,
        beta: float = 0.2,
    ):
        """
        Hybrid scoring:
        1) Ask FAISS for a wide candidate pool (`widen`, default max(50, top_k*10)).
        2) Compute a lightweight keyword score on candidates (no extra index).
        3) Final score = alpha * (1 - distance) + beta * kw_norm.
        4) Sort by final score, then by distance; return top_k. Rank is reassigned.
        """
        # 1) Wide FAISS shot
        widen = widen or max(50, top_k * 10)
        emb = self._embedding_search(query, widen)

        # 2) Tokenize for keyword scoring (splitCamelCase a bit)
        def split_camel(s: str) -> str:
            return re.sub(r"([a-z])([A-Z])", r"\1 \2", s)

        toks = [t for t in re.findall(r"\w+", split_camel(query).lower()) if len(t) >= 3]

        def kw_score(txt: str) -> int:
            if not toks:
                return 0
            low = txt.lower()
            return sum(low.count(t) for t in toks)

        # 3) Compute scores
        max_kw = 1
        for r in emb:
            d = float(r.get("Distance", 1.0))
            r["_emb_score"] = max(0.0, 1.0 - d)  # smaller distance → higher score
            r["_kw_raw"] = kw_score(r.get("Content", ""))
            if r["_kw_raw"] > max_kw:
                max_kw = r["_kw_raw"]

        for r in emb:
            kw_norm = r["_kw_raw"] / max_kw if max_kw > 0 else 0.0
            r["_kw_norm"] = kw_norm
            r["_final_score"] = alpha * r["_emb_score"] + beta * kw_norm

        # 4) Sort, trim, and clean up temporary fields
        emb.sort(key=lambda x: (-x["_final_score"], x["Distance"]))
        out = emb[:top_k]
        for i, r in enumerate(out, start=1):
            r["Rank"] = i
            r.pop("_emb_score", None)
            r.pop("_kw_raw", None)
            r.pop("_kw_norm", None)
            r.pop("_final_score", None)
            # r["Engine"] = "faiss+rtr"  # optional for diagnostics

        return out
    

    def _chunk_passes_filters(self, chunk, filters):
        """
        Returns True if FAISS/BM25 chunk satisfies metadata filters.
        Example filters:
            { "data_type": ["sql"], "file_type": ["storedproc"] }
        """
        if not filters:
            return True

        for key, allowed_values in filters.items():
            if not allowed_values:
                continue

            # Normalize both sides
            allowed = set(a.lower() for a in allowed_values)

            # Try different key casings
            val = (
                chunk.get(key)
                or chunk.get(key.lower())
                or chunk.get(key.upper())
            )

            if val is None:
                return False

            # Normalize chunk value(s)
            if isinstance(val, list):
                vals = [v.lower() for v in val]
            else:
                vals = [val.lower()]

            # Check intersection
            if not any(v in allowed for v in vals):
                return False

        return True

    def _chunk_passes_filters(self, chunk: Dict[str, Any], filters: Dict[str, List[str]]) -> bool:
        """
        Returns True if chunk metadata satisfies filters.
        Filters example:
            {"data_type": ["sql"], "file_type": ["proc"]}
        """
        for key, allowed_values in filters.items():
            if not allowed_values:
                continue

            allowed = {v.lower() for v in allowed_values}

            # try three casings
            value = (
                chunk.get(key)
                or chunk.get(key.lower())
                or chunk.get(key.upper())
            )

            if value is None:
                return False

            if isinstance(value, list):
                vals = [str(v).lower() for v in value]
            else:
                vals = [str(value).lower()]

            if not any(val in allowed for val in vals):
                return False

        return True
