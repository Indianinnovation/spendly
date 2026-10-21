# Spec: Expense Analytics

## Overview
Step 10 adds a dedicated analytics page for a signed-in user. The profile page
shows totals, recent transactions, and a category breakdown, but it cannot
answer "how is my spending changing?" This step adds `/analytics`, which shows
a month-by-month spending trend, average spend figures, the largest single
expenses, and the busiest category — all computed from the user's existing
expenses. It reuses the date-range filter conventions from Step 6 so the page
is bookmarkable and needs no new tables.

## Depends on
- Step 1: Database setup (`expenses.date` stored as `YYYY-MM-DD` text)
- Step 3: Login / Logout (`session["user_id"]` identifies the user)
- Step 5: Backend routes for profile (`get_expense_summary`, `get_category_totals`)
- Step 6: Date filter (`_parse_date_range`, `_filter_presets`, `_range_label`, `_date_clause`)
- Step 7: Add expense (data to analyse)

## Routes
- `GET /analytics` — analytics page for the signed-in user — logged-in only
  (redirects to `/login` when signed out). Accepts optional `start_date` and
  `end_date` query parameters (`YYYY-MM-DD`, inclusive), same semantics as
  `/profile`.

## Database changes
No database changes. All figures are derived from `expenses` with new read-only
queries in `database/db.py`.

## Templates
- **Create:** `templates/analytics.html` (extends `base.html`)
  - Filter presets and from/to form, error message, and active-range label,
    mirroring `profile.html`.
  - Stat tiles: total spent, number of expenses, average per expense, average
    per active month, busiest category.
  - "Monthly Trend" section: one row per month (oldest first) with the month
    label, ₹ total, and a bar scaled to the largest month.
  - "Largest Expenses" table: top 5 expenses in the range (date, description,
    category badge, amount).
  - Empty state when the range has no expenses.
- **Modify:** `templates/base.html` — add an "Analytics" navbar link (signed-in
  users only) using `url_for('analytics')`.

## Files to change
- `app.py` — add `analytics()` route plus a small private helper to build the
  monthly-trend rows and bar classes; route stays "fetch data, render, done".
- `database/db.py` — add `get_monthly_totals`, `get_top_expenses` (see below).
- `templates/base.html` — navbar link.
- `static/css/style.css` — styles for stat tiles, trend rows, and top-expenses
  table, using existing CSS variables and `.bar-w-N` classes.
- `CLAUDE.md` — add `/analytics` to the implemented routes table and mark
  Step 10 done.

## Files to create
- `templates/analytics.html`
- `tests/test_analytics.py`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — user input is bound with `?`; only fixed SQL fragments may be concatenated (reuse `_date_clause`)
- Passwords hashed with werkzeug (no auth changes in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles — bar widths use `.bar-w-N` classes (N a multiple of 5)
- Use `url_for()` for every link and form action — never hardcode URLs
- DB logic lives in `database/db.py` only; the route never builds SQL
- New helpers take `(user_id, start_date=None, end_date=None)` and always scope by `user_id`
- `get_monthly_totals` groups with `strftime('%Y-%m', date)` and returns rows ordered oldest first
- `get_top_expenses(user_id, limit=5, ...)` orders by `amount DESC, date DESC, id DESC`
- Reuse `_parse_date_range` for validation: invalid or reversed dates show an error and respond 200, never 500
- Divide-by-zero must be impossible: with no expenses, averages are 0 and no bars render
- Currency displays as ₹ with `"₹{:,.0f}"` for tiles and trend rows, `"₹{:,.2f}"` for individual expenses
- Signed-out requests redirect to `/login` before any query runs
- No JavaScript is required

## Tests to write
In `tests/test_analytics.py` (temporary DB from `conftest.py`, never `spendly.db`):
- Signed out: `/analytics` redirects to `/login`, with and without params
- Signed in, no expenses: 200, zero stats, empty-state message
- Monthly totals group correctly across several months and are ordered oldest first
- Average per expense and per active month are correct for known data
- Largest expenses list is capped at 5 and ordered by amount descending
- `start_date` / `end_date` limit every section; boundaries are inclusive
- Invalid date (`start_date=abc`) and reversed range: 200 with an error message
- SQL-injection-style value in a date param is rejected, not executed
- Another user's expenses never appear in any figure
- Navbar shows the Analytics link when signed in and not when signed out

## Definition of done
- [ ] Signed out, `/analytics` redirects to `/login`
- [ ] Signed in, the navbar shows an Analytics link that opens `/analytics`
- [ ] Stat tiles show total, count, average per expense, average per active month, and busiest category
- [ ] Monthly Trend lists each month with expenses, oldest first, with bars scaled to the largest month
- [ ] Largest Expenses shows at most 5 rows, highest amount first
- [ ] Preset buttons and the from/to form filter every section, and the URL carries `?start_date=...&end_date=...`
- [ ] A range with no expenses shows ₹0 stats and an empty-state message with no errors
- [ ] `/analytics?start_date=garbage` shows an error and does not crash
- [ ] Another user's data never appears
- [ ] All amounts display with the ₹ symbol
- [ ] `pytest` passes, including the new `tests/test_analytics.py`
