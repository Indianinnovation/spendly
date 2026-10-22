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


def _seed(owner_id, name="Visa", balance=50000):
    return db.create_debt(owner_id, name, "Credit Card", balance, 18, 2000, 5, 1)


def _pay_form(**overrides):
    data = {"amount": "12500", "paid_on": "2026-01-15", "note": "January"}
    data.update(overrides)
    return data


def _payment_count(debt_id=None):
    conn = db.get_db()
    try:
        if debt_id is None:
            row = conn.execute("SELECT COUNT(*) FROM debt_payments").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM debt_payments WHERE debt_id = ?",
                (debt_id,),
            ).fetchone()
        return row[0]
    finally:
        conn.close()


def _balance(debt_id, owner_id):
    return db.get_debt(debt_id, owner_id)["balance"]


# ------------------------------------------------------------------ #
# Auth guard
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/debts/1"),
        ("post", "/debts/1/payments"),
        ("post", "/debts/1/payments/1/delete"),
    ],
)
def test_payment_routes_signed_out_redirect_to_login(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 302, "Expected redirect when signed out"
    assert response.headers["Location"].endswith("/login")


# ------------------------------------------------------------------ #
# Detail page
# ------------------------------------------------------------------ #


class TestDetailPage:
    def test_detail_renders_for_owner(self, logged_in, user_id):
        debt_id = _seed(user_id)
        response = logged_in.get(f"/debts/{debt_id}")
        assert response.status_code == 200
        assert "Visa" in _html(response)

    def test_detail_empty_state(self, logged_in, user_id):
        debt_id = _seed(user_id)
        html = _html(logged_in.get(f"/debts/{debt_id}"))
        assert "No payments yet." in html
        assert "0% paid" in html

    def test_detail_missing_debt_404(self, logged_in):
        assert logged_in.get("/debts/9999").status_code == 404

    def test_detail_other_users_debt_404(self, logged_in, other_user_id):
        debt_id = _seed(other_user_id)
        assert logged_in.get(f"/debts/{debt_id}").status_code == 404

    def test_detail_shows_payments_with_rupee_format(self, logged_in, user_id):
        debt_id = _seed(user_id)
        db.log_debt_payment(debt_id, user_id, 12500, "2026-01-15", "Diwali bonus")
        html = _html(logged_in.get(f"/debts/{debt_id}"))
        assert "₹12,500.00" in html
        assert "25% paid" in html
        assert "No payments yet." not in html
        assert "<td>Diwali bonus</td>" in html

    def test_delete_form_has_confirm(self, logged_in, user_id):
        debt_id = _seed(user_id)
        db.log_debt_payment(debt_id, user_id, 1000, "2026-01-15", None)
        html = _html(logged_in.get(f"/debts/{debt_id}"))
        assert 'data-confirm="Delete this payment?"' in html

    def test_unpaid_debt_shows_log_form(self, logged_in, user_id):
        debt_id = _seed(user_id)
        html = _html(logged_in.get(f"/debts/{debt_id}"))
        assert 'name="amount"' in html
        assert "This debt is paid off" not in html

    def test_paid_off_debt_hides_form(self, logged_in, user_id):
        debt_id = _seed(user_id)
        db.log_debt_payment(debt_id, user_id, 50000, "2026-01-15", None)
        html = _html(logged_in.get(f"/debts/{debt_id}"))
        assert "This debt is paid off" in html
        assert 'name="amount"' not in html

    def test_planner_shows_paid_off_and_links_to_detail(self, logged_in, user_id):
        debt_id = _seed(user_id)
        db.log_debt_payment(debt_id, user_id, 50000, "2026-01-15", None)
        html = _html(logged_in.get("/debts"))
        assert "<td>Paid off</td>" in html
        assert f'href="/debts/{debt_id}">Payments</a>' in html


# ------------------------------------------------------------------ #
# Logging payments
# ------------------------------------------------------------------ #


class TestLogPayment:
    def test_log_payment_redirects_and_flashes(self, logged_in, user_id):
        debt_id = _seed(user_id)
        response = logged_in.post(f"/debts/{debt_id}/payments", data=_pay_form())
        assert response.status_code == 302
        assert response.headers["Location"].endswith(f"/debts/{debt_id}")
        page = logged_in.get(f"/debts/{debt_id}")
        assert "Payment logged." in _html(page)

    def test_log_payment_lowers_balance_and_adds_row(self, logged_in, user_id):
        debt_id = _seed(user_id)
        logged_in.post(f"/debts/{debt_id}/payments", data=_pay_form())
        assert _balance(debt_id, user_id) == 37500
        payments = db.get_debt_payments(debt_id, user_id)
        assert len(payments) == 1
        assert payments[0]["amount"] == 12500
        assert payments[0]["paid_on"] == "2026-01-15"
        assert payments[0]["note"] == "January"
        html = _html(logged_in.get(f"/debts/{debt_id}"))
        assert "25% paid" in html

    def test_original_balance_unchanged(self, logged_in, user_id):
        debt_id = _seed(user_id)
        logged_in.post(f"/debts/{debt_id}/payments", data=_pay_form())
        assert db.get_debt(debt_id, user_id)["original_balance"] == 50000

    def test_pay_full_balance_sets_zero(self, logged_in, user_id):
        debt_id = _seed(user_id)
        response = logged_in.post(
            f"/debts/{debt_id}/payments", data=_pay_form(amount="50000")
        )
        assert response.status_code == 302
        assert _balance(debt_id, user_id) == 0

    def test_blank_note_stored_as_null(self, logged_in, user_id):
        debt_id = _seed(user_id)
        logged_in.post(f"/debts/{debt_id}/payments", data=_pay_form(note=""))
        payments = db.get_debt_payments(debt_id, user_id)
        assert len(payments) == 1
        assert payments[0]["note"] is None

    def test_sql_injection_note_stored_literally(self, logged_in, user_id):
        debt_id = _seed(user_id)
        evil = "'); DROP TABLE debt_payments; --"
        logged_in.post(f"/debts/{debt_id}/payments", data=_pay_form(note=evil))
        payments = db.get_debt_payments(debt_id, user_id)
        assert len(payments) == 1
        assert payments[0]["note"] == evil

    def test_note_is_html_escaped(self, logged_in, user_id):
        debt_id = _seed(user_id)
        logged_in.post(
            f"/debts/{debt_id}/payments",
            data=_pay_form(note="<script>alert(1)</script>"),
        )
        html = _html(logged_in.get(f"/debts/{debt_id}"))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_note_of_200_chars_accepted(self, logged_in, user_id):
        debt_id = _seed(user_id)
        response = logged_in.post(
            f"/debts/{debt_id}/payments", data=_pay_form(note="a" * 200)
        )
        assert response.status_code == 302
        assert _payment_count(debt_id) == 1

    @pytest.mark.parametrize(
        "overrides, message",
        [
            ({"amount": ""}, "Amount is required."),
            ({"amount": "abc"}, "Amount must be a number."),
            ({"amount": "0"}, "Amount must be greater than zero."),
            ({"amount": "-5"}, "Amount must be greater than zero."),
            ({"amount": "50001"}, "more than the current balance"),
            ({"paid_on": ""}, "Please enter a valid date (YYYY-MM-DD)."),
            ({"paid_on": "not-a-date"}, "Please enter a valid date (YYYY-MM-DD)."),
            ({"paid_on": "2026-02-30"}, "Please enter a valid date (YYYY-MM-DD)."),
            ({"note": "a" * 201}, "Note must be 200 characters or fewer."),
        ],
    )
    def test_validation_errors_rerender_and_save_nothing(
        self, logged_in, user_id, overrides, message
    ):
        debt_id = _seed(user_id)
        response = logged_in.post(
            f"/debts/{debt_id}/payments", data=_pay_form(**overrides)
        )
        assert response.status_code == 200, "Validation error should re-render"
        assert message in _html(response)
        assert _payment_count(debt_id) == 0
        assert _balance(debt_id, user_id) == 50000

    def test_over_balance_error_shows_current_balance(self, logged_in, user_id):
        debt_id = _seed(user_id)
        html = _html(
            logged_in.post(f"/debts/{debt_id}/payments", data=_pay_form(amount="60000"))
        )
        assert "more than the current balance (₹50,000)." in html

    def test_log_payment_other_users_debt_404(self, logged_in, other_user_id):
        debt_id = _seed(other_user_id)
        response = logged_in.post(f"/debts/{debt_id}/payments", data=_pay_form())
        assert response.status_code == 404
        assert _payment_count(debt_id) == 0
        assert _balance(debt_id, other_user_id) == 50000

    def test_log_payment_missing_debt_404(self, logged_in):
        response = logged_in.post("/debts/9999/payments", data=_pay_form())
        assert response.status_code == 404


# ------------------------------------------------------------------ #
# Deleting payments
# ------------------------------------------------------------------ #


class TestDeletePayment:
    def test_delete_get_is_405(self, logged_in, user_id):
        debt_id = _seed(user_id)
        db.log_debt_payment(debt_id, user_id, 1000, "2026-01-15", None)
        pid = db.get_debt_payments(debt_id, user_id)[0]["id"]
        response = logged_in.get(f"/debts/{debt_id}/payments/{pid}/delete")
        assert response.status_code == 405
        assert _payment_count(debt_id) == 1

    def test_delete_redirects_flashes_and_restores_balance(self, logged_in, user_id):
        debt_id = _seed(user_id)
        db.log_debt_payment(debt_id, user_id, 12500, "2026-01-15", None)
        pid = db.get_debt_payments(debt_id, user_id)[0]["id"]
        assert _balance(debt_id, user_id) == 37500
        response = logged_in.post(f"/debts/{debt_id}/payments/{pid}/delete")
        assert response.status_code == 302
        assert response.headers["Location"].endswith(f"/debts/{debt_id}")
        assert _balance(debt_id, user_id) == 50000
        assert _payment_count(debt_id) == 0
        page = logged_in.get(f"/debts/{debt_id}")
        assert "Payment deleted." in _html(page)

    def test_restore_never_exceeds_original_balance(self, logged_in, user_id):
        debt_id = _seed(user_id)
        db.log_debt_payment(debt_id, user_id, 10000, "2026-01-15", None)
        pid = db.get_debt_payments(debt_id, user_id)[0]["id"]
        conn = db.get_db()
        try:
            conn.execute("UPDATE debts SET balance = ? WHERE id = ?", (49000, debt_id))
            conn.commit()
        finally:
            conn.close()
        logged_in.post(f"/debts/{debt_id}/payments/{pid}/delete")
        assert _balance(debt_id, user_id) == 50000

    def test_delete_via_wrong_debt_404_no_balance_change(self, logged_in, user_id):
        debt_a = _seed(user_id, name="A")
        debt_b = _seed(user_id, name="B")
        db.log_debt_payment(debt_a, user_id, 12500, "2026-01-15", None)
        pid = db.get_debt_payments(debt_a, user_id)[0]["id"]
        response = logged_in.post(f"/debts/{debt_b}/payments/{pid}/delete")
        assert response.status_code == 404
        assert _payment_count(debt_a) == 1
        assert _balance(debt_a, user_id) == 37500
        assert _balance(debt_b, user_id) == 50000

    def test_delete_other_users_payment_404(self, logged_in, user_id, other_user_id):
        debt_id = _seed(other_user_id)
        db.log_debt_payment(debt_id, other_user_id, 12500, "2026-01-15", None)
        pid = db.get_debt_payments(debt_id, other_user_id)[0]["id"]
        response = logged_in.post(f"/debts/{debt_id}/payments/{pid}/delete")
        assert response.status_code == 404
        assert _payment_count(debt_id) == 1
        assert _balance(debt_id, other_user_id) == 37500

    def test_delete_missing_payment_404(self, logged_in, user_id):
        debt_id = _seed(user_id)
        response = logged_in.post(f"/debts/{debt_id}/payments/9999/delete")
        assert response.status_code == 404

    def test_delete_missing_debt_404(self, logged_in):
        response = logged_in.post("/debts/9999/payments/1/delete")
        assert response.status_code == 404


# ------------------------------------------------------------------ #
# Cascade
# ------------------------------------------------------------------ #


def test_deleting_debt_cascades_to_payments(logged_in, user_id):
    debt_id = _seed(user_id)
    db.log_debt_payment(debt_id, user_id, 1000, "2026-01-15", "a")
    db.log_debt_payment(debt_id, user_id, 2000, "2026-01-16", "b")
    assert _payment_count(debt_id) == 2
    response = logged_in.post(f"/debts/{debt_id}/delete")
    assert response.status_code == 302
    assert db.get_debt(debt_id, user_id) is None
    assert _payment_count(debt_id) == 0
    assert _payment_count() == 0


def test_deleting_debt_leaves_other_debts_payments(logged_in, user_id):
    debt_a = _seed(user_id, name="A")
    debt_b = _seed(user_id, name="B")
    db.log_debt_payment(debt_a, user_id, 1000, "2026-01-15", None)
    db.log_debt_payment(debt_b, user_id, 1000, "2026-01-15", None)
    logged_in.post(f"/debts/{debt_a}/delete")
    assert _payment_count(debt_a) == 0
    assert _payment_count(debt_b) == 1
