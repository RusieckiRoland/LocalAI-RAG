from __future__ import annotations

import logging
import multiprocessing as mp
import threading
from typing import Any, Dict, List, Optional

py_logger = logging.getLogger(__name__)

# Worker client cache (per process)
_worker_lock = threading.Lock()
_workers: Dict[str, "SemanticWorkerClient"] = {}


def shutdown_all_workers() -> None:
    """Terminate all semantic worker processes (best-effort)."""
    with _worker_lock:
        items = list(_workers.items())
        _workers.clear()

    for _, w in items:
        try:
            w.shutdown()
        except Exception:
            pass


def _worker_main(conn, index_id: Optional[str]) -> None:
    """
    Worker process entry point.

    IMPORTANT:
    - torch / sentence_transformers are imported ONLY here.
    - UnifiedSearch is loaded ONLY here.
    """
    # Local imports in worker only
    from vector_search.models import VectorSearchFilters, VectorSearchRequest
    from vector_db import unified_index_loader

    unified = unified_index_loader.load_unified_search(index_id)

    while True:
        msg = conn.recv()
        op = msg.get("op")

        if op == "shutdown":
            conn.send({"ok": True})
            return

        if op != "search":
            conn.send({"ok": False, "error": f"Unknown op: {op}"})
            continue

        try:
            req_dict = msg.get("req") or {}
            f_dict = req_dict.get("filters") or {}
            fs = VectorSearchFilters(**f_dict)

            req = VectorSearchRequest(
                text_query=req_dict.get("text_query") or "",
                top_k=int(req_dict.get("top_k") or 10),
                oversample_factor=int(req_dict.get("oversample_factor") or 5),
                filters=fs,
                include_text_preview=bool(req_dict.get("include_text_preview", True)),
            )

            results = unified.search(req)
            conn.send({"ok": True, "results": results})
        except Exception as ex:
            conn.send({"ok": False, "error": f"{type(ex).__name__}: {ex}"})


class SemanticWorkerClient:
    """
    A small synchronous RPC client for semantic search.
    Uses a dedicated subprocess to avoid in-process torch/triton re-initialization problems.
    """

    def __new__(cls, *, index_id: Optional[str]):
        key = (index_id or "").strip() or "__active__"

        cached = _workers.get(key)
        if cached is not None:
            return cached

        with _worker_lock:
            cached = _workers.get(key)
            if cached is not None:
                return cached

            obj = super().__new__(cls)
            _workers[key] = obj
            return obj

    def __init__(self, *, index_id: Optional[str]):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._initialized = True
        self._index_id = (index_id or "").strip() or "__active__"
        self._rpc_lock = threading.Lock()

        ctx = mp.get_context("spawn")  # safe + explicit

        parent_conn, child_conn = ctx.Pipe(duplex=True)

        # daemon=True -> worker dies when parent interpreter ends (test-friendly)
        proc = ctx.Process(
            target=_worker_main,
            args=(child_conn, index_id),
            daemon=True,
        )
        proc.start()

        self._conn = parent_conn
        self._proc = proc

    def search(self, req_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Perform semantic search in the worker process.
        """
        with self._rpc_lock:
            self._conn.send({"op": "search", "req": req_dict})
            resp = self._conn.recv()

        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or "Semantic worker error")

        results = resp.get("results")
        if results is None:
            return []
        return results

    def shutdown(self) -> None:
        """
        Gracefully ask worker to shutdown (best-effort).
        """
        try:
            with self._rpc_lock:
                if self._conn is not None:
                    self._conn.send({"op": "shutdown"})
                    _ = self._conn.recv()
        except Exception:
            pass

        try:
            if self._proc is not None and self._proc.is_alive():
                self._proc.terminate()
        except Exception:
            pass
