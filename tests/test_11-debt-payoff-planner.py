"""Tests for Step 11: debt payoff planner (spec: .claude/specs/11-debt-payoff-planner.md).

Written from the spec. Note: the spec describes the planner page at /debts;
the project has since moved the planner to /debts/plan (CLAUDE.md) and made
/debts a dashboard. Planner-content assertions therefore use PLANNER_URL, and
post-action redirects accept either page.
"""

import pytest

import database.db as db
import planner

PLANNER_URL = "/debts/plan"
DEBT_PAGES = ("/debts", "/debts/plan")


# ------------------------------------------------------------------ #
# Fixtures / helpers
# ------------------------------------------------------------------ #


@pytest.fixture
def user_id(app):
    return db.create_user("Test User", "user@example.com", "password1")


@pytest.fixture
def other_user_id(app):
    return db.create_user("Other User", "other@example.com", "password1")


@pytest.fixture
def logged_in(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return client


def _html(response):
    return response.get_data(as_text=True)


def _seed(
    owner_id,
    name="Visa",
    debt_type="Credit Card",
    balance=50000,
    apr=18,
    min_payment=2000,
    due_day=5,
    priority=1,
):
    return db.create_debt(
        owner_id, name, debt_type, balance, apr, min_payment, due_day, priority
    )


def _form(**overrides):
    data = {
        "name": "Visa",
        "debt_type": "Credit Card",
        "balance": "50000",
        "apr": "18",
        "min_payment": "2000",
        "due_day": "5",
        "priority": "1",
    }
    data.update(overrides)
    return data


def _pay(client, debt_id, **overrides):
    data = {"amount": "1000", "paid_on": "2025-01-15", "note": "test"}
    data.update(overrides)
    return client.post(f"/debts/{debt_id}/payments", data=data)


def _debt(owner_id, debt_id):
    return db.get_debt(debt_id, owner_id)


def _d(id, name, balance, apr, min_payment, priority=None):
    return {
        "id": id,
        "name": name,
        "balance": balance,
        "apr": apr,
        "min_payment": min_payment,
        "priority": priority,
    }


# ------------------------------------------------------------------ #
# Auth guard / navbar
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/debts"),
        ("get", "/debts/plan"),
        ("get", "/debts/plan?strategy=snowball"),
        ("get", "/debts/add"),
        ("post", "/debts/add"),
        ("get", "/debts/1/edit"),
        ("post", "/debts/1/edit"),
        ("post", "/debts/1/delete"),
        ("post", "/debts/settings"),
        ("get", "/debts/1"),
        ("post", "/debts/1/payments"),
        ("post", "/debts/1/payments/1/delete"),
    ],
)
def test_signed_out_redirects_to_login(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 302, f"{method} {path} should redirect"
    assert response.headers["Location"].endswith("/login")


def test_signed_out_post_creates_nothing(client, user_id):
    client.post("/debts/add", data=_form())
    assert db.get_debts(user_id) == [], "signed-out POST must not create a debt"


def test_navbar_debts_link_only_when_signed_in(client, user_id):
    assert 'href="/debts"' not in _html(client.get("/login"))
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    html = _html(client.get("/profile"))
    assert 'href="/debts"' in html
    assert "nav-debts" in html


# ------------------------------------------------------------------ #
# DB layer
# ------------------------------------------------------------------ #


class TestDbHelpers:
    def test_constants(self, app):
        assert db.DEBT_TYPES == [
            "Credit Card",
            "Personal Loan",
            "Car Loan",
            "Education Loan",
            "Home Loan",
            "Other",
        ]
        assert tuple(planner.STRATEGIES) == ("snowball", "avalanche", "custom")

    def test_create_debt_sets_original_balance(self, user_id):
        debt_id = _seed(user_id, balance=12345)
        debt = _debt(user_id, debt_id)
        assert debt["balance"] == 12345
        assert debt["original_balance"] == 12345

    def test_get_debts_scoped_to_user(self, user_id, other_user_id):
        _seed(user_id, name="Mine")
        _seed(other_user_id, name="Theirs")
        names = [d["name"] for d in db.get_debts(user_id)]
        assert names == ["Mine"]

    def test_get_debt_other_user_returns_none(self, user_id, other_user_id):
        debt_id = _seed(user_id)
        assert db.get_debt(debt_id, other_user_id) is None

    def test_update_debt_returns_true_and_changes_row(self, user_id):
        debt_id = _seed(user_id)
        ok = db.update_debt(
            debt_id, user_id, "Renamed", "Car Loan", 40000, 9, 1500, None, None
        )
        assert ok is True
        debt = _debt(user_id, debt_id)
        assert debt["name"] == "Renamed"
        assert debt["debt_type"] == "Car Loan"
        assert debt["due_day"] is None

    def test_update_debt_other_user_returns_false(self, user_id, other_user_id):
        debt_id = _seed(user_id)
        ok = db.update_debt(
            debt_id, other_user_id, "Hacked", "Other", 1, 1, 1, None, None
        )
        assert ok is False
        assert _debt(user_id, debt_id)["name"] == "Visa"

    def test_update_debt_raising_balance_raises_original(self, user_id):
        debt_id = _seed(user_id, balance=50000)
        db.update_debt(debt_id, user_id, "Visa", "Credit Card", 80000, 18, 2000, 5, 1)
        debt = _debt(user_id, debt_id)
        assert debt["balance"] == 80000
        assert debt["original_balance"] >= 80000

    def test_delete_debt_returns_bool(self, user_id, other_user_id):
        debt_id = _seed(user_id)
        assert db.delete_debt(debt_id, other_user_id) is False
        assert db.delete_debt(debt_id, user_id) is True
        assert db.delete_debt(debt_id, user_id) is False

    def test_settings_default_when_no_row(self, user_id):
        settings = db.get_debt_settings(user_id)
        assert settings["extra_payment"] == 0
        assert settings["strategy"] == "avalanche"

    def test_save_settings_upserts(self, user_id):
        db.save_debt_settings(user_id, 500, "snowball")
        db.save_debt_settings(user_id, 900, "custom")
        settings = db.get_debt_settings(user_id)
        assert settings["extra_payment"] == 900
        assert settings["strategy"] == "custom"

    def test_log_payment_lowers_balance_and_records(self, user_id):
        debt_id = _seed(user_id, balance=10000)
        assert db.log_debt_payment(debt_id, user_id, 2500, "2025-01-10", "n")
        assert _debt(user_id, debt_id)["balance"] == 7500
        payments = db.get_debt_payments(debt_id, user_id)
        assert len(payments) == 1
        assert payments[0]["amount"] == 2500

    def test_log_payment_wrong_user_returns_false_and_no_row(
        self, user_id, other_user_id
    ):
        debt_id = _seed(user_id, balance=10000)
        assert (
            db.log_debt_payment(debt_id, other_user_id, 100, "2025-01-10", None)
            is False
        )
        assert _debt(user_id, debt_id)["balance"] == 10000
        assert db.get_debt_payments(debt_id, user_id) == []

    def test_log_payment_balance_never_negative(self, user_id):
        debt_id = _seed(user_id, balance=1000)
        db.log_debt_payment(debt_id, user_id, 5000, "2025-01-10", None)
        assert _debt(user_id, debt_id)["balance"] == 0

    def test_get_payments_newest_first(self, user_id):
        debt_id = _seed(user_id, balance=10000)
        db.log_debt_payment(debt_id, user_id, 100, "2025-01-01", "old")
        db.log_debt_payment(debt_id, user_id, 200, "2025-03-01", "new")
        payments = db.get_debt_payments(debt_id, user_id)
        assert [p["paid_on"] for p in payments] == ["2025-03-01", "2025-01-01"]

    def test_delete_payment_restores_balance(self, user_id):
        debt_id = _seed(user_id, balance=10000)
        db.log_debt_payment(debt_id, user_id, 3000, "2025-01-01", None)
        pid = db.get_debt_payments(debt_id, user_id)[0]["id"]
        assert db.delete_debt_payment(pid, debt_id, user_id) is True
        assert _debt(user_id, debt_id)["balance"] == 10000

    def test_delete_payment_restore_capped_at_original(self, user_id):
        debt_id = _seed(user_id, balance=10000)
        db.log_debt_payment(debt_id, user_id, 3000, "2025-01-01", None)
        pid = db.get_debt_payments(debt_id, user_id)[0]["id"]
        # Lower the balance further outside the payment log is not possible via
        # public API; instead pay a second time then delete the first twice
        db.log_debt_payment(debt_id, user_id, 500, "2025-01-02", None)
        db.delete_debt_payment(pid, debt_id, user_id)
        assert _debt(user_id, debt_id)["balance"] <= 10000

    def test_delete_payment_wrong_user_returns_false(self, user_id, other_user_id):
        debt_id = _seed(user_id, balance=10000)
        db.log_debt_payment(debt_id, user_id, 3000, "2025-01-01", None)
        pid = db.get_debt_payments(debt_id, user_id)[0]["id"]
        assert db.delete_debt_payment(pid, debt_id, other_user_id) is False
        assert _debt(user_id, debt_id)["balance"] == 7000

    def test_delete_debt_cascades_payments(self, user_id):
        debt_id = _seed(user_id, balance=10000)
        db.log_debt_payment(debt_id, user_id, 100, "2025-01-01", None)
        db.delete_debt(debt_id, user_id)
        conn = db.get_db()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM debt_payments WHERE debt_id = ?",
                (debt_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 0, "payments must be removed with their debt"


# ------------------------------------------------------------------ #
# Empty state / planner page
# ------------------------------------------------------------------ #


def test_planner_empty_state_links_to_add(logged_in):
    response = logged_in.get(PLANNER_URL)
    assert response.status_code == 200
    html = _html(response)
    assert "/debts/add" in html, "empty state should link to add-debt"
    assert "<svg" not in html or "chart-series-0" not in html


def test_debts_home_renders_for_signed_in_user(logged_in):
    assert logged_in.get("/debts").status_code == 200


def test_planner_with_debts_renders_svg_and_rupee(logged_in, user_id):
    _seed(user_id, name="Visa")
    _seed(
        user_id,
        name="Car",
        debt_type="Car Loan",
        balance=200000,
        apr=9,
        min_payment=8000,
        priority=2,
    )
    html = _html(logged_in.get(PLANNER_URL))
    assert "<svg" in html, "payoff chart SVG expected"
    assert "chart-series-0" in html
    assert "chart-series-1" in html, "one band per debt"
    assert "₹" in html
    assert "Visa" in html and "Car" in html


def test_planner_comparison_lists_strategies_and_minimums(logged_in, user_id):
    _seed(user_id, priority=1)
    html = _html(logged_in.get(PLANNER_URL))
    for label in ("Snowball", "Avalanche", "Minimums only"):
        assert label in html, f"comparison table should list {label}"


def test_planner_unknown_strategy_does_not_crash(logged_in, user_id):
    _seed(user_id)
    assert logged_in.get(PLANNER_URL + "?strategy=bogus").status_code == 200


def _debts_table(response):
    # the chart legend lists debts in insertion order, so only look at the table
    html = _html(response)
    return html[html.index("tx-table"):]


def test_strategy_param_changes_payoff_order(logged_in, user_id):
    # snowball -> small balance first; avalanche -> high APR first
    _seed(user_id, name="SmallLowApr", balance=5000, apr=3, min_payment=500, priority=2)
    _seed(
        user_id, name="BigHighApr", balance=90000, apr=30, min_payment=3000, priority=1
    )
    snow = _debts_table(logged_in.get(PLANNER_URL + "?strategy=snowball"))
    aval = _debts_table(logged_in.get(PLANNER_URL + "?strategy=avalanche"))
    assert snow.index("SmallLowApr") < snow.index("BigHighApr")
    assert aval.index("BigHighApr") < aval.index("SmallLowApr")


def test_custom_strategy_orders_by_priority(logged_in, user_id):
    _seed(user_id, name="PrioTwo", balance=5000, apr=30, min_payment=500, priority=2)
    _seed(user_id, name="PrioOne", balance=90000, apr=3, min_payment=3000, priority=1)
    html = _debts_table(logged_in.get(PLANNER_URL + "?strategy=custom"))
    assert html.index("PrioOne") < html.index("PrioTwo")


def test_min_payment_below_interest_shows_warning(logged_in, user_id):
    # monthly interest = 100000 * 24% / 12 = 2000 > 500 minimum
    _seed(user_id, name="Underwater", balance=100000, apr=24, min_payment=500)
    html = _html(logged_in.get(PLANNER_URL))
    assert "plan-warning" in html
    assert "Underwater" in html
    assert "Not payable at current payments" in html


def test_healthy_debt_has_no_warning(logged_in, user_id):
    _seed(user_id, balance=10000, apr=12, min_payment=2000)
    html = _html(logged_in.get(PLANNER_URL))
    assert "plan-warning" not in html.replace(".plan-warning", "")


def test_only_own_debts_listed(logged_in, user_id, other_user_id):
    _seed(user_id, name="MineDebt")
    _seed(other_user_id, name="SecretDebt")
    html = _html(logged_in.get(PLANNER_URL))
    assert "MineDebt" in html
    assert "SecretDebt" not in html


# ------------------------------------------------------------------ #
# Add
# ------------------------------------------------------------------ #


def test_add_form_renders(logged_in):
    response = logged_in.get("/debts/add")
    assert response.status_code == 200
    html = _html(response)
    for debt_type in db.DEBT_TYPES:
        assert debt_type in html


def test_add_debt_happy_path_creates_and_flashes(logged_in, user_id):
    response = logged_in.post("/debts/add", data=_form(), follow_redirects=True)
    assert response.status_code == 200
    assert "Debt added." in _html(response)
    debts = db.get_debts(user_id)
    assert len(debts) == 1
    assert debts[0]["name"] == "Visa"
    assert debts[0]["balance"] == debts[0]["original_balance"] == 50000


def test_add_debt_redirects_to_debts_page(logged_in):
    response = logged_in.post("/debts/add", data=_form())
    assert response.status_code == 302
    assert response.headers["Location"].endswith(DEBT_PAGES)


def test_add_debt_optional_fields_blank_stored_as_null(logged_in, user_id):
    logged_in.post("/debts/add", data=_form(due_day="", priority=""))
    debt = db.get_debts(user_id)[0]
    assert debt["due_day"] is None
    assert debt["priority"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 500},
        {"debt_type": "Bogus"},
        {"debt_type": ""},
        {"balance": ""},
        {"balance": "abc"},
        {"balance": "-5"},
        {"balance": "0"},
        {"balance": "100000001"},
        {"balance": "nan"},
        {"balance": "inf"},
        {"apr": "-1"},
        {"apr": "150"},
        {"apr": "101"},
        {"apr": "abc"},
        {"min_payment": "0"},
        {"min_payment": "-10"},
        {"min_payment": ""},
        {"min_payment": "100000001"},
        {"due_day": "0"},
        {"due_day": "32"},
        {"due_day": "abc"},
        {"priority": "0"},
        {"priority": "100"},
        {"priority": "x"},
    ],
)
def test_add_debt_invalid_input_rerenders_without_saving(logged_in, user_id, overrides):
    response = logged_in.post("/debts/add", data=_form(**overrides))
    assert response.status_code == 200, f"{overrides} should re-render form"
    assert db.get_debts(user_id) == [], f"{overrides} must not create a debt"


def test_add_debt_invalid_input_keeps_entered_values(logged_in):
    response = logged_in.post("/debts/add", data=_form(name="KeepMe", apr="150"))
    assert "KeepMe" in _html(response)


@pytest.mark.parametrize("apr", ["0", "100"])
def test_add_debt_apr_boundaries_accepted(logged_in, user_id, apr):
    logged_in.post("/debts/add", data=_form(apr=apr))
    assert len(db.get_debts(user_id)) == 1


@pytest.mark.parametrize("day", ["1", "31"])
def test_add_debt_due_day_boundaries_accepted(logged_in, user_id, day):
    logged_in.post("/debts/add", data=_form(due_day=day))
    assert len(db.get_debts(user_id)) == 1


def test_add_debt_sql_injection_stored_literally(logged_in, user_id):
    evil = "x'); DROP TABLE debts;--"
    logged_in.post("/debts/add", data=_form(name=evil))
    debts = db.get_debts(user_id)
    assert len(debts) == 1
    assert debts[0]["name"] == evil


def test_add_debt_html_name_is_escaped(logged_in, user_id):
    _seed(user_id, name="<script>alert(1)</script>")
    html = _html(logged_in.get(PLANNER_URL))
    assert "<script>alert(1)</script>" not in html


# ------------------------------------------------------------------ #
# Edit
# ------------------------------------------------------------------ #


def test_edit_form_prefilled(logged_in, user_id):
    debt_id = _seed(user_id, name="PrefillMe", balance=777)
    response = logged_in.get(f"/debts/{debt_id}/edit")
    assert response.status_code == 200
    html = _html(response)
    assert "PrefillMe" in html
    assert "777" in html


def test_edit_debt_happy_path(logged_in, user_id):
    debt_id = _seed(user_id)
    response = logged_in.post(
        f"/debts/{debt_id}/edit",
        data=_form(name="Updated", apr="12"),
        follow_redirects=True,
    )
    assert "Debt updated." in _html(response)
    debt = _debt(user_id, debt_id)
    assert debt["name"] == "Updated"
    assert debt["apr"] == 12


def test_edit_debt_redirects_to_debts_page(logged_in, user_id):
    debt_id = _seed(user_id)
    response = logged_in.post(f"/debts/{debt_id}/edit", data=_form())
    assert response.status_code == 302
    assert response.headers["Location"].endswith(DEBT_PAGES)


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"debt_type": "Nope"},
        {"balance": "-1"},
        {"apr": "150"},
        {"min_payment": "0"},
        {"due_day": "40"},
        {"priority": "500"},
    ],
)
def test_edit_debt_invalid_input_not_saved(logged_in, user_id, overrides):
    debt_id = _seed(user_id, name="Original")
    response = logged_in.post(f"/debts/{debt_id}/edit", data=_form(**overrides))
    assert response.status_code == 200
    assert _debt(user_id, debt_id)["name"] == "Original"


def test_edit_missing_debt_404(logged_in):
    assert logged_in.get("/debts/9999/edit").status_code == 404
    assert logged_in.post("/debts/9999/edit", data=_form()).status_code == 404


def test_edit_other_users_debt_404(logged_in, other_user_id):
    debt_id = _seed(other_user_id, name="NotYours")
    assert logged_in.get(f"/debts/{debt_id}/edit").status_code == 404
    response = logged_in.post(f"/debts/{debt_id}/edit", data=_form(name="Hax"))
    assert response.status_code == 404
    assert _debt(other_user_id, debt_id)["name"] == "NotYours"


# ------------------------------------------------------------------ #
# Delete
# ------------------------------------------------------------------ #


def test_delete_debt_happy_path(logged_in, user_id):
    debt_id = _seed(user_id)
    response = logged_in.post(f"/debts/{debt_id}/delete", follow_redirects=True)
    assert "Debt deleted." in _html(response)
    assert db.get_debts(user_id) == []


def test_delete_debt_get_is_405(logged_in, user_id):
    debt_id = _seed(user_id)
    assert logged_in.get(f"/debts/{debt_id}/delete").status_code == 405
    assert len(db.get_debts(user_id)) == 1


def test_delete_other_users_debt_404_and_kept(logged_in, other_user_id):
    debt_id = _seed(other_user_id)
    assert logged_in.post(f"/debts/{debt_id}/delete").status_code == 404
    assert len(db.get_debts(other_user_id)) == 1


def test_delete_missing_debt_404(logged_in):
    assert logged_in.post("/debts/9999/delete").status_code == 404


def test_delete_debt_via_route_removes_payments(logged_in, user_id):
    debt_id = _seed(user_id, balance=10000)
    db.log_debt_payment(debt_id, user_id, 100, "2025-01-01", None)
    logged_in.post(f"/debts/{debt_id}/delete")
    assert db.get_debt_payments(debt_id, user_id) == []


# ------------------------------------------------------------------ #
# Settings
# ------------------------------------------------------------------ #


def test_settings_save_and_persist(logged_in, user_id):
    response = logged_in.post(
        "/debts/settings",
        data={"extra_payment": "1500", "strategy": "snowball"},
        follow_redirects=True,
    )
    assert "Plan updated." in _html(response)
    settings = db.get_debt_settings(user_id)
    assert settings["extra_payment"] == 1500
    assert settings["strategy"] == "snowball"
    # persists across a later request
    assert logged_in.get(PLANNER_URL).status_code == 200
    assert db.get_debt_settings(user_id)["strategy"] == "snowball"


def test_settings_redirects_to_debts_page(logged_in):
    response = logged_in.post(
        "/debts/settings", data={"extra_payment": "0", "strategy": "avalanche"}
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(DEBT_PAGES)


def test_settings_second_save_overwrites(logged_in, user_id):
    logged_in.post(
        "/debts/settings", data={"extra_payment": "100", "strategy": "snowball"}
    )
    logged_in.post(
        "/debts/settings", data={"extra_payment": "200", "strategy": "avalanche"}
    )
    settings = db.get_debt_settings(user_id)
    assert (settings["extra_payment"], settings["strategy"]) == (200, "avalanche")


@pytest.mark.parametrize(
    "data",
    [
        {"extra_payment": "-1", "strategy": "snowball"},
        {"extra_payment": "100000001", "strategy": "snowball"},
        {"extra_payment": "abc", "strategy": "snowball"},
        {"extra_payment": "100", "strategy": "bogus"},
        {"extra_payment": "100", "strategy": ""},
    ],
)
def test_settings_invalid_not_saved(logged_in, user_id, data):
    response = logged_in.post("/debts/settings", data=data)
    assert response.status_code == 200
    settings = db.get_debt_settings(user_id)
    assert settings["extra_payment"] == 0
    assert settings["strategy"] == "avalanche"


def test_settings_are_per_user(logged_in, user_id, other_user_id):
    logged_in.post(
        "/debts/settings", data={"extra_payment": "999", "strategy": "snowball"}
    )
    assert db.get_debt_settings(other_user_id)["extra_payment"] == 0


def test_extra_payment_moves_debt_free_date_earlier(logged_in, user_id):
    _seed(user_id, balance=100000, apr=18, min_payment=4000)
    before = _html(logged_in.get(PLANNER_URL))
    logged_in.post(
        "/debts/settings", data={"extra_payment": "20000", "strategy": "avalanche"}
    )
    after = _html(logged_in.get(PLANNER_URL))
    assert before != after, "extra payment should change the plan output"


# ------------------------------------------------------------------ #
# Debt detail and payments (11b)
# ------------------------------------------------------------------ #


def test_detail_page_renders(logged_in, user_id):
    debt_id = _seed(user_id, name="DetailDebt")
    response = logged_in.get(f"/debts/{debt_id}")
    assert response.status_code == 200
    assert "DetailDebt" in _html(response)
    assert "₹" in _html(response)


def test_detail_other_users_debt_404(logged_in, other_user_id):
    debt_id = _seed(other_user_id)
    assert logged_in.get(f"/debts/{debt_id}").status_code == 404


def test_detail_missing_debt_404(logged_in):
    assert logged_in.get("/debts/9999").status_code == 404


def test_log_payment_happy_path(logged_in, user_id):
    debt_id = _seed(user_id, balance=10000)
    response = logged_in.post(
        f"/debts/{debt_id}/payments",
        data={"amount": "2500", "paid_on": "2025-02-01", "note": "hello"},
        follow_redirects=True,
    )
    assert "Payment logged." in _html(response)
    assert _debt(user_id, debt_id)["balance"] == 7500
    payments = db.get_debt_payments(debt_id, user_id)
    assert len(payments) == 1
    assert payments[0]["note"] == "hello"
    assert payments[0]["paid_on"] == "2025-02-01"


def test_log_payment_redirects_to_detail(logged_in, user_id):
    debt_id = _seed(user_id, balance=10000)
    response = _pay(logged_in, debt_id)
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/debts/{debt_id}")


def test_log_payment_exact_balance_zeroes_debt(logged_in, user_id):
    debt_id = _seed(user_id, balance=1000)
    _pay(logged_in, debt_id, amount="1000")
    assert _debt(user_id, debt_id)["balance"] == 0


def test_log_payment_blank_note_allowed(logged_in, user_id):
    debt_id = _seed(user_id, balance=1000)
    _pay(logged_in, debt_id, note="")
    assert len(db.get_debt_payments(debt_id, user_id)) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": ""},
        {"amount": "abc"},
        {"amount": "0"},
        {"amount": "-5"},
        {"amount": "10001"},  # more than the 10000 balance
        {"paid_on": ""},
        {"paid_on": "not-a-date"},
        {"paid_on": "2025-13-45"},
        {"note": "n" * 201},
    ],
)
def test_log_payment_invalid_rejected(logged_in, user_id, overrides):
    debt_id = _seed(user_id, balance=10000)
    response = _pay(logged_in, debt_id, **overrides)
    assert response.status_code == 200, f"{overrides} should re-render"
    assert _debt(user_id, debt_id)["balance"] == 10000
    assert db.get_debt_payments(debt_id, user_id) == []


def test_log_payment_note_200_chars_ok(logged_in, user_id):
    debt_id = _seed(user_id, balance=10000)
    _pay(logged_in, debt_id, note="n" * 200)
    assert len(db.get_debt_payments(debt_id, user_id)) == 1


def test_log_payment_other_users_debt_404(logged_in, other_user_id):
    debt_id = _seed(other_user_id, balance=10000)
    assert _pay(logged_in, debt_id).status_code == 404
    assert _debt(other_user_id, debt_id)["balance"] == 10000
    assert db.get_debt_payments(debt_id, other_user_id) == []


def test_log_payment_missing_debt_404(logged_in):
    assert _pay(logged_in, 9999).status_code == 404


def test_payment_history_shown_on_detail(logged_in, user_id):
    debt_id = _seed(user_id, balance=10000)
    _pay(logged_in, debt_id, amount="1234.50", note="UniqueNote")
    html = _html(logged_in.get(f"/debts/{debt_id}"))
    assert "UniqueNote" in html
    assert "₹1,234.50" in html


def test_delete_payment_restores_balance(logged_in, user_id):
    debt_id = _seed(user_id, balance=10000)
    _pay(logged_in, debt_id, amount="4000")
    pid = db.get_debt_payments(debt_id, user_id)[0]["id"]
    response = logged_in.post(
        f"/debts/{debt_id}/payments/{pid}/delete", follow_redirects=True
    )
    assert "Payment deleted." in _html(response)
    assert _debt(user_id, debt_id)["balance"] == 10000
    assert db.get_debt_payments(debt_id, user_id) == []


def test_delete_payment_get_is_405(logged_in, user_id):
    debt_id = _seed(user_id, balance=10000)
    _pay(logged_in, debt_id)
    pid = db.get_debt_payments(debt_id, user_id)[0]["id"]
    assert logged_in.get(f"/debts/{debt_id}/payments/{pid}/delete").status_code == 405


def test_delete_payment_other_users_404(logged_in, user_id, other_user_id):
    debt_id = _seed(other_user_id, balance=10000)
    db.log_debt_payment(debt_id, other_user_id, 3000, "2025-01-01", None)
    pid = db.get_debt_payments(debt_id, other_user_id)[0]["id"]
    response = logged_in.post(f"/debts/{debt_id}/payments/{pid}/delete")
    assert response.status_code == 404
    assert _debt(other_user_id, debt_id)["balance"] == 7000
    assert len(db.get_debt_payments(debt_id, other_user_id)) == 1


def test_delete_payment_missing_404(logged_in, user_id):
    debt_id = _seed(user_id)
    assert logged_in.post(f"/debts/{debt_id}/payments/9999/delete").status_code == 404


def test_payment_progress_bar_reflects_payment(logged_in, user_id):
    debt_id = _seed(user_id, balance=10000)
    _pay(logged_in, debt_id, amount="5000")
    html = _html(logged_in.get(f"/debts/{debt_id}"))
    assert "bar-w-50" in html, "half paid should render the 50% bar class"


def test_no_inline_style_attributes_on_planner_pages(logged_in, user_id):
    debt_id = _seed(user_id)
    for path in (PLANNER_URL, f"/debts/{debt_id}", "/debts/add"):
        assert 'style="' not in _html(
            logged_in.get(path)
        ), f"{path} must not use inline style attributes"


# ------------------------------------------------------------------ #
# planner.py (pure functions)
# ------------------------------------------------------------------ #


class TestPlanner:
    def test_zero_apr_pays_off_in_ten_months_no_interest(self):
        result = planner.simulate([_d(1, "A", 1000, 0, 100)], 0, "avalanche")
        assert result["months"] == 10
        assert result["total_interest"] == 0
        assert result["paid_off"] is True

    def test_single_debt_twelve_percent_matches_hand_calc(self):
        # Hand-computed with the same monthly compounding the spec describes.
        balance, months, interest = 1000.0, 0, 0.0
        while balance > 0.005:
            months += 1
            i = round(balance * 12 / 1200, 2)
            interest += i
            balance = round(balance + i - min(200, balance + i), 2)
        result = planner.simulate([_d(1, "A", 1000, 12, 200)], 0, "avalanche")
        assert result["months"] == months
        assert result["total_interest"] == pytest.approx(interest, abs=0.05)

    def test_avalanche_pays_highest_apr_first(self):
        debts = [_d(1, "Low", 1000, 5, 100), _d(2, "High", 1000, 25, 100)]
        result = planner.simulate(debts, 200, "avalanche")
        assert result["payoff_order"][0]["name"] == "High"

    def test_snowball_pays_smallest_balance_first(self):
        debts = [_d(1, "Big", 5000, 25, 100), _d(2, "Small", 500, 5, 100)]
        result = planner.simulate(debts, 200, "snowball")
        assert result["payoff_order"][0]["name"] == "Small"

    def test_custom_follows_priority(self):
        debts = [
            _d(1, "P2", 500, 25, 100, priority=2),
            _d(2, "P1", 5000, 5, 100, priority=1),
        ]
        ordered = planner.order_debts(debts, "custom")
        assert [d["name"] for d in ordered] == ["P1", "P2"]

    def test_order_debts_strategies(self):
        debts = [
            _d(1, "A", 900, 10, 50),
            _d(2, "B", 100, 20, 50),
            _d(3, "C", 500, 30, 50),
        ]
        assert [d["name"] for d in planner.order_debts(debts, "snowball")] == [
            "B",
            "C",
            "A",
        ]
        assert [d["name"] for d in planner.order_debts(debts, "avalanche")] == [
            "C",
            "B",
            "A",
        ]

    def test_freed_minimum_rolls_to_next_debt(self):
        debts = [_d(1, "First", 100, 0, 100), _d(2, "Second", 1000, 0, 100)]
        with_roll = planner.simulate(debts, 0, "snowball")
        # Without rollover, Second would take 10 months; rollover makes it faster.
        assert with_roll["months"] < 10 + 1
        assert with_roll["months"] == 6  # 100 paid in m1, then 200/month

    def test_leftover_in_final_month_applies_to_next_debt(self):
        debts = [_d(1, "First", 150, 0, 100), _d(2, "Second", 1000, 0, 100)]
        result = planner.simulate(debts, 0, "snowball")
        # Total money is conserved: all principal gets paid, nothing is wasted.
        assert result["total_paid"] == pytest.approx(1150, abs=0.01)
        assert result["months"] <= 7

    def test_avalanche_interest_not_more_than_snowball(self):
        debts = [
            _d(1, "A", 8000, 28, 250),
            _d(2, "B", 1500, 6, 80),
            _d(3, "C", 5000, 15, 150),
        ]
        aval = planner.simulate(debts, 300, "avalanche")
        snow = planner.simulate(debts, 300, "snowball")
        assert aval["total_interest"] <= snow["total_interest"] + 0.01

    def test_unpayable_debt_hits_cap(self):
        # interest 2000/month > 500 payment
        result = planner.simulate([_d(1, "A", 100000, 24, 500)], 0, "avalanche")
        assert result["paid_off"] is False
        assert result["months"] == 600
        assert result["debt_free_date"] is None

    def test_extra_payment_reduces_months_and_interest(self):
        debts = [_d(1, "A", 10000, 18, 400)]
        base = planner.simulate(debts, 0, "avalanche")
        boosted = planner.simulate(debts, 500, "avalanche")
        assert boosted["months"] < base["months"]
        assert boosted["total_interest"] < base["total_interest"]

    def test_series_has_balance_per_debt(self):
        debts = [_d(1, "A", 1000, 0, 100), _d(2, "B", 500, 0, 100)]
        result = planner.simulate(debts, 0, "avalanche")
        assert set(result["series"]) == {1, 2}
        assert result["series"][1][-1] == 0

    def test_compare_includes_minimums_last_and_savings_non_negative(self):
        debts = [_d(1, "A", 8000, 28, 250, priority=1), _d(2, "B", 1500, 6, 80)]
        results = planner.compare(debts, 200)
        assert results[-1]["strategy"] == "minimums"
        for r in results:
            assert r["interest_saved"] >= 0
            assert r["months_saved"] >= 0
        assert results[-1]["interest_saved"] == 0
        assert results[-1]["months_saved"] == 0

    def test_compare_custom_only_with_a_priority(self):
        no_prio = [_d(1, "A", 1000, 10, 100), _d(2, "B", 500, 5, 50)]
        names = [r["strategy"] for r in planner.compare(no_prio, 0)]
        assert "custom" not in names
        with_prio = [_d(1, "A", 1000, 10, 100, priority=1), _d(2, "B", 500, 5, 50)]
        names = [r["strategy"] for r in planner.compare(with_prio, 0)]
        assert "custom" in names

    def test_build_chart_one_polygon_per_debt(self):
        series = {1: [100.0, 50.0, 0.0], 2: [200.0, 100.0, 0.0]}
        chart = planner.build_chart(series, {1: "A", 2: "B"}, ["m0", "m1", "m2"])
        assert len(chart["layers"]) == 2

    def test_build_chart_downsamples_to_max_points_keeping_final(self):
        values = [float(1000 - i) for i in range(500)]
        chart = planner.build_chart(
            {1: values}, {1: "A"}, [f"m{i}" for i in range(500)]
        )
        points = chart["layers"][0]["points"].split()
        # polygon = upper edge + lower edge, so each column appears twice
        assert len(points) <= 2 * 120 + 2
        assert chart["x_labels"][-1]["label"] == "m499", "final month kept"

    def test_build_chart_coordinates_one_decimal(self):
        chart = planner.build_chart(
            {1: [333.333, 111.111, 0.0]}, {1: "A"}, ["a", "b", "c"]
        )
        for pair in chart["layers"][0]["points"].split():
            for number in pair.split(","):
                decimals = number.split(".")[1] if "." in number else ""
                assert len(decimals) <= 1, f"{number} has too many decimals"

    def test_build_chart_axis_ticks_use_rupees(self):
        chart = planner.build_chart({1: [1000.0, 0.0]}, {1: "A"}, ["s", "e"])
        assert all(t["label"].startswith("₹") for t in chart["y_ticks"])
        assert len(chart["x_labels"]) == 3

    def test_build_chart_empty_returns_none(self):
        assert planner.build_chart({}, {}, []) is None
