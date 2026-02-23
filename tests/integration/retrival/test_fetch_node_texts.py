from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from tests.integration.retrival.helpers import (
    connect,
    resolve_snapshots,
    write_named_log,
    write_test_results_log,
)
from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.weaviate_retrieval_backend import WeaviateRetrievalBackend
from code_query_engine.pipeline.state import PipelineState


@dataclass(frozen=True)
class FetchCase:
    case_id: str
    mode: str
    expected_order: List[str]


def _canonical_id(repo: str, snapshot_id: str, kind: str, local_id: str) -> str:
    return f"{repo}::{snapshot_id}::{kind}::{local_id}"


def _log_fetch_case(env, case_id: str, expected_ids: List[str]) -> None:
    lines = [
        f"Test : fetch_node_texts::{case_id}",
        f"Round : {env.round.id}",
        f"Expected order : {'; '.join(expected_ids)}",
    ]
    write_named_log(stem="fetch_texts_results", test_id=case_id, lines=lines)
    write_test_results_log(test_id=f"fetch_node_texts::{case_id}", lines=lines)


class _TokenCounter:
    def count_tokens(self, text: str) -> int:
        return max(1, len((text or "").split()))


def _build_runtime(client, env) -> PipelineRuntime:
    backend = WeaviateRetrievalBackend(client=client, query_embed_model="models/embedding/e5-base-v2")
    return PipelineRuntime(
        pipeline_settings={
            "repository": env.repo_name,
            "max_context_tokens": 12000,
        },
        model=None,
        searcher=None,
        markdown_translator=None,
        translator_pl_en=None,
        history_manager=None,
        logger=None,
        constants=None,
        retrieval_backend=backend,
        graph_provider=None,
        token_counter=_TokenCounter(),
        add_plant_link=lambda x, _consultant=None: x,
    )


def test_fetch_node_texts_order_and_limits(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    client = connect(env)
    try:
        primary, _secondary = resolve_snapshots(client, env)
    finally:
        client.close()

    seed_ids = [
        _canonical_id(env.repo_name, primary, "cs", "C0005"),
        _canonical_id(env.repo_name, primary, "cs", "C0016"),
        _canonical_id(env.repo_name, primary, "cs", "C0011"),
    ]
    graph_ids = [
        _canonical_id(env.repo_name, primary, "cs", "C0013"),
        _canonical_id(env.repo_name, primary, "cs", "C0006"),
        _canonical_id(env.repo_name, primary, "cs", "C0027"),
    ]

    cases = [
        FetchCase(
            case_id="F1",
            mode="seed_first",
            expected_order=[seed_ids[0], seed_ids[1]],
        ),
        FetchCase(
            case_id="F2",
            mode="seed_first",
            expected_order=[seed_ids[0], seed_ids[1], seed_ids[2], graph_ids[1], graph_ids[0], graph_ids[2]],
        ),
        FetchCase(
            case_id="F3",
            mode="graph_first",
            expected_order=[seed_ids[0], graph_ids[1], seed_ids[1], graph_ids[0], seed_ids[2], graph_ids[2]],
        ),
        FetchCase(
            case_id="F4",
            mode="balanced",
            expected_order=[seed_ids[0], graph_ids[1], seed_ids[1], graph_ids[0], seed_ids[2], graph_ids[2]],
        ),
    ]

    for case in cases:
        client = connect(env)
        try:
            runtime = _build_runtime(client, env)
            state = PipelineState(
                user_query="",
                session_id="it-fetch",
                consultant="rejewski",
                translate_chat=False,
                repository=env.repo_name,
                snapshot_set_id=env.snapshot_set_id,
                snapshot_id=primary,
            )
            state.retrieval_seed_nodes = list(seed_ids)
            state.graph_expanded_nodes = list(graph_ids)
            state.graph_edges = [
                {"from_id": seed_ids[0], "to_id": graph_ids[1], "edge_type": "cs_dep"},
                {"from_id": seed_ids[1], "to_id": graph_ids[0], "edge_type": "cs_dep"},
                {"from_id": seed_ids[2], "to_id": graph_ids[2], "edge_type": "cs_dep"},
            ]

            step = StepDef(
                id="fetch_node_texts",
                action="fetch_node_texts",
                raw={
                    "prioritization_mode": case.mode,
                    "budget_tokens": 2000,
                },
            )
            FetchNodeTextsAction().execute(step, state, runtime)
        finally:
            client.close()

        observed_ids = [str(x.get("id")) for x in (state.node_texts or []) if isinstance(x, dict)]
        expected = case.expected_order
        _log_fetch_case(env, case.case_id, expected)
        assert observed_ids[: len(expected)] == expected
