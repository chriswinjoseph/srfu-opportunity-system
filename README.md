Safe Roads For Us Opportunity System
A Django application for managing outreach to community banks, bank branches and sports clubs. It brings organisation records, contacts, email drafts and outreach history into one place.
Features
- Organisation search, filters, contact history and archiving.
- Admin and Staff roles, invitation-only accounts and password recovery.
- AI-assisted or manual email drafts, with Admin approval before sending.
- Excel import with preview, duplicate review and proposed changes.
- Background scraping from configured public sources.
Organisation contact status is Not Yet Contacted or Contacted. Responses such as Interested, Not Interested and Do Not Contact are recorded separately. Creating or approving a draft does not mark an organisation Contacted.
Before you begin
The documented installation is for local use on Windows with PowerShell. It is not a production hosting configuration. The website and scraper worker share a SQLite database on the same computer.

You need Python 3.12 or newer, Git and a browser. Python 3.12.5 and Windows PowerShell 5.1 were used in developer verification. Dependencies are listed in requirements.txt.

A clone contains source code only. It does not include the client workbook, database, accounts, passwords, .env, API keys or approved email template. It does not connect to the developer's installation.

Choose your route before creating the database:
Route	Use
Client installation	Complete setup with the person responsible for maintaining the system. Use client-controlled services, the confirmed workbook and approved template wording.
Isolated verification	Use a separate database, synthetic data, file-based email and simulated AI. Configure verification mode after environment setup and before migrations.


Never share .env, passwords, API keys or invitation/reset links in screenshots, messages or issue reports.
1. Get the code
These PowerShell examples use a folder under your Windows user profile. You may choose another writable location. Do not clone over an existing installation.
New-Item -ItemType Directory -Force "$HOME\srfu" | Out-Null
Set-Location "$HOME\srfu"
git clone https://github.com/chriswinjoseph/srfu-opportunity-system.git
Set-Location srfu-opportunity-system
git rev-parse HEAD
Record the commit hash when reporting a problem. If repository access is restricted, request access from its owner.
2. Install dependencies and configure the environment
Run commands from the folder containing manage.py.
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip check
Copy-Item .env.example .env
notepad .env
Copy .env.example only on a new installation; do not overwrite an existing .env. If activation is blocked, run Set-ExecutionPolicy -Scope Process Bypass, then activate again. That policy change applies only to the current PowerShell window.
Setting	What to supply
DJANGO_SECRET_KEY	A new secret. Generate one with python -c "import secrets; print(secrets.token_urlsafe(50))".
DJANGO_DEBUG	True for this local development-server setup. A hosted deployment needs different security and static-file configuration.
DJANGO_ALLOWED_HOSTS	For local use, 127.0.0.1,localhost.
OPENAI_API_KEY	A valid client-controlled key for real drafting. The application currently requires a non-empty value even for startup commands. A placeholder cannot generate real drafts.
EMAIL_HOST, EMAIL_PORT, EMAIL_USE_TLS	Settings supplied by the sending mailbox provider.
EMAIL_HOST_USER, EMAIL_HOST_PASSWORD	Mailbox authentication details; use a provider-issued App Password where required.
DEFAULT_FROM_EMAIL	The authorised sender address; replace the example placeholder.


The Admin login email and SMTP sender are separate settings. Creating an Admin does not configure email delivery. Real invitations, resets and outreach require working SMTP settings; normal operation has no console email fallback.

For isolated testing, synthetic non-secret configuration values are sufficient only after verification settings are enabled. Continue with the following section before any database-writing command. For a client installation, skip it and continue to section 3.
Isolated verification
In every PowerShell window used for testing, activate the environment, enter the project folder and run:
$env:PYTHONPATH = "$PWD\scripts\verification"
$env:SRFU_VERIFY_DB = "$HOME\srfu-verification\verify.sqlite3"
$env:SRFU_VERIFY_MAIL_DIR = "$HOME\srfu-verification\mail"
$env:DJANGO_SETTINGS_MODULE = "verification_settings"
python scripts\support\assert_database_path.py $env:SRFU_VERIFY_DB
The path check must report OK and identify the separate verification database. Stop if it resolves to the operational database. Use a new location for a separate exercise.

This mode writes email to files, substitutes simulated AI and blocks non-local network connections. It does not verify real email delivery, real OpenAI output or live scraping. Use synthetic workbooks and template wording. See [README.md](scripts/README.md) for supported verification procedures.

Closing a terminal does not stop processes already running. Stop the test website and worker, then close every configured window before returning to normal operation. A new terminal does not inherit these settings.
3. Create the database and first Admin
For a new installation:
python manage.py migrate
python manage.py migrate --check
python manage.py check
python manage.py runserver 127.0.0.1:8000
Leave the website running. Open another PowerShell window, enter the project folder and activate .venv. If testing, configure verification mode there too.

For normal local setup, replace the email and name placeholders:
python manage.py create_first_admin --email "<admin email>" --name "<Admin name>" --base-url http://127.0.0.1:8000 --print-link
Open the printed single-use link while the website is running and set your own password. The link is secret and expires after three days. The command does not choose a password; Django stores a salted password hash after setup.

With configured SMTP, omit --print-link to email the link. In verification mode, omit it to write the email to the verification mail folder instead. Follow the local file's setup link without sharing it.

There are no default credentials. The first-Admin command refuses once an active Admin has completed setup. If setup is unfinished, running it again issues a replacement link and invalidates the previous one. Invite subsequent users through User Management.

When transferring an existing installation, create and verify the client's Admin access before disabling the temporary Admin. Do not copy development password hashes or create a Django superuser just to obtain an application Admin account.
4. Add the email template and organisation data
Approved email template
Draft generation needs an active template. None is seeded automatically and there is no template editor. Copy the support script, replace every PLACEHOLDER with approved wording, and run it:
$templateScript = "$HOME\srfu-create-template.py"
Copy-Item scripts\support\create_email_template.py $templateScript
notepad $templateScript
python manage.py shell -c "exec(open(r'$templateScript', encoding='utf-8-sig').read())"
The script refuses unresolved placeholders. Follow its signature instructions. For isolated verification, use synthetic wording; for client use, obtain SRFU approval first.
Excel import
Sign in as an Admin and open Data > Import Data. Download a template or synthetic example, upload a genuine .xlsx, inspect the preview and confirm the import.
- Single sheet: headers organisation_id, bank_name, state, contact_names, emails, overall_status. ID, name and State require values; the remaining fields may be blank.
- Two sheets: the original client format with Organisations and Contacts, including outreach evidence.
- Extra supported columns are accepted; unsupported columns are identified and ignored.
- overall_status alone never establishes Contacted. Unsupported Contacted claims are held for review.
- Names and emails are paired only where one of each is supplied. Multiple-contact rows are not paired by position.
Review possible duplicates and proposed changes before deciding. Repeat imports use the duplicate safeguards; inspect the results rather than assuming every row was accepted. Use the confirmed workbook for client setup and synthetic examples for testing.

Full rules: [Import-Format.md](docs/Import-Format.md).
5. Daily use
After initial setup, open the project folder in Windows File Explorer:
Action	File
Start website and scraper worker; open the browser	Double-click Start-SRFU.bat
Check whether both are running	Double-click Status-SRFU.bat
Stop both	Double-click Stop-SRFU.bat


Opening a .bat file in a code editor only displays its contents. Run it from File Explorer, or use the documented PowerShell launcher commands in [Intake-Jobs.md](docs/Intake-Jobs.md).

Sign in at http://127.0.0.1:8000/accounts/login/. VS Code is not required for daily operation. The computer must stay on while this local installation is in use. Other computers do not automatically share its database or website.

The launcher does not install dependencies or apply migrations. Starting the worker can process an already queued scrape. Check the queue before starting it if a job must remain paused. For website-only operation, use python manage.py runserver 127.0.0.1:8000 in an activated environment and leave that terminal open.
Accounts and email workflow
Admins manage users, organisations, approvals, imports and scraping. Staff prepare drafts and send approved emails within their permissions.

Drafts require 90–120 words inclusive. A matching template signature at the end is excluded; manual drafts count every word. An Admin approves the exact version, and editing removes approval. Do Not Contact and archive safeguards block outreach. Confirmed SMTP acceptance updates contact status; it is not proof of inbox delivery. Uncertain sends are blocked from retry pending reconciliation.

For a pending invitation, an Admin uses Resend invitation. For password recovery after account setup, use Forgot password? The reset page intentionally does not reveal whether an account exists or delivery succeeded. If SMTP fails, fix the configuration and request a new reset; invitation resend is not a password-reset action.

Workflow details: [Email-Approval-Workflow.md](docs/Email-Approval-Workflow.md).
Scraping
An Admin queues a run from Data > Scraper. The worker processes supported sources, and the results identify completed work, failures and items requiring review. A queued run waits when the worker is stopped.

Current coverage is 11 configured Victorian Bendigo Community Bank pages. The council Club directory blocks automated access; the system does not bypass it. No Branch source is configured. This is not a general-purpose scraper for arbitrary websites.

New organisations start as Not Yet Contacted. Existing records are matched, blank fields may be filled, and changes to populated values go to review. Scraping does not mark organisations Contacted.

Worker operation and source decisions: [Intake-Jobs.md](docs/Intake-Jobs.md) and [Scraper-BA-Clarifications.md](docs/Scraper-BA-Clarifications.md).
6. Backups and maintenance
The operational database is db.sqlite3 in the project folder. Keep backups, exports and candidate databases outside the repository, in access-controlled storage. They contain personal information and are not supplied by a Git clone.

Before upgrading or replacing data, stop the website and worker and take a verified backup:
python scripts\support\backup_sqlite.py db.sqlite3 "$HOME\srfu-backups"
After a restore or code change, check compatibility before restarting:
python scripts\support\check_db_matches_code.py
python manage.py migrate --check
python manage.py check
The match utility reports RESULT : MATCH or RESULT : MISMATCH and lists migrations ahead of or behind the code. Do not resume operation on a mismatch. migrate --check alone does not detect a database ahead of the code.

Recovery limitation: restoring an older database can make an already-sent draft appear sendable. There is no supported procedure to reconcile all post-backup email activity. Keep services stopped and involve the maintainer; a restore is not complete until duplicate-send risks are resolved. Do not overwrite newer activity or use Git to recover client data.

Detailed tools and procedures: [README.md](scripts/README.md) and the developer handover supplied with the installation.
7. Troubleshooting
Problem	Action
manage.py cannot be found	Enter the cloned project folder containing manage.py.
Missing Python module	Activate the project environment and complete dependency installation.
Missing secret key or OpenAI key	Check .env; never paste its contents into a support request.
Launcher reports pending migrations	Back up an existing database, then apply migrations as directed.
Port 8000 is busy	Check application status and identify the existing process before starting another.
No approved templates available	Complete the template setup above.
Invitation or reset does not arrive	Check SMTP configuration and sanitised server logs; retry using the appropriate account action.
Scrape remains queued	Check worker status and the run page.
Scrape reports an automated-access check	The source blocks collection; do not attempt to bypass it.
Upload rejected	Use the page's template and correct the sheet, header or row identified in the message.


Logs written by the launcher are under logs/. Keep logs and setup links private. Include the commit hash, command and sanitised error when reporting a problem.
8. Verification and current limitations
Automated checks:
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
Automated tests use isolated test databases and substitutes for external services. A passing test suite does not establish real SMTP delivery, live AI behaviour or client acceptance. Running-app verification uses the separate mode described earlier.

Before live outreach, complete supervised checks of an invitation, password reset and outreach email to a controlled test inbox, plus a real AI draft using the approved template. Record the results and outstanding client decisions.

Remaining limitations include:
- Production hosting, ownership and deployment security need agreement; the local launcher uses Django's development server. Setting debug off alone does not configure static-file serving or HTTPS.
- Client mailbox, API ownership, approved template and account transfer must be completed for the installation. There is no application-enforced AI spending cap.
- Scraper coverage is restricted as described above; larger imports and a move away from SQLite need further assessment.
- State/Region filtering and several matching/import interpretations await business confirmation in the project documentation.
- Session expiry settings are configured, but real elapsed-time and browser-close behaviour have not been independently verified.
- A historical database backup was removed from reachable repository history. GitHub's purge of old objects remains unconfirmed; the repository owner must resolve that exposure.
- Backup rollback reconciliation remains a blocker, as described above.
Project layout
accounts/   Login, roles, invitations and user management
outreach/   Organisations, dashboard, drafts and approval workflow
intake/     Excel import, reviews, provenance, scraper and queue
srfu/       Django settings and URLs
scripts/    Launcher, support tools and verification settings
static/     CSS and JavaScript
docs/       Requirements and detailed operating documentation