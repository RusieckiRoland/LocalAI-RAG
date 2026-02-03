from server.snapshots.snapshot_registry import SnapshotRegistry


class _FakeObj:
    def __init__(self, properties):
        self.properties = properties


class _FakeQueryResult:
    def __init__(self, objects):
        self.objects = objects


class _FakeQuery:
    def __init__(self, handler):
        self._handler = handler

    def fetch_objects(self, filters=None, limit=None, return_properties=None):
        return self._handler(filters, limit, return_properties)


class _FakeCollection:
    def __init__(self, handler):
        self.query = _FakeQuery(handler)


class _FakeCollections:
    def __init__(self, handlers):
        self._handlers = handlers

    def use(self, name):
        return _FakeCollection(self._handlers[name])


class _FakeClient:
    def __init__(self, handlers):
        self.collections = _FakeCollections(handlers)


def test_snapshot_registry_uses_allowed_refs_when_aligned():
    def snapshot_set_handler(*_):
        return _FakeQueryResult([
            _FakeObj({
                "snapshot_set_id": "set1",
                "repo": "nop",
                "allowed_snapshot_ids": ["s1", "s2"],
                "allowed_refs": ["Release_1", "Release_2"],
            })
        ])

    def import_handler(*_):
        raise AssertionError("ImportRun should not be queried when allowed_refs match")

    client = _FakeClient({
        "SnapshotSet": snapshot_set_handler,
        "ImportRun": import_handler,
    })

    reg = SnapshotRegistry(client)
    labels = reg.list_snapshots(snapshot_set_id="set1", repository="nop")

    assert [(x.id, x.label) for x in labels] == [("s1", "Release_1"), ("s2", "Release_2")]


def test_snapshot_registry_fallbacks_to_import_labels(monkeypatch):
    def snapshot_set_handler(*_):
        return _FakeQueryResult([
            _FakeObj({
                "snapshot_set_id": "set1",
                "repo": "nop",
                "allowed_snapshot_ids": ["s1", "s2"],
                "allowed_refs": [],
            })
        ])

    client = _FakeClient({
        "SnapshotSet": snapshot_set_handler,
        "ImportRun": lambda *_: _FakeQueryResult([]),
    })

    reg = SnapshotRegistry(client)

    monkeypatch.setattr(SnapshotRegistry, "_resolve_snapshot_label", lambda self, repo, sid: "Nice" if sid == "s1" else sid)

    labels = reg.list_snapshots(snapshot_set_id="set1", repository="nop")
    assert [(x.id, x.label) for x in labels] == [("s1", "Nice"), ("s2", "s2")]
