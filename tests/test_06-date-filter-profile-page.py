"""Tests for Step 6: date filter on the profile page.

Behaviour under test (from .claude/specs/06-date-filter-profile-page.md):
GET /profile accepts optional ``start_date`` / ``end_date`` (YYYY-MM-DD,
inclusive) query params. Stats, transactions and the category breakdown all
reflect the range. Invalid input -> 200 + error + ignored filter. start > end
-> error + unfiltered view. Always scoped to the signed-in user.
"""
import pathlib
import re

import pytest

import database.db as db

PROFILE_TEMPLATE = pathlib.Path(__file__).resolve().parent.parent / "templates" / "profile.html"

# (amount, category, date, description) -- descriptions are unique markers.
EXPENSES = [
    (100.00, "Food", "2026-09-30", "ZZ-sept-last-day"),
    (200.50, "Food", "2026-10-01", "ZZ-oct-first"),
    (300.00, "Transport", "2026-10-10", "ZZ-oct-mid"),
    (400.00, "Shopping", "2026-10-31", "ZZ-oct-last"),
    (500.00, "Bills", "2026-11-01", "ZZ-nov-first"),
]
ALL_MARKERS = [row[3] for row in EXPENSES]
ALL_TOTAL = "₹1,500.50"
OCT_TOTAL = "₹900.50"  # 200.50 + 300 + 400


# ------------------------------------------------------------------ helpers

def _insert(owner_id, rows):
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


def _snapshot():
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses ORDER BY id"
        ).fetchall()
        return [tuple(r) for r in rows]
    finally:
        conn.close()


def _get(client, **params):
    return client.get("/profile", query_string=params)


def _html(response):
    return response.get_data(as_text=True)


def _error_shown(html):
    """Loose check for a visible error message, independent of markup."""
    return bool(re.search(r"error|invalid|please enter|must be", html, re.I))


def _present(html):
    return [m for m in ALL_MARKERS if m in html]


def _input_tag(html, name):
    for tag in re.findall(r"<input[^>]*>", html, re.I):
        if re.search(r'name="%s"' % name, tag):
            return tag
    return None


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def user_id(app):
    return db.create_user("Test User", "user@example.com", "password1")


@pytest.fixture
def logged_in(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


@pytest.fixture
def expenses(user_id):
    _insert(user_id, EXPENSES)


# ------------------------------------------------------------------ no params

class TestNoParams:
    def test_no_params_returns_200(self, client, logged_in, expenses):
        assert _get(client).status_code == 200

    def test_no_params_shows_all_expenses(self, client, logged_in, expenses):
        html = _html(_get(client))
        assert _present(html) == ALL_MARKERS, "All-time view must list every expense"
        assert ALL_TOTAL in html

    def test_no_params_shows_no_error(self, client, logged_in, expenses):
        assert not _error_shown(_html(_get(client)))

    def test_empty_params_treated_as_no_filter(self, client, logged_in, expenses):
        response = _get(client, start_date="", end_date="")
        html = _html(response)
        assert response.status_code == 200
        assert _present(html) == ALL_MARKERS
        assert not _error_shown(html)

    def test_unknown_params_are_ignored(self, client, logged_in, expenses):
        html = _html(_get(client, foo="bar"))
        assert _present(html) == ALL_MARKERS


# ------------------------------------------------------------------ bounds

class TestDateBounds:
    def test_start_date_only_excludes_earlier(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-10"))
        assert _present(html) == ["ZZ-oct-mid", "ZZ-oct-last", "ZZ-nov-first"]

    def test_end_date_only_excludes_later(self, client, logged_in, expenses):
        html = _html(_get(client, end_date="2026-10-10"))
        assert _present(html) == ["ZZ-sept-last-day", "ZZ-oct-first", "ZZ-oct-mid"]

    def test_both_bounds_only_inside_range(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        assert _present(html) == ["ZZ-oct-first", "ZZ-oct-mid", "ZZ-oct-last"]

    def test_lower_bound_is_inclusive(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-05"))
        assert "ZZ-oct-first" in html

    def test_upper_bound_is_inclusive(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-20", end_date="2026-10-31"))
        assert "ZZ-oct-last" in html

    def test_start_equal_to_end_is_valid_single_day(self, client, logged_in, expenses):
        response = _get(client, start_date="2026-10-01", end_date="2026-10-01")
        html = _html(response)
        assert response.status_code == 200
        assert _present(html) == ["ZZ-oct-first"]
        assert "₹200.50" in html
        assert not _error_shown(html)

    def test_transactions_listed_newest_first(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        positions = [html.index(m) for m in ("ZZ-oct-last", "ZZ-oct-mid", "ZZ-oct-first")]
        assert positions == sorted(positions), "Filtered list must be newest first"


# ------------------------------------------------------------------ stats

class TestFilteredStats:
    def test_total_reflects_range(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        assert OCT_TOTAL in html
        assert ALL_TOTAL not in html

    def test_transaction_count_reflects_range(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        counts = re.findall(r"Transactions[^0-9]{0,80}(\d+)", html)
        assert "3" in counts, "Expected a transaction count of 3 in the stats"

    def test_top_category_reflects_range(self, client, logged_in, expenses):
        unfiltered = _html(_get(client)).split("Top category")[1][:200]
        filtered = _html(
            _get(client, start_date="2026-10-01", end_date="2026-10-31")
        ).split("Top category")[1][:200]
        assert "Bills" in unfiltered
        assert "Shopping" in filtered
        assert "Bills" not in filtered

    def test_amounts_use_rupee_symbol_with_two_decimals(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        assert "₹900.50" in html
        assert "₹400.00" in html
        assert "₹300.00" in html
        assert "₹200.50" in html

    def test_thousands_separator_in_total(self, client, logged_in, expenses):
        assert "₹1,500.50" in _html(_get(client))


# ------------------------------------------------------------------ breakdown

class TestFilteredBreakdown:
    def test_breakdown_excludes_out_of_range_categories(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        body = html.split("By Category")[1]
        assert "Shopping" in body
        assert "Transport" in body
        assert "Food" in body
        assert "Bills" not in body, "Bills only has a November expense"

    def test_bar_widths_scaled_to_filtered_total(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        widths = [int(w) for w in re.findall(r"bar-w-(\d+)", html)]
        # Shopping: 400 / 900.5 = 44.4% -> 45 ; unfiltered would be 400/1500.5 -> 25
        assert 45 in widths, "Expected bar scaled to the filtered total, got %s" % widths
        assert all(w % 5 == 0 and 0 <= w <= 100 for w in widths)

    def test_single_category_range_fills_bar(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-09-30", end_date="2026-09-30"))
        assert 100 in [int(w) for w in re.findall(r"bar-w-(\d+)", html)]


# ------------------------------------------------------------------ empty range

class TestEmptyRange:
    def test_empty_range_returns_200_without_error(self, client, logged_in, expenses):
        response = _get(client, start_date="2027-01-01", end_date="2027-01-31")
        assert response.status_code == 200
        assert not _error_shown(_html(response))

    def test_empty_range_shows_zero_stats(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2027-01-01", end_date="2027-01-31"))
        assert "₹0.00" in html
        assert _present(html) == []
        assert ALL_TOTAL not in html

    def test_empty_range_shows_empty_state_messages(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2027-01-01", end_date="2027-01-31"))
        assert "No transactions in this range." in html
        assert "No expenses in this range." in html

    def test_empty_range_has_no_breakdown_bars(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2027-01-01", end_date="2027-01-31"))
        assert not re.search(r"bar-w-\d+", html)


# ------------------------------------------------------------------ validation

class TestValidation:
    @pytest.mark.parametrize(
        "value",
        ["abc", "2026-13-01", "2026-02-30", "10/01/2026", "2026/10/01", "01-10-2026",
         "2026-10", "yesterday", "x" * 5000],
    )
    @pytest.mark.parametrize("param", ["start_date", "end_date"])
    def test_invalid_date_returns_200_with_error(self, client, logged_in, expenses, param, value):
        response = _get(client, **{param: value})
        assert response.status_code == 200, "Invalid date must not crash"
        assert _error_shown(_html(response))

    def test_invalid_date_shows_error_only_when_invalid(self, client, logged_in, expenses):
        assert not _error_shown(_html(_get(client)))
        assert _error_shown(_html(_get(client, start_date="abc")))

    def test_invalid_start_is_ignored_and_data_still_shown(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="abc"))
        assert _present(html) == ALL_MARKERS
        assert ALL_TOTAL in html

    def test_invalid_start_keeps_valid_end_bound(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="abc", end_date="2026-10-01"))
        assert _error_shown(html)
        assert _present(html) == ["ZZ-sept-last-day", "ZZ-oct-first"]

    def test_invalid_end_keeps_valid_start_bound(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-31", end_date="abc"))
        assert _error_shown(html)
        assert _present(html) == ["ZZ-oct-last", "ZZ-nov-first"]

    def test_start_after_end_shows_error(self, client, logged_in, expenses):
        response = _get(client, start_date="2026-10-31", end_date="2026-10-01")
        assert response.status_code == 200
        assert _error_shown(_html(response))

    def test_start_after_end_falls_back_to_unfiltered(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-31", end_date="2026-10-01"))
        assert _present(html) == ALL_MARKERS
        assert ALL_TOTAL in html


# ------------------------------------------------------------------ injection

INJECTIONS = [
    "' OR '1'='1",
    "2026-10-01'; DROP TABLE expenses;--",
    "2026-10-01' OR '1'='1",
    "1; DELETE FROM expenses",
    "\" OR \"\"=\"",
    "2026-10-01 UNION SELECT * FROM users",
]


class TestInjection:
    @pytest.mark.parametrize("payload", INJECTIONS)
    @pytest.mark.parametrize("param", ["start_date", "end_date"])
    def test_injection_rejected_as_invalid(self, client, logged_in, expenses, param, payload):
        response = _get(client, **{param: payload})
        assert response.status_code == 200
        assert _error_shown(_html(response))

    @pytest.mark.parametrize("payload", INJECTIONS)
    def test_injection_does_not_mutate_or_drop_data(self, client, logged_in, expenses, payload):
        before = _snapshot()
        _get(client, start_date=payload, end_date=payload)
        assert _snapshot() == before, "Expenses table must be untouched"
        conn = db.get_db()
        try:
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            conn.close()
        assert users == 1

    @pytest.mark.parametrize("payload", INJECTIONS)
    def test_injection_does_not_leak_other_users_rows(self, client, logged_in, expenses, payload):
        other = db.create_user("Other", "other@example.com", "password1")
        _insert(other, [(7777.77, "Other", "2026-10-02", "OTHERUSER-SECRET")])
        html = _html(_get(client, start_date=payload))
        assert "OTHERUSER-SECRET" not in html
        assert "7,777.77" not in html

    @pytest.mark.parametrize("payload", INJECTIONS)
    def test_db_helpers_treat_dates_as_data(self, user_id, expenses, payload):
        before = _snapshot()
        db.get_expense_summary(user_id, start_date=payload, end_date=payload)
        db.get_category_totals(user_id, start_date=payload, end_date=payload)
        db.get_recent_expenses(user_id, start_date=payload, end_date=payload)
        assert _snapshot() == before


# ------------------------------------------------------------------ isolation

class TestUserIsolation:
    def test_filter_never_exposes_another_users_expenses(self, client, logged_in, expenses):
        other = db.create_user("Other", "other@example.com", "password1")
        _insert(other, [(7777.77, "Health", "2026-10-10", "OTHERUSER-SECRET")])
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        assert "OTHERUSER-SECRET" not in html
        assert "7,777.77" not in html
        assert OCT_TOTAL in html

    def test_other_users_rows_do_not_affect_unbounded_filter(self, client, logged_in, expenses):
        other = db.create_user("Other", "other@example.com", "password1")
        _insert(other, [(7777.77, "Health", "2026-10-10", "OTHERUSER-SECRET")])
        html = _html(_get(client, start_date="2026-01-01"))
        assert "OTHERUSER-SECRET" not in html
        assert ALL_TOTAL in html

    def test_each_user_sees_only_own_filtered_data(self, client, user_id, expenses):
        other = db.create_user("Other", "other@example.com", "password1")
        _insert(other, [(55.00, "Food", "2026-10-10", "OTHERUSER-ONLY")])
        with client.session_transaction() as sess:
            sess["user_id"] = other
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        assert "OTHERUSER-ONLY" in html
        assert "₹55.00" in html
        assert _present(html) == []

    def test_db_helpers_scoped_to_user(self, user_id, expenses):
        other = db.create_user("Other", "other@example.com", "password1")
        _insert(other, [(7777.77, "Health", "2026-10-10", "OTHERUSER-SECRET")])
        summary = db.get_expense_summary(user_id, start_date="2026-10-01", end_date="2026-10-31")
        assert summary["count"] == 3
        assert summary["total_spent"] == pytest.approx(900.50)
        cats = [r["category"] for r in db.get_category_totals(
            user_id, start_date="2026-10-01", end_date="2026-10-31")]
        assert "Health" not in cats


# ------------------------------------------------------------------ no mutation

class TestReadOnly:
    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"start_date": "2026-10-01"},
            {"end_date": "2026-10-01"},
            {"start_date": "2026-10-01", "end_date": "2026-10-31"},
            {"start_date": "2026-10-31", "end_date": "2026-10-01"},
            {"start_date": "garbage"},
            {"start_date": "2030-01-01", "end_date": "2030-12-31"},
        ],
    )
    def test_filtering_never_mutates_data(self, client, logged_in, expenses, params):
        before = _snapshot()
        assert _get(client, **params).status_code == 200
        assert _snapshot() == before

    def test_repeated_filtering_is_idempotent(self, client, logged_in, expenses):
        first = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        second = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        assert _present(first) == _present(second)
        assert OCT_TOTAL in second


# ------------------------------------------------------------------ auth

class TestAuthGuard:
    def test_signed_out_with_params_redirects_to_login(self, client, expenses):
        response = _get(client, start_date="2026-10-01")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")

    @pytest.mark.parametrize(
        "params",
        [
            {"start_date": "2026-10-01", "end_date": "2026-10-31"},
            {"end_date": "2026-10-31"},
            {"start_date": "garbage"},
            {"start_date": "' OR '1'='1"},
        ],
    )
    def test_signed_out_never_sees_data(self, client, expenses, params):
        response = _get(client, **params)
        assert response.status_code == 302
        assert _present(_html(response)) == []

    def test_deleted_session_user_with_params_redirects(self, client, app):
        with client.session_transaction() as sess:
            sess["user_id"] = 9999
        response = _get(client, start_date="2026-10-01")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")


# ------------------------------------------------------------------ UI

class TestFilterUI:
    def test_has_start_and_end_date_inputs(self, client, logged_in, expenses):
        html = _html(_get(client))
        for name in ("start_date", "end_date"):
            tag = _input_tag(html, name)
            assert tag is not None, "Missing input named %s" % name
            assert 'type="date"' in tag

    def test_filter_form_submits_via_get(self, client, logged_in, expenses):
        html = _html(_get(client))
        forms = [f for f in re.findall(r"<form[^>]*>.*?</form>", html, re.S | re.I)
                 if 'name="start_date"' in f]
        assert forms, "Expected a form containing the date inputs"
        assert re.search(r'method="get"', forms[0], re.I)

    def test_has_apply_control(self, client, logged_in, expenses):
        assert "Apply" in _html(_get(client))

    def test_has_preset_filters(self, client, logged_in, expenses):
        html = _html(_get(client))
        for label in ("All Time", "This Month", "Last 3 Months", "Last 6 Months"):
            assert label in html, "Missing preset: %s" % label

    def test_inputs_prefilled_with_active_range(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-05", end_date="2026-10-15"))
        assert 'value="2026-10-05"' in _input_tag(html, "start_date")
        assert 'value="2026-10-15"' in _input_tag(html, "end_date")

    def test_inputs_prefilled_with_only_start(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-05"))
        assert 'value="2026-10-05"' in _input_tag(html, "start_date")
        assert "2026-10-05" not in _input_tag(html, "end_date")

    def test_inputs_not_prefilled_without_filter(self, client, logged_in, expenses):
        html = _html(_get(client))
        for name in ("start_date", "end_date"):
            assert not re.search(r"\d{4}-\d{2}-\d{2}", _input_tag(html, name))

    def test_active_range_is_labelled(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-19"))
        assert "01 Oct 2026" in html
        assert "19 Oct 2026" in html

    def test_valid_filter_page_shows_no_error(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        assert not _error_shown(html)

    def test_page_extends_base_layout(self, client, logged_in, expenses):
        html = _html(_get(client, start_date="2026-10-01"))
        assert "<html" in html.lower() and "</html>" in html.lower()

    def test_no_inline_styles_in_template_or_response(self, client, logged_in, expenses):
        source = PROFILE_TEMPLATE.read_text(encoding="utf-8")
        assert not re.search(r"\sstyle\s*=", source), "profile.html must not use inline styles"
        html = _html(_get(client, start_date="2026-10-01", end_date="2026-10-31"))
        assert "<style" not in html.lower()

    def test_no_hardcoded_hex_colours_in_template(self):
        source = PROFILE_TEMPLATE.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{6}\b", source)


# ------------------------------------------------------------------ db helpers

class TestDbHelperDefaults:
    def test_helpers_without_dates_cover_all_rows(self, user_id, expenses):
        summary = db.get_expense_summary(user_id)
        assert summary["count"] == 5
        assert summary["total_spent"] == pytest.approx(1500.50)
        assert len(db.get_recent_expenses(user_id)) == 5
        assert len(db.get_category_totals(user_id)) == 4

    def test_helpers_with_none_dates_match_defaults(self, user_id, expenses):
        assert db.get_expense_summary(user_id, start_date=None, end_date=None) == \
            db.get_expense_summary(user_id)

    def test_summary_inclusive_range(self, user_id, expenses):
        summary = db.get_expense_summary(user_id, "2026-10-01", "2026-10-31")
        assert summary["count"] == 3
        assert summary["total_spent"] == pytest.approx(900.50)

    def test_summary_empty_range_is_zero(self, user_id, expenses):
        summary = db.get_expense_summary(user_id, "2030-01-01", "2030-12-31")
        assert summary["count"] == 0
        assert not summary["total_spent"]

    def test_recent_expenses_filtered_newest_first(self, user_id, expenses):
        rows = db.get_recent_expenses(user_id, start_date="2026-10-01", end_date="2026-10-31")
        assert [r["description"] for r in rows] == ["ZZ-oct-last", "ZZ-oct-mid", "ZZ-oct-first"]

    def test_category_totals_filtered_largest_first(self, user_id, expenses):
        rows = db.get_category_totals(user_id, start_date="2026-10-01", end_date="2026-10-31")
        assert [r["category"] for r in rows] == ["Shopping", "Transport", "Food"]
        assert rows[2]["total"] == pytest.approx(200.50)
