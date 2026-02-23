from __future__ import annotations

import weaviate
from weaviate.classes.query import Filter


def _connect(env) -> weaviate.WeaviateClient:
    return weaviate.connect_to_local(
        host=env.weaviate_host,
        port=env.weaviate_http_port,
        grpc_port=env.weaviate_grpc_port,
    )


def test_snapshot_set_exists(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    client = _connect(env)
    try:
        coll = client.collections.use("SnapshotSet")
        result = coll.query.fetch_objects(
            filters=Filter.by_property("snapshot_set_id").equal(env.snapshot_set_id),
            return_properties=["repo", "allowed_refs", "allowed_snapshot_ids", "is_active"],
            limit=1,
        )

        assert len(result.objects) == 1
        props = result.objects[0].properties or {}
        assert props.get("repo") == env.repo_name
        assert sorted(props.get("allowed_refs") or []) == sorted(env.imported_refs)
        assert len(props.get("allowed_snapshot_ids") or []) >= len(env.imported_refs)
        assert bool(props.get("is_active")) is True
    finally:
        client.close()


def test_import_runs_completed(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    client = _connect(env)
    try:
        coll = client.collections.use("ImportRun")
        result = coll.query.fetch_objects(
            filters=Filter.all_of(
                [
                    Filter.by_property("repo").equal(env.repo_name),
                    Filter.by_property("status").equal("completed"),
                ]
            ),
            return_properties=["tag", "status"],
            limit=50,
        )
        tags = [str((obj.properties or {}).get("tag") or "").strip() for obj in result.objects]
        for ref in env.imported_refs:
            assert ref in tags
    finally:
        client.close()


def test_ragnode_schema_matches_permissions(retrieval_integration_env) -> None:
    env = retrieval_integration_env
    client = _connect(env)
    try:
        coll = client.collections.get("RagNode")
        cfg = coll.config.get()
        props = {p.name for p in (cfg.properties or [])}

        acl_enabled = bool(env.round.permissions.get("acl_enabled", True))
        security_enabled = bool(env.round.permissions.get("security_enabled", False))
        security_model = env.round.permissions.get("security_model") or {}
        kind = str(security_model.get("kind") or "")

        if acl_enabled:
            assert "acl_allow" in props
        else:
            assert "acl_allow" not in props

        if not security_enabled:
            assert "classification_labels" not in props
            assert "doc_level" not in props
            return

        if kind == "clearance_level":
            assert "doc_level" in props
            assert "classification_labels" not in props
        else:
            assert "classification_labels" in props
            assert "doc_level" not in props
    finally:
        client.close()
