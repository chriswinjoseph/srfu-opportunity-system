# Safe Roads For Us — Community Bank Outreach Tool

Django app for managing outreach to community banks, branches and clubs:
accounts and roles (Admin / Staff), organisation dashboard with search and
filters, AI-assisted draft emails with human approval, outreach tracking,
and Admin-only data import and public-source scraping.

## Setup

You need **Python 3.12 or newer** (Django 6.1 requires it). On Windows,
`python3` is not a real command (it is a Microsoft Store shortcut); use the
`py` launcher as shown below. Run every command from the project folder
(the one containing `manage.py`).

### 1. Create a virtual environment and install dependencies

Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, run
`Set-ExecutionPolicy -Scope Process Bypass` first and activate again.

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. Configure environment variables

Windows (PowerShell): `Copy-Item .env.example .env`
macOS / Linux: `cp .env.example .env`

Then edit `.env`:

| Variable | What to put |
|---|---|
| `DJANGO_SECRET_KEY` | Required. Any long random string, for example the output of `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `OPENAI_API_KEY` | Required to start the app. Replace the placeholder with your own key (the placeholder lets the app start but AI draft generation will fail). Never commit it. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | SMTP settings for invitation, password-setup and password-reset emails. For Gmail use an App Password. |

Email is always sent over SMTP: there is no console fallback. If the SMTP
settings are missing or wrong, emails fail. Account creation still works:
an Admin can use **Resend invitation** in User Management once SMTP is fixed,
and the first Admin can be set up without email (step 5).

### 3. Create the database

```
python manage.py migrate
```

### 4. Create the first Admin

No password is chosen or stored. The command prints a single-use
password-setup link to your terminal (treat it as a secret); open it in a
browser to set the password:

```
python manage.py create_first_admin --email you@example.org --name "Your Name" --base-url http://127.0.0.1:8000 --print-link
```

Once SMTP works you can leave out `--print-link` and the link is emailed
instead. The command refuses to run again once an Admin exists; create
further users in User Management.

### 5. Add an approved email template

AI draft generation needs at least one active **approved email template**.
Without one, the email dialog shows "No approved templates available" and
a draft cannot be generated. There is no template editor yet and no
built-in template, so create one yourself, using wording approved by SRFU:

```
python manage.py shell
```

Paste the following (replace every value with SRFU's approved text), then
press Enter twice and type `exit()`:

```python
from outreach.models import EmailTemplate

EmailTemplate.objects.create(
    name="Community Bank introduction",
    version="v1",
    purpose="Introduce Safe Roads For Us and start a conversation",
    template_body="Introduce the organisation and the road safety program, "
                  "and invite the recipient to talk.",
    sender_name="Replace with the approved sender name",
    sender_role="Replace with the approved sender role",
    project_details="Replace with approved project details",
    call_to_action="Please reply to this email if you would like to talk.",
    signature="Replace with the approved sender name\nSafe Roads For Us",
)
```

Notes:

- The first line of `signature` must appear in the generated email (the
  draft check looks for it), so make it the sender's name.
- Only templates with `is_active=True` are offered in the email dialog. To
  stop offering one, set `is_active=False` on it in `manage.py shell`.
- Every generated draft still needs human approval before it can be sent.

### 6. Run the app

```
python manage.py runserver
```

Then visit:

- http://127.0.0.1:8000/accounts/login/
- http://127.0.0.1:8000/outreach/dashboard/ (dashboard: search, filters, drafts)
- http://127.0.0.1:8000/accounts/users/ (User Management, Admin only)
- http://127.0.0.1:8000/data/ (data import and scraper, Admin only)
- http://127.0.0.1:8000/admin/ (Django admin: Admin role plus the Django staff flag; users are read-only there)

A scrape queued from the Scraper page only runs while the background worker
is running. In a second terminal (with the virtual environment activated):

```
python manage.py run_intake_worker
```

### Running the tests

```
python manage.py test
```

The tests use their own temporary database, Django's test email outbox
(no real email is sent) and mocked OpenAI calls. The full suite can take a
long time on a slow machine.

### Troubleshooting

| Message | Cause and fix |
|---|---|
| `KeyError: 'DJANGO_SECRET_KEY'` | `.env` is missing or has no `DJANGO_SECRET_KEY`. Complete step 2. |
| `RuntimeError: OPENAI_API_KEY is not configured.` | `OPENAI_API_KEY` is empty or missing in `.env`. |
| `ModuleNotFoundError` | The virtual environment is not activated, or step 1's install did not finish. |
| Invitation or reset email not delivered | Check the SMTP settings in `.env`, restart the server, then use **Resend invitation**. |

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

## Project structure

```
srfu/        Django project config (settings, urls)
accounts/    custom email-login User, roles, invitations, user management
outreach/    organisations, dashboard, AI draft emails and approval workflow
intake/      Admin-only workbook import, duplicate review and public-source scraper
static/      CSS and JavaScript
docs/        requirements, acceptance criteria and status notes
```

## Database

Currently SQLite (`db.sqlite3`) for zero-setup local development. It is not
committed (see `.gitignore`); back it up before importing real data.
Switching to Postgres later is a change to `DATABASES` in `settings.py`.
