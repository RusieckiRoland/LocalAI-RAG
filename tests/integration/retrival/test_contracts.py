from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from code_query_engine.pipeline.actions.fetch_node_texts import FetchNodeTextsAction
from code_query_engine.pipeline.actions.search_nodes import SearchNodesAction
from code_query_engine.pipeline.actions.expand_dependency_tree import ExpandDependencyTreeAction
from code_query_engine.pipeline.definitions import StepDef
from code_query_engine.pipeline.engine import PipelineRuntime
from code_query_engine.pipeline.providers.weaviate_retrieval_backend import WeaviateRetrievalBackend
from code_query_engine.pipeline.providers.weaviate_graph_provider import WeaviateGraphProvider
from code_query_engine.pipeline.state import PipelineState

from tests.integration.retrival.helpers import connect, resolve_snapshots, write_named_log, write_test_results_log


@dataclass(frozen=True)
class ContractCase:
    case_id: str
    expected_error: str


def _log_case(env, case_id: str, status: str, expected: str, observed: str) -> None:
    lines = [
        f"Test : contract::{case_id}",
        f"Round : {env.round.id}",
        f"Status : {status}",
        f"Expected : {expected}",
        f"Observed : {observed}",
    ]
    write_named_log(stem="contract_gap_results", test_id=case_id, lines=lines)
    write_test_results_log(test_id=f"contract::{case_id}", lines=lines)


def _build_runtime(client, env, *, graph: bool = False) -> PipelineRuntime:
    backend = WeaviateRetrievalBackend(client=client, query_embed_model="models/embedding/e5-base-v2")
    graph_provider = WeaviateGraphProvider(client=client) if graph else None
    class _TokenCounter:
        def count_tokens(self, text: str) -> int:
            return max(1, len((text or "").split()))
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
        graph_provider=graph_provider,
        token_counter=_TokenCounter(),
        add_plant_link=lambda x, _consultant=None: x,
    )


def test_search_nodes_missing_top_k(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    client = connect(env)
    try:
        primary, _secondary = resolve_snapshots(client, env)
        runtime = _build_runtime(client, env)
        state = PipelineState(
            user_query="",
            session_id="it-contract",
            consultant="rejewski",
            translate_chat=False,
            repository=env.repo_name,
            snapshot_set_id=env.snapshot_set_id,
            snapshot_id=primary,
        )
        state.last_model_response = "test query"
        step = StepDef(id="search_nodes", action="search_nodes", raw={"search_type": "bm25"})
        expected = "search_nodes: Missing required top_k (step.raw.top_k or pipeline_settings.top_k)."
        try:
            SearchNodesAction().execute(step, state, runtime)
            observed = "no error"
            status = "fail"
        except Exception as exc:
            observed = str(exc)
            status = "pass" if expected in observed else "fail"
        _log_case(env, "search_nodes_missing_top_k", status, expected, observed)
        assert expected in observed
    finally:
        client.close()


def test_search_nodes_unknown_search_type(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    client = connect(env)
    try:
        primary, _secondary = resolve_snapshots(client, env)
        runtime = _build_runtime(client, env)
        state = PipelineState(
            user_query="",
            session_id="it-contract",
            consultant="rejewski",
            translate_chat=False,
            repository=env.repo_name,
            snapshot_set_id=env.snapshot_set_id,
            snapshot_id=primary,
        )
        state.last_model_response = "test query"
        step = StepDef(id="search_nodes", action="search_nodes", raw={"search_type": "unknown", "top_k": 3})
        expected = "search_nodes: invalid search_type='unknown'"
        try:
            SearchNodesAction().execute(step, state, runtime)
            observed = "no error"
            status = "fail"
        except Exception as exc:
            observed = str(exc)
            status = "pass" if expected in observed else "fail"
        _log_case(env, "search_nodes_unknown_search_type", status, expected, observed)
        assert expected in observed
    finally:
        client.close()


def test_search_nodes_rerank_only_for_semantic(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    client = connect(env)
    try:
        primary, _secondary = resolve_snapshots(client, env)
        runtime = _build_runtime(client, env)
        state = PipelineState(
            user_query="",
            session_id="it-contract",
            consultant="rejewski",
            translate_chat=False,
            repository=env.repo_name,
            snapshot_set_id=env.snapshot_set_id,
            snapshot_id=primary,
        )
        state.last_model_response = "test query"
        step = StepDef(id="search_nodes", action="search_nodes", raw={"search_type": "bm25", "top_k": 3, "rerank": "keyword_rerank"})
        expected = "search_nodes: rerank='keyword_rerank' is only allowed for search_type='semantic' (contract)."
        try:
            SearchNodesAction().execute(step, state, runtime)
            observed = "no error"
            status = "fail"
        except Exception as exc:
            observed = str(exc)
            status = "pass" if expected in observed else "fail"
        _log_case(env, "search_nodes_rerank_only_for_semantic", status, expected, observed)
        assert expected in observed
    finally:
        client.close()


def test_fetch_node_texts_budget_conflict(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    client = connect(env)
    try:
        primary, _secondary = resolve_snapshots(client, env)
        runtime = _build_runtime(client, env)
        state = PipelineState(
            user_query="",
            session_id="it-contract",
            consultant="rejewski",
            translate_chat=False,
            repository=env.repo_name,
            snapshot_set_id=env.snapshot_set_id,
            snapshot_id=primary,
        )
        state.retrieval_seed_nodes = [f"{env.repo_name}::{primary}::cs::C0001"]
        step = StepDef(id="fetch_node_texts", action="fetch_node_texts", raw={"budget_tokens": 10, "max_chars": 10})
        expected = "fetch_node_texts: max_chars cannot be used together with budget_tokens (contract)."
        try:
            FetchNodeTextsAction().execute(step, state, runtime)
            observed = "no error"
            status = "fail"
        except Exception as exc:
            observed = str(exc)
            status = "pass" if expected in observed else "fail"
        _log_case(env, "fetch_node_texts_budget_conflict", status, expected, observed)
        assert expected in observed
    finally:
        client.close()


def test_expand_dependency_tree_missing_settings(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    client = connect(env)
    try:
        primary, _secondary = resolve_snapshots(client, env)
        runtime = _build_runtime(client, env, graph=True)
        state = PipelineState(
            user_query="",
            session_id="it-contract",
            consultant="rejewski",
            translate_chat=False,
            repository=env.repo_name,
            snapshot_set_id=env.snapshot_set_id,
            snapshot_id=primary,
        )
        state.retrieval_seed_nodes = [f"{env.repo_name}::{primary}::cs::C0001"]
        step = StepDef(id="expand_dependency_tree", action="expand_dependency_tree", raw={})
        expected = "expand_dependency_tree: Missing required 'max_depth_from_settings' in YAML step."
        try:
            ExpandDependencyTreeAction().execute(step, state, runtime)
            observed = "no error"
            status = "fail"
        except Exception as exc:
            observed = str(exc)
            status = "pass" if expected in observed else "fail"
        _log_case(env, "expand_missing_settings", status, expected, observed)
        assert expected in observed
    finally:
        client.close()
