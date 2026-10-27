"""API request / response models (Pydantic). They also drive the OpenAPI docs at /docs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Dialect = Literal["sqlite", "postgres", "mysql"]
ResponseType = Literal["sql", "refusal", "clarification", "error"]


class ChatRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$", description="UUID created by the frontend")
    message: str = Field(min_length=1, max_length=4000)
    dialect: Dialect = "sqlite"
    execute: bool = Field(True, description="Run the validated query against the sample database")
    # The browser's copy of the last successful query. Used only when the server has no memory
    # of this session (e.g. after a restart), and re-validated before use.
    previous_sql: str | None = Field(None, max_length=10000)
    previous_question: str | None = Field(None, max_length=4000)


class Explanation(BaseModel):
    summary: str = ""
    details: list[str] = []


class Results(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float


class ChatResponse(BaseModel):
    type: ResponseType
    intent: str | None = None
    message: str = ""
    sql: str | None = None
    sql_sqlite: str | None = None
    dialect: Dialect = "sqlite"
    explanation: Explanation | None = None
    results: Results | None = None
    execution_error: str | None = None
    warnings: list[str] = []
    errors: list[str] = []
    notes: str = ""
    cost: dict[str, Any] | None = None
    optimization: dict[str, Any] | None = None
    debug: dict[str, Any] | None = None
    retries: int = 0
    tables: list[str] = []
    steps: list[str] = []
    last_attempt: str | None = None
    options: list[str] = []          # clickable answers to a clarifying question
    follow_ups: list[str] = []       # suggested next questions
    based_on: str | None = None      # the question a follow-up modified


class RunRequest(BaseModel):
    """SQL the user edited in the panel. Validated exactly like generated SQL."""
    sql: str = Field(min_length=1, max_length=10000)
    dialect: Dialect = "sqlite"
    question: str | None = Field(None, max_length=4000)
    session_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{8,64}$")


class ExportRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10000, description="Validated SQLite query")


class FeedbackRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    question: str = Field(max_length=4000)
    sql: str = Field(max_length=10000)
    rating: Literal["up", "down"]
    comment: str = Field("", max_length=1000)


class AuthRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    token: str
    username: str


class ConversationIn(BaseModel):
    title: str = Field(max_length=200)
    messages: list[Any]


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
