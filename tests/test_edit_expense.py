"""Tests for Step 8 - Edit Expense (GET/POST /expenses/<id>/edit).

Based on .claude/specs/08-edit-expense.md. Uses the temporary DB from conftest.py.
"""

import pytest

import database.db as db

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


@pytest.fixture
def expense_id(user_id):
    return db.create_expense(
        user_id, 12.50, "Transport", "2026-09-15", "Old unique cab ride"
    )


@pytest.fixture
def other_expense_id(other_user_id):
    return db.create_expense(
        other_user_id, 99.0, "Bills", "2026-09-01", "Other user secret"
    )


def _url(expense_id):
    return f"/expenses/{expense_id}/edit"


def _rows():
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT id, user_id, amount, category, date, description, created_at "
            "FROM expenses ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _row(expense_id):
    for row in _rows():
        if row["id"] == expense_id:
            return row
    return None


def _snapshot(expense_id):
    return tuple(_row(expense_id))


def _valid(**overrides):
    data = {
        "amount": "250.50",
        "category": "Food",
        "date": "2026-10-10",
        "description": "Updated lunch at cafe",
    }
    data.update(overrides)
    return data


# --- Auth guards -----------------------------------------------------------


def test_get_edit_expense_signed_out_redirects_to_login(client, expense_id):
    response = client.get(_url(expense_id))
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_post_edit_expense_signed_out_redirects_and_changes_nothing(client, expense_id):
    before = _snapshot(expense_id)
    response = client.post(_url(expense_id), data=_valid())
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert _snapshot(expense_id) == before, "Signed-out POST must not change the row"


def test_get_edit_expense_stale_session_redirects_to_login(client, expense_id):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    response = client.get(_url(expense_id))
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_post_edit_expense_stale_session_redirects_and_changes_nothing(
    client, expense_id
):
    before = _snapshot(expense_id)
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    response = client.post(_url(expense_id), data=_valid())
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert _snapshot(expense_id) == before


# --- Profile edit link -----------------------------------------------------


def test_profile_transactions_contain_edit_link_for_expense(
    client, logged_in, expense_id
):
    html = client.get("/profile").get_data(as_text=True)
    assert f'href="{_url(expense_id)}"' in html, "Profile should link to the edit form"


def test_profile_has_edit_link_for_each_expense(client, logged_in, user_id, expense_id):
    second = db.create_expense(user_id, 5.0, "Food", "2026-09-16", "Second one")
    html = client.get("/profile").get_data(as_text=True)
    assert f'href="{_url(expense_id)}"' in html
    assert f'href="{_url(second)}"' in html


# --- GET pre-fill ----------------------------------------------------------


def test_get_edit_expense_returns_form(client, logged_in, expense_id):
    response = client.get(_url(expense_id))
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for name in ("amount", "category", "date", "description"):
        assert f'name="{name}"' in html, f"Form should have a {name} field"


def test_get_edit_expense_prefills_amount(client, logged_in, expense_id):
    html = client.get(_url(expense_id)).get_data(as_text=True)
    assert "12.50" in html, "Amount should be shown as 12.50"


def test_get_edit_expense_prefills_selected_category(client, logged_in, expense_id):
    html = client.get(_url(expense_id)).get_data(as_text=True)
    idx = html.index("Transport")
    assert (
        "selected" in html[max(0, idx - 60) : idx + 60]
    ), "Transport should be selected"


def test_get_edit_expense_prefills_date(client, logged_in, expense_id):
    html = client.get(_url(expense_id)).get_data(as_text=True)
    assert "2026-09-15" in html


def test_get_edit_expense_prefills_description(client, logged_in, expense_id):
    html = client.get(_url(expense_id)).get_data(as_text=True)
    assert "Old unique cab ride" in html


def test_get_edit_expense_lists_all_categories(client, logged_in, expense_id):
    html = client.get(_url(expense_id)).get_data(as_text=True)
    for category in CATEGORIES:
        assert category in html


def test_get_edit_expense_null_description_does_not_render_none(
    client, logged_in, user_id
):
    blank_id = db.create_expense(user_id, 5.0, "Food", "2026-09-02", None)
    response = client.get(_url(blank_id))
    assert response.status_code == 200
    assert b"None" not in response.data


def test_get_edit_expense_does_not_modify_row(client, logged_in, expense_id):
    before = _snapshot(expense_id)
    client.get(_url(expense_id))
    assert _snapshot(expense_id) == before


# --- Valid update ----------------------------------------------------------


def test_post_valid_edit_redirects_to_profile(client, logged_in, expense_id):
    response = client.post(_url(expense_id), data=_valid())
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"


def test_post_valid_edit_updates_row(client, logged_in, expense_id):
    client.post(_url(expense_id), data=_valid())
    row = _row(expense_id)
    assert row["amount"] == pytest.approx(250.50)
    assert row["category"] == "Food"
    assert row["date"] == "2026-10-10"
    assert row["description"] == "Updated lunch at cafe"


def test_post_valid_edit_keeps_user_id_and_created_at(
    client, logged_in, user_id, expense_id
):
    before = _row(expense_id)
    client.post(_url(expense_id), data=_valid())
    after = _row(expense_id)
    assert after["user_id"] == user_id
    assert after["created_at"] == before["created_at"]
    assert after["id"] == before["id"]
    assert len(_rows()) == 1, "Editing must not create or delete rows"


def test_post_valid_edit_shows_flash_message_on_profile(client, logged_in, expense_id):
    response = client.post(_url(expense_id), data=_valid(), follow_redirects=True)
    assert response.status_code == 200
    assert "Expense updated." in response.get_data(as_text=True)


def test_post_valid_edit_reflected_in_profile_list_and_total(
    client, logged_in, expense_id
):
    response = client.post(
        _url(expense_id),
        data=_valid(
            amount="1234", category="Bills", description="Brand new broadband bill"
        ),
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert "Brand new broadband bill" in html
    assert "Old unique cab ride" not in html, "Old description should be gone"
    assert "1,234" in html, "Total/amount should reflect the new amount"
    assert "Bills" in html


@pytest.mark.parametrize("category", CATEGORIES)
def test_post_edit_accepts_every_category(client, logged_in, expense_id, category):
    response = client.post(_url(expense_id), data=_valid(category=category))
    assert response.status_code == 302
    assert _row(expense_id)["category"] == category


@pytest.mark.parametrize("amount", ["1", "0.01", "99999", "12.5", "1000000"])
def test_post_edit_accepts_valid_amounts(client, logged_in, expense_id, amount):
    response = client.post(_url(expense_id), data=_valid(amount=amount))
    assert response.status_code == 302
    assert _row(expense_id)["amount"] == pytest.approx(float(amount))


def test_post_edit_description_is_stripped(client, logged_in, expense_id):
    client.post(_url(expense_id), data=_valid(description="  padded note  "))
    assert _row(expense_id)["description"] == "padded note"


# --- Blank description -----------------------------------------------------


@pytest.mark.parametrize("description", ["", "   "])
def test_post_edit_blank_description_is_stored_as_null(
    client, logged_in, expense_id, description
):
    response = client.post(_url(expense_id), data=_valid(description=description))
    assert response.status_code == 302
    assert _row(expense_id)["description"] is None


def test_post_edit_missing_description_field_is_accepted(client, logged_in, expense_id):
    data = _valid()
    del data["description"]
    response = client.post(_url(expense_id), data=data)
    assert response.status_code == 302
    assert _row(expense_id)["description"] is None


# --- Amount validation -----------------------------------------------------


@pytest.mark.parametrize(
    "amount", ["", " ", "0", "0.00", "-5", "abc", "1000001", "nan", "0.001", "0.004"]
)
def test_post_edit_invalid_amount_rerenders_form_and_changes_nothing(
    client, logged_in, expense_id, amount
):
    before = _snapshot(expense_id)
    response = client.post(_url(expense_id), data=_valid(amount=amount))
    assert response.status_code == 200, f"Amount {amount!r} should re-render the form"
    assert 'name="amount"' in response.get_data(as_text=True)
    assert _snapshot(expense_id) == before, f"Amount {amount!r} must not update the row"


def test_post_edit_missing_amount_field_changes_nothing(client, logged_in, expense_id):
    before = _snapshot(expense_id)
    data = _valid()
    del data["amount"]
    response = client.post(_url(expense_id), data=data)
    assert response.status_code == 200
    assert _snapshot(expense_id) == before


def test_post_edit_invalid_amount_shows_error_message(client, logged_in, expense_id):
    html = client.post(_url(expense_id), data=_valid(amount="-5")).get_data(
        as_text=True
    )
    assert "amount" in html.lower()
    assert (
        "must" in html.lower() or "valid" in html.lower() or "greater" in html.lower()
    )


# --- Category validation ---------------------------------------------------


@pytest.mark.parametrize(
    "category", ["", "Groceries", "food", "Rent", "'; DROP TABLE expenses;--"]
)
def test_post_edit_invalid_category_rerenders_form_and_changes_nothing(
    client, logged_in, expense_id, category
):
    before = _snapshot(expense_id)
    response = client.post(_url(expense_id), data=_valid(category=category))
    assert response.status_code == 200, f"Category {category!r} should be rejected"
    assert _snapshot(expense_id) == before


def test_post_edit_missing_category_field_changes_nothing(
    client, logged_in, expense_id
):
    before = _snapshot(expense_id)
    data = _valid()
    del data["category"]
    response = client.post(_url(expense_id), data=data)
    assert response.status_code == 200
    assert _snapshot(expense_id) == before


# --- Date validation -------------------------------------------------------


@pytest.mark.parametrize(
    "bad_date",
    [
        "",
        "not-a-date",
        "2026-13-01",
        "2026-02-30",
        "10/20/2026",
        "20-10-2026",
        "2026-10",
        "2026-10-10T10:00",
    ],
)
def test_post_edit_invalid_date_rerenders_form_and_changes_nothing(
    client, logged_in, expense_id, bad_date
):
    before = _snapshot(expense_id)
    response = client.post(_url(expense_id), data=_valid(date=bad_date))
    assert response.status_code == 200, f"Date {bad_date!r} should be rejected"
    assert _snapshot(expense_id) == before


def test_post_edit_missing_date_field_changes_nothing(client, logged_in, expense_id):
    before = _snapshot(expense_id)
    data = _valid()
    del data["date"]
    response = client.post(_url(expense_id), data=data)
    assert response.status_code == 200
    assert _snapshot(expense_id) == before


# --- Description length ----------------------------------------------------


def test_post_edit_description_at_limit_is_accepted(client, logged_in, expense_id):
    response = client.post(_url(expense_id), data=_valid(description="x" * 200))
    assert response.status_code == 302
    assert len(_row(expense_id)["description"]) == 200


def test_post_edit_description_over_limit_rejected_and_changes_nothing(
    client, logged_in, expense_id
):
    before = _snapshot(expense_id)
    response = client.post(_url(expense_id), data=_valid(description="x" * 201))
    assert response.status_code == 200
    assert "200 characters" in response.get_data(as_text=True)
    assert _snapshot(expense_id) == before


# --- Entered values preserved after an error -------------------------------


def test_invalid_amount_preserves_entered_values(client, logged_in, expense_id):
    html = client.post(
        _url(expense_id),
        data=_valid(
            amount="abc",
            category="Health",
            date="2026-09-09",
            description="Keep me please",
        ),
    ).get_data(as_text=True)
    assert "abc" in html, "Entered amount should be preserved"
    assert "2026-09-09" in html, "Entered date should be preserved"
    assert "Keep me please" in html, "Entered description should be preserved"
    idx = html.index("Health")
    assert (
        "selected" in html[max(0, idx - 60) : idx + 60]
    ), "Health should remain selected"


def test_invalid_category_preserves_other_inputs(client, logged_in, expense_id):
    html = client.post(
        _url(expense_id),
        data=_valid(
            category="Bogus",
            amount="77.25",
            date="2026-08-08",
            description="Sticky note",
        ),
    ).get_data(as_text=True)
    assert "77.25" in html
    assert "2026-08-08" in html
    assert "Sticky note" in html


def test_invalid_date_preserves_other_inputs(client, logged_in, expense_id):
    html = client.post(
        _url(expense_id),
        data=_valid(date="garbage-date", amount="42", description="Remember this"),
    ).get_data(as_text=True)
    assert "garbage-date" in html
    assert "42" in html
    assert "Remember this" in html


# --- Missing and foreign expenses -> 404 -----------------------------------


def test_get_edit_nonexistent_expense_returns_404(client, logged_in):
    assert client.get(_url(9999)).status_code == 404


def test_post_edit_nonexistent_expense_returns_404(client, logged_in, expense_id):
    before = _snapshot(expense_id)
    assert client.post(_url(9999), data=_valid()).status_code == 404
    assert _snapshot(expense_id) == before


def test_get_edit_other_users_expense_returns_404(client, logged_in, other_expense_id):
    assert client.get(_url(other_expense_id)).status_code == 404


def test_get_edit_other_users_expense_does_not_leak_details(
    client, logged_in, other_expense_id
):
    html = client.get(_url(other_expense_id)).get_data(as_text=True)
    assert "Other user secret" not in html


def test_post_edit_other_users_expense_returns_404_and_leaves_row_unchanged(
    client, logged_in, other_expense_id
):
    before = _snapshot(other_expense_id)
    response = client.post(_url(other_expense_id), data=_valid())
    assert response.status_code == 404
    assert _snapshot(other_expense_id) == before


def test_post_edit_other_users_expense_with_invalid_data_still_404(
    client, logged_in, other_expense_id
):
    before = _snapshot(other_expense_id)
    response = client.post(_url(other_expense_id), data=_valid(amount="abc"))
    assert response.status_code == 404
    assert _snapshot(other_expense_id) == before


def test_post_edit_ignores_user_id_in_form(
    client, logged_in, user_id, other_user_id, expense_id
):
    client.post(_url(expense_id), data=_valid(user_id=str(other_user_id)))
    assert (
        _row(expense_id)["user_id"] == user_id
    ), "Form-supplied user_id must be ignored"


def test_nonexistent_and_foreign_expense_give_same_response_status(
    client, logged_in, other_expense_id
):
    missing = client.get(_url(9999))
    foreign = client.get(_url(other_expense_id))
    assert missing.status_code == foreign.status_code == 404


# --- Isolation between expenses --------------------------------------------


def test_editing_one_expense_leaves_other_untouched(
    client, logged_in, user_id, expense_id
):
    second = db.create_expense(
        user_id, 80.0, "Shopping", "2026-09-20", "Second untouched"
    )
    before_second = _snapshot(second)
    client.post(_url(expense_id), data=_valid())
    assert _snapshot(second) == before_second
    assert _row(expense_id)["description"] == "Updated lunch at cafe"
    assert len(_rows()) == 2


def test_editing_own_expense_leaves_other_users_expense_untouched(
    client, logged_in, expense_id, other_expense_id
):
    before_other = _snapshot(other_expense_id)
    client.post(_url(expense_id), data=_valid())
    assert _snapshot(other_expense_id) == before_other


# --- SQL injection safety --------------------------------------------------


def test_post_edit_sql_injection_in_description_is_stored_literally(
    client, logged_in, expense_id
):
    payload = "x'); DROP TABLE expenses;--"
    response = client.post(_url(expense_id), data=_valid(description=payload))
    assert response.status_code == 302
    assert _row(expense_id)["description"] == payload


# --- Delete is POST-only ---------------------------------------------------


def test_delete_get_is_not_allowed(client, expense_id):
    response = client.get(f"/expenses/{expense_id}/delete")
    assert response.status_code == 405


def test_delete_get_does_not_remove_expense(client, logged_in, expense_id):
    client.get(f"/expenses/{expense_id}/delete")
    assert _row(expense_id) is not None
