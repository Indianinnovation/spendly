import pytest

import database.db as db

EMAIL = "user@example.com"
PASSWORD = "password1"


@pytest.fixture
def user_id(app):
    return db.create_user("Test User", EMAIL, PASSWORD)


def post_login(client, **overrides):
    return client.post("/login", data={"email": EMAIL, "password": PASSWORD, **overrides})


def test_get_login_shows_form(client):
    response = client.get("/login")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'action="/login"' in html


def test_valid_login_redirects_to_profile(client, user_id):
    response = post_login(client)
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    with client.session_transaction() as sess:
        assert sess["user_id"] == user_id


def test_login_email_is_case_and_whitespace_insensitive(client, user_id):
    response = post_login(client, email="  USER@Example.COM ")
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user_id"] == user_id


def test_wrong_password_and_unknown_email_share_error(client, user_id):
    wrong = post_login(client, password="wrong-password")
    unknown = post_login(client, email="nobody@example.com")
    for response in (wrong, unknown):
        assert response.status_code == 200
        assert "Invalid email or password." in response.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "user_id" not in sess


@pytest.mark.parametrize("overrides", [
    {"email": ""},
    {"email": "   "},
    {"password": ""},
])
def test_missing_fields_show_required_error(client, user_id, overrides):
    response = post_login(client, **overrides)
    assert response.status_code == 200
    assert "Email and password are required." in response.get_data(as_text=True)


def test_post_with_no_data_returns_200(client):
    response = client.post("/login")
    assert response.status_code == 200
    assert "Email and password are required." in response.get_data(as_text=True)


def test_error_keeps_email_but_not_password(client, user_id):
    response = post_login(client, password="wrong-password")
    html = response.get_data(as_text=True)
    assert f'value="{EMAIL}"' in html
    assert "wrong-password" not in html


def test_login_page_redirects_when_signed_in(client, user_id):
    post_login(client)
    response = client.get("/login")
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"


def test_login_page_shows_form_for_stale_session(client, app):
    with client.session_transaction() as sess:
        sess["user_id"] = 999
    assert client.get("/login").status_code == 200


def test_login_resets_existing_session(client, user_id):
    with client.session_transaction() as sess:
        sess["junk"] = "leftover"
    post_login(client)
    with client.session_transaction() as sess:
        assert "junk" not in sess
        assert sess["user_id"] == user_id


def test_navbar_when_signed_out(client):
    html = client.get("/terms").get_data(as_text=True)
    assert "Sign in" in html
    assert "Get started" in html
    assert "Sign out" not in html


def test_navbar_when_signed_in(client, user_id):
    post_login(client)
    html = client.get("/terms").get_data(as_text=True)
    assert "Test User" in html
    assert 'href="/logout"' in html
    assert "Get started" not in html


def test_stale_session_is_treated_as_signed_out(client, app):
    with client.session_transaction() as sess:
        sess["user_id"] = 999
    html = client.get("/terms").get_data(as_text=True)
    assert "Sign in" in html
    assert "Sign out" not in html


def test_logout_clears_session_and_flashes_once(client, user_id):
    post_login(client)
    response = client.get("/logout")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        assert "user_id" not in sess

    page = client.get("/login")
    assert "You have been signed out." in page.get_data(as_text=True)
    again = client.get("/login")
    assert "You have been signed out." not in again.get_data(as_text=True)


def test_logout_when_signed_out_redirects(client):
    response = client.get("/logout")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_get_user_by_id(user_id):
    assert db.get_user_by_id(user_id)["email"] == EMAIL
    assert db.get_user_by_id(999) is None
    assert db.get_user_by_id(None) is None


def test_register_redirects_when_signed_in(client, user_id):
    post_login(client)
    for response in (client.get("/register"), client.post("/register")):
        assert response.status_code == 302
        assert response.headers["Location"] == "/profile"


def test_register_shows_form_for_stale_session(client, app):
    with client.session_transaction() as sess:
        sess["user_id"] = 999
    assert client.get("/register").status_code == 200
