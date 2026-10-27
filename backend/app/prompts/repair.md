Your previous SQL failed validation. Fix it so it satisfies the original request.

Original request:
{{message}}

Task type: {{intent}}

SQL that failed:
```sql
{{sql}}
```

Validator errors (exact):
{{errors}}

Fix every error. Use only tables and columns that exist in the schema; when the error
suggests a name ("Did you mean ..."), check it against the schema and use the correct one.
Return a single read-only SQLite SELECT statement.
