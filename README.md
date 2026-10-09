# Safe Roads For Us — Sprint 1 (Auth)

Django app covering Sprint 1's requirements: sign up, log in, password
visibility toggle, forgot password (real email + reset flow), logout,
and a placeholder authenticated dashboard.

## Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# then edit .env and fill in EMAIL_HOST_USER / EMAIL_HOST_PASSWORD
# (see .env.example for how to get a Gmail App Password — free)
#
# If you leave EMAIL_HOST_USER/PASSWORD blank, reset emails print to
# the console instead of sending for real, so you can still develop
# without setting up email.

# 4. Run migrations
python3 manage.py migrate

# 5. Create the first Admin. No password is chosen or stored: a one-time
#    password-setup link is emailed (or printed with --print-link).
python3 manage.py create_first_admin --email you@example.org     --name "Your Name" --base-url http://127.0.0.1:8000

# 6. Run the dev server
python3 manage.py runserver
```

Then visit:
- http://127.0.0.1:8000/accounts/login/
- http://127.0.0.1:8000/accounts/forgot-password/
- http://127.0.0.1:8000/accounts/users/ (User Management, Admin only)
- http://127.0.0.1:8000/admin/ (Django admin: Admin role plus the Django staff flag; users are read-only there)

## What's implemented

| Requirement (from Sprint 1 doc) | Status |
|---|---|
| Account creation | Admin-only invitations (public sign-up was removed); see `accounts/user_views.py` |
| Password rules: 8+ chars, upper, lower, number, special char | Done — custom validator in `accounts/validators.py` |
| Login by email + password | Done — custom `User` model uses email as `USERNAME_FIELD` |
| Password visibility toggle | Done — vanilla JS, no library |
| Login validation / clear error messages | Done |
| Forgot password | Done — sends a real reset email (SMTP) with a secure, expiring token link, plus the actual "set new password" page |
| Successful login redirect to dashboard | Done — placeholder dashboard page |
| Logout | Done — POST-only (CSRF-safe), ends session |
| Responsive design | Done — single breakpoint at 480px |
| Accessibility | Labels on all fields, `aria-label` on toggle buttons, keyboard-operable |

**One deliberate addition beyond the literal spec:** the requirements doc's
Forgot Password acceptance criteria stops at "confirmation that the request
has been processed" — it doesn't describe the actual password-reset step.
I built that step anyway (`/accounts/reset/<uid>/<token>/`) using Django's
built-in, security-reviewed token view, since a forgot-password feature
that never lets you actually reset your password isn't functionally
complete. Flag this to your marker/supervisor if grading strictly against
the written acceptance criteria — it's extra, not a gap.

## Project structure

```
srfu/                   # Django project config
  settings.py            # custom user model, password validator, email config
  urls.py
accounts/                # the auth app
  models.py               # custom User (email login)
  forms.py                 # AddUserForm, EmailAuthenticationForm, ForgotPasswordForm
  views.py                  # login, logout, forgot/reset password, dashboard
  validators.py              # ComplexPasswordValidator (Sprint 1 password rules)
  urls.py
  admin.py                    # User registered with Django admin
  templates/accounts/          # all HTML templates
static/css/auth.css            # all styling
```

## Database

Currently SQLite (`db.sqlite3`) for zero-setup local dev. Switching to
Postgres later is a config change in `settings.py` `DATABASES`, not a
rewrite — none of the app code depends on which database is used.

## Notes for later sprints

- `AUTH_USER_MODEL` is a custom model from the start, so adding role
  fields (e.g. distinguishing an "authorised SRFU user" for the outreach
  approval workflow described in the project brief) won't require a
  disruptive migration later.
- Django admin is already wired up — useful as a free CRUD interface
  once the bank/branch/club/opportunity models get built in later sprints.


## Roles and permissions

`User.role` (`admin` or `staff`) is the source of truth for outreach
permissions; see `accounts/roles.py`. Django groups, individually assigned
permissions and the superuser flag are ignored for `outreach.*`
permissions, so demoting a user always removes Admin capabilities.
`is_staff` only controls access to the Django admin site (which also
requires the Admin role). Roles are changed in User Management, which
enforces the last-Admin, self-change, audit and session rules.

The BA does not say which "system settings" an Admin may change. No
settings editor exists; Django admin access is limited to Admin-role
users and the User model is read-only there.
