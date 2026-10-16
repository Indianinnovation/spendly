import sqlite3

import pytest

import database.db as db

VALID = {
    "name": "Test User",
    "email": "Test@Example.com",
    "password": "password1",
    "confirm_password": "password1",
}


def post_register(client, **overrides):
    return client.post("/register", data={**VALID, **overrides})


def test_get_register_shows_form(client):
    response = client.get("/register")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'action="/register"' in html
    assert 'href="/login"' in html


def test_valid_registration_redirects_to_login(client):
    response = post_register(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_success_message_shown_once(client):
    response = client.post("/register", data=VALID, follow_redirects=True)
    assert "Account created. Please sign in." in response.get_data(as_text=True)

    again = client.get("/login")
    assert "Account created" not in again.get_data(as_text=True)


def test_user_stored_lowercase_with_hashed_password(client):
    post_register(client)
    user = db.get_user_by_email("test@example.com")
    assert user is not None
    assert user["name"] == "Test User"
    assert user["password_hash"] != VALID["password"]
    assert user["password_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_duplicate_email_different_casing_rejected(client, user_count):
    post_register(client)
    response = post_register(client, email="test@example.com")
    assert response.status_code == 200
    assert "An account with that email already exists." in response.get_data(as_text=True)
    assert user_count() == 1


def test_mismatched_confirm_password_rejected(client, user_count):
    response = post_register(client, confirm_password="different1")
    assert response.status_code == 200
    assert "Passwords do not match." in response.get_data(as_text=True)
    assert user_count() == 0


def test_empty_confirm_password_rejected(client, user_count):
    response = post_register(client, confirm_password="")
    assert response.status_code == 200
    assert "All fields are required." in response.get_data(as_text=True)
    assert user_count() == 0


def test_short_password_rejected(client, user_count):
    response = post_register(client, password="1234567", confirm_password="1234567")
    assert response.status_code == 200
    assert "Password must be at least 8 characters." in response.get_data(as_text=True)
    assert user_count() == 0


@pytest.mark.parametrize("email", ["foo@bar", "foo", "@x.com", "a@@b.com"])
def test_invalid_email_rejected(client, user_count, email):
    response = post_register(client, email=email)
    assert response.status_code == 200
    assert "Please enter a valid email address." in response.get_data(as_text=True)
    assert user_count() == 0


@pytest.mark.parametrize("field", ["name", "email"])
def test_whitespace_only_field_rejected(client, user_count, field):
    response = post_register(client, **{field: "   "})
    assert response.status_code == 200
    assert "All fields are required." in response.get_data(as_text=True)
    assert user_count() == 0


def test_error_repopulates_name_and_email_but_not_password(client):
    response = post_register(client, password="short", confirm_password="short")
    html = response.get_data(as_text=True)
    assert 'value="Test User"' in html
    assert 'value="test@example.com"' in html
    assert "short" not in html


def test_empty_post_returns_required_error(client):
    response = client.post("/register")
    assert response.status_code == 200
    assert "All fields are required." in response.get_data(as_text=True)


def test_duplicate_race_shows_error_not_500(client, monkeypatch, user_count):
    post_register(client)
    monkeypatch.setattr("app.get_user_by_email", lambda email: None)
    response = post_register(client)
    assert response.status_code == 200
    assert "An account with that email already exists." in response.get_data(as_text=True)
    assert user_count() == 1


def test_create_user_duplicate_raises_integrity_error(app):
    db.create_user("A", "a@example.com", "password1")
    with pytest.raises(sqlite3.IntegrityError):
        db.create_user("B", "a@example.com", "password2")


def test_get_user_by_email_unknown_returns_none(app):
    assert db.get_user_by_email("nobody@example.com") is None
