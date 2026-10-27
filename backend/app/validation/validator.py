"""Code-level SQL validation. The LLM is asked to behave; this module enforces it.

Checks, in order (each one is unit-tested in tests/test_validator.py):
  1. Parse with sqlglot (syntax)
  2. Exactly one statement (blocks ``SELECT 1; DROP TABLE x``)
  3. Read-only: root must be a query and no write/DDL/command node anywhere in the AST
  4. Every table exists (with "did you mean" suggestions)
  5. Every column exists in the table it resolves to (aliases, CTEs, subqueries resolved)
  6. JOIN conditions follow declared foreign keys (warning, not error)
  7. SQLite compiles it: ``EXPLAIN QUERY PLAN`` on the real read-only database
"""

from __future__ import annotations

import difflib
import sqlite3
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.db.database import SchemaInfo, explain_query_plan

# Any of these anywhere in the tree means the statement is not read-only.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert", "Update", "Delete", "Drop", "Alter", "Create", "TruncateTable", "Merge",
        "Command", "Pragma", "Attach", "Detach", "Transaction", "Commit", "Rollback", "Set",
        "Use", "Copy", "Analyze", "Grant", "Revoke", "LoadData", "Into",
    )
    if hasattr(exp, name)
)
# Functions that read files or the environment in some SQLite builds.
FORBIDDEN_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}
SQLITE_PSEUDO_COLUMNS = {"rowid", "oid", "_rowid_"}


@dataclass
class ValidationResult:
    sql: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    read_only_violation: bool = False
    tables: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _suggest(name: str, candidates: list[str]) -> str:
    lowered = {c.lower(): c for c in candidates}
    match = difflib.get_close_matches(name.lower(), list(lowered), n=1, cutoff=0.5)
    return f" Did you mean '{lowered[match[0]]}'?" if match else ""


def parse_single(sql: str) -> tuple[exp.Expression | None, list[str]]:
    """Parse SQLite SQL; return (ast, errors). Errors cover syntax and multi-statements."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except ParseError as exc:
        first = exc.errors[0] if exc.errors else {}
        detail = first.get("description") or str(exc).splitlines()[0]
        where = f" (line {first['line']}, col {first['col']})" if first.get("line") else ""
        return None, [f"Syntax error: {detail}{where}."]
    if not statements:
        return None, ["Empty query."]
    if len(statements) > 1:
        return None, [
            f"Found {len(statements)} statements. Only a single SELECT statement is allowed."
        ]
    return statements[0], []


def check_read_only(ast: exp.Expression) -> list[str]:
    errors = []
    if not isinstance(ast, exp.Query):
        kind = ast.key.upper() if isinstance(ast, exp.Expression) else "UNKNOWN"
        errors.append(f"Only read-only SELECT queries are allowed; got a {kind} statement.")
    for node in ast.walk():
        if isinstance(node, FORBIDDEN_NODES):
            errors.append(
                f"Forbidden operation '{node.key.upper()}' found. The assistant is read-only."
            )
            break
    for func in ast.find_all(exp.Anonymous):
        if str(func.this).lower() in FORBIDDEN_FUNCTIONS:
            errors.append(f"Function '{func.this}' is not allowed.")
    return errors


def _cte_names(ast: exp.Expression) -> set[str]:
    return {cte.alias_or_name.lower() for cte in ast.find_all(exp.CTE)}


def check_tables(ast: exp.Expression, schema: SchemaInfo) -> tuple[list[str], list[str]]:
    errors, used = [], []
    ctes = _cte_names(ast)
    real = list(schema.tables)
    for table in ast.find_all(exp.Table):
        name = table.name
        if not name or name.lower() in ctes:
            continue
        if table.args.get("db") or table.args.get("catalog"):
            errors.append(f"Table '{table.sql()}' references another database, which is not allowed.")
            continue
        info = schema.table(name)
        if info is None:
            errors.append(f"Table '{name}' does not exist.{_suggest(name, real)}")
        elif info.name not in used:
            used.append(info.name)
    return errors, used


def _scope_chain(scope: Scope):
    while scope is not None:
        yield scope
        scope = scope.parent


def _source_columns(source, schema: SchemaInfo) -> set[str] | None:
    """Output column names of a FROM source, lower-cased. None = unknown (allow anything)."""
    if isinstance(source, exp.Table):
        info = schema.table(source.name)
        return {c.lower() for c in info.column_names} if info else None
    if isinstance(source, Scope):
        expr = source.expression
        selects = getattr(expr, "named_selects", None) or []
        if not selects or "*" in selects or any(isinstance(s, exp.Star) for s in getattr(expr, "selects", [])):
            return None
        return {s.lower() for s in selects}
    return None


def check_columns(ast: exp.Expression, schema: SchemaInfo) -> list[str]:
    errors: list[str] = []
    try:
        scopes = traverse_scope(ast)
    except Exception:
        return errors  # unusual shapes: EXPLAIN QUERY PLAN below is still authoritative

    for scope in scopes:
        select_aliases = set()
        if isinstance(scope.expression, exp.Select):
            select_aliases = {
                s.alias.lower() for s in scope.expression.selects if isinstance(s, exp.Alias)
            }
        for column in scope.columns:
            name = column.name
            if not name or name == "*" or name.lower() in SQLITE_PSEUDO_COLUMNS:
                continue
            lname, qualifier = name.lower(), column.table

            if qualifier:
                source = None
                for s in _scope_chain(scope):
                    source = s.sources.get(qualifier) or next(
                        (v for k, v in s.sources.items() if k.lower() == qualifier.lower()), None
                    )
                    if source is not None:
                        break
                if source is None:
                    if schema.table(qualifier) is None:
                        errors.append(f"Unknown table or alias '{qualifier}' in '{column.sql()}'.")
                    continue
                cols = _source_columns(source, schema)
                if cols is not None and lname not in cols:
                    label = source.name if isinstance(source, exp.Table) else qualifier
                    real = schema.table(label).column_names if schema.table(label) else sorted(cols)
                    errors.append(f"Column '{name}' does not exist in '{label}'.{_suggest(name, real)}")
                continue

            # Unqualified: must exist in some source visible from this scope, or be a select alias.
            if lname in select_aliases:
                continue
            candidates: list[str] = []
            found = unknown_source = False
            for s in _scope_chain(scope):
                for source in s.sources.values():
                    cols = _source_columns(source, schema)
                    if cols is None:
                        unknown_source = True
                    elif lname in cols:
                        found = True
                    else:
                        if isinstance(source, exp.Table) and schema.table(source.name):
                            candidates += schema.table(source.name).column_names
                        else:
                            candidates += sorted(cols)
            if not found and not unknown_source:
                hint = _suggest(name, candidates)
                if not hint and column.this.quoted:
                    hint = " If this is a text value, use single quotes ('...'), not double quotes."
                errors.append(f"Column '{name}' does not exist in the referenced tables.{hint}")
    # Deduplicate, keep order.
    return list(dict.fromkeys(errors))


def check_joins(ast: exp.Expression, schema: SchemaInfo) -> list[str]:
    """Warn when a JOIN is not on a declared foreign key or has no condition at all."""
    warnings: list[str] = []
    fk_pairs = schema.fk_pairs()
    try:
        scopes = traverse_scope(ast)
    except Exception:
        return warnings

    for scope in scopes:
        select = scope.expression
        if not isinstance(select, exp.Select):
            continue
        alias_to_table = {
            alias.lower(): src.name.lower()
            for alias, src in scope.sources.items() if isinstance(src, exp.Table)
        }
        for join in select.args.get("joins") or []:
            on = join.args.get("on")
            if join.args.get("using"):
                continue
            # A bare JOIN parses with ON TRUE; a comma join parses as CROSS with no ON.
            if on is None or isinstance(on, exp.Boolean):
                alias = join.this.alias_or_name.lower()
                where = select.args.get("where")
                linked = where is not None and any(
                    isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Column)
                    and alias in {eq.left.table.lower(), eq.right.table.lower()}
                    for eq in where.find_all(exp.EQ)
                )
                if not linked:
                    warnings.append(
                        f"'{join.this.sql()}' is joined without a join condition: this is a cross "
                        "join and returns every combination of rows."
                    )
                continue
            pairs = []
            for eq in on.find_all(exp.EQ):
                left, right = eq.left, eq.right
                if isinstance(left, exp.Column) and isinstance(right, exp.Column):
                    lt = alias_to_table.get(left.table.lower()) if left.table else None
                    rt = alias_to_table.get(right.table.lower()) if right.table else None
                    if lt and rt:
                        pairs.append(frozenset({(lt, left.name.lower()), (rt, right.name.lower())}))
            if pairs and not any(p in fk_pairs for p in pairs):
                warnings.append(
                    f"JOIN condition '{on.sql(dialect='sqlite')}' does not follow a declared foreign key. "
                    "Double-check that this relationship is intended."
                )
    return warnings


def check_semantics(ast: exp.Expression) -> tuple[list[str], list[str]]:
    """Mistakes SQLite accepts silently: ``= NULL`` (error) and bare columns next to aggregates."""
    errors, warnings = [], []
    for cmp in ast.find_all(exp.EQ, exp.NEQ):
        if isinstance(cmp.right, exp.Null) or isinstance(cmp.left, exp.Null):
            op = "=" if isinstance(cmp, exp.EQ) else "<>"
            fix = "IS NULL" if op == "=" else "IS NOT NULL"
            errors.append(
                f"'{cmp.sql(dialect='sqlite')}' is never true because NULL is not equal to anything. "
                f"Use {fix} instead of {op} NULL."
            )

    for select in ast.find_all(exp.Select):
        projections = [p.unalias() if isinstance(p, exp.Alias) else p for p in select.selects]
        has_agg = any(p.find(exp.AggFunc) and not p.find(exp.Window) for p in projections)
        group = select.args.get("group")
        if not has_agg and not group:
            continue
        group_exprs = group.expressions if group else []
        grouped = {g.sql(dialect="sqlite").lower() for g in group_exprs}
        grouped_names = {g.name.lower() for g in group_exprs if isinstance(g, exp.Column)}
        aliases = {p.alias.lower() for p in select.selects if isinstance(p, exp.Alias)}
        for raw, proj in zip(select.selects, projections):
            if proj.find(exp.AggFunc) or proj.find(exp.Window) or isinstance(proj, (exp.Literal, exp.Star)):
                continue
            if proj.sql(dialect="sqlite").lower() in grouped:
                continue
            if isinstance(raw, exp.Alias) and raw.alias.lower() in grouped_names:
                continue  # GROUP BY Month, where Month is this projection's alias
            for col in proj.find_all(exp.Column):
                if col.sql(dialect="sqlite").lower() in grouped or col.name.lower() in grouped_names:
                    continue
                if col.name.lower() in aliases and not col.table:
                    continue
                warnings.append(
                    f"Column '{col.sql(dialect='sqlite')}' is selected but is neither aggregated nor in "
                    "GROUP BY, so SQLite returns an arbitrary value from each group."
                )
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


def validate_sql(sql: str, schema: SchemaInfo, db_path=None, check_db: bool = True) -> ValidationResult:
    """Run every check and collect errors (block) and warnings (inform)."""
    result = ValidationResult(sql=(sql or "").strip())
    if not result.sql:
        result.errors.append("No SQL was produced.")
        return result

    ast, errors = parse_single(result.sql)
    if errors:
        result.read_only_violation = any("statements" in e for e in errors)
        if check_db and not result.read_only_violation:
            # SQLite's own wording ('near "SELEC": syntax error') is clearer than sqlglot's.
            try:
                explain_query_plan(result.sql, db_path)
            except sqlite3.Error as exc:
                errors = [f"Syntax error: {exc}."]
        result.errors += errors
        return result

    ro_errors = check_read_only(ast)
    if ro_errors:
        result.errors += ro_errors
        result.read_only_violation = True
        return result

    table_errors, result.tables = check_tables(ast, schema)
    result.errors += table_errors
    if not table_errors:
        result.errors += check_columns(ast, schema)
        result.warnings += check_joins(ast, schema)
        sem_errors, sem_warnings = check_semantics(ast)
        result.errors += sem_errors
        result.warnings += sem_warnings

    if not result.errors and check_db:
        try:
            explain_query_plan(result.sql, db_path)
        except sqlite3.Error as exc:
            msg = str(exc)
            if msg.startswith("no such column: "):
                col = msg.split(": ", 1)[1].split(".")[-1]
                all_cols = [c for t in schema.tables.values() for c in t.column_names]
                msg += "." + _suggest(col, all_cols)
            result.errors.append(f"SQLite rejected the query: {msg}")
    return result


def ensure_limit(sql: str, max_rows: int) -> str:
    """Add ``LIMIT max_rows`` to the outermost query when it has none."""
    ast, errors = parse_single(sql)
    if errors or not isinstance(ast, exp.Query):
        return sql
    if ast.args.get("limit") is not None:
        return sql
    return ast.limit(max_rows).sql(dialect="sqlite")


def transpile(sql: str, dialect: str) -> str:
    """Render validated SQLite SQL in another dialect (postgres, mysql, ...)."""
    if not dialect or dialect == "sqlite":
        return format_sql(sql)
    try:
        return sqlglot.transpile(sql, read="sqlite", write=dialect, pretty=True)[0]
    except Exception:
        return sql


def to_sqlite(sql: str, dialect: str) -> str:
    """Convert user-pasted SQL from their dialect to SQLite before validation."""
    if not dialect or dialect == "sqlite":
        return sql
    try:
        return sqlglot.transpile(sql, read=dialect, write="sqlite")[0]
    except Exception:
        return sql


def format_sql(sql: str) -> str:
    try:
        return sqlglot.transpile(sql, read="sqlite", write="sqlite", pretty=True)[0]
    except Exception:
        return sql
