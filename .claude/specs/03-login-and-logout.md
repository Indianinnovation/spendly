# Spec: Login and Logout

## Overview
Implement session-based authentication so registered users can sign in and out of Spendly. This step upgrades the existing `GET /login` page into a form that accepts a POST, verifies the email and password against the `users` table, and stores the user id in the Flask session. It also replaces the `/logout` stub with a route that clears the session. Registration (Step 2) creates accounts but does not sign anyone in; this step makes those accounts usable and is the foundation for every protected page that follows (profile, expenses).

## Depends on
- Step 1 (Database setup): `users` table and `get_db()` / `init_db()` in `database/db.py`.
- Step 2 (Registration): `create_user`, `get_user_by_email`, `app.secret_key`, and the flash-message block in `login.html`.

## Routes
- `GET /login` — render the sign-in form; if already signed in, redirect to `/` — public
- `POST /login` — validate credentials, set `session["user_id"]`, redirect to `/` on success; on failure re-render the form with an error — public
- `GET /logout` — clear the session, flash a confirmation, redirect to `/login` — public (safe to call when not signed in)

`/profile` is still a stub (Step 4), so the post-login redirect targets the landing page via `url_for("landing")` for now; switch it to `/profile` in Step 4. Do not implement `/profile` or any other stub here.

## Database changes
No schema changes; the `users` table is sufficient.

`get_user_by_email(email)` already exists in `database/db.py` and returns the full row including `password_hash`. Add one helper:

- `get_user_by_id(user_id)` — returns the matching `sqlite3.Row` or `None`; opens a connection via `get_db()` and closes it before returning. Used to resolve the signed-in user for templates.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html`
    - `action="/login"` becomes `action="{{ url_for('login') }}"`
    - Repopulate the `email` input on error (`value="{{ email or '' }}"`); never repopulate the password
  - `templates/base.html`
    - Navbar: when `current_user` is set, show the user's name and a "Sign out" link (`url_for('logout')`) instead of "Sign in" / "Get started"; otherwise keep the existing links

## Files to change
- `app.py`
  - Import `session` from Flask and `check_password_hash` from `werkzeug.security`; import `get_user_by_id` from `database.db`
  - Change `@app.route("/login")` to accept `methods=["GET", "POST"]` and handle the POST
  - Replace the `/logout` stub with a real implementation
  - Add a `@app.context_processor` that injects `current_user` (via `get_user_by_id(session.get("user_id"))`, or `None`)
- `database/db.py` — add `get_user_by_id`
- `templates/login.html` — changes above
- `templates/base.html` — conditional navbar links
- `static/css/style.css` — only if the navbar user name needs styling; use existing CSS variables
- `CLAUDE.md` — update the implemented/stub routes table for `/login` and `/logout`

## Files to create
None.

## New dependencies
No new dependencies (`werkzeug.security.check_password_hash` and `flask.session` ship with Flask).

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders), no f-strings or string formatting in SQL
- Passwords hashed with werkzeug; verify with `check_password_hash` only; never log or re-render plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Use `url_for()` for every internal link, form action and redirect
- DB logic stays in `database/db.py`; the route only reads the form, calls helpers, and renders or redirects
- Normalise the email (strip, lower-case) before lookup, matching registration
- Use `request.form.get(...)` so missing fields never raise a 400/500
- Use one generic error for both unknown email and wrong password: "Invalid email or password." (do not reveal which was wrong)
- If either field is empty after trimming the email: "Email and password are required."
- Validation failures return HTTP 200 with the form re-rendered and `error` set; no bare string returns
- Success: `session.clear()` first (avoids session fixation), then `session["user_id"] = user["id"]`, then `redirect(url_for("landing"))`
- Store only the user id in the session — never the password hash or other user data
- Logout: `session.clear()`, `flash("You have been signed out.")`, `redirect(url_for("login"))`
- A session whose `user_id` no longer matches a user must behave as signed out (`current_user` is `None`)
- Do not implement other stub routes (`/profile`, `/expenses/*`)

## Definition of done
- [ ] `python app.py` starts on port 5001 with no errors
- [ ] Signing in with the seeded demo account (`demo@spendly.com` / `demo123`) redirects to `/`
- [ ] Signing in with an account created via `/register` works, including when the email is typed in a different case
- [ ] A wrong password and an unknown email both show "Invalid email or password." with HTTP 200 and no session set
- [ ] An empty email or password shows "Email and password are required."
- [ ] On error, the email keeps its submitted value and the password field is empty
- [ ] `curl -X POST http://localhost:5001/login` (no fields) returns 200 with the required-fields error, not a 400 or 500
- [ ] After signing in, the navbar shows the user's name and a "Sign out" link, and no longer shows "Sign in" / "Get started"
- [ ] Visiting `/login` while signed in redirects to `/`
- [ ] Clicking "Sign out" redirects to `/login` showing "You have been signed out.", and the navbar shows "Sign in" / "Get started" again
- [ ] The confirmation message does not reappear on refresh (flash is consumed once)
- [ ] Visiting `/logout` while not signed in redirects to `/login` without error
- [ ] The login form `action` and all navbar links are rendered via `url_for`; any `style.css` diff contains no new hex values
