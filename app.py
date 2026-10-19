import os
import sqlite3
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash
from database.db import (
    get_db, init_db, seed_db, create_user, get_user_by_email, get_user_by_id,
    get_recent_expenses, get_expense_summary, get_category_totals,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

with app.app_context():
    init_db()
    seed_db()


@app.context_processor
def inject_current_user():
    user_id = session.get("user_id")
    return {"current_user": get_user_by_id(user_id) if user_id else None}


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


def _is_valid_email(email):
    if email.count("@") != 1:
        return False
    local, domain = email.split("@")
    return bool(local) and bool(domain) and "." in domain


def _is_signed_in():
    user_id = session.get("user_id")
    return bool(user_id and get_user_by_id(user_id))


@app.route("/register", methods=["GET", "POST"])
def register():
    if _is_signed_in():
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("register.html")

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    def fail(message):
        return render_template("register.html", error=message, name=name, email=email)

    if not name or not email or not password or not confirm_password:
        return fail("All fields are required.")
    if not _is_valid_email(email):
        return fail("Please enter a valid email address.")
    if len(password) < 8:
        return fail("Password must be at least 8 characters.")
    if password != confirm_password:
        return fail("Passwords do not match.")
    if get_user_by_email(email):
        return fail("An account with that email already exists.")

    try:
        create_user(name, email, password)
    except sqlite3.IntegrityError:
        return fail("An account with that email already exists.")

    flash("Account created. Please sign in.")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if _is_signed_in():
            return redirect(url_for("profile"))
        return render_template("login.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    def fail(message):
        return render_template("login.html", error=message, email=email)

    if not email or not password:
        return fail("Email and password are required.")

    user = get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return fail("Invalid email or password.")

    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for("profile"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.")
    return redirect(url_for("login"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Profile and expense routes                                          #
# ------------------------------------------------------------------ #

def _format_member_since(raw):
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%B %Y")
    except (TypeError, ValueError):
        return ""


def _format_date(raw):
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return raw or ""


@app.route("/profile")
def profile():
    if not _is_signed_in():
        return redirect(url_for("login"))

    user = get_user_by_id(session["user_id"])

    transactions = [
        {
            "date": row["date"],
            "date_label": _format_date(row["date"]),
            "description": row["description"] or "",
            "category": row["category"],
            "amount": row["amount"],
            "badge_class": f"badge-{row['category'].lower()}",
        }
        for row in get_recent_expenses(user["id"])
    ]

    category_rows = get_category_totals(user["id"])
    grand_total = sum(row["total"] for row in category_rows)
    breakdown = [
        {
            "name": row["category"],
            "amount": row["total"],
            "bar_class": f"bar-w-{round(row['total'] / grand_total * 100 / 5) * 5}",
            "color_class": f"fill-{row['category'].lower()}",
        }
        for row in category_rows
    ] if grand_total else []

    summary = get_expense_summary(user["id"])
    stats = {
        "total_spent": summary["total_spent"],
        "count": summary["count"],
        "top_category": breakdown[0]["name"] if breakdown else "—",
    }

    initials = "".join(word[0] for word in user["name"].split()[:2]).upper() or "?"

    return render_template(
        "profile.html",
        initials=initials,
        member_since=_format_member_since(user["created_at"]),
        stats=stats,
        transactions=transactions,
        breakdown=breakdown,
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
