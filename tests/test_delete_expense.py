"""Tests for Step 9 - Delete Expense (POST /expenses/<id>/delete).

Based on .claude/specs/09-delete-expense.md. Uses the temporary DB from conftest.py.
"""

import pytest
from flask import url_for

import app as app_module
import database.db as db


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
        user_id, 12.50, "Transport", "2026-09-15", "Unique cab ride"
    )


@pytest.fixture
def second_expense_id(user_id):
    return db.create_expense(
        user_id, 40.0, "Health", "2026-09-16", "Unique pharmacy visit"
    )


@pytest.fixture
def other_expense_id(other_user_id):
    return db.create_expense(
        other_user_id, 99.0, "Bills", "2026-09-01", "Other user secret"
    )


def _url(expense_id):
    return f"/expenses/{expense_id}/delete"


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


# --- Auth guards -----------------------------------------------------------


def test_signed_out_post_redirects_to_login(client, expense_id):
    response = client.post(_url(expense_id))
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_signed_out_post_does_not_delete(client, expense_id):
    client.post(_url(expense_id))
    assert _row(expense_id) is not None


def test_stale_session_post_redirects_and_does_not_delete(client, expense_id):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    response = client.post(_url(expense_id))
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert _row(expense_id) is not None


# --- POST only -------------------------------------------------------------


def test_get_returns_405_when_signed_in(client, logged_in, expense_id):
    assert client.get(_url(expense_id)).status_code == 405


def test_get_returns_405_when_signed_out(client, expense_id):
    assert client.get(_url(expense_id)).status_code == 405


def test_get_does_not_delete(client, logged_in, expense_id):
    client.get(_url(expense_id))
    assert _row(expense_id) is not None


# --- Successful delete -----------------------------------------------------


def test_owner_delete_redirects_to_profile(client, logged_in, expense_id):
    response = client.post(_url(expense_id))
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"


def test_owner_delete_removes_row(client, logged_in, expense_id):
    client.post(_url(expense_id))
    assert _row(expense_id) is None


def test_delete_flashes_message(client, logged_in, expense_id):
    response = client.post(_url(expense_id), follow_redirects=True)
    assert "Expense deleted." in response.get_data(as_text=True)


def test_deleted_row_gone_from_profile(client, logged_in, expense_id):
    client.post(_url(expense_id))
    html = client.get("/profile").get_data(as_text=True)
    assert "Unique cab ride" not in html


def test_other_expenses_of_same_user_unaffected(
    client, logged_in, expense_id, second_expense_id
):
    before = tuple(_row(second_expense_id))
    client.post(_url(expense_id))
    assert tuple(_row(second_expense_id)) == before
    assert len(_rows()) == 1


def test_profile_totals_exclude_deleted_expense(
    client, logged_in, user_id, expense_id, second_expense_id
):
    client.post(_url(expense_id))
    summary = db.get_expense_summary(user_id)
    assert summary["count"] == 1
    assert summary["total_spent"] == 40.0


def test_deleting_last_expense_in_category_removes_it_from_breakdown(
    client, logged_in, user_id, expense_id, second_expense_id
):
    client.post(_url(expense_id))
    categories = [row["category"] for row in db.get_category_totals(user_id)]
    assert "Transport" not in categories
    assert "Health" in categories


# --- Missing and foreign expenses ------------------------------------------


def test_missing_expense_returns_404(client, logged_in):
    assert client.post(_url(9999)).status_code == 404


def test_foreign_expense_returns_404(client, logged_in, other_expense_id):
    assert client.post(_url(other_expense_id)).status_code == 404


def test_foreign_expense_is_not_deleted(client, logged_in, other_expense_id):
    before = tuple(_row(other_expense_id))
    client.post(_url(other_expense_id))
    assert tuple(_row(other_expense_id)) == before


def test_delete_ignores_user_id_in_form(
    client, logged_in, other_user_id, other_expense_id
):
    response = client.post(_url(other_expense_id), data={"user_id": other_user_id})
    assert response.status_code == 404
    assert _row(other_expense_id) is not None


def test_row_vanishing_before_delete_returns_404(
    client, logged_in, expense_id, monkeypatch
):
    monkeypatch.setattr(app_module, "delete_expense_row", lambda *args: False)
    assert client.post(_url(expense_id)).status_code == 404


# --- Profile page ----------------------------------------------------------


def test_profile_has_delete_form_per_row(
    client, logged_in, expense_id, second_expense_id
):
    html = client.get("/profile").get_data(as_text=True)
    for eid in (expense_id, second_expense_id):
        assert f'action="/expenses/{eid}/delete"' in html
    assert html.count('class="tx-delete-btn"') == 2


def test_profile_delete_form_uses_post(client, logged_in, expense_id):
    html = client.get("/profile").get_data(as_text=True)
    assert 'method="post" action="/expenses/%d/delete"' % expense_id in html


def test_profile_includes_confirm_script(client, logged_in, expense_id):
    html = client.get("/profile").get_data(as_text=True)
    assert "Delete this expense?" in html


def test_delete_endpoint_resolves(app):
    with app.test_request_context():
        assert url_for("delete_expense", id=3) == "/expenses/3/delete"


# --- DB helper -------------------------------------------------------------


def test_helper_returns_true_for_owner(user_id, expense_id):
    assert db.delete_expense(expense_id, user_id) is True
    assert _row(expense_id) is None


def test_helper_returns_false_for_foreign_user(user_id, other_expense_id):
    assert db.delete_expense(other_expense_id, user_id) is False
    assert _row(other_expense_id) is not None


def test_helper_returns_false_for_missing_id(user_id):
    assert db.delete_expense(9999, user_id) is False
