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

# 5. (Optional) create an admin account to browse Django admin
python3 manage.py createsuperuser

# 6. Run the dev server
python3 manage.py runserver
```

Then visit:
- http://127.0.0.1:8000/accounts/signup/
- http://127.0.0.1:8000/accounts/login/
- http://127.0.0.1:8000/accounts/forgot-password/
- http://127.0.0.1:8000/admin/ (Django admin, if you created a superuser)

## What's implemented

| Requirement (from Sprint 1 doc) | Status |
|---|---|
| Sign up (first name, last name, email, password) | Done |
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
  forms.py                 # SignUpForm, EmailAuthenticationForm, ForgotPasswordForm
  views.py                  # signup, login, logout, forgot/reset password, dashboard
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
