import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.db as db  # noqa: E402

# app.py runs init_db()/seed_db() on import, so point it at a throwaway DB
# before importing it — never touch the real spendly.db.
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "import.db")

from app import app as flask_app  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    flask_app.config.update(TESTING=True)
    yield flask_app


@pytest.fixture
def user_count():
    def count():
        conn = db.get_db()
        try:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            conn.close()
    return count
