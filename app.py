import math
import os
import secrets
import sqlite3
from datetime import date, datetime

from flask import (
    Flask,
    abort,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from werkzeug.security import check_password_hash
from database.db import (
    get_db,
    init_db,
    seed_db,
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_recent_expenses,
    get_expense_summary,
    get_category_totals,
    get_monthly_totals,
    get_top_expenses,
    create_expense,
    get_expense,
    update_expense,
    delete_expense as delete_expense_row,
    CATEGORIES,
)

MAX_AMOUNT = 1_000_000
MAX_DESCRIPTION_LENGTH = 200
EXPENSE_FIELDS = ("amount", "category", "date", "description")

app = Flask(__name__)
# Without SECRET_KEY a random per-process key is used: sessions stay safe from
# forgery but are logged out on every restart. Set SECRET_KEY for persistence.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

with app.app_context():
    init_db()
    # Skip the demo account (known password) on deployed environments.
    if not os.environ.get("RAILWAY_ENVIRONMENT"):
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


def _parse_date_bound(raw):
    raw = (raw or "").strip()
    if not raw:
        return None, False
    try:
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d"), False
    except ValueError:
        return None, True


def _parse_date_range(args):
    start, start_bad = _parse_date_bound(args.get("start_date"))
    end, end_bad = _parse_date_bound(args.get("end_date"))

    if start_bad or end_bad:
        return start, end, "Please enter dates in YYYY-MM-DD format."
    if start and end and start > end:
        return None, None, "Start date must be on or before the end date."
    return start, end, None


def _months_back_start(today, months):
    index = today.year * 12 + today.month - 1 - months
    return today.replace(year=index // 12, month=index % 12 + 1, day=1)


def _filter_presets(start, end):
    today = date.today()
    end_iso = today.isoformat()
    presets = [
        ("All Time", None, None),
        ("This Month", today.replace(day=1).isoformat(), end_iso),
        ("Last 3 Months", _months_back_start(today, 3).isoformat(), end_iso),
        ("Last 6 Months", _months_back_start(today, 6).isoformat(), end_iso),
    ]
    return [
        {
            "label": label,
            "start": p_start,
            "end": p_end,
            "active": (p_start, p_end) == (start, end),
        }
        for label, p_start, p_end in presets
    ]


def _range_label(start, end):
    if start and end:
        return f"Showing {_format_date(start)} – {_format_date(end)}"
    if start:
        return f"Showing from {_format_date(start)}"
    if end:
        return f"Showing up to {_format_date(end)}"
    return None


@app.route("/profile")
def profile():
    if not _is_signed_in():
        return redirect(url_for("login"))

    user = get_user_by_id(session["user_id"])
    start_date, end_date, date_error = _parse_date_range(request.args)

    transactions = [
        {
            "id": row["id"],
            "date": row["date"],
            "date_label": _format_date(row["date"]),
            "description": row["description"] or "",
            "category": row["category"],
            "amount": row["amount"],
            "badge_class": f"badge-{row['category'].lower()}",
        }
        for row in get_recent_expenses(
            user["id"], start_date=start_date, end_date=end_date
        )
    ]

    category_rows = get_category_totals(user["id"], start_date, end_date)
    grand_total = sum(row["total"] for row in category_rows)
    breakdown = (
        [
            {
                "name": row["category"],
                "amount": row["total"],
                "bar_class": f"bar-w-{round(row['total'] / grand_total * 100 / 5) * 5}",
                "color_class": f"fill-{row['category'].lower()}",
            }
            for row in category_rows
        ]
        if grand_total
        else []
    )

    summary = get_expense_summary(user["id"], start_date, end_date)
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
        start_date=start_date,
        end_date=end_date,
        date_error=date_error,
        range_label=_range_label(start_date, end_date),
        presets=_filter_presets(start_date, end_date),
        is_filtered=bool(start_date or end_date),
    )


def _build_monthly_trend(rows):
    peak = max((row["total"] for row in rows), default=0)
    if peak <= 0:
        return []
    return [
        {
            "label": datetime.strptime(row["month"], "%Y-%m").strftime("%b %Y"),
            "amount": row["total"],
            "bar_class": f"bar-w-{max(5, round(row['total'] / peak * 100 / 5) * 5)}",
        }
        for row in rows
    ]


def _build_analytics_stats(summary, monthly_rows, category_rows):
    total = summary["total_spent"] or 0
    count = summary["count"]
    active_months = len(monthly_rows)
    return {
        "total": total,
        "count": count,
        "avg_expense": total / count if count else 0,
        "avg_month": total / active_months if active_months else 0,
        "busiest_category": category_rows[0]["category"] if category_rows else "—",
    }


@app.route("/analytics")
def analytics():
    if not _is_signed_in():
        return redirect(url_for("login"))

    start_date, end_date, date_error = _parse_date_range(request.args)
    user_id = session["user_id"]

    monthly_rows = get_monthly_totals(user_id, start_date, end_date)
    stats = _build_analytics_stats(
        get_expense_summary(user_id, start_date, end_date),
        monthly_rows,
        get_category_totals(user_id, start_date, end_date),
    )
    top_expenses = [
        {
            "date_label": _format_date(row["date"]),
            "description": row["description"] or "",
            "category": row["category"],
            "amount": row["amount"],
            "badge_class": f"badge-{row['category'].lower()}",
        }
        for row in get_top_expenses(user_id, 5, start_date, end_date)
    ]

    return render_template(
        "analytics.html",
        stats=stats,
        trend=_build_monthly_trend(monthly_rows),
        top_expenses=top_expenses,
        start_date=start_date,
        end_date=end_date,
        date_error=date_error,
        range_label=_range_label(start_date, end_date),
        presets=_filter_presets(start_date, end_date),
        is_filtered=bool(start_date or end_date),
    )


def _is_valid_date(raw):
    try:
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d") == raw
    except ValueError:
        return False


def _render_expense_form(form, error=None):
    return render_template(
        "add_expense.html", form=form, error=error, categories=CATEGORIES
    )


def _render_edit_form(form, expense_id, error=None):
    return render_template(
        "edit_expense.html",
        form=form,
        error=error,
        categories=CATEGORIES,
        expense_id=expense_id,
    )


def _read_expense_form():
    return {name: (request.form.get(name) or "").strip() for name in EXPENSE_FIELDS}


def _validate_expense_form(form):
    """Return (amount, error); error is None when the form is valid."""
    if not form["amount"]:
        return None, "Amount is required."
    try:
        amount = float(form["amount"])
    except ValueError:
        return None, "Amount must be a number."
    if not math.isfinite(amount):
        return None, "Amount must be a number."
    # Round first so values like 0.001 can't pass as a zero amount.
    amount = round(amount, 2)
    if amount <= 0:
        return None, "Amount must be greater than zero."
    if amount > MAX_AMOUNT:
        return None, f"Amount must not exceed ₹{MAX_AMOUNT:,}."
    if form["category"] not in CATEGORIES:
        return None, "Please choose a category."
    if not _is_valid_date(form["date"]):
        return None, "Please enter a date in YYYY-MM-DD format."
    if len(form["description"]) > MAX_DESCRIPTION_LENGTH:
        return (
            None,
            f"Description must be {MAX_DESCRIPTION_LENGTH} characters or fewer.",
        )
    return amount, None


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not _is_signed_in():
        return redirect(url_for("login"))

    if request.method == "GET":
        blank = dict.fromkeys(EXPENSE_FIELDS, "")
        return _render_expense_form({**blank, "date": date.today().isoformat()})

    form = _read_expense_form()
    amount, error = _validate_expense_form(form)
    if error:
        return _render_expense_form(form, error)

    create_expense(
        user_id=session["user_id"],
        amount=amount,
        category=form["category"],
        expense_date=form["date"],
        description=form["description"] or None,
    )
    flash("Expense added.")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if not _is_signed_in():
        return redirect(url_for("login"))

    expense = get_expense(id, session["user_id"])
    if expense is None:
        abort(404)

    if request.method == "GET":
        form = {
            "amount": f"{expense['amount']:.2f}",
            "category": expense["category"],
            "date": expense["date"],
            "description": expense["description"] or "",
        }
        return _render_edit_form(form, id)

    form = _read_expense_form()
    amount, error = _validate_expense_form(form)
    if error:
        return _render_edit_form(form, id, error)

    updated = update_expense(
        expense_id=id,
        user_id=session["user_id"],
        amount=amount,
        category=form["category"],
        expense_date=form["date"],
        description=form["description"] or None,
    )
    # The row can vanish between the lookup above and this update.
    if not updated:
        abort(404)
    flash("Expense updated.")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def delete_expense(id):
    if not _is_signed_in():
        return redirect(url_for("login"))
    if get_expense(id, session["user_id"]) is None:
        abort(404)
    if not delete_expense_row(id, session["user_id"]):
        # The row can vanish between the lookup above and this delete.
        abort(404)
    flash("Expense deleted.")
    return redirect(url_for("profile"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001)
