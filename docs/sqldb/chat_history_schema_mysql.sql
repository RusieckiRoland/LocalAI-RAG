-- MySQL schema for chat history (tenant + soft-delete + tagging).

CREATE TABLE chat_tenants (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE chat_sessions (
  id VARCHAR(36) PRIMARY KEY,
  tenant_id VARCHAR(36) NOT NULL,
  user_id VARCHAR(80) NOT NULL,
  title VARCHAR(200),
  consultant_id VARCHAR(80),
  message_count INT NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6),
  deleted_by VARCHAR(80),
  CONSTRAINT fk_chat_sessions_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX ix_chat_sessions_tenant_user_updated
  ON chat_sessions (tenant_id, user_id, updated_at);

CREATE INDEX ix_chat_sessions_tenant_deleted
  ON chat_sessions (tenant_id, deleted_at);

CREATE TABLE chat_messages (
  id VARCHAR(36) PRIMARY KEY,
  session_id VARCHAR(36) NOT NULL,
  tenant_id VARCHAR(36) NOT NULL,
  ts DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  q TEXT,
  a TEXT,
  meta_json TEXT,
  deleted_at DATETIME(6),
  deleted_by VARCHAR(80),
  CONSTRAINT fk_chat_messages_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id),
  CONSTRAINT fk_chat_messages_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX ix_chat_messages_session_ts
  ON chat_messages (session_id, ts);

CREATE INDEX ix_chat_messages_tenant_deleted
  ON chat_messages (tenant_id, deleted_at);

CREATE TABLE chat_tags (
  id VARCHAR(36) PRIMARY KEY,
  tenant_id VARCHAR(36) NOT NULL,
  name VARCHAR(80) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT uq_chat_tags_tenant_name UNIQUE (tenant_id, name),
  CONSTRAINT fk_chat_tags_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX ix_chat_tags_tenant_name
  ON chat_tags (tenant_id, name);

CREATE TABLE chat_session_tags (
  session_id VARCHAR(36) NOT NULL,
  tag_id VARCHAR(36) NOT NULL,
  tenant_id VARCHAR(36) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT uq_chat_session_tags_session_tag UNIQUE (session_id, tag_id),
  CONSTRAINT fk_chat_session_tags_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id),
  CONSTRAINT fk_chat_session_tags_tag FOREIGN KEY (tag_id) REFERENCES chat_tags(id),
  CONSTRAINT fk_chat_session_tags_tenant FOREIGN KEY (tenant_id) REFERENCES chat_tenants(id),
  PRIMARY KEY (session_id, tag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX ix_chat_session_tags_tenant
  ON chat_session_tags (tenant_id);
