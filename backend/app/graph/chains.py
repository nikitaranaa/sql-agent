"""Every LLM call the agent makes. Each returns a validated Pydantic object.

Graph nodes call these functions through the module (``chains.generate_sql(...)``) so
tests can monkeypatch them and run the whole graph without an API key.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from app import prompts
from app.config import get_settings
from app.llm import get_chat_model
from app.validation.guards import wrap_user_text

logger = logging.getLogger(__name__)

Intent = Literal[
    "generate", "followup", "optimize", "debug", "explain", "clarify", "destructive", "out_of_scope"
]


# --- Structured outputs ----------------------------------------------------------
class IntentResult(BaseModel):
    intent: Intent
    needs_clarification: bool = Field(False, description="True when intent is clarify")
    clarification_question: str = Field("", description="One short question, only for clarify")
    clarification_options: list[str] = Field(
        default_factory=list,
        description="For clarify: 2-3 complete, specific rewordings of the request the user can pick, "
                    "each answerable on its own (e.g. 'Top 5 products by total revenue')",
    )
    safe_alternative: str = Field(
        "", description="For destructive: a read-only question the user could ask instead"
    )
    reasoning: str = Field("", description="One sentence on why this intent was chosen")


class SQLResult(BaseModel):
    sql: str = Field(description="A single read-only SQLite SELECT statement, or '' if impossible")
    notes: str = Field("", description="Assumptions made, or why the request cannot be answered")


class IndexSuggestion(BaseModel):
    statement: str = Field(description="CREATE INDEX statement (recommendation only)")
    reason: str


class OptimizeResult(BaseModel):
    optimized_sql: str
    changes: list[str] = Field(description="Each readability/performance change made, one line each")
    removed_joins: list[str] = Field(default_factory=list, description="Joins removed and why")
    index_recommendations: list[IndexSuggestion] = Field(default_factory=list)


class DebugIssue(BaseModel):
    problem: str = Field(description="What is wrong, e.g. 'Column HireDt does not exist'")
    why: str = Field(description="Why it is incorrect")
    fix: str = Field(description="What was changed")


class DebugResult(BaseModel):
    issues: list[DebugIssue]
    corrected_sql: str


class ExplanationResult(BaseModel):
    summary: str = Field(description="One sentence: what the query returns")
    details: list[str] = Field(default_factory=list, description="2-5 short plain-English bullets")
    follow_ups: list[str] = Field(
        default_factory=list,
        description="2-3 short follow-up questions that refine this query, e.g. 'Only those from California'",
    )


# --- Helpers ----------------------------------------------------------------------
def _call(tier: str, schema_prompt: str, user_prompt: str, output: type[BaseModel]):
    llm = get_chat_model(tier)
    messages = [
        SystemMessage(content=prompts.render("system", schema=schema_prompt)),
        HumanMessage(content=user_prompt),
    ]
    # Groq's open models sometimes answer in prose instead of calling the tool, so prefer
    # JSON-schema mode there and fall back to tool calling if the model rejects it.
    # JSON-schema output occasionally fails on Groq, so it gets a second try.
    if get_settings().llm_provider.lower() == "groq":
        methods = ["json_schema", "json_schema", "function_calling"]
    else:
        methods = ["function_calling"]
    first_exc: Exception | None = None
    for method in methods:
        try:
            if method == "json_schema":
                raw = llm.with_structured_output(output, method=method, include_raw=True).invoke(messages)
                result = raw["parsed"] or _salvage(raw["raw"], output)
            else:
                result = llm.with_structured_output(output, method=method).invoke(messages)
            if result is not None:
                return result
        except Exception as exc:  # malformed output or unsupported method: try the next one
            logger.warning("Structured output (%s) for %s failed: %s", method, output.__name__, exc)
            first_exc = first_exc or exc
    raise first_exc or RuntimeError("The model returned no structured output.")


def _salvage(message, output: type[BaseModel]) -> BaseModel | None:
    """Recover an answer the model wrapped in the schema's own shape.

    Small open models sometimes reply ``{"description": "", "properties": {<answer>}, ...}``
    instead of ``{<answer>}``; the answer is still there, one level down.
    """
    text = getattr(message, "content", "") or ""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    fields = set(output.model_fields)
    for candidate in (data, data.get("properties") if isinstance(data, dict) else None):
        if isinstance(candidate, dict) and fields & set(candidate):
            try:
                return output.model_validate(candidate)
            except ValidationError:
                continue
    return None


def _previous_block(previous_sql: str | None, previous_question: str | None) -> str:
    if not previous_sql:
        return ""
    return (
        "This is a FOLLOW-UP. Modify the previous query to satisfy the new request; keep its "
        "existing filters, joins and columns unless the user asks to change them.\n"
        f"Previous question: {previous_question or '(unknown)'}\n"
        f"Previous query:\n```sql\n{previous_sql}\n```\n"
    )


# --- Chains -------------------------------------------------------------------------
def classify_intent(
    message: str,
    schema_prompt: str,
    previous_question: str | None,
    previous_sql: str | None,
    history: str,
) -> IntentResult:
    prompt = prompts.render(
        "intent",
        message=wrap_user_text(message),
        previous_question=previous_question or "(none)",
        previous_sql=previous_sql or "(none)",
        history=history or "(none)",
    )
    return _call("fast", schema_prompt, prompt, IntentResult)


def generate_sql(
    message: str, schema_prompt: str, previous_sql: str | None = None,
    previous_question: str | None = None,
) -> SQLResult:
    prompt = prompts.render(
        "generate",
        few_shot=prompts.load("few_shot"),
        previous_block=_previous_block(previous_sql, previous_question),
        message=wrap_user_text(message),
    )
    return _call("strong", schema_prompt, prompt, SQLResult)


def repair_sql(message: str, intent: str, sql: str, errors: list[str], schema_prompt: str) -> SQLResult:
    prompt = prompts.render(
        "repair",
        message=wrap_user_text(message),
        intent=intent,
        sql=sql,
        errors="\n".join(f"- {e}" for e in errors),
    )
    return _call("strong", schema_prompt, prompt, SQLResult)


def optimize_sql(message: str, sql: str, plan: list[str], schema_prompt: str) -> OptimizeResult:
    prompt = prompts.render(
        "optimize",
        message=wrap_user_text(message),
        sql=sql,
        plan="\n".join(plan) or "(not available)",
    )
    return _call("strong", schema_prompt, prompt, OptimizeResult)


def debug_sql(message: str, sql: str, errors: list[str], schema_prompt: str) -> DebugResult:
    prompt = prompts.render(
        "debug",
        message=wrap_user_text(message),
        sql=sql,
        errors="\n".join(f"- {e}" for e in errors) or "(none reported)",
    )
    return _call("strong", schema_prompt, prompt, DebugResult)


def explain_sql(
    sql: str, context: str, schema_prompt: str, results_note: str = "",
    on_token: Callable[[str], None] | None = None,
) -> ExplanationResult:
    """Plain-English explanation. With ``on_token`` the text is streamed as it is written.

    Streaming uses a simple line format (summary, bullets, follow-ups) instead of JSON so the
    visible text can be shown while it arrives. If streaming fails or the text can't be
    parsed, it falls back to the structured call.
    """
    if on_token is not None:
        try:
            result = _stream_explanation(sql, context, schema_prompt, results_note, on_token)
            if result is not None:
                return result
        except Exception as exc:
            logger.warning("Streaming explanation failed, falling back: %s", exc)
    prompt = prompts.render("explain", sql=sql, context=context, results_note=results_note)
    return _call("strong", schema_prompt, prompt, ExplanationResult)


FOLLOW_UP_MARKER = "FOLLOW-UPS:"


def _stream_explanation(sql, context, schema_prompt, results_note, on_token) -> ExplanationResult | None:
    messages = [
        SystemMessage(content=prompts.render("system", schema=schema_prompt)),
        HumanMessage(content=prompts.render("explain_stream", sql=sql, context=context,
                                            results_note=results_note)),
    ]
    text, sent = "", 0
    for chunk in get_chat_model("strong").stream(messages):
        piece = chunk.content if isinstance(chunk.content, str) else ""
        if not piece:
            continue
        text += piece
        # Show everything before the follow-up marker. Hold back a marker-sized tail in
        # case the marker is split across chunks.
        cut = text.find(FOLLOW_UP_MARKER)
        visible_end = cut if cut != -1 else max(sent, len(text) - len(FOLLOW_UP_MARKER))
        if visible_end > sent:
            on_token(text[sent:visible_end])
            sent = visible_end
    if FOLLOW_UP_MARKER not in text and len(text) > sent:
        on_token(text[sent:])
    return parse_streamed_explanation(text)


def parse_streamed_explanation(text: str) -> ExplanationResult | None:
    body, _, follow = text.partition(FOLLOW_UP_MARKER)
    lines = [ln.strip() for ln in body.strip().splitlines() if ln.strip()]
    if not lines:
        return None
    bullet = re.compile(r"^[-*•]\s+|^\d+[.)]\s+")
    summary = bullet.sub("", lines[0]).strip("* ")
    details = [bullet.sub("", ln).strip() for ln in lines[1:]]
    follow_ups = [bullet.sub("", ln).strip().strip('"') for ln in follow.splitlines() if ln.strip()]
    return ExplanationResult(summary=summary, details=[d for d in details if d][:6],
                             follow_ups=[f for f in follow_ups if f][:3])
