The user pasted a SQL query and wants it optimized. Rewrite it for this SQLite schema.

Do all of the following where they apply:
1. Readability: consistent formatting, meaningful aliases, explicit JOIN ... ON instead of
   comma joins, CTEs (WITH) for nested logic, named columns instead of SELECT *.
2. Performance: avoid functions on indexed columns in WHERE (sargable predicates), replace
   correlated subqueries with joins/aggregates when equivalent, use EXISTS instead of
   IN (subquery) or COUNT(*) > 0, remove redundant DISTINCT / ORDER BY in subqueries.
3. Remove unnecessary joins: a joined table whose columns are never used and that cannot
   change the row set (e.g. a join to the parent side of a NOT NULL foreign key).
4. Indexes: recommend CREATE INDEX statements for columns used in WHERE, JOIN and
   ORDER BY that are not already indexed. Recommendations are text only; never put them
   in optimized_sql.

The optimized query MUST return the same rows as the original. If a change would alter
results, mention it in "changes" instead of applying it.

Query plan of the ORIGINAL query (from EXPLAIN QUERY PLAN):
{{plan}}

User request:
{{message}}

Original SQL:
```sql
{{sql}}
```
