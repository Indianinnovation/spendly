# Spec: Edit Expense

## Overview
Lets a signed-in user correct an existing expense (amount, category, date, description) from a pre-filled form. This replaces the Step 8 stub at `/expenses/<id>/edit`. Step 7 made it possible to add expenses; this step closes the loop by letting users fix mistakes, and the profile stats, transactions list and category breakdown reflect the change immediately. Each row in the profile transactions table gains an "Edit" link so the form is reachable.

## Depends on
- Step 1 — database setup (`expenses` table, `get_db()`)
- Step 3 — login/logout (`session["user_id"]`, `_is_signed_in()`)
- Step 4/5 — profile page and its DB-backed queries (where the edit link lives and changes show up)
- Step 7 — add expense (`CATEGORIES`, `_validate_expense_form`, expense form template pattern)

## Routes
- `GET /expenses/<int:id>/edit` — render the form pre-filled with the expense's current values — logged-in, owner only (redirect to `/login` when signed out; 404 when the expense does not exist or belongs to another user)
- `POST /expenses/<int:id>/edit` — validate the form, update the expense, redirect to `/profile` — logged-in, owner only (same redirect/404 rules)

## Database changes
No schema changes. The existing `expenses` table already has all required columns. Add two helpers to `database/db.py`:
- `get_expense(expense_id, user_id)` — parameterised `SELECT id, amount, category, date, description ... WHERE id = ? AND user_id = ?`; returns the row or `None`
- `update_expense(expense_id, user_id, amount, category, expense_date, description)` — parameterised `UPDATE ... WHERE id = ? AND user_id = ?`; returns `True` if a row was updated, `False` otherwise

Scoping both queries by `user_id` is what enforces ownership; the route never relies on the id alone.

## Templates
- **Create:** `templates/edit_expense.html` — same fields as `add_expense.html` (amount, category select, date, optional description), posts to `url_for('edit_expense', id=expense_id)`, title "Edit expense", submit button "Save changes"; extends `base.html`
- **Modify:** `templates/profile.html` — add an "Edit" link per transaction row via `url_for('edit_expense', id=tx.id)` (new column header, update the empty-state `colspan`)

## Files to change
- `app.py` — replace the `edit_expense` stub with a GET/POST route; import `get_expense` and `update_expense`; include `"id": row["id"]` in each profile transaction dict; reuse `_validate_expense_form` and `EXPENSE_FIELDS`
- `database/db.py` — add `get_expense()` and `update_expense()`
- `templates/profile.html` — Edit link column
- `static/css/style.css` — minimal styles for the Edit link / action column, reusing existing `.section-link` and CSS variables where possible
- `CLAUDE.md` — mark `GET/POST /expenses/<id>/edit` as implemented and Step 8 as done (only when the feature is finished)

## Files to create
- `templates/edit_expense.html`
- `tests/test_edit_expense.py`

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
- Signed-out requests (GET and POST) redirect to `login`
- Ownership: always look up and update by both expense id and `session["user_id"]`; never accept a user id from the form. A missing or foreign expense must `abort(404)` (same response for both, so ids of other users' expenses are not revealed)
- Reuse `_validate_expense_form` so add and edit share identical rules (amount > 0 and <= `MAX_AMOUNT`, category in `CATEGORIES`, valid `YYYY-MM-DD` date, description <= `MAX_DESCRIPTION_LENGTH`); on error re-render with the error and the user's entered values, no update
- Blank description is stored as `NULL`
- GET pre-fills the form from the stored row (amount, category, date, description or empty string)
- On success, `flash("Expense updated.")` and redirect to `profile`
- Editing must not change `user_id` or `created_at`
- Do not implement Step 9 (delete); leave its stub untouched
- Tests use pytest-flask with the temporary DB from `conftest.py`, never `spendly.db`

## Definition of done
- [ ] Visiting `/expenses/<id>/edit` while signed out redirects to `/login`
- [ ] A POST to `/expenses/<id>/edit` while signed out redirects to `/login` and changes nothing
- [ ] Each row in the profile transactions table has an "Edit" link that opens that expense's edit form
- [ ] The edit form is pre-filled with the expense's current amount, category, date and description
- [ ] Submitting valid changes redirects to `/profile` with "Expense updated." and the transactions list, total and category breakdown reflect the change
- [ ] Clearing the description is accepted and stored as blank
- [ ] An empty, zero, negative, non-numeric or over-limit amount shows an error and changes nothing
- [ ] An invalid category or malformed date shows an error and changes nothing
- [ ] After a validation error the entered values are still in the form
- [ ] Requesting an expense id that does not exist returns 404
- [ ] Requesting or submitting an edit for another user's expense returns 404 and leaves that expense unchanged
- [ ] `/expenses/<id>/delete` stub is unchanged
- [ ] `pytest` passes, including the new `tests/test_edit_expense.py`
