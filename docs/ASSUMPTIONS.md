# Assumptions made during development

## Data and schema
1. **The provided schema had not arrived**, so a representative e-commerce + HR schema was
   created (Customers, Employees, Departments, Orders, OrderItems, Products, Categories) that
   covers every example in the brief (`Employees.HireDate`, `Customers.State`). The agent
   introspects the database at runtime, so the real schema can be dropped in
   ([SCHEMA.md](SCHEMA.md#swapping-in-the-provided-schema)).
2. **SQLite is the execution engine.** It needs no server, ships inside the Docker image and
   supports a true read-only mode. PostgreSQL and MySQL are supported as **output dialects**
   (transpiled with sqlglot); they are not executed.
3. Dates are ISO-8601 text (`'YYYY-MM-DD'`); US states are 2-letter codes. "After January 2024"
   is read as `>= '2024-01-01'`, matching the brief's example.
4. Revenue questions exclude `Cancelled` orders unless the user says otherwise (stated in the prompt).

## Behaviour
5. **Read-only is absolute.** Any request to change data or schema is refused, including
   harmless-sounding ones ("add a test customer"). Index recommendations are text only.
6. **Out of scope** means anything not answerable with SQL against this database. General SQL
   questions ("what is a LEFT JOIN?") and questions about the schema itself count as in scope.
   Writing code in other languages (even code that would run SQL) is out of scope.
7. When a request is ambiguous, the agent asks **one** clarifying question rather than guessing.
8. A follow-up modifies the **last successfully validated** query, not a failed attempt.
9. Results are capped at **100 rows** and **5 seconds**. The SQL shown to the user does not
   include the added `LIMIT` unless they asked for one.
10. JOINs that don't follow a declared foreign key are **warnings**, not errors: valid joins
    (on dates or names) aren't always declared.
11. "Explain" on SQL that fails validation is treated as "debug", because broken SQL can't be
    meaningfully explained.

## Infrastructure
12. Accounts are **optional**: the brief asks for a publicly accessible app, so anyone can use it
    without signing in. Signing in adds conversation sync across devices and per-user limits.
    Requests are rate-limited per user, or per IP when signed out.
13. Without `DATABASE_URL`, the agent's memory is in-process (`MemorySaver`) and resets on restart
    or when the free tier sleeps. The browser then sends its copy of the last valid query, which
    the server re-validates, so follow-ups keep working. With `DATABASE_URL` (Postgres), memory,
    accounts, synced chats and feedback all persist.
14. Any of OpenAI, Anthropic or Groq can be used; the model names in `.env.example` are
    defaults to adjust to your account.
15. Rate-limit counters live in the server's memory, which suits one instance. Running several
    instances would need a shared store such as Redis.
16. "Stop" cancels the request in the browser; the server finishes the work it already started.
