import pytest

from database import db
from database.db import get_db


@pytest.fixture
def user_id(app):
    return db.create_user("Test User", "user@example.com", "password1")


@pytest.fixture
def logged_in(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return client


def _insert(owner_id, rows):
    conn = get_db()
    try:
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            [(owner_id, *row) for row in rows],
        )
        conn.commit()
    finally:
        conn.close()


def _get(client, **params):
    return client.get("/analytics", query_string=params)


def _html(response):
    return response.get_data(as_text=True)


# ------------------------------------------------------------------ #
# Access                                                              #
# ------------------------------------------------------------------ #


def test_signed_out_redirects_to_login(client):
    for params in ({}, {"start_date": "2026-10-01"}):
        response = _get(client, **params)
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"


def test_navbar_link_only_when_signed_in(client, user_id):
    assert "/analytics" not in _html(client.get("/login"))
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    assert 'href="/analytics"' in _html(client.get("/profile"))


# ------------------------------------------------------------------ #
# Content                                                             #
# ------------------------------------------------------------------ #


def test_empty_state(logged_in):
    response = _get(logged_in)
    html = _html(response)
    assert response.status_code == 200
    assert "No expenses yet." in html
    assert "₹0" in html
    assert "Monthly Trend" not in html
    assert "Largest Expenses" not in html


def test_empty_range_shows_range_message(logged_in, user_id):
    _insert(user_id, [(100, "Food", "2026-01-10", "ZZ-old")])
    html = _html(_get(logged_in, start_date="2026-06-01", end_date="2026-06-30"))
    assert "No expenses in this range." in html
    assert "ZZ-old" not in html


def test_monthly_totals_grouped_and_ordered(logged_in, user_id):
    _insert(
        user_id,
        [
            (300, "Food", "2026-10-05", "a"),
            (100, "Food", "2026-08-05", "b"),
            (50, "Bills", "2026-08-20", "c"),
            (200, "Bills", "2026-09-01", "d"),
        ],
    )
    html = _html(_get(logged_in))
    assert html.index("Aug 2026") < html.index("Sep 2026") < html.index("Oct 2026")
    assert "₹150" in html  # Aug: 100 + 50 grouped


def test_averages_and_busiest_category(logged_in, user_id):
    _insert(
        user_id,
        [
            (100, "Food", "2026-08-05", "a"),
            (300, "Bills", "2026-08-06", "b"),
            (200, "Bills", "2026-09-01", "c"),
            (400, "Bills", "2026-09-02", "d"),
        ],
    )
    html = _html(_get(logged_in))
    assert "₹1,000" in html  # total
    assert "₹250" in html  # 1000 / 4 expenses
    assert "₹500" in html  # 1000 / 2 active months
    assert "Bills" in html


def test_top_expenses_capped_and_ordered(logged_in, user_id):
    _insert(
        user_id,
        [
            (amt, "Food", "2026-10-01", f"ZZ-{amt}")
            for amt in (10, 20, 30, 40, 50, 60, 70)
        ],
    )
    html = _html(_get(logged_in))
    assert "ZZ-70" in html and "ZZ-30" in html
    assert "ZZ-20" not in html and "ZZ-10" not in html
    assert html.index("ZZ-70") < html.index("ZZ-60") < html.index("ZZ-30")
    assert "₹70.00" in html


def test_top_expenses_tie_broken_by_newest_date(logged_in, user_id):
    _insert(
        user_id,
        [
            (500, "Food", "2026-09-01", "ZZ-older"),
            (500, "Food", "2026-10-01", "ZZ-newer"),
        ],
    )
    html = _html(_get(logged_in))
    assert html.index("ZZ-newer") < html.index("ZZ-older")


def test_bar_scaling(logged_in, user_id):
    _insert(
        user_id,
        [
            (10000, "Food", "2026-09-01", "big"),
            (10, "Food", "2026-10-01", "tiny"),
        ],
    )
    html = _html(_get(logged_in))
    assert "bar-w-100" in html
    assert "bar-w-5" in html
    assert "bar-w-0" not in html


# ------------------------------------------------------------------ #
# Filtering                                                           #
# ------------------------------------------------------------------ #


def test_date_filter_inclusive_and_limits_all_sections(logged_in, user_id):
    _insert(
        user_id,
        [
            (111, "Food", "2026-09-30", "ZZ-before"),
            (222, "Food", "2026-10-01", "ZZ-start"),
            (333, "Food", "2026-10-31", "ZZ-end"),
            (444, "Food", "2026-11-01", "ZZ-after"),
        ],
    )
    html = _html(_get(logged_in, start_date="2026-10-01", end_date="2026-10-31"))
    assert "ZZ-start" in html and "ZZ-end" in html
    assert "ZZ-before" not in html and "ZZ-after" not in html
    assert "₹555" in html  # 222 + 333
    assert "Sep 2026" not in html and "Nov 2026" not in html


def test_invalid_date_shows_error(logged_in):
    response = _get(logged_in, start_date="abc")
    assert response.status_code == 200
    assert "YYYY-MM-DD" in _html(response)


def test_reversed_range_shows_error_and_unfiltered_data(logged_in, user_id):
    _insert(user_id, [(100, "Food", "2026-10-05", "ZZ-row")])
    response = _get(logged_in, start_date="2026-11-01", end_date="2026-10-01")
    html = _html(response)
    assert response.status_code == 200
    assert "Start date must be on or before the end date." in html
    assert "ZZ-row" in html


def test_sql_injection_param_is_rejected(logged_in, user_id):
    _insert(user_id, [(100, "Food", "2026-10-05", "ZZ-row")])
    response = _get(logged_in, start_date="' OR 1=1; DROP TABLE expenses; --")
    assert response.status_code == 200
    assert "YYYY-MM-DD" in _html(response)
    conn = get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
    finally:
        conn.close()


def test_presets_link_to_analytics(logged_in):
    html = _html(_get(logged_in))
    assert 'action="/analytics"' in html
    assert "/analytics?start_date=" in html
    assert "/profile?start_date=" not in html


# ------------------------------------------------------------------ #
# Isolation                                                           #
# ------------------------------------------------------------------ #


def test_other_users_data_never_appears(logged_in, user_id):
    other_id = db.create_user("Other User", "other@example.com", "password1")
    _insert(user_id, [(100, "Food", "2026-10-05", "ZZ-mine")])
    _insert(other_id, [(99999, "Bills", "2026-03-05", "ZZ-theirs")])
    html = _html(_get(logged_in))
    assert "ZZ-mine" in html
    assert "ZZ-theirs" not in html
    assert "Mar 2026" not in html
    assert "99,999" not in html
