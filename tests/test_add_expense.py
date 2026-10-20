"""Tests for Step 7 - Add Expense (GET/POST /expenses/add).

Based on .claude/specs/07-add-expense.md. Uses the temporary DB from conftest.py.
"""
from datetime import date

import pytest

import database.db as db

URL = "/expenses/add"
CATEGORIES = db.CATEGORIES


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


def _rows():
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT user_id, amount, category, date, description FROM expenses ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _valid(**overrides):
    data = {
        "amount": "250.50",
        "category": "Food",
        "date": "2026-10-10",
        "description": "Lunch at cafe",
    }
    data.update(overrides)
    return data


# --- Auth guards -----------------------------------------------------------

def test_get_add_expense_signed_out_redirects_to_login(client):
    response = client.get(URL)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_post_add_expense_signed_out_redirects_and_saves_nothing(client, user_id):
    response = client.post(URL, data=_valid())
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert _rows() == [], "Signed-out POST must not insert anything"


def test_get_add_expense_stale_session_user_redirects(client, app):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    response = client.get(URL)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


# --- GET form --------------------------------------------------------------

def test_get_add_expense_signed_in_returns_form(client, logged_in):
    response = client.get(URL)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for field in ("amount", "category", "date", "description"):
        assert f'name="{field}"' in html, f"Form missing field {field}"


def test_get_add_expense_lists_all_seven_categories(client, logged_in):
    html = client.get(URL).get_data(as_text=True)
    assert "<select" in html
    for cat in CATEGORIES:
        assert cat in html, f"Category {cat} missing from dropdown"


def test_get_add_expense_date_prefilled_with_today(client, logged_in):
    html = client.get(URL).get_data(as_text=True)
    assert date.today().isoformat() in html


def test_profile_has_add_expense_link(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    assert f'href="{URL}"' in html


# --- Happy path ------------------------------------------------------------

def test_post_valid_expense_redirects_to_profile(client, logged_in):
    response = client.post(URL, data=_valid())
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"


def test_post_valid_expense_saves_row_with_submitted_values(client, logged_in, user_id):
    client.post(URL, data=_valid())
    rows = _rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == user_id
    assert row["amount"] == pytest.approx(250.50)
    assert row["category"] == "Food"
    assert row["date"] == "2026-10-10"
    assert row["description"] == "Lunch at cafe"


def test_post_valid_expense_shows_flash_message_on_profile(client, logged_in):
    response = client.post(URL, data=_valid(), follow_redirects=True)
    assert response.status_code == 200
    with client.session_transaction() as sess:
        # flash message has been consumed by the rendered profile page
        assert not sess.get("_flashes")
    html = response.get_data(as_text=True)
    assert "alert" in html.lower() or "flash" in html.lower() or "added" in html.lower(), (
        "Expected a success message after adding an expense"
    )


def test_new_expense_appears_in_profile_transactions_and_totals(client, logged_in):
    response = client.post(
        URL,
        data=_valid(amount="1234", category="Bills", description="Unique broadband bill"),
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert "Unique broadband bill" in html
    assert "1,234" in html, "Total/amount should reflect the new expense"
    assert "Bills" in html


def test_second_expense_accumulates_in_profile_total(client, logged_in):
    client.post(URL, data=_valid(amount="1000", description="First one"))
    response = client.post(
        URL, data=_valid(amount="500", description="Second one"), follow_redirects=True
    )
    html = response.get_data(as_text=True)
    assert "First one" in html and "Second one" in html
    assert "1,500" in html
    assert len(_rows()) == 2


@pytest.mark.parametrize("category", CATEGORIES)
def test_post_accepts_every_listed_category(client, logged_in, category):
    response = client.post(URL, data=_valid(category=category))
    assert response.status_code == 302
    assert _rows()[0]["category"] == category


@pytest.mark.parametrize("amount", ["1", "0.01", "99999", "12.5"])
def test_post_accepts_positive_amounts(client, logged_in, amount):
    response = client.post(URL, data=_valid(amount=amount))
    assert response.status_code == 302
    assert _rows()[0]["amount"] == pytest.approx(float(amount))


# --- Description handling --------------------------------------------------

def test_post_blank_description_is_accepted(client, logged_in):
    response = client.post(URL, data=_valid(description=""))
    assert response.status_code == 302
    rows = _rows()
    assert len(rows) == 1
    assert not rows[0]["description"], "Blank description should be stored as NULL/empty"


def test_post_whitespace_only_description_stored_blank(client, logged_in):
    response = client.post(URL, data=_valid(description="    "))
    assert response.status_code == 302
    assert not _rows()[0]["description"]


def test_post_missing_description_field_is_accepted(client, logged_in):
    data = _valid()
    del data["description"]
    response = client.post(URL, data=data)
    assert response.status_code == 302
    assert len(_rows()) == 1


def test_post_description_is_stripped(client, logged_in):
    client.post(URL, data=_valid(description="   padded note   "))
    assert _rows()[0]["description"] == "padded note"


# --- Amount validation -----------------------------------------------------

@pytest.mark.parametrize("amount", ["", "   ", "0", "0.00", "-1", "-250.5", "abc", "12abc", "1,000x"])
def test_post_invalid_amount_rerenders_form_and_saves_nothing(client, logged_in, amount):
    response = client.post(URL, data=_valid(amount=amount))
    assert response.status_code == 200, f"Amount {amount!r} should re-render the form"
    assert _rows() == [], f"Amount {amount!r} must not be saved"
    assert 'name="amount"' in response.get_data(as_text=True)


def test_post_missing_amount_field_saves_nothing(client, logged_in):
    data = _valid()
    del data["amount"]
    response = client.post(URL, data=data)
    assert response.status_code == 200
    assert _rows() == []


def test_invalid_amount_shows_an_error_message(client, logged_in):
    html = client.post(URL, data=_valid(amount="-5")).get_data(as_text=True)
    assert "amount" in html.lower()
    assert "error" in html.lower() or "must" in html.lower() or "valid" in html.lower() or "greater" in html.lower()


# --- Category validation ---------------------------------------------------

@pytest.mark.parametrize("category", ["", "Groceries", "food", "Rent", "<script>", "Food; DROP TABLE expenses"])
def test_post_invalid_category_rerenders_form_and_saves_nothing(client, logged_in, category):
    response = client.post(URL, data=_valid(category=category))
    assert response.status_code == 200, f"Category {category!r} should be rejected"
    assert _rows() == []


def test_post_missing_category_field_saves_nothing(client, logged_in):
    data = _valid()
    del data["category"]
    response = client.post(URL, data=data)
    assert response.status_code == 200
    assert _rows() == []


# --- Date validation -------------------------------------------------------

@pytest.mark.parametrize(
    "bad_date",
    ["", "   ", "not-a-date", "2026-13-01", "2026-02-30", "10/20/2026", "20-10-2026", "2026-10", "2026-10-10T10:00"],
)
def test_post_invalid_date_rerenders_form_and_saves_nothing(client, logged_in, bad_date):
    response = client.post(URL, data=_valid(date=bad_date))
    assert response.status_code == 200, f"Date {bad_date!r} should be rejected"
    assert _rows() == []


def test_post_missing_date_field_saves_nothing(client, logged_in):
    data = _valid()
    del data["date"]
    response = client.post(URL, data=data)
    assert response.status_code == 200
    assert _rows() == []


# --- Preserved input after error ------------------------------------------

def test_invalid_amount_preserves_other_inputs(client, logged_in):
    html = client.post(
        URL,
        data=_valid(amount="abc", category="Transport", date="2026-09-09", description="Keep me please"),
    ).get_data(as_text=True)
    assert "abc" in html, "Entered amount should be preserved"
    assert "2026-09-09" in html, "Entered date should be preserved"
    assert "Keep me please" in html, "Entered description should be preserved"


def test_invalid_amount_preserves_selected_category(client, logged_in):
    html = client.post(URL, data=_valid(amount="0", category="Health")).get_data(as_text=True)
    assert "selected" in html
    idx = html.index("Health")
    assert "selected" in html[max(0, idx - 60): idx + 60], "Health should remain selected"


def test_invalid_category_preserves_other_inputs(client, logged_in):
    html = client.post(
        URL,
        data=_valid(category="Bogus", amount="77.25", date="2026-08-08", description="Sticky note"),
    ).get_data(as_text=True)
    assert "77.25" in html
    assert "2026-08-08" in html
    assert "Sticky note" in html


def test_invalid_date_preserves_other_inputs(client, logged_in):
    html = client.post(
        URL,
        data=_valid(date="garbage-date", amount="42", description="Remember this"),
    ).get_data(as_text=True)
    assert "garbage-date" in html
    assert "42" in html
    assert "Remember this" in html


# --- Ownership / DB side effects ------------------------------------------

def test_expense_saved_under_session_user_not_form_user_id(client, logged_in, user_id, other_user_id):
    client.post(URL, data=_valid(user_id=str(other_user_id)))
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["user_id"] == user_id, "Expense must belong to the session user"


def test_expense_not_visible_to_other_user(client, logged_in, other_user_id):
    client.post(URL, data=_valid(description="Private purchase xyz"))
    with client.session_transaction() as sess:
        sess["user_id"] = other_user_id
    html = client.get("/profile").get_data(as_text=True)
    assert "Private purchase xyz" not in html


def test_sql_injection_in_description_stored_literally(client, logged_in):
    payload = "x'); DROP TABLE expenses; --"
    response = client.post(URL, data=_valid(description=payload))
    assert response.status_code == 302
    rows = _rows()  # would raise if the table had been dropped
    assert len(rows) == 1
    assert rows[0]["description"] == payload


def test_very_long_description_does_not_crash(client, logged_in):
    response = client.post(URL, data=_valid(description="a" * 5000))
    assert response.status_code in (302, 200)
    assert len(_rows()) in (0, 1)


def test_failed_post_does_not_affect_existing_rows(client, logged_in):
    client.post(URL, data=_valid(description="Good one"))
    client.post(URL, data=_valid(amount="-3", description="Bad one"))
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["description"] == "Good one"


# --- create_expense helper & CATEGORIES (spec: database/db.py) -------------

def test_db_categories_constant_lists_the_seven_categories():
    assert list(db.CATEGORIES) == [
        "Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other",
    ]


def test_db_create_expense_inserts_row_and_returns_id(user_id):
    new_id = db.create_expense(user_id, 10.0, "Food", "2026-10-01", "Tea")
    assert isinstance(new_id, int) and new_id > 0
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["description"] == "Tea"


# --- Description length cap ------------------------------------------------

def test_description_at_limit_is_accepted(client, logged_in):
    response = client.post(URL, data=_valid(description="x" * 200))
    assert response.status_code == 302
    assert len(_rows()[0]["description"]) == 200


def test_description_over_limit_rejected_and_saves_nothing(client, logged_in):
    response = client.post(URL, data=_valid(description="x" * 201))
    assert response.status_code == 200
    assert "200 characters" in response.get_data(as_text=True)
    assert _rows() == []
