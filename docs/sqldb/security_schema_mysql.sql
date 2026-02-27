CREATE TABLE IF NOT EXISTS security_groups (
  group_key VARCHAR(191) NOT NULL PRIMARY KEY,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT ck_security_groups_group_key_nonempty CHECK (CHAR_LENGTH(TRIM(group_key)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS security_group_policies (
  group_key VARCHAR(191) NOT NULL PRIMARY KEY,
  owner_id VARCHAR(191) NOT NULL DEFAULT '',
  source_system_id VARCHAR(191) NOT NULL DEFAULT '',
  user_level INT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_security_group_policies_group
    FOREIGN KEY (group_key) REFERENCES security_groups(group_key)
    ON DELETE CASCADE,
  CONSTRAINT ck_security_group_policies_user_level CHECK (user_level IS NULL OR user_level >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS security_group_allowed_pipelines (
  group_key VARCHAR(191) NOT NULL,
  pipeline_id VARCHAR(191) NOT NULL,
  PRIMARY KEY (group_key, pipeline_id),
  CONSTRAINT fk_security_group_allowed_pipelines_group
    FOREIGN KEY (group_key) REFERENCES security_groups(group_key)
    ON DELETE CASCADE,
  CONSTRAINT ck_security_group_allowed_pipelines_nonempty CHECK (CHAR_LENGTH(TRIM(pipeline_id)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS security_group_allowed_commands (
  group_key VARCHAR(191) NOT NULL,
  command_id VARCHAR(191) NOT NULL,
  PRIMARY KEY (group_key, command_id),
  CONSTRAINT fk_security_group_allowed_commands_group
    FOREIGN KEY (group_key) REFERENCES security_groups(group_key)
    ON DELETE CASCADE,
  CONSTRAINT ck_security_group_allowed_commands_nonempty CHECK (CHAR_LENGTH(TRIM(command_id)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS security_group_acl_tags_any (
  group_key VARCHAR(191) NOT NULL,
  acl_tag VARCHAR(191) NOT NULL,
  PRIMARY KEY (group_key, acl_tag),
  CONSTRAINT fk_security_group_acl_tags_any_group
    FOREIGN KEY (group_key) REFERENCES security_groups(group_key)
    ON DELETE CASCADE,
  CONSTRAINT ck_security_group_acl_tags_any_nonempty CHECK (CHAR_LENGTH(TRIM(acl_tag)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS security_group_classification_labels_all (
  group_key VARCHAR(191) NOT NULL,
  classification_label VARCHAR(191) NOT NULL,
  PRIMARY KEY (group_key, classification_label),
  CONSTRAINT fk_security_group_classification_labels_all_group
    FOREIGN KEY (group_key) REFERENCES security_groups(group_key)
    ON DELETE CASCADE,
  CONSTRAINT ck_security_group_classification_labels_all_nonempty CHECK (CHAR_LENGTH(TRIM(classification_label)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS security_configuration_versions (
  config_version_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  config_source VARCHAR(20) NOT NULL,
  valid_from DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  valid_to DATETIME(6) NULL,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  change_note VARCHAR(1000) NOT NULL DEFAULT '',
  created_by VARCHAR(200) NOT NULL DEFAULT 'system',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT ck_security_configuration_versions_source CHECK (config_source IN ('json', 'sql')),
  CONSTRAINT ck_security_configuration_versions_window CHECK (valid_to IS NULL OR valid_to > valid_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO security_configuration_versions (config_source, valid_from, valid_to, is_enabled, change_note, created_by)
SELECT 'json', CURRENT_TIMESTAMP(6), NULL, 1, 'Initial mode: policy source is JSON files.', 'migration'
WHERE NOT EXISTS (SELECT 1 FROM security_configuration_versions);

CREATE INDEX ix_security_configuration_versions_window
  ON security_configuration_versions (is_enabled, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS security_claim_mappings (
  mapping_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  claim_name VARCHAR(200) NOT NULL,
  mapping_kind VARCHAR(50) NOT NULL,
  source_doc VARCHAR(200) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_security_claim_mappings (claim_name, mapping_kind, source_doc),
  CONSTRAINT ck_security_claim_mappings_claim_nonempty CHECK (CHAR_LENGTH(TRIM(claim_name)) > 0),
  CONSTRAINT ck_security_claim_mappings_source_nonempty CHECK (CHAR_LENGTH(TRIM(source_doc)) > 0),
  CONSTRAINT ck_security_claim_mappings_kind CHECK (mapping_kind IN ('list_map', 'value_map'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS security_claim_mapping_entries (
  mapping_id BIGINT NOT NULL,
  from_value VARCHAR(255) NOT NULL,
  to_group_key VARCHAR(191) NOT NULL,
  PRIMARY KEY (mapping_id, from_value),
  CONSTRAINT fk_security_claim_mapping_entries_mapping
    FOREIGN KEY (mapping_id) REFERENCES security_claim_mappings(mapping_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_security_claim_mapping_entries_group
    FOREIGN KEY (to_group_key) REFERENCES security_groups(group_key),
  CONSTRAINT ck_security_claim_mapping_entries_from_nonempty CHECK (CHAR_LENGTH(TRIM(from_value)) > 0),
  CONSTRAINT ck_security_claim_mapping_entries_to_nonempty CHECK (CHAR_LENGTH(TRIM(to_group_key)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX ix_security_claim_mapping_entries_to_group
  ON security_claim_mapping_entries (to_group_key);

CREATE INDEX ix_security_group_policies_user_level
  ON security_group_policies (user_level);
