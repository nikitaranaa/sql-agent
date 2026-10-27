"""API tests through FastAPI's TestClient (with the fake LLM)."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def sid() -> str:
    return str(uuid.uuid4())


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_schema(client):
    body = client.get("/schema").json()
    names = [t["name"] for t in body["tables"]]
    assert "Customers" in names and body["examples"]
    orders = next(t for t in body["tables"] if t["name"] == "Orders")
    assert any(c["fk"] == "Customers.CustomerID" for c in orders["columns"])


def test_chat_returns_sql_and_results(client, fake_llm):
    fake_llm.queue_intent("generate")
    fake_llm.sqls.append("SELECT * FROM Customers WHERE State = 'CA'")
    body = client.post("/chat", json={"session_id": sid(), "message": "California customers"}).json()
    assert body["type"] == "sql"
    assert body["results"]["row_count"] > 0
    assert body["steps"][0] == "preflight" and body["steps"][-1] == "respond"


def test_chat_refusal(client, fake_llm):
    body = client.post("/chat", json={"session_id": sid(), "message": "Who won the FIFA World Cup?"}).json()
    assert body["type"] == "refusal"


def test_chat_rejects_bad_input(client):
    assert client.post("/chat", json={"session_id": "x", "message": "hi"}).status_code == 422
    assert client.post("/chat", json={"session_id": sid(), "message": ""}).status_code == 422
    assert client.post("/chat", json={"session_id": sid(), "message": "a" * 5000}).status_code == 422
    assert client.post("/chat", json={"session_id": sid(), "message": "x", "dialect": "oracle"}).status_code == 422


def test_llm_failure_becomes_error_response(client, monkeypatch):
    from app.graph import chains

    def boom(**kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(chains, "classify_intent", boom)
    body = client.post("/chat", json={"session_id": sid(), "message": "show customers"}).json()
    assert body["type"] == "error" and "provider down" in body["message"]


def test_stream_emits_steps_then_result(client, fake_llm):
    fake_llm.queue_intent("generate")
    fake_llm.sqls.append("SELECT COUNT(*) FROM Orders")
    with client.stream("POST", "/chat/stream", json={"session_id": sid(), "message": "count orders"}) as r:
        text = "".join(r.iter_text())
    events = [block for block in text.strip().split("\n\n") if block]
    kinds = [e.split("\n")[0].removeprefix("event: ") for e in events]
    assert kinds[0] == "step" and kinds[-1] == "result"
    result = json.loads(events[-1].split("data: ", 1)[1])
    assert result["type"] == "sql"


def test_history_roundtrip(client, fake_llm):
    session = sid()
    fake_llm.queue_intent("generate")
    fake_llm.sqls.append("SELECT * FROM Products")
    client.post("/chat", json={"session_id": session, "message": "show products"})
    history = client.get(f"/history/{session}").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert client.delete(f"/history/{session}").status_code == 200
    assert client.get(f"/history/{session}").json() == []


def test_graph_endpoint_returns_mermaid(client):
    text = client.get("/graph").text
    assert "validate_sql" in text and "generate_sql" in text
