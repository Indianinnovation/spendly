"""Tests for Step 11a: debt payoff planner (CRUD, settings, planner page, chart).

11b items (payments, detail page) are intentionally not covered.
"""

from datetime import date

import pytest

import database.db as db
import planner

START = date(2026, 1, 1)


# ------------------------------------------------------------------ #
# Helpers / fixtures                                                  #
# ------------------------------------------------------------------ #


@pytest.fixture
def user_id(app):
    return db.create_user("Test User", "user@example.com", "password1")


@pytest.fixture
def other_user_id(app):
    return db.create_user("Other User", "other@example.com", "password2")


@pytest.fixture
def logged_in(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return client


def _html(response):
    return response.get_data(as_text=True)


def _form(**overrides):
    data = {
        "name": "Visa",
        "debt_type": "Credit Card",
        "balance": "50000",
        "apr": "18",
        "min_payment": "2000",
        "due_day": "5",
        "priority": "",
    }
    data.update(overrides)
    return data


def _add(
    uid,
    name="Visa",
    debt_type="Credit Card",
    balance=50000,
    apr=18,
    min_payment=2000,
    due_day=None,
    priority=None,
):
    return db.create_debt(
        uid, name, debt_type, balance, apr, min_payment, due_day, priority
    )


def _count_debts(uid):
    return len(db.get_debts(uid))


# ------------------------------------------------------------------ #
# Auth guards                                                         #
# ------------------------------------------------------------------ #


class TestAuthGuards:
    @pytest.mark.parametrize(
        "method, path",
        [
            ("get", "/debts"),
            ("get", "/debts?strategy=snowball"),
            ("get", "/debts/add"),
            ("post", "/debts/add"),
            ("get", "/debts/1/edit"),
            ("post", "/debts/1/edit"),
            ("post", "/debts/1/delete"),
            ("post", "/debts/settings"),
        ],
    )
    def test_signed_out_redirects_to_login(self, client, method, path):
        response = getattr(client, method)(path)
        assert response.status_code == 302, f"{method} {path} should redirect"
        assert response.headers["Location"].endswith("/login")

    def test_signed_out_post_creates_nothing(self, client, user_id):
        client.post("/debts/add", data=_form())
        assert _count_debts(user_id) == 0

    def test_navbar_debts_link_only_when_signed_in(self, client, user_id):
        assert "nav-debts" not in _html(client.get("/login"))
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
        html = _html(client.get("/debts"))
        assert 'class="nav-debts"' in html
        assert 'href="/debts"' in html


# ------------------------------------------------------------------ #
# Empty state                                                         #
# ------------------------------------------------------------------ #


def test_empty_state_renders_add_first_debt_link(logged_in):
    response = logged_in.get("/debts")
    html = _html(response)
    assert response.status_code == 200
    assert "Add your first debt" in html
    assert 'href="/debts/add"' in html
    assert "<svg" not in html


# ------------------------------------------------------------------ #
# Add                                                                 #
# ------------------------------------------------------------------ #


class TestAddDebt:
    def test_get_renders_form_fields(self, logged_in):
        response = logged_in.get("/debts/add")
        html = _html(response)
        assert response.status_code == 200
        for field in (
            "name",
            "debt_type",
            "balance",
            "apr",
            "min_payment",
            "due_day",
            "priority",
        ):
            assert f'name="{field}"' in html, f"missing field {field}"
        for debt_type in db.DEBT_TYPES:
            assert debt_type in html

    def test_post_valid_creates_debt_and_flashes(self, logged_in, user_id):
        response = logged_in.post("/debts/add", data=_form(priority="2"))
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/debts")
        debts = db.get_debts(user_id)
        assert len(debts) == 1
        debt = debts[0]
        assert debt["name"] == "Visa"
        assert debt["debt_type"] == "Credit Card"
        assert debt["balance"] == 50000
        assert debt["original_balance"] == 50000
        assert debt["apr"] == 18
        assert debt["min_payment"] == 2000
        assert debt["due_day"] == 5
        assert debt["priority"] == 2
        assert "Debt added." in _html(logged_in.get("/debts"))

    def test_post_optional_fields_blank_stored_as_null(self, logged_in, user_id):
        logged_in.post("/debts/add", data=_form(due_day="", priority=""))
        debt = db.get_debts(user_id)[0]
        assert debt["due_day"] is None
        assert debt["priority"] is None

    def test_post_zero_apr_is_allowed(self, logged_in, user_id):
        response = logged_in.post("/debts/add", data=_form(apr="0"))
        assert response.status_code == 302
        assert _count_debts(user_id) == 1

    def test_sql_injection_name_stored_literally(self, logged_in, user_id):
        evil = "x'); DROP TABLE debts;--"
        logged_in.post("/debts/add", data=_form(name=evil))
        debts = db.get_debts(user_id)
        assert len(debts) == 1
        assert debts[0]["name"] == evil


INVALID_DEBT_INPUTS = [
    ("blank_name", {"name": ""}),
    ("whitespace_name", {"name": "   "}),
    ("name_too_long", {"name": "a" * 61}),
    ("unknown_type", {"debt_type": "Pirate Loan"}),
    ("blank_type", {"debt_type": ""}),
    ("blank_balance", {"balance": ""}),
    ("non_numeric_balance", {"balance": "abc"}),
    ("negative_balance", {"balance": "-5"}),
    ("zero_balance", {"balance": "0"}),
    ("huge_balance", {"balance": "100000001"}),
    ("blank_apr", {"apr": ""}),
    ("negative_apr", {"apr": "-1"}),
    ("apr_over_100", {"apr": "150"}),
    ("zero_min_payment", {"min_payment": "0"}),
    ("negative_min_payment", {"min_payment": "-10"}),
    ("huge_min_payment", {"min_payment": "100000001"}),
    ("due_day_zero", {"due_day": "0"}),
    ("due_day_32", {"due_day": "32"}),
    ("due_day_text", {"due_day": "abc"}),
    ("priority_zero", {"priority": "0"}),
    ("priority_100", {"priority": "100"}),
    ("priority_text", {"priority": "high"}),
]


class TestDebtValidation:
    @pytest.mark.parametrize(
        "label, overrides", INVALID_DEBT_INPUTS, ids=[i[0] for i in INVALID_DEBT_INPUTS]
    )
    def test_add_invalid_rerenders_and_saves_nothing(
        self, logged_in, user_id, label, overrides
    ):
        response = logged_in.post("/debts/add", data=_form(**overrides))
        assert response.status_code == 200, f"{label} should re-render"
        assert 'class="auth-error"' in _html(response), f"{label}: no error"
        assert _count_debts(user_id) == 0

    @pytest.mark.parametrize(
        "label, overrides", INVALID_DEBT_INPUTS, ids=[i[0] for i in INVALID_DEBT_INPUTS]
    )
    def test_edit_invalid_rerenders_and_changes_nothing(
        self, logged_in, user_id, label, overrides
    ):
        debt_id = _add(user_id)
        response = logged_in.post(f"/debts/{debt_id}/edit", data=_form(**overrides))
        assert response.status_code == 200, f"{label} should re-render"
        assert 'class="auth-error"' in _html(response)
        debt = db.get_debt(debt_id, user_id)
        assert debt["name"] == "Visa"
        assert debt["balance"] == 50000
        assert debt["apr"] == 18

    def test_add_invalid_keeps_entered_values(self, logged_in):
        response = logged_in.post("/debts/add", data=_form(name="Keepme", apr="150"))
        assert "Keepme" in _html(response)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"name": "a" * 60},
            {"balance": "100000000"},
            {"apr": "100"},
            {"min_payment": "100000000"},
            {"due_day": "1"},
            {"due_day": "31"},
            {"priority": "1"},
            {"priority": "99"},
        ],
    )
    def test_add_boundary_values_accepted(self, logged_in, user_id, overrides):
        response = logged_in.post("/debts/add", data=_form(**overrides))
        assert response.status_code == 302, f"{overrides} should be valid"
        assert _count_debts(user_id) == 1


# ------------------------------------------------------------------ #
# Edit                                                                #
# ------------------------------------------------------------------ #


class TestEditDebt:
    def test_get_prefilled(self, logged_in, user_id):
        debt_id = _add(user_id, name="Prefilled Card", due_day=12)
        response = logged_in.get(f"/debts/{debt_id}/edit")
        html = _html(response)
        assert response.status_code == 200
        assert "Prefilled Card" in html
        assert "50000" in html

    def test_post_updates_and_flashes(self, logged_in, user_id):
        debt_id = _add(user_id)
        response = logged_in.post(
            f"/debts/{debt_id}/edit",
            data=_form(name="Renamed", apr="12", min_payment="2500"),
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/debts")
        debt = db.get_debt(debt_id, user_id)
        assert debt["name"] == "Renamed"
        assert debt["apr"] == 12
        assert debt["min_payment"] == 2500
        assert "Debt updated." in _html(logged_in.get("/debts"))

    def test_lowering_balance_keeps_original_balance(self, logged_in, user_id):
        debt_id = _add(user_id, balance=50000)
        logged_in.post(f"/debts/{debt_id}/edit", data=_form(balance="30000"))
        debt = db.get_debt(debt_id, user_id)
        assert debt["balance"] == 30000
        assert debt["original_balance"] == 50000

    def test_raising_balance_raises_original_balance(self, logged_in, user_id):
        debt_id = _add(user_id, balance=50000)
        logged_in.post(f"/debts/{debt_id}/edit", data=_form(balance="80000"))
        debt = db.get_debt(debt_id, user_id)
        assert debt["balance"] == 80000
        assert debt["original_balance"] == 80000

    def test_missing_debt_404(self, logged_in):
        assert logged_in.get("/debts/9999/edit").status_code == 404
        assert logged_in.post("/debts/9999/edit", data=_form()).status_code == 404


# ------------------------------------------------------------------ #
# Delete                                                              #
# ------------------------------------------------------------------ #


class TestDeleteDebt:
    def test_post_deletes_and_flashes(self, logged_in, user_id):
        debt_id = _add(user_id)
        response = logged_in.post(f"/debts/{debt_id}/delete")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/debts")
        assert db.get_debt(debt_id, user_id) is None
        assert "Debt deleted." in _html(logged_in.get("/debts"))

    def test_get_is_405_and_keeps_debt(self, logged_in, user_id):
        debt_id = _add(user_id)
        assert logged_in.get(f"/debts/{debt_id}/delete").status_code == 405
        assert db.get_debt(debt_id, user_id) is not None

    def test_missing_debt_404(self, logged_in):
        assert logged_in.post("/debts/9999/delete").status_code == 404

    def test_delete_only_removes_target(self, logged_in, user_id):
        keep = _add(user_id, name="Keep")
        gone = _add(user_id, name="Gone")
        logged_in.post(f"/debts/{gone}/delete")
        assert [d["id"] for d in db.get_debts(user_id)] == [keep]


# ------------------------------------------------------------------ #
# Ownership                                                           #
# ------------------------------------------------------------------ #


class TestOwnership:
    def test_other_users_debt_edit_get_404(self, logged_in, other_user_id):
        debt_id = _add(other_user_id, name="Secret")
        assert logged_in.get(f"/debts/{debt_id}/edit").status_code == 404

    def test_other_users_debt_edit_post_404_and_unchanged(
        self, logged_in, other_user_id
    ):
        debt_id = _add(other_user_id, name="Secret")
        response = logged_in.post(f"/debts/{debt_id}/edit", data=_form(name="Hacked"))
        assert response.status_code == 404
        assert db.get_debt(debt_id, other_user_id)["name"] == "Secret"

    def test_other_users_debt_delete_404_and_kept(self, logged_in, other_user_id):
        debt_id = _add(other_user_id, name="Secret")
        assert logged_in.post(f"/debts/{debt_id}/delete").status_code == 404
        assert db.get_debt(debt_id, other_user_id) is not None

    def test_other_users_debt_not_listed(self, logged_in, other_user_id):
        _add(other_user_id, name="Secret Loan Name")
        html = _html(logged_in.get("/debts"))
        assert "Secret Loan Name" not in html
        assert "Add your first debt" in html

    def test_other_users_settings_not_leaked(self, logged_in, user_id, other_user_id):
        db.save_debt_settings(other_user_id, 7777, "snowball")
        assert db.get_debt_settings(user_id)["extra_payment"] == 0


# ------------------------------------------------------------------ #
# Settings                                                            #
# ------------------------------------------------------------------ #


class TestSettings:
    def test_defaults_when_no_row(self, user_id):
        settings = db.get_debt_settings(user_id)
        assert settings["extra_payment"] == 0
        assert settings["strategy"] == "avalanche"

    def test_save_persists_and_flashes(self, logged_in, user_id):
        response = logged_in.post(
            "/debts/settings", data={"extra_payment": "1500", "strategy": "snowball"}
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/debts")
        settings = db.get_debt_settings(user_id)
        assert settings["extra_payment"] == 1500
        assert settings["strategy"] == "snowball"
        html = _html(logged_in.get("/debts"))
        assert "Plan updated." in html

    def test_flash_shown_after_follow_redirect(self, logged_in):
        response = logged_in.post(
            "/debts/settings",
            data={"extra_payment": "100", "strategy": "avalanche"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Plan updated." in _html(response)

    def test_second_save_updates_single_row(self, logged_in, user_id):
        logged_in.post(
            "/debts/settings", data={"extra_payment": "100", "strategy": "snowball"}
        )
        logged_in.post(
            "/debts/settings", data={"extra_payment": "250", "strategy": "avalanche"}
        )
        conn = db.get_db()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM debt_settings WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 1
        settings = db.get_debt_settings(user_id)
        assert settings["extra_payment"] == 250
        assert settings["strategy"] == "avalanche"

    def test_saved_strategy_used_as_default_view(self, logged_in, user_id):
        _add(user_id)
        logged_in.post(
            "/debts/settings", data={"extra_payment": "0", "strategy": "snowball"}
        )
        html = _html(logged_in.get("/debts"))
        assert 'class="filter-pill is-active"' in html
        active = html.split('class="filter-pill is-active"')[1][:200]
        assert "snowball" in active.lower()

    @pytest.mark.parametrize(
        "data",
        [
            {"extra_payment": "", "strategy": "snowball"},
            {"extra_payment": "abc", "strategy": "snowball"},
            {"extra_payment": "-1", "strategy": "snowball"},
            {"extra_payment": "100000001", "strategy": "snowball"},
            {"extra_payment": "100", "strategy": "yolo"},
            {"extra_payment": "100", "strategy": ""},
        ],
    )
    def test_invalid_rerenders_and_saves_nothing(self, logged_in, user_id, data):
        _add(user_id)
        response = logged_in.post("/debts/settings", data=data)
        assert response.status_code == 200
        assert 'class="auth-error"' in _html(response)
        settings = db.get_debt_settings(user_id)
        assert settings["extra_payment"] == 0
        assert settings["strategy"] == "avalanche"

    def test_raising_extra_moves_debt_free_date_earlier(self, logged_in, user_id):
        _add(user_id, balance=100000, apr=12, min_payment=3000)
        plain = planner.simulate(
            [dict(d) for d in db.get_debts(user_id)], 0, "avalanche", START
        )
        boosted = planner.simulate(
            [dict(d) for d in db.get_debts(user_id)], 5000, "avalanche", START
        )
        assert boosted["months"] < plain["months"]
        logged_in.post(
            "/debts/settings", data={"extra_payment": "5000", "strategy": "avalanche"}
        )
        assert db.get_debt_settings(user_id)["extra_payment"] == 5000


# ------------------------------------------------------------------ #
# Planner page                                                        #
# ------------------------------------------------------------------ #


class TestPlannerPage:
    @pytest.fixture
    def two_debts(self, user_id):
        # Snowball -> Small first; avalanche -> Big (higher APR) first.
        _add(
            user_id,
            name="SmallLowApr",
            balance=10000,
            apr=5,
            min_payment=1000,
            priority=2,
        )
        _add(
            user_id,
            name="BigHighApr",
            balance=90000,
            apr=24,
            min_payment=3000,
            priority=1,
        )

    def test_summary_tiles_in_rupees(self, logged_in, two_debts):
        response = logged_in.get("/debts")
        html = _html(response)
        assert response.status_code == 200
        for label in (
            "Total debt",
            "Debt-free date",
            "Total interest",
            "Interest saved",
        ):
            assert label in html, f"missing tile {label}"
        assert "₹100,000" in html

    def test_debt_list_shows_names_types_and_rupees(self, logged_in, two_debts):
        html = _html(logged_in.get("/debts"))
        assert "SmallLowApr" in html
        assert "BigHighApr" in html
        assert "Credit Card" in html
        assert "₹10,000" in html
        assert "₹90,000" in html
        assert "% paid" in html
        assert "/debts/add" in html

    def test_edit_and_delete_controls_present(self, logged_in, user_id, two_debts):
        debt_id = db.get_debts(user_id)[0]["id"]
        html = _html(logged_in.get("/debts"))
        assert f"/debts/{debt_id}/edit" in html
        assert f"/debts/{debt_id}/delete" in html

    def test_chart_svg_and_legend_per_debt(self, logged_in, two_debts):
        html = _html(logged_in.get("/debts"))
        assert "<svg" in html
        assert html.count("<polygon") == 2
        assert "chart-legend" in html
        legend = html.split("chart-legend")[1]
        assert "SmallLowApr" in legend
        assert "BigHighApr" in legend

    def test_comparison_table_lists_all_strategies_and_minimums(
        self, logged_in, two_debts
    ):
        html = _html(logged_in.get("/debts"))
        assert "Strategy Comparison" in html
        assert "Snowball" in html
        assert "Avalanche" in html
        assert "Custom" in html  # at least one debt has a priority
        assert "Minimums only" in html

    def test_comparison_omits_custom_without_priorities(self, logged_in, user_id):
        _add(user_id, name="NoPrio")
        html = _html(logged_in.get("/debts"))
        assert "Minimums only" in html
        comparison = html.split("Strategy Comparison")[1]
        assert "Custom" not in comparison.split("Plan Settings")[0]

    @pytest.mark.parametrize("strategy", ["snowball", "avalanche", "custom"])
    def test_strategy_param_marks_pill_active(self, logged_in, two_debts, strategy):
        response = logged_in.get("/debts", query_string={"strategy": strategy})
        html = _html(response)
        assert response.status_code == 200
        assert html.count("is-active") >= 1
        after = html.split("is-active")[1][:200]
        assert strategy in after.lower()

    def test_strategy_changes_listed_order(self, logged_in, two_debts):
        snow = _html(logged_in.get("/debts?strategy=snowball"))
        aval = _html(logged_in.get("/debts?strategy=avalanche"))
        tbl = lambda h: h.split("Your Debts")[1]  # noqa: E731
        assert tbl(snow).index("SmallLowApr") < tbl(snow).index("BigHighApr")
        assert tbl(aval).index("BigHighApr") < tbl(aval).index("SmallLowApr")

    def test_custom_strategy_follows_priority(self, logged_in, two_debts):
        html = _html(logged_in.get("/debts?strategy=custom"))
        body = html.split("Your Debts")[1]
        assert body.index("BigHighApr") < body.index("SmallLowApr")

    def test_unknown_strategy_param_does_not_crash(self, logged_in, two_debts):
        response = logged_in.get("/debts?strategy=bogus")
        assert response.status_code == 200

    def test_interest_warning_when_minimum_below_interest(self, logged_in, user_id):
        _add(user_id, name="Underwater", balance=100000, apr=36, min_payment=100)
        html = _html(logged_in.get("/debts"))
        assert "plan-warning" in html
        assert "Underwater" in html.split("plan-warning")[1]

    def test_no_interest_warning_for_healthy_debt(self, logged_in, user_id):
        _add(user_id, name="Healthy", balance=10000, apr=12, min_payment=2000)
        assert "plan-warning" not in _html(logged_in.get("/debts"))

    def test_unpayable_plan_shows_not_payable(self, logged_in, user_id):
        _add(user_id, name="Underwater", balance=100000, apr=36, min_payment=100)
        html = _html(logged_in.get("/debts"))
        assert "Not payable at current payments" in html

    def test_payable_plan_has_no_not_payable_text(self, logged_in, user_id):
        _add(user_id, balance=10000, apr=12, min_payment=2000)
        assert "Not payable at current payments" not in _html(logged_in.get("/debts"))

    def test_page_does_not_modify_data(self, logged_in, user_id):
        _add(user_id)
        logged_in.get("/debts?strategy=snowball")
        assert _count_debts(user_id) == 1
        assert db.get_debt_settings(user_id)["strategy"] == "avalanche"


# ------------------------------------------------------------------ #
# planner.py pure functions                                           #
# ------------------------------------------------------------------ #


def _d(id, balance, apr, min_payment, priority=None, name=None):
    return {
        "id": id,
        "name": name or f"D{id}",
        "balance": balance,
        "original_balance": balance,
        "apr": apr,
        "min_payment": min_payment,
        "priority": priority,
    }


class TestPlannerSimulation:
    def test_zero_apr_ten_months_no_interest(self):
        result = planner.simulate([_d(1, 1000, 0, 100)], 0, "avalanche", START)
        assert result["months"] == 10
        assert result["total_interest"] == 0
        assert result["paid_off"] is True
        assert result["debt_free_date"]

    def test_twelve_percent_matches_hand_computation(self):
        balance, apr, minimum = 1200.0, 12.0, 200.0
        months, interest = 0, 0.0
        while balance > 0.005:
            months += 1
            charge = round(balance * apr / 1200, 2)
            interest += charge
            balance = round(balance + charge - min(minimum, balance + charge), 2)
        result = planner.simulate([_d(1, 1200, 12, 200)], 0, "avalanche", START)
        assert result["months"] == months
        assert result["total_interest"] == pytest.approx(interest, abs=0.1)

    def test_extra_payment_shortens_plan(self):
        debts = [_d(1, 1000, 0, 100)]
        result = planner.simulate(debts, 100, "avalanche", START)
        assert result["months"] == 5

    def test_avalanche_pays_highest_apr_first(self):
        debts = [_d(1, 1000, 5, 50, name="Low"), _d(2, 5000, 24, 100, name="High")]
        result = planner.simulate(debts, 500, "avalanche", START)
        assert result["payoff_order"][0]["debt_id"] == 2
        ordered = planner.order_debts(debts, "avalanche")
        assert [d["id"] for d in ordered] == [2, 1]

    def test_snowball_pays_smallest_balance_first(self):
        debts = [_d(1, 5000, 24, 100), _d(2, 1000, 5, 50)]
        ordered = planner.order_debts(debts, "snowball")
        assert [d["id"] for d in ordered] == [2, 1]

    def test_custom_follows_priority(self):
        debts = [_d(1, 1000, 5, 50, priority=2), _d(2, 5000, 24, 100, priority=1)]
        ordered = planner.order_debts(debts, "custom")
        assert [d["id"] for d in ordered] == [2, 1]

    def test_snowball_first_payoff_is_smallest_debt(self):
        debts = [_d(1, 5000, 0, 100), _d(2, 300, 0, 100)]
        result = planner.simulate(debts, 0, "snowball", START)
        first = result["payoff_order"][0]
        assert first["debt_id"] == 2

    def test_minimum_rolls_over_after_payoff(self):
        # Small (100) cleared in 2 months, then its 50 min rolls to Big.
        debts = [_d(1, 100, 0, 50), _d(2, 1000, 0, 50)]
        result = planner.simulate(debts, 0, "snowball", START)
        assert result["months"] == 11
        # Without rollover Big alone would need 20 months.
        minimums = planner.simulate(debts, 0, "minimums", START)
        assert minimums["months"] == 20

    def test_leftover_in_final_month_goes_to_next_debt_same_month(self):
        debts = [_d(1, 120, 0, 100), _d(2, 1000, 0, 100)]
        result = planner.simulate(debts, 0, "snowball", START)
        # series[0] is the starting balance; index 2 is end of month 2.
        # Month1: B=900. Month2: B pays 100 + 80 leftover from A -> 720.
        assert result["series"][2][2] == pytest.approx(720.0, abs=0.01)
        assert result["series"][1][2] == 0

    def test_avalanche_interest_not_more_than_snowball(self):
        debts = [_d(1, 1000, 5, 50), _d(2, 5000, 24, 100), _d(3, 3000, 15, 80)]
        aval = planner.simulate(debts, 200, "avalanche", START)
        snow = planner.simulate(debts, 200, "snowball", START)
        assert aval["total_interest"] <= snow["total_interest"] + 0.01

    def test_unpayable_hits_cap(self):
        result = planner.simulate([_d(1, 100000, 36, 100)], 0, "avalanche", START)
        assert result["paid_off"] is False
        assert result["months"] == 600
        assert result["debt_free_date"] is None

    def test_no_debts_zero_months(self):
        result = planner.simulate([], 0, "avalanche", START)
        assert result["months"] == 0

    def test_interest_warnings_names_underwater_debts(self):
        debts = [_d(1, 100000, 36, 100, name="Bad"), _d(2, 1000, 12, 500, name="Good")]
        warnings = planner.interest_warnings(debts)
        assert any("Bad" in str(w) for w in warnings)
        assert not any("Good" in str(w) for w in warnings)


class TestPlannerCompare:
    def test_minimums_is_last_and_all_strategies_present(self):
        debts = [_d(1, 1000, 5, 50, priority=1), _d(2, 5000, 24, 100)]
        results = planner.compare(debts, 100, START)
        strategies = [r["strategy"] for r in results]
        assert strategies[-1] == "minimums"
        assert set(strategies) == {"snowball", "avalanche", "custom", "minimums"}
        assert len(results) == 4

    def test_custom_omitted_without_priority(self):
        debts = [_d(1, 1000, 5, 50), _d(2, 5000, 24, 100)]
        assert len(planner.compare(debts, 100, START)) == 3

    def test_interest_saved_never_negative_and_zero_for_baseline(self):
        debts = [_d(1, 1000, 5, 50), _d(2, 5000, 24, 100)]
        results = planner.compare(debts, 100, START)
        assert all(r["interest_saved"] >= 0 for r in results)
        assert all(r["months_saved"] >= 0 for r in results)
        assert results[-1]["interest_saved"] == 0
        assert results[-1]["months_saved"] == 0

    def test_extra_payment_produces_positive_savings(self):
        debts = [_d(1, 10000, 20, 300)]
        results = planner.compare(debts, 500, START)
        assert results[0]["interest_saved"] > 0
        assert results[0]["months_saved"] > 0


class TestBuildChart:
    def _series(self, points, ids=(1, 2)):
        return {i: [float(points - n) for n in range(points)] for i in ids}

    def test_one_polygon_per_debt(self):
        series = self._series(10)
        labels = [f"M{n}" for n in range(10)]
        chart = planner.build_chart(series, {1: "A", 2: "B"}, labels)
        assert len(chart["layers"]) == 2
        assert all(layer["points"] for layer in chart["layers"])

    def test_downsamples_to_at_most_max_points(self):
        n = 500
        series = self._series(n)
        labels = [f"M{k}" for k in range(n)]
        chart = planner.build_chart(series, {1: "A", 2: "B"}, labels)
        for layer in chart["layers"]:
            coords = layer["points"].split()
            # polygon = upper edge + lower edge => <= 2 * (max_points + 1)
            assert len(coords) <= 2 * 121, f"{len(coords)} coords"
        assert chart["x_labels"][-1]["label"] == labels[-1]
        assert chart["x_labels"][0]["label"] == labels[0]

    def test_y_ticks_formatted_in_rupees(self):
        series = {1: [5000.0, 2500.0, 0.0]}
        chart = planner.build_chart(series, {1: "A"}, ["a", "b", "c"])
        assert all(t["label"].startswith("₹") for t in chart["y_ticks"])

    def test_empty_series_returns_none(self):
        assert planner.build_chart({}, {}, []) is None
