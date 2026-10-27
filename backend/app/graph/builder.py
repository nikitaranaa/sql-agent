"""Builds and compiles the LangGraph workflow.

    START -> preflight -> detect_intent -> check_scope -> load_schema -> (task) -> validate_sql
          -> analyze_query -> execute_query -> explain -> respond -> END

with exits to refuse / clarify / fail and a retry loop validate_sql -> generate_sql.
See docs/WORKFLOW.md for the node-by-node walkthrough.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graph import nodes
from app.graph.state import AgentState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(AgentState)

    builder.add_node("preflight", nodes.preflight)
    builder.add_node("detect_intent", nodes.detect_intent)
    builder.add_node("check_scope", nodes.check_scope)
    builder.add_node("load_schema", nodes.load_schema)
    builder.add_node("generate_sql", nodes.generate_sql)
    builder.add_node("optimize_sql", nodes.optimize_sql)
    builder.add_node("debug_sql", nodes.debug_sql)
    builder.add_node("validate_sql", nodes.validate_sql_node)
    builder.add_node("analyze_query", nodes.analyze_query)
    builder.add_node("execute_query", nodes.execute_query)
    builder.add_node("explain", nodes.explain)
    builder.add_node("respond", nodes.respond)
    builder.add_node("refuse", nodes.refuse)
    builder.add_node("clarify", nodes.clarify)
    builder.add_node("fail", nodes.fail)

    builder.add_edge(START, "preflight")
    builder.add_conditional_edges(
        "preflight", nodes.route_after_preflight, ["detect_intent", "refuse"]
    )
    builder.add_edge("detect_intent", "check_scope")
    builder.add_conditional_edges(
        "check_scope", nodes.route_by_intent, ["load_schema", "refuse", "clarify"]
    )
    builder.add_conditional_edges(
        "load_schema", nodes.route_by_task,
        ["generate_sql", "optimize_sql", "debug_sql", "validate_sql"],
    )
    builder.add_conditional_edges(
        "generate_sql", nodes.route_after_generation, ["validate_sql", "fail"]
    )
    builder.add_edge("optimize_sql", "validate_sql")
    builder.add_edge("debug_sql", "validate_sql")
    # The retry loop: invalid SQL goes back to generation with the exact errors.
    builder.add_conditional_edges(
        "validate_sql", nodes.route_after_validation,
        ["analyze_query", "generate_sql", "debug_sql", "fail"],
    )
    builder.add_conditional_edges(
        "analyze_query", nodes.route_after_analysis, ["execute_query", "explain"]
    )
    builder.add_edge("execute_query", "explain")
    builder.add_edge("explain", "respond")
    for terminal in ("respond", "refuse", "clarify", "fail"):
        builder.add_edge(terminal, END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())


def make_checkpointer() -> BaseCheckpointSaver:
    """MemorySaver by default (lost on restart); SqliteSaver when CHECKPOINT_DB is set."""
    path = get_settings().checkpoint_db
    if path:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        return SqliteSaver(sqlite3.connect(path, check_same_thread=False))
    return MemorySaver()
