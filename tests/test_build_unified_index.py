import json
import os
import zipfile
from pathlib import Path

import pytest

from vector_db import build_unified_index as bui


def _create_fake_branch_zip(tmp_root: Path, branches_dir: Path, name: str) -> Path:
    """
    Create a minimal fake branch structure with:
    - regular_code_bundle/chunks.json (one C# entry)
    - sql_bundle/docs/sql_bodies.jsonl (one SQL entry)
    and pack it into branches/<name>.zip

    The archive will have a single top-level folder "<name>/..."
    so that extract_to_named_root() behaves like in real branches.
    """
    branch_dir = tmp_root / f"{name}_branch_src"
    regular_dir = branch_dir / "regular_code_bundle"
    sql_docs_dir = branch_dir / "sql_bundle" / "docs"

    regular_dir.mkdir(parents=True, exist_ok=True)
    sql_docs_dir.mkdir(parents=True, exist_ok=True)

    # Minimal chunks.json for C#
    chunks = [
        {
            "Id": f"{name}-cs-id",
            "Text": f"// {name} C# content",
            "File": f"{name}.cs",
            "Class": "TestClass",
            "Member": "TestMethod",
        }
    ]
    (regular_dir / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")

    # Minimal sql_bodies.jsonl for SQL
    sql_body = {
        "key": f"NopDb::{name}.TestProc",
        "kind": "Procedure",
        "schema": "dbo",
        "name": f"{name}_TestProc",
        "file": f"sql/{name}_TestProc.sql",
        "body": "SELECT 1;",
    }
    sql_bodies_path = sql_docs_dir / "sql_bodies.jsonl"
    with sql_bodies_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(sql_body) + "\n")

    branches_dir.mkdir(parents=True, exist_ok=True)
    zip_path = branches_dir / f"{name}.zip"

    # Pack everything under top-level folder "<name>/..."
    with zipfile.ZipFile(zip_path, "w") as zf:
        for root, _dirs, files in os.walk(branch_dir):
            for file_name in files:
                full_path = os.path.join(root, file_name)
                rel = os.path.relpath(full_path, branch_dir)
                arcname = os.path.join(name, rel)
                zf.write(full_path, arcname=arcname)

    return zip_path


def test_build_unified_index_combines_branches_and_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Build a unified index from two fake branches and verify that:
    - both branches are included,
    - both data_type values ("regular_code", "db_code") are present,
    - both file_type values ("cs", "sql") are present,
    - metadata is written to the expected location.
    """
    tmp_root = tmp_path
    branches_dir = tmp_root / "branches"
    vector_root = tmp_root / "vector_indexes"

    # Minimal config for the builder – we bypass real config.json via monkeypatch.
    config = {
        "output_dir": "branches",
        "model_path_embd": "models/embedding/dummy-model",
        "use_gpu": False,
        "vector_indexes_root": "vector_indexes",
        "active_index_id": "test_index",
        "repo_name": "nopCommerce",
    }
    config_dir = str(tmp_root)

    def fake_load_config(script_dir: str):
        # script_dir is ignored here; we use temporary paths only.
        return config, config_dir

    monkeypatch.setattr(bui, "load_config", fake_load_config)

    # Prepare two fake branches: "develop" and "master"
    zip_develop = _create_fake_branch_zip(tmp_root, branches_dir, "develop")
    zip_master = _create_fake_branch_zip(tmp_root, branches_dir, "master")

    def fake_list_archives(_branches_dir: str):
        # Ignore the argument and return our two archives.
        return [str(zip_develop), str(zip_master)]

    def fake_choose_archives(files):
        # Select all archives without interactive input.
        return files

    monkeypatch.setattr(bui, "list_archives", fake_list_archives)
    monkeypatch.setattr(bui, "choose_archives", fake_choose_archives)

    # Use a lightweight fake embedding model to avoid heavy SentenceTransformer call.
    class FakeModel:
        def __init__(self, model_path: str):
            self.model_path = model_path

        def to(self, device):
            return self

        def encode(self, texts, batch_size: int = 32, convert_to_numpy: bool = True, show_progress_bar: bool = False):
            import numpy as np

            # Deterministic small vectors: shape (len(texts), 4)
            n = len(texts)
            dim = 4
            arr = np.arange(n * dim, dtype="float32").reshape(n, dim)
            return arr

    monkeypatch.setattr(bui, "SentenceTransformer", FakeModel)
    # Force CPU path to avoid GPU-specific code in tests.
    monkeypatch.setattr(bui.torch.cuda, "is_available", lambda: False)

    # Act
    bui.build_unified_index(index_id="test_index")

    # Assert: index and metadata exist
    index_dir = vector_root / "test_index"
    meta_path = index_dir / "unified_metadata.json"
    faiss_path = index_dir / "unified_index.faiss"

    assert meta_path.is_file(), "Expected unified_metadata.json to be created"
    assert faiss_path.is_file(), "Expected unified_index.faiss to be created"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # Two branches × (1 C# + 1 SQL) = 4 documents
    assert len(meta) == 4

    data_types = {m["data_type"] for m in meta}
    assert data_types == {"regular_code", "db_code"}

    branches = {m["branch"] for m in meta}
    assert branches == {"develop", "master"}

    file_types = {m["file_type"] for m in meta}
    assert "cs" in file_types
    assert "sql" in file_types
