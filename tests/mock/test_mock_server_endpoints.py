import json
import os
import socket
import subprocess
import time
from contextlib import closing
from urllib import request

import pytest
import shutil


def _find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, timeout_s: float = 3.0) -> None:
    deadline = time.time() + timeout_s
    url = f"http://127.0.0.1:{port}/health"
    last_err = None
    while time.time() < deadline:
        try:
            with request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - best effort
            last_err = exc
            time.sleep(0.1)
    raise RuntimeError(f"Mock server did not start in time: {last_err}")


@pytest.fixture(scope="module")
def mock_server():
    if not shutil.which("node"):
        pytest.skip("node is not installed")

    port = _find_free_port()
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["NODE_ENV"] = "test"

    proc = subprocess.Popen(
        ["node", "frontend/mock/server.js"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        _wait_for_health(port)
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def _get_json(url: str) -> dict:
    with request.urlopen(url, timeout=2) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=2) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def test_app_config_dev_and_prod(mock_server) -> None:
    port = mock_server
    for mode in ("dev", "prod"):
        data = _get_json(f"http://127.0.0.1:{port}/app-config/{mode}")
        assert "consultants" in data
        assert "defaultConsultantId" in data
        assert data.get("isMultilingualProject") is True
        assert data.get("neutralLanguage") == "en"
        assert data.get("translatedLanguage") == "pl"


def test_search_and_query_dev_and_prod(mock_server) -> None:
    port = mock_server
    payload = {"consultant": "rejewski", "query": "hi", "enableTrace": True}
    for mode in ("dev", "prod"):
        out = _post_json(f"http://127.0.0.1:{port}/search/{mode}", payload)
        assert "session_id" in out
        assert "results" in out
        assert "pipeline_run_id" in out

        out2 = _post_json(f"http://127.0.0.1:{port}/query/{mode}", payload)
        assert "session_id" in out2
        assert "results" in out2


def test_pipeline_stream_and_cancel(mock_server) -> None:
    port = mock_server
    with request.urlopen(
        f"http://127.0.0.1:{port}/pipeline/stream/dev?run_id=abc", timeout=2
    ) as resp:
        body = resp.read().decode("utf-8")
        assert "data:" in body
        assert "\"done\"" in body

    out = _post_json(f"http://127.0.0.1:{port}/pipeline/cancel/prod", {"run_id": "abc"})
    assert out.get("ok") is True
