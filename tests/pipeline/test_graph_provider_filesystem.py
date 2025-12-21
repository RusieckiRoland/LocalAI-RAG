from __future__ import annotations

import json
from pathlib import Path

from code_query_engine.pipeline.providers.graph_provider import GraphProvider


def _write_edges_csv(path: Path, rows: list[dict]) -> None:
    header = ["from", "to", "type"]
    lines = [",".join(header)]
    for r in rows:
        lines.append(f"{r.get('from','')},{r.get('to','')},{r.get('type','')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_graph_provider_expand_dependency_tree_reads_edges_csv(tmp_path: Path) -> None:
    repo_root = tmp_path / "repositories"
    graph_dir = repo_root / "repo1" / "branches" / "b1" / "sql_bundle" / "graph"
    graph_dir.mkdir(parents=True)

    _write_edges_csv(
        graph_dir / "edges.csv",
        [
            {"from": "A", "to": "B", "type": "dep"},
            {"from": "B", "to": "C", "type": "dep"},
            {"from": "A", "to": "D", "type": "ref"},
        ],
    )

    gp = GraphProvider(repositories_root=str(repo_root))

    out = gp.expand_dependency_tree(
        seed_nodes=["A"],
        max_depth=2,
        max_nodes=100,
        edge_allowlist=["dep"],
        repository="repo1",
        branch="b1",
        active_index=None,
    )

    assert out["nodes"] == ["A", "B", "C"]
    assert out["edges"] == [
        {"from": "A", "to": "B", "type": "dep"},
        {"from": "B", "to": "C", "type": "dep"},
    ]


def test_graph_provider_fetch_node_texts_reads_nodes_json_and_applies_max_chars(tmp_path: Path) -> None:
    repo_root = tmp_path / "repositories"
    graph_dir = repo_root / "repo1" / "branches" / "b1" / "sql_bundle" / "graph"
    graph_dir.mkdir(parents=True)

    nodes = {"A": "aaaaa", "B": "bbbbb", "C": "ccccc"}
    (graph_dir / "nodes.json").write_text(json.dumps(nodes), encoding="utf-8")

    gp = GraphProvider(repositories_root=str(repo_root))

    out = gp.fetch_node_texts(
        node_ids=["A", "B", "C"],
        repository="repo1",
        branch="b1",
        active_index=None,
        max_chars=9,
    )

    assert out == [
        {"id": "A", "text": "aaaaa"},
        {"id": "B", "text": "bbbb"},
    ]
