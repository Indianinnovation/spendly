# Spec: Add Expense

## Overview
Lets a signed-in user record a new expense from a form instead of relying on seeded data. This replaces the Step 7 stub at `/expenses/add`. Until now the profile page only reads expenses; this is the first feature that writes them, so the profile stats, transactions list and category breakdown start reflecting real user input.

## Depends on
- Step 1 — database setup (`expenses` table, `get_db()`)
- Step 3 — login/logout (`session["user_id"]`, `_is_signed_in()`)
- Step 4/5 — profile page and its DB-backed queries (where the new expense appears)

## Routes
- `GET /expenses/add` — render the add-expense form — logged-in (redirect to `/login` when signed out)
- `POST /expenses/add` — validate the form, insert the expense, redirect to `/profile` — logged-in (redirect to `/login` when signed out)

## Database changes
No database changes. The existing `expenses` table already has all required columns. Add one helper to `database/db.py`:
- `create_expense(user_id, amount, category, date, description)` — parameterised `INSERT`, returns the new row id

Also add a module-level `CATEGORIES` list in `database/db.py` (Food, Transport, Bills, Health, Entertainment, Shopping, Other) as the single source of truth for valid categories.

## Templates
- **Create:** `templates/add_expense.html` — form with amount, category (select), date, optional description; extends `base.html`
- **Modify:** `templates/profile.html` — add an "Add expense" link (via `url_for('add_expense')`) near the transactions section

## Files to change
- `app.py` — replace the `add_expense` stub with a GET/POST route; import `create_expense` and `CATEGORIES`
- `database/db.py` — add `CATEGORIES` and `create_expense()`
- `templates/profile.html` — add link to the form
- `static/css/style.css` — any styles needed for the form, reusing existing `.auth-*` / `.form-input` / `.btn-submit` patterns where possible

## Files to create
- `templates/add_expense.html`
- `tests/test_add_expense.py`

## New dependencies
No new dependencies

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never f-strings in SQL
- Passwords hashed with werkzeug (no auth changes in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- DB logic lives in `database/db.py` only, not in the route
- Use `url_for()` for every link and redirect; no hardcoded URLs
- Signed-out requests (GET and POST) redirect to `login`; the expense is always saved for `session["user_id"]`, never a user id taken from the form
- Validation (re-render the form with an error and preserved input, no insert):
  - amount is required, numeric, and greater than 0
  - category must be one of `CATEGORIES`
  - date is required and must be a valid `YYYY-MM-DD`
  - description is optional; strip whitespace and store `NULL`/empty when blank
- Default the date field to today
- On success, `flash` a confirmation and redirect to `profile`
- Do not implement Step 8 (edit) or Step 9 (delete) routes; leave their stubs untouched
- Tests use pytest-flask with the temporary DB from `conftest.py`, never `spendly.db`

## Definition of done
- [ ] Visiting `/expenses/add` while signed out redirects to `/login`
- [ ] Visiting `/expenses/add` while signed in shows the form with a category dropdown listing all 7 categories and the date pre-filled with today
- [ ] Submitting a valid expense redirects to `/profile` with a success message
- [ ] The new expense appears in the profile transactions list, and the total, count and category breakdown update
- [ ] Submitting an empty amount, a zero/negative/non-numeric amount shows an error and saves nothing
- [ ] Submitting an invalid category or malformed date shows an error and saves nothing
- [ ] After a validation error the previously entered values are still in the form
- [ ] A blank description is accepted
- [ ] A POST while signed out redirects to `/login` and saves nothing
- [ ] The profile page has a working "Add expense" link
- [ ] `pytest` passes, including the new `tests/test_add_expense.py`
