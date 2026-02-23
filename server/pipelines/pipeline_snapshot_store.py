from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Tuple


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineSnapshotStore:
    """
    Resolves pipeline -> snapshot_set_id from the loaded pipeline settings.

    Source of truth:
    - pipeline YAML settings (settings.snapshot_set_id)
    """
    pipeline_settings_by_name: Any

    def get_snapshot_set_id(self, pipeline_name: str) -> Tuple[bool, Optional[str]]:
        name = (pipeline_name or "").strip()
        if not name:
            return False, None

        settings = None
        try:
            settings = (self.pipeline_settings_by_name or {}).get(name)
        except Exception:
            settings = None

        if not isinstance(settings, dict):
            return False, None

        snapshot_set_id = str(settings.get("snapshot_set_id") or "").strip()
        return True, (snapshot_set_id or None)
