from server.pipelines.pipeline_snapshot_store import PipelineSnapshotStore


def test_pipeline_snapshot_store_reads_snapshot_set_id():
    store = PipelineSnapshotStore({"rejewski": {"snapshot_set_id": "set1"}})

    exists, sid = store.get_snapshot_set_id("rejewski")

    assert exists is True
    assert sid == "set1"


def test_pipeline_snapshot_store_missing_pipeline():
    store = PipelineSnapshotStore({})

    exists, sid = store.get_snapshot_set_id("missing")

    assert exists is False
    assert sid is None
