import math
from datetime import date

import pytest

import planner
from database import db

START = date(2026, 1, 1)


@pytest.fixture
def user_id(app):
    return db.create_user("Dilip Tandekar", "dilip@example.com", "password1")


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
    priority=None,
):
    return db.create_debt(
        owner_id, name, debt_type, balance, apr, min_payment, None, priority
    )


def _debt(id, balance, apr, min_payment, name=None):
    return {
        "id": id,
        "name": name or f"D{id}",
        "balance": balance,
        "apr": apr,
        "min_payment": min_payment,
        "priority": None,
    }


# ------------------------------------------------------------------ #
# planner.py additions                                                #
# ------------------------------------------------------------------ #


def test_schedule_rows_split_payment_into_principal_and_interest():
    result = planner.simulate(
        [_debt(1, 12000, 24, 500), _debt(2, 3000, 12, 200)], 300, "avalanche", START
    )
    for rows in result["schedule"].values():
        for row in rows:
            assert row["principal"] + row["interest"] == pytest.approx(
                row["payment"], abs=0.011
            )
        assert rows[-1]["balance"] == 0
    total = sum(row["payment"] for rows in result["schedule"].values() for row in rows)
    assert total == pytest.approx(result["total_paid"], abs=0.05)


def test_amortization_matches_hand_computed_loan():
    # ₹1,000 at 12% with ₹510 a month: m1 interest 10, m2 interest 5.
    rows, paid_off = planner.amortization(_debt(1, 1000, 12, 510), START)
    assert paid_off
    assert [row["label"] for row in rows] == ["Feb 2026", "Mar 2026"]
    assert rows[0] == {
        "label": "Feb 2026",
        "payment": 510,
        "interest": 10.0,
        "principal": 500.0,
        "balance": 500.0,
    }
    assert rows[1]["payment"] == 505.0
    assert rows[1]["interest"] == 5.0
    assert rows[1]["balance"] == 0


def test_amortization_of_unpayable_debt_is_not_paid_off():
    rows, paid_off = planner.amortization(_debt(1, 10000, 24, 100), START)
    assert not paid_off
    assert len(rows) == planner.MAX_MONTHS


@pytest.mark.parametrize(
    "months, expected", [(0, (0, 0)), (11, (0, 11)), (12, (1, 0)), (157, (13, 1))]
)
def test_countdown(months, expected):
    assert planner.countdown(months) == expected


def test_progress_ring_dash_is_share_of_circumference():
    ring = planner.progress_ring(25, radius=36)
    assert ring["circumference"] == pytest.approx(2 * math.pi * 36, abs=0.01)
    assert ring["dash"] == pytest.approx(ring["circumference"] / 4, abs=0.01)
    assert planner.progress_ring(150)["dash"] == planner.progress_ring(100)["dash"]
    assert planner.progress_ring(-5)["dash"] == 0


def test_total_and_group_series():
    series = {1: [100, 50, 0], 2: [10, 5, 0], 3: [1, 1, 1]}
    assert planner.total_series(series) == {"total": [111, 56, 1]}
    assert planner.total_series({}) == {}
    grouped = planner.group_series(series, {1: "Card", 2: "Loan", 3: "Card"}.get)
    assert grouped == {"Card": [101, 51, 1], "Loan": [10, 5, 0]}


def test_overlay_chart_pads_shorter_series():
    chart = planner.build_chart(
        {"base": [100, 80, 60, 40, 20, 0], "plan": [100, 50, 0]},
        {"base": "Minimums", "plan": "Plan"},
        [f"m{i}" for i in range(6)],
        stacked=False,
    )
    assert len(chart["layers"]) == 2
    assert chart["x_labels"][-1]["label"] == "m5"
    # Both overlaid areas start at the same height (₹100).
    assert (
        chart["layers"][0]["points"].split()[0]
        == chart["layers"][1]["points"].split()[0]
    )


def test_build_chart_returns_none_for_empty_series():
    assert planner.build_chart({"a": [], "b": []}, {}, []) is None


# ------------------------------------------------------------------ #
# Home dashboard                                                      #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "path", ["/debts", "/debts/plan", "/debts/plan?strategy=custom"]
)
def test_debt_pages_redirect_when_signed_out(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_home_greets_user_and_shows_progress(logged_in, user_id):
    debt_id = _seed(user_id, balance=40000)
    db.log_debt_payment(debt_id, user_id, 10000, "2026-01-15", None)
    html = _html(logged_in.get("/debts"))
    assert "Hi Dilip!" in html
    assert 'aria-label="25% paid"' in html
    assert "₹10,000" in html  # principal paid
    assert "₹30,000" in html  # balance
    assert 'class="ring-fill"' in html


def test_home_countdown_shows_years_and_months(logged_in, user_id):
    # ₹1,20,000 at 0% with ₹1,000 a month takes 120 months = 10 years.
    _seed(user_id, balance=120000, apr=0, min_payment=1000)
    html = _html(logged_in.get("/debts"))
    assert "Debt-free countdown" in html
    assert "<strong>10</strong><span>years</span>" in html
    assert "<strong>0</strong><span>months</span>" in html


def test_home_unpayable_plan_shows_message_instead_of_countdown(logged_in, user_id):
    _seed(user_id, balance=10000, apr=24, min_payment=100)
    html = _html(logged_in.get("/debts"))
    assert "Not payable at current payments" in html
    assert "<span>years</span>" not in html


@pytest.mark.parametrize(
    "mode, legend",
    [("total", "Total balance"), ("type", "Car Loan"), ("debt", "Swift")],
)
def test_home_timeline_modes(logged_in, user_id, mode, legend):
    _seed(user_id, name="Visa")
    _seed(
        user_id,
        name="Swift",
        debt_type="Car Loan",
        balance=300000,
        apr=9,
        min_payment=8000,
    )
    html = _html(logged_in.get("/debts", query_string={"chart": mode}))
    active = html.split('class="chart-tab is-active"')[1][:80]
    assert f'href="/debts?chart={mode}"' in active
    assert legend in html
    assert html.count('class="chart-area') >= 2  # timeline + impact


def test_home_timeline_by_debt_has_one_layer_per_debt(logged_in, user_id):
    _seed(user_id, name="Visa")
    _seed(user_id, name="Swift", debt_type="Car Loan")
    _seed(user_id, name="Amex")
    html = _html(logged_in.get("/debts", query_string={"chart": "debt"}))
    timeline = html.split("Payoff timeline")[1].split("Planned extra payments")[0]
    assert timeline.count("<polygon") == 3
    by_type = _html(logged_in.get("/debts", query_string={"chart": "type"}))
    timeline = by_type.split("Payoff timeline")[1].split("Planned extra payments")[0]
    assert timeline.count("<polygon") == 2  # Credit Card + Car Loan


def test_home_unknown_chart_mode_falls_back_to_total(logged_in, user_id):
    _seed(user_id)
    html = _html(logged_in.get("/debts", query_string={"chart": "bogus"}))
    active = html.split('class="chart-tab is-active"')[1][:80]
    assert 'href="/debts?chart=total"' in active
    assert "Total balance" in html


def test_home_impact_shows_savings_with_extra_payment(logged_in, user_id):
    _seed(user_id, balance=120000, apr=0, min_payment=1000)
    db.save_debt_settings(user_id, 1000, "avalanche")
    html = _html(logged_in.get("/debts"))
    # Minimums: 120 months; with ₹1,000 extra: 60 months, so 5 years sooner.
    impact = html.split("Planned extra payments impact")[1]
    assert "<dd>5 years</dd>" in impact
    assert "Minimums only" in impact
    assert "Your plan" in impact
    assert "Add an extra monthly payment" not in html


def test_home_impact_hint_when_no_extra_payment(logged_in, user_id):
    _seed(user_id)
    html = _html(logged_in.get("/debts"))
    assert "Add an extra monthly payment" in html
    assert "<dd>0 months</dd>" in html


def test_home_progress_by_type_groups_debts(logged_in, user_id):
    first = _seed(user_id, name="Visa", balance=20000)
    _seed(user_id, name="Amex", balance=20000)
    _seed(user_id, name="Swift", debt_type="Car Loan", balance=100000)
    db.log_debt_payment(first, user_id, 10000, "2026-01-15", None)
    html = _html(logged_in.get("/debts"))
    cards = html.split("Progress by type")[1]
    assert cards.count('<article class="type-card') == 2
    assert "type-card type-credit-card" in cards
    assert "Balance ₹30,000" in cards  # 40,000 − 10,000 across both cards
    assert "25%" in cards
    assert 'class="debt-icon"' in cards


def test_home_empty_state(logged_in):
    html = _html(logged_in.get("/debts"))
    assert "Add your first debt" in html
    assert "Debt-free countdown" not in html
    assert "<svg viewBox" not in html


def test_home_never_shows_other_users_debts(logged_in, other_user_id):
    _seed(other_user_id, name="SecretLoan")
    html = _html(logged_in.get("/debts"))
    assert "SecretLoan" not in html
    assert "Add your first debt" in html


# ------------------------------------------------------------------ #
# Sidebar                                                             #
# ------------------------------------------------------------------ #


def test_sidebar_on_debt_pages(logged_in, user_id):
    debt_id = _seed(user_id, name="Visa", balance=12000, apr=0, min_payment=1000)
    # 12 months at ₹1,000 from today's month.
    expected = planner.simulate(
        [_debt(debt_id, 12000, 0, 1000)], 0, "avalanche"
    )["debt_free_date"]
    for path, active in [
        ("/debts", "/debts"),
        ("/debts/plan", "/debts/plan"),
        (f"/debts/{debt_id}", f"/debts/{debt_id}"),
    ]:
        html = _html(logged_in.get(path))
        assert 'class="debt-sidebar"' in html
        assert "Debt payoff date" in html
        card = html.split('class="debt-date-card"')[1].split("</div>")[0]
        assert f"<strong>{expected}</strong>" in card
        assert f'href="{active}" aria-current="page"' in html
        assert f'href="/debts/{debt_id}"' in html  # Track link for the debt


def test_sidebar_absent_on_other_pages(logged_in):
    assert 'class="debt-sidebar"' not in _html(logged_in.get("/profile"))


def test_settings_redirect_back_to_plan(logged_in, user_id):
    _seed(user_id)
    response = logged_in.post(
        "/debts/settings", data={"extra_payment": "500", "strategy": "snowball"}
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/debts/plan"


# ------------------------------------------------------------------ #
# Debt page tabs and amortization                                     #
# ------------------------------------------------------------------ #


def test_detail_overview_has_ring_and_tabs(logged_in, user_id):
    debt_id = _seed(user_id)
    html = _html(logged_in.get(f"/debts/{debt_id}"))
    assert 'class="ring ring-warm"' in html
    assert f'href="/debts/{debt_id}?tab=amortization"' in html
    assert "Payment History" in html
    assert "Amortization</h2>" not in html


def test_detail_amortization_tab(logged_in, user_id):
    debt_id = _seed(user_id, balance=1000, apr=12, min_payment=510)
    html = _html(
        logged_in.get(f"/debts/{debt_id}", query_string={"tab": "amortization"})
    )
    assert "Amortization</h2>" in html
    assert "Payment History" not in html
    table = html.split('class="tx-table amort-table"')[1]
    assert table.count("<tr>") == 3  # header + 2 months
    assert "₹510.00" in table
    assert "₹10.00" in table  # first month's interest
    assert "₹500.00" in table  # first month's principal and balance
    assert "Showing the first" not in html


def test_detail_amortization_caps_long_schedules(logged_in, user_id):
    debt_id = _seed(user_id, balance=10000, apr=24, min_payment=100)
    html = _html(logged_in.get(f"/debts/{debt_id}?tab=amortization"))
    table = html.split('class="tx-table amort-table"')[1]
    assert table.count("<tr>") == 361
    assert "Showing the first 360 months" in html


def test_detail_amortization_for_paid_off_debt(logged_in, user_id):
    debt_id = _seed(user_id, balance=1000)
    db.log_debt_payment(debt_id, user_id, 1000, "2026-01-15", None)
    html = _html(logged_in.get(f"/debts/{debt_id}?tab=amortization"))
    assert "This debt is paid off" in html
    assert "amort-table" not in html


def test_detail_unknown_tab_shows_overview(logged_in, user_id):
    debt_id = _seed(user_id)
    html = _html(logged_in.get(f"/debts/{debt_id}?tab=bogus"))
    assert "Payment History" in html


def test_detail_other_users_debt_still_404(logged_in, other_user_id):
    debt_id = _seed(other_user_id)
    assert logged_in.get(f"/debts/{debt_id}?tab=amortization").status_code == 404
