"""The database layer: read-only connection, limits, timeouts, schema introspection."""

import sqlite3

import pytest

from app.analysis.cost import estimate_cost
from app.db.database import QueryTimeoutError, connect_readonly, execute_readonly


def test_readonly_connection_refuses_writes():
    conn = connect_readonly()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM Customers")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE hacked (id INTEGER)")
    conn.close()


def test_execute_caps_rows():
    result = execute_readonly("SELECT * FROM OrderItems", max_rows=10)
    assert result["row_count"] == 10 and result["truncated"] is True


def test_execute_timeout_stops_runaway_cross_join():
    sql = "SELECT COUNT(*) FROM OrderItems a, OrderItems b, OrderItems c"
    with pytest.raises(QueryTimeoutError):
        execute_readonly(sql, timeout=0.2)


def test_schema_introspection(schema):
    assert {"Customers", "Employees", "Orders", "OrderItems", "Products"} <= set(schema.tables)
    orders = schema.table("orders")  # case-insensitive lookup
    assert any(fk.ref_table == "Customers" for fk in orders.foreign_keys)
    prompt = schema.to_prompt(["Customers"])
    assert "CREATE TABLE Customers" in prompt and "Sample rows" in prompt


def test_cost_estimate_flags_full_scan_and_recommends_index(schema):
    est = estimate_cost("SELECT * FROM Customers WHERE State = 'CA'", schema)
    assert est.full_scans == ["Customers"]
    assert est.index_recommendations[0].statement == \
        "CREATE INDEX idx_customers_state ON Customers(State);"


def test_cost_estimate_primary_key_lookup_is_cheap(schema):
    est = estimate_cost("SELECT * FROM Customers WHERE CustomerID = 3", schema)
    assert est.level == "low" and not est.full_scans and not est.index_recommendations


def test_cost_estimate_does_not_recommend_existing_index(schema):
    est = estimate_cost("SELECT * FROM Employees WHERE DepartmentID = 2", schema)
    assert not est.index_recommendations
