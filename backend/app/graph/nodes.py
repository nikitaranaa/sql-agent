"""Graph nodes. Each takes the state and returns only the fields it changed.

LLM work goes through ``chains``; every decision about safety is made here in code.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_stream_writer

from app.analysis.cost import estimate_cost
from app.config import get_settings
from app.db.database import QueryTimeoutError, SchemaInfo, execute_readonly, explain_query_plan, get_schema
from app.graph import chains
from app.graph.state import AgentState
from app.validation import guards
from app.validation.validator import ensure_limit, to_sqlite, transpile, validate_sql

USER_SQL_INTENTS = {"optimize", "debug", "explain"}

OUT_OF_SCOPE_MESSAGE = (
    "I'm designed to assist only with SQL and database-related tasks. "
    "Please ask a question related to the provided database schema."
)
INJECTION_MESSAGE = (
    "I can't follow instructions that try to change how I work. I'm a read-only SQL assistant "
    "for this database: ask me a question about the data, or paste a query to explain, "
    "optimize or debug."
)
DESTRUCTIVE_MESSAGE = (
    "I can't do that: this assistant is read-only, so it never creates, modifies or deletes "
    "data or tables (no INSERT, UPDATE, DELETE, DROP, ALTER or TRUNCATE)."
)


# --- helpers ---------------------------------------------------------------------------
def schema_terms(schema: SchemaInfo) -> set[str]:
    terms: set[str] = set()
    for t in schema.tables.values():
        terms.add(t.name.lower().rstrip("s"))
        terms |= {c.lower().rstrip("s") for c in t.column_names}
        # split CamelCase: OrderItems -> order, item
        terms |= {w.lower().rstrip("s") for w in re.findall(r"[A-Z][a-z]+", t.name)}
    return terms


def _tokens(text: str) -> list[str]:
    """Split identifiers and words: 'OrderItems', 'unit_price' -> order, item, unit, price."""
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", text.replace("_", " "))
    return [w.lower().rstrip("s") for w in words if len(w) > 1]


def rank_tables(schema: SchemaInfo, text: str, k1: float = 1.5, b: float = 0.75) -> list[tuple[float, str]]:
    """BM25 score of each table for the question. A table's document is its name (weighted x3),
    its column names and the tables it references."""
    docs = {}
    for t in schema.tables.values():
        doc = _tokens(t.name) * 3 + _tokens(" ".join(t.column_names))
        doc += _tokens(" ".join(fk.ref_table for fk in t.foreign_keys))
        docs[t.name] = Counter(doc)
    if not docs:
        return []
    avg_len = sum(sum(d.values()) for d in docs.values()) / len(docs)
    query = set(_tokens(text))
    scores = []
    for name, doc in docs.items():
        length = sum(doc.values())
        score = 0.0
        for term in query:
            tf = doc.get(term, 0)
            if not tf:
                continue
            df = sum(1 for d in docs.values() if term in d)
            idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg_len))
        if score > 0:
            scores.append((score, name))
    return sorted(scores, reverse=True)


def select_relevant_tables(schema: SchemaInfo, text: str, extra_sql: str | None = None,
                           top_k: int = 8) -> list[str]:
    """Schema retrieval. Small schemas go in whole; large ones get the BM25 top-k tables plus
    their foreign-key neighbours (so the joins between them are possible)."""
    names = list(schema.tables)
    if len(names) <= get_settings().schema_full_threshold:
        return names
    chosen = [name for _, name in rank_tables(schema, f"{text} {extra_sql or ''}")[:top_k]]
    for name in list(chosen):
        for fk in schema.tables[name].foreign_keys:
            if fk.ref_table in schema.tables and fk.ref_table not in chosen:
                chosen.append(fk.ref_table)
    return chosen or names[: get_settings().schema_full_threshold]


def describe_results(results: dict[str, Any] | None) -> str:
    """A short note about the results, so the explanation can mention what came back."""
    if not results:
        return ""
    return (
        f"\nThe query returned {results['row_count']} row(s)"
        f"{' (truncated)' if results['truncated'] else ''}. "
        f"Columns: {', '.join(results['columns'])}. First rows: {results['rows'][:3]}"
    )


def _history_text(state: AgentState) -> str:
    turns = get_settings().history_turns
    lines = []
    for m in (state.get("messages") or [])[-turns * 2:]:
        role = "User" if isinstance(m, HumanMessage) else "Assistant"
        lines.append(f"{role}: {str(m.content)[:400]}")
    return "\n".join(lines)


# --- nodes --------------------------------------------------------------------------------
def preflight(state: AgentState) -> dict[str, Any]:
    """Code-only checks before any LLM call: injection, destructive, obvious off-topic."""
    question = state["question"]
    result = guards.preflight(question, schema_terms(get_schema()))
    user_sql = result.user_sql
    if user_sql:
        user_sql = to_sqlite(user_sql, state.get("dialect") or "sqlite")
    return {
        "forced_intent": result.forced_intent,
        "preflight_reason": result.reason,
        "user_sql": user_sql,
        "messages": [HumanMessage(content=question)],
    }


def detect_intent(state: AgentState) -> dict[str, Any]:
    """LLM classifier (fast model): which job is this, and is it in scope?"""
    schema = get_schema()
    try:
        result = chains.classify_intent(
            message=state["question"],
            schema_prompt=schema.to_prompt(sample_rows=0),
            previous_question=state.get("last_question"),
            previous_sql=state.get("last_sql"),
            history=_history_text(state),
        )
    except Exception:
        # Code already decided to refuse; the LLM was only asked for a safe alternative.
        if state.get("forced_intent") == "destructive":
            return {"intent": "destructive"}
        raise
    return {
        "intent": result.intent,
        "clarification_question": result.clarification_question,
        "clarification_options": result.clarification_options[:3],
        "safe_alternative": result.safe_alternative,
    }


def check_scope(state: AgentState) -> dict[str, Any]:
    """Code-level policy on top of the classifier. Code always wins over the LLM."""
    intent = state.get("intent") or "generate"
    update: dict[str, Any] = {}

    if state.get("forced_intent") == "destructive":
        intent = "destructive"
    elif intent in USER_SQL_INTENTS and not state.get("user_sql"):
        if state.get("last_sql"):          # "explain that", "optimize it"
            update["user_sql"] = state["last_sql"]
        else:
            intent = "clarify"
            update["clarification_question"] = (
                f"Please paste the SQL query you'd like me to {state.get('intent')}."
            )
    elif intent == "followup" and not state.get("last_sql"):
        intent = "generate"
    elif intent == "clarify" and not state.get("clarification_question"):
        update["clarification_question"] = (
            "Could you be more specific? Tell me which table or metric you're interested in."
        )
    update["intent"] = intent
    return update


def load_schema(state: AgentState) -> dict[str, Any]:
    """Schema retrieval + seed the candidate SQL for optimize/debug/explain."""
    schema = get_schema()
    intent = state["intent"]
    extra_sql = state.get("user_sql") or (state.get("last_sql") if intent == "followup" else None)
    tables = select_relevant_tables(schema, state["question"], extra_sql)
    update: dict[str, Any] = {"tables": tables, "schema_prompt": schema.to_prompt(tables)}
    if intent in USER_SQL_INTENTS:
        update["sql"] = state.get("user_sql")
    return update


def generate_sql(state: AgentState) -> dict[str, Any]:
    """Generate (or follow-up modify) SQL; on a retry, repair it using the validator's errors."""
    if state.get("errors"):
        result = chains.repair_sql(
            message=state["question"], intent=state["intent"], sql=state.get("sql") or "",
            errors=state["errors"], schema_prompt=state["schema_prompt"],
        )
    else:
        followup = state["intent"] == "followup"
        result = chains.generate_sql(
            message=state["question"],
            schema_prompt=state["schema_prompt"],
            previous_sql=state.get("last_sql") if followup else None,
            previous_question=state.get("last_question") if followup else None,
        )
    return {"sql": result.sql.strip(), "notes": result.notes}


def optimize_sql(state: AgentState) -> dict[str, Any]:
    original = state["sql"]
    try:
        plan = explain_query_plan(original)
    except Exception as exc:
        plan = [f"(original query does not compile: {exc})"]
    result = chains.optimize_sql(state["question"], original, plan, state["schema_prompt"])
    return {
        "sql": result.optimized_sql.strip(),
        "optimization": {
            "original_sql": original,
            "original_plan": plan,
            "changes": result.changes,
            "removed_joins": result.removed_joins,
            "index_recommendations": [i.model_dump() for i in result.index_recommendations],
        },
    }


def debug_sql(state: AgentState) -> dict[str, Any]:
    original = state["sql"] or ""
    found = validate_sql(original, get_schema())
    result = chains.debug_sql(state["question"], original, found.errors, state["schema_prompt"])
    return {
        "intent": "debug",
        "sql": result.corrected_sql.strip(),
        "errors": [],
        "debug": {
            "original_sql": original,
            "validator_errors": found.errors,
            "issues": [i.model_dump() for i in result.issues],
        },
    }


def validate_sql_node(state: AgentState) -> dict[str, Any]:
    """Every SQL string passes here before it can reach the database."""
    result = validate_sql(state.get("sql") or "", get_schema())
    update: dict[str, Any] = {"errors": result.errors, "warnings": result.warnings}
    if result.errors:
        update["error_history"] = (state.get("error_history") or []) + result.errors
        if state.get("intent") == "explain":
            update["intent"] = "debug"   # can't explain broken SQL: debug it first
        else:
            update["retries"] = (state.get("retries") or 0) + 1
    return update


def analyze_query(state: AgentState) -> dict[str, Any]:
    """SQL optimization step for every query: plan, cost estimate, index advice (code only)."""
    cost = estimate_cost(state["sql"], get_schema())
    return {"cost": cost.to_dict()}


def execute_query(state: AgentState) -> dict[str, Any]:
    settings = get_settings()
    # One extra row so execute_readonly can tell the result was cut off.
    sql = ensure_limit(state["sql"], settings.max_result_rows + 1)
    try:
        return {"results": execute_readonly(sql), "execution_error": None}
    except QueryTimeoutError as exc:
        return {"results": None, "execution_error": str(exc)}
    except Exception as exc:
        return {"results": None, "execution_error": f"Execution failed: {exc}"}


def explain(state: AgentState) -> dict[str, Any]:
    intent = state["intent"]
    context = {
        "generate": f"Generated for the request: {state['question']}",
        "followup": f"Modified previous query for the follow-up: {state['question']}",
        "optimize": "Optimized version of the user's query.",
        "debug": "Corrected version of the user's query.",
        "explain": f"The user asked: {state['question']}",
    }.get(intent, state["question"])
    results_note = describe_results(state.get("results"))
    writer = get_stream_writer()
    try:
        result = chains.explain_sql(state["sql"], context, state["schema_prompt"], results_note,
                                    on_token=lambda text: writer({"token": text}))
    except Exception:
        # The SQL is already validated (and maybe executed); don't lose it over the explanation.
        return {"explanation": {
            "summary": "The query was validated and run, but a plain-English explanation could not be generated this time.",
            "details": [],
        }}
    return {"explanation": result.model_dump()}


def respond(state: AgentState) -> dict[str, Any]:
    sql = state["sql"]
    dialect = state.get("dialect") or "sqlite"
    explanation = state.get("explanation") or {}
    response = {
        "type": "sql",
        "intent": state["intent"],
        "message": explanation.get("summary", ""),
        "sql": transpile(sql, dialect),
        "sql_sqlite": sql,
        "dialect": dialect,
        "explanation": explanation,
        "results": state.get("results"),
        "execution_error": state.get("execution_error"),
        "warnings": state.get("warnings") or [],
        "notes": state.get("notes") or "",
        "cost": state.get("cost"),
        "optimization": state.get("optimization"),
        "debug": state.get("debug"),
        "retries": state.get("retries") or 0,
        "tables": state.get("tables") or [],
        "follow_ups": explanation.get("follow_ups") or [],
        # Shown as "Modifying: ..." so users see which query a follow-up changed.
        "based_on": state.get("last_question") if state["intent"] == "followup" else None,
    }
    # Same dialect and formatting as the new SQL, so the UI can diff them line by line.
    for key in ("optimization", "debug"):
        if response[key]:
            response[key] = {**response[key],
                             "original_formatted": transpile(response[key]["original_sql"], dialect)}
    summary = f"{explanation.get('summary', '')}\nSQL: {sql}"
    return {
        "response": response,
        "last_sql": sql,
        "last_question": state["question"],
        "messages": [AIMessage(content=summary)],
    }


def refuse(state: AgentState) -> dict[str, Any]:
    kind = state.get("forced_intent") or state.get("intent") or "out_of_scope"
    if kind == "injection":
        message = INJECTION_MESSAGE
    elif kind == "destructive":
        alt = state.get("safe_alternative")
        message = DESTRUCTIVE_MESSAGE + (
            f' I can show you the data instead. Try: "{alt}"' if alt
            else " I can help you look at the data instead, for example by showing the matching rows."
        )
    else:
        message = OUT_OF_SCOPE_MESSAGE
    return {
        "response": {"type": "refusal", "intent": kind, "message": message},
        "messages": [AIMessage(content=message)],
    }


def clarify(state: AgentState) -> dict[str, Any]:
    question = state.get("clarification_question") or "Could you be more specific?"
    return {
        "response": {"type": "clarification", "intent": "clarify", "message": question,
                     "options": state.get("clarification_options") or []},
        "messages": [AIMessage(content=question)],
    }


def fail(state: AgentState) -> dict[str, Any]:
    if not state.get("sql") and state.get("notes"):
        message = state["notes"]   # the model said the schema can't answer this
        errors: list[str] = []
    else:
        message = (
            f"I couldn't produce a valid query after {state.get('retries', 0)} attempt(s). "
            "Try rephrasing, or name the tables and columns you're interested in."
        )
        errors = list(dict.fromkeys(state.get("error_history") or state.get("errors") or []))
    return {
        "response": {
            "type": "error", "intent": state.get("intent"), "message": message,
            "errors": errors, "last_attempt": state.get("sql"),
        },
        "messages": [AIMessage(content=message)],
    }


# --- routing (conditional edges) -------------------------------------------------------
def route_after_preflight(state: AgentState) -> str:
    return "refuse" if state.get("forced_intent") in ("injection", "out_of_scope") else "detect_intent"


def route_by_intent(state: AgentState) -> str:
    intent = state["intent"]
    if intent in ("out_of_scope", "destructive"):
        return "refuse"
    if intent == "clarify":
        return "clarify"
    return "load_schema"


def route_by_task(state: AgentState) -> str:
    return {
        "optimize": "optimize_sql",
        "debug": "debug_sql",
        "explain": "validate_sql",
    }.get(state["intent"], "generate_sql")


def route_after_generation(state: AgentState) -> str:
    return "validate_sql" if state.get("sql") else "fail"


def route_after_validation(state: AgentState) -> str:
    if not state.get("errors"):
        return "analyze_query"
    if state.get("intent") == "debug" and not state.get("debug"):
        return "debug_sql"   # an "explain" request turned out to be broken SQL
    if (state.get("retries") or 0) < get_settings().max_retries:
        return "generate_sql"
    return "fail"


def route_after_analysis(state: AgentState) -> str:
    return "execute_query" if state.get("execute", True) else "explain"

