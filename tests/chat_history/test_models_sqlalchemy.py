from datetime import datetime

import pytest

sa = pytest.importorskip("sqlalchemy")
orm = pytest.importorskip("sqlalchemy.orm")

from server.chat_history import Base, ChatMessage, ChatSession, ChatSessionTag, ChatTag, ChatTenant


@pytest.fixture()
def session():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = orm.sessionmaker(bind=engine, future=True)
    with Session() as sess:
        yield sess


def test_insert_session_message_and_tag(session) -> None:
    tenant = ChatTenant(id="t1", name="Tenant 1")
    session.add(tenant)
    session.flush()

    chat = ChatSession(
        id="s1",
        tenant_id="t1",
        user_id="u1",
        title="Test",
        consultant_id="ada",
    )
    session.add(chat)
    session.flush()

    msg = ChatMessage(
        id="m1",
        session_id="s1",
        tenant_id="t1",
        q="q",
        a="a",
    )
    session.add(msg)

    tag = ChatTag(id="tag1", tenant_id="t1", name="important")
    session.add(tag)
    session.flush()

    link = ChatSessionTag(session_id="s1", tag_id="tag1", tenant_id="t1")
    session.add(link)
    session.commit()

    loaded = session.get(ChatSession, "s1")
    assert loaded is not None
    assert loaded.tenant_id == "t1"

    tags = session.query(ChatTag).all()
    assert len(tags) == 1


def test_soft_delete_filters(session) -> None:
    tenant = ChatTenant(id="t2", name="Tenant 2")
    session.add(tenant)
    session.flush()

    chat = ChatSession(
        id="s2",
        tenant_id="t2",
        user_id="u2",
        title="Delete me",
    )
    session.add(chat)
    session.flush()

    chat.deleted_at = datetime.utcnow()
    session.commit()

    active = (
        session.query(ChatSession)
        .filter(ChatSession.tenant_id == "t2", ChatSession.deleted_at.is_(None))
        .all()
    )
    assert active == []


def test_unique_tag_per_tenant(session) -> None:
    tenant = ChatTenant(id="t3", name="Tenant 3")
    session.add(tenant)
    session.flush()

    session.add(ChatTag(id="tag2", tenant_id="t3", name="dup"))
    session.commit()

    session.add(ChatTag(id="tag3", tenant_id="t3", name="dup"))
    with pytest.raises(Exception):
        session.commit()
