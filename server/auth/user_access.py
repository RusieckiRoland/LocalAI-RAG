from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class UserAccessContext:
    """
    Immutable access context resolved for a single request.
    """
    user_id: Optional[str]
    is_anonymous: bool
    group_ids: List[str]
    allowed_pipelines: List[str]
    allowed_commands: List[str]
    acl_tags_any: List[str] = field(default_factory=list)
    classification_labels_all: List[str] = field(default_factory=list)
    owner_id: Optional[str] = None
    source_system_id: Optional[str] = None
    # Backward-compatible alias retained during migration.
    acl_tags_all: List[str] = field(default_factory=list)


class UserAccessProvider:
    """
    Resolve access rules for the current request.
    Implementations must be side-effect free and fast.
    """

    def resolve(
        self,
        *,
        user_id: Optional[str],
        token: Optional[str],
        session_id: str,
    ) -> UserAccessContext:
        raise NotImplementedError


@dataclass(frozen=True)
class GroupPolicy:
    """
    Group-level policy: ACL tags, classification labels and allowed pipelines.
    """
    allowed_pipelines: List[str] = field(default_factory=list)
    allowed_commands: List[str] = field(default_factory=list)
    acl_tags_any: List[str] = field(default_factory=list)
    classification_labels_all: List[str] = field(default_factory=list)
    owner_id: Optional[str] = None
    source_system_id: Optional[str] = None
    # Backward-compatible alias retained during migration.
    acl_tags_all: List[str] = field(default_factory=list)


class DevUserAccessProvider(UserAccessProvider):
    """
    Development provider for fake auth.

    Expected token format:
      Authorization: Bearer dev-user:<user_id>

    If the token is missing or invalid, the request is treated as anonymous.
    """

    def __init__(
        self,
        *,
        anonymous_group_id: str = "anonymous",
        authenticated_group_id: str = "authenticated",
        user_group_prefix: str = "user:",
        group_policies: Optional[Dict[str, GroupPolicy]] = None,
    ) -> None:
        self._anonymous_group_id = anonymous_group_id
        self._authenticated_group_id = authenticated_group_id
        self._user_group_prefix = user_group_prefix
        self._group_policies = group_policies or {}

    def resolve(
        self,
        *,
        user_id: Optional[str],
        token: Optional[str],
        session_id: str,
    ) -> UserAccessContext:
        resolved_user_id = self._parse_dev_token(token) or user_id
        has_bearer = self._has_any_bearer_token(token)

        if resolved_user_id:
            group_ids = [self._authenticated_group_id, f"{self._user_group_prefix}{resolved_user_id}"]
            is_anonymous = False
        elif has_bearer:
            # Generic bearer still means "authenticated" in DEV transition mode.
            group_ids = [self._authenticated_group_id]
            is_anonymous = False
        else:
            group_ids = [self._anonymous_group_id]
            is_anonymous = True

        acl_tags_any = self._merge_acl_tags_any(group_ids)
        classification_labels_all = self._merge_classification_labels(group_ids)
        allowed_pipelines = self._merge_allowed_pipelines(group_ids)
        allowed_commands = self._merge_allowed_commands(group_ids)
        owner_id = self._resolve_owner_id(group_ids)
        source_system_id = self._resolve_source_system_id(group_ids)

        return UserAccessContext(
            user_id=resolved_user_id,
            is_anonymous=is_anonymous,
            group_ids=group_ids,
            allowed_pipelines=allowed_pipelines,
            allowed_commands=allowed_commands,
            acl_tags_any=acl_tags_any,
            classification_labels_all=classification_labels_all,
            owner_id=owner_id,
            source_system_id=source_system_id,
            acl_tags_all=list(acl_tags_any),
        )

    def _parse_dev_token(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        token = token.strip()
        if not token.lower().startswith("bearer "):
            return None
        raw = token[7:].strip()
        if not raw.startswith("dev-user:"):
            return None
        candidate = raw[len("dev-user:") :].strip()
        return candidate or None

    def _has_any_bearer_token(self, token: Optional[str]) -> bool:
        if not token:
            return False
        t = token.strip()
        if not t.lower().startswith("bearer "):
            return False
        return bool(t[7:].strip())

    def _merge_acl_tags_any(self, group_ids: Iterable[str]) -> List[str]:
        tags: List[str] = []
        for gid in group_ids:
            policy = self._group_policies.get(gid)
            if policy:
                tags.extend(policy.acl_tags_any or [])
                tags.extend(policy.acl_tags_all or [])
        return _unique_preserve_order(tags)

    def _merge_classification_labels(self, group_ids: Iterable[str]) -> List[str]:
        labels: List[str] = []
        for gid in group_ids:
            policy = self._group_policies.get(gid)
            if policy:
                labels.extend(policy.classification_labels_all or [])
        return _unique_preserve_order(labels)

    def _merge_allowed_pipelines(self, group_ids: Iterable[str]) -> List[str]:
        allowed: List[str] = []
        for gid in group_ids:
            policy = self._group_policies.get(gid)
            if policy:
                allowed.extend(policy.allowed_pipelines or [])
        return _unique_preserve_order(allowed)

    def _merge_allowed_commands(self, group_ids: Iterable[str]) -> List[str]:
        allowed: List[str] = []
        for gid in group_ids:
            policy = self._group_policies.get(gid)
            if policy:
                allowed.extend(policy.allowed_commands or [])
        return _unique_preserve_order(allowed)

    def _resolve_owner_id(self, group_ids: Iterable[str]) -> Optional[str]:
        for gid in group_ids:
            policy = self._group_policies.get(gid)
            if not policy:
                continue
            owner_id = str(policy.owner_id or "").strip()
            if owner_id:
                return owner_id
        return None

    def _resolve_source_system_id(self, group_ids: Iterable[str]) -> Optional[str]:
        for gid in group_ids:
            policy = self._group_policies.get(gid)
            if not policy:
                continue
            source_system_id = str(policy.source_system_id or "").strip()
            if source_system_id:
                return source_system_id
        return None


def _unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        s = str(item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


_default_provider: Optional[UserAccessProvider] = None


def get_default_user_access_provider() -> UserAccessProvider:
    """
    Central place to construct the access provider.
    Replace this with a real implementation later.
    """
    global _default_provider
    if _default_provider is None:
        # In tests, skip policy loading to avoid unexpected auth failures.
        if os.getenv("PYTEST_CURRENT_TEST"):
            group_policies = {}
        else:
            group_policies = _load_group_policies_from_json()
        _default_provider = DevUserAccessProvider(group_policies=group_policies)
    return _default_provider


def _load_group_policies_from_json() -> Dict[str, GroupPolicy]:
    """
    Load group policies from a dedicated JSON file.
    This is a temporary storage mechanism until policies live in a database.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    default_path = os.path.join(project_root, "config", "auth_policies.json")
    path = os.getenv("AUTH_POLICIES_PATH") or default_path

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

    groups = raw.get("groups")
    if not isinstance(groups, dict):
        return {}

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
        owner_id = str(payload.get("owner_id") or "").strip() or None
        source_system_id = str(payload.get("source_system_id") or "").strip() or None
        if not isinstance(acl_any, list) or not isinstance(labels_all, list) or not isinstance(allowed, list) or not isinstance(allowed_commands, list):
            continue
        policies[str(group_id)] = GroupPolicy(
            acl_tags_any=[str(x) for x in acl_any if str(x).strip()],
            classification_labels_all=[str(x) for x in labels_all if str(x).strip()],
            owner_id=owner_id,
            source_system_id=source_system_id,
            acl_tags_all=[str(x) for x in acl_any if str(x).strip()],
            allowed_pipelines=[str(x) for x in allowed if str(x).strip()],
            allowed_commands=[str(x) for x in allowed_commands if str(x).strip()],
        )

    return policies
