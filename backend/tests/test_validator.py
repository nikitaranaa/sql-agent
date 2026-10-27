"""One test (or more) per validation check. These are the guardrails that actually matter."""

import pytest

from app.validation.validator import ensure_limit, to_sqlite, transpile, validate_sql

VALID = [
    "SELECT * FROM Employees WHERE HireDate >= '2024-01-01';",
    "SELECT c.FirstName, SUM(o.TotalAmount) AS Revenue FROM Customers AS c "
    "JOIN Orders AS o ON o.CustomerID = c.CustomerID GROUP BY c.CustomerID, c.FirstName "
    "ORDER BY Revenue DESC LIMIT 5",
    "WITH r AS (SELECT CustomerID, SUM(TotalAmount) AS t FROM Orders GROUP BY CustomerID) "
    "SELECT c.FirstName, r.t FROM r JOIN Customers c ON c.CustomerID = r.CustomerID",
    "SELECT * FROM Customers c WHERE EXISTS "
    "(SELECT 1 FROM Orders o WHERE o.CustomerID = c.CustomerID AND o.Status = 'Pending')",
    "SELECT strftime('%Y-%m', OrderDate) AS Month, SUM(TotalAmount) FROM Orders GROUP BY Month",
    "SELECT e.FirstName, m.FirstName AS Manager FROM Employees e "
    "LEFT JOIN Employees m ON m.EmployeeID = e.ManagerID",
    "SELECT x.n FROM (SELECT Name AS n FROM Products) x",
    "SELECT FirstName FROM Employees UNION SELECT FirstName FROM Customers",
    "SELECT Name, ROW_NUMBER() OVER (PARTITION BY CategoryID ORDER BY UnitPrice DESC) AS rn FROM Products",
    "SELECT State, COUNT(*) AS n FROM Customers GROUP BY State HAVING n > 3",
    "select firstname from customers",  # identifiers are case-insensitive in SQLite
]


@pytest.mark.parametrize("sql", VALID)
def test_valid_queries_pass(schema, sql):
    result = validate_sql(sql, schema)
    assert result.ok, result.errors


# --- 1. syntax ------------------------------------------------------------------------------
def test_syntax_error_is_reported(schema):
    result = validate_sql("SELEC * FROM Customers", schema)
    assert not result.ok
    assert "syntax error" in result.errors[0].lower()


def test_empty_sql_is_rejected(schema):
    assert not validate_sql("", schema).ok


# --- 2. single statement --------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE Customers",
    "SELECT * FROM Customers; DELETE FROM Customers",
    "SELECT 1; SELECT 2",
])
def test_stacked_queries_are_blocked(schema, sql):
    result = validate_sql(sql, schema)
    assert not result.ok and result.read_only_violation
    assert "single SELECT" in result.errors[0]


# --- 3. read-only ---------------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "DELETE FROM Customers",
    "UPDATE Customers SET State = 'CA'",
    "INSERT INTO Customers (FirstName) VALUES ('x')",
    "DROP TABLE Customers",
    "ALTER TABLE Customers ADD COLUMN x TEXT",
    "TRUNCATE TABLE Customers",
    "CREATE TABLE t (id INTEGER)",
    "PRAGMA table_info(Customers)",
    "ATTACH DATABASE 'other.db' AS other",
    "REPLACE INTO Customers (CustomerID) VALUES (1)",
    "/* sneaky */ dRoP tAbLe Customers",
    "WITH x AS (SELECT 1) DELETE FROM Customers",
])
def test_write_operations_are_blocked(schema, sql):
    result = validate_sql(sql, schema)
    assert not result.ok
    assert result.read_only_violation


# --- 4. tables ------------------------------------------------------------------------------
def test_unknown_table_suggests_closest(schema):
    result = validate_sql("SELECT * FROM Employes", schema)
    assert result.errors == ["Table 'Employes' does not exist. Did you mean 'Employees'?"]


def test_hallucinated_table_is_rejected(schema):
    assert not validate_sql("SELECT * FROM Invoices", schema).ok


def test_other_database_is_rejected(schema):
    assert not validate_sql("SELECT * FROM main.Customers", schema).ok


# --- 5. columns -----------------------------------------------------------------------------
def test_unknown_column_suggests_closest(schema):
    result = validate_sql("SELECT * FROM Employees WHERE HireDt > '2024-01-01'", schema)
    assert "Did you mean 'HireDate'?" in result.errors[0]


def test_alias_column_is_resolved_to_its_table(schema):
    result = validate_sql("SELECT e.Salry FROM Employees e", schema)
    assert result.errors == ["Column 'Salry' does not exist in 'Employees'. Did you mean 'Salary'?"]


def test_column_from_wrong_table_is_rejected(schema):
    # State lives on Customers, not Orders.
    assert not validate_sql("SELECT o.State FROM Orders o", schema).ok


def test_double_quoted_string_is_caught(schema):
    result = validate_sql('SELECT * FROM Customers WHERE State = "CA"', schema)
    assert not result.ok
    assert "single quotes" in result.errors[0]


def test_cte_columns_are_checked(schema):
    sql = "WITH r AS (SELECT CustomerID AS cid FROM Orders) SELECT r.nope FROM r"
    assert not validate_sql(sql, schema).ok


# --- 6. joins -------------------------------------------------------------------------------
def test_join_on_foreign_key_has_no_warning(schema):
    sql = "SELECT * FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID"
    assert validate_sql(sql, schema).warnings == []


def test_join_not_on_foreign_key_warns(schema):
    sql = "SELECT * FROM Orders o JOIN Products p ON p.ProductID = o.CustomerID"
    result = validate_sql(sql, schema)
    assert result.ok and "foreign key" in result.warnings[0]


@pytest.mark.parametrize("sql", [
    "SELECT * FROM Orders o JOIN Customers c",
    "SELECT * FROM Orders o, Customers c",
])
def test_missing_join_condition_warns_cross_join(schema, sql):
    assert "cross join" in validate_sql(sql, schema).warnings[0]


def test_comma_join_with_where_condition_is_fine(schema):
    sql = "SELECT * FROM Orders o, Customers c WHERE o.CustomerID = c.CustomerID"
    assert validate_sql(sql, schema).warnings == []


# --- semantic checks ------------------------------------------------------------------------
def test_equals_null_is_an_error(schema):
    result = validate_sql("SELECT * FROM Customers WHERE Phone = NULL", schema)
    assert "IS NULL" in result.errors[0]


def test_missing_group_by_column_warns(schema):
    result = validate_sql("SELECT FirstName, COUNT(*) FROM Customers GROUP BY State", schema)
    assert result.ok and "GROUP BY" in result.warnings[0]


# --- 7. real database compile ---------------------------------------------------------------
def test_sqlite_explain_catches_what_sqlglot_misses(schema):
    result = validate_sql("SELECT no_such_function(1) FROM Customers", schema)
    assert not result.ok and "SQLite rejected" in result.errors[0]


# --- helpers --------------------------------------------------------------------------------
def test_ensure_limit_adds_limit_only_when_missing():
    assert ensure_limit("SELECT * FROM Customers", 100).endswith("LIMIT 100")
    assert ensure_limit("SELECT * FROM Customers LIMIT 5", 100).endswith("LIMIT 5")


def test_transpile_to_other_dialects():
    sql = "SELECT * FROM Customers LIMIT 5"
    assert "LIMIT 5" in transpile(sql, "postgres")
    assert "LIMIT 5" in transpile(sql, "mysql")


def test_user_sql_from_other_dialect_is_converted():
    assert "LIMIT 5" in to_sqlite("SELECT TOP 5 * FROM Customers", "tsql")
