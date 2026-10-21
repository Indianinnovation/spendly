# Spec: Debt Payoff Planner

## Overview
Step 11 adds a debt payoff planner modelled on debtpayoffplanner.com, the first
step on the roadmap toward a Mint/Monarch-style money app. Up to step 10, Spendly
only tracks money already spent. This step adds the money the user owes.

A signed-in user records each debt: name, type, balance, APR, minimum payment,
optional due day and optional priority. They then choose a payoff strategy:
- **snowball**: smallest balance first
- **avalanche**: highest APR first
- **custom**: by priority

They can also add an extra monthly payment. Spendly runs the plan month by month,
rolling each freed-up minimum into the next debt. It shows:
- the debt-free date, total interest and interest saved compared with paying
  minimums only
- a side-by-side comparison of every strategy
- a stacked-area chart of balances over time, rendered as server-side SVG

Users can log real payments against a debt. Each payment lowers the debt's
balance and shows on the debt's own page with a progress bar.

Delivered in two PRs on this branch's spec:
- **11a**: CRUD, simulation, planner page and chart
- **11b**: payment logging and the debt detail page

## Depends on
- Step 1: Database setup (`get_db()` with `PRAGMA foreign_keys = ON`, `init_db()`)
- Step 3: Login / Logout (`session["user_id"]`, `_is_signed_in()`)
- Step 7 / 8 / 9: Expense CRUD (form validation, flash and 404-ownership patterns to mirror)
- Step 10: Expense analytics (`stat-card`, `.bar-w-N` and `filter-pill` UI patterns)

## Routes
- `GET /debts`: planner page — logged-in
  - Shows summary tiles, strategy pills, the payoff chart, the debt list with
    progress bars, the strategy comparison table and the plan settings form.
  - `?strategy=snowball|avalanche|custom` previews a strategy without saving it.
    An unknown value falls back to the saved strategy.
- `GET /debts/add`: add-debt form — logged-in
- `POST /debts/add`: validate and create a debt, flash "Debt added.", redirect to `/debts` — logged-in
- `GET /debts/<int:debt_id>/edit`: edit form pre-filled — logged-in, owner only (404 otherwise)
- `POST /debts/<int:debt_id>/edit`: validate and update, flash "Debt updated.", redirect to `/debts` — logged-in, owner only
- `POST /debts/<int:debt_id>/delete`: delete the debt and its payments, flash "Debt deleted.", redirect to `/debts` — logged-in, owner only (GET is 405)
- `POST /debts/settings`: save extra monthly payment and default strategy, flash "Plan updated.", redirect to `/debts` — logged-in
- `GET /debts/<int:debt_id>` (11b): debt detail page with progress, payment history and log-payment form — logged-in, owner only
- `POST /debts/<int:debt_id>/payments` (11b): validate and log a payment, flash "Payment logged.", redirect to the detail page — logged-in, owner only
- `POST /debts/<int:debt_id>/payments/<int:payment_id>/delete` (11b): delete a payment and restore the balance, flash "Payment deleted." — logged-in, owner only

Every route redirects to `/login` when signed out, before running any query.

## Database changes
There are three new tables, each created in `init_db()` with
`CREATE TABLE IF NOT EXISTS`. Existing tables are unchanged and no migration is
needed.

```sql
CREATE TABLE IF NOT EXISTS debts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    name             TEXT NOT NULL,
    debt_type        TEXT NOT NULL,
    original_balance REAL NOT NULL,
    balance          REAL NOT NULL,
    apr              REAL NOT NULL,
    min_payment      REAL NOT NULL,
    due_day          INTEGER,
    priority         INTEGER,
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS debt_payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    debt_id    INTEGER NOT NULL REFERENCES debts(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    amount     REAL NOT NULL,
    paid_on    TEXT NOT NULL,          -- YYYY-MM-DD
    note       TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS debt_settings (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id),
    extra_payment REAL NOT NULL DEFAULT 0,
    strategy      TEXT NOT NULL DEFAULT 'avalanche'
);
```

### Constants
These live in `database/db.py`, next to `CATEGORIES`:
- `DEBT_TYPES = ["Credit Card", "Personal Loan", "Car Loan", "Education Loan", "Home Loan", "Other"]`
- `STRATEGIES = ("snowball", "avalanche", "custom")`

### New helpers in `database/db.py`
Every helper is scoped by `user_id` and opens and closes its own connection.
- `create_debt(user_id, name, debt_type, balance, apr, min_payment, due_day, priority)`
  - Sets `original_balance = balance`.
- `get_debts(user_id)`
- `get_debt(debt_id, user_id)`
- `update_debt(debt_id, user_id, ...)` returns a bool.
  - If the new balance is above `original_balance`, raise `original_balance` to match.
- `delete_debt(debt_id, user_id)` returns a bool.
- `get_debt_settings(user_id)` returns `{extra_payment: 0, strategy: "avalanche"}` when the user has no row yet.
- `save_debt_settings(user_id, extra_payment, strategy)` uses `INSERT ... ON CONFLICT(user_id) DO UPDATE`.
- `log_debt_payment(debt_id, user_id, amount, paid_on, note)` (11b) returns a bool.
  - Runs as one transaction.
  - First `UPDATE debts SET balance = MAX(0, balance - ?) WHERE id = ? AND user_id = ?`.
  - If no row was updated, return False. Otherwise insert the payment row.
- `get_debt_payments(debt_id, user_id)` (11b) returns payments newest first.
- `delete_debt_payment(payment_id, debt_id, user_id)` (11b) returns a bool.
  - Adds the amount back to the balance, capped at `original_balance`.

## Templates
- **Create:**
  - `templates/debts.html`: the planner page.
    - Flash message area.
    - Summary tiles: total debt, debt-free date, total interest, and interest
      saved compared with minimums only.
    - Strategy pills, each a `url_for('debts', strategy=...)` link.
    - SVG payoff chart with an HTML legend.
    - Debt list table: name, type badge, balance, APR, minimum, payoff month,
      progress bar, edit/delete actions.
    - Comparison table with one row per strategy plus "Minimums only": months,
      debt-free date, total interest, interest saved.
    - Settings form: extra monthly payment and default strategy.
    - Empty state with an "Add your first debt" link.
    - `.plan-warning` banners in two cases:
      - when a debt's minimum payment doesn't cover its monthly interest
      - when the plan can't finish within 600 months
  - `templates/add_debt.html`: add-debt form (mirrors `add_expense.html`).
  - `templates/edit_debt.html`: edit-debt form, pre-filled.
  - `templates/debt_detail.html` (11b): progress bar, original and current
    balance, payment history table with delete buttons, and the log-payment form.
- **Modify:** `templates/base.html` gets a "Debts" navbar link
  (`url_for('debts')`, class `nav-debts`) next to Analytics. It shows only when
  signed in.

## Files to change
- `database/db.py`: new tables in `init_db()`, `DEBT_TYPES`, `STRATEGIES`, and the debt, settings and payment helpers.
- `app.py`:
  - All new routes.
  - Validators, each returning `(clean, error)` like `_validate_expense_form`:
    `_validate_debt_form`, `_validate_payment_form`, `_validate_debt_settings`.
  - View-model helpers that keep the routes thin: `_build_debt_rows` and `_build_planner_summary`.
- `templates/base.html`: navbar link.
- `static/css/style.css`: new "Debt planner" section.
  - `.payoff-chart`, `.chart-area`, `.chart-axis`, `.chart-tick`, `.chart-legend`, `.chart-swatch`
  - `.chart-series-0` … `.chart-series-5`, using existing variables (`--accent`, `--accent-2`, `--purple`, `--danger`, `--ink-muted`, `--ink-faint`)
  - debt-type badges such as `.badge-credit-card`
  - `.plan-warning`
  - hide `.nav-debts` in the 600px media query, like `.nav-analytics`
- `CLAUDE.md`: add the debt routes to the implemented-routes table and mark Step 11 done.

## Files to create
- `planner.py` (repo root): pure functions with no Flask, SQL or I/O.
  - `order_debts(debts, strategy)` sorts as follows:
    - snowball: balance ascending, then APR descending
    - avalanche: APR descending, then balance ascending
    - custom: priority ascending, blank priorities last, then id
    - `"minimums"`: input order, with rollover turned off
  - `simulate(debts, extra, strategy, start=None, max_months=600)` runs one loop per month:
    1. Add interest of `round(balance * apr / 1200, 2)` to each open debt.
    2. Pay each debt `min(min_payment, balance)`.
    3. Build a pool from the extra payment, the minimums of debts already paid
       off, and any unused part of this month's payments.
    4. Apply the pool down the strategy order, so leftover money moves on to
       the next debt in the same month.
    5. Treat any balance below 0.005 as 0.

    It returns a dict:
    - `months`, `debt_free_date` (`"%b %Y"`), `total_interest`, `total_paid`
    - `payoff_order`: a list of `{debt_id, name, month}`
    - `series`: `{debt_id: [balance per month]}`
    - `paid_off`: False when the 600-month cap is hit
  - `compare(debts, extra)`: runs each strategy plus `"minimums"` and adds
    `interest_saved` and `months_saved` compared with the minimums baseline.
    Custom is included only when at least one debt has a priority.
  - `build_chart(series, names, width=600, height=240, max_points=120)` builds the chart data:
    - stacked-area `points` strings, one polygon per debt
    - downsampled to at most `max_points` columns, always keeping the final month
    - y-axis ticks formatted in ₹, plus start, middle and end month labels
    - coordinates rounded to 1 decimal place
- `templates/debts.html`, `templates/add_debt.html`, `templates/edit_debt.html`, `templates/debt_detail.html`
- `tests/test_planner.py`: unit tests for `planner.py` (no DB)
- `tests/test_debts.py`: route tests (temporary DB via `conftest.py`)

## New dependencies
No new dependencies.

## Rules for implementation
### Data access and security
- No SQLAlchemy or ORMs. Use raw `sqlite3` through `get_db()` only.
- Parameterised queries only, with `?` placeholders. Never put user input in SQL with f-strings.
- Passwords hashed with werkzeug (no auth changes in this step).
- All SQL lives in `database/db.py`. The simulation lives in `planner.py` as pure functions. Routes only fetch data, call the planner, render, and finish.
- Every query is scoped by `user_id`. Another user's debt or payment returns `abort(404)`, never a 403 or a leak of data.

### Templates and styling
- Use CSS variables. Never hardcode hex values.
- All templates extend `base.html`.
- No inline `style=` attributes:
  - Progress bars use `.bar-w-N` (N a multiple of 5).
  - SVG colours come from CSS classes. Geometry attributes (`points`, `x`, `y`, `viewBox`) are allowed.
- Use `url_for()` for every link and form action.
- No JavaScript is required. The chart is static SVG rendered by Jinja.

### Validation
Invalid input re-renders the form with `error=` and responds 200, never 500.
- **Debt form:**
  - name: required, at most 60 characters
  - `debt_type`: must be in `DEBT_TYPES`
  - balance: a finite number, greater than 0 and at most 100,000,000
  - APR: 0 to 100
  - `min_payment`: greater than 0 and at most 100,000,000
  - `due_day`: optional, 1 to 31
  - priority: optional, 1 to 99
- **Payment form (11b):**
  - amount: greater than 0 and at most the current balance
  - `paid_on`: a valid `YYYY-MM-DD` date
  - note: at most 200 characters
- **Settings form:**
  - extra payment: 0 to 100,000,000
  - strategy: must be in `STRATEGIES`

### Planner behaviour
- A minimum payment that doesn't cover the monthly interest is **allowed**, but
  the planner shows a `.plan-warning` naming the debt. The 600-month cap
  guarantees the simulation ends, and in that case the page shows "Not payable
  at current payments" instead of a date.
- A logged payment reduces principal only. Spec it this way and say so in the
  UI hint text.
- The comparison table always shows every strategy, whatever the active or
  saved strategy is.

### Display
- Currency displays as ₹: `"₹{:,.0f}"` for tiles and tables, `"₹{:,.2f}"` for
  individual payments.

## Tests to write
### `tests/test_planner.py`
- ₹1,000 at 0% APR with a ₹100 minimum: 10 months, ₹0 interest.
- A 12% APR single debt matches the hand-computed months and total interest.
- Ordering:
  - avalanche pays the highest APR first
  - snowball pays the smallest balance first
  - custom follows priority
- After a debt is paid off, its minimum rolls over to the next debt.
- Leftover money in a debt's final month is applied to the next debt in the same month.
- Avalanche total interest is less than or equal to snowball total interest.
- `interest_saved` is at least 0 for every strategy.
- A minimum below the monthly interest hits the cap and returns `paid_off=False`.
- An empty debt list returns 0 months.
- `build_chart` downsamples to at most 120 points and returns one polygon per debt.

### `tests/test_debts.py`
- Signed out, every debt route redirects to `/login`.
- The navbar shows the Debts link only when signed in.
- Empty state renders with no debts.
- CRUD happy paths with their flash messages.
- Each validation error message renders with a 200 response.
- Another user's debt returns 404 for view, edit, delete and payment.
- `GET /debts/<id>/delete` returns 405.
- Settings persist across requests.
- `?strategy=` changes the payoff order shown.
- An `<svg` element is present when debts exist.
- Amounts render with ₹.
- (11b) Logging a payment lowers the balance, and deleting it restores the balance.
- (11b) Deleting a debt cascades to its payments.

## Definition of done
- [ ] Signed out, `/debts` and every debt route redirect to `/login`
- [ ] Signed in, the navbar shows a Debts link that opens `/debts`
- [ ] With no debts, `/debts` shows an empty state with an "Add your first debt" link
- [ ] A debt can be added, edited and deleted. Each action shows its flash message.
- [ ] Invalid debt input (blank name, negative balance, APR of 150, unknown type) shows an error and does not crash
- [ ] Summary tiles show total debt, debt-free date, total interest and interest saved, all in ₹
- [ ] Switching between Snowball, Avalanche and Custom changes the payoff order and the debt-free date
- [ ] Raising the extra monthly payment in settings moves the debt-free date earlier and persists after reload
- [ ] The comparison table lists every strategy plus "Minimums only"
- [ ] The SVG payoff chart renders, with one coloured band per debt and a legend
- [ ] A debt whose minimum doesn't cover its interest shows a warning, and an unpayable plan shows "Not payable at current payments"
- [ ] (11b) Logging a payment lowers the balance and updates the progress bar. Deleting the payment restores the balance.
- [ ] (11b) Deleting a debt also removes its payments
- [ ] Another user's debts and payments are never visible or editable (404)
- [ ] `pytest` passes, including `tests/test_planner.py` and `tests/test_debts.py`
