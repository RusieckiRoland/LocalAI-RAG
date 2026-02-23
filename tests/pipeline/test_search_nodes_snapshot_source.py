from __future__ import annotations

import pytest

from code_query_engine.pipeline.actions.search_nodes import _resolve_snapshot_scope
from code_query_engine.pipeline.state import PipelineState


def _state(*, snapshot_id: str | None, snapshot_id_b: str | None) -> PipelineState:
    return PipelineState(
        user_query="q",
        session_id="s",
        consultant="c",
        snapshot_id=snapshot_id,
        snapshot_id_b=snapshot_id_b,
    )


def test_snapshot_source_primary_is_default() -> None:
    sid, sid_b, any_ids = _resolve_snapshot_scope({}, _state(snapshot_id="s1", snapshot_id_b="s2"), {})
    assert sid == "s1"
    assert sid_b == "s2"
    assert any_ids is None


def test_snapshot_source_secondary_uses_snapshot_id_b() -> None:
    sid, sid_b, any_ids = _resolve_snapshot_scope({}, _state(snapshot_id="s1", snapshot_id_b="s2"), {"snapshot_source": "secondary"})
    assert sid == "s2"
    assert sid_b == "s2"
    assert any_ids is None


def test_snapshot_source_both_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid snapshot_source='both'"):
        _resolve_snapshot_scope({}, _state(snapshot_id="s1", snapshot_id_b="s2"), {"snapshot_source": "both"})


def test_snapshot_source_secondary_requires_snapshot_id_b() -> None:
    with pytest.raises(ValueError, match="Missing required 'snapshot_id_b'"):
        _resolve_snapshot_scope({}, _state(snapshot_id="s1", snapshot_id_b=None), {"snapshot_source": "secondary"})
