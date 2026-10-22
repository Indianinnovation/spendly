"""Debt payoff simulation: pure functions, no Flask, SQL or I/O.

Debts are plain dicts with id, name, balance, apr, min_payment and priority.
"""

import math
from datetime import date

MAX_MONTHS = 600
MAX_YEARS = MAX_MONTHS // 12
# The user-selectable strategies, in display order; STRATEGIES is derived
# from this so adding one is a single edit.
STRATEGY_LABELS = {
    "snowball": "Snowball",
    "avalanche": "Avalanche",
    "custom": "Custom",
}
STRATEGIES = tuple(STRATEGY_LABELS)
# Baseline used only for comparison: minimums, no extra, no rollover.
BASELINE = "minimums"
BASELINE_LABEL = "Minimums only"
CHART_SERIES = 6


def order_debts(debts, strategy):
    if strategy == "snowball":
        return sorted(debts, key=lambda d: (d["balance"], -d["apr"], d["id"]))
    if strategy == "avalanche":
        return sorted(debts, key=lambda d: (-d["apr"], d["balance"], d["id"]))
    if strategy == "custom":
        return sorted(
            debts,
            key=lambda d: (d["priority"] is None, d["priority"] or 0, d["id"]),
        )
    return list(debts)


def format_rupees(amount, decimals=0):
    return f"₹{amount:,.{decimals}f}"


def monthly_interest(debt):
    return round(debt["balance"] * debt["apr"] / 1200, 2)


def interest_warnings(debts):
    """Names of debts whose minimum payment doesn't cover a month's interest."""
    return [
        debt["name"]
        for debt in debts
        if debt["balance"] > 0
        and debt["apr"] > 0
        and debt["min_payment"] <= monthly_interest(debt)
    ]


def _month_label(start, offset):
    index = start.year * 12 + start.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1).strftime("%b %Y")


def simulate(debts, extra, strategy, start=None, max_months=MAX_MONTHS):
    """Run the plan month by month.

    "minimums" is the baseline: each debt gets only its own minimum, with no
    extra payment and no rollover of freed-up minimums.
    """
    start = start or date.today()
    rollover = strategy != BASELINE
    ordered = [debt for debt in order_debts(debts, strategy) if debt["balance"] > 0]
    balances = {debt["id"]: round(debt["balance"], 2) for debt in ordered}
    series = {debt["id"]: [balances[debt["id"]]] for debt in ordered}
    schedule = {debt["id"]: [] for debt in ordered}
    labels = [_month_label(start, 0)]
    payoff_order = []
    freed = 0.0
    total_interest = 0.0
    total_paid = 0.0
    month = 0

    while any(balances.values()) and month < max_months:
        month += 1
        pool = extra + freed if rollover else 0.0
        paid = {}
        charged = {}

        for debt in ordered:
            balance = balances[debt["id"]]
            if not balance:
                continue
            interest = round(balance * debt["apr"] / 1200, 2)
            balance += interest
            payment = min(debt["min_payment"], balance)
            balances[debt["id"]] = round(balance - payment, 2)
            paid[debt["id"]] = payment
            charged[debt["id"]] = interest
            total_interest += interest
            total_paid += payment
            if rollover:
                # A debt closing this month leaves part of its minimum unused.
                pool += debt["min_payment"] - payment

        for debt in ordered:
            if pool < 0.005:
                break
            balance = balances[debt["id"]]
            if not balance:
                continue
            payment = min(pool, balance)
            balances[debt["id"]] = round(balance - payment, 2)
            paid[debt["id"]] = paid.get(debt["id"], 0.0) + payment
            pool -= payment
            total_paid += payment

        for debt in ordered:
            if balances[debt["id"]] < 0.005:
                balances[debt["id"]] = 0.0
            closed = not balances[debt["id"]]
            if closed and series[debt["id"]][-1]:
                payoff_order.append(
                    {
                        "debt_id": debt["id"],
                        "name": debt["name"],
                        "month": month,
                        "date": _month_label(start, month),
                    }
                )
                freed += debt["min_payment"]
            series[debt["id"]].append(balances[debt["id"]])
            if debt["id"] in paid:
                payment = round(paid[debt["id"]], 2)
                interest = charged[debt["id"]]
                schedule[debt["id"]].append(
                    {
                        "label": _month_label(start, month),
                        "payment": payment,
                        "interest": interest,
                        "principal": round(payment - interest, 2),
                        "balance": balances[debt["id"]],
                    }
                )
        labels.append(_month_label(start, month))

    paid_off = not any(balances.values())
    return {
        "strategy": strategy,
        "label": STRATEGY_LABELS.get(strategy, BASELINE_LABEL),
        "months": month,
        "debt_free_date": _month_label(start, month) if paid_off and month else None,
        "total_interest": round(total_interest, 2),
        "total_paid": round(total_paid, 2),
        "payoff_order": payoff_order,
        "series": series,
        "schedule": schedule,
        "labels": labels,
        "paid_off": paid_off,
    }


def amortization(debt, start=None):
    """Month-by-month rows for one debt paid at its own minimum."""
    result = simulate([debt], 0, BASELINE, start)
    return result["schedule"].get(debt["id"], []), result["paid_off"]


def countdown(months):
    """Split a month count into (years, months)."""
    return divmod(months, 12)


def progress_ring(pct, radius=36):
    """Geometry for an SVG progress ring drawn with stroke-dasharray."""
    circumference = round(2 * math.pi * radius, 2)
    pct = min(100, max(0, pct))
    return {
        "radius": radius,
        "size": radius * 2 + 16,
        "centre": radius + 8,
        "circumference": circumference,
        "dash": round(circumference * pct / 100, 2),
    }


def total_series(series):
    """Sum every debt's balance month by month into one series."""
    if not series:
        return {}
    return {"total": [round(sum(month), 2) for month in zip(*series.values())]}


def group_series(series, key_of):
    """Sum debt series into groups, e.g. by debt type; keeps first-seen order."""
    grouped = {}
    for debt_id, values in series.items():
        key = key_of(debt_id)
        if key in grouped:
            grouped[key] = [round(a + b, 2) for a, b in zip(grouped[key], values)]
        else:
            grouped[key] = list(values)
    return grouped


def has_priorities(debts):
    return any(debt["priority"] is not None for debt in debts)


def compare(debts, extra, start=None):
    """Every strategy plus the minimums-only baseline, which comes last."""
    strategies = ["snowball", "avalanche"]
    if has_priorities(debts):
        strategies.append("custom")
    base = simulate(debts, extra, BASELINE, start)
    results = [simulate(debts, extra, s, start) for s in strategies] + [base]
    for result in results:
        result["interest_saved"] = max(
            0.0, round(base["total_interest"] - result["total_interest"], 2)
        )
        result["months_saved"] = max(0, base["months"] - result["months"])
    return results


def build_chart(
    series,
    names,
    labels,
    width=600,
    height=240,
    max_points=120,
    stacked=True,
    classes=None,
):
    """Area chart geometry for an inline <svg>, or None if empty.

    Stacked layers sit on top of each other; overlaid layers (stacked=False)
    each start from the baseline. Shorter series are padded with zeros.
    `classes` optionally gives one CSS class per layer, in series order.
    """
    if not series:
        return None
    count = max(len(values) for values in series.values())
    if not count:
        return None
    series = {
        key: list(values) + [0.0] * (count - len(values))
        for key, values in series.items()
    }
    step = max(1, math.ceil(count / max_points))
    columns = list(range(0, count, step))
    if columns[-1] != count - 1:
        columns.append(count - 1)

    left, right, top, bottom = 72, 12, 12, 28
    plot_w = width - left - right
    plot_h = height - top - bottom
    base_y = top + plot_h

    stacks = []
    running = [0.0] * len(columns)
    for debt_id in series:
        values = [series[debt_id][col] for col in columns]
        if stacked:
            running = [total + value for total, value in zip(running, values)]
            stacks.append(running)
        else:
            stacks.append(values)
    peak = max(max(stack) for stack in stacks) or 1.0

    span = max(1, len(columns) - 1)
    xs = [round(left + plot_w * i / span, 1) for i in range(len(columns))]

    def y(value):
        return round(base_y - plot_h * value / peak, 1)

    layers = []
    below = [0.0] * len(columns)
    for index, (debt_id, stack) in enumerate(zip(series, stacks)):
        upper = [f"{x},{y(v)}" for x, v in zip(xs, stack)]
        lower = [f"{x},{y(v)}" for x, v in zip(reversed(xs), reversed(below))]
        layers.append(
            {
                "name": names.get(debt_id, ""),
                "points": " ".join(upper + lower),
                "cls": (
                    classes[index]
                    if classes
                    else f"chart-series-{index % CHART_SERIES}"
                ),
            }
        )
        if stacked:
            below = stack

    y_ticks = [
        {"y": y(peak * k / 3), "label": format_rupees(peak * k / 3)}
        for k in range(4)
    ]
    middle = len(columns) // 2
    x_labels = [
        {"x": xs[i], "label": labels[columns[i]], "anchor": anchor}
        for i, anchor in ((0, "start"), (middle, "middle"), (len(columns) - 1, "end"))
    ]
    return {
        "width": width,
        "height": height,
        "left": left,
        "right": width - right,
        "top": top,
        "base_y": base_y,
        "label_y": height - 8,
        "layers": layers,
        "y_ticks": y_ticks,
        "x_labels": x_labels,
    }
