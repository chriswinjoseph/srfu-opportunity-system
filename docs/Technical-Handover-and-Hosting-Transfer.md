# SRFU Technical Setup and Transfer Guide

## 1. Purpose

This guide explains how to install, run, maintain and move the Safe Roads For Us Opportunity System. It is for the developer or operator responsible for supporting Shane after handover.

The application currently runs locally on Windows. A domain is not required for local use. Online hosting requires additional work by a developer or hosting provider.

Safe Roads for Us must retain the source code, its data export and application Admin access. These must not depend on continued access to a developer's personal computer.

## 2. System Overview

| Part | Responsibility |
| --- | --- |
| `srfu/` | Django project settings and URLs. |
| `accounts/` | Login, Admin/Staff roles, invitations, password recovery and user activity. |
| `outreach/` | Organisations, contacts, opportunities, dashboard, drafts, approvals and email sending. |
| `intake/` | Excel imports, duplicate checks, reviews, proposed changes, provenance and scraper jobs. |
| `scripts/` | Launcher, support utilities and verification settings. |
| `static/` | CSS and JavaScript. |
| `docs/` | Requirements and detailed operating instructions. |
| `db.sqlite3` | Local database containing accounts, records, history and the scraper queue. Not included in Git. |

The browser connects to Django. Django uses SQLite for storage, OpenAI for draft generation and SMTP for email. A separate worker processes queued scraper jobs using the same database.

### Important rules

- Contact status is **Not Yet Contacted** or **Contacted**. Interested, Not Interested and Do Not Contact are separate opportunity outcomes.
- Creating or approving a draft does not establish contact. Successful sending, recorded external outreach or qualifying import evidence can establish it.
- Staff can view imported organisations. Importing, starting scraper runs and approving drafts are Admin-only actions.
- Approval applies to the exact draft version. Editing removes approval. Do Not Contact and archive safeguards block outreach.
- Emails require 90–120 words inclusive. A matching template signature at the end is excluded; manual drafts count the entire body.
- Uncertain SMTP delivery must not be retried blindly. SMTP acceptance does not prove delivery to the recipient's inbox.
- Existing data and history must be preserved. Possible duplicates and changes to populated values go through review.

### Database relationships

Banks, Branches and Clubs are separate tables. Records that can belong to any of them use a content type and an integer object ID; some intake records name these fields `target_content_type` and `target_id`. Always use both values when querying. These generic links do not provide an ordinary database foreign key to an organisation.

EmailDraft has an integer primary key and a separate UUID `draft_id` used in draft URLs. The two are not interchangeable. Transfer a compatible whole database or use supported imports; do not copy individual tables between databases with SQL.

## 3. Requirements

For the documented local installation, obtain:

- Windows, PowerShell, Python 3.12 or newer, Git and a browser.
- Internet access for downloading the code and dependencies.
- The client's Admin email and display name.
- The confirmed client workbook and approved email template wording.
- A client-controlled OpenAI key and SMTP mailbox configuration for real drafting and sending.

A fresh clone includes no database, accounts, client workbook, approved template or `.env`. Client records entered on one local installation do not automatically appear on another computer.

Use the README and `scripts/README.md` belonging to the selected release. Record its commit hash and check commands against that release before transfer.

## 4. Initial Setup

These steps create a new installation. To move an existing installation, use section 7 instead.

### Download and install

1. Open PowerShell in a writable folder. The example uses your Windows home folder.
2. Clone the repository and enter the project folder.
3. Create and activate the Python environment.
4. Install and check dependencies.

```powershell
New-Item -ItemType Directory -Force "$HOME\srfu" | Out-Null
Set-Location "$HOME\srfu"
git clone https://github.com/chriswinjoseph/srfu-opportunity-system.git
Set-Location srfu-opportunity-system
git rev-parse HEAD
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip check
```

If activation is blocked, run `Set-ExecutionPolicy -Scope Process Bypass`, then activate again. Enter the folder containing `manage.py` and activate the environment in every new terminal.

### Configure the application

On a new installation only:

```powershell
Copy-Item .env.example .env
notepad .env
```

| Setting | Value needed |
| --- | --- |
| `DJANGO_SECRET_KEY` | A new random secret for a new installation. |
| `DJANGO_DEBUG` | `True` for this local setup. Hosting requires separate security and static-file configuration. |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` for local use. |
| `OPENAI_API_KEY` | A valid key for real drafting. The application currently requires a non-empty value even for startup commands. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS` | SMTP connection settings from the email provider. |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP authentication details. |
| `DEFAULT_FROM_EMAIL` | The authorised sending address. Replace the example value. |

Generate a secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Never commit `.env` or put secrets in documentation. The Admin login address is separate from the SMTP sender. For an existing installation, preserve settings until the transfer plan is agreed; changing the signing key can invalidate sessions and links.

### Optional isolated rehearsal

For testing, configure verification mode **before migrations or other database writes**. Repeat this in every test terminal:

```powershell
$env:PYTHONPATH = "$PWD\scripts\verification"
$env:SRFU_VERIFY_DB = "$HOME\srfu-verification\verify.sqlite3"
$env:SRFU_VERIFY_MAIL_DIR = "$HOME\srfu-verification\mail"
$env:DJANGO_SETTINGS_MODULE = "verification_settings"
python scripts\support\assert_database_path.py $env:SRFU_VERIFY_DB
```

Continue only when the path check reports `OK` for the separate test database. Use synthetic data and wording. Email goes to files, AI is simulated and external network access is blocked. This does not verify live services. Stop test processes and close the configured terminals before normal operation.

### Create the database and Admin

1. Apply migrations and check the application.
2. Start the website and leave the terminal open.

```powershell
python manage.py migrate
python manage.py migrate --check
python manage.py check
python manage.py runserver 127.0.0.1:8000
```

3. Open another terminal, enter the project folder and activate the environment. If testing, repeat verification settings there too.
4. Create the first Admin, replacing the name placeholder. Use a synthetic email during rehearsal.

```powershell
python manage.py create_first_admin --email "info@saferoadsforus.com.au" --name "<confirmed display name>" --base-url http://127.0.0.1:8000 --print-link
```

5. Open the private setup link while the website is running and choose a password.

The link is single-use and expires after three days. Django stores a salted password hash. Omit `--print-link` to send the link using configured SMTP; in verification mode the email is saved to the test mail folder instead.

The command refuses once an active Admin has completed setup. Create subsequent users through User Management. Do not copy development password hashes or create an unnecessary Django superuser.

### Add the template and workbook

1. Copy `scripts/support/create_email_template.py` to a writable location outside the repository.
2. Replace every `PLACEHOLDER` with SRFU-approved wording. Use synthetic wording for rehearsal.
3. Run the script using the instructions in `scripts/README.md`.
4. Sign in as Admin and open **Data > Import Data**.
5. Upload the workbook, review the preview, confirm and inspect the results.

Both single-sheet and original Organisations/Contacts workbooks are supported. See `docs/Import-Format.md`. An `overall_status` label alone does not establish Contacted.

The confirmed client workbook's recorded SHA-256 is:

```text
ca221f1427e7ac528e094fbfff61ca26f817f770b684329739cda024ab39ab57
```

A clean import of that workbook produced **168 Banks, 244 contacts, 166 Contacted and 2 Not Yet Contacted**. These are initial dataset counts, not expected totals after later client activity. Use `scripts/support/verify_client_import.py` with its documented options to check the import.

## 5. Starting, Stopping and Maintenance

After initial setup, use Windows File Explorer:

| File | Action |
| --- | --- |
| `Start-SRFU.bat` | Starts the website and worker, then opens the browser. |
| `Status-SRFU.bat` | Shows process status. |
| `Stop-SRFU.bat` | Stops both processes. |

Open the application at `http://127.0.0.1:8000/accounts/login/`. Opening a `.bat` file in an editor only displays its contents. Daily website use does not require VS Code or GitHub push permission.

The computer must stay on. The launcher does not migrate the database or provide production process supervision. Starting the worker can process already queued jobs.

For manual operation, use `python manage.py runserver 127.0.0.1:8000` for the website and `python manage.py run_intake_worker` in a separate terminal for the worker. Use `python manage.py intake_status` for queue/worker health information.

### Scraper coverage

The Bank scraper supports 11 fixed Victorian Bendigo Community Bank pages. The council Club source blocks automated access, and no Branch source is configured. It cannot collect from an arbitrary website.

Partial success means some work completed while other results failed or need attention. Check individual run results. Adding sources requires permitted access, extraction rules and testing; do not bypass access controls.

### Routine maintenance

Assign someone to review failed jobs and email issues, manage dependencies and credentials, and maintain backups. Verify updates in isolation before upgrading. Keep logs private because infrastructure access logs may contain setup/reset links. Review duplicate and proposed-change records through supported Admin controls.

## 6. Data Export and Admin Handover

Safe Roads for Us must receive:

- Control of the agreed source repository or a complete client-controlled release copy, including migrations, tests, scripts and documentation.
- A verified database backup and an organisation/contact export through a private channel.
- Working client Admin access and instructions for managing users.
- Ownership or agreed control of service accounts and backup storage.

Use `scripts/support/export_organisations_contacts.py` with the options in `scripts/README.md`. Supply the output files and manifest where produced. CSV exports are for accessing business data; they are not a full backup of accounts, drafts and history.

For the clean client installation, create `info@saferoadsforus.com.au` as the sole initial application Admin. Keep development users, test records and development activity out of it, while preserving them in a private backup. Keep logging enabled for genuine client actions.

If transferring an existing installation, verify client Admin access before disabling temporary development accounts. Preserve genuine client history. Transfer secrets privately and retire development credentials after client services work. Confirm receipt of source, data and access; do not mark them transferred based only on document approval.

## 7. Moving the System

### Prepare the destination

1. Agree the destination, responsible developer, database storage and backup location with SRFU.
2. Record the approved code commit and database/migration state.
3. Install that release and its dependencies on the destination.
4. Configure private settings and rehearse using a separate database.

For an existing client installation, transfer its complete current database. For a first clean client installation, build a new candidate from the confirmed workbook. Do not replace genuine later activity with an older prepared candidate.

### Back up before switching

Stop the website and worker and confirm no process is writing. Create a verified backup outside the repository:

```powershell
python scripts\support\backup_sqlite.py db.sqlite3 "$HOME\srfu-backups"
```

Keep its manifest, matching source release and private configuration in access-controlled storage. Agree backup frequency and retention with SRFU.

### Transfer and verify

1. Obtain approval for the candidate and maintenance period.
2. Stop both installations' websites and workers. Inspect queued jobs.
3. Take a fresh final backup. For an existing installation, use its stopped-state database so recent activity is retained.
4. Keep the old installation intact and stopped. Copy the approved database to the destination's configured operational location and verify its checksum.
5. With services stopped, run:

```powershell
python scripts\support\check_db_matches_code.py
python manage.py migrate --check
python manage.py check
```

6. Require `RESULT : MATCH` and successful checks. On mismatch, stop and resolve the release/schema difference. Do not reverse migrations or overwrite data blindly. The match utility checks migration names, not all data correctness.
7. Start the destination website only. Check client login, dashboard counts, sample records, history and permissions.
8. Complete supervised SMTP and AI checks using a controlled inbox and approved template. Do not email client organisations as a smoke test.
9. Review queued jobs before starting the worker. Keep the old installation stopped.
10. Record the destination, release, verification results, owners and unresolved issues in the handover record.

### If SRFU moves online

A future developer must configure production web serving, static files, HTTPS, allowed hosts, CSRF origins, secure cookies, private secrets and debug off. They must also arrange persistent storage, managed worker restart, monitoring and scheduled backups.

The current launcher uses Django's development server and is not a production deployment. Separate services must not use independent SQLite copies. A move to PostgreSQL needs migration and verification; current SQLite tests do not prove PostgreSQL behaviour.

### Recovery limitation

Restore a compatible combination of code, dependencies and database. Preserve the failed database and post-backup activity first.

**Rollback reconciliation remains a blocker:** an older backup may show an already-sent draft as approved and sendable. The application has no complete supported procedure to reconcile all later sends or clear all reconciliation flags, and it stores no Message-ID.

`scripts/support/report_email_activity.py` lists drafts requiring review; it does not reconcile them. SMTP acceptance is not proof of delivery, and the mailbox's Sent folder is not guaranteed to record SMTP sends. Recording external contact alone does not remove follow-up duplicate-send risks.

Keep services stopped until a reviewed reconciliation procedure resolves the risks. A valid backup alone does not make restarting safe after possible email activity.

## 8. Troubleshooting and Limitations

| Problem | Action |
| --- | --- |
| `manage.py` cannot be found | Enter the cloned project folder containing that file. |
| Missing Python package | Activate the environment and complete dependency installation. |
| Missing secret or OpenAI key | Check private `.env` settings without sharing their contents. |
| No approved templates available | Complete template setup with approved wording. |
| Invitation or reset not received | Check SMTP and sanitised logs. Resend pending invitations through Admin controls; request another password reset through Forgot password. |
| Scrape remains queued | Check the worker and run status. |
| Automated-access check reported | The source blocks collection; do not bypass it. |
| Database/code mismatch | Stop and resolve the release/schema difference before startup. |

Run automated checks against the delivered release:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

The reported developer run passed **734 tests at commit `83c88f0` on 27 October 2026**. The fresh-clone rehearsal used the developer's computer, simulated AI and file-based email. These results do not verify later releases, another computer or live client services. Independent testing was reported as in progress; confirm its outcome separately.

Keep these outstanding matters assigned until resolved:

- Client database cutover, Admin setup and approved template wording.
- Real SMTP and AI verification, and client acceptance.
- Service/repository ownership, backup storage and hosting if needed.
- The rollback reconciliation blocker.
- State/Region filtering and pending matching/import decisions.
- Historical repository exposure: the database backup was removed from reachable history, but GitHub's purge of old objects is unconfirmed. The repository owner must resolve and record the outcome.
