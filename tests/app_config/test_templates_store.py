import json
import os
import time

from server.app_config.templates_store import TemplatesStore


def test_templates_store_cache_refreshes_on_mtime_change(tmp_path):
    path = tmp_path / "templates.json"
    path.write_text(json.dumps({"v": 1}), encoding="utf-8")

    store = TemplatesStore(candidates=[str(path)])
    first = store.load()
    assert first.get("v") == 1

    time.sleep(0.01)
    path.write_text(json.dumps({"v": 2}), encoding="utf-8")
    os.utime(path, None)

    second = store.load()
    assert second.get("v") == 2
