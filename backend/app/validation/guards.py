"""Cheap, deterministic input checks that run before any LLM call.

These are a first layer only. The LLM classifier is the second layer, and the
SQL validator plus the read-only connection are what actually guarantee that
nothing destructive can run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from app.validation.validator import FORBIDDEN_NODES

# --- Destructive requests in plain English -------------------------------------
# Only unambiguous verbs. "remove the filter", "add their orders", "change the sort" are
# follow-ups, so softer verbs are left to the LLM classifier (and the validator).
_DESTRUCTIVE_VERBS = r"(delete|drop|truncate|erase|wipe|purge|destroy)"
_DATA_NOUNS = r"(table|tables|database|db|schema|rows?|records?|data|column|columns|index|entries|customers?|employees?|orders?|products?|categor(?:y|ies)|departments?|items?|salar(?:y|ies)|prices?|users?|everything|all)"
DESTRUCTIVE_PATTERNS = [
    re.compile(rf"^\s*(please\s+|can you\s+|could you\s+|go ahead and\s+|now\s+)?{_DESTRUCTIVE_VERBS}\b.*\b{_DATA_NOUNS}\b", re.I),
    re.compile(r"\b(drop|truncate)\s+(table|database|schema|index|view)\b", re.I),
    re.compile(r"\bdelete\s+from\b", re.I),
    re.compile(r"\binsert\s+into\b", re.I),
    re.compile(r"\bupdate\s+\w+\s+set\b", re.I),
    re.compile(r"\balter\s+table\b", re.I),
    re.compile(r"\b(give|raise|increase|decrease|cut)\b.*\b(salar(y|ies)|prices?)\b.*\bby\b", re.I),
]
# Mentions that mean the user is editing the query, not the data.
_QUERY_EDIT_HINTS = re.compile(r"\b(query|filter|condition|clause|results?|output|sql|sort|limit)\b", re.I)

# --- Prompt injection ------------------------------------------------------------
INJECTION_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"\bignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|your)\s+(instructions|rules|prompts?|directions)",
        r"\bdisregard\s+(all\s+|the\s+|your\s+)?(previous|prior|above|system)",
        r"\bforget\s+(all\s+|your\s+|the\s+)?(previous\s+|prior\s+)?(instructions|rules)",
        r"\b(reveal|show|print|repeat|leak)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions)",
        r"\byou\s+are\s+now\b",
        r"\bact\s+as\s+(a|an)\s+(?!sql)",
        r"\bpretend\s+(to\s+be|you\s+are)\b",
        r"\bdeveloper\s+mode\b|\bjailbreak\b|\bDAN\b",
        r"\bnew\s+instructions\s*:",
        r"</?\s*(system|user_request|instructions)\s*>",
    )
]

# --- Obvious off-topic requests ---------------------------------------------------
OFF_TOPIC_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"\b(fifa|world\s*cup|olympics?|nba|ipl|super\s*bowl|cricket|football|soccer)\b",
        r"\b(president|prime\s+minister|election|politic\w*|senate|parliament)\b",
        r"\b(weather|forecast|horoscope|recipe|movie|song|lyrics)\b",
        r"\b(write|compose)\s+(me\s+)?(a\s+)?(poem|story|essay|song|haiku|joke)\b",
        r"\btell\s+me\s+a\s+joke\b",
        r"\bcapital\s+of\b",
        r"^\s*what\s+is\s+\d+\s*[-+*/x^]\s*\d+",
        r"\b(solve|integrate|differentiate|derivative)\b.*\b(equation|x\^?\d|integral)\b",
    )
]
_SQL_HINTS = re.compile(
    r"\b(sql|query|queries|select|join|table|tables|column|database|schema|index|where|group\s+by|order\s+by)\b",
    re.I,
)

_CODE_FENCE = re.compile(r"```(?:sql)?\s*(.+?)```", re.S | re.I)
_SQL_START = re.compile(
    r"\b(SELECT|WITH|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|PRAGMA|ATTACH)\b", re.I
)


@dataclass
class PreflightResult:
    forced_intent: str | None = None     # "destructive" | "out_of_scope" | "injection" | None
    reason: str = ""
    user_sql: str | None = None          # SQL pasted by the user, if any


def extract_sql(message: str) -> str | None:
    """Pull a SQL statement out of a chat message (code fence or inline)."""
    fenced = _CODE_FENCE.search(message)
    if fenced:
        return fenced.group(1).strip()
    match = _SQL_START.search(message)
    if not match:
        return None
    candidate = message[match.start():].strip()
    # Only treat it as SQL if it parses; "select the best customers" is English.
    try:
        parsed = [s for s in sqlglot.parse(candidate, read="sqlite") if s is not None]
    except Exception:
        # Broken SQL pasted for debugging still counts if it has SQL structure.
        if re.search(r"\b(FROM|SET|INTO|TABLE|WHERE)\b", candidate, re.I):
            return candidate
        return None
    if parsed and not all(isinstance(p, exp.Command) for p in parsed):
        return candidate
    return None


def sql_is_destructive(sql: str) -> bool:
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except Exception:
        return bool(re.match(r"\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE)\b", sql, re.I))
    for stmt in statements:
        if not isinstance(stmt, exp.Query):
            return True
        if any(isinstance(n, FORBIDDEN_NODES) for n in stmt.walk()):
            return True
    return False


def detect_injection(message: str) -> bool:
    return any(p.search(message) for p in INJECTION_PATTERNS)


def detect_destructive_request(message: str, user_sql: str | None) -> bool:
    if user_sql and sql_is_destructive(user_sql):
        return True
    text = message.strip()
    hard = DESTRUCTIVE_PATTERNS[1:]
    if any(p.search(text) for p in hard):
        return True
    # "delete all customers" yes; "drop the state filter from the query" no.
    return bool(DESTRUCTIVE_PATTERNS[0].search(text)) and not _QUERY_EDIT_HINTS.search(text)


def detect_off_topic(message: str, schema_terms: set[str]) -> bool:
    """True only when an off-topic keyword appears AND nothing SQL/schema-related does."""
    if not any(p.search(message) for p in OFF_TOPIC_PATTERNS):
        return False
    if _SQL_HINTS.search(message):
        return False
    words = {w.lower().rstrip("s") for w in re.findall(r"[A-Za-z_]+", message)}
    return not (words & schema_terms)


def preflight(message: str, schema_terms: set[str]) -> PreflightResult:
    user_sql = extract_sql(message)
    if detect_injection(message):
        return PreflightResult("injection", "Prompt-injection pattern detected.", user_sql)
    if detect_destructive_request(message, user_sql):
        return PreflightResult("destructive", "Request would modify or delete data.", user_sql)
    if not user_sql and detect_off_topic(message, schema_terms):
        return PreflightResult("out_of_scope", "Request is not about SQL or this database.", None)
    return PreflightResult(None, "", user_sql)


def wrap_user_text(text: str) -> str:
    """Delimit untrusted user text so the model treats it as data, not instructions."""
    cleaned = re.sub(r"</?\s*user_request\s*>", "", text, flags=re.I)
    return f"<user_request>\n{cleaned}\n</user_request>"
