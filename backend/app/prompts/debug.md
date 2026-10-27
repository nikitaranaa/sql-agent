The user pasted a SQL query that has errors. Find every problem, explain it, and return
a corrected query for this SQLite schema.

Look for, among others:
- misspelled or non-existent table / column names (compare with the schema)
- non-aggregated columns missing from GROUP BY
- = NULL or <> NULL instead of IS NULL / IS NOT NULL
- missing JOIN conditions (accidental cross join)
- string literals without quotes, or in double quotes
- WHERE used to filter aggregates (should be HAVING)
- wrong date format comparisons (dates are 'YYYY-MM-DD' text)
- dialect mistakes (TOP, ILIKE, NOW(), :: casts are not SQLite)

Errors reported by the validator / SQLite (may be empty if it parses but is logically wrong):
{{errors}}

User request:
{{message}}

SQL to debug:
```sql
{{sql}}
```
