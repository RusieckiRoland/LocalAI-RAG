from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BranchResolver:
    """
    Branch list resolver (snapshot-based mode returns empty).
    """
    project_root: str

    def list_branches(self, cfg: Dict[str, Any]) -> List[str]:
        # Snapshot-based flow: branches are not sourced from FAISS manifests anymore.
        # Keep the method but return empty to avoid legacy coupling.
        _ = cfg
        return []

    def pick_default(self, branches: List[str]) -> str:
        return branches[0] if branches else ""

    def _extract_branch_name(self, item: Any) -> None:
        _ = item
        return None

    def _load_json_file(self, path: str) -> Dict[str, Any]:
        _ = path
        return {}
