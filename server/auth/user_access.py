from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .policies_provider import default_json_provider, GroupPolicy


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
    user_level: Optional[int] = None
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
        claims: Optional[Dict[str, object]] = None,
    ) -> UserAccessContext:
        raise NotImplementedError



class DevUserAccessProvider(UserAccessProvider):
    """
    Development provider for fake auth.

    Expected token format:
      Authorization: Bearer dev-user:<user_id>
    """

    def __init__(
        self,
        *,
        user_group_prefix: str = "user:",
        group_policies: Optional[Dict[str, GroupPolicy]] = None,
        claim_group_mappings: Optional[List[Dict[str, object]]] = None,
        user_extra_groups: Optional[Dict[str, List[str]]] = None,
        auto_reload_policies: bool = False,
    ) -> None:
        self._user_group_prefix = user_group_prefix
        self._group_policies = group_policies or {}
        self._claim_group_mappings = claim_group_mappings or []
        self._user_extra_groups = user_extra_groups or {}
        self._auto_reload_policies = bool(auto_reload_policies)

    def resolve(
        self,
        *,
        user_id: Optional[str],
        token: Optional[str],
        session_id: str,
        claims: Optional[Dict[str, object]] = None,
    ) -> UserAccessContext:
        if self._auto_reload_policies:
            try:
                provider = default_json_provider()
                group_policies, claim_group_mappings = provider.load()
                self._group_policies = group_policies or {}
                self._claim_group_mappings = claim_group_mappings or []
            except Exception:
                # Keep last good policies in memory.
                pass

        claims = claims or {}
        resolved_user_id = self._parse_dev_token(token) or user_id or self._derive_user_id_from_claims(claims)

        mapped_groups = self._map_claims_to_groups(claims)

        base_user_groups: List[str] = []
        if resolved_user_id:
            base_user_groups = [f"{self._user_group_prefix}{resolved_user_id}"]
            base_user_groups.extend(list(self._user_extra_groups.get(resolved_user_id) or []))

        # Keep roles/groups (from claims, extra groups) before the user-scoped group, for stable ordering.
        group_ids = _unique_preserve_order(mapped_groups + base_user_groups)
        is_anonymous = not bool(resolved_user_id)

        acl_tags_any = self._merge_acl_tags_any(group_ids)
        classification_labels_all = self._merge_classification_labels(group_ids)
        user_level = self._merge_user_level(group_ids)
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
            user_level=user_level,
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

    @staticmethod
    def _derive_user_id_from_claims(claims: Dict[str, object]) -> Optional[str]:
        """
        Best-effort identity extraction for non-dev tokens.
        Keep it stable and safe for downstream IDs.
        """
        raw = claims.get("preferred_username") or claims.get("sub") or claims.get("email")
        if raw is None:
            return None
        s = str(raw).strip()
        if not s:
            return None
        # Keep only safe chars used by the rest of the app; collapse others to '_'.
        out = []
        for ch in s:
            if ch.isalnum() or ch in ("_", "-"):
                out.append(ch)
            else:
                out.append("_")
        safe = "".join(out).strip("_")
        safe = safe[:64]
        return safe or None

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

    def _merge_user_level(self, group_ids: Iterable[str]) -> Optional[int]:
        levels: List[int] = []
        for gid in group_ids:
            policy = self._group_policies.get(gid)
            if policy and policy.user_level is not None:
                levels.append(int(policy.user_level))
        if not levels:
            return None
        return max(levels)

    def _map_claims_to_groups(self, claims: Dict[str, object]) -> List[str]:
        def _get_claim_value(obj: object, path: str) -> object | None:
            """
            Best-effort nested claim extraction.

            Supports dotted paths like "realm_access.roles" and wildcard paths
            like "resource_access.*.roles".
            """
            parts = [str(p or "").strip() for p in (path or "").split(".") if str(p or "").strip()]
            if not parts:
                return None

            def _walk(cur: object, idx: int) -> List[object]:
                if idx >= len(parts):
                    return [cur]
                part = parts[idx]
                if part == "*":
                    if not isinstance(cur, dict):
                        return []
                    out_vals: List[object] = []
                    for v in cur.values():
                        out_vals.extend(_walk(v, idx + 1))
                    return out_vals
                if not isinstance(cur, dict) or part not in cur:
                    return []
                return _walk(cur.get(part), idx + 1)

            values = _walk(obj, 0)
            if not values:
                return None
            if len(values) == 1:
                return values[0]

            # Flatten wildcard outputs to a single list.
            merged: List[object] = []
            for v in values:
                if isinstance(v, (list, tuple, set)):
                    merged.extend(list(v))
                else:
                    merged.append(v)
            return merged

        def _resolve_map_entry(map_obj: object, raw_key: object) -> Optional[str]:
            if not isinstance(map_obj, dict):
                return None
            key = str(raw_key or "").strip()
            if not key:
                return None

            # Exact hit first.
            if key in map_obj and map_obj.get(key):
                return str(map_obj.get(key))

            # Case-insensitive / slash-insensitive fallback.
            key_norm = key.lstrip("/").lower()
            for mk, mv in map_obj.items():
                map_key_norm = str(mk or "").strip().lstrip("/").lower()
                if map_key_norm == key_norm and mv:
                    return str(mv)
            return None

        def _extract_candidates(obj: object, depth: int = 0) -> List[object]:
            if depth > 8:
                return []
            if obj is None:
                return []
            if isinstance(obj, (str, int, float, bool)):
                return [obj]
            if isinstance(obj, (list, tuple, set)):
                out_vals: List[object] = []
                for item in obj:
                    out_vals.extend(_extract_candidates(item, depth + 1))
                return out_vals
            if isinstance(obj, dict):
                out_vals: List[object] = []
                # Common IdP object shapes: {"name":"analyst"}, {"value":"developer"}, etc.
                for key in ("name", "value", "role", "group", "groups", "id"):
                    if key in obj:
                        out_vals.extend(_extract_candidates(obj.get(key), depth + 1))
                for v in obj.values():
                    out_vals.extend(_extract_candidates(v, depth + 1))
                return out_vals
            return []

        def _normalize_alias(raw: object) -> str:
            s = str(raw or "").strip().lstrip("/").lower()
            if not s:
                return ""
            # Common role prefixes found in IdP payloads.
            for prefix in ("role:", "role_", "roles:", "roles_", "realm:", "group:", "groups:"):
                if s.startswith(prefix):
                    s = s[len(prefix):]
            return s.strip()

        out: List[str] = []
        for rule in self._claim_group_mappings:
            if not isinstance(rule, dict):
                continue
            claim = str(rule.get("claim") or "").strip()
            if not claim:
                continue
            value = _get_claim_value(claims, claim)
            if value is None:
                continue
            value_map = rule.get("value_map") or {}
            list_map = rule.get("list_map") or {}
            candidates = _extract_candidates(value)
            if not candidates:
                continue
            for candidate in candidates:
                group = _resolve_map_entry(list_map, candidate)
                if group:
                    out.append(group)
                    continue
                group = _resolve_map_entry(value_map, candidate)
                if group:
                    out.append(group)

        # Fallback: if explicit claim paths didn't match, scan all token claims for known aliases.
        if out:
            return _unique_preserve_order(out)

        alias_map: Dict[str, str] = {}
        for rule in self._claim_group_mappings:
            if not isinstance(rule, dict):
                continue
            for map_obj_name in ("list_map", "value_map"):
                map_obj = rule.get(map_obj_name) or {}
                if not isinstance(map_obj, dict):
                    continue
                for raw_key, raw_group in map_obj.items():
                    group = str(raw_group or "").strip()
                    alias = _normalize_alias(raw_key)
                    if alias and group:
                        alias_map[alias] = group
        if not alias_map:
            return []

        for candidate in _extract_candidates(claims):
            normalized = _normalize_alias(candidate)
            if not normalized:
                continue
            direct = alias_map.get(normalized)
            if direct:
                out.append(direct)
                continue
            # Tokenize strings like "ROLE_ANALYST,offline_access".
            parts = [
                p.strip()
                for p in str(candidate).replace(";", ",").replace("|", ",").replace(" ", ",").split(",")
                if p and p.strip()
            ]
            for part in parts:
                group = alias_map.get(_normalize_alias(part))
                if group:
                    out.append(group)
        return out


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
            claim_group_mappings: List[Dict[str, object]] = []
            auto_reload = False
        else:
            provider = default_json_provider()
            group_policies, claim_group_mappings = provider.load()
            auto_reload = True
        _default_provider = DevUserAccessProvider(
            group_policies=group_policies,
            claim_group_mappings=claim_group_mappings,
            auto_reload_policies=auto_reload,
        )
    return _default_provider
