Write ONE SQLite SELECT query that answers the user's request.

Guidelines:
- Use only tables and columns from the schema. Join on the declared foreign keys.
- Select the columns the user asked for; use SELECT * only when they ask for "all" rows of
  a single table.
- Use explicit JOIN ... ON, table aliases for multi-table queries, and readable formatting.
- Exclude 'Cancelled' orders from revenue/sales totals unless the user asks otherwise.
- Use IS NULL / IS NOT NULL, never = NULL.
- Add ORDER BY when the user asks for top/bottom/latest; add LIMIT n only when the user
  asks for a specific number of rows.
- If the request cannot be answered from this schema, set sql to an empty string and say
  why in "notes".

{{few_shot}}

{{previous_block}}
User request:
{{message}}
