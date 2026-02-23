-- Microsoft SQL Server schema for chat history (tenant + soft-delete + tagging).

CREATE TABLE chat_tenants (
  id NVARCHAR(36) NOT NULL PRIMARY KEY,
  name NVARCHAR(200) NOT NULL,
  created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);

CREATE TABLE chat_sessions (
  id NVARCHAR(36) NOT NULL PRIMARY KEY,
  tenant_id NVARCHAR(36) NOT NULL,
  user_id NVARCHAR(80) NOT NULL,
  title NVARCHAR(200) NULL,
  consultant_id NVARCHAR(80) NULL,
  message_count INT NOT NULL DEFAULT 0,
  created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
  updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
  deleted_at DATETIME2 NULL,
  deleted_by NVARCHAR(80) NULL,
  CONSTRAINT fk_chat_sessions_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
);

CREATE INDEX ix_chat_sessions_tenant_user_updated
  ON chat_sessions (tenant_id, user_id, updated_at);

CREATE INDEX ix_chat_sessions_tenant_deleted
  ON chat_sessions (tenant_id, deleted_at);

CREATE TABLE chat_messages (
  id NVARCHAR(36) NOT NULL PRIMARY KEY,
  session_id NVARCHAR(36) NOT NULL,
  tenant_id NVARCHAR(36) NOT NULL,
  ts DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
  q NVARCHAR(MAX) NULL,
  a NVARCHAR(MAX) NULL,
  meta_json NVARCHAR(MAX) NULL,
  deleted_at DATETIME2 NULL,
  deleted_by NVARCHAR(80) NULL,
  CONSTRAINT fk_chat_messages_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id),
  CONSTRAINT fk_chat_messages_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
);

CREATE INDEX ix_chat_messages_session_ts
  ON chat_messages (session_id, ts);

CREATE INDEX ix_chat_messages_tenant_deleted
  ON chat_messages (tenant_id, deleted_at);

CREATE TABLE chat_tags (
  id NVARCHAR(36) NOT NULL PRIMARY KEY,
  tenant_id NVARCHAR(36) NOT NULL,
  name NVARCHAR(80) NOT NULL,
  created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
  CONSTRAINT uq_chat_tags_tenant_name UNIQUE (tenant_id, name),
  CONSTRAINT fk_chat_tags_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
);

CREATE INDEX ix_chat_tags_tenant_name
  ON chat_tags (tenant_id, name);

CREATE TABLE chat_session_tags (
  session_id NVARCHAR(36) NOT NULL,
  tag_id NVARCHAR(36) NOT NULL,
  tenant_id NVARCHAR(36) NOT NULL,
  created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
  CONSTRAINT uq_chat_session_tags_session_tag UNIQUE (session_id, tag_id),
  CONSTRAINT fk_chat_session_tags_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id),
  CONSTRAINT fk_chat_session_tags_tag FOREIGN KEY (tag_id) REFERENCES chat_tags(id),
  CONSTRAINT fk_chat_session_tags_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id),
  PRIMARY KEY (session_id, tag_id)
);

CREATE INDEX ix_chat_session_tags_tenant
  ON chat_session_tags (tenant_id);
