from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from .policies_provider import AuthPoliciesProvider, GroupPolicy


@dataclass(frozen=True)
class SqlSecurityInspection:
    schema_present: bool
    schema_complete: bool
    groups_count: int
    claim_mappings_count: int
    claim_mapping_entries_count: int

    @property
    def data_empty(self) -> bool:
        return self.groups_count <= 0 and self.claim_mappings_count <= 0 and self.claim_mapping_entries_count <= 0

    @property
    def has_required_data(self) -> bool:
        return self.groups_count > 0 and self.claim_mapping_entries_count > 0


class SqlAuthPoliciesProvider:
    def __init__(
        self,
        *,
        database_type: str,
        connection_url: str,
        connect_timeout_seconds: int = 5,
    ) -> None:
        self._database_type = str(database_type or "").strip().lower()
        self._connection_url = str(connection_url or "").strip()
        self._connect_timeout_seconds = max(1, int(connect_timeout_seconds or 5))
        self._engine_instance = None
        if self._database_type not in {"postgres", "mysql", "mssql"}:
            raise ValueError("SqlAuthPoliciesProvider requires database_type in {'postgres','mysql','mssql'}")
        if not self._connection_url:
            raise ValueError("SqlAuthPoliciesProvider requires a non-empty connection_url")

    def inspect(self) -> SqlSecurityInspection:
        from sqlalchemy import text  # type: ignore

        with self._connect() as conn:
            table_exists = {
                "groups": self._table_exists(conn, table_name="groups", mysql_name="security_groups"),
                "group_policies": self._table_exists(conn, table_name="group_policies", mysql_name="security_group_policies"),
                "claim_mappings": self._table_exists(conn, table_name="claim_mappings", mysql_name="security_claim_mappings"),
                "claim_mapping_entries": self._table_exists(
                    conn,
                    table_name="claim_mapping_entries",
                    mysql_name="security_claim_mapping_entries",
                ),
                "configuration_versions": self._table_exists(
                    conn,
                    table_name="configuration_versions",
                    mysql_name="security_configuration_versions",
                ),
            }
            schema_present = any(bool(v) for v in table_exists.values())
            schema_complete = all(bool(v) for v in table_exists.values())
            if not schema_complete:
                return SqlSecurityInspection(
                    schema_present=schema_present,
                    schema_complete=False,
                    groups_count=0,
                    claim_mappings_count=0,
                    claim_mapping_entries_count=0,
                )

            groups_count = int(
                conn.execute(text(f"SELECT COUNT(*) FROM {self._tn('groups', mysql_name='security_groups')}")).scalar() or 0
            )
            claim_mappings_count = int(
                conn.execute(
                    text(f"SELECT COUNT(*) FROM {self._tn('claim_mappings', mysql_name='security_claim_mappings')}")
                ).scalar()
                or 0
            )
            claim_mapping_entries_count = int(
                conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {self._tn('claim_mapping_entries', mysql_name='security_claim_mapping_entries')}"
                    )
                ).scalar()
                or 0
            )
            return SqlSecurityInspection(
                schema_present=True,
                schema_complete=True,
                groups_count=groups_count,
                claim_mappings_count=claim_mappings_count,
                claim_mapping_entries_count=claim_mapping_entries_count,
            )

    def load(self) -> Tuple[Dict[str, GroupPolicy], List[Dict[str, object]]]:
        from sqlalchemy import text  # type: ignore

        with self._connect() as conn:
            group_rows = conn.execute(
                text(
                    f"""
                    SELECT
                      g.group_key AS group_key,
                      gp.owner_id AS owner_id,
                      gp.source_system_id AS source_system_id,
                      gp.user_level AS user_level
                    FROM {self._tn('groups', mysql_name='security_groups')} g
                    LEFT JOIN {self._tn('group_policies', mysql_name='security_group_policies')} gp
                      ON gp.group_key = g.group_key
                    ORDER BY g.group_key
                    """
                )
            ).mappings().all()

            policies: Dict[str, GroupPolicy] = {}
            for row in group_rows:
                gid = str(row.get("group_key") or "").strip()
                if not gid:
                    continue
                policies[gid] = GroupPolicy(
                    allowed_pipelines=[],
                    allowed_commands=[],
                    acl_tags_any=[],
                    classification_labels_all=[],
                    user_level=_normalize_int(row.get("user_level")),
                    owner_id=str(row.get("owner_id") or "").strip() or None,
                    source_system_id=str(row.get("source_system_id") or "").strip() or None,
                    acl_tags_all=[],
                )

            self._merge_group_list(
                conn=conn,
                table_name=self._tn("group_allowed_pipelines", mysql_name="security_group_allowed_pipelines"),
                value_column="pipeline_id",
                target=policies,
                attr="allowed_pipelines",
            )
            self._merge_group_list(
                conn=conn,
                table_name=self._tn("group_allowed_commands", mysql_name="security_group_allowed_commands"),
                value_column="command_id",
                target=policies,
                attr="allowed_commands",
            )
            self._merge_group_list(
                conn=conn,
                table_name=self._tn("group_acl_tags_any", mysql_name="security_group_acl_tags_any"),
                value_column="acl_tag",
                target=policies,
                attr="acl_tags_any",
            )
            self._merge_group_list(
                conn=conn,
                table_name=self._tn(
                    "group_classification_labels_all",
                    mysql_name="security_group_classification_labels_all",
                ),
                value_column="classification_label",
                target=policies,
                attr="classification_labels_all",
            )

            claim_rows = conn.execute(
                text(
                    f"""
                    SELECT
                      m.mapping_id AS mapping_id,
                      m.claim_name AS claim_name,
                      m.mapping_kind AS mapping_kind,
                      m.source_doc AS source_doc,
                      e.from_value AS from_value,
                      e.to_group_key AS to_group_key
                    FROM {self._tn('claim_mappings', mysql_name='security_claim_mappings')} m
                    LEFT JOIN {self._tn('claim_mapping_entries', mysql_name='security_claim_mapping_entries')} e
                      ON e.mapping_id = m.mapping_id
                    ORDER BY m.mapping_id, e.from_value
                    """
                )
            ).mappings().all()

            by_mapping_id: Dict[int, Dict[str, object]] = {}
            for row in claim_rows:
                mapping_id = int(row.get("mapping_id") or 0)
                if mapping_id <= 0:
                    continue
                item = by_mapping_id.get(mapping_id)
                if item is None:
                    kind = str(row.get("mapping_kind") or "").strip()
                    item = {
                        "claim": str(row.get("claim_name") or "").strip(),
                        "source_doc": str(row.get("source_doc") or "").strip(),
                        "value_map": {},
                        "list_map": {},
                    }
                    by_mapping_id[mapping_id] = item
                    if kind not in ("value_map", "list_map"):
                        continue
                from_value = str(row.get("from_value") or "").strip()
                to_group_key = str(row.get("to_group_key") or "").strip()
                if not from_value or not to_group_key:
                    continue
                kind = str(row.get("mapping_kind") or "").strip()
                if kind == "value_map":
                    cast_map = item.setdefault("value_map", {})
                    if isinstance(cast_map, dict):
                        cast_map[from_value] = to_group_key
                elif kind == "list_map":
                    cast_map = item.setdefault("list_map", {})
                    if isinstance(cast_map, dict):
                        cast_map[from_value] = to_group_key

            mappings = [m for m in by_mapping_id.values() if str(m.get("claim") or "").strip()]
            return policies, mappings

    def bootstrap_from_provider(self, *, source_provider: AuthPoliciesProvider) -> None:
        from sqlalchemy import text  # type: ignore

        policies, mappings = source_provider.load()
        if not policies:
            raise RuntimeError("Cannot bootstrap SQL security from files: no group policies found.")

        now = datetime.now(timezone.utc)
        with self._begin() as conn:
            for group_key, policy in policies.items():
                gid = str(group_key or "").strip()
                if not gid:
                    continue
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self._tn('groups', mysql_name='security_groups')} (group_key, created_at)
                        VALUES (:group_key, :created_at)
                        """
                    ),
                    {"group_key": gid, "created_at": now},
                )
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self._tn('group_policies', mysql_name='security_group_policies')}
                          (group_key, owner_id, source_system_id, user_level, updated_at)
                        VALUES (:group_key, :owner_id, :source_system_id, :user_level, :updated_at)
                        """
                    ),
                    {
                        "group_key": gid,
                        "owner_id": str(policy.owner_id or ""),
                        "source_system_id": str(policy.source_system_id or ""),
                        "user_level": _normalize_int(policy.user_level),
                        "updated_at": now,
                    },
                )
                self._insert_group_values(
                    conn=conn,
                    table_name=self._tn("group_allowed_pipelines", mysql_name="security_group_allowed_pipelines"),
                    value_column="pipeline_id",
                    group_key=gid,
                    values=policy.allowed_pipelines,
                )
                self._insert_group_values(
                    conn=conn,
                    table_name=self._tn("group_allowed_commands", mysql_name="security_group_allowed_commands"),
                    value_column="command_id",
                    group_key=gid,
                    values=policy.allowed_commands,
                )
                self._insert_group_values(
                    conn=conn,
                    table_name=self._tn("group_acl_tags_any", mysql_name="security_group_acl_tags_any"),
                    value_column="acl_tag",
                    group_key=gid,
                    values=policy.acl_tags_any or policy.acl_tags_all,
                )
                self._insert_group_values(
                    conn=conn,
                    table_name=self._tn(
                        "group_classification_labels_all",
                        mysql_name="security_group_classification_labels_all",
                    ),
                    value_column="classification_label",
                    group_key=gid,
                    values=policy.classification_labels_all,
                )

            mapping_rows = self._flatten_claim_mappings(mappings)
            for item in mapping_rows:
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self._tn('claim_mappings', mysql_name='security_claim_mappings')}
                          (claim_name, mapping_kind, source_doc, created_at)
                        VALUES (:claim_name, :mapping_kind, :source_doc, :created_at)
                        """
                    ),
                    {
                        "claim_name": item["claim_name"],
                        "mapping_kind": item["mapping_kind"],
                        "source_doc": item["source_doc"],
                        "created_at": now,
                    },
                )
                mapping_id = conn.execute(
                    text(
                        f"""
                        SELECT mapping_id
                        FROM {self._tn('claim_mappings', mysql_name='security_claim_mappings')}
                        WHERE claim_name = :claim_name
                          AND mapping_kind = :mapping_kind
                          AND source_doc = :source_doc
                        """
                    ),
                    {
                        "claim_name": item["claim_name"],
                        "mapping_kind": item["mapping_kind"],
                        "source_doc": item["source_doc"],
                    },
                ).scalar()
                if mapping_id is None:
                    raise RuntimeError("Failed to resolve mapping_id while bootstrapping SQL security.")
                for from_value, to_group_key in item["entries"]:
                    conn.execute(
                        text(
                            f"""
                            INSERT INTO {self._tn('claim_mapping_entries', mysql_name='security_claim_mapping_entries')}
                              (mapping_id, from_value, to_group_key)
                            VALUES (:mapping_id, :from_value, :to_group_key)
                            """
                        ),
                        {
                            "mapping_id": int(mapping_id),
                            "from_value": from_value,
                            "to_group_key": to_group_key,
                        },
                    )

            cfg_table = self._tn("configuration_versions", mysql_name="security_configuration_versions")
            conn.execute(
                text(
                    f"""
                    UPDATE {cfg_table}
                    SET is_enabled = :disabled,
                        valid_to = COALESCE(valid_to, :now)
                    WHERE is_enabled = :enabled
                    """
                ),
                {"disabled": False if self._database_type in ("postgres", "mssql") else 0, "enabled": True if self._database_type in ("postgres", "mssql") else 1, "now": now},
            )
            conn.execute(
                text(
                    f"""
                    INSERT INTO {cfg_table}
                      (config_source, valid_from, valid_to, is_enabled, change_note, created_by, created_at)
                    VALUES (:config_source, :valid_from, :valid_to, :is_enabled, :change_note, :created_by, :created_at)
                    """
                ),
                {
                    "config_source": "sql",
                    "valid_from": now,
                    "valid_to": None,
                    "is_enabled": True if self._database_type in ("postgres", "mssql") else 1,
                    "change_note": "Bootstrapped SQL security from security_conf.",
                    "created_by": "startup-bootstrap",
                    "created_at": now,
                },
            )

    def _flatten_claim_mappings(self, mappings: List[Dict[str, object]]) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        for idx, item in enumerate(mappings or []):
            if not isinstance(item, dict):
                continue
            claim_name = str(item.get("claim") or "").strip()
            if not claim_name:
                continue
            source_doc_base = str(item.get("source_doc") or "security_conf").strip() or "security_conf"
            value_map = item.get("value_map") or {}
            list_map = item.get("list_map") or {}
            if isinstance(value_map, dict) and value_map:
                out.append(
                    {
                        "claim_name": claim_name,
                        "mapping_kind": "value_map",
                        "source_doc": f"{source_doc_base}:value_map:{idx}",
                        "entries": [
                            (str(k).strip(), str(v).strip())
                            for k, v in value_map.items()
                            if str(k).strip() and str(v).strip()
                        ],
                    }
                )
            if isinstance(list_map, dict) and list_map:
                out.append(
                    {
                        "claim_name": claim_name,
                        "mapping_kind": "list_map",
                        "source_doc": f"{source_doc_base}:list_map:{idx}",
                        "entries": [
                            (str(k).strip(), str(v).strip())
                            for k, v in list_map.items()
                            if str(k).strip() and str(v).strip()
                        ],
                    }
                )
        return [item for item in out if item["entries"]]

    def _insert_group_values(
        self,
        *,
        conn,
        table_name: str,
        value_column: str,
        group_key: str,
        values: Iterable[str],
    ) -> None:
        from sqlalchemy import text  # type: ignore

        for value in values or []:
            v = str(value or "").strip()
            if not v:
                continue
            conn.execute(
                text(
                    f"""
                    INSERT INTO {table_name} (group_key, {value_column})
                    VALUES (:group_key, :value)
                    """
                ),
                {"group_key": group_key, "value": v},
            )

    def _merge_group_list(
        self,
        *,
        conn,
        table_name: str,
        value_column: str,
        target: Dict[str, GroupPolicy],
        attr: str,
    ) -> None:
        from sqlalchemy import text  # type: ignore

        rows = conn.execute(
            text(f"SELECT group_key, {value_column} AS value FROM {table_name} ORDER BY group_key, {value_column}")
        ).mappings().all()
        for row in rows:
            gid = str(row.get("group_key") or "").strip()
            val = str(row.get("value") or "").strip()
            if not gid or not val:
                continue
            policy = target.get(gid)
            if policy is None:
                continue
            existing = list(getattr(policy, attr))
            existing.append(val)
            target[gid] = GroupPolicy(
                allowed_pipelines=list(existing) if attr == "allowed_pipelines" else list(policy.allowed_pipelines),
                allowed_commands=list(existing) if attr == "allowed_commands" else list(policy.allowed_commands),
                acl_tags_any=list(existing) if attr == "acl_tags_any" else list(policy.acl_tags_any),
                classification_labels_all=(
                    list(existing) if attr == "classification_labels_all" else list(policy.classification_labels_all)
                ),
                user_level=policy.user_level,
                owner_id=policy.owner_id,
                source_system_id=policy.source_system_id,
                acl_tags_all=(list(existing) if attr == "acl_tags_any" else list(policy.acl_tags_all)),
            )

    def _table_exists(self, conn, *, table_name: str, mysql_name: str) -> bool:
        from sqlalchemy import text  # type: ignore

        if self._database_type == "postgres":
            return bool(conn.execute(text(f"SELECT to_regclass('security.{table_name}') IS NOT NULL")).scalar())
        if self._database_type == "mysql":
            return bool(
                int(
                    conn.execute(
                        text(
                            "SELECT COUNT(*) FROM information_schema.tables "
                            "WHERE table_schema = DATABASE() AND table_name = :table_name"
                        ),
                        {"table_name": mysql_name},
                    ).scalar()
                    or 0
                )
                > 0
            )
        return bool(
            int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_SCHEMA = 'security' AND TABLE_NAME = :table_name"
                    ),
                    {"table_name": table_name},
                ).scalar()
                or 0
            )
            > 0
        )

    def _tn(self, table_name: str, *, mysql_name: str) -> str:
        if self._database_type == "mysql":
            return mysql_name
        return f"security.{table_name}"

    def _connect(self):
        return self._engine().connect()

    def _begin(self):
        return self._engine().begin()

    def _engine(self):
        from sqlalchemy import create_engine  # type: ignore

        if self._engine_instance is not None:
            return self._engine_instance
        connect_args = {}
        if self._database_type in {"postgres", "mysql"}:
            connect_args["connect_timeout"] = int(self._connect_timeout_seconds)
        elif self._database_type == "mssql":
            connect_args["timeout"] = int(self._connect_timeout_seconds)
        self._engine_instance = create_engine(self._connection_url, pool_pre_ping=True, connect_args=connect_args)
        return self._engine_instance


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
