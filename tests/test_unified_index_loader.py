# tests/test_unified_index_loader.py
import json
import os
from pathlib import Path

import pytest

from vector_db import unified_index_loader as uil
from vector_search.unified_search import UnifiedSearch


pytestmark = pytest.mark.unit


class DummyIndex:
    """Minimal FAISS-like index used in tests."""

    def __init__(self, ntotal: int):
        self.ntotal = ntotal

    def search(self, vectors, k):
        raise NotImplementedError("DummyIndex is not used for real search in this test.")


class FakeModel:
    """Minimal embedding model stub."""

    def __init__(self, model_path: str):
        # Keep the path only for debugging purposes.
        self.model_path = model_path

    def encode(self, texts, convert_to_numpy=True, **kwargs):
        import numpy as np

        # Return a single fixed-size vector; content is irrelevant here.
        n = len(texts)
        dim = 8
        return np.zeros((n, dim), dtype="float32")


def test_load_unified_search_builds_searcher_from_config_and_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Verify that load_unified_search():
    - reads config via load_config(),
    - resolves vector_indexes_root and active_index_id,
    - loads FAISS index and metadata from the expected directory,
    - loads the embedding model,
    - returns a UnifiedSearch instance wired with these objects.
    """
    # --- Arrange: fake config and paths ---
    config_dir = str(tmp_path)
    vector_root = tmp_path / "vector_indexes"
    index_id = "test_index"
    index_dir = vector_root / index_id

    index_dir.mkdir(parents=True, exist_ok=True)

    # Create minimal metadata list on disk
    metadata = [
        {"Id": "doc0", "File": "A.cs", "Content": "hello"},
        {"Id": "doc1", "File": "B.sql", "Content": "select 1"},
    ]
    meta_path = index_dir / "unified_metadata.json"
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")

    # FAISS file must exist on disk because loader checks os.path.isfile,
    # but its contents are irrelevant thanks to monkeypatch on faiss.read_index.
    faiss_path = index_dir / "unified_index.faiss"
    faiss_path.write_bytes(b"")

    config = {
        "vector_indexes_root": "vector_indexes",
        "active_index_id": index_id,
        "model_path_embd": "models/embedding/dummy-model",
    }

    # --- Monkeypatch helpers used inside unified_index_loader ---

    # load_config(script_dir) -> (config, config_dir)
    def fake_load_config(script_dir: str):
        return config, config_dir

    monkeypatch.setattr(uil, "load_config", fake_load_config)

    # resolve_path(path, base_dir) -> join(base_dir, path)
    def fake_resolve_path(path: str, base_dir: str) -> str:
        return str(Path(base_dir) / path)

    monkeypatch.setattr(uil, "resolve_path", fake_resolve_path)

    # faiss.read_index -> return DummyIndex with ntotal matching metadata length
    monkeypatch.setattr(uil.faiss, "read_index", lambda _: DummyIndex(ntotal=len(metadata)))

    # SentenceTransformer -> FakeModel
    monkeypatch.setattr(uil, "SentenceTransformer", FakeModel)

    # --- Act ---
    searcher = uil.load_unified_search()

    # --- Assert ---
    assert isinstance(searcher, UnifiedSearch)

    # Internal wiring: index + metadata + embedding model
    # (we rely on UnifiedSearch implementation details here on purpose).
    assert hasattr(searcher, "_index")
    assert hasattr(searcher, "_metadata")
    assert hasattr(searcher, "_embed_model")

    assert isinstance(searcher._index, DummyIndex)
    assert searcher._index.ntotal == len(metadata)
    assert searcher._metadata == metadata
    assert isinstance(searcher._embed_model, FakeModel)
    # Model path should come from config via model_path_embd
    assert searcher._embed_model.model_path.endswith("models/embedding/dummy-model")


def test_load_unified_search_raises_when_faiss_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    If unified_index.faiss is missing, loader should fail fast with FileNotFoundError.
    """
    config_dir = str(tmp_path)
    vector_root = tmp_path / "vector_indexes"
    index_id = "test_index_missing_faiss"
    index_dir = vector_root / index_id
    index_dir.mkdir(parents=True, exist_ok=True)

    # Create metadata (exists)
    metadata = [{"Id": "doc0", "File": "A.cs", "Content": "hello"}]
    (index_dir / "unified_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    # DO NOT create unified_index.faiss

    config = {
        "vector_indexes_root": "vector_indexes",
        "active_index_id": index_id,
        "model_path_embd": "models/embedding/dummy-model",
    }

    def fake_load_config(script_dir: str):
        return config, config_dir

    monkeypatch.setattr(uil, "load_config", fake_load_config)

    def fake_resolve_path(path: str, base_dir: str) -> str:
        return str(Path(base_dir) / path)

    monkeypatch.setattr(uil, "resolve_path", fake_resolve_path)

    # SentenceTransformer not needed (we should fail before model load),
    # but patching it keeps the test stable if the implementation changes.
    monkeypatch.setattr(uil, "SentenceTransformer", FakeModel)

    with pytest.raises(FileNotFoundError) as ex:
        uil.load_unified_search()

    assert "unified_index.faiss" in str(ex.value)


def test_load_unified_search_raises_when_faiss_size_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    If FAISS index ntotal != len(unified_metadata.json), loader should raise ValueError.
    This invariant is critical because row_id must align 1:1 with metadata rows.
    """
    config_dir = str(tmp_path)
    vector_root = tmp_path / "vector_indexes"
    index_id = "test_index_mismatch"
    index_dir = vector_root / index_id
    index_dir.mkdir(parents=True, exist_ok=True)

    metadata = [
        {"Id": "doc0", "File": "A.cs", "Content": "hello"},
        {"Id": "doc1", "File": "B.sql", "Content": "select 1"},
    ]
    (index_dir / "unified_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    # FAISS file must exist
    (index_dir / "unified_index.faiss").write_bytes(b"")

    config = {
        "vector_indexes_root": "vector_indexes",
        "active_index_id": index_id,
        "model_path_embd": "models/embedding/dummy-model",
    }

    def fake_load_config(script_dir: str):
        return config, config_dir

    monkeypatch.setattr(uil, "load_config", fake_load_config)

    def fake_resolve_path(path: str, base_dir: str) -> str:
        return str(Path(base_dir) / path)

    monkeypatch.setattr(uil, "resolve_path", fake_resolve_path)

    # FAISS index returns ntotal != metadata length => should raise
    monkeypatch.setattr(uil.faiss, "read_index", lambda _: DummyIndex(ntotal=len(metadata) + 1))

    # SentenceTransformer should not be invoked if mismatch is detected early,
    # but patching keeps it deterministic.
    monkeypatch.setattr(uil, "SentenceTransformer", FakeModel)

    with pytest.raises(ValueError) as ex:
        uil.load_unified_search()

    assert "does not match metadata length" in str(ex.value)
