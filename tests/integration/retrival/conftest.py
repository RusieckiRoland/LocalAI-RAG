from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.request import urlopen

import pytest


@dataclass(frozen=True)
class RetrievalIntegrationEnv:
    weaviate_host: str
    weaviate_http_port: int
    weaviate_grpc_port: int
    snapshot_set_id: str
    repo_name: str
    imported_refs: tuple[str, ...]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    integration_root = Path(__file__).resolve().parent
    for item in items:
        try:
            p = Path(str(item.path)).resolve()
        except Exception:
            continue
        if integration_root in p.parents:
            item.add_marker(pytest.mark.integration)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_command(cmd: list[str], *, cwd: Path, timeout_s: int = 900) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        joined = " ".join(cmd)
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {joined}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )
    return proc


def _docker_logs(container_name: str) -> str:
    proc = subprocess.run(
        ["docker", "logs", container_name],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return f"(docker logs unavailable: {proc.stderr.strip()})"
    return proc.stdout.strip()


def _wait_for_weaviate_ready(*, host: str, http_port: int, timeout_s: int = 120) -> None:
    deadline = time.monotonic() + timeout_s
    url = f"http://{host}:{http_port}/v1/.well-known/ready"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= int(response.status) < 300:
                    return
        except (URLError, ConnectionResetError, TimeoutError, OSError):
            time.sleep(1)
            continue
        time.sleep(1)
    raise TimeoutError(f"Weaviate did not become ready within {timeout_s}s ({url}).")


def _extract_repo_name(bundle_zip: Path) -> str:
    with zipfile.ZipFile(bundle_zip, "r") as zf:
        names = [n for n in zf.namelist() if n.endswith("repo_meta.json")]
        if not names:
            return "unknown-repo"
        meta = json.loads(zf.read(names[0]).decode("utf-8", errors="replace"))

    for key in ("Repo", "Repository", "RepositoryName", "repo", "repository"):
        val = str(meta.get(key) or "").strip()
        if val:
            return val

    repo_root = str(meta.get("RepositoryRoot") or "").strip().rstrip("/\\")
    if repo_root:
        return repo_root.split("/")[-1].split("\\")[-1].strip() or "unknown-repo"
    return "unknown-repo"


def _assert_docker_available() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for retrieval integration tests.")
    probe = subprocess.run(["docker", "info"], text=True, capture_output=True, check=False)
    if probe.returncode != 0:
        pytest.skip("Docker daemon is not available. Start Docker and rerun integration tests.")


def _collect_bundles(bundles_dir: Path) -> list[Path]:
    pattern = os.getenv("INTEGRATION_BUNDLE_GLOB", "Release_FAKE_ENTERPRISE_*.zip").strip() or "*.zip"
    bundles = sorted(p for p in bundles_dir.glob(pattern) if p.is_file())
    if not bundles:
        pytest.skip(f"No fake repositories found in {bundles_dir} matching {pattern!r}")
    return bundles


def _unique(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


@pytest.fixture(scope="session")
def retrieval_integration_env() -> RetrievalIntegrationEnv:
    """
    End-to-end integration fixture:
    1) starts dedicated Weaviate container on non-conflicting host ports
    2) imports fake bundles from tests/repositories/fake
    3) creates SnapshotSet: Fake_snapshot
    4) tears down the container after test session
    """
    if os.getenv("RUN_INTEGRATION_TESTS", "").strip() != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run retrieval integration tests.")

    _assert_docker_available()

    repo_root = Path(__file__).resolve().parents[3]
    fake_bundles_dir = repo_root / "tests" / "repositories" / "fake"
    bundles = _collect_bundles(fake_bundles_dir)

    embed_model = os.getenv("INTEGRATION_EMBED_MODEL", "models/embedding/e5-base-v2").strip()
    if not embed_model:
        pytest.skip("INTEGRATION_EMBED_MODEL is empty.")

    repo_names = _unique(_extract_repo_name(bundle) for bundle in bundles)
    if len(repo_names) != 1:
        raise RuntimeError(f"Expected one repository name in fake bundles, got: {repo_names}")
    repo_name = repo_names[0]

    host = "127.0.0.1"
    http_port = _find_free_port()
    grpc_port = _find_free_port()
    while grpc_port == http_port:
        grpc_port = _find_free_port()
    container_name = f"weaviate-it-{uuid.uuid4().hex[:10]}"
    snapshot_set_id = "Fake_snapshot"
    imported_refs: list[str] = []

    docker_cmd = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        container_name,
        "-p",
        f"{host}:{http_port}:8080",
        "-p",
        f"{host}:{grpc_port}:50051",
        "-e",
        "QUERY_DEFAULTS_LIMIT=25",
        "-e",
        "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true",
        "-e",
        "PERSISTENCE_DATA_PATH=/var/lib/weaviate",
        "-e",
        "DEFAULT_VECTORIZER_MODULE=none",
        "-e",
        "ENABLE_MODULES=",
        "-e",
        "CLUSTER_HOSTNAME=node1",
        "cr.weaviate.io/semitechnologies/weaviate:1.32.2",
    ]

    try:
        _run_command(docker_cmd, cwd=repo_root, timeout_s=90)
        try:
            _wait_for_weaviate_ready(host=host, http_port=http_port, timeout_s=180)
        except TimeoutError as ex:
            logs = _docker_logs(container_name)
            raise RuntimeError(f"{ex}\nContainer logs:\n{logs}\n") from ex

        for bundle in bundles:
            ref_name = bundle.stem
            imported_refs.append(ref_name)
            import_cmd = [
                sys.executable,
                "-m",
                "tools.weaviate.import_branch_to_weaviate",
                "--bundle",
                str(bundle),
                "--weaviate-host",
                host,
                "--weaviate-http-port",
                str(http_port),
                "--weaviate-grpc-port",
                str(grpc_port),
                "--embed-model",
                embed_model,
                "--ref-type",
                "tag",
                "--ref-name",
                ref_name,
                "--tag",
                ref_name,
                "--import-id",
                f"it::{ref_name}",
            ]
            _run_command(import_cmd, cwd=repo_root, timeout_s=1800)

        snapshot_cmd = [
            sys.executable,
            "-m",
            "tools.weaviate.snapshot_sets",
            "--weaviate-host",
            host,
            "--weaviate-http-port",
            str(http_port),
            "--weaviate-grpc-port",
            str(grpc_port),
            "add",
            "--id",
            snapshot_set_id,
            "--repo",
            repo_name,
            "--refs",
            *imported_refs,
            "--description",
            "Integration tests fake snapshot set",
        ]
        _run_command(snapshot_cmd, cwd=repo_root, timeout_s=120)

        yield RetrievalIntegrationEnv(
            weaviate_host=host,
            weaviate_http_port=http_port,
            weaviate_grpc_port=grpc_port,
            snapshot_set_id=snapshot_set_id,
            repo_name=repo_name,
            imported_refs=tuple(imported_refs),
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            text=True,
            capture_output=True,
            check=False,
        )
