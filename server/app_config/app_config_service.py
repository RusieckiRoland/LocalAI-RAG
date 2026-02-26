from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from server.auth import UserAccessProvider
from server.pipelines.pipeline_access import PipelineAccessService
from server.pipelines.pipeline_snapshot_store import PipelineSnapshotStore
from server.snapshots.snapshot_registry import SnapshotRegistry


@dataclass(frozen=True)
class AppConfigService:
    templates_store: Any
    access_provider: UserAccessProvider
    pipeline_access: PipelineAccessService
    snapshot_registry: Optional[SnapshotRegistry]
    pipeline_snapshot_store: Optional[PipelineSnapshotStore]
    snapshot_policy: str

    def build_app_config(
        self,
        *,
        runtime_cfg: Dict[str, Any],
        session_id: str,
        auth_header: str,
        claims: Optional[Dict[str, object]] = None,
    ) -> Dict[str, Any]:
        templates = self.templates_store.load()
        multilingual_enabled, neutral_language, translated_language = self._resolve_language_config(runtime_cfg)

        access_ctx = self.access_provider.resolve(
            user_id=None,
            token=auth_header,
            session_id=session_id,
            claims=claims,
        )

        repos = self._list_repositories(runtime_cfg)
        repo_name = str(runtime_cfg.get("repo_name") or "").strip() or (repos[0] if repos else "")

        consultants, default_consultant_id = self.pipeline_access.filter_consultants(
            templates,
            allowed_pipelines=access_ctx.allowed_pipelines,
        )

        consultants = self._attach_snapshots(consultants, repository=repo_name)

        return {
            "repositories": repos,
            "defaultRepository": repo_name,
            "consultants": consultants,
            "defaultConsultantId": default_consultant_id,
            "templates": templates,
            "translateChat": multilingual_enabled,
            "isMultilingualProject": multilingual_enabled,
            "neutralLanguage": neutral_language,
            "translatedLanguage": translated_language,
            "snapshotPolicy": self.snapshot_policy,
            "historyGroups": runtime_cfg.get("history_groups") or [],
            "historyImportant": runtime_cfg.get("history_important") or {},
        }

    def _list_repositories(self, cfg: Dict[str, Any]) -> List[str]:
        import os
        project_root = str(cfg.get("project_root") or "").strip()
        repos_root = cfg.get("repositories_root")

        if not repos_root:
            # Legacy: derive from project root.
            repos_root = os.path.join(project_root, "repositories") if project_root else "repositories"

        try:
            out: List[str] = []
            if not os.path.isdir(repos_root):
                return out
            for name in sorted(os.listdir(repos_root)):
                p = os.path.join(repos_root, name)
                if os.path.isdir(p):
                    out.append(name)
            return out
        except Exception:
            return []

    def _attach_snapshots(self, consultants: List[Dict[str, Any]], *, repository: str) -> List[Dict[str, Any]]:
        if not consultants:
            return consultants

        if not self.snapshot_registry or not self.pipeline_snapshot_store:
            return [self._with_snapshot_fields(c, snapshot_set_id=None, snapshots=[]) for c in consultants]

        out: List[Dict[str, Any]] = []
        for c in consultants:
            pipeline_name = str(c.get("pipelineName") or "").strip()
            exists, snapshot_set_id = self.pipeline_snapshot_store.get_snapshot_set_id(pipeline_name)

            if not exists:
                raise ValueError(f"Pipeline '{pipeline_name}' not found in loaded pipeline settings")

            if snapshot_set_id:
                snapshots = self.snapshot_registry.list_snapshots(
                    snapshot_set_id=snapshot_set_id,
                    repository=repository or None,
                )
                out.append(self._with_snapshot_fields(c, snapshot_set_id=snapshot_set_id, snapshots=snapshots))
            else:
                out.append(self._with_snapshot_fields(c, snapshot_set_id=None, snapshots=[]))

        return out

    def _resolve_language_config(self, runtime_cfg: Dict[str, Any]) -> tuple[bool, str, str]:
        multilingual_enabled = self._coerce_bool(runtime_cfg.get("is_multilingual_project"), default=True)
        neutral_language = self._normalize_language_code(runtime_cfg.get("neutral_language"), default="en")
        translated_language = self._normalize_language_code(runtime_cfg.get("translated_language"), default="pl")
        return multilingual_enabled, neutral_language, translated_language

    @staticmethod
    def _coerce_bool(value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "yes", "y", "on"}:
                return True
            if v in {"0", "false", "no", "n", "off"}:
                return False
            return default
        return default

    @staticmethod
    def _normalize_language_code(value: Any, *, default: str) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return default
        # Normalize tags like "en-US" / "pt_BR" to a simple language code.
        norm = raw.replace("_", "-").split("-", 1)[0].strip()
        return norm or default

    def _with_snapshot_fields(
        self,
        consultant: Dict[str, Any],
        *,
        snapshot_set_id: Optional[str],
        snapshots: List[Any],
    ) -> Dict[str, Any]:
        cloned = dict(consultant or {})
        cloned["snapshotSetId"] = snapshot_set_id
        cloned["snapshots"] = [{"id": s.id, "label": s.label} for s in snapshots]
        return cloned
