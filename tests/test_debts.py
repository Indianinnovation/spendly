import pytest

import database.db as db


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


def _debt_count(owner_id):
    return len(db.get_debts(owner_id))


# ------------------------------------------------------------------ #
# Auth guard / navbar
# ------------------------------------------------------------------ #


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
def test_signed_out_redirects_to_login(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 302, f"{method} {path} should redirect"
    assert response.headers["Location"] == "/login"


def test_navbar_link_only_when_signed_in(client, user_id):
    assert 'href="/debts"' not in _html(client.get("/login"))
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    assert 'href="/debts"' in _html(client.get("/profile"))


# ------------------------------------------------------------------ #
# Planner page
# ------------------------------------------------------------------ #


def test_empty_state_renders_without_debts(logged_in):
    response = logged_in.get("/debts")
    html = _html(response)
    assert response.status_code == 200
    assert "first debt" in html.lower(), "Expected empty-state prompt"
    assert "/debts/add" in html


def test_planner_page_shows_svg_and_rupee_amounts(logged_in, user_id):
    _seed(user_id)
    response = logged_in.get("/debts")
    html = _html(response)
    assert response.status_code == 200
    assert "<svg" in html, "Expected server-rendered chart"
    assert "₹50,000" in html
    assert "Visa" in html


def test_comparison_table_lists_minimums_only(logged_in, user_id):
    _seed(user_id)
    html = _html(logged_in.get("/debts"))
    assert "Minimums only" in html


@pytest.mark.parametrize("strategy", ["snowball", "avalanche", "custom"])
def test_known_strategy_param_renders(logged_in, user_id, strategy):
    _seed(user_id, name="Visa", balance=50000, apr=30, priority=2)
    _seed(
        user_id,
        name="Loan",
        debt_type="Personal Loan",
        balance=10000,
        apr=10,
        priority=1,
    )
    response = logged_in.get("/debts", query_string={"strategy": strategy})
    assert response.status_code == 200


def test_unknown_strategy_param_still_renders(logged_in, user_id):
    _seed(user_id)
    response = logged_in.get("/debts", query_string={"strategy": "bogus"})
    assert response.status_code == 200


def test_strategy_changes_payoff_order(logged_in, user_id):
    _seed(
        user_id, name="BigHighApr", balance=90000, apr=36, min_payment=3000, priority=2
    )
    _seed(
        user_id,
        name="SmallLowApr",
        debt_type="Personal Loan",
        balance=5000,
        apr=5,
        min_payment=500,
        priority=1,
    )
    snow = _html(logged_in.get("/debts/plan", query_string={"strategy": "snowball"}))
    aval = _html(logged_in.get("/debts/plan", query_string={"strategy": "avalanche"}))
    custom = _html(logged_in.get("/debts/plan", query_string={"strategy": "custom"}))
    # The debt table lists debts in the order the strategy pays them.
    assert snow.index("<td>SmallLowApr</td>") < snow.index("<td>BigHighApr</td>")
    assert aval.index("<td>BigHighApr</td>") < aval.index("<td>SmallLowApr</td>")
    assert custom.index("<td>SmallLowApr</td>") < custom.index("<td>BigHighApr</td>")


def test_only_own_debts_are_listed(logged_in, user_id, other_user_id):
    _seed(user_id, name="MineDebt")
    _seed(other_user_id, name="TheirsDebt")
    html = _html(logged_in.get("/debts"))
    assert "MineDebt" in html
    assert "TheirsDebt" not in html


# ------------------------------------------------------------------ #
# Warnings
# ------------------------------------------------------------------ #


def test_unpayable_debt_shows_warnings(logged_in, user_id):
    _seed(user_id, name="Trap", balance=10000, apr=24, min_payment=100)
    html = _html(logged_in.get("/debts"))
    assert "Not payable at current payments" in html
    assert "cover its monthly interest" in html
    assert "plan-warning" in html


def test_payable_debt_shows_no_warning(logged_in, user_id):
    _seed(user_id, name="Fine", balance=10000, apr=12, min_payment=2000)
    html = _html(logged_in.get("/debts"))
    assert "Not payable at current payments" not in html
    assert "cover its monthly interest" not in html


# ------------------------------------------------------------------ #
# Add
# ------------------------------------------------------------------ #


def test_add_get_renders_form(logged_in):
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
        assert f'name="{field}"' in html, f"Missing field {field}"


def test_add_valid_creates_debt_and_redirects(logged_in, user_id):
    response = logged_in.post("/debts/add", data=_form())
    assert response.status_code == 302
    assert response.headers["Location"] == "/debts"
    debts = db.get_debts(user_id)
    assert len(debts) == 1
    assert debts[0]["name"] == "Visa"
    assert debts[0]["balance"] == 50000
    assert debts[0]["original_balance"] == 50000


def test_add_valid_flashes_message(logged_in):
    response = logged_in.post("/debts/add", data=_form(), follow_redirects=True)
    assert response.status_code == 200
    assert "Debt added." in _html(response)


def test_add_optional_fields_may_be_blank(logged_in, user_id):
    response = logged_in.post("/debts/add", data=_form(due_day="", priority=""))
    assert response.status_code == 302
    assert _debt_count(user_id) == 1


def test_add_accepts_sql_injection_name_as_plain_text(logged_in, user_id):
    name = "x'); DROP TABLE debts;--"
    response = logged_in.post("/debts/add", data=_form(name=name))
    assert response.status_code == 302
    assert db.get_debts(user_id)[0]["name"] == name


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("name", "", "Name is required."),
        ("name", "   ", "Name is required."),
        ("name", "a" * 61, "Name must be 60 characters or fewer."),
    ],
)
def test_add_name_errors(logged_in, user_id, field, value, message):
    response = logged_in.post("/debts/add", data=_form(**{field: value}))
    assert response.status_code == 200
    assert message in _html(response)
    assert _debt_count(user_id) == 0


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"debt_type": "Bogus"}, "Please choose a debt type."),
        ({"debt_type": ""}, "Please choose a debt type."),
        ({"balance": ""}, "Balance is required."),
        ({"balance": "abc"}, "Balance must be a number."),
        ({"balance": "-1"}, "Balance must be greater than zero."),
        ({"balance": "100000001"}, "Balance must not exceed ₹100,000,000."),
        ({"apr": ""}, "APR is required."),
        ({"apr": "-1"}, "APR must be between 0 and 100."),
        ({"apr": "101"}, "APR must be between 0 and 100."),
        ({"apr": "abc"}, "APR must be a number."),
        ({"min_payment": "0"}, "Minimum payment must be greater than zero."),
        ({"min_payment": "-5"}, "Minimum payment must be greater than zero."),
        ({"min_payment": "100000001"}, "Minimum payment must not exceed ₹100,000,000."),
        ({"min_payment": "abc"}, "Minimum payment must be a number."),
        ({"due_day": "0"}, "Due day must be a whole number from 1 to 31."),
        ({"due_day": "32"}, "Due day must be a whole number from 1 to 31."),
        ({"due_day": "abc"}, "Due day must be a whole number from 1 to 31."),
        ({"priority": "0"}, "Priority must be a whole number from 1 to 99."),
        ({"priority": "100"}, "Priority must be a whole number from 1 to 99."),
        ({"priority": "abc"}, "Priority must be a whole number from 1 to 99."),
    ],
)
def test_add_invalid_input_rerenders_without_creating(
    logged_in, user_id, overrides, message
):
    response = logged_in.post("/debts/add", data=_form(**overrides))
    assert response.status_code == 200, f"{overrides} should re-render"
    assert message in _html(response)
    assert _debt_count(user_id) == 0, f"{overrides} must not create a debt"


@pytest.mark.parametrize("debt_type", db.DEBT_TYPES)
def test_add_accepts_every_debt_type(logged_in, user_id, debt_type):
    response = logged_in.post("/debts/add", data=_form(debt_type=debt_type))
    assert response.status_code == 302
    assert db.get_debts(user_id)[0]["debt_type"] == debt_type


# ------------------------------------------------------------------ #
# Edit
# ------------------------------------------------------------------ #


def test_edit_get_prefills_form(logged_in, user_id):
    debt_id = _seed(user_id, name="Prefilled")
    response = logged_in.get(f"/debts/{debt_id}/edit")
    html = _html(response)
    assert response.status_code == 200
    assert 'value="50000.00"' in html
    assert "Prefilled" in html


def test_edit_valid_updates_and_flashes(logged_in, user_id):
    debt_id = _seed(user_id)
    response = logged_in.post(
        f"/debts/{debt_id}/edit", data=_form(name="Renamed", apr="12")
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/debts"
    debt = db.get_debt(debt_id, user_id)
    assert debt["name"] == "Renamed"
    assert debt["apr"] == 12
    page = logged_in.get("/debts")
    assert page.status_code == 200


def test_edit_valid_shows_flash_after_redirect(logged_in, user_id):
    debt_id = _seed(user_id)
    response = logged_in.post(
        f"/debts/{debt_id}/edit", data=_form(), follow_redirects=True
    )
    assert "Debt updated." in _html(response)


def test_edit_raising_balance_raises_original_balance(logged_in, user_id):
    debt_id = _seed(user_id, balance=50000)
    logged_in.post(f"/debts/{debt_id}/edit", data=_form(balance="60000"))
    debt = db.get_debt(debt_id, user_id)
    assert debt["balance"] == 60000
    assert debt["original_balance"] == 60000


def test_edit_invalid_rerenders_and_keeps_data(logged_in, user_id):
    debt_id = _seed(user_id, name="Keep")
    response = logged_in.post(f"/debts/{debt_id}/edit", data=_form(name=""))
    assert response.status_code == 200
    assert "Name is required." in _html(response)
    assert db.get_debt(debt_id, user_id)["name"] == "Keep"


def test_edit_missing_debt_returns_404(logged_in):
    assert logged_in.get("/debts/9999/edit").status_code == 404
    assert logged_in.post("/debts/9999/edit", data=_form()).status_code == 404


# ------------------------------------------------------------------ #
# Delete
# ------------------------------------------------------------------ #


def test_delete_removes_row_and_flashes(logged_in, user_id):
    debt_id = _seed(user_id)
    response = logged_in.post(f"/debts/{debt_id}/delete", follow_redirects=True)
    assert response.status_code == 200
    assert "Debt deleted." in _html(response)
    assert db.get_debt(debt_id, user_id) is None
    assert _debt_count(user_id) == 0


def test_delete_redirects_to_debts(logged_in, user_id):
    debt_id = _seed(user_id)
    response = logged_in.post(f"/debts/{debt_id}/delete")
    assert response.status_code == 302
    assert response.headers["Location"] == "/debts"


def test_delete_get_is_405_and_keeps_row(logged_in, user_id):
    debt_id = _seed(user_id)
    assert logged_in.get(f"/debts/{debt_id}/delete").status_code == 405
    assert db.get_debt(debt_id, user_id) is not None


def test_delete_missing_debt_returns_404(logged_in):
    assert logged_in.post("/debts/9999/delete").status_code == 404


# ------------------------------------------------------------------ #
# Ownership
# ------------------------------------------------------------------ #


def test_other_users_debt_edit_get_returns_404(logged_in, other_user_id):
    debt_id = _seed(other_user_id)
    assert logged_in.get(f"/debts/{debt_id}/edit").status_code == 404


def test_other_users_debt_edit_post_returns_404_and_unchanged(logged_in, other_user_id):
    debt_id = _seed(other_user_id, name="Theirs")
    response = logged_in.post(f"/debts/{debt_id}/edit", data=_form(name="Hacked"))
    assert response.status_code == 404
    assert db.get_debt(debt_id, other_user_id)["name"] == "Theirs"


def test_other_users_debt_delete_returns_404_and_keeps_row(logged_in, other_user_id):
    debt_id = _seed(other_user_id)
    response = logged_in.post(f"/debts/{debt_id}/delete")
    assert response.status_code == 404
    assert db.get_debt(debt_id, other_user_id) is not None


# ------------------------------------------------------------------ #
# Settings
# ------------------------------------------------------------------ #


def test_settings_valid_persists_and_flashes(logged_in, user_id):
    response = logged_in.post(
        "/debts/settings",
        data={"extra_payment": "5000", "strategy": "snowball"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/debts/plan"
    settings = db.get_debt_settings(user_id)
    assert settings["extra_payment"] == 5000.0
    assert settings["strategy"] == "snowball"


def test_settings_valid_shows_flash(logged_in):
    response = logged_in.post(
        "/debts/settings",
        data={"extra_payment": "5000", "strategy": "avalanche"},
        follow_redirects=True,
    )
    assert "Plan updated." in _html(response)


def test_settings_value_shown_on_page_after_save(logged_in, user_id):
    _seed(user_id)
    logged_in.post(
        "/debts/settings", data={"extra_payment": "5000", "strategy": "avalanche"}
    )
    html = _html(logged_in.get("/debts/plan"))
    assert 'value="5000.00"' in html


def test_settings_defaults_without_saved_row(logged_in, user_id):
    settings = db.get_debt_settings(user_id)
    assert settings["extra_payment"] == 0
    assert settings["strategy"] == "avalanche"


@pytest.mark.parametrize(
    "data, message",
    [
        ({"extra_payment": "-1", "strategy": "snowball"}, "Extra payment cannot be negative."),
        ({"extra_payment": "100000001", "strategy": "snowball"}, "Extra payment must not exceed ₹100,000,000."),
        ({"extra_payment": "abc", "strategy": "snowball"}, "Extra payment must be a number."),
        ({"extra_payment": "100", "strategy": "bogus"}, "Please choose a strategy."),
        ({"extra_payment": "100", "strategy": ""}, "Please choose a strategy."),
    ],
)
def test_settings_invalid_rerenders_200_and_not_saved(
    logged_in, user_id, data, message
):
    _seed(user_id)
    response = logged_in.post("/debts/settings", data=data)
    assert response.status_code == 200, f"{data} should re-render"
    assert message in _html(response)
    settings = db.get_debt_settings(user_id)
    assert settings["extra_payment"] == 0, "Invalid settings must not persist"
    assert settings["strategy"] == "avalanche"


def test_settings_are_per_user(logged_in, user_id, other_user_id):
    logged_in.post(
        "/debts/settings", data={"extra_payment": "700", "strategy": "custom"}
    )
    other = db.get_debt_settings(other_user_id)
    assert other["extra_payment"] == 0
    assert other["strategy"] == "avalanche"


# ------------------------------------------------------------------ #
# Review follow-ups                                                   #
# ------------------------------------------------------------------ #


def test_add_rejected_at_debt_cap(logged_in, user_id, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "MAX_DEBTS_PER_USER", 2)
    _seed(user_id, name="One")
    _seed(user_id, name="Two")
    response = logged_in.post("/debts/add", data=_form(name="Three"))
    assert response.status_code == 200
    assert "You can track up to 2 debts." in _html(response)
    assert len(db.get_debts(user_id)) == 2


def test_session_cookie_is_lax_and_httponly(client, app):
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True


def test_custom_without_priorities_shows_hint(logged_in, user_id):
    _seed(user_id, priority=None)
    html = _html(logged_in.get("/debts/plan", query_string={"strategy": "custom"}))
    assert "No debt has a priority yet" in html
    html = _html(logged_in.get("/debts/plan", query_string={"strategy": "snowball"}))
    assert "No debt has a priority yet" not in html


def test_delete_forms_use_shared_confirm(logged_in, user_id):
    _seed(user_id)
    html = _html(logged_in.get("/debts/plan"))
    assert 'data-confirm="Delete this debt?"' in html
    assert "confirm(" not in html


def test_custom_with_priorities_has_no_hint(logged_in, user_id):
    _seed(user_id, priority=1)
    html = _html(logged_in.get("/debts", query_string={"strategy": "custom"}))
    assert "No debt has a priority yet" not in html
