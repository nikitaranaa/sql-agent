# Architecture

## System overview

```mermaid
flowchart TB
    subgraph Browser
        UI["React SPA (Vite + Tailwind)<br/>Chat · SQL panel · Explanation · Results · Schema sidebar"]
        LS[(localStorage<br/>conversations, theme, dialect)]
        UI <--> LS
    end

    subgraph Backend["Backend (FastAPI, Docker on Render)"]
        API["main.py<br/>/chat · /chat/stream · /schema · /history · /graph · /health"]
        subgraph Agent["LangGraph agent (graph/)"]
            N["nodes.py<br/>15 nodes + routing functions"]
            CH["chains.py<br/>LLM calls with structured output"]
        end
        PR["prompts/*.md<br/>one prompt per job"]
        VAL["validation/<br/>guards.py (input) · validator.py (SQL AST)"]
        AN["analysis/cost.py<br/>query plan · cost · index advice"]
        DBL["db/database.py<br/>schema introspection · read-only execution"]
        CP[(Checkpointer<br/>MemorySaver / SqliteSaver)]
    end

    LLM[(LLM provider<br/>OpenAI / Anthropic / Groq)]
    DB[("SQLite app.db<br/>opened with mode=ro + query_only")]

    UI -- "HTTPS + SSE" --> API
    API --> N
    N --> CH --> LLM
    CH --> PR
    N --> VAL
    N --> AN
    N --> DBL
    VAL --> DBL
    AN --> DBL
    DBL --> DB
    N <-- "state per thread_id" --> CP
```

## Components

| Component | File(s) | Responsibility |
|---|---|---|
| **Frontend** | `frontend/src` | Chat UI, per-step progress, SQL panel (highlighting, copy, download), explanation, validation and cost insights, results table with CSV export, schema explorer, dark mode, conversation list |
| **API** | `backend/app/main.py` | Request validation (Pydantic), CORS, SSE streaming, error mapping, graph lifecycle |
| **Graph** | `backend/app/graph/builder.py` | Wires nodes and edges, compiles the graph with a checkpointer |
| **Nodes** | `backend/app/graph/nodes.py` | One function per step. All safety decisions live here, in code |
| **Chains** | `backend/app/graph/chains.py` | Every LLM call; returns Pydantic objects via `with_structured_output` |
| **Prompts** | `backend/app/prompts/*.md` | System, intent, generate, few-shot, repair, optimize, debug, explain |
| **Input guards** | `backend/app/validation/guards.py` | Prompt-injection, destructive and off-topic prefilters; SQL extraction |
| **Validator** | `backend/app/validation/validator.py` | sqlglot AST checks + SQLite `EXPLAIN QUERY PLAN`; dialect transpiling |
| **Cost analysis** | `backend/app/analysis/cost.py` | Full scan vs index search, estimated rows read, index recommendations |
| **Database** | `backend/app/db/` | Schema DDL, deterministic seed, read-only connection, timeout and row cap |
| **LLM factory** | `backend/app/llm.py` | Provider switch (OpenAI / Anthropic / Groq), fast vs strong model |

## Request lifecycle (one chat turn)

```mermaid
sequenceDiagram
    autonumber
    participant UI as React UI
    participant API as FastAPI
    participant G as LangGraph
    participant L as LLM
    participant V as Validator
    participant DB as SQLite (read-only)

    UI->>API: POST /chat/stream {session_id, message, dialect, execute}
    API->>G: stream(new_turn_input, thread_id=session_id)
    G->>G: preflight (regex + AST guards)
    G-->>UI: event: step "Checking the request"
    G->>L: classify intent (fast model)
    G->>G: check_scope (code policy overrides LLM)
    G->>G: load_schema (relevant tables, last_sql)
    G->>L: generate SQL (strong model, temp 0, few-shot)
    G->>V: validate (parse, read-only, tables, columns, joins)
    V->>DB: EXPLAIN QUERY PLAN
    alt invalid
        G->>L: repair with the exact errors (≤ 3 attempts)
    end
    G->>DB: EXPLAIN QUERY PLAN → cost + index advice
    G->>DB: execute with LIMIT 100 + timeout
    G->>L: explain in plain English
    G->>G: respond (transpile to dialect, save last_sql)
    API-->>UI: event: result {type, sql, explanation, results, cost, ...}
```

## Key design decisions

1. **Code enforces safety, the LLM only proposes.** The model never touches the database.
   Read-only is guaranteed by three independent layers: AST validation, a `mode=ro`
   connection, and `PRAGMA query_only`.
2. **The graph has explicit nodes for each job**, not one big prompt, so each step can be
   tested, traced and streamed to the UI on its own.
3. **Structured output everywhere.** Each chain returns a Pydantic model (`IntentResult`,
   `SQLResult`, `OptimizeResult`, `DebugResult`, `ExplanationResult`), so there is no
   free-text parsing.
4. **The schema is introspected, not hard-coded.** `load_schema()` reads tables, columns,
   foreign keys, indexes, row counts and sample rows from SQLite, so the provided schema can
   be swapped in without code changes.
5. **Two model tiers.** A cheap model classifies intent; a strong model writes and fixes SQL.
6. **Testable without an API key.** Nodes call `chains.<fn>` through the module, so tests
   replace them with a scripted fake and exercise the real graph, validator and database.
7. **Scaling path.** `select_relevant_tables()` sends the whole schema when it is small
   (≤ 25 tables). Beyond that it retrieves relevant tables plus their foreign-key
   neighbours. Swapping the keyword score for embeddings changes no other code.
