from datetime import datetime
import pathlib
import re

import pytest

import database.db as db


@pytest.fixture
def user_id(app):
    return db.create_user("Test User", "user@example.com", "password1")


@pytest.fixture
def logged_in(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _add_expenses(owner_id, rows):
    conn = db.get_db()
    try:
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            [(owner_id, *row) for row in rows],
        )
        conn.commit()
    finally:
        conn.close()


SAMPLE_EXPENSES = [
    (250.0, "Food", "2026-10-01", "Groceries"),
    (120.0, "Transport", "2026-10-03", "Metro card recharge"),
    (1800.0, "Bills", "2026-10-05", "Electricity bill"),
    (450.0, "Health", "2026-10-08", "Pharmacy"),
    (600.0, "Entertainment", "2026-10-12", "Movie night"),
    (2200.0, "Shopping", "2026-10-15", "New shoes"),
    (300.0, "Other", "2026-10-18", "Gift"),
    (180.0, "Food", "2026-10-22", "Dinner out"),
]


@pytest.fixture
def expenses(user_id):
    _add_expenses(user_id, SAMPLE_EXPENSES)


def test_profile_redirects_anonymous_to_login(client):
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_profile_redirects_when_session_user_deleted(client, app):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_profile_ok_when_logged_in(client, logged_in):
    assert client.get("/profile").status_code == 200


def test_profile_shows_real_user_identity(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    assert "Test User" in html
    assert "user@example.com" in html
    assert "Member since" in html
    assert ">TU<" in html


def test_profile_has_three_stats(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    for label in ("Total spent", "Transactions", "Top category"):
        assert label in html
    assert re.search(r"₹[\d,]+", html)


def test_profile_transactions_table(client, logged_in, expenses):
    html = client.get("/profile").get_data(as_text=True)
    body = html.split("<tbody>")[1].split("</tbody>")[0]
    assert body.count("<tr>") >= 3
    assert "badge-" in body


def test_profile_breakdown_bar_widths_valid(client, logged_in, expenses):
    html = client.get("/profile").get_data(as_text=True)
    assert html.count("breakdown-fill") >= 3
    widths = [int(w) for w in re.findall(r"breakdown-fill bar-w-(\d+)", html)]
    assert widths
    assert all(w % 5 == 0 and 0 <= w <= 100 for w in widths)


def test_profile_stats_match_expenses(client, logged_in, expenses):
    html = client.get("/profile").get_data(as_text=True)
    assert "₹5,900.00" in html
    assert "Shopping" in html.split("Top category")[1].split("</div>")[0]
    assert db.get_expense_summary(1) == {"total_spent": 5900.0, "count": 8}


def test_profile_transactions_newest_first(client, logged_in, expenses):
    html = client.get("/profile").get_data(as_text=True)
    body = html.split("<tbody>")[1].split("</tbody>")[0]
    labels = re.findall(r"<td>(\d{2} \w{3} \d{4})</td>", body)
    dates = [datetime.strptime(label, "%d %b %Y") for label in labels]
    assert len(dates) == 8
    assert dates == sorted(dates, reverse=True)
    assert labels[0] == "22 Oct 2026"


def test_profile_breakdown_largest_first_with_all_categories(client, logged_in, expenses):
    totals = db.get_category_totals(1)
    assert len(totals) == 7
    assert totals[0]["category"] == "Shopping"
    amounts = [row["total"] for row in totals]
    assert amounts == sorted(amounts, reverse=True)


def test_profile_empty_state_for_user_without_expenses(client, logged_in):
    response = client.get("/profile")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count("No expenses yet.") == 2
    assert "breakdown-fill" not in html
    assert db.get_recent_expenses(1) == []
    assert db.get_expense_summary(1) == {"total_spent": 0, "count": 0}
    assert db.get_category_totals(1) == []


def test_profile_never_shows_other_users_expenses(client, logged_in):
    other_id = db.create_user("Other Person", "other@example.com", "password1")
    _add_expenses(other_id, [(999.0, "Food", "2026-10-02", "Secret lunch")])
    html = client.get("/profile").get_data(as_text=True)
    assert "Secret lunch" not in html
    assert "No expenses yet." in html


def test_profile_has_no_inline_styles_or_hex(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    assert "style=" not in html
    template = pathlib.Path("templates/profile.html").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", template)


def test_navbar_links_username_to_profile(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    assert 'href="/profile" class="nav-user"' in html
