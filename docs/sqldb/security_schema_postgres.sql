CREATE SCHEMA IF NOT EXISTS security;

CREATE TABLE IF NOT EXISTS security.groups (
  group_key TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT ck_security_groups_group_key_nonempty CHECK (btrim(group_key) <> '')
);

CREATE TABLE IF NOT EXISTS security.group_policies (
  group_key TEXT PRIMARY KEY REFERENCES security.groups(group_key) ON DELETE CASCADE,
  owner_id TEXT NOT NULL DEFAULT '',
  source_system_id TEXT NOT NULL DEFAULT '',
  user_level INT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT ck_security_group_policies_user_level CHECK (user_level IS NULL OR user_level >= 0)
);

CREATE TABLE IF NOT EXISTS security.group_allowed_pipelines (
  group_key TEXT NOT NULL REFERENCES security.groups(group_key) ON DELETE CASCADE,
  pipeline_id TEXT NOT NULL,
  PRIMARY KEY (group_key, pipeline_id),
  CONSTRAINT ck_security_group_allowed_pipelines_pipeline_nonempty CHECK (btrim(pipeline_id) <> '')
);

CREATE TABLE IF NOT EXISTS security.group_allowed_commands (
  group_key TEXT NOT NULL REFERENCES security.groups(group_key) ON DELETE CASCADE,
  command_id TEXT NOT NULL,
  PRIMARY KEY (group_key, command_id),
  CONSTRAINT ck_security_group_allowed_commands_command_nonempty CHECK (btrim(command_id) <> '')
);

CREATE TABLE IF NOT EXISTS security.group_acl_tags_any (
  group_key TEXT NOT NULL REFERENCES security.groups(group_key) ON DELETE CASCADE,
  acl_tag TEXT NOT NULL,
  PRIMARY KEY (group_key, acl_tag),
  CONSTRAINT ck_security_group_acl_tags_any_tag_nonempty CHECK (btrim(acl_tag) <> '')
);

CREATE TABLE IF NOT EXISTS security.group_classification_labels_all (
  group_key TEXT NOT NULL REFERENCES security.groups(group_key) ON DELETE CASCADE,
  classification_label TEXT NOT NULL,
  PRIMARY KEY (group_key, classification_label),
  CONSTRAINT ck_security_group_class_labels_nonempty CHECK (btrim(classification_label) <> '')
);

CREATE TABLE IF NOT EXISTS security.configuration_versions (
  config_version_id BIGSERIAL PRIMARY KEY,
  config_source TEXT NOT NULL,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  valid_to TIMESTAMPTZ NULL,
  is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  change_note TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT 'system',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT ck_security_configuration_versions_source CHECK (config_source IN ('json', 'sql')),
  CONSTRAINT ck_security_configuration_versions_window CHECK (valid_to IS NULL OR valid_to > valid_from)
);

INSERT INTO security.configuration_versions (config_source, valid_from, valid_to, is_enabled, change_note, created_by)
SELECT 'json', NOW(), NULL, TRUE, 'Initial mode: policy source is JSON files.', 'migration'
WHERE NOT EXISTS (SELECT 1 FROM security.configuration_versions);

CREATE INDEX IF NOT EXISTS ix_security_configuration_versions_window
  ON security.configuration_versions (is_enabled, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS security.claim_mappings (
  mapping_id BIGSERIAL PRIMARY KEY,
  claim_name TEXT NOT NULL,
  mapping_kind TEXT NOT NULL,
  source_doc TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_security_claim_mappings UNIQUE (claim_name, mapping_kind, source_doc),
  CONSTRAINT ck_security_claim_mappings_claim_nonempty CHECK (btrim(claim_name) <> ''),
  CONSTRAINT ck_security_claim_mappings_source_nonempty CHECK (btrim(source_doc) <> ''),
  CONSTRAINT ck_security_claim_mappings_kind CHECK (mapping_kind IN ('list_map', 'value_map'))
);

CREATE TABLE IF NOT EXISTS security.claim_mapping_entries (
  mapping_id BIGINT NOT NULL REFERENCES security.claim_mappings(mapping_id) ON DELETE CASCADE,
  from_value TEXT NOT NULL,
  to_group_key TEXT NOT NULL REFERENCES security.groups(group_key) ON DELETE RESTRICT,
  PRIMARY KEY (mapping_id, from_value),
  CONSTRAINT ck_security_claim_mapping_entries_from_nonempty CHECK (btrim(from_value) <> ''),
  CONSTRAINT ck_security_claim_mapping_entries_to_nonempty CHECK (btrim(to_group_key) <> '')
);

CREATE INDEX IF NOT EXISTS ix_security_claim_mapping_entries_to_group
  ON security.claim_mapping_entries (to_group_key);

CREATE INDEX IF NOT EXISTS ix_security_group_policies_user_level
  ON security.group_policies (user_level);

CREATE OR REPLACE FUNCTION security.tg_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_security_group_policies_updated_at ON security.group_policies;
CREATE TRIGGER trg_security_group_policies_updated_at
BEFORE UPDATE ON security.group_policies
FOR EACH ROW
EXECUTE FUNCTION security.tg_set_updated_at();
