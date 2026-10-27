"""Shared fixtures. Tests never call a real LLM: ``fake_llm`` replaces every chain."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.config import get_settings
from app.db.database import get_schema
from app.db.seed import build_database
from app.graph import chains


@pytest.fixture(scope="session", autouse=True)
def database():
    build_database(get_settings().database_path)
    return get_schema()


@pytest.fixture
def schema(database):
    return database


@dataclass
class FakeLLM:
    """Scripted stand-in for app.graph.chains. Queue answers, then inspect ``calls``."""

    intents: list[chains.IntentResult] = field(default_factory=list)
    sqls: list[str] = field(default_factory=list)          # generate_sql / repair_sql answers
    optimize_result: chains.OptimizeResult | None = None
    debug_result: chains.DebugResult | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def queue_intent(self, intent: str, **kw) -> None:
        self.intents.append(chains.IntentResult(intent=intent, **kw))

    def classify_intent(self, **kw):
        self.calls.append(("classify_intent", kw))
        return self.intents.pop(0) if self.intents else chains.IntentResult(intent="generate")

    def generate_sql(self, **kw):
        self.calls.append(("generate_sql", kw))
        return chains.SQLResult(sql=self.sqls.pop(0) if self.sqls else "")

    def repair_sql(self, **kw):
        self.calls.append(("repair_sql", kw))
        return chains.SQLResult(sql=self.sqls.pop(0) if self.sqls else "")

    def optimize_sql(self, message, sql, plan, schema_prompt):
        self.calls.append(("optimize_sql", {"sql": sql, "plan": plan}))
        return self.optimize_result

    def debug_sql(self, message, sql, errors, schema_prompt):
        self.calls.append(("debug_sql", {"sql": sql, "errors": errors}))
        return self.debug_result

    def explain_sql(self, sql, context, schema_prompt, results_note=""):
        self.calls.append(("explain_sql", {"sql": sql, "context": context}))
        return chains.ExplanationResult(summary=f"Explains: {sql}", details=["detail"])

    def called(self, name: str) -> list[dict[str, Any]]:
        return [kw for n, kw in self.calls if n == name]


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    for name in ("classify_intent", "generate_sql", "repair_sql", "optimize_sql", "debug_sql", "explain_sql"):
        monkeypatch.setattr(chains, name, getattr(fake, name))
    return fake
