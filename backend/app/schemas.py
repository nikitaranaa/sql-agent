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


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
