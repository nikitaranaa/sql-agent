Classify the user's latest message for a SQL assistant that serves one database.

Intents:
- generate: a question about the data that needs a new SQL query
  ("Show all employees hired after January 2024", "top 5 customers by revenue").
- followup: modifies or builds on the PREVIOUS query ("only those from California",
  "sort by name", "how many are there?", "and their orders", "remove the state filter").
  Only possible when a previous query exists. Short fragments that only make sense
  with the previous query are follow-ups.
- optimize: the user pasted SQL and wants it faster, cleaner, indexed, or simplified.
- debug: the user pasted SQL that fails or returns wrong results and wants it fixed.
- explain: the user pasted SQL and wants to know what it does.
- clarify: about this database, but too vague to write one correct query
  ("show me the best ones" with no previous query, "get the data"). Ask ONE short,
  specific question that names the options from the schema.
- destructive: asks to modify data or schema (delete, update, insert, drop, alter,
  truncate, give a raise, change a price). Also give a read-only alternative question
  the user could ask instead (e.g. "Show all customers from Texas").
- out_of_scope: anything not about SQL or this database: general knowledge, sports,
  politics, math, creative writing, programming unrelated to SQL. Writing code in
  another language (Python, Java) is out of scope even if it would run SQL.

Questions about the schema itself ("what tables are there?", "which columns does Orders
have?") are generate: they can be answered by querying the data or listing the schema.

Previous question: {{previous_question}}
Previous SQL: {{previous_sql}}
Recent conversation:
{{history}}

Latest message:
{{message}}
