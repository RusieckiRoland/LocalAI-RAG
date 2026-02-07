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
from typing import Iterable, List
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from tests.integration.retrival.helpers import write_named_log, write_test_results_log


@dataclass(frozen=True)
class RoundConfig:
    id: str
    permissions: dict
    bundle_refs: tuple[str, str]


@dataclass(frozen=True)
class RetrievalIntegrationEnv:
    weaviate_host: str
    weaviate_http_port: int
    weaviate_grpc_port: int
    snapshot_set_id: str
    repo_name: str
    imported_refs: tuple[str, ...]
    round: RoundConfig
    bundle_paths: tuple[Path, ...]


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


def _unique(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _bundle_paths(repo_root: Path) -> list[Path]:
    fake_dir = repo_root / "tests" / "repositories" / "fake"
    return sorted(
        fake_dir / name
        for name in (
            "Release_FAKE_ENTERPRISE_1.0.zip",
            "Release_FAKE_ENTERPRISE_1.1.zip",
            "Release_FAKE_ENTERPRISE_2.0.zip",
            "Release_FAKE_ENTERPRISE_2.1.zip",
            "Release_FAKE_ENTERPRISE_3.0.zip",
            "Release_FAKE_ENTERPRISE_3.1.zip",
            "Release_FAKE_ENTERPRISE_4.0.zip",
            "Release_FAKE_ENTERPRISE_4.1.zip",
        )
    )


def _write_permissions_config(repo_root: Path, permissions: dict) -> None:
    for rel in ("config.json", "tests/config.json"):
        cfg_path = repo_root / rel
        if not cfg_path.exists():
            continue
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw["permissions"] = permissions
        cfg_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


ROUNDS: list[RoundConfig] = [
    RoundConfig(
        id="round-1",
        permissions={
            "security_enabled": False,
            "acl_enabled": False,
            "require_travel_permission": False,
        },
        bundle_refs=("Release_FAKE_ENTERPRISE_1.0", "Release_FAKE_ENTERPRISE_1.1"),
    ),
    RoundConfig(
        id="round-2",
        permissions={
            "security_enabled": True,
            "acl_enabled": True,
            "require_travel_permission": True,
            "security_model": {
                "kind": "clearance_level",
                "clearance_level": {
                    "doc_level_field": "doc_level",
                    "user_level_source": "claim",
                    "user_level_claim": "user_level",
                    "default_doc_level": 0,
                    "allow_missing_doc_level": True,
                    "levels": {
                        "public": 0,
                        "internal": 10,
                        "restricted": 20,
                        "critical": 30,
                    },
                },
            },
        },
        bundle_refs=("Release_FAKE_ENTERPRISE_2.0", "Release_FAKE_ENTERPRISE_2.1"),
    ),
    RoundConfig(
        id="round-3",
        permissions={
            "security_enabled": True,
            "acl_enabled": True,
            "require_travel_permission": False,
            "security_model": {
                "kind": "labels_universe_subset",
                "labels_universe_subset": {
                    "doc_labels_field": "classification_labels",
                    "user_labels_source": "claim",
                    "user_labels_claim": "labels",
                    "allow_unlabeled": True,
                    "classification_labels_universe": [
                        "public",
                        "internal",
                        "secret",
                        "restricted",
                    ],
                },
            },
        },
        bundle_refs=("Release_FAKE_ENTERPRISE_3.0", "Release_FAKE_ENTERPRISE_3.1"),
    ),
    RoundConfig(
        id="round-4",
        permissions={
            "security_enabled": False,
            "acl_enabled": True,
            "require_travel_permission": True,
        },
        bundle_refs=("Release_FAKE_ENTERPRISE_4.0", "Release_FAKE_ENTERPRISE_4.1"),
    ),
]


@pytest.fixture(scope="session", autouse=True)
def _generate_fake_bundles() -> Iterable[Path]:
    if os.getenv("RUN_INTEGRATION_TESTS", "").strip() != "1":
        return

    repo_root = Path(__file__).resolve().parents[3]
    bundles = _bundle_paths(repo_root)

    # Generate fresh bundles for this test session.
    _run_command([sys.executable, "-m", "tools.generate_retrieval_corpora_bundles"], cwd=repo_root, timeout_s=600)

    missing = [p for p in bundles if not p.exists()]
    if missing:
        raise RuntimeError(f"Bundle generation failed; missing: {missing}")

    try:
        yield bundles
    finally:
        for p in bundles:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                # Best-effort cleanup.
                pass


@pytest.fixture(scope="session", autouse=True)
def _backup_and_restore_config() -> Iterable[None]:
    if os.getenv("RUN_INTEGRATION_TESTS", "").strip() != "1":
        return

    repo_root = Path(__file__).resolve().parents[3]
    backups: dict[Path, str] = {}
    for rel in ("config.json", "tests/config.json"):
        cfg_path = repo_root / rel
        if cfg_path.exists():
            backups[cfg_path] = cfg_path.read_text(encoding="utf-8")

    try:
        yield None
    finally:
        for path, content in backups.items():
            try:
                path.write_text(content, encoding="utf-8")
            except Exception:
                pass


@pytest.fixture(scope="session", params=ROUNDS, ids=[r.id for r in ROUNDS])
def retrieval_integration_env(request) -> Iterable[RetrievalIntegrationEnv]:
    if os.getenv("RUN_INTEGRATION_TESTS", "").strip() != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run retrieval integration tests.")

    _assert_docker_available()

    round_cfg: RoundConfig = request.param
    repo_root = Path(__file__).resolve().parents[3]

    _write_permissions_config(repo_root, round_cfg.permissions)

    os.environ["ACL_ENABLED"] = "true" if round_cfg.permissions.get("acl_enabled", True) else "false"
    os.environ["REQUIRE_TRAVEL_PERMISSION"] = "true" if round_cfg.permissions.get("require_travel_permission", True) else "false"

    embed_model = os.getenv("INTEGRATION_EMBED_MODEL", "models/embedding/e5-base-v2").strip()
    if not embed_model:
        pytest.skip("INTEGRATION_EMBED_MODEL is empty.")

    fake_dir = repo_root / "tests" / "repositories" / "fake"
    bundle_paths = tuple(fake_dir / f"{ref}.zip" for ref in round_cfg.bundle_refs)
    for p in bundle_paths:
        if not p.exists():
            pytest.skip(f"Missing bundle: {p}")

    repo_names = _unique(_extract_repo_name(bundle) for bundle in bundle_paths)
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
        create_lines = [
            f"Round : {round_cfg.id}",
            "Event : container_create",
            f"Container : {container_name}",
            f"Host : {host}",
            f"HTTP port : {http_port}",
            f"gRPC port : {grpc_port}",
            f"Bundles : {', '.join(round_cfg.bundle_refs)}",
        ]
        print("[integration] container_create")
        for line in create_lines:
            print(f"[integration] {line}")
        write_named_log(stem="container_lifecycle", test_id=f"{round_cfg.id}_create", lines=create_lines)
        write_test_results_log(test_id=f"container_create::{round_cfg.id}", lines=create_lines)
        try:
            _wait_for_weaviate_ready(host=host, http_port=http_port, timeout_s=180)
        except TimeoutError as ex:
            logs = _docker_logs(container_name)
            raise RuntimeError(f"{ex}\nContainer logs:\n{logs}\n") from ex

        for bundle in bundle_paths:
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
            f"Integration tests {round_cfg.id}",
        ]
        _run_command(snapshot_cmd, cwd=repo_root, timeout_s=120)

        yield RetrievalIntegrationEnv(
            weaviate_host=host,
            weaviate_http_port=http_port,
            weaviate_grpc_port=grpc_port,
            snapshot_set_id=snapshot_set_id,
            repo_name=repo_name,
            imported_refs=tuple(imported_refs),
            round=round_cfg,
            bundle_paths=bundle_paths,
        )
    finally:
        rm_proc = subprocess.run(
            ["docker", "rm", "-f", container_name],
            text=True,
            capture_output=True,
            check=False,
        )
        destroy_lines = [
            f"Round : {round_cfg.id}",
            "Event : container_destroy",
            f"Container : {container_name}",
            f"Return code : {rm_proc.returncode}",
            f"stdout : {rm_proc.stdout.strip()}",
            f"stderr : {rm_proc.stderr.strip()}",
        ]
        print("[integration] container_destroy")
        for line in destroy_lines:
            print(f"[integration] {line}")
        write_named_log(stem="container_lifecycle", test_id=f"{round_cfg.id}_destroy", lines=destroy_lines)
        write_test_results_log(test_id=f"container_destroy::{round_cfg.id}", lines=destroy_lines)
