from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ChatTenant(Base):
    __tablename__ = "chat_tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    sessions: Mapped[list["ChatSession"]] = relationship(back_populates="tenant")
    tags: Mapped[list["ChatTag"]] = relationship(back_populates="tenant")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_tenants.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(200))
    consultant_id: Mapped[Optional[str]] = mapped_column(String(80))
    message_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column()
    deleted_by: Mapped[Optional[str]] = mapped_column(String(80))

    tenant: Mapped["ChatTenant"] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session")
    tags: Mapped[list["ChatSessionTag"]] = relationship(back_populates="session")

    __table_args__ = (
        Index("ix_chat_sessions_tenant_user_updated", "tenant_id", "user_id", "updated_at"),
        Index("ix_chat_sessions_tenant_deleted", "tenant_id", "deleted_at"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_tenants.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    q: Mapped[Optional[str]] = mapped_column(Text)
    a: Mapped[Optional[str]] = mapped_column(Text)
    meta_json: Mapped[Optional[str]] = mapped_column(Text)
    deleted_at: Mapped[Optional[datetime]] = mapped_column()
    deleted_by: Mapped[Optional[str]] = mapped_column(String(80))

    session: Mapped["ChatSession"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_chat_messages_session_ts", "session_id", "ts"),
        Index("ix_chat_messages_tenant_deleted", "tenant_id", "deleted_at"),
    )


class ChatTag(Base):
    __tablename__ = "chat_tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    tenant: Mapped["ChatTenant"] = relationship(back_populates="tags")
    sessions: Mapped[list["ChatSessionTag"]] = relationship(back_populates="tag")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_chat_tags_tenant_name"),
        Index("ix_chat_tags_tenant_name", "tenant_id", "name"),
    )


class ChatSessionTag(Base):
    __tablename__ = "chat_session_tags"

    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_tags.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_tenants.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="tags")
    tag: Mapped["ChatTag"] = relationship(back_populates="sessions")

    __table_args__ = (
        UniqueConstraint("session_id", "tag_id", name="uq_chat_session_tags_session_tag"),
        Index("ix_chat_session_tags_tenant", "tenant_id"),
    )
