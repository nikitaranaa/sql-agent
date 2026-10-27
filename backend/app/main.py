"""FastAPI entry point.

Endpoints:
  POST /chat                one turn, JSON response
  POST /chat/stream         one turn, server-sent events: "step" per graph node,
                            "token" while the explanation is written, then "result"
  POST /run                 validate + run SQL the user edited, with a fresh explanation
  POST /export              full CSV of a validated query (beyond the 100-row preview)
  POST /feedback            thumbs up / down on an answer
  POST /auth/register|login optional accounts; GET /auth/me
  GET/PUT/DELETE /conversations[/{id}]   conversation sync for signed-in users
  GET  /schema              tables and columns for the sidebar
  GET  /history/{id}        conversation stored by the LangGraph checkpointer
  DELETE /history/{id}      forget a conversation
  GET  /graph               the compiled graph as Mermaid text
  GET  /health              liveness probe for the host
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from langchain_core.messages import HumanMessage

from app import ratelimit
from app.analysis.cost import estimate_cost
from app.auth import User, create_token, hash_password, optional_user, required_user, verify_password
from app.config import get_settings
from app.db.database import QueryTimeoutError, execute_readonly, get_schema
from app.db.seed import build_database
from app.graph import chains
from app.graph.builder import build_graph, make_checkpointer
from app.graph.nodes import describe_results
from app.graph.state import new_turn_input
from app.llm import LLMConfigError
from app.schemas import (
    AuthRequest, AuthResponse, ChatRequest, ChatResponse, ConversationIn, ExportRequest,
    FeedbackRequest, HistoryMessage, RunRequest,
)
from app.store import get_store
from app.validation.validator import ensure_limit, to_sqlite, transpile, validate_sql

logger = logging.getLogger("sql_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STEP_LABELS = {
    "preflight": "Checking the request",
    "detect_intent": "Detecting intent",
    "check_scope": "Checking scope",
    "load_schema": "Loading schema",
    "generate_sql": "Writing SQL",
    "optimize_sql": "Optimizing SQL",
    "debug_sql": "Debugging SQL",
    "validate_sql": "Validating SQL",
    "analyze_query": "Estimating cost",
    "execute_query": "Running query (read-only)",
    "explain": "Explaining the query",
    "respond": "Done",
    "refuse": "Declined",
    "clarify": "Needs clarification",
    "fail": "Could not produce valid SQL",
}

EXAMPLE_PROMPTS = [
    "Show all employees hired after January 2024",
    "Top 5 customers by total revenue",
    "Monthly revenue for 2025",
    "Which products have never been ordered?",
    "Optimize: SELECT * FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID WHERE o.Status = 'Pending'",
    "Debug: SELECT FirstName, COUNT(*) FROM Customers WHERE Phone = NULL",
    "Delete all customers",
    "Who won the FIFA World Cup?",
]

MAX_CONVERSATION_BYTES = 2_000_000


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    build_database(settings.database_path)   # no-op when the file exists
    schema = get_schema()
    logger.info("Loaded schema: %s", ", ".join(schema.tables))
    get_store()                               # create account/feedback tables
    app.state.graph = build_graph(make_checkpointer())
    yield


app = FastAPI(
    title="SQL Query AI Agent",
    description="Natural language to validated, read-only SQL with LangGraph.",
    version="1.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    expose_headers=["X-Truncated"],
)


def _thread_id(session_id: str, user: User | None) -> str:
    # Signed-in users' server memory is namespaced by user, so another account can't
    # read it even with the conversation id.
    return f"u{user.id}-{session_id}" if user else session_id


def _config(session_id: str, user: User | None = None) -> dict[str, Any]:
    return {"configurable": {"thread_id": _thread_id(session_id, user)}, "recursion_limit": 40}


def _restore_context(graph, config: dict[str, Any], req: ChatRequest) -> dict[str, Any]:
    """Seed last_sql from the browser when the server has forgotten this session.

    Server memory is in RAM by default, so a restart or a sleeping free-tier host loses it
    while the browser still shows the conversation. The client value is untrusted: it is
    only accepted if it passes the same validation as generated SQL.
    """
    if not req.previous_sql:
        return {}
    state = graph.get_state(config)
    if (state.values or {}).get("last_sql"):
        return {}
    if not validate_sql(req.previous_sql, get_schema()).ok:
        return {}
    return {"last_sql": req.previous_sql, "last_question": req.previous_question}


def _run_turn(req: ChatRequest, user: User | None) -> Iterator[tuple[str, Any]]:
    """Run the graph once, yielding ("step", node), ("token", text) and finally ("result", payload)."""
    graph = app.state.graph
    config = _config(req.session_id, user)
    steps: list[str] = []
    try:
        turn = new_turn_input(req.message.strip(), req.dialect, req.execute)
        turn.update(_restore_context(graph, config, req))
        for mode, chunk in graph.stream(turn, config, stream_mode=["updates", "custom"]):
            if mode == "custom":
                if chunk.get("token"):
                    yield "token", chunk["token"]
                continue
            for node in chunk:
                steps.append(node)
                yield "step", node
        response = graph.get_state(config).values.get("response") or {
            "type": "error", "message": "The agent finished without a response."
        }
    except LLMConfigError as exc:
        logger.error("LLM configuration error: %s", exc)
        response = {"type": "error", "message": f"The language model is not configured: {exc}"}
    except Exception as exc:  # LLM/network failures should not crash the API
        logger.exception("Agent run failed")
        response = {"type": "error", "message": f"Something went wrong while processing the request: {exc}"}
    response["steps"] = steps
    yield "result", ChatResponse(**response).model_dump()


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    # This is the API; the chat UI lives on the frontend. Send visitors to the docs.
    return RedirectResponse("/docs")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/schema")
def schema() -> dict[str, Any]:
    return {
        "tables": get_schema().to_api(),
        "dialects": ["sqlite", "postgres", "mysql"],
        "examples": EXAMPLE_PROMPTS,
    }


# --- chat ---------------------------------------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, user: User | None = Depends(optional_user)) -> dict[str, Any]:
    ratelimit.check(ratelimit.client_key(request, user))
    result: dict[str, Any] = {}
    for kind, payload in _run_turn(req, user):
        if kind == "result":
            result = payload
    return result


@app.post("/chat/stream")
def chat_stream(req: ChatRequest, request: Request,
                user: User | None = Depends(optional_user)) -> StreamingResponse:
    ratelimit.check(ratelimit.client_key(request, user))

    def events() -> Iterator[str]:
        for kind, payload in _run_turn(req, user):
            if kind == "step":
                data: Any = {"node": payload, "label": STEP_LABELS.get(payload, payload)}
            elif kind == "token":
                data = {"text": payload}
            else:
                data = payload
            yield f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- edit & run, export, feedback -----------------------------------------------------------
@app.post("/run")
def run_sql(req: RunRequest, request: Request, user: User | None = Depends(optional_user)) -> dict[str, Any]:
    """Run SQL the user edited. It goes through exactly the same validator as generated SQL."""
    ratelimit.check(ratelimit.client_key(request, user))
    schema_info = get_schema()
    sql = to_sqlite(req.sql.strip(), req.dialect)
    check = validate_sql(sql, schema_info)
    if not check.ok:
        return {"ok": False, "errors": check.errors, "warnings": check.warnings}

    settings = get_settings()
    try:
        # One extra row so execute_readonly can tell the result was cut off.
        results, execution_error = execute_readonly(ensure_limit(sql, settings.max_result_rows + 1)), None
    except QueryTimeoutError as exc:
        results, execution_error = None, str(exc)
    except Exception as exc:
        results, execution_error = None, f"Execution failed: {exc}"
    try:
        explanation = chains.explain_sql(
            sql, f"Edited by the user. Their original request: {req.question or '(unknown)'}",
            schema_info.to_prompt(), describe_results(results),
        ).model_dump()
    except Exception:
        explanation = {"summary": "Your edited query was validated and run, but an explanation "
                                  "could not be generated this time.", "details": [], "follow_ups": []}

    if req.session_id:   # later follow-ups should build on the edited query
        config = _config(req.session_id, user)
        try:
            if app.state.graph.get_state(config).values:
                app.state.graph.update_state(config, {"last_sql": sql, "last_question": req.question},
                                             as_node="respond")
        except Exception:
            logger.warning("Could not update conversation memory after an edit", exc_info=True)

    return {
        "ok": True,
        "sql": transpile(sql, req.dialect),
        "sql_sqlite": sql,
        "dialect": req.dialect,
        "results": results,
        "execution_error": execution_error,
        "warnings": check.warnings,
        "cost": estimate_cost(sql, schema_info).to_dict(),
        "explanation": explanation,
        "follow_ups": explanation.get("follow_ups") or [],
    }


@app.post("/export")
def export_csv(req: ExportRequest, request: Request,
               user: User | None = Depends(optional_user)) -> StreamingResponse:
    """Full results as CSV (up to EXPORT_MAX_ROWS), on the same read-only connection."""
    ratelimit.check(ratelimit.client_key(request, user) + ":export", per_minute=5, per_day=100)
    check = validate_sql(req.sql, get_schema())
    if not check.ok:
        raise HTTPException(422, "; ".join(check.errors))
    settings = get_settings()
    try:
        data = execute_readonly(req.sql, max_rows=settings.export_max_rows,
                                timeout=settings.export_timeout_seconds)
    except QueryTimeoutError as exc:
        raise HTTPException(408, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Execution failed: {exc}") from exc

    def rows() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(data["columns"])
        for i, row in enumerate(data["rows"], 1):
            writer.writerow(row)
            if i % 1000 == 0:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    return StreamingResponse(rows(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="results.csv"',
        "X-Truncated": "true" if data["truncated"] else "false",
    })


@app.post("/feedback")
def feedback(req: FeedbackRequest, request: Request,
             user: User | None = Depends(optional_user)) -> dict[str, str]:
    ratelimit.check(ratelimit.client_key(request, user) + ":feedback", per_minute=30, per_day=500)
    get_store().add_feedback(req.session_id, user.id if user else None, req.question, req.sql,
                             req.rating, req.comment)
    return {"status": "saved"}


# --- accounts -------------------------------------------------------------------------------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


@app.post("/auth/register", response_model=AuthResponse)
def register(req: AuthRequest, request: Request) -> dict[str, str]:
    ratelimit.check(ratelimit.client_key(request, None) + ":auth", per_minute=10, per_day=200)
    if not USERNAME_RE.match(req.username):
        raise HTTPException(422, "Username must be 3-32 letters, digits, '.', '_' or '-'.")
    if len(req.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters.")
    user_id = get_store().create_user(req.username, hash_password(req.password))
    if user_id is None:
        raise HTTPException(409, "That username is taken.")
    user = User(id=user_id, username=req.username)
    return {"token": create_token(user), "username": user.username}


@app.post("/auth/login", response_model=AuthResponse)
def login(req: AuthRequest, request: Request) -> dict[str, str]:
    ratelimit.check(ratelimit.client_key(request, None) + ":auth", per_minute=10, per_day=200)
    row = get_store().get_user(req.username)
    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(401, "Wrong username or password.")
    user = User(id=row["id"], username=row["username"])
    return {"token": create_token(user), "username": user.username}


@app.get("/auth/me")
def me(user: User = Depends(required_user)) -> dict[str, Any]:
    return {"username": user.username}


@app.get("/conversations")
def list_conversations(user: User = Depends(required_user)) -> list[dict[str, Any]]:
    return get_store().list_conversations(user.id)


@app.put("/conversations/{conv_id}")
def save_conversation(conv_id: str, body: ConversationIn, user: User = Depends(required_user)) -> dict[str, str]:
    if not re.match(r"^[A-Za-z0-9_-]{8,64}$", conv_id):
        raise HTTPException(422, "Invalid conversation id.")
    if len(json.dumps(body.messages, default=str)) > MAX_CONVERSATION_BYTES:
        raise HTTPException(413, "This conversation is too large to sync.")
    get_store().save_conversation(user.id, conv_id, body.title, body.messages)
    return {"status": "saved"}


@app.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str, user: User = Depends(required_user)) -> dict[str, str]:
    get_store().delete_conversation(user.id, conv_id)
    _forget(conv_id, user)
    return {"status": "deleted"}


# --- server-side memory -----------------------------------------------------------------------
def _forget(session_id: str, user: User | None) -> None:
    checkpointer = app.state.graph.checkpointer
    if hasattr(checkpointer, "delete_thread"):
        checkpointer.delete_thread(_thread_id(session_id, user))


@app.get("/history/{session_id}", response_model=list[HistoryMessage])
def history(session_id: str, user: User | None = Depends(optional_user)) -> list[dict[str, str]]:
    state = app.state.graph.get_state(_config(session_id, user))
    messages = (state.values or {}).get("messages", []) if state else []
    return [
        {"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": str(m.content)}
        for m in messages
    ]


@app.delete("/history/{session_id}")
def clear_history(session_id: str, user: User | None = Depends(optional_user)) -> dict[str, str]:
    if not hasattr(app.state.graph.checkpointer, "delete_thread"):
        raise HTTPException(501, "This checkpointer cannot delete conversations.")
    _forget(session_id, user)
    return {"status": "deleted"}


@app.get("/graph", response_class=PlainTextResponse)
def graph_mermaid() -> str:
    return app.state.graph.get_graph().draw_mermaid()
