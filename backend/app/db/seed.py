"""Build the sample SQLite database from schema.sql with deterministic seed data.

Usage (from backend/):
    python -m app.db.seed            # writes app/db/app.db
    python -m app.db.seed --force    # rebuilds even if the file exists
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_DIR = Path(__file__).parent
SCHEMA_PATH = DB_DIR / "schema.sql"
DEFAULT_DB_PATH = DB_DIR / "app.db"

FIRST_NAMES = [
    "Olivia", "Liam", "Emma", "Noah", "Ava", "Elijah", "Sophia", "James", "Isabella", "Lucas",
    "Mia", "Mason", "Amelia", "Ethan", "Harper", "Logan", "Evelyn", "Aiden", "Abigail", "Jackson",
    "Priya", "Arjun", "Mei", "Hiro", "Fatima", "Omar", "Sofia", "Mateo", "Chloe", "Daniel",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
    "Martinez", "Patel", "Nguyen", "Kim", "Chen", "Singh", "Lopez", "Wilson", "Anderson", "Thomas",
    "Taylor", "Moore", "Lee", "Walker", "Hall", "Young",
]
CITIES = [
    ("Los Angeles", "CA"), ("San Francisco", "CA"), ("San Diego", "CA"), ("Sacramento", "CA"),
    ("New York", "NY"), ("Buffalo", "NY"), ("Austin", "TX"), ("Houston", "TX"), ("Dallas", "TX"),
    ("Seattle", "WA"), ("Chicago", "IL"), ("Miami", "FL"), ("Orlando", "FL"), ("Denver", "CO"),
    ("Boston", "MA"), ("Phoenix", "AZ"),
]
DEPARTMENTS = [
    ("Sales", "New York"), ("Engineering", "San Francisco"), ("Marketing", "Austin"),
    ("Support", "Denver"), ("Finance", "Chicago"), ("HR", "Boston"),
]
TITLES = {
    "Sales": ["Sales Representative", "Account Executive", "Sales Manager"],
    "Engineering": ["Software Engineer", "Senior Software Engineer", "Engineering Manager"],
    "Marketing": ["Marketing Specialist", "Marketing Manager"],
    "Support": ["Support Agent", "Support Lead"],
    "Finance": ["Accountant", "Finance Manager"],
    "HR": ["HR Generalist", "HR Manager"],
}
CATEGORIES = [
    ("Electronics", "Phones, laptops and accessories"),
    ("Books", "Printed and digital books"),
    ("Home", "Furniture and home goods"),
    ("Sports", "Sporting goods and outdoor gear"),
    ("Toys", "Toys and games"),
    ("Grocery", "Food and beverages"),
]
PRODUCTS = {
    "Electronics": [("Wireless Mouse", 24.99), ("Mechanical Keyboard", 89.0), ("USB-C Hub", 39.5),
                    ("Noise-Cancelling Headphones", 199.0), ("27-inch Monitor", 279.0),
                    ("Laptop Stand", 45.0)],
    "Books": [("SQL for Humans", 34.0), ("Data Pipelines 101", 42.0), ("The Pragmatic Analyst", 29.5),
              ("Graph Thinking", 38.0), ("Cooking with Data", 25.0)],
    "Home": [("Desk Lamp", 32.0), ("Office Chair", 249.0), ("Standing Desk", 499.0),
             ("Bookshelf", 129.0), ("Plant Pot", 15.0)],
    "Sports": [("Yoga Mat", 28.0), ("Running Shoes", 119.0), ("Water Bottle", 18.0),
               ("Tennis Racket", 149.0), ("Bike Helmet", 59.0)],
    "Toys": [("Puzzle 1000pc", 22.0), ("Building Blocks", 49.0), ("Board Game", 35.0),
             ("RC Car", 79.0)],
    "Grocery": [("Coffee Beans 1kg", 21.0), ("Green Tea", 9.5), ("Dark Chocolate", 6.0),
                ("Olive Oil", 14.0), ("Granola", 7.5)],
}
STATUSES = ["Pending", "Shipped", "Delivered", "Delivered", "Delivered", "Cancelled"]


def _rand_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def build_database(db_path: Path = DEFAULT_DB_PATH, force: bool = False) -> Path:
    """Create the SQLite file from schema.sql and insert deterministic sample rows."""
    db_path = Path(db_path)
    if db_path.exists():
        if not force:
            return db_path
        db_path.unlink()

    rng = random.Random(42)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        cur = conn.cursor()

        # Departments
        for i, (name, loc) in enumerate(DEPARTMENTS, start=1):
            cur.execute("INSERT INTO Departments VALUES (?, ?, ?)", (i, name, loc))

        # Employees: one manager per department first, then reports.
        emp_id = 0
        managers: dict[int, int] = {}
        for dept_id, (dept, _) in enumerate(DEPARTMENTS, start=1):
            emp_id += 1
            fn, ln = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            hire = _rand_date(rng, date(2018, 1, 1), date(2022, 12, 31))
            cur.execute(
                "INSERT INTO Employees VALUES (?,?,?,?,?,?,?,?,?)",
                (emp_id, fn, ln, f"{fn}.{ln}{emp_id}@acme.example".lower(), TITLES[dept][-1],
                 dept_id, None, hire.isoformat(), float(rng.randrange(110_000, 180_000, 1000))),
            )
            managers[dept_id] = emp_id
        for _ in range(26):
            emp_id += 1
            dept_id = rng.randint(1, len(DEPARTMENTS))
            dept = DEPARTMENTS[dept_id - 1][0]
            fn, ln = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            # Roughly a third hired in 2024 or later, so "hired after January 2024" has answers.
            hire = _rand_date(rng, date(2019, 1, 1), date(2026, 6, 30))
            cur.execute(
                "INSERT INTO Employees VALUES (?,?,?,?,?,?,?,?,?)",
                (emp_id, fn, ln, f"{fn}.{ln}{emp_id}@acme.example".lower(),
                 rng.choice(TITLES[dept][:-1]), dept_id, managers[dept_id], hire.isoformat(),
                 float(rng.randrange(55_000, 140_000, 1000))),
            )
        sales_reps = [r[0] for r in cur.execute(
            "SELECT EmployeeID FROM Employees WHERE DepartmentID = 1").fetchall()]

        # Customers
        for cid in range(1, 81):
            fn, ln = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            city, state = rng.choice(CITIES)
            phone = None if rng.random() < 0.15 else f"555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"
            created = _rand_date(rng, date(2021, 1, 1), date(2026, 6, 30))
            cur.execute(
                "INSERT INTO Customers VALUES (?,?,?,?,?,?,?,?,?)",
                (cid, fn, ln, f"{fn}.{ln}{cid}@mail.example".lower(), phone, city, state, "USA",
                 created.isoformat()),
            )

        # Categories and products
        pid = 0
        products: list[tuple[int, float]] = []
        for cat_id, (cat, desc) in enumerate(CATEGORIES, start=1):
            cur.execute("INSERT INTO Categories VALUES (?, ?, ?)", (cat_id, cat, desc))
            for name, price in PRODUCTS[cat]:
                pid += 1
                discontinued = 1 if rng.random() < 0.1 else 0
                cur.execute(
                    "INSERT INTO Products VALUES (?,?,?,?,?,?)",
                    (pid, name, cat_id, price, rng.randint(0, 300), discontinued),
                )
                products.append((pid, price))

        # Orders and order items. The last 3 products and last 5 customers never appear,
        # so "never ordered" / "never purchased" questions have real answers.
        orderable = products[:-3]
        item_id = 0
        for oid in range(1, 501):
            cust = rng.randint(1, 75)
            order_date = _rand_date(rng, date(2023, 1, 1), date(2026, 9, 30))
            status = rng.choice(STATUSES)
            shipped = None
            if status in ("Shipped", "Delivered"):
                shipped = (order_date + timedelta(days=rng.randint(1, 7))).isoformat()
            total = 0.0
            lines = []
            for prod_id, price in rng.sample(orderable, rng.randint(1, 4)):
                item_id += 1
                qty = rng.randint(1, 5)
                discount = rng.choice([0, 0, 0, 0.05, 0.1, 0.15])
                total += qty * price * (1 - discount)
                lines.append((item_id, oid, prod_id, qty, price, discount))
            cur.execute(
                "INSERT INTO Orders VALUES (?,?,?,?,?,?,?)",
                (oid, cust, rng.choice(sales_reps), order_date.isoformat(), shipped, status,
                 round(total, 2)),
            )
            cur.executemany("INSERT INTO OrderItems VALUES (?,?,?,?,?,?)", lines)

        conn.commit()
    finally:
        conn.close()
    return db_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="output SQLite file")
    parser.add_argument("--force", action="store_true", help="rebuild if the file exists")
    args = parser.parse_args()
    path = build_database(Path(args.db), force=args.force)
    print(f"Database ready at {path}")


if __name__ == "__main__":
    main()
