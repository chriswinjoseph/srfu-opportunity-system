# Safe Roads For Us - Opportunity System

A web application for Safe Roads For Us (SRFU) to manage outreach to community banks,
bank branches and sports clubs.

**What it does**

* Keeps one record per organisation (Bank, Branch or Club) with its contacts and contact status
  (*Not Yet Contacted* or *Contacted*).
* Staff prepare outreach emails (optionally drafted by an AI service from an approved template),
  submit them for approval, and send them only after an Admin approves. Follow-ups, Do Not Contact
  and archiving are supported.
* Admins import the client's Excel workbook of organisations and contacts, review possible
  duplicates, and run a public-information **scraper** that adds new organisations from approved
  public websites.
* Role-based access: **Admin** (everything, including user management, import and scraper) and
  **Staff** (organisations, drafts and sending approved email).

**Architecture**

| Part | What it is |
|---|---|
| Website | Django 6.1 application (`srfu/`, `accounts/`, `outreach/`, `intake/`), served on port 8000 |
| Database | SQLite file `db.sqlite3` in the project folder (not in Git) |
| Background worker | A second process, `python manage.py run_intake_worker`, that runs queued scraper jobs. Scraping never runs inside a web request |
| Email | SMTP (invitations, password resets, outreach email) |
| AI drafting | OpenAI API (draft text only; every draft needs human approval) |
| Public sources | HTTPS pages on explicitly approved hosts only |

The website alone is not enough for scraping: a queued scrape waits until the worker is running
(see [Starting and stopping](#5-starting-and-stopping-the-application-windows)).

Further documents are in `docs/`: [Import-Format.md](docs/Import-Format.md),
[Intake-Jobs.md](docs/Intake-Jobs.md) (worker, monitoring, hosting),
[Scraper-BA-Clarifications.md](docs/Scraper-BA-Clarifications.md) (open decisions),
[Email-Approval-Workflow.md](docs/Email-Approval-Workflow.md) and the requirement documents.

---

## 1. Prerequisites

Verified versions (Windows 11, Windows PowerShell 5.1):

| Component | Version used | Notes |
|---|---|---|
| Python | 3.12.5 (3.12 or newer is required) | Use the `py -3.12` launcher; `python3` on Windows is a Microsoft Store stub |
| Git | 2.55 | Any recent Git |
| Django and libraries | Pinned in `requirements.txt` (Django 6.1) | Installed in step 2 |
| Browser | Any current browser | Only a headless Chromium was used for checks |

You also need, from the people named in step 3: an SMTP mailbox for sending email and an OpenAI
API key for drafting.

All commands below are for **Windows PowerShell**. Text in `<angle brackets>` is a placeholder you
replace. Quote paths that contain spaces.

## 2. Get the code and install

Choose a short folder you own (long paths make Git fail on Windows):

```powershell
cd "D:\srfu"
git clone https://github.com/chriswinjoseph/srfu-opportunity-system.git srfu-opportunity-system
cd srfu-opportunity-system
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope Process Bypass`
and activate again (this affects only the current window). If the repository is private the
owner must first give your GitHub account read access. `git rev-parse HEAD` shows the version you
have.

A fresh clone contains **no** database, accounts, `.env` file, client workbook or email template.
Steps 3 to 7 create each of them. Every later PowerShell window needs `cd` to the project folder
and `.venv\Scripts\Activate.ps1` again.

## 3. Configure the environment (`.env`)

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env` is never committed. Do not paste its contents into emails or tickets.

| Variable | Purpose | Where the operator gets it |
|---|---|---|
| `DJANGO_SECRET_KEY` | Required. Signs sessions and links | Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_DEBUG` | `True` only on a development computer; leave `False` otherwise | Operator's choice |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated host names the site answers to | The address people use to reach the site |
| `OPENAI_API_KEY` | Required to start the application; used for draft generation | The owner of the SRFU OpenAI account (owner not yet confirmed). A placeholder lets the site start but drafts will fail |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | SMTP for invitations, resets and outreach email | The owner of the sending mailbox (owner not yet confirmed). For Gmail use an App Password, not the normal password |

Email is always sent over SMTP; there is no console fallback. With missing or wrong SMTP
settings, emails fail with a clear message but nothing else breaks.

## 4. Create the database and the first Admin

```powershell
python manage.py migrate
```

The first Admin is created without ever choosing or storing a password. The command prints a
**single-use password-setup link** (a secret; valid for 3 days). The link points at the website,
so **the website must be running when you open it**. Start the application first (step 5), then in
a second PowerShell window (project folder, environment activated):

```powershell
python manage.py create_first_admin --email "<admin email>" --name "<Admin full name>" --base-url http://127.0.0.1:8000 --print-link
```

Open the printed link in a browser and set a password (8+ characters with upper case, lower case,
a number and a special character). There are no default accounts or passwords. The command
refuses to run again once an active Admin has finished setup (if setup was never finished,
running it again issues a new link and the old one stops working). With working SMTP you can omit `--print-link` and the
link is emailed instead. Use the public address as `--base-url` once the site has one.

*Temporary arrangement:* a temporary development Admin is in use (recorded in the developer
handover); the client's own main Admin is to be created with this command (or invited from User
Management) once supplied, and the temporary account then disabled in User Management.

## 5. Starting and stopping the application (Windows)

In the project folder, **double-click**:

| File | What it does |
|---|---|
| `Start-SRFU.bat` | Starts the website and the background worker, waits until both are ready, opens the login page. Safe to run again; processes already running are detected and not duplicated. Reports why if it cannot start (details in `logs\`) |
| `Status-SRFU.bat` | Shows whether the website and worker are running. Changes nothing |
| `Stop-SRFU.bat` | Stops both |

Requirements: steps 2 to 4 done (`.venv`, `.env`, migrated database). The launcher never runs
migrations and never starts a scrape. **Starting the worker runs any scrape that is already
queued**, so check the Scraper page first if a queued job should not run yet.

The same actions from a terminal:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1            # start
powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Status
powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Stop
```

Notes: the launcher serves one Windows computer using Django's development web server and does
not restart a process that later crashes (the worker itself retries 5 times, then stops with a
message in `logs\worker.err.log`; double-click Start again). Stopping mid-scrape is safe: finished
pages are kept and the job resumes (within 5 minutes of the next start) without duplicating
records. The computer must stay on and the launcher must have been run since the last restart for
scrapes to run. Hosting a production service needs a managed process and health check
(`docs/Intake-Jobs.md`); the hosting platform has not been decided.

## 6. Approved email template

Draft generation needs at least one active, SRFU-approved email template; none is built in and
there is no editor yet. Use the supplied script:

```powershell
Copy-Item scripts\support\create_email_template.py "$HOME\srfu-create-template.py"
notepad "$HOME\srfu-create-template.py"      # replace every PLACEHOLDER with SRFU-approved wording
python manage.py shell -c "exec(open(r'$HOME\srfu-create-template.py', encoding='utf-8-sig').read())"
```

The script refuses to run while any `PLACEHOLDER` remains. The first line of `signature` must be
the sender's name (the draft check looks for it). Wording comes from SRFU; approved wording has
not yet been supplied. Only active templates are offered; every draft still needs human approval.

## 7. Importing the organisation workbook (Admin only)

1. Sign in as an Admin and open **Data > Import Data** (`/data/import/`).
2. Read the instructions beside the upload (expandable detail lists every sheet, column, accepted
   value and the contact-status rules). **Download blank template** gives the exact sheets and
   headers with no records; **Download synthetic example** shows a filled file with invented data
   that must not be imported for real. Both are Admin-only. Full format: `docs/Import-Format.md`.
3. The workbook must be a genuine Excel `.xlsx` with sheets `Organisations` and `Contacts`. A CSV or
   other file cannot simply be renamed to `.xlsx`; save it from Excel as an Excel Workbook. A
   headers-only template cannot be previewed: add at least one organisation row first.
4. **Validate and preview.** Structure problems name the missing sheet or column and nothing is
   created. The preview shows what would be created, matched, held for review and which rows have
   problems. Nothing is saved yet.
5. **Confirm and import.** Each organisation is processed on its own; a bad row is reported and does
   not stop good ones. Possible duplicates are held on **Duplicate Review** for an Admin decision
   and never merged automatically. Replies are kept as evidence and never set Interested.
6. **Repeat imports are safe.** Importing the same file again creates no duplicate organisations or
   contacts; existing values are never overwritten (differences become **Proposed Changes**) and
   organisations that are archived are not restored.

The client workbook is not in Git (`*.xlsx` is ignored); the Admin supplies it at import time.

## 8. Using the system

* **Sign in:** `http://127.0.0.1:8000/accounts/login/` (or the site's public address). Sessions end
  after 1 hour idle or when the browser closes.
* **Dashboard:** `/outreach/dashboard/` - search, filters, add an organisation (duplicate warnings
  appear for similar names), open an organisation to see contacts, status and history.
* **Users (Admin):** `/accounts/users/` - add a user (Admin or Staff) which sends an invitation,
  **Resend invitation**, change role, disable or enable, view activity. The last Admin and your own
  account are protected. Links are single-use secrets and are never shown on a page.
* **Password recovery:** on the login page choose *Forgot password?*; an emailed single-use link
  (valid 3 days) opens the new-password page. An expired or already-used link shows an error and
  an Admin can resend an invitation.
* **Drafts and approval:** Staff generate or write a draft, edit it (90-120 words), submit it; an
  Admin approves or rejects with a reason; only approved drafts can be sent. A draft cannot be sent
  twice, and Do Not Contact organisations cannot be emailed. Details: `docs/Email-Approval-Workflow.md`.
* **Django admin** (`/admin/`) is limited to Admin-role users and is read-only for accounts.

## 9. The scraper (Admin only)

1. **Data > Scraper** (`/data/scraper/`) lists the approved sources, what each covers and any known
   restriction **before** you queue. Choose organisation types and states, then **Queue scrape**.
2. The scrape runs in the background worker. The run page updates by itself and distinguishes
   *Queued - not started* (no worker), *Waiting*, *Running*, and finished states. A stopped worker
   is shown on queued **and** running jobs; a waiting job is never shown as successful.
3. Result statuses: **Successful** (everything processed), **Partially Successful** (some work
   saved and something failed, is incomplete or awaits review), **Failed** (nothing could be
   processed). The summary shows pages and organisations separately. Every failed page or incomplete
   result lists the source URL, the reason, the affected field and the action required.
4. New organisations are created as *Not Yet Contacted* with their source URL. Existing records are
   matched, not duplicated; blank fields may be filled, different values become **Proposed Changes**
   for an Admin, a removed website value is kept and flagged for checking, and archived
   organisations are neither recreated, restored nor contacted.
5. Fetching is limited to HTTPS pages on approved hosts, respects `robots.txt`, uses timeouts, a
   pause between requests, at most 60 pages and 20 minutes per run, and never bypasses a login or
   bot-protection check.

**Source coverage today (not national):** Banks - 11 Bendigo Community Bank pages in Victoria
(collected successfully on 23 October 2026). Clubs - one council directory that answered with an
automated-access check, so nothing could be collected and the check is not bypassed. Branches - no
source. Adding coverage needs a permitted source and a code change (`intake/sources.py`).
Open questions for the business are in `docs/Scraper-BA-Clarifications.md`.

## 10. Backup, maintenance and recovery

Stop the application (`Stop-SRFU.bat`) before copying or restoring the database. Never copy
`db.sqlite3` while the website or worker is running.

```powershell
python scripts\support\check_db_matches_code.py                                   # MATCH or MISMATCH
python scripts\support\backup_sqlite.py db.sqlite3 "D:\srfu-backups"              # folder must be OUTSIDE the repository
python manage.py migrate --check                                                  # exit 0 = database is up to date
```

`backup_sqlite.py` writes a verified copy with a manifest (SHA-256, integrity check, latest
migration, Git commit). Take one before every upgrade or import, and keep backups outside Git and
access-controlled: they contain personal information. Other tools in `scripts\support\`:
`assert_database_path.py` (confirms which database settings resolve to), `verify_client_import.py`
(read-only comparison of a database with its workbook), `export_organisations_contacts.py`
(CSV export; not a backup), `report_email_activity.py` (lists drafts to reconcile after a restore).

Upgrading: stop the application, back up, `git pull`, `python -m pip install -r requirements.txt`,
`python manage.py migrate`, start again. **Recovery from a restored backup** must include checking
whether any email was sent after the backup was taken, so nothing is sent twice
(`report_email_activity.py` lists the drafts to check). There is **no supported command that
reconciles a restored database** with emails sent after the backup; this is an open item recorded
in the developer handover (section 9.4), so restores must be supervised by a developer.

Logs: `logs\web.*.log` and `logs\worker.*.log` (ignored by Git). Removing old logs is safe.

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `KeyError: 'DJANGO_SECRET_KEY'` | `.env` is missing or lacks the key (step 3) |
| `RuntimeError: OPENAI_API_KEY is not configured.` | Key missing or empty in `.env` |
| `ModuleNotFoundError` | Environment not activated, or step 2's install did not finish |
| `Start-SRFU.bat` says setup is incomplete / database needs migrating | Complete step 3, or run `python manage.py migrate` (after a backup); the launcher never migrates |
| `Start-SRFU.bat` says port 8000 is in use | Another program uses it; close it or run the script with `-Port 8001` |
| Scraper page says the background service is not running | Double-click `Start-SRFU.bat` |
| A scrape ended *Failed* with "automated-access check" | The source blocks automated access; this is not bypassed (see step 9) |
| Invitation or reset email not delivered | Check SMTP settings, restart, then **Resend invitation** |
| Setup link says invalid or expired | Links last 3 days and work once; issue a new one |
| Upload rejected | The message names the missing sheet or column; use the template (step 7) |

## 12. Known limitations

* Hosting, public address, database server and ownership of the OpenAI account and sending mailbox
  are not yet decided; the application is not deployed to a production environment.
* No HTTPS/secure-cookie configuration (depends on hosting). SQLite suits one site with a small
  number of simultaneous Admins; PostgreSQL concurrency has not been tested.
* Scraper coverage is limited as described in step 9. Import confirmation runs inside the web
  request (fine for hundreds of organisations, not for very large files).
* Real email delivery and real AI output have been checked only with stand-ins in automated and
  isolated tests; supervised checks with a test inbox are still required before real outreach.
* Several rules are interpretations awaiting business confirmation:
  `docs/Scraper-BA-Clarifications.md`.

## 13. Automated verification (for developers)

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

The test suite uses its own temporary database, Django's in-memory email outbox, mocked OpenAI
calls and stored web pages; it sends no email, makes no AI call and does not touch the project
database. The full suite takes about 20-25 minutes.

To exercise the running application without side effects (separate database, email written to
files, stand-in AI, network restricted to this computer), use the verification settings in each
PowerShell window **before** any other command:

```powershell
$env:PYTHONPATH             = "$PWD\scripts\verification"
$env:SRFU_VERIFY_DB         = "D:\srfu-verify\verify.sqlite3"     # a database for this exercise only
$env:SRFU_VERIFY_MAIL_DIR   = "D:\srfu-verify\mail"
$env:DJANGO_SETTINGS_MODULE = "verification_settings"
python scripts\support\assert_database_path.py $env:SRFU_VERIFY_DB   # must print OK before anything is written
```

Closing the window ends this mode. It is not a way to run the real system.
`scripts\verification\live_scrape_check_settings.py` additionally allows network access to named
approved scraper hosts for a bounded live check against a disposable database only.

## Project structure

```
srfu/        Django project settings and URLs
accounts/    email-login users, roles, invitations, user management
outreach/    organisations, dashboard, AI draft emails and approval workflow
intake/      workbook import, duplicate review, proposed changes, scraper and worker
scripts/     launcher, support utilities (support/), verification settings (verification/)
static/      CSS and JavaScript
docs/        requirements, acceptance criteria, operating and status documents
```

Roles: `User.role` (`admin` or `staff`) is the source of truth for permissions
(`accounts/roles.py`); Django groups and the superuser flag are ignored for `outreach.*`
permissions. Role changes are made in User Management.
