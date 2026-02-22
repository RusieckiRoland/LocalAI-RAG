-- PostgreSQL schema for chat history (tenant + soft-delete + tagging).

CREATE TABLE chat_tenants (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE chat_sessions (
  id VARCHAR(36) PRIMARY KEY,
  tenant_id VARCHAR(36) NOT NULL REFERENCES chat_tenants(id),
  user_id VARCHAR(80) NOT NULL,
  title VARCHAR(200),
  consultant_id VARCHAR(80),
  message_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ,
  deleted_by VARCHAR(80)
);

CREATE INDEX ix_chat_sessions_tenant_user_updated
  ON chat_sessions (tenant_id, user_id, updated_at);

CREATE INDEX ix_chat_sessions_tenant_deleted
  ON chat_sessions (tenant_id, deleted_at);

CREATE TABLE chat_messages (
  id VARCHAR(36) PRIMARY KEY,
  session_id VARCHAR(36) NOT NULL REFERENCES chat_sessions(id),
  tenant_id VARCHAR(36) NOT NULL REFERENCES chat_tenants(id),
  ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  q TEXT,
  a TEXT,
  meta_json TEXT,
  deleted_at TIMESTAMPTZ,
  deleted_by VARCHAR(80)
);

CREATE INDEX ix_chat_messages_session_ts
  ON chat_messages (session_id, ts);

CREATE INDEX ix_chat_messages_tenant_deleted
  ON chat_messages (tenant_id, deleted_at);

CREATE TABLE chat_tags (
  id VARCHAR(36) PRIMARY KEY,
  tenant_id VARCHAR(36) NOT NULL REFERENCES chat_tenants(id),
  name VARCHAR(80) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_chat_tags_tenant_name UNIQUE (tenant_id, name)
);

CREATE INDEX ix_chat_tags_tenant_name
  ON chat_tags (tenant_id, name);

CREATE TABLE chat_session_tags (
  session_id VARCHAR(36) NOT NULL REFERENCES chat_sessions(id),
  tag_id VARCHAR(36) NOT NULL REFERENCES chat_tags(id),
  tenant_id VARCHAR(36) NOT NULL REFERENCES chat_tenants(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_chat_session_tags_session_tag UNIQUE (session_id, tag_id),
  PRIMARY KEY (session_id, tag_id)
);

CREATE INDEX ix_chat_session_tags_tenant
  ON chat_session_tags (tenant_id);
