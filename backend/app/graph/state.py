"""The state object that flows through every node of the graph."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # --- Turn input ---------------------------------------------------------------
    question: str
    dialect: str                 # sqlite | postgres | mysql (display dialect)
    execute: bool                # run the query against the sample DB?

    # --- Conversation memory (persisted by the checkpointer across turns) ---------
    messages: Annotated[list[AnyMessage], add_messages]   # reducer: appends turns
    last_sql: str | None         # last successfully validated query (for follow-ups)
    last_question: str | None

    # --- Per-turn working fields (reset by new_turn_input) ---------------------------
    forced_intent: str | None    # set by code-level preflight; overrides the LLM
    preflight_reason: str
    user_sql: str | None         # SQL pasted by the user (optimize / debug / explain)
    intent: str | None
    clarification_question: str
    clarification_options: list[str]
    safe_alternative: str
    tables: list[str]            # tables retrieved into the prompt
    schema_prompt: str
    sql: str | None              # current candidate SQL (SQLite dialect)
    notes: str
    errors: list[str]            # validator errors on the current candidate
    error_history: list[str]     # every error seen this turn (shown on failure)
    warnings: list[str]
    retries: int
    cost: dict[str, Any] | None
    optimization: dict[str, Any] | None
    debug: dict[str, Any] | None
    results: dict[str, Any] | None
    execution_error: str | None
    explanation: dict[str, Any] | None
    response: dict[str, Any] | None   # final payload returned to the API


def new_turn_input(question: str, dialect: str = "sqlite", execute: bool = True) -> dict[str, Any]:
    """Input for one turn: the new question plus every per-turn field reset.

    Keys with reducers (messages) are appended; plain keys overwrite, so passing
    them here clears the previous turn's leftovers while last_sql survives.
    """
    return {
        "question": question,
        "dialect": dialect,
        "execute": execute,
        "forced_intent": None,
        "preflight_reason": "",
        "user_sql": None,
        "intent": None,
        "clarification_question": "",
        "clarification_options": [],
        "safe_alternative": "",
        "tables": [],
        "schema_prompt": "",
        "sql": None,
        "notes": "",
        "errors": [],
        "error_history": [],
        "warnings": [],
        "retries": 0,
        "cost": None,
        "optimization": None,
        "debug": None,
        "results": None,
        "execution_error": None,
        "explanation": None,
        "response": None,
    }
