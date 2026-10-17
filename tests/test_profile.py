import pathlib
import re

import pytest

import database.db as db


@pytest.fixture
def user_id(app):
    return db.create_user("Test User", "user@example.com", "password1")


@pytest.fixture
def logged_in(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_profile_redirects_anonymous_to_login(client):
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_profile_redirects_when_session_user_deleted(client, app):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_profile_ok_when_logged_in(client, logged_in):
    assert client.get("/profile").status_code == 200


def test_profile_shows_real_user_identity(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    assert "Test User" in html
    assert "user@example.com" in html
    assert "Member since" in html
    assert ">TU<" in html


def test_profile_has_three_stats(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    for label in ("Total spent", "Transactions", "Top category"):
        assert label in html
    assert re.search(r"₹[\d,]+", html)


def test_profile_transactions_table(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    body = html.split("<tbody>")[1].split("</tbody>")[0]
    assert body.count("<tr>") >= 3
    assert "badge-" in body


def test_profile_breakdown_bar_widths_valid(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    assert html.count("breakdown-fill") >= 3
    widths = [int(w) for w in re.findall(r"breakdown-fill bar-w-(\d+)", html)]
    assert widths
    assert all(w % 5 == 0 and 0 <= w <= 100 for w in widths)


def test_profile_has_no_inline_styles_or_hex(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    assert "style=" not in html
    template = pathlib.Path("templates/profile.html").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", template)


def test_navbar_links_username_to_profile(client, logged_in):
    html = client.get("/profile").get_data(as_text=True)
    assert 'href="/profile" class="nav-user"' in html
