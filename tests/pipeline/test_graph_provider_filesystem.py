from __future__ import annotations

import json
from pathlib import Path

from code_query_engine.pipeline.providers.file_system_graph_provider import FileSystemGraphProvider


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_filesystem_graph_provider_expands_code_dependencies_from_regular_bundle(tmp_path: Path) -> None:
    # repositories/<repo>/branches/<branch>/regular_code_bundle/dependencies.json
    repo = "r"
    branch = "b"
    root = tmp_path / "repositories" / repo / "branches" / branch

    deps_path = root / "regular_code_bundle" / "dependencies.json"
    _write_text(deps_path, json.dumps({"A": ["B"]}, ensure_ascii=False))

    # chunks.json only needed for fetch_node_texts, but keep minimal structure here
    chunks_path = root / "regular_code_bundle" / "chunks.json"
    _write_text(
        chunks_path,
        json.dumps(
            [
                {"Id": "A", "File": "a.py", "Text": "AAA"},
                {"Id": "B", "File": "b.py", "Text": "BBB"},
            ],
            ensure_ascii=False,
        ),
    )

    gp = FileSystemGraphProvider(repositories_root=str(tmp_path / "repositories"))

    out = gp.expand_dependency_tree(
        seed_nodes=["A"],
        max_depth=2,
        max_nodes=50,
        edge_allowlist=None,
        repository=repo,
        branch=branch,
        active_index=None,
    )

    assert out["nodes"][:2] == ["A", "B"]
    assert out["edges"]
    assert out["edges"][0]["from"] == "A"
    assert out["edges"][0]["to"] == "B"
    assert out["edges"][0]["type"] == "code_dep"


def test_filesystem_graph_provider_expands_sql_edges_from_sql_bundle(tmp_path: Path) -> None:
    # repositories/<repo>/branches/<branch>/sql_bundle/graph/edges.csv
    repo = "r"
    branch = "b"
    root = tmp_path / "repositories" / repo / "branches" / branch

    edges_csv = root / "sql_bundle" / "graph" / "edges.csv"
    _write_text(
        edges_csv,
        "from,to,relation\nS1,S2,calls\n",
    )

    gp = FileSystemGraphProvider(repositories_root=str(tmp_path / "repositories"))

    out = gp.expand_dependency_tree(
        seed_nodes=["S1"],
        max_depth=2,
        max_nodes=50,
        edge_allowlist=None,
        repository=repo,
        branch=branch,
        active_index=None,
    )

    assert out["nodes"][:2] == ["S1", "S2"]
    assert out["edges"]
    e = out["edges"][0]
    assert e["from"] == "S1"
    assert e["to"] == "S2"
    assert e["type"] == "calls"
