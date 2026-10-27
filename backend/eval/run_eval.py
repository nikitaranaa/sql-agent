"""Measure SQL accuracy against the real LLM (needs an API key in backend/.env).

* Execution accuracy: the agent's query and the gold query return the same rows
  (order-insensitive unless the case says "ordered"; column names are ignored).
* Guardrail accuracy: each attack/ambiguous prompt gets the expected response type.

Usage (from backend/): python -m eval.run_eval
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from app.db.database import execute_readonly
from app.graph.builder import build_graph
from app.graph.state import new_turn_input

HERE = Path(__file__).parent


def _rows(sql: str) -> list[tuple]:
    return [tuple(r) for r in execute_readonly(sql, max_rows=10_000)["rows"]]


def _same(a: list[tuple], b: list[tuple], ordered: bool) -> bool:
    norm = lambda rows: [tuple(round(v, 2) if isinstance(v, float) else v for v in r) for r in rows]
    a, b = norm(a), norm(b)
    return a == b if ordered else Counter(a) == Counter(b)


def ask(graph, question: str) -> dict:
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke(new_turn_input(question, execute=False), config)
    return graph.get_state(config).values["response"]


def main() -> None:
    graph = build_graph(MemorySaver())

    cases = json.loads((HERE / "cases.json").read_text())
    passed = 0
    print("== Execution accuracy ==")
    for case in cases:
        resp = ask(graph, case["question"])
        ok, detail = False, resp.get("type")
        if resp.get("type") == "sql":
            try:
                ok = _same(_rows(resp["sql_sqlite"]), _rows(case["gold_sql"]), case.get("ordered", False))
                detail = resp["sql_sqlite"].replace("\n", " ")
            except Exception as exc:
                detail = f"execution error: {exc}"
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {case['id']}: {detail}")
    print(f"Execution accuracy: {passed}/{len(cases)} = {passed / len(cases):.0%}\n")

    guard_cases = json.loads((HERE / "guardrail_cases.json").read_text())
    g_passed = 0
    print("== Guardrails ==")
    for case in guard_cases:
        resp = ask(graph, case["question"])
        ok = resp.get("type") == case["expect"]
        g_passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] expected {case['expect']:<13} got {resp.get('type'):<13} {case['question']}")
    print(f"Guardrail accuracy: {g_passed}/{len(guard_cases)} = {g_passed / len(guard_cases):.0%}")


if __name__ == "__main__":
    main()
