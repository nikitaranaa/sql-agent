"""Query cost estimation and index recommendations, computed in code (no LLM).

SQLite's ``EXPLAIN QUERY PLAN`` says, per table, whether it will SCAN (read every
row) or SEARCH (seek through an index). Combined with table row counts that gives
a cheap, explainable cost estimate. Index recommendations come from columns the
query filters, joins or sorts on, for tables that are scanned and lack an index
on that column.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

from sqlglot import exp

from app.db.database import SchemaInfo, explain_query_plan
from app.validation.validator import parse_single

_PLAN_TABLE = re.compile(r"^(SCAN|SEARCH)\s+(?:TABLE\s+)?(\w+)(?:\s+AS\s+(\w+))?", re.I)


@dataclass
class IndexRecommendation:
    table: str
    columns: list[str]
    reason: str
    statement: str


@dataclass
class CostEstimate:
    plan: list[str] = field(default_factory=list)
    full_scans: list[str] = field(default_factory=list)
    index_searches: list[str] = field(default_factory=list)
    estimated_rows_read: int = 0
    uses_temp_btree: bool = False
    level: str = "low"  # low | medium | high
    summary: str = ""
    index_recommendations: list[IndexRecommendation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _indexed_leading_columns(schema: SchemaInfo, table: str) -> set[str]:
    info = schema.table(table)
    if not info:
        return set()
    leading = {idx["columns"][0].lower() for idx in info.indexes if idx["columns"]}
    leading |= {c["name"].lower() for c in info.columns if c["pk"]}
    return leading


def _candidate_columns(ast: exp.Expression, schema: SchemaInfo) -> dict[str, dict[str, str]]:
    """table -> {column: reason} for columns used in WHERE / JOIN ON / ORDER BY / GROUP BY."""
    alias_map: dict[str, str] = {}
    for table in ast.find_all(exp.Table):
        info = schema.table(table.name)
        if info:
            alias_map[(table.alias or table.name).lower()] = info.name
            alias_map[info.name.lower()] = info.name
    single_table = len({v for v in alias_map.values()}) == 1

    found: dict[str, dict[str, str]] = {}

    def add(col: exp.Column, reason: str) -> None:
        table = alias_map.get(col.table.lower()) if col.table else None
        if table is None and single_table:
            table = next(iter(alias_map.values()))
        if table is None:  # unqualified in a multi-table query: find the owning table
            owners = [t for t in set(alias_map.values())
                      if col.name.lower() in {c.lower() for c in schema.table(t).column_names}]
            table = owners[0] if len(owners) == 1 else None
        if table and col.name.lower() in {c.lower() for c in schema.table(table).column_names}:
            found.setdefault(table, {}).setdefault(col.name, reason)

    for where in ast.find_all(exp.Where):
        for col in where.find_all(exp.Column):
            add(col, "filtered in WHERE")
    for join in ast.find_all(exp.Join):
        if join.args.get("on"):
            for col in join.args["on"].find_all(exp.Column):
                add(col, "used as a JOIN key")
    for order in ast.find_all(exp.Order):
        for col in order.find_all(exp.Column):
            add(col, "used in ORDER BY")
    for group in ast.find_all(exp.Group):
        for col in group.find_all(exp.Column):
            add(col, "used in GROUP BY")
    return found


def estimate_cost(sql: str, schema: SchemaInfo, db_path=None) -> CostEstimate:
    est = CostEstimate()
    try:
        est.plan = explain_query_plan(sql, db_path)
    except Exception as exc:  # validation already ran; this is best-effort
        est.summary = f"Could not compute a query plan: {exc}"
        return est

    # Newer SQLite prints the alias ("SCAN o"), older prints the table ("SCAN TABLE Orders").
    ast, parse_errors = parse_single(sql)
    alias_to_table: dict[str, str] = {}
    if not parse_errors and ast is not None:
        for table in ast.find_all(exp.Table):
            info = schema.table(table.name)
            if info:
                alias_to_table[(table.alias or table.name).lower()] = info.name
                alias_to_table.setdefault(info.name.lower(), info.name)
    rows = 0
    for line in est.plan:
        if "TEMP B-TREE" in line.upper():
            est.uses_temp_btree = True
        m = _PLAN_TABLE.match(line.strip())
        if not m:
            continue
        op, name = m.group(1).upper(), m.group(2)
        resolved = alias_to_table.get(name.lower()) or alias_to_table.get((m.group(3) or "").lower())
        info = schema.table(resolved or name)
        if not info:
            continue  # CTE / subquery materialisation
        if op == "SCAN" and "COVERING INDEX" not in line.upper():
            est.full_scans.append(info.name)
            rows += info.row_count
        else:
            est.index_searches.append(info.name)
            rows += max(1, int(math.log2(info.row_count + 1)))
    est.estimated_rows_read = rows

    # Nested-loop joins over several scanned tables are the expensive case.
    scanned = len(est.full_scans)
    if rows > 50_000 or scanned >= 3:
        est.level = "high"
    elif rows > 2_000 or scanned == 2 or est.uses_temp_btree:
        est.level = "medium"

    if not parse_errors and ast is not None:
        for table, cols in _candidate_columns(ast, schema).items():
            if table not in est.full_scans:
                continue
            indexed = _indexed_leading_columns(schema, table)
            missing = [(c, r) for c, r in cols.items() if c.lower() not in indexed]
            for col, reason in missing:
                est.index_recommendations.append(IndexRecommendation(
                    table=table,
                    columns=[col],
                    reason=f"{table}.{col} is {reason} but {table} is fully scanned "
                           f"({schema.table(table).row_count} rows).",
                    statement=f"CREATE INDEX idx_{table.lower()}_{col.lower()} ON {table}({col});",
                ))

    parts = []
    if est.full_scans:
        parts.append("full scan of " + ", ".join(dict.fromkeys(est.full_scans)))
    if est.index_searches:
        parts.append("index lookup on " + ", ".join(dict.fromkeys(est.index_searches)))
    if est.uses_temp_btree:
        parts.append("temporary sort/grouping structure")
    est.summary = (
        f"{est.level.capitalize()} cost: ~{est.estimated_rows_read:,} rows read"
        + (f" ({'; '.join(parts)})" if parts else "")
        + "."
    )
    return est
