from __future__ import annotations

import json
from pathlib import Path

from code_query_engine.pipeline.providers.file_system_graph_provider import FileSystemGraphProvider
from code_query_engine.pipeline.providers.graph_provider import GraphProvider


def test_graph_provider_expand_dependency_tree_edges_csv(tmp_path: Path) -> None:
    repos = tmp_path / "repositories"
    graph_dir = repos / "repo1" / "branches" / "develop" / "sql_bundle" / "graph"
    graph_dir.mkdir(parents=True)

    (graph_dir / "edges.csv").write_text(
        "from,to,type\n"
        "A,B,Calls\n"
        "B,C,Uses\n",
        encoding="utf-8",
    )

    provider = GraphProvider(repositories_root=str(repos))
    out = provider.expand_dependency_tree(seed_nodes=["A"], max_depth=2, repository="repo1", branch="develop")

    assert out["nodes"] == ["A", "B", "C"]
    assert out["edges"] == [
        {"from": "A", "to": "B", "type": "Calls"},
        {"from": "B", "to": "C", "type": "Uses"},
    ]


def test_graph_provider_fetch_node_texts_nodes_json_and_max_chars(tmp_path: Path) -> None:
    repos = tmp_path / "repositories"
    graph_dir = repos / "repo1" / "branches" / "develop" / "sql_bundle" / "graph"
    graph_dir.mkdir(parents=True)

    (graph_dir / "nodes.json").write_text(json.dumps({"A": "ABCDE", "B": "FGHIJ"}), encoding="utf-8")

    provider = GraphProvider(repositories_root=str(repos))
    out = provider.fetch_node_texts(node_ids=["A", "B"], repository="repo1", branch="develop", max_chars=3)

    # Budget should truncate and stop deterministically.
    assert out == [{"id": "A", "text": "ABC"}]


def test_file_system_graph_provider_contract_adapter(tmp_path: Path) -> None:
    repos = tmp_path / "repositories"

    # Minimal bundle layout
    code_dir = repos / "repo1" / "branches" / "develop" / "regular_code_bundle"
    code_dir.mkdir(parents=True)
    (code_dir / "dependencies.json").write_text(json.dumps({"X": ["Y"]}), encoding="utf-8")
    (code_dir / "chunks.json").write_text(
        json.dumps(
            [
                {"Id": "X", "File": "a.cs", "Text": "class X {}"},
                {"Id": "Y", "File": "b.cs", "Text": "class Y {}"},
            ]
        ),
        encoding="utf-8",
    )

    provider = FileSystemGraphProvider(repositories_root=str(repos))

    expanded = provider.expand_dependency_tree(seed_nodes=["X"], max_depth=1, repository="repo1", branch="develop", active_index="idx")

    assert expanded["nodes"] == ["X", "Y"]
    assert expanded["edges"], "Expected at least one edge"

    texts = provider.fetch_node_texts(node_ids=["X", "Y"], repository="repo1", branch="develop", active_index="idx", max_chars=10_000)
    assert any(t.get("node_id") == "X" and "class X" in (t.get("text") or "") for t in texts)
