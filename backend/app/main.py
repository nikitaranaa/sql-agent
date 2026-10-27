"""FastAPI entry point.

Endpoints:
  POST /chat            one turn, JSON response
  POST /chat/stream     one turn, server-sent events: a "step" per graph node, then "result"
  GET  /schema          tables and columns for the sidebar
  GET  /history/{id}    conversation stored by the LangGraph checkpointer
  DELETE /history/{id}  forget a conversation
  GET  /graph           the compiled graph as Mermaid text
  GET  /health          liveness probe for the host
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from langchain_core.messages import HumanMessage

from app.config import get_settings
from app.db.database import get_schema
from app.db.seed import build_database
from app.graph.builder import build_graph, make_checkpointer
from app.graph.state import new_turn_input
from app.llm import LLMConfigError
from app.schemas import ChatRequest, ChatResponse, HistoryMessage

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    build_database(settings.database_path)   # no-op when the file exists
    schema = get_schema()
    logger.info("Loaded schema: %s", ", ".join(schema.tables))
    app.state.graph = build_graph(make_checkpointer())
    yield


app = FastAPI(
    title="SQL Query AI Agent",
    description="Natural language to validated, read-only SQL with LangGraph.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


def _config(session_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": session_id}, "recursion_limit": 40}


def _run_turn(req: ChatRequest) -> Iterator[tuple[str, Any]]:
    """Run the graph once, yielding ("step", node) per node and finally ("result", payload)."""
    graph = app.state.graph
    config = _config(req.session_id)
    steps: list[str] = []
    try:
        for update in graph.stream(
            new_turn_input(req.message.strip(), req.dialect, req.execute), config, stream_mode="updates"
        ):
            for node in update:
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


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind, payload in _run_turn(req):
        if kind == "result":
            result = payload
    return result


@app.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    def events() -> Iterator[str]:
        for kind, payload in _run_turn(req):
            if kind == "step":
                data = {"node": payload, "label": STEP_LABELS.get(payload, payload)}
            else:
                data = payload
            yield f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/history/{session_id}", response_model=list[HistoryMessage])
def history(session_id: str) -> list[dict[str, str]]:
    state = app.state.graph.get_state(_config(session_id))
    messages = (state.values or {}).get("messages", []) if state else []
    return [
        {"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": str(m.content)}
        for m in messages
    ]


@app.delete("/history/{session_id}")
def clear_history(session_id: str) -> dict[str, str]:
    checkpointer = app.state.graph.checkpointer
    if not hasattr(checkpointer, "delete_thread"):
        raise HTTPException(501, "This checkpointer cannot delete conversations.")
    checkpointer.delete_thread(session_id)
    return {"status": "deleted"}


@app.get("/graph", response_class=PlainTextResponse)
def graph_mermaid() -> str:
    return app.state.graph.get_graph().draw_mermaid()
