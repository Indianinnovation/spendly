# Spec: Registration

## Overview
## Overview

Implement user registration so new visitors can create a Spendly account. This step upgrades the existing stub `GET /register` route into a fully functional form that accepts a POST, validates input, hashes the password, and inserts a new row into the `users` table.

On success the user is shown with a success message and then redirected to the login page.

This is the entry point for all authenticated features that follow.



## Depends on

- Step 1 (Database setup): `users` table with `id`, `name`, `email` (UNIQUE), `password_hash`, `created_at`, and `get_db()` / `init_db()` in `database/db.py`, with `init_db()` called on app startup.
- **Precondition:** `database/db.py` currently contains only the comment stub, even though spec 01 and the "create database setup" commit say Step 1 is done. `get_db()` and `init_db()` must exist before this step starts; implement Step 1 first if they do not.

## Routes

- GET /register – render the registration form – public (already implemented; unchanged)
- POST /register – validate the form, create the user, flash a success message and redirect to `/login`; on failure re-render the form with an error – public

No other new routes. Do not implement `/login` POST or `/logout` here.

## Database changes

No schema changes; the `users` table from Step 1 is sufficient.

Add helpers in `database/db.py` (no DB logic in `app.py`):

- `create_user(name, email, password)` – hashes the password with `generate_password_hash`, inserts the row with a parameterised query, commits, returns the new user id. Lets `sqlite3.IntegrityError` propagate on a duplicate email.
- `get_user_by_email(email)` – returns the matching `sqlite3.Row` or `None`.

Both helpers open a connection via `get_db()` and close it before returning.

Emails are normalised (stripped, lower-cased) in the route before calling either helper, so uniqueness is case-insensitive.

## Templates

- Create: none
- Modify:
  - `templates/register.html`
    - `action="/register"` becomes `action="{{ url_for('register') }}"`
    - Fix the broken sign-in line to: `Already have an account? <a href="{{ url_for('login') }}">Sign in</a>`
    - Repopulate `name` and `email` inputs on error (`value="{{ name or '' }}"`, `value="{{ email or '' }}"`); never repopulate the password
    - Add `minlength="8"` on the password input to match the placeholder
    - Add a "Confirm password" input (`name="confirm_password"`, `type="password"`, `minlength="8"`, `required`) after the password input; never repopulate it
  - `templates/login.html`
    - Above the existing `{% if error %}` block, render flashed messages with `get_flashed_messages()` in a `<div class="auth-success">`

## Files to change

- `app.py`
  - Import `request`, `redirect`, `url_for`, `flash` from Flask
  - Set `app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")` (required for `flash`)
  - Change `@app.route("/register")` to accept `methods=["GET", "POST"]`
- `database/db.py` – add `create_user`, `get_user_by_email`
- `templates/register.html` – changes above
- `templates/login.html` – flash message block
- `static/css/style.css` – add `.auth-success` next to `.auth-error`, using `var(--accent-light)` background, `var(--accent)` text, `var(--radius-sm)`; no hex values

## Files to create

None.

## New dependencies

No new dependencies (`werkzeug.security` ships with Flask; `os` and `sqlite3` are standard library).

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders), no f-strings or string formatting in SQL
- Passwords hashed with werkzeug (`generate_password_hash`); never store, log or re-render plaintext
- Use CSS variables – never hardcode hex values (do not copy the hardcoded border colour from `.auth-error`)
- All templates extend `base.html`
- Use `url_for()` for every internal link and form action
- DB logic stays in `database/db.py`; the route only reads the form, validates, calls helpers, and renders or redirects
- Server-side validation (do not rely on HTML attributes alone), checked in this order, first failure wins:
  1. `name`, `email`, `password`, `confirm_password` all present and non-empty after trimming (passwords are not trimmed for storage) → "All fields are required."
  2. email contains exactly one `@` with non-empty parts and a `.` in the domain → "Please enter a valid email address."
  3. password at least 8 characters → "Password must be at least 8 characters."
  4. `password` equals `confirm_password` → "Passwords do not match."
  5. email not already registered (check `get_user_by_email`, and also catch `sqlite3.IntegrityError` from `create_user` for the race) → "An account with that email already exists."
- Use `request.form.get(...)` (not `request.form[...]`) so missing fields never raise a 400/500
- Validation failures return HTTP 200 with the form re-rendered and `error` set; no bare string returns
- Success: `flash("Account created. Please sign in.")` then `redirect(url_for("login"))`
- Do not log the user in on registration (login is a later step); do not touch `session`
- Do not implement stub routes (`/logout`, `/profile`, `/expenses/*`)

## Definition of done

- [ ] `python app.py` starts on port 5001 with no errors
- [ ] `GET /register` shows the form; "Sign in" link goes to `/login`; form `action` is rendered via `url_for`
- [ ] Submitting a name, a new email and an 8+ character password redirects to `/login`, which shows "Account created. Please sign in."
- [ ] Refreshing `/login` after that no longer shows the success message (flash is consumed once)
- [ ] The new row exists in `users`; email is stored lower-case; `password_hash` is not the plaintext (starts with `scrypt:` or `pbkdf2:`)
- [ ] Registering the same email again, including different casing (`Test@Example.com` vs `test@example.com`), shows the duplicate-email error and creates no second row
- [ ] A 7-character password shows the length error and creates no row
- [ ] A confirm password that differs from the password shows "Passwords do not match." and creates no row
- [ ] An email like `foo@bar` or `foo` shows the invalid-email error and creates no row
- [ ] Whitespace-only name or email shows "All fields are required." and creates no row
- [ ] On any error, name and email keep their submitted values and the password field is empty
- [ ] `curl -X POST http://localhost:5001/register` (no fields) returns 200 with the required-fields error, not a 400 or 500
- [ ] The success message box on `/login` uses the green accent styling; `style.css` diff contains no new hex values
