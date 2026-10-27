"""Tests for the UX and production features: streaming, follow-ups, edit & run, export,
feedback, accounts, conversation sync, rate limiting and schema retrieval."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.config import get_settings
from app.db.database import ForeignKey, SchemaInfo, TableInfo
from app.graph import chains
from app.graph.nodes import rank_tables, select_relevant_tables
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def sid() -> str:
    return str(uuid.uuid4())


def sse_events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def signup(client, name=None) -> dict:
    name = name or f"user_{uuid.uuid4().hex[:8]}"
    r = client.post("/auth/register", json={"username": name, "password": "correct horse"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# --- streaming, follow-ups, clarification ----------------------------------------------------
def test_stream_sends_explanation_tokens_before_result(client, fake_llm):
    fake_llm.queue_intent("generate")
    fake_llm.sqls.append("SELECT COUNT(*) FROM Orders")
    with client.stream("POST", "/chat/stream", json={"session_id": sid(), "message": "count orders"}) as r:
        events = sse_events("".join(r.iter_text()))
    kinds = [k for k, _ in events]
    tokens = "".join(d["text"] for k, d in events if k == "token")
    assert tokens == "Explains: SELECT COUNT(*) FROM Orders"
    assert kinds.index("token") < kinds.index("result")
    assert events[-1][1]["follow_ups"] == ["Only those from California"]


def test_followup_reports_which_question_it_modified(client, fake_llm):
    session = sid()
    fake_llm.queue_intent("generate")
    fake_llm.sqls.append("SELECT * FROM Customers")
    first = client.post("/chat", json={"session_id": session, "message": "Show all customers"}).json()
    assert first["based_on"] is None
    fake_llm.queue_intent("followup")
    fake_llm.sqls.append("SELECT * FROM Customers WHERE State = 'CA'")
    second = client.post("/chat", json={"session_id": session, "message": "Only CA"}).json()
    assert second["based_on"] == "Show all customers"


def test_optimize_response_includes_formatted_original_for_diff(client, fake_llm):
    fake_llm.queue_intent("optimize")
    fake_llm.optimize_result = chains.OptimizeResult(optimized_sql="SELECT OrderID FROM Orders", changes=["x"])
    body = client.post("/chat", json={"session_id": sid(),
                                      "message": "Optimize: select * from Orders"}).json()
    assert body["optimization"]["original_formatted"].startswith("SELECT")


# --- edit & run --------------------------------------------------------------------------------
def test_run_edited_sql(client, fake_llm):
    body = client.post("/run", json={"sql": "SELECT * FROM Customers WHERE State = 'NY'",
                                     "question": "NY customers"}).json()
    assert body["ok"] and body["results"]["row_count"] > 0
    assert body["explanation"]["summary"].startswith("Explains:")
    assert body["cost"]["level"]


@pytest.mark.parametrize("sql", ["DELETE FROM Customers", "SELECT Nope FROM Customers",
                                 "SELECT 1; DROP TABLE Customers"])
def test_run_rejects_unsafe_or_invalid_sql(client, fake_llm, sql):
    body = client.post("/run", json={"sql": sql}).json()
    assert body["ok"] is False and body["errors"]
    assert fake_llm.called("explain_sql") == []


def test_run_converts_from_selected_dialect(client, fake_llm):
    body = client.post("/run", json={"sql": "SELECT TOP 3 * FROM Customers", "dialect": "sqlite"}).json()
    assert body["ok"] is False   # T-SQL isn't SQLite
    body = client.post("/run", json={"sql": "SELECT * FROM Customers LIMIT 3", "dialect": "postgres"}).json()
    assert body["ok"] and body["results"]["row_count"] == 3


def test_edited_sql_becomes_the_base_for_follow_ups(client, fake_llm):
    session = sid()
    fake_llm.queue_intent("generate")
    fake_llm.sqls.append("SELECT * FROM Customers")
    client.post("/chat", json={"session_id": session, "message": "Show all customers"})
    client.post("/run", json={"sql": "SELECT * FROM Customers WHERE State = 'TX'",
                              "question": "Texas customers", "session_id": session})
    fake_llm.queue_intent("followup")
    fake_llm.sqls.append("SELECT COUNT(*) FROM Customers WHERE State = 'TX'")
    client.post("/chat", json={"session_id": session, "message": "how many?"})
    assert "TX" in fake_llm.called("generate_sql")[-1]["previous_sql"]


# --- export ---------------------------------------------------------------------------------------
def test_export_returns_all_rows_not_just_the_preview(client):
    r = client.post("/export", json={"sql": "SELECT * FROM OrderItems"})
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert len(lines) - 1 > get_settings().max_result_rows   # more than the 100-row preview
    assert r.headers["x-truncated"] == "false"


def test_export_rejects_writes(client):
    assert client.post("/export", json={"sql": "DELETE FROM Customers"}).status_code == 422


# --- feedback -------------------------------------------------------------------------------------
def test_feedback_is_stored(client):
    from app.store import get_store

    r = client.post("/feedback", json={"session_id": sid(), "question": "q-feedback", "sql": "SELECT 1",
                                       "rating": "down", "comment": "wrong filter"})
    assert r.status_code == 200
    assert any(f["question"] == "q-feedback" and f["rating"] == "down" for f in get_store().list_feedback())


def test_feedback_rating_is_validated(client):
    r = client.post("/feedback", json={"session_id": sid(), "question": "q", "sql": "s", "rating": "meh"})
    assert r.status_code == 422


# --- accounts ---------------------------------------------------------------------------------------
def test_register_login_me(client):
    name = f"ada_{uuid.uuid4().hex[:6]}"
    signup(client, name)
    r = client.post("/auth/login", json={"username": name, "password": "correct horse"})
    token = r.json()["token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json() == {"username": name}


def test_duplicate_username_and_wrong_password(client):
    name = f"bob_{uuid.uuid4().hex[:6]}"
    signup(client, name)
    assert client.post("/auth/register", json={"username": name.upper(), "password": "whatever123"}).status_code == 409
    assert client.post("/auth/login", json={"username": name, "password": "nope-nope"}).status_code == 401


@pytest.mark.parametrize("username,password", [("ab", "longenough"), ("bad name!", "longenough"),
                                               ("goodname", "short")])
def test_register_validates_input(client, username, password):
    assert client.post("/auth/register", json={"username": username, "password": password}).status_code == 422


def test_bad_token_is_rejected_not_treated_as_anonymous(client):
    r = client.get("/conversations", headers={"Authorization": "Bearer forged.token.here"})
    assert r.status_code == 401
    assert client.get("/conversations").status_code == 401   # sign-in required


def test_passwords_are_hashed():
    from app.auth import hash_password, verify_password

    stored = hash_password("s3cret-pass")
    assert "s3cret-pass" not in stored and verify_password("s3cret-pass", stored)
    assert not verify_password("other", stored)


# --- conversation sync -------------------------------------------------------------------------------
def test_conversation_sync_roundtrip_and_isolation(client):
    alice, mallory = signup(client), signup(client)
    conv = sid()
    msgs = [{"role": "user", "content": "Show all customers"}]
    assert client.put(f"/conversations/{conv}", json={"title": "Customers", "messages": msgs},
                      headers=alice).status_code == 200
    listed = client.get("/conversations", headers=alice).json()
    assert listed[0]["id"] == conv and listed[0]["messages"] == msgs
    assert client.get("/conversations", headers=mallory).json() == []
    client.delete(f"/conversations/{conv}", headers=alice)
    assert client.get("/conversations", headers=alice).json() == []


def test_server_memory_is_namespaced_per_user(client, fake_llm):
    alice, mallory = signup(client), signup(client)
    session = sid()
    fake_llm.queue_intent("generate")
    fake_llm.sqls.append("SELECT * FROM Products")
    client.post("/chat", json={"session_id": session, "message": "show products"}, headers=alice)
    assert len(client.get(f"/history/{session}", headers=alice).json()) == 2
    assert client.get(f"/history/{session}", headers=mallory).json() == []
    assert client.get(f"/history/{session}").json() == []


def test_oversized_conversation_is_rejected(client):
    alice = signup(client)
    big = [{"content": "x" * 2_100_000}]
    assert client.put(f"/conversations/{sid()}", json={"title": "t", "messages": big},
                      headers=alice).status_code == 413


# --- rate limiting ------------------------------------------------------------------------------------
def test_rate_limit_returns_429(client, fake_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 2)
    ratelimit.reset()
    for _ in range(2):
        fake_llm.queue_intent("generate")
        fake_llm.sqls.append("SELECT 1 FROM Customers")
        assert client.post("/chat", json={"session_id": sid(), "message": "customers"}).status_code == 200
    r = client.post("/chat", json={"session_id": sid(), "message": "customers"})
    assert r.status_code == 429 and "too quickly" in r.json()["detail"]


def test_rate_limit_is_per_client():
    ratelimit.reset()
    ratelimit.check("ip:1", per_minute=1, per_day=10)
    with pytest.raises(Exception):
        ratelimit.check("ip:1", per_minute=1, per_day=10)
    ratelimit.check("ip:2", per_minute=1, per_day=10)   # someone else is unaffected


# --- schema retrieval (BM25) --------------------------------------------------------------------------
def _big_schema() -> SchemaInfo:
    schema = SchemaInfo()
    def table(name, cols, fks=()):
        schema.tables[name] = TableInfo(name, [{"name": c, "type": "TEXT", "pk": 0, "notnull": 0} for c in cols],
                                        list(fks), [], 0, [], f"CREATE TABLE {name} ()")
    for i in range(40):
        table(f"Filler{i}", [f"Col{i}", "Notes"])
    table("Customers", ["CustomerID", "FirstName", "State"])
    table("Invoices", ["InvoiceID", "CustomerID", "Amount"], [ForeignKey("CustomerID", "Customers", "CustomerID")])
    table("ShippingCarriers", ["CarrierID", "CarrierName"])
    return schema


def test_bm25_ranks_the_relevant_table_first():
    ranked = rank_tables(_big_schema(), "total invoice amount per month")
    assert ranked[0][1] == "Invoices"


def test_large_schema_retrieval_adds_fk_neighbours_and_skips_noise():
    chosen = select_relevant_tables(_big_schema(), "invoice amounts")
    assert chosen[0] == "Invoices" and "Customers" in chosen   # joinable neighbour
    assert not any(name.startswith("Filler") for name in chosen)
    assert len(chosen) < 10


def test_small_schema_is_sent_whole(schema):
    assert select_relevant_tables(schema, "anything") == list(schema.tables)


def test_run_reports_truncation(client, fake_llm):
    body = client.post("/run", json={"sql": "SELECT * FROM OrderItems"}).json()
    assert body["results"]["row_count"] == 100 and body["results"]["truncated"] is True
