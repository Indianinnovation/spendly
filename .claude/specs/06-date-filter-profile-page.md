# Spec: Date Filter for Profile Page

## Overview
Step 6 lets a signed-in user narrow the profile page to a date range. Today
`/profile` always shows all-time totals, the 10 most recent transactions, and
an all-time category breakdown. This step adds a small "from / to" filter form
so the summary stats, transaction list, and category breakdown all reflect only
expenses inside the chosen range. The range is carried in query parameters, so
filtered views are bookmarkable and need no new routes or tables.

## Depends on
- Step 1: Database setup (`expenses.date` stored as `YYYY-MM-DD` text)
- Step 3: Login / Logout (`session["user_id"]` identifies the user)
- Step 4: Profile page static UI
- Step 5: Backend routes for profile (`get_recent_expenses`, `get_expense_summary`, `get_category_totals` exist)

## Routes
No new routes. The existing `GET /profile` route is modified to accept two
optional query parameters (logged-in only, unchanged):
- `start_date` — `YYYY-MM-DD`, inclusive lower bound
- `end_date` — `YYYY-MM-DD`, inclusive upper bound

Either, both, or neither may be supplied. With neither, behaviour is identical
to today (all-time).

## Database changes
No database changes. `expenses.date` already stores ISO `YYYY-MM-DD` text,
which compares correctly as a string.

## Templates
- **Create:** None.
- **Modify:** `templates/profile.html`
  - Add a filter form (`method="get"`, `action="{{ url_for('profile') }}"`) with
    two `<input type="date">` fields (`start_date`, `end_date`), an "Apply"
    button, and a "Clear" link back to `url_for('profile')`. Fields are
    pre-filled with the active range.
  - Show an error message above the stats when the submitted range is invalid.
  - Show a label for the active range (e.g. "Showing 01 Oct 2026 – 19 Oct 2026").
  - Section title "Recent Transactions" stays; the empty-state message should
    read as a filter result when a range is active (e.g. "No transactions in
    this range.").

## Files to change
- `app.py` — in `profile()`, read and validate `start_date` / `end_date`, pass
  them to the query helpers, and pass the active range and any error to the
  template. Add a small private helper (e.g. `_parse_date_range(args)`) that
  returns `(start, end, error)`; route stays "fetch data, render, done".
- `database/db.py` — add optional `start_date=None, end_date=None` parameters to
  `get_recent_expenses`, `get_expense_summary`, and `get_category_totals`. Build
  the `WHERE` clause from fixed SQL fragments and bind the dates as `?`
  parameters.
- `templates/profile.html` — filter form, error and active-range display.
- `static/css/style.css` — styles for the filter form and error message, using
  existing CSS variables.
- `tests/test_profile.py` — date-filter tests (see below).

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — dates are bound with `?`, never formatted into SQL; only fixed SQL fragments may be concatenated
- Passwords hashed with werkzeug (no auth changes in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles
- Use `url_for()` for the form action and Clear link — never hardcode URLs
- Validate dates server-side with `datetime.strptime(value, "%Y-%m-%d")`; never trust the query string
- Invalid or unparseable date → ignore that filter, show an error message, and respond 200 (not a 500)
- `start_date` later than `end_date` → show an error and fall back to the unfiltered view
- Both bounds are inclusive (`date >= start AND date <= end`)
- Filtering must always stay scoped to the signed-in user's `user_id`
- Default helper arguments must keep existing callers and Step 5 tests working unchanged
- The "By Category" bar widths must be computed from the filtered total
- Currency displays as ₹ with `"₹{:,.2f}"`
- No JavaScript is required; the form works as a plain GET submit

## Tests to write
Add to `tests/test_profile.py` (temporary DB from `conftest.py`):
- No params: same results as before (all expenses counted)
- `start_date` only: excludes earlier expenses
- `end_date` only: excludes later expenses
- Both: only expenses inside the range, boundaries inclusive
- Stats (total, count, top category) and category breakdown reflect the range
- Range with no matching expenses: 200, zero stats, empty-state message
- Invalid date string (e.g. `start_date=abc`): 200, error shown, no crash
- `start_date` after `end_date`: 200, error shown, unfiltered data shown
- SQL-injection-style value in a date param is not executed and is rejected as invalid
- Filter never exposes another user's expenses
- Signed out with params still redirects to `/login`

## Definition of done
- [ ] `/profile` with no query params looks and behaves exactly as before
- [ ] The profile page shows a "from" and "to" date input with Apply and Clear controls
- [ ] Choosing a range and clicking Apply updates the URL to `?start_date=...&end_date=...`
- [ ] Total spent, transaction count, and top category reflect only expenses in the range
- [ ] The transaction list shows only expenses in the range, newest first
- [ ] The By Category breakdown reflects only the range, with bars scaled to the filtered total
- [ ] Both boundary dates are included in results
- [ ] The date inputs stay pre-filled with the active range after Apply
- [ ] Clear returns to the unfiltered `/profile`
- [ ] A range with no expenses shows ₹0.00, 0 transactions, and empty-state messages with no errors
- [ ] `/profile?start_date=garbage` shows an error message and does not crash
- [ ] A start date after the end date shows an error and the unfiltered data
- [ ] Signed out, `/profile?start_date=2026-10-01` redirects to `/login`
- [ ] All amounts still display with the ₹ symbol
