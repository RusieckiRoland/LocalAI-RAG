import os
import sys
import json

# Ensure repo root is on sys.path (pytest runs from ./tests sometimes)
THIS_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from code_query_engine.pipeline.providers.file_system_graph_provider import FileSystemGraphProvider


REPO = "fake"
BRANCH = "Release_FAKE_UNIVERSAL_4.60"

CANONICAL_IDS = [
    f"{REPO}::{BRANCH}::C0001",
    f"{REPO}::{BRANCH}::C0002",
    f"{REPO}::{BRANCH}::C0178",
]


def test_07_graph_provider_fetch_node_texts_smoke() -> None:
    """
    This test isolates the materialization bug.

    We KNOW chunks.json contains Text (proved by manual python -c).
    So if fetch_node_texts still returns empty strings -> the bug is in:
      - path resolution
      - ID canonical->local mapping
      - OR fetch_node_texts logic

    This test checks all 3 in one place with explicit diagnostics.
    """

    # IMPORTANT:
    # Running from ./tests, fake repositories live in ./tests/repositories
    provider = FileSystemGraphProvider(repositories_root="repositories")

    # 1) Verify the exact file path that provider resolves
    paths = provider._resolve_paths(repository=REPO, branch=BRANCH)
    chunks_path = paths.chunks_json

    print("\n--- RESOLVED PATHS ---")
    print("chunks_json =", chunks_path)
    assert os.path.isfile(chunks_path), f"chunks.json does not exist at resolved path: {chunks_path}"

    # 2) Raw file sanity (independent from provider mapping)
    with open(chunks_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    assert isinstance(raw, list) and raw, "chunks.json parsed but is empty or not a list"
    first = raw[0]
    assert isinstance(first, dict), "chunks.json first item is not a dict"

    # Find C0001 in raw file
    c0001 = None
    for c in raw:
        if isinstance(c, dict) and str(c.get("Id")) == "C0001":
            c0001 = c
            break

    assert c0001 is not None, "C0001 not found in raw chunks.json (unexpected)"

    raw_text_len = len((c0001.get("Text") or "").strip())
    print("\n--- RAW FILE CHECK ---")
    print("C0001 raw len(Text) =", raw_text_len)
    assert raw_text_len > 0, "RAW chunks.json has empty Text for C0001 (contradicts your proof)"

    # 3) Provider internal load (should match raw file)
    chunks_by_id = provider._load_chunks(repository=REPO, branch=BRANCH)
    assert "C0001" in chunks_by_id, "provider._load_chunks() did not index C0001"

    loaded_text_len = len((chunks_by_id["C0001"].get("Text") or "").strip())
    print("\n--- PROVIDER _load_chunks CHECK ---")
    print("C0001 loaded len(Text) =", loaded_text_len)
    assert loaded_text_len > 0, "provider._load_chunks() loaded empty Text for C0001"

    # 4) The real failing call: canonical IDs -> fetch_node_texts -> materialized text
    out = provider.fetch_node_texts(
        node_ids=CANONICAL_IDS,
        repository=REPO,
        branch=BRANCH,
        active_index=None,
        max_chars=50_000,
    )

    assert isinstance(out, list), "fetch_node_texts did not return a list"
    assert out, "fetch_node_texts returned empty list"

    print("\n--- fetch_node_texts OUTPUT ---")
    by_id = {x.get("id"): (x.get("text") or "") for x in out if isinstance(x, dict)}
    for cid in CANONICAL_IDS:
        txt = by_id.get(cid, "")
        print(f"id={cid} text_len={len(txt)}")

    # This is the contract signal:
    # If this fails -> canonical->local mapping OR provider fetch logic is broken.
    assert any((by_id.get(cid) or "").strip() for cid in CANONICAL_IDS), (
        "fetch_node_texts returned ONLY EMPTY texts.\n"
        "RAW file and _load_chunks prove Text exists.\n"
        "So the bug is inside fetch_node_texts() mapping/canonical stripping logic."
    )
