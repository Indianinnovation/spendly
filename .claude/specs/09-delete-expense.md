# Spec: Delete Expense

## Overview
Lets a signed-in user permanently remove one of their own expenses from the profile transactions table. This replaces the Step 9 stub at `/expenses/<id>/delete`. Steps 7 and 8 let users add and correct expenses; this step completes the expense lifecycle. Because deletion is destructive, it is a POST-only action triggered by a small form button on each row (with a vanilla JS confirmation), not a plain link, so it cannot be fired by a link, image tag or prefetch from another site.

## Depends on
- Step 1 — database setup (`expenses` table, `get_db()`)
- Step 3 — login/logout (`session["user_id"]`, `_is_signed_in()`)
- Step 4/5 — profile page and its DB-backed queries (where the Delete button lives and the result shows up)
- Step 8 — edit expense (`get_expense()` ownership pattern, per-row action column in `profile.html`)

## Routes
- `POST /expenses/<int:id>/delete` — delete the expense, flash a message, redirect to `/profile` — logged-in, owner only (redirect to `/login` when signed out; 404 when the expense does not exist or belongs to another user)
- `GET /expenses/<int:id>/delete` — no longer served; the route accepts POST only, so GET returns 405

## Database changes
No schema changes. Add one helper to `database/db.py`:
- `delete_expense(expense_id, user_id)` — parameterised `DELETE FROM expenses WHERE id = ? AND user_id = ?`; returns `True` if a row was deleted, `False` otherwise

Scoping the query by `user_id` is what enforces ownership; the route never relies on the id alone.

## Templates
- **Create:** none
- **Modify:** `templates/profile.html` — in each transaction row's action cell, add a `<form method="post" action="{{ url_for('delete_expense', id=tx.id) }}">` with a "Delete" submit button next to the existing "Edit" link; add a `{% block scripts %}` handler (vanilla JS) that asks `confirm("Delete this expense?")` on submit of those forms and cancels the submit if declined

## Files to change
- `app.py` — replace the `delete_expense` stub with a POST-only route; the DB helper and the view function share a name, so import the helper under an alias (e.g. `delete_expense as delete_expense_row`) and keep the view/endpoint name `delete_expense`
- `database/db.py` — add `delete_expense()`
- `templates/profile.html` — Delete button + confirmation script
- `static/css/style.css` — minimal styles so the Delete button looks like the Edit link in the action column (reuse existing classes and CSS variables)
- `CLAUDE.md` — mark `POST /expenses/<id>/delete` as implemented and Step 9 as done (only when the feature is finished)

## Files to create
- `tests/test_delete_expense.py`

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
- Deletion is POST-only; never delete on GET
- Signed-out requests redirect to `login` and delete nothing
- Ownership: always delete by both expense id and `session["user_id"]`; never accept a user id from the form. A missing or foreign expense must `abort(404)` (same response for both, so ids of other users' expenses are not revealed). Look up with `get_expense()` first, and also `abort(404)` if the delete helper returns `False`
- On success, `flash("Expense deleted.")` and redirect to `profile`
- Vanilla JS only, in the template's `{% block scripts %}`; no inline `style=` attributes
- The no-JS path must still work: the form posts and deletes without the confirmation
- Do not touch the add or edit routes
- Tests use pytest-flask with the temporary DB from `conftest.py`, never the real `spendly.db`

## Definition of done
- [ ] A POST to `/expenses/<id>/delete` while signed out redirects to `/login` and the expense still exists
- [ ] A GET to `/expenses/<id>/delete` returns 405 and deletes nothing
- [ ] Each row in the profile transactions table has a "Delete" button beside "Edit"
- [ ] Clicking Delete shows a confirmation; cancelling leaves the expense in place
- [ ] Confirming redirects to `/profile` with "Expense deleted." and the row is gone
- [ ] The profile total, transaction count and category breakdown update to exclude the deleted expense
- [ ] Deleting the last expense in a category removes that category from the breakdown
- [ ] POSTing a delete for an id that does not exist returns 404
- [ ] POSTing a delete for another user's expense returns 404 and leaves that expense unchanged
- [ ] Other expenses of the same user are unaffected
- [ ] `url_for('delete_expense', id=...)` still resolves (endpoint name unchanged)
- [ ] `pytest` passes, including the new `tests/test_delete_expense.py`
