from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Protocol, Tuple, Optional


@dataclass(frozen=True)
class GroupPolicy:
    """
    Group-level policy: ACL tags, classification labels and allowed pipelines.
    """
    allowed_pipelines: List[str] = field(default_factory=list)
    allowed_commands: List[str] = field(default_factory=list)
    acl_tags_any: List[str] = field(default_factory=list)
    classification_labels_all: List[str] = field(default_factory=list)
    user_level: Optional[int] = None
    owner_id: Optional[str] = None
    source_system_id: Optional[str] = None
    # Backward-compatible alias retained during migration.
    acl_tags_all: List[str] = field(default_factory=list)


class AuthPoliciesProvider(Protocol):
    def load(self) -> Tuple[Dict[str, GroupPolicy], List[Dict[str, object]]]:
        ...


@dataclass(frozen=True)
class JsonAuthPoliciesProvider:
    path: str

    def load(self) -> Tuple[Dict[str, GroupPolicy], List[Dict[str, object]]]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return {}, []
        except Exception:
            return {}, []

        groups = raw.get("groups")
        if not isinstance(groups, dict):
            return {}, []

        policies: Dict[str, GroupPolicy] = {}
        for group_id, payload in groups.items():
            if not isinstance(payload, dict):
                continue
            acl_any = payload.get("acl_tags_any")
            if acl_any is None:
                acl_any = payload.get("acl_tags_all")
            labels_all = payload.get("classification_labels_all") or []
            allowed = payload.get("allowed_pipelines") or []
            allowed_commands = payload.get("allowed_commands") or []
            user_level = payload.get("user_level")
            owner_id = str(payload.get("owner_id") or "").strip() or None
            source_system_id = str(payload.get("source_system_id") or "").strip() or None
            if not isinstance(acl_any, list) or not isinstance(labels_all, list) or not isinstance(allowed, list) or not isinstance(allowed_commands, list):
                continue
            policies[str(group_id)] = GroupPolicy(
                acl_tags_any=[str(x) for x in acl_any if str(x).strip()],
                classification_labels_all=[str(x) for x in labels_all if str(x).strip()],
                user_level=_normalize_int(user_level),
                owner_id=owner_id,
                source_system_id=source_system_id,
                acl_tags_all=[str(x) for x in acl_any if str(x).strip()],
                allowed_pipelines=[str(x) for x in allowed if str(x).strip()],
                allowed_commands=[str(x) for x in allowed_commands if str(x).strip()],
            )

        claim_group_mappings = raw.get("claim_group_mappings") or []
        if not isinstance(claim_group_mappings, list):
            claim_group_mappings = []
        claim_group_mappings = claim_group_mappings + _load_extra_claim_group_mappings()
        return policies, claim_group_mappings


def default_json_provider() -> JsonAuthPoliciesProvider:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    default_path = os.path.join(project_root, "config", "auth_policies.json")
    path = os.getenv("AUTH_POLICIES_PATH") or default_path
    return JsonAuthPoliciesProvider(path=path)


def _load_extra_claim_group_mappings() -> List[Dict[str, object]]:
    """
    Additional claim->group mappings stored outside of auth_policies.json.
    Intended for IAM/IDP mappings (e.g. token groups -> application roles).
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    default_path = os.path.join(project_root, "security_conf", "claim_group_mappings.json")
    path = os.getenv("CLAIM_GROUP_MAPPINGS_PATH") or default_path
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    # Keep as-is; DevUserAccessProvider will validate each rule defensively.
    return raw  # type: ignore[return-value]


def _normalize_int(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip()
        if not s:
            return None
        return int(float(s))
    except Exception:
        return None
