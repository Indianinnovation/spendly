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


# ---------------------------------------------------------------- #
# Date filter                                                       #
# ---------------------------------------------------------------- #

def _tbody(html):
    return html.split("<tbody>")[1].split("</tbody>")[0]


def test_profile_no_date_params_shows_all_time(client, logged_in, expenses):
    html = client.get("/profile").get_data(as_text=True)
    assert "₹5,900.00" in html
    assert _tbody(html).count("<tr>") == 8
    assert "filter-label" not in html
    assert "filter-error" not in html


def test_profile_filter_form_rendered(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    assert 'name="start_date"' in html
    assert 'name="end_date"' in html
    assert ">Apply</button>" in html
    for label in ("All Time", "This Month", "Last 3 Months", "Last 6 Months"):
        assert label in html
    assert 'class="filter-pill is-active"' in html
    assert 'href="/profile"' in html


def test_profile_preset_highlights_when_range_matches(client, logged_in):
    from app import _filter_presets
    preset = next(p for p in _filter_presets(None, None) if p["label"] == "This Month")
    html = client.get(
        "/profile", query_string={"start_date": preset["start"], "end_date": preset["end"]}
    ).get_data(as_text=True)
    active = re.findall(r'class="filter-pill is-active"[^>]*>([^<]+)<', html)
    assert active == ["This Month"]


def test_filter_presets_month_math():
    from datetime import date
    from app import _months_back_start
    assert _months_back_start(date(2026, 4, 28), 3) == date(2026, 1, 1)
    assert _months_back_start(date(2026, 2, 10), 3) == date(2025, 11, 1)
    assert _months_back_start(date(2026, 1, 31), 6) == date(2025, 7, 1)


def test_profile_start_date_only(client, logged_in, expenses):
    html = client.get("/profile?start_date=2026-10-15").get_data(as_text=True)
    assert "New shoes" in html
    assert "Dinner out" in html
    assert "Groceries" not in html
    assert "Showing from 15 Oct 2026" in html


def test_profile_end_date_only(client, logged_in, expenses):
    html = client.get("/profile?end_date=2026-10-03").get_data(as_text=True)
    assert "Groceries" in html
    assert "Metro card recharge" in html
    assert "Electricity bill" not in html
    assert "Showing up to 03 Oct 2026" in html


def test_profile_both_bounds_are_inclusive(client, logged_in, expenses):
    html = client.get(
        "/profile?start_date=2026-10-05&end_date=2026-10-15"
    ).get_data(as_text=True)
    assert "Electricity bill" in html
    assert "New shoes" in html
    assert "Metro card recharge" not in html
    assert "Gift" not in html
    assert _tbody(html).count("<tr>") == 4


def test_profile_stats_reflect_range(client, logged_in, expenses):
    html = client.get(
        "/profile?start_date=2026-10-05&end_date=2026-10-15"
    ).get_data(as_text=True)
    assert "₹5,050.00" in html
    assert re.search(r"Transactions</span>\s*<span class=\"stat-value\">4<", html)
    assert re.search(r"Top category</span>\s*<span class=\"stat-value\">Shopping<", html)


def test_profile_breakdown_reflects_range(client, logged_in, expenses):
    html = client.get(
        "/profile?start_date=2026-10-05&end_date=2026-10-15"
    ).get_data(as_text=True)
    assert html.count("breakdown-fill") == 4
    widths = [int(w) for w in re.findall(r"bar-w-(\d+)", html)]
    assert widths and all(w % 5 == 0 and 0 <= w <= 100 for w in widths)
    assert max(widths) == round(2200 / 5050 * 100 / 5) * 5


def test_profile_transactions_in_range_newest_first(client, logged_in, expenses):
    html = client.get(
        "/profile?start_date=2026-10-05&end_date=2026-10-15"
    ).get_data(as_text=True)
    dates = re.findall(r"\d{2} \w{3} 2026", _tbody(html))
    parsed = [datetime.strptime(d, "%d %b %Y") for d in dates]
    assert parsed == sorted(parsed, reverse=True)


def test_profile_inputs_prefilled_with_active_range(client, logged_in, expenses):
    html = client.get(
        "/profile?start_date=2026-10-05&end_date=2026-10-15"
    ).get_data(as_text=True)
    assert 'value="2026-10-05"' in html
    assert 'value="2026-10-15"' in html


def test_profile_empty_range(client, logged_in, expenses):
    html = client.get(
        "/profile?start_date=2027-01-01&end_date=2027-01-31"
    ).get_data(as_text=True)
    assert "₹0.00" in html
    assert "No transactions in this range." in html
    assert "No expenses in this range." in html
    assert "filter-error" not in html
    assert "breakdown-fill" not in html


def test_profile_invalid_date_shows_error(client, logged_in, expenses):
    response = client.get("/profile?start_date=abc")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "filter-error" in html
    assert "₹5,900.00" in html


def test_profile_invalid_bound_keeps_valid_bound(client, logged_in, expenses):
    html = client.get(
        "/profile?start_date=abc&end_date=2026-10-03"
    ).get_data(as_text=True)
    assert "filter-error" in html
    assert "Groceries" in html
    assert "Electricity bill" not in html


def test_profile_start_after_end_falls_back_to_unfiltered(client, logged_in, expenses):
    response = client.get("/profile?start_date=2026-10-20&end_date=2026-10-01")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "filter-error" in html
    assert "₹5,900.00" in html
    assert "filter-label" not in html


@pytest.mark.parametrize("payload", ["' OR '1'='1", "2026-10-01'; DROP TABLE expenses;--"])
def test_profile_sql_injection_value_rejected(client, logged_in, expenses, payload):
    response = client.get("/profile", query_string={"start_date": payload})
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "filter-error" in html
    assert db.get_expense_summary(1)["count"] == 8


def test_profile_filter_never_shows_other_users_expenses(client, logged_in, expenses):
    other_id = db.create_user("Other Person", "other@example.com", "password1")
    _add_expenses(other_id, [(999.0, "Food", "2026-10-10", "Secret lunch")])
    html = client.get(
        "/profile?start_date=2026-10-01&end_date=2026-10-31"
    ).get_data(as_text=True)
    assert "Secret lunch" not in html


def test_profile_filter_requires_login(client):
    response = client.get("/profile?start_date=2026-10-01")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_db_helpers_accept_date_range(user_id, expenses):
    assert db.get_expense_summary(1, "2026-10-05", "2026-10-15") == {
        "total_spent": 5050.0,
        "count": 4,
    }
    assert db.get_expense_summary(1, end_date="2026-10-01")["count"] == 1
    assert len(db.get_recent_expenses(1, 10, "2026-10-12", None)) == 4
    totals = db.get_category_totals(1, "2026-10-05", "2026-10-15")
    assert [row["category"] for row in totals] == [
        "Shopping", "Bills", "Entertainment", "Health",
    ]
