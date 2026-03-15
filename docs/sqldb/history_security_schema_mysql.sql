-- MySQL DDL for LocalAI-RAG durable history + security.
-- MySQL uses separate databases instead of PostgreSQL/MSSQL-style schemas.
-- Adjust the database names below if your deployment uses different names.

CREATE DATABASE IF NOT EXISTS localai_rag_history
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS localai_rag_security
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------------
-- History database
-- ------------------------------------------------------------------

USE localai_rag_history;

CREATE TABLE IF NOT EXISTS chat_tenants (
  id VARCHAR(36) NOT NULL PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_sessions (
  id VARCHAR(36) NOT NULL PRIMARY KEY,
  tenant_id VARCHAR(36) NOT NULL,
  user_id VARCHAR(80) NOT NULL,
  title VARCHAR(200),
  consultant_id VARCHAR(80),
  message_count INT NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6),
  deleted_by VARCHAR(80),
  KEY ix_chat_sessions_tenant_user_updated (tenant_id, user_id, updated_at),
  KEY ix_chat_sessions_tenant_deleted (tenant_id, deleted_at),
  CONSTRAINT fk_chat_sessions_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_messages (
  id VARCHAR(36) NOT NULL PRIMARY KEY,
  session_id VARCHAR(36) NOT NULL,
  tenant_id VARCHAR(36) NOT NULL,
  ts DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  q TEXT,
  a TEXT,
  meta_json TEXT,
  deleted_at DATETIME(6),
  deleted_by VARCHAR(80),
  KEY ix_chat_messages_session_ts (session_id, ts),
  KEY ix_chat_messages_tenant_deleted (tenant_id, deleted_at),
  CONSTRAINT fk_chat_messages_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id),
  CONSTRAINT fk_chat_messages_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_tags (
  id VARCHAR(36) NOT NULL PRIMARY KEY,
  tenant_id VARCHAR(36) NOT NULL,
  name VARCHAR(80) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_chat_tags_tenant_name (tenant_id, name),
  KEY ix_chat_tags_tenant_name (tenant_id, name),
  CONSTRAINT fk_chat_tags_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_session_tags (
  session_id VARCHAR(36) NOT NULL,
  tag_id VARCHAR(36) NOT NULL,
  tenant_id VARCHAR(36) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (session_id, tag_id),
  UNIQUE KEY uq_chat_session_tags_session_tag (session_id, tag_id),
  KEY ix_chat_session_tags_tenant (tenant_id),
  CONSTRAINT fk_chat_session_tags_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id),
  CONSTRAINT fk_chat_session_tags_tag FOREIGN KEY (tag_id) REFERENCES chat_tags(id),
  CONSTRAINT fk_chat_session_tags_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ------------------------------------------------------------------
-- Security database
-- ------------------------------------------------------------------

USE localai_rag_security;

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
  KEY ix_security_group_policies_user_level (user_level),
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
  KEY ix_security_configuration_versions_window (is_enabled, valid_from, valid_to),
  CONSTRAINT ck_security_configuration_versions_source CHECK (config_source IN ('json', 'sql')),
  CONSTRAINT ck_security_configuration_versions_window CHECK (valid_to IS NULL OR valid_to > valid_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO security_configuration_versions (config_source, valid_from, valid_to, is_enabled, change_note, created_by)
SELECT 'json', CURRENT_TIMESTAMP(6), NULL, 1, 'Initial mode: policy source is JSON files.', 'migration'
WHERE NOT EXISTS (SELECT 1 FROM security_configuration_versions);

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
  KEY ix_security_claim_mapping_entries_to_group (to_group_key),
  CONSTRAINT fk_security_claim_mapping_entries_mapping
    FOREIGN KEY (mapping_id) REFERENCES security_claim_mappings(mapping_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_security_claim_mapping_entries_group
    FOREIGN KEY (to_group_key) REFERENCES security_groups(group_key),
  CONSTRAINT ck_security_claim_mapping_entries_from_nonempty CHECK (CHAR_LENGTH(TRIM(from_value)) > 0),
  CONSTRAINT ck_security_claim_mapping_entries_to_nonempty CHECK (CHAR_LENGTH(TRIM(to_group_key)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
