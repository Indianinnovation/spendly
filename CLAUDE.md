# CLAUDE.md

## Project overview

Spendly is a lightweight personal expense tracker built with Flask and SQLite.

---

## Architecture
```
expense-tracker/
├── app.py                 # All routes — single file, no blueprints (port 5001)
├── requirements.txt
├── database/
│   ├── __init__.py        # empty
│   └── db.py              # SQLite helpers: get_db(), init_db(), seed_db()
├── templates/
│   ├── base.html          # Shared layout (navbar, footer); blocks: title, head, content, scripts
│   ├── landing.html       # Home page; contains the inline YouTube modal <script>
│   ├── login.html
│   ├── register.html
│   ├── profile.html       # Profile page (identity from session user; stats/transactions are sample data)
│   ├── terms.html
│   └── privacy.html
└── static/
    ├── css/style.css      # Single global stylesheet for every page (incl. landing)
    └── js/main.js         # Vanilla JS only; currently an empty placeholder
```

Tests live in `tests/` (pytest-flask, temporary DB via `conftest.py`). The DB file is git-ignored. `file.md` is a pasted terminal transcript, not documentation.

**Where things belong:**
- New routes → `app.py` only, no blueprints
- DB logic → `database/db.py` only, never inline in routes
- New pages → new `.html` file extending `base.html`
- Styles → add to `static/css/style.css` (the only stylesheet today); if a page needs its own, create a new `.css` file rather than inline `<style>` tags
- Page-specific JS → the template's `{% block scripts %}`; shared JS → `static/js/main.js`

---

## Code style

- Python: PEP 8, snake_case for all variables and functions
- Templates: Jinja2 with `url_for()` for every internal link — never hardcode URLs
- Route functions: one responsibility only — fetch data, render template, done
- DB queries: always use parameterized queries (`?` placeholders) — never f-strings in SQL
- Error handling: use `abort()` for HTTP errors, not bare `return "error string"`

---

## Tech constraints

- **Flask only** — no FastAPI, no Django, no other web frameworks
- **SQLite only** — no PostgreSQL, no SQLAlchemy ORM, no external DB
- **Vanilla JS only** — no React, no jQuery, no npm packages
- **No new pip packages** — work within `requirements.txt` as-is unless explicitly told otherwise
- Python 3.10+ assumed — f-strings and `match` statements are fine

---

## Subagent Policy
- Always use a builtin explore subagent for codebase exploration 
  before implementing any new feature
- Always use a subagent to verify test results 
  after any implementation
- When asked to plan, delegate codebase research 
  to a subagent before presenting the plan
- always use a builtin plan subagent in plan mode

---

## Commands
```bash
# Setup
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
# Claude's shell does not keep activation between commands — call venv/bin/python, venv/bin/pip, venv/bin/pytest directly

# Run dev server (port 5001)
python app.py

# Run all tests (no tests exist yet; put them in tests/ — pytest-flask is installed)
pytest

# Run a specific test file
pytest tests/test_foo.py

# Run a specific test by name
pytest -k "test_name"

# Run tests with output visible
pytest -s
```

---

## Implemented vs stub routes

| Route | Status |
|---|---|
| `GET /` | Implemented — renders `landing.html` |
| `GET/POST /register` | Implemented — renders `register.html`; POST validates and creates the user |
| `GET/POST /login` | Implemented — renders `login.html`; POST verifies credentials and sets `session["user_id"]` |
| `GET /terms` | Implemented — renders `terms.html` |
| `GET /privacy` | Implemented — renders `privacy.html` |
| `GET /logout` | Implemented — clears the session, redirects to `/login` |
| `GET /profile` | Implemented — renders `profile.html` with hardcoded sample data (DB wiring comes later); redirects to `/login` when signed out |
| `GET/POST /expenses/add` | Implemented — renders `add_expense.html`; POST validates and creates the expense |
| `GET/POST /expenses/<id>/edit` | Implemented — renders `edit_expense.html` pre-filled; POST validates and updates; owner only (404 otherwise), redirects to `/login` when signed out |
| `POST /expenses/<id>/delete` | Implemented — POST only (GET is 405); deletes the owner's expense, flashes "Expense deleted.", redirects to `/profile`; owner only (404 otherwise), redirects to `/login` when signed out |

Steps 1 (database setup), 2 (registration), 3 (login/logout) 4 (profile page UI), 7 (add expense), 8 (edit expense) and 9 (delete expense) are done. Steps 5 and 6 are not defined anywhere in the repo.

**Do not implement a stub route unless the active task explicitly targets that step.**

---

## Warnings and things to avoid

- **Never use raw string returns for stub routes** once a step is implemented — always render a template
- **Never hardcode URLs** in templates — always use `url_for()`
- **Never put DB logic in route functions** — it belongs in `database/db.py`
- **Never install new packages** mid-feature without flagging it — keep `requirements.txt` in sync
- **Never use JS frameworks** — the frontend is intentionally vanilla
- **`database/db.py` is currently only a comment spec** (no code) — do not assume `get_db()`, `init_db()` or `seed_db()` exist until the database step implements them
- **FK enforcement is manual** — SQLite foreign keys are off by default; `get_db()` must run `PRAGMA foreign_keys = ON` on every connection
- The app runs on **port 5001**, not the Flask default 5000 — don't change this

---

## Conventions for upcoming features

- **Database:** file is `spendly.db` (git-ignored). `init_db()` uses `CREATE TABLE IF NOT EXISTS`; `seed_db()` is for development data only. Where they are invoked (app startup vs. a CLI command) is not decided yet — confirm before wiring.
- **Auth:** Flask sessions need `app.secret_key`, which is not set yet. Hash passwords with `werkzeug.security` (already a dependency); never store plaintext. Protected routes should redirect to `login` when there is no session user.
- **Currency:** the product is rupee-based (landing page: "Track Every Rupee"). Display amounts with ₹.
- **Amounts:** format in templates with `"₹{:,.0f}".format(x)`. Bar widths use `.bar-w-N` classes (N a multiple of 5) because inline `style=` is not allowed.
- **Tests:** place in `tests/` using pytest-flask; point tests at a temporary SQLite DB, never `spendly.db`.
