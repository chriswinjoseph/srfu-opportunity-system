# scripts

Run every command from the project folder (the one containing `manage.py`) with the virtual
environment activated. None of these files contains a secret, a client record or a private path.

| File | Purpose | Changes data? |
|---|---|---|
| `start-demo.ps1` | Starts, checks (`-Status`) and stops (`-Stop`) the website and the background worker; used by `Start-SRFU.bat`, `Status-SRFU.bat`, `Stop-SRFU.bat` in the project folder | No data; starts processes |
| `support/assert_database_path.py` | Prints which database the current settings resolve to; exits 1 unless it is the one you expect and is not the project's own `db.sqlite3`. Run before any write on a disposable database | No |
| `support/check_db_matches_code.py` | Compares applied migrations with the code's migrations (names only) | No |
| `support/backup_sqlite.py` | Verified SQLite backup with a manifest. Refuses a folder inside the repository | No |
| `support/create_email_template.py` | Creates the approved email template; refuses while any `PLACEHOLDER` remains. Copy it, edit the copy, run it (README step 6) | Adds one template |
| `support/verify_client_import.py` | Read-only comparison of a database with the Bank-only client workbook; prints counts only. It reports FAIL if the database holds Branch or Club records or a different number of banks, so it does not apply to databases built from other workbooks | No |
| `support/export_organisations_contacts.py` | Read-only CSV export of organisations and contacts (not a backup). Output holds personal data: keep it outside the repository | No |
| `support/report_email_activity.py` | Read-only list of drafts needing review after a restore | No |
| `verification/verification_settings.py` | Settings for exercising the application without side effects: separate database, email written to files, stand-in AI, network limited to this computer | Only the database you name |
| `verification/live_scrape_check_settings.py` | The same plus network access to named approved scraper hosts, for a bounded live check on a disposable database | Only the disposable database |

Using the verification settings (each PowerShell window, before any other command):

```powershell
$env:PYTHONPATH             = "$PWD\scripts\verification"
$env:SRFU_VERIFY_DB         = "D:\srfu-verify\verify.sqlite3"
$env:SRFU_VERIFY_MAIL_DIR   = "D:\srfu-verify\mail"
$env:DJANGO_SETTINGS_MODULE = "verification_settings"
python scripts\support\assert_database_path.py $env:SRFU_VERIFY_DB     # must print OK
```

Every command then prints a `VERIFICATION MODE:` line. The settings last only for that window.
Do not use them with the real database or a running real worker.
