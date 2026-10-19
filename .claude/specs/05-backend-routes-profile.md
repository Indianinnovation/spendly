# Spec: Backend Connection

## Overview
Step 5 replaces all hardcoded data in the `/profile` route with live queries
against the SQLite database. The profile page currently renders a static demo
user, fixed summary stats, a hand-typed transaction list, and a hardcoded
category breakdown. This step wires those four sections to real data so that
every logged-in user sees their own expenses. Three parallel subagents handle
the three independent data concerns — transaction history, summary stats, and
category breakdown — before being integrated into the single `/profile` route.

## Depends on
- Step 1: Database setup (tables and `get_db()` exist)
- Step 2: Registration (users are stored in the database)
- Step 3: Login / Logout (`session["user_id"]` is set on login)
- Step 4: Profile page static UI (template already renders all four sections)

## Routes
No new routes. The existing `GET /profile` route is modified.

## Database changes
No database changes. The `users` and `expenses` tables already have all
required columns (`user_id`, `amount`, `category`, `date`, `description`,
`created_at`).

## Templates
- **Modify**: `templates/profile.html`
  - Amounts must be rendered with the ₹ symbol (Indian Rupee).
  - All four dynamic sections (user info, summary stats, transaction list,
    category breakdown) are already present — no structural changes needed,
    only the Jinja variables they consume are now real.

## Files to change
- `app.py` — replace hardcoded data in the `profile()` view with DB queries
- `database/db.py` — add read-only query helpers (CLAUDE.md: DB logic lives only in `db.py`), one per data concern. The existing `get_user_by_id` is reused:
  - `get_recent_expenses(user_id, limit=10)` → rows with `id`, `amount`, `category`, `date`, `description`, newest first
  - `get_expense_summary(user_id)` → dict with `total_spent`, `count`
  - `get_category_totals(user_id)` → rows with `category`, `total`, largest first
- `templates/profile.html` — empty-state messages when there are no expenses
- `static/css/style.css` — add `.badge-other` (Other is a seeded category)
- `tests/test_profile.py` — data-driven tests

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never string-format values into SQL
- Foreign keys PRAGMA must be enabled on every connection (already done in `get_db()`)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles
- Currency must always display as ₹ — never £ or $
- `member_since` must be derived from `users.created_at` and formatted as
  "Month YYYY" (e.g. "January 2026")
- Bar widths use `.bar-w-N` classes (N a multiple of 5, 0–100), derived from each category's share of the total
- If a user has no expenses, summary stats should return zeros and "—" and the
  lists should be empty, rather than raising exceptions
- Query helpers in `database/db.py` must call `get_db()` internally and
  close the connection before returning
- Amounts display with two decimals: `"₹{:,.2f}"`

## Tests to write
File: `tests/test_profile.py` (temporary DB from `conftest.py`; expenses inserted per test)

- `GET /profile` signed out redirects to `/login` (302)
- Signed in with 8 sample expenses: 200, `₹5,900` total, top category Shopping, 8 transactions
- Transaction list is newest-first
- Category breakdown has 7 categories, largest first, bar widths multiples of 5 in 0–100
- User with no expenses: 200, both empty-state messages shown, no `breakdown-fill` bars
- Helpers return `[]` / zeros for a user with no expenses
- A user never sees another user's expenses

## Definition of done
- [ ] Logging in as the seed user (demo@spendly.com / demo123) shows "Demo User" and "demo@spendly.com" on the profile page
- [ ] Total spent displayed equals ₹5,900
- [ ] Transaction count displayed is 8
- [ ] Top category displayed is "Shopping"
- [ ] Transaction list shows 8 rows ordered newest date first
- [ ] Category breakdown shows 7 categories, largest first
- [ ] All amounts on the page display the ₹ symbol
- [ ] Registering a brand-new user and visiting `/profile` shows ₹0 total spent, 0 transactions, and empty-state messages — no errors
