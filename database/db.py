import os
import sqlite3
from datetime import date

from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "spendly.db",
)

CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]

DEBT_TYPES = [
    "Credit Card",
    "Personal Loan",
    "Car Loan",
    "Education Loan",
    "Home Loan",
    "Other",
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at    TEXT DEFAULT (datetime('now'))
            )
            """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                amount      REAL NOT NULL,
                category    TEXT NOT NULL,
                date        TEXT NOT NULL,
                description TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
            """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS debts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL REFERENCES users(id),
                name             TEXT NOT NULL,
                debt_type        TEXT NOT NULL,
                original_balance REAL NOT NULL,
                balance          REAL NOT NULL,
                apr              REAL NOT NULL,
                min_payment      REAL NOT NULL,
                due_day          INTEGER,
                priority         INTEGER,
                created_at       TEXT DEFAULT (datetime('now'))
            )
            """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS debt_payments (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                debt_id    INTEGER NOT NULL REFERENCES debts(id) ON DELETE CASCADE,
                user_id    INTEGER NOT NULL REFERENCES users(id),
                amount     REAL NOT NULL,
                paid_on    TEXT NOT NULL,
                note       TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS debt_settings (
                user_id       INTEGER PRIMARY KEY REFERENCES users(id),
                extra_payment REAL NOT NULL DEFAULT 0,
                strategy      TEXT NOT NULL DEFAULT 'avalanche'
            )
            """)
        conn.commit()
    finally:
        conn.close()


def create_user(name, email, password):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()


def create_expense(user_id, amount, category, expense_date, description):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, expense_date, description),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_expense(expense_id, user_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, amount, category, date, description FROM expenses "
            "WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def update_expense(expense_id, user_id, amount, category, expense_date, description):
    conn = get_db()
    try:
        cursor = conn.execute(
            "UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? "
            "WHERE id = ? AND user_id = ?",
            (amount, category, expense_date, description, expense_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_expense(expense_id, user_id):
    conn = get_db()
    try:
        cursor = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


DEBT_COLUMNS = (
    "id, name, debt_type, original_balance, balance, apr, min_payment, "
    "due_day, priority"
)


def create_debt(
    user_id, name, debt_type, balance, apr, min_payment, due_day, priority
):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO debts (user_id, name, debt_type, original_balance, balance, "
            "apr, min_payment, due_day, priority) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, debt_type, balance, balance, apr, min_payment, due_day,
             priority),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_debts(user_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT " + DEBT_COLUMNS + " FROM debts WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def count_debts(user_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM debts WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def get_debt(debt_id, user_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT " + DEBT_COLUMNS + " FROM debts WHERE id = ? AND user_id = ?",
            (debt_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def update_debt(
    debt_id, user_id, name, debt_type, balance, apr, min_payment, due_day, priority
):
    conn = get_db()
    try:
        # Raising the balance above the original also raises the original,
        # so progress never goes negative.
        cursor = conn.execute(
            "UPDATE debts SET name = ?, debt_type = ?, balance = ?, "
            "original_balance = MAX(original_balance, ?), apr = ?, min_payment = ?, "
            "due_day = ?, priority = ? WHERE id = ? AND user_id = ?",
            (name, debt_type, balance, balance, apr, min_payment, due_day, priority,
             debt_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_debt(debt_id, user_id):
    conn = get_db()
    try:
        cursor = conn.execute(
            "DELETE FROM debts WHERE id = ? AND user_id = ?",
            (debt_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_debt_settings(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT extra_payment, strategy FROM debt_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"extra_payment": 0.0, "strategy": "avalanche"}
    return {"extra_payment": row["extra_payment"], "strategy": row["strategy"]}


def save_debt_settings(user_id, extra_payment, strategy):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO debt_settings (user_id, extra_payment, strategy) "
            "VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
            "extra_payment = excluded.extra_payment, strategy = excluded.strategy",
            (user_id, extra_payment, strategy),
        )
        conn.commit()
    finally:
        conn.close()


def _date_clause(user_id, start_date, end_date):
    where = "WHERE user_id = ?"
    params = [user_id]
    if start_date:
        where += " AND date >= ?"
        params.append(start_date)
    if end_date:
        where += " AND date <= ?"
        params.append(end_date)
    return where, params


def get_recent_expenses(user_id, limit=10, start_date=None, end_date=None):
    where, params = _date_clause(user_id, start_date, end_date)
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, amount, category, date, description FROM expenses "
            + where
            + " ORDER BY date DESC, id DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    finally:
        conn.close()


def get_expense_summary(user_id, start_date=None, end_date=None):
    where, params = _date_clause(user_id, start_date, end_date)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_spent, COUNT(*) AS count "
            "FROM expenses " + where,
            params,
        ).fetchone()
        return {"total_spent": row["total_spent"], "count": row["count"]}
    finally:
        conn.close()


def get_category_totals(user_id, start_date=None, end_date=None):
    where, params = _date_clause(user_id, start_date, end_date)
    conn = get_db()
    try:
        return conn.execute(
            "SELECT category, SUM(amount) AS total FROM expenses "
            + where
            + " GROUP BY category ORDER BY total DESC, category",
            params,
        ).fetchall()
    finally:
        conn.close()


def get_monthly_totals(user_id, start_date=None, end_date=None):
    where, params = _date_clause(user_id, start_date, end_date)
    conn = get_db()
    try:
        return conn.execute(
            "SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS total "
            "FROM expenses " + where + " GROUP BY month ORDER BY month",
            params,
        ).fetchall()
    finally:
        conn.close()


def get_top_expenses(user_id, limit=5, start_date=None, end_date=None):
    where, params = _date_clause(user_id, start_date, end_date)
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, amount, category, date, description FROM expenses "
            + where
            + " ORDER BY amount DESC, date DESC, id DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    finally:
        conn.close()


def seed_db():
    conn = get_db()
    try:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return

        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
        )
        user_id = cursor.lastrowid

        today = date.today()
        samples = [
            (250.0, "Food", 1, "Groceries"),
            (120.0, "Transport", 3, "Metro card recharge"),
            (1800.0, "Bills", 5, "Electricity bill"),
            (450.0, "Health", 8, "Pharmacy"),
            (600.0, "Entertainment", 12, "Movie night"),
            (2200.0, "Shopping", 15, "New shoes"),
            (300.0, "Other", 18, "Gift"),
            (180.0, "Food", 22, "Dinner out"),
        ]
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (user_id, amount, category, today.replace(day=day).isoformat(), desc)
                for amount, category, day, desc in samples
            ],
        )
        conn.commit()
    finally:
        conn.close()
