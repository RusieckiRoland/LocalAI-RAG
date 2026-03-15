-- Microsoft SQL Server DDL for LocalAI-RAG durable history + security.
-- Creates two schemas in a single database:
--   - history
--   - security

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'history')
  EXEC(N'CREATE SCHEMA history AUTHORIZATION dbo;');

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'security')
  EXEC(N'CREATE SCHEMA security AUTHORIZATION dbo;');

-- ------------------------------------------------------------------
-- History schema
-- ------------------------------------------------------------------

IF OBJECT_ID(N'history.chat_tenants', N'U') IS NULL
BEGIN
  CREATE TABLE history.chat_tenants (
    id NVARCHAR(36) NOT NULL PRIMARY KEY,
    name NVARCHAR(200) NOT NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT df_history_chat_tenants_created_at DEFAULT SYSUTCDATETIME()
  );
END;

IF OBJECT_ID(N'history.chat_sessions', N'U') IS NULL
BEGIN
  CREATE TABLE history.chat_sessions (
    id NVARCHAR(36) NOT NULL PRIMARY KEY,
    tenant_id NVARCHAR(36) NOT NULL,
    user_id NVARCHAR(80) NOT NULL,
    title NVARCHAR(200) NULL,
    consultant_id NVARCHAR(80) NULL,
    message_count INT NOT NULL CONSTRAINT df_history_chat_sessions_message_count DEFAULT 0,
    created_at DATETIME2 NOT NULL CONSTRAINT df_history_chat_sessions_created_at DEFAULT SYSUTCDATETIME(),
    updated_at DATETIME2 NOT NULL CONSTRAINT df_history_chat_sessions_updated_at DEFAULT SYSUTCDATETIME(),
    deleted_at DATETIME2 NULL,
    deleted_by NVARCHAR(80) NULL,
    CONSTRAINT fk_history_chat_sessions_tenant FOREIGN KEY (tenant_id) REFERENCES history.chat_tenants(id)
  );
END;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'history.chat_sessions')
    AND name = N'ix_chat_sessions_tenant_user_updated'
)
BEGIN
  CREATE INDEX ix_chat_sessions_tenant_user_updated
    ON history.chat_sessions (tenant_id, user_id, updated_at);
END;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'history.chat_sessions')
    AND name = N'ix_chat_sessions_tenant_deleted'
)
BEGIN
  CREATE INDEX ix_chat_sessions_tenant_deleted
    ON history.chat_sessions (tenant_id, deleted_at);
END;

IF OBJECT_ID(N'history.chat_messages', N'U') IS NULL
BEGIN
  CREATE TABLE history.chat_messages (
    id NVARCHAR(36) NOT NULL PRIMARY KEY,
    session_id NVARCHAR(36) NOT NULL,
    tenant_id NVARCHAR(36) NOT NULL,
    ts DATETIME2 NOT NULL CONSTRAINT df_history_chat_messages_ts DEFAULT SYSUTCDATETIME(),
    q NVARCHAR(MAX) NULL,
    a NVARCHAR(MAX) NULL,
    meta_json NVARCHAR(MAX) NULL,
    deleted_at DATETIME2 NULL,
    deleted_by NVARCHAR(80) NULL,
    CONSTRAINT fk_history_chat_messages_session FOREIGN KEY (session_id) REFERENCES history.chat_sessions(id),
    CONSTRAINT fk_history_chat_messages_tenant FOREIGN KEY (tenant_id) REFERENCES history.chat_tenants(id)
  );
END;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'history.chat_messages')
    AND name = N'ix_chat_messages_session_ts'
)
BEGIN
  CREATE INDEX ix_chat_messages_session_ts
    ON history.chat_messages (session_id, ts);
END;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'history.chat_messages')
    AND name = N'ix_chat_messages_tenant_deleted'
)
BEGIN
  CREATE INDEX ix_chat_messages_tenant_deleted
    ON history.chat_messages (tenant_id, deleted_at);
END;

IF OBJECT_ID(N'history.chat_tags', N'U') IS NULL
BEGIN
  CREATE TABLE history.chat_tags (
    id NVARCHAR(36) NOT NULL PRIMARY KEY,
    tenant_id NVARCHAR(36) NOT NULL,
    name NVARCHAR(80) NOT NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT df_history_chat_tags_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_chat_tags_tenant_name UNIQUE (tenant_id, name),
    CONSTRAINT fk_history_chat_tags_tenant FOREIGN KEY (tenant_id) REFERENCES history.chat_tenants(id)
  );
END;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'history.chat_tags')
    AND name = N'ix_chat_tags_tenant_name'
)
BEGIN
  CREATE INDEX ix_chat_tags_tenant_name
    ON history.chat_tags (tenant_id, name);
END;

IF OBJECT_ID(N'history.chat_session_tags', N'U') IS NULL
BEGIN
  CREATE TABLE history.chat_session_tags (
    session_id NVARCHAR(36) NOT NULL,
    tag_id NVARCHAR(36) NOT NULL,
    tenant_id NVARCHAR(36) NOT NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT df_history_chat_session_tags_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_chat_session_tags_session_tag UNIQUE (session_id, tag_id),
    CONSTRAINT fk_history_chat_session_tags_session FOREIGN KEY (session_id) REFERENCES history.chat_sessions(id),
    CONSTRAINT fk_history_chat_session_tags_tag FOREIGN KEY (tag_id) REFERENCES history.chat_tags(id),
    CONSTRAINT fk_history_chat_session_tags_tenant FOREIGN KEY (tenant_id) REFERENCES history.chat_tenants(id),
    PRIMARY KEY (session_id, tag_id)
  );
END;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'history.chat_session_tags')
    AND name = N'ix_chat_session_tags_tenant'
)
BEGIN
  CREATE INDEX ix_chat_session_tags_tenant
    ON history.chat_session_tags (tenant_id);
END;

-- ------------------------------------------------------------------
-- Security schema
-- ------------------------------------------------------------------

IF OBJECT_ID(N'security.groups', N'U') IS NULL
BEGIN
  CREATE TABLE security.groups (
    group_key NVARCHAR(400) NOT NULL PRIMARY KEY,
    created_at DATETIME2 NOT NULL CONSTRAINT df_security_groups_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT ck_security_groups_group_key_nonempty CHECK (LEN(LTRIM(RTRIM(group_key))) > 0)
  );
END;

IF OBJECT_ID(N'security.group_policies', N'U') IS NULL
BEGIN
  CREATE TABLE security.group_policies (
    group_key NVARCHAR(400) NOT NULL PRIMARY KEY,
    owner_id NVARCHAR(400) NOT NULL CONSTRAINT df_security_group_policies_owner_id DEFAULT N'',
    source_system_id NVARCHAR(400) NOT NULL CONSTRAINT df_security_group_policies_source_system_id DEFAULT N'',
    user_level INT NULL,
    updated_at DATETIME2 NOT NULL CONSTRAINT df_security_group_policies_updated_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT fk_security_group_policies_group
      FOREIGN KEY (group_key) REFERENCES security.groups(group_key) ON DELETE CASCADE,
    CONSTRAINT ck_security_group_policies_user_level CHECK (user_level IS NULL OR user_level >= 0)
  );
END;

IF OBJECT_ID(N'security.group_allowed_pipelines', N'U') IS NULL
BEGIN
  CREATE TABLE security.group_allowed_pipelines (
    group_key NVARCHAR(400) NOT NULL,
    pipeline_id NVARCHAR(200) NOT NULL,
    CONSTRAINT pk_security_group_allowed_pipelines PRIMARY KEY (group_key, pipeline_id),
    CONSTRAINT fk_security_group_allowed_pipelines_group
      FOREIGN KEY (group_key) REFERENCES security.groups(group_key) ON DELETE CASCADE,
    CONSTRAINT ck_security_group_allowed_pipelines_nonempty CHECK (LEN(LTRIM(RTRIM(pipeline_id))) > 0)
  );
END;

IF OBJECT_ID(N'security.group_allowed_commands', N'U') IS NULL
BEGIN
  CREATE TABLE security.group_allowed_commands (
    group_key NVARCHAR(400) NOT NULL,
    command_id NVARCHAR(200) NOT NULL,
    CONSTRAINT pk_security_group_allowed_commands PRIMARY KEY (group_key, command_id),
    CONSTRAINT fk_security_group_allowed_commands_group
      FOREIGN KEY (group_key) REFERENCES security.groups(group_key) ON DELETE CASCADE,
    CONSTRAINT ck_security_group_allowed_commands_nonempty CHECK (LEN(LTRIM(RTRIM(command_id))) > 0)
  );
END;

IF OBJECT_ID(N'security.group_acl_tags_any', N'U') IS NULL
BEGIN
  CREATE TABLE security.group_acl_tags_any (
    group_key NVARCHAR(400) NOT NULL,
    acl_tag NVARCHAR(200) NOT NULL,
    CONSTRAINT pk_security_group_acl_tags_any PRIMARY KEY (group_key, acl_tag),
    CONSTRAINT fk_security_group_acl_tags_any_group
      FOREIGN KEY (group_key) REFERENCES security.groups(group_key) ON DELETE CASCADE,
    CONSTRAINT ck_security_group_acl_tags_any_nonempty CHECK (LEN(LTRIM(RTRIM(acl_tag))) > 0)
  );
END;

IF OBJECT_ID(N'security.group_classification_labels_all', N'U') IS NULL
BEGIN
  CREATE TABLE security.group_classification_labels_all (
    group_key NVARCHAR(400) NOT NULL,
    classification_label NVARCHAR(200) NOT NULL,
    CONSTRAINT pk_security_group_classification_labels_all PRIMARY KEY (group_key, classification_label),
    CONSTRAINT fk_security_group_classification_labels_all_group
      FOREIGN KEY (group_key) REFERENCES security.groups(group_key) ON DELETE CASCADE,
    CONSTRAINT ck_security_group_classification_labels_all_nonempty CHECK (LEN(LTRIM(RTRIM(classification_label))) > 0)
  );
END;

IF OBJECT_ID(N'security.configuration_versions', N'U') IS NULL
BEGIN
  CREATE TABLE security.configuration_versions (
    config_version_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    config_source NVARCHAR(20) NOT NULL,
    valid_from DATETIME2 NOT NULL CONSTRAINT df_security_configuration_versions_valid_from DEFAULT SYSUTCDATETIME(),
    valid_to DATETIME2 NULL,
    is_enabled BIT NOT NULL CONSTRAINT df_security_configuration_versions_is_enabled DEFAULT 1,
    change_note NVARCHAR(1000) NOT NULL CONSTRAINT df_security_configuration_versions_change_note DEFAULT N'',
    created_by NVARCHAR(200) NOT NULL CONSTRAINT df_security_configuration_versions_created_by DEFAULT N'system',
    created_at DATETIME2 NOT NULL CONSTRAINT df_security_configuration_versions_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT ck_security_configuration_versions_source CHECK (config_source IN (N'json', N'sql')),
    CONSTRAINT ck_security_configuration_versions_window CHECK (valid_to IS NULL OR valid_to > valid_from)
  );
END;

IF NOT EXISTS (SELECT 1 FROM security.configuration_versions)
BEGIN
  INSERT INTO security.configuration_versions (config_source, valid_from, valid_to, is_enabled, change_note, created_by)
  VALUES (N'json', SYSUTCDATETIME(), NULL, 1, N'Initial mode: policy source is JSON files.', N'migration');
END;

IF OBJECT_ID(N'security.claim_mappings', N'U') IS NULL
BEGIN
  CREATE TABLE security.claim_mappings (
    mapping_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    claim_name NVARCHAR(200) NOT NULL,
    mapping_kind NVARCHAR(50) NOT NULL,
    source_doc NVARCHAR(200) NOT NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT df_security_claim_mappings_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_security_claim_mappings UNIQUE (claim_name, mapping_kind, source_doc),
    CONSTRAINT ck_security_claim_mappings_claim_nonempty CHECK (LEN(LTRIM(RTRIM(claim_name))) > 0),
    CONSTRAINT ck_security_claim_mappings_source_nonempty CHECK (LEN(LTRIM(RTRIM(source_doc))) > 0),
    CONSTRAINT ck_security_claim_mappings_kind CHECK (mapping_kind IN (N'list_map', N'value_map'))
  );
END;

IF OBJECT_ID(N'security.claim_mapping_entries', N'U') IS NULL
BEGIN
  CREATE TABLE security.claim_mapping_entries (
    mapping_id BIGINT NOT NULL,
    from_value NVARCHAR(400) NOT NULL,
    to_group_key NVARCHAR(400) NOT NULL,
    CONSTRAINT pk_security_claim_mapping_entries PRIMARY KEY (mapping_id, from_value),
    CONSTRAINT fk_security_claim_mapping_entries_mapping
      FOREIGN KEY (mapping_id) REFERENCES security.claim_mappings(mapping_id) ON DELETE CASCADE,
    CONSTRAINT fk_security_claim_mapping_entries_group
      FOREIGN KEY (to_group_key) REFERENCES security.groups(group_key),
    CONSTRAINT ck_security_claim_mapping_entries_from_nonempty CHECK (LEN(LTRIM(RTRIM(from_value))) > 0),
    CONSTRAINT ck_security_claim_mapping_entries_to_nonempty CHECK (LEN(LTRIM(RTRIM(to_group_key))) > 0)
  );
END;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'security.claim_mapping_entries')
    AND name = N'ix_security_claim_mapping_entries_to_group'
)
BEGIN
  CREATE INDEX ix_security_claim_mapping_entries_to_group
    ON security.claim_mapping_entries (to_group_key);
END;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'security.group_policies')
    AND name = N'ix_security_group_policies_user_level'
)
BEGIN
  CREATE INDEX ix_security_group_policies_user_level
    ON security.group_policies (user_level);
END;

IF NOT EXISTS (
  SELECT 1
  FROM sys.indexes
  WHERE object_id = OBJECT_ID(N'security.configuration_versions')
    AND name = N'ix_security_configuration_versions_window'
)
BEGIN
  CREATE INDEX ix_security_configuration_versions_window
    ON security.configuration_versions (is_enabled, valid_from, valid_to);
END;

IF OBJECT_ID(N'security.trg_security_group_policies_updated_at', N'TR') IS NOT NULL
  DROP TRIGGER security.trg_security_group_policies_updated_at;
GO
CREATE TRIGGER security.trg_security_group_policies_updated_at
ON security.group_policies
AFTER UPDATE
AS
BEGIN
  SET NOCOUNT ON;
  UPDATE gp
  SET updated_at = SYSUTCDATETIME()
  FROM security.group_policies gp
  INNER JOIN inserted i ON i.group_key = gp.group_key;
END;
GO
