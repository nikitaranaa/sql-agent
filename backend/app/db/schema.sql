-- Sample database schema for the SQL Query AI Agent.
-- SQLite dialect. Dates are stored as ISO-8601 text ('YYYY-MM-DD').
-- Replace this file (and seed.py) with the provided schema when it arrives;
-- the agent introspects the database at startup, so no code changes are needed.

CREATE TABLE Departments (
    DepartmentID   INTEGER PRIMARY KEY,
    Name           TEXT    NOT NULL UNIQUE,
    Location       TEXT
);

CREATE TABLE Employees (
    EmployeeID     INTEGER PRIMARY KEY,
    FirstName      TEXT    NOT NULL,
    LastName       TEXT    NOT NULL,
    Email          TEXT    NOT NULL UNIQUE,
    Title          TEXT    NOT NULL,
    DepartmentID   INTEGER NOT NULL REFERENCES Departments(DepartmentID),
    ManagerID      INTEGER REFERENCES Employees(EmployeeID),
    HireDate       TEXT    NOT NULL,          -- 'YYYY-MM-DD'
    Salary         REAL    NOT NULL
);

CREATE TABLE Customers (
    CustomerID     INTEGER PRIMARY KEY,
    FirstName      TEXT    NOT NULL,
    LastName       TEXT    NOT NULL,
    Email          TEXT    NOT NULL UNIQUE,
    Phone          TEXT,
    City           TEXT    NOT NULL,
    State          TEXT    NOT NULL,          -- two-letter US state code, e.g. 'CA'
    Country        TEXT    NOT NULL DEFAULT 'USA',
    CreatedAt      TEXT    NOT NULL           -- 'YYYY-MM-DD'
);

CREATE TABLE Categories (
    CategoryID     INTEGER PRIMARY KEY,
    Name           TEXT    NOT NULL UNIQUE,
    Description    TEXT
);

CREATE TABLE Products (
    ProductID      INTEGER PRIMARY KEY,
    Name           TEXT    NOT NULL,
    CategoryID     INTEGER NOT NULL REFERENCES Categories(CategoryID),
    UnitPrice      REAL    NOT NULL,
    UnitsInStock   INTEGER NOT NULL DEFAULT 0,
    Discontinued   INTEGER NOT NULL DEFAULT 0 -- 0 = active, 1 = discontinued
);

CREATE TABLE Orders (
    OrderID        INTEGER PRIMARY KEY,
    CustomerID     INTEGER NOT NULL REFERENCES Customers(CustomerID),
    EmployeeID     INTEGER REFERENCES Employees(EmployeeID),  -- sales rep
    OrderDate      TEXT    NOT NULL,          -- 'YYYY-MM-DD'
    ShippedDate    TEXT,                      -- NULL until shipped
    Status         TEXT    NOT NULL,          -- 'Pending', 'Shipped', 'Delivered', 'Cancelled'
    TotalAmount    REAL    NOT NULL
);

CREATE TABLE OrderItems (
    OrderItemID    INTEGER PRIMARY KEY,
    OrderID        INTEGER NOT NULL REFERENCES Orders(OrderID),
    ProductID      INTEGER NOT NULL REFERENCES Products(ProductID),
    Quantity       INTEGER NOT NULL,
    UnitPrice      REAL    NOT NULL,
    Discount       REAL    NOT NULL DEFAULT 0  -- fraction, 0.10 = 10%
);

-- Only primary keys are indexed on purpose, so the optimizer has
-- realistic index recommendations to make (e.g. Orders.CustomerID).
CREATE INDEX idx_employees_department ON Employees(DepartmentID);
