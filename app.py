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
    create_debt,
    get_debts,
    get_debt,
    update_debt,
    delete_debt as delete_debt_row,
    count_debts,
    get_debt_settings,
    save_debt_settings,
    log_debt_payment,
    get_debt_payments,
    delete_debt_payment,
    CATEGORIES,
    DEBT_TYPES,
)
from planner import (
    BASELINE,
    BASELINE_LABEL,
    MAX_YEARS,
    STRATEGIES,
    STRATEGY_LABELS,
    amortization,
    build_chart,
    compare,
    countdown,
    format_rupees,
    group_series,
    has_priorities,
    interest_warnings,
    order_debts,
    progress_ring,
    simulate,
    total_series,
)

MAX_AMOUNT = 1_000_000
MAX_DESCRIPTION_LENGTH = 200
EXPENSE_FIELDS = ("amount", "category", "date", "description")
MAX_DEBT_AMOUNT = 100_000_000
MAX_DEBT_NAME_LENGTH = 60
# Each planner view runs several 600-month simulations over every debt,
# so the debt count is capped to keep a request's cost bounded.
MAX_DEBTS_PER_USER = 50
PAYMENT_FIELDS = ("amount", "paid_on", "note")
CHART_MODES = {"total": "Balance", "type": "By type", "debt": "By debt"}
DETAIL_TABS = {"overview": "Progress", "amortization": "Amortization"}
MAX_AMORTIZATION_ROWS = 360
MAX_PAYMENT_NOTE_LENGTH = 200
DEBT_FIELDS = (
    "name",
    "debt_type",
    "balance",
    "apr",
    "min_payment",
    "due_day",
    "priority",
)

app = Flask(__name__)
# Without SECRET_KEY a random per-process key is used: sessions stay safe from
# forgery but are logged out on every restart. Set SECRET_KEY for persistence.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
# Lax stops other sites' cross-site POSTs from carrying the session cookie.
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)

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


def _initials(name):
    return "".join(word[0] for word in name.split()[:2]).upper() or "?"


def _first_name(name):
    words = name.split()
    return words[0] if words else "there"


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

    return render_template(
        "profile.html",
        initials=_initials(user["name"]),
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


def _parse_number(raw, label):
    """Return (value, error) for a required finite number rounded to 2 dp.

    Rounding happens before any range check, so values like 0.001 can't
    pass as a zero amount.
    """
    if not raw:
        return None, f"{label} is required."
    try:
        value = float(raw)
    except ValueError:
        return None, f"{label} must be a number."
    if not math.isfinite(value):
        return None, f"{label} must be a number."
    return round(value, 2), None


def _validate_expense_form(form):
    """Return (amount, error); error is None when the form is valid."""
    amount, error = _parse_number(form["amount"], "Amount")
    if error:
        return None, error
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


# ------------------------------------------------------------------ #
# Debt payoff planner                                                 #
# ------------------------------------------------------------------ #


def _parse_optional_int(raw, label, low, high):
    """Return (value, error); a blank field is None."""
    if not raw:
        return None, None
    try:
        value = int(raw)
    except ValueError:
        value = None
    if value is None or not low <= value <= high:
        return None, f"{label} must be a whole number from {low} to {high}."
    return value, None


def _read_debt_form():
    return {name: (request.form.get(name) or "").strip() for name in DEBT_FIELDS}


def _validate_debt_form(form):
    """Return (debt, error); error is None when the form is valid."""
    if not form["name"]:
        return None, "Name is required."
    if len(form["name"]) > MAX_DEBT_NAME_LENGTH:
        return None, f"Name must be {MAX_DEBT_NAME_LENGTH} characters or fewer."
    if form["debt_type"] not in DEBT_TYPES:
        return None, "Please choose a debt type."

    balance, error = _parse_number(form["balance"], "Balance")
    if error:
        return None, error
    if balance <= 0:
        return None, "Balance must be greater than zero."
    if balance > MAX_DEBT_AMOUNT:
        return None, f"Balance must not exceed ₹{MAX_DEBT_AMOUNT:,}."

    apr, error = _parse_number(form["apr"], "APR")
    if error:
        return None, error
    if not 0 <= apr <= 100:
        return None, "APR must be between 0 and 100."

    min_payment, error = _parse_number(form["min_payment"], "Minimum payment")
    if error:
        return None, error
    if min_payment <= 0:
        return None, "Minimum payment must be greater than zero."
    if min_payment > MAX_DEBT_AMOUNT:
        return None, f"Minimum payment must not exceed ₹{MAX_DEBT_AMOUNT:,}."

    due_day, error = _parse_optional_int(form["due_day"], "Due day", 1, 31)
    if error:
        return None, error
    priority, error = _parse_optional_int(form["priority"], "Priority", 1, 99)
    if error:
        return None, error

    return {
        "name": form["name"],
        "debt_type": form["debt_type"],
        "balance": balance,
        "apr": apr,
        "min_payment": min_payment,
        "due_day": due_day,
        "priority": priority,
    }, None


def _validate_debt_settings(form):
    """Return ((extra_payment, strategy), error)."""
    extra, error = _parse_number(form["extra_payment"], "Extra payment")
    if error:
        return None, error
    if extra < 0:
        return None, "Extra payment cannot be negative."
    if extra > MAX_DEBT_AMOUNT:
        return None, f"Extra payment must not exceed ₹{MAX_DEBT_AMOUNT:,}."
    if form["strategy"] not in STRATEGIES:
        return None, "Please choose a strategy."
    return (extra, form["strategy"]), None


def _paid_progress(debt):
    """Return (percent paid, bar class) for a debt's progress bar."""
    original = debt["original_balance"]
    paid = (original - debt["balance"]) / original * 100 if original > 0 else 100
    paid = min(100, max(0, paid))
    return round(paid), f"bar-w-{round(paid / 5) * 5}"


def _build_debt_rows(debt_list, plan):
    payoff = {item["debt_id"]: item["date"] for item in plan["payoff_order"]}
    rows = []
    for debt in order_debts(debt_list, plan["strategy"]):
        paid_pct, bar_class = _paid_progress(debt)
        if debt["balance"] <= 0:
            payoff_label = "Paid off"
        else:
            payoff_label = payoff.get(debt["id"], "Not payable")
        rows.append(
            {
                "id": debt["id"],
                "name": debt["name"],
                "debt_type": debt["debt_type"],
                "badge_class": "badge-" + debt["debt_type"].lower().replace(" ", "-"),
                "balance": format_rupees(debt["balance"]),
                "apr": f"{debt['apr']:g}%",
                "min_payment": format_rupees(debt["min_payment"]),
                "payoff": payoff_label,
                "paid_pct": paid_pct,
                "bar_class": bar_class,
            }
        )
    return rows


def _build_planner_summary(debt_list, plan, baseline):
    saved = max(0, baseline["total_interest"] - plan["total_interest"])
    return {
        "total_debt": format_rupees(sum(debt["balance"] for debt in debt_list)),
        "debt_free_date": plan["debt_free_date"]
        or ("—" if plan["paid_off"] else "Not payable at current payments"),
        "total_interest": format_rupees(plan["total_interest"]),
        "interest_saved": format_rupees(saved),
    }


def _build_comparison_rows(comparison):
    rows = []
    for result in comparison:
        # A plan that hits the month cap is still running when it stops.
        suffix = "" if result["paid_off"] else "+"
        rows.append(
            {
                "label": result["label"],
                "months": f"{result['months']}{suffix} months",
                "debt_free_date": result["debt_free_date"] or "Not payable",
                "total_interest": format_rupees(result["total_interest"]),
                "interest_saved": format_rupees(result["interest_saved"]),
            }
        )
    return rows


def _load_plan(user_id, strategy=None):
    """Debts, settings and simulations shared by every debt page.

    strategy previews a plan without saving it; anything unknown falls back
    to the user's saved strategy.
    """
    settings = get_debt_settings(user_id)
    if strategy not in STRATEGIES:
        strategy = settings["strategy"]
    debt_list = [dict(row) for row in get_debts(user_id)]
    extra = settings["extra_payment"]
    comparison = compare(debt_list, extra)
    by_strategy = {result["strategy"]: result for result in comparison}
    # compare() skips Custom when no debt has a priority, so simulate it here.
    plan = by_strategy.get(strategy) or simulate(debt_list, extra, strategy)
    return {
        "settings": settings,
        "strategy": strategy,
        "debts": debt_list,
        "comparison": comparison,
        "baseline": by_strategy[BASELINE],
        "plan": plan,
    }


def _debt_free_label(plan):
    return plan["debt_free_date"] or ("—" if plan["paid_off"] else "Not payable")


def _duration_label(months):
    years, months = countdown(months)
    parts = []
    if years:
        parts.append(f"{years} year" + ("s" if years != 1 else ""))
    if months or not years:
        parts.append(f"{months} month" + ("s" if months != 1 else ""))
    return " ".join(parts)


def _debt_sidebar(loaded, active, user):
    return {
        "initials": _initials(user["name"]),
        "name": user["name"],
        "debt_free_date": _debt_free_label(loaded["plan"]),
        "active": active,
        "debts": [
            {"id": debt["id"], "name": debt["name"]} for debt in loaded["debts"]
        ],
    }


def _type_slug(debt_type):
    return debt_type.lower().replace(" ", "-")


def _build_type_cards(debt_list):
    totals = {}
    for debt in debt_list:
        group = totals.setdefault(
            debt["debt_type"], {"original_balance": 0.0, "balance": 0.0}
        )
        group["original_balance"] += debt["original_balance"]
        group["balance"] += debt["balance"]
    cards = []
    for debt_type in DEBT_TYPES:
        if debt_type not in totals:
            continue
        paid_pct, bar_class = _paid_progress(totals[debt_type])
        cards.append(
            {
                "debt_type": debt_type,
                "slug": _type_slug(debt_type),
                "balance": format_rupees(totals[debt_type]["balance"]),
                "paid_pct": paid_pct,
                "bar_class": bar_class,
            }
        )
    return cards


def _build_timeline(loaded, mode):
    plan = loaded["plan"]
    if mode == "total":
        series, names = total_series(plan["series"]), {"total": "Total balance"}
    elif mode == "type":
        type_of = {debt["id"]: debt["debt_type"] for debt in loaded["debts"]}
        series = group_series(plan["series"], type_of.get)
        names = {debt_type: debt_type for debt_type in series}
    else:
        series = plan["series"]
        names = {debt["id"]: debt["name"] for debt in loaded["debts"]}
    return build_chart(series, names, plan["labels"])


def _build_impact(loaded):
    plan, base = loaded["plan"], loaded["baseline"]
    labels = max(plan["labels"], base["labels"], key=len)
    chart = build_chart(
        {
            "minimums": total_series(base["series"]).get("total", []),
            "plan": total_series(plan["series"]).get("total", []),
        },
        {"minimums": BASELINE_LABEL, "plan": "Your plan"},
        labels,
        stacked=False,
        # Baseline in a muted colour behind the plan.
        classes=("chart-series-4", "chart-series-0"),
    )
    months_saved = max(0, base["months"] - plan["months"]) if plan["paid_off"] else 0
    return {
        "months_saved": _duration_label(months_saved),
        "interest_saved": format_rupees(
            max(0, base["total_interest"] - plan["total_interest"])
        ),
        "chart": chart,
    }


def _render_home(user_id, chart_mode):
    loaded = _load_plan(user_id)
    debt_list, plan = loaded["debts"], loaded["plan"]
    original = sum(debt["original_balance"] for debt in debt_list)
    balance = sum(debt["balance"] for debt in debt_list)
    paid_pct, _ = _paid_progress({"original_balance": original, "balance": balance})
    paid_pct = paid_pct if original else 0
    years, months = countdown(plan["months"])
    user = get_user_by_id(user_id)
    return render_template(
        "debts.html",
        sidebar=_debt_sidebar(loaded, "home", user),
        has_debts=bool(debt_list),
        first_name=_first_name(user["name"]),
        progress={
            "paid_pct": paid_pct,
            "ring": progress_ring(paid_pct),
            "principal_paid": format_rupees(original - balance),
            "balance": format_rupees(balance),
        },
        countdown={
            "paid_off": plan["paid_off"],
            "month": (plan["debt_free_date"] or "").upper(),
            "years": years,
            "months": months,
        },
        chart_modes=list(CHART_MODES.items()),
        chart_mode=chart_mode,
        timeline=_build_timeline(loaded, chart_mode),
        impact=_build_impact(loaded),
        has_extra=loaded["settings"]["extra_payment"] > 0,
        type_cards=_build_type_cards(debt_list),
        warnings=interest_warnings(debt_list),
        unpayable=bool(debt_list) and not plan["paid_off"],
        max_years=MAX_YEARS,
    )


def _render_planner(user_id, strategy=None, settings_form=None, settings_error=None):
    loaded = _load_plan(user_id, strategy)
    settings, strategy = loaded["settings"], loaded["strategy"]
    debt_list, plan = loaded["debts"], loaded["plan"]
    comparison = loaded["comparison"]
    extra = settings["extra_payment"]
    names = {debt["id"]: debt["name"] for debt in debt_list}

    if settings_form is None:
        settings_form = {
            "extra_payment": f"{extra:.2f}",
            "strategy": settings["strategy"],
        }

    return render_template(
        "debts_plan.html",
        sidebar=_debt_sidebar(loaded, "plan", get_user_by_id(user_id)),
        has_debts=bool(debt_list),
        strategy=strategy,
        strategies=list(STRATEGY_LABELS.items()),
        custom_without_priorities=strategy == "custom"
        and not has_priorities(debt_list),
        summary=_build_planner_summary(debt_list, plan, loaded["baseline"]),
        debt_rows=_build_debt_rows(debt_list, plan),
        comparison=_build_comparison_rows(comparison),
        chart=build_chart(plan["series"], names, plan["labels"]),
        warnings=interest_warnings(debt_list),
        unpayable=bool(debt_list) and not plan["paid_off"],
        max_years=MAX_YEARS,
        settings_form=settings_form,
        settings_error=settings_error,
    )


def _debt_to_form(debt):
    return {
        "name": debt["name"],
        "debt_type": debt["debt_type"],
        "balance": f"{debt['balance']:.2f}",
        "apr": f"{debt['apr']:g}",
        "min_payment": f"{debt['min_payment']:.2f}",
        "due_day": "" if debt["due_day"] is None else str(debt["due_day"]),
        "priority": "" if debt["priority"] is None else str(debt["priority"]),
    }


def _render_debt_form(template, form, error=None, debt_id=None):
    return render_template(
        template, form=form, error=error, debt_types=DEBT_TYPES, debt_id=debt_id
    )


@app.route("/debts")
def debts():
    if not _is_signed_in():
        return redirect(url_for("login"))
    chart_mode = request.args.get("chart")
    if chart_mode not in CHART_MODES:
        chart_mode = "total"
    return _render_home(session["user_id"], chart_mode)


@app.route("/debts/plan")
def debts_plan():
    if not _is_signed_in():
        return redirect(url_for("login"))
    return _render_planner(session["user_id"], request.args.get("strategy"))


@app.route("/debts/add", methods=["GET", "POST"])
def add_debt():
    if not _is_signed_in():
        return redirect(url_for("login"))

    if request.method == "GET":
        return _render_debt_form("add_debt.html", dict.fromkeys(DEBT_FIELDS, ""))

    form = _read_debt_form()
    debt, error = _validate_debt_form(form)
    if not error and count_debts(session["user_id"]) >= MAX_DEBTS_PER_USER:
        error = f"You can track up to {MAX_DEBTS_PER_USER} debts."
    if error:
        return _render_debt_form("add_debt.html", form, error)

    create_debt(user_id=session["user_id"], **debt)
    flash("Debt added.")
    return redirect(url_for("debts"))


@app.route("/debts/<int:debt_id>/edit", methods=["GET", "POST"])
def edit_debt(debt_id):
    if not _is_signed_in():
        return redirect(url_for("login"))

    debt = get_debt(debt_id, session["user_id"])
    if debt is None:
        abort(404)

    if request.method == "GET":
        return _render_debt_form(
            "edit_debt.html", _debt_to_form(debt), debt_id=debt_id
        )

    form = _read_debt_form()
    clean, error = _validate_debt_form(form)
    if error:
        return _render_debt_form("edit_debt.html", form, error, debt_id)

    # The row can vanish between the lookup above and this update.
    if not update_debt(debt_id=debt_id, user_id=session["user_id"], **clean):
        abort(404)
    flash("Debt updated.")
    return redirect(url_for("debts"))


@app.route("/debts/<int:debt_id>/delete", methods=["POST"])
def delete_debt(debt_id):
    if not _is_signed_in():
        return redirect(url_for("login"))
    if get_debt(debt_id, session["user_id"]) is None:
        abort(404)
    if not delete_debt_row(debt_id, session["user_id"]):
        # The row can vanish between the lookup above and this delete.
        abort(404)
    flash("Debt deleted.")
    return redirect(url_for("debts"))


@app.route("/debts/settings", methods=["POST"])
def debt_settings():
    if not _is_signed_in():
        return redirect(url_for("login"))

    form = {
        name: (request.form.get(name) or "").strip()
        for name in ("extra_payment", "strategy")
    }
    settings, error = _validate_debt_settings(form)
    if error:
        return _render_planner(
            session["user_id"], settings_form=form, settings_error=error
        )

    save_debt_settings(session["user_id"], *settings)
    flash("Plan updated.")
    return redirect(url_for("debts_plan"))


def _read_payment_form():
    return {name: (request.form.get(name) or "").strip() for name in PAYMENT_FIELDS}


def _validate_payment_form(form, balance):
    """Return (payment, error); error is None when the form is valid."""
    amount, error = _parse_number(form["amount"], "Amount")
    if error:
        return None, error
    if amount <= 0:
        return None, "Amount must be greater than zero."
    if amount > balance:
        return None, (
            f"Amount can't be more than the current balance ({format_rupees(balance)})."
        )
    if not _is_valid_date(form["paid_on"]):
        return None, "Please enter a valid date (YYYY-MM-DD)."
    if len(form["note"]) > MAX_PAYMENT_NOTE_LENGTH:
        return None, f"Note must be {MAX_PAYMENT_NOTE_LENGTH} characters or fewer."
    return {
        "amount": amount,
        "paid_on": form["paid_on"],
        "note": form["note"] or None,
    }, None


def _build_amortization_rows(debt):
    rows, paid_off = amortization(dict(debt))
    schedule_complete = paid_off and len(rows) <= MAX_AMORTIZATION_ROWS
    table = [
        {
            "label": row["label"],
            "payment": format_rupees(row["payment"], 2),
            "principal": format_rupees(row["principal"], 2),
            "interest": format_rupees(row["interest"], 2),
            "balance": format_rupees(row["balance"], 2),
        }
        for row in rows[:MAX_AMORTIZATION_ROWS]
    ]
    return table, schedule_complete


def _render_debt_detail(debt, form=None, error=None, tab="overview"):
    paid_pct, bar_class = _paid_progress(debt)
    loaded = _load_plan(session["user_id"])
    payments = [
        {
            "id": row["id"],
            "date_label": _format_date(row["paid_on"]),
            "note": row["note"] or "",
            "amount": format_rupees(row["amount"], 2),
        }
        for row in get_debt_payments(debt["id"], session["user_id"])
    ]
    if form is None:
        form = {"amount": "", "paid_on": date.today().isoformat(), "note": ""}
    amortization_rows, schedule_complete = (
        _build_amortization_rows(debt) if tab == "amortization" else ([], True)
    )
    return render_template(
        "debt_detail.html",
        sidebar=_debt_sidebar(
            loaded, f"debt-{debt['id']}", get_user_by_id(session["user_id"])
        ),
        tab=tab,
        tabs=list(DETAIL_TABS.items()),
        ring=progress_ring(paid_pct),
        amortization_rows=amortization_rows,
        schedule_complete=schedule_complete,
        max_amortization_rows=MAX_AMORTIZATION_ROWS,
        debt={
            "id": debt["id"],
            "name": debt["name"],
            "debt_type": debt["debt_type"],
            "badge_class": "badge-" + _type_slug(debt["debt_type"]),
            "slug": _type_slug(debt["debt_type"]),
            "original_balance": format_rupees(debt["original_balance"]),
            "balance": format_rupees(debt["balance"]),
            "paid_so_far": format_rupees(debt["original_balance"] - debt["balance"]),
            "apr": f"{debt['apr']:g}%",
            "min_payment": format_rupees(debt["min_payment"]),
            "is_paid_off": debt["balance"] <= 0,
            "paid_pct": paid_pct,
            "bar_class": bar_class,
        },
        payments=payments,
        form=form,
        error=error,
    )


@app.route("/debts/<int:debt_id>")
def debt_detail(debt_id):
    if not _is_signed_in():
        return redirect(url_for("login"))
    debt = get_debt(debt_id, session["user_id"])
    if debt is None:
        abort(404)
    tab = request.args.get("tab")
    if tab not in DETAIL_TABS:
        tab = "overview"
    return _render_debt_detail(debt, tab=tab)


@app.route("/debts/<int:debt_id>/payments", methods=["POST"])
def log_payment(debt_id):
    if not _is_signed_in():
        return redirect(url_for("login"))
    debt = get_debt(debt_id, session["user_id"])
    if debt is None:
        abort(404)

    form = _read_payment_form()
    payment, error = _validate_payment_form(form, debt["balance"])
    if error:
        return _render_debt_detail(debt, form, error)

    # The debt can vanish between the lookup above and this update.
    if not log_debt_payment(debt_id, session["user_id"], **payment):
        abort(404)
    flash("Payment logged.")
    return redirect(url_for("debt_detail", debt_id=debt_id))


@app.route(
    "/debts/<int:debt_id>/payments/<int:payment_id>/delete", methods=["POST"]
)
def delete_payment(debt_id, payment_id):
    if not _is_signed_in():
        return redirect(url_for("login"))
    if not delete_debt_payment(payment_id, debt_id, session["user_id"]):
        abort(404)
    flash("Payment deleted.")
    return redirect(url_for("debt_detail", debt_id=debt_id))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001)
