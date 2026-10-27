"""Postgres-backed storage. Runs only when TEST_DATABASE_URL points at a scratch database:

    TEST_DATABASE_URL=postgresql://... pytest tests/test_postgres.py
"""

import os
import uuid

import pytest
from langgraph.checkpoint.postgres import PostgresSaver

from app.config import get_settings
from app.graph.builder import build_graph, make_checkpointer
from app.graph.state import new_turn_input
from app.store import Store

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_DATABASE_URL to run Postgres tests")


@pytest.fixture
def postgres(monkeypatch):
    monkeypatch.setattr(get_settings(), "database_url", URL)
    yield URL


def test_store_on_postgres(postgres):
    store = Store()
    assert store.postgres
    name = f"pg_{uuid.uuid4().hex[:8]}"
    user_id = store.create_user(name, "scrypt$hash")
    assert user_id and store.create_user(name.upper(), "x") is None     # case-insensitive unique
    conv = str(uuid.uuid4())
    store.save_conversation(user_id, conv, "Title", [{"role": "user", "content": "hi"}])
    store.save_conversation(user_id, conv, "Renamed", [{"role": "user", "content": "hi"}])   # upsert
    convs = store.list_conversations(user_id)
    assert [(c["id"], c["title"]) for c in convs] == [(conv, "Renamed")]
    store.add_feedback("s" * 8, user_id, "q", "SELECT 1", "up", "")
    assert any(f["question"] == "q" for f in store.list_feedback())
    store.delete_conversation(user_id, conv)
    assert store.list_conversations(user_id) == []


def test_conversation_memory_survives_a_restart(postgres, fake_llm):
    assert isinstance(make_checkpointer(), PostgresSaver)
    thread = {"configurable": {"thread_id": f"pg-{uuid.uuid4()}"}}

    fake_llm.queue_intent("generate")
    fake_llm.sqls.append("SELECT * FROM Customers")
    build_graph(make_checkpointer()).invoke(new_turn_input("Show all customers"), thread)

    # A brand-new graph and connection pool, as after a server restart.
    restarted = build_graph(make_checkpointer())
    fake_llm.queue_intent("followup")
    fake_llm.sqls.append("SELECT * FROM Customers WHERE State = 'CA'")
    restarted.invoke(new_turn_input("Only those from California"), thread)
    assert fake_llm.called("generate_sql")[-1]["previous_sql"] == "SELECT * FROM Customers"
    assert len(restarted.get_state(thread).values["messages"]) == 4
