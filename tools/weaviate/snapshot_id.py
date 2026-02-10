from __future__ import annotations

from typing import Any, Mapping, Tuple

from weaviate.util import generate_uuid5


def extract_repo_name(meta: Mapping[str, Any]) -> str:
    repo_name = str(
        meta.get("RepoName")
        or meta.get("Repo")
        or meta.get("Repository")
        or meta.get("RepositoryName")
        or meta.get("repo")
        or meta.get("repository")
        or ""
    ).strip()

    if not repo_name:
        repo_root = str(meta.get("RepositoryRoot") or "").strip()
        if repo_root:
            repo_root = repo_root.rstrip("/\\")
            repo_name = repo_root.split("/")[-1].split("\\")[-1].strip()

    return repo_name or "unknown-repo"


def extract_head_sha(meta: Mapping[str, Any]) -> str:
    head_sha_raw = meta.get("HeadSha") or meta.get("HeadSHA") or meta.get("head_sha")
    return str(head_sha_raw or "").strip()


def extract_folder_fingerprint(meta: Mapping[str, Any]) -> str:
    folder_raw = meta.get("FolderFingerprint") or meta.get("folder_fingerprint")
    return str(folder_raw or "").strip()


def compute_snapshot_id(*, repo_name: str, head_sha: str = "", folder_fingerprint: str = "") -> str:
    repo = (repo_name or "").strip() or "unknown-repo"
    sha = (head_sha or "").strip()
    fingerprint = (folder_fingerprint or "").strip()

    if sha:
        return str(generate_uuid5(f"{repo}:{sha}"))
    if fingerprint:
        return str(generate_uuid5(f"{repo}:{fingerprint}"))
    raise ValueError("cannot compute snapshot_id: both HeadSha and FolderFingerprint are empty")


def compute_snapshot_id_from_repo_meta(meta: Mapping[str, Any]) -> Tuple[str, str, str]:
    repo = extract_repo_name(meta)
    sha = extract_head_sha(meta)
    fingerprint = extract_folder_fingerprint(meta)
    snapshot_id = compute_snapshot_id(repo_name=repo, head_sha=sha, folder_fingerprint=fingerprint)
    return repo, snapshot_id, sha
