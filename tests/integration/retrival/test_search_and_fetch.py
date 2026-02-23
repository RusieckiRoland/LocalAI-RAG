from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import json
import os

import pytest

from tests.integration.retrival.helpers import (
    QueryCase,
    connect,
    load_bundle_metadata,
    load_observed_docs,
    load_observed_sources,
    parse_golden_results,
    run_search_and_fetch,
    write_pipeline_trace,
    write_test_results_log,
    is_visible,
)


GOLDEN_PATH = Path("tests/integration/fake_data/retrieval_results_top5_corpus1_corpus2.md")
GOLDEN_CASES = parse_golden_results(GOLDEN_PATH)

_USER_ACL = ["finance", "security"]
_USER_LABELS = ["public", "internal", "secret"]
_USER_LEVEL = 10

def _build_filters(env, corpus: str) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if corpus == "csharp":
        filters["source_system_id"] = "code.csharp"
    else:
        filters["source_system_id"] = "code.sql"

    if env.round.permissions.get("acl_enabled", True):
        filters["acl_tags_any"] = list(_USER_ACL)

    if env.round.permissions.get("security_enabled", False):
        model = env.round.permissions.get("security_model") or {}
        kind = model.get("kind")
        if kind == "clearance_level":
            filters["user_level"] = _USER_LEVEL
        elif kind in ("labels_universe_subset", "classification_labels"):
            filters["classification_labels_all"] = list(_USER_LABELS)
    return filters


def _expected_sources(env, case: QueryCase) -> List[str]:
    # Use primary bundle metadata (first in round).
    meta = load_bundle_metadata(env.bundle_paths[0])
    filters = _build_filters(env, case.corpus)
    acl_any = list(filters.get("acl_tags_any") or [])
    labels_all = list(filters.get("classification_labels_all") or [])
    user_level = filters.get("user_level")

    out: List[str] = []
    for src in case.expected_sources:
        m = meta.get(src, {"acl": [], "labels": [], "clearance": None})
        if is_visible(
            m,
            acl_any=acl_any,
            labels_all=labels_all,
            user_level=user_level,
            permissions=env.round.permissions,
        ):
            out.append(src)
    return out


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[f"{c.corpus}:{c.search_type}:{c.query_id}" for c in GOLDEN_CASES])
def test_search_then_fetch_matches_expected_markers(retrieval_integration_env, case: QueryCase) -> None:
    env = retrieval_integration_env
    filters = _build_filters(env, case.corpus)

    state = run_search_and_fetch(env=env, case=case, retrieval_filters=filters)
    client = connect(env)
    try:
        observed_sources = load_observed_sources(client, state, env.repo_name)
        observed_docs = load_observed_docs(client, state, env.repo_name)
    finally:
        client.close()

    expected_sources = _expected_sources(env, case)
    observed_docs = observed_docs or []
    security_entries: List[str] = []
    for doc in observed_docs:
        source = str(doc.get("source_file") or "")
        acl = ",".join(str(x) for x in (doc.get("acl_allow") or [])) or "-"
        labels = ",".join(str(x) for x in (doc.get("classification_labels") or [])) or "-"
        doc_level = str(doc.get("doc_level") or "-")
        security_entries.append(f"{source} [acl={acl} | cls={labels} | lvl={doc_level}]")

    filters_text = json.dumps(state.retrieval_filters or {}, ensure_ascii=False, sort_keys=True)
    test_id = f"search_then_fetch::{case.corpus}:{case.search_type}:{case.query_id}"
    write_test_results_log(
        test_id=test_id,
        lines=[
            f"Test : {test_id}",
            f"Round : {env.round.id}",
            f"Query : {case.query}",
            f"Search mode : {case.search_type}",
            f"Applied filters : {filters_text}",
            f"Expected sources : {'; '.join(expected_sources)}",
            f"Observed sources : {'; '.join(observed_sources)}",
            f"Observed security : {'; '.join(security_entries)}",
        ],
    )
    write_pipeline_trace(search_type=case.search_type, query=case.query, retrieval_filters=filters, observed_sources=observed_sources)

    assert state.retrieval_seed_nodes, "search_nodes returned no seed nodes."

    if not env.round.permissions.get("acl_enabled", True) and not env.round.permissions.get("security_enabled", False):
        assert observed_sources == expected_sources, (
            f"Expected sources {expected_sources} but got {observed_sources} "
            f"for round={env.round.id} corpus={case.corpus}"
        )
    else:
        meta = load_bundle_metadata(env.bundle_paths[0])
        for src in observed_sources:
            m = meta.get(src, {"acl": [], "labels": [], "clearance": None})
            assert is_visible(
                m,
                acl_any=list(filters.get("acl_tags_any") or []),
                labels_all=list(filters.get("classification_labels_all") or []),
                user_level=filters.get("user_level"),
                permissions=env.round.permissions,
            ), f"Observed source not allowed by filters: {src}"
    if observed_sources:
        assert state.node_texts, "fetch_node_texts returned no texts."
