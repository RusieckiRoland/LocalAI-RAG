from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from tests.integration.retrival.helpers import (
    connect,
    run_expand_dependency_tree,
    resolve_snapshots,
    write_named_log,
    write_test_results_log,
)


@dataclass(frozen=True)
class GraphCase:
    case_id: str
    seed_local_id: str
    kind: str
    allowlist: List[str]
    max_depth: int
    expected_local_ids: List[str]


def _canonical_id(repo: str, snapshot_id: str, kind: str, local_id: str) -> str:
    return f"{repo}::{snapshot_id}::{kind}::{local_id}"


_GRAPH_CASES = [
    GraphCase(
        case_id="cs_dep",
        seed_local_id="C0001",
        kind="cs",
        allowlist=["cs_dep"],
        max_depth=2,
        expected_local_ids=["C0001", "C0002", "C0003"],
    ),
    GraphCase(
        case_id="sql_calls",
        seed_local_id="SQL:dbo.proc_Corpus_001",
        kind="sql",
        allowlist=["sql_Calls"],
        max_depth=2,
        expected_local_ids=[
            "SQL:dbo.proc_Corpus_001",
            "SQL:dbo.proc_Corpus_002",
            "SQL:dbo.proc_Corpus_003",
        ],
    ),
]

def _log_graph_case(env, case_id: str, seed_ids: List[str], expected_ids: List[str], observed_ids: List[str]) -> None:
    lines = [
        f"Test : expand_dependency_tree::{case_id}",
        f"Round : {env.round.id}",
        f"Seed IDs : {'; '.join(seed_ids)}",
        f"Expected node IDs : {'; '.join(expected_ids)}",
        f"Observed node IDs : {'; '.join(observed_ids)}",
    ]
    write_named_log(stem="graph_results", test_id=f"{case_id}_graph", lines=lines)
    write_test_results_log(test_id=f"expand_dependency_tree::{case_id}", lines=lines)


@pytest.mark.parametrize("case", _GRAPH_CASES, ids=[c.case_id for c in _GRAPH_CASES])
def test_dependency_tree_allowlist_expected_outputs(retrieval_integration_env, case: GraphCase) -> None:
    env = retrieval_integration_env
    client = connect(env)
    try:
        primary, _secondary = resolve_snapshots(client, env)
    finally:
        client.close()

    seed_id = _canonical_id(env.repo_name, primary, case.kind, case.seed_local_id)
    expected_ids = [_canonical_id(env.repo_name, primary, case.kind, x) for x in case.expected_local_ids]

    state = run_expand_dependency_tree(
        env=env,
        seed_ids=[seed_id],
        retrieval_filters={},
        allowlist=case.allowlist,
        max_depth=case.max_depth,
    )

    observed_ids = list(state.graph_expanded_nodes or [])

    _log_graph_case(env, case.case_id, [seed_id], expected_ids, observed_ids)

    assert seed_id in set(observed_ids)
    assert set(observed_ids) == set(expected_ids)


def test_expand_dependency_tree_travel_permission(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    if not env.round.permissions.get("acl_enabled", True):
        pytest.skip("ACL disabled for this round.")

    client = connect(env)
    try:
        primary, _secondary = resolve_snapshots(client, env)
    finally:
        client.close()

    seed_id = _canonical_id(env.repo_name, primary, "cs", "C0001")
    allowlist = ["cs_dep"]
    max_depth = 6

    filters = {
        "acl_tags_any": ["finance", "security"],
    }

    state = run_expand_dependency_tree(
        env=env,
        seed_ids=[seed_id],
        retrieval_filters=filters,
        allowlist=allowlist,
        max_depth=max_depth,
    )
    observed_ids = list(state.graph_expanded_nodes or [])

    # Expected behavior depends on require_travel_permission.
    if env.round.permissions.get("require_travel_permission", True):
        expected_ids = [seed_id]
    else:
        expected_ids = [
            seed_id,
            _canonical_id(env.repo_name, primary, "cs", "C0006"),
            _canonical_id(env.repo_name, primary, "cs", "C0007"),
        ]

    _log_graph_case(env, "travel_permission", [seed_id], expected_ids, observed_ids)

    assert set(observed_ids) == set(expected_ids)
