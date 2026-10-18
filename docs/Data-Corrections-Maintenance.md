# Applying approved client-data corrections (maintenance procedure)

This is the supported way to apply the client-data corrections to the **live** database. It is an
operator procedure: do it in a maintenance window, with the website and the worker stopped.

`apply_data_corrections` (the rehearsal command) still refuses the project's own `db.sqlite3`.
That protection is unchanged and must not be bypassed, and the database must not be renamed to
get around it. The live database is changed only by `corrections_maintenance`, which refuses
unless every safeguard below passes.

## What is corrected

Every correction belongs to one *kind*. Each kind is approved separately.

| Kind | Change |
|---|---|
| `state_in_region` | The state code stored in Region is moved to State (Region is left empty, not guessed). |
| `region_duplicate_of_state` | State is already set and Region still holds the same state code: Region is cleared and State is kept. Proposed only when the workbook confirms the code, the bank was never edited after import, and no source ever supplied a Region. Anything uncertain is excluded and listed with its reason. |
| `unspecified_name` | A contact named `(unspecified)` becomes blank when the workbook has no name. A real name in the workbook is never overwritten. |
| `source_provenance` | Records where each organisation came from, using the recorded import time (no date is invented). |
| `contact_provenance` | Same for contacts, including the delivery-failure evidence. |
| `contact_status` | A bank imported as Contacted whose only evidence is a delivery failure becomes Not Yet Contacted. Never done when there is later outreach, a response, a draft, a recorded contact date, or when the bank is archived. |

Archived organisations are never changed by any kind.

## Procedure

All commands run from the project folder with the project's virtual environment.

1. **Stop writes.**
   `powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Stop`, then `-Status`
   and confirm both are "not running". Also close any website or worker started another way.
2. **Check it is quiet.** `python manage.py corrections_maintenance check`
   (no worker heartbeat in the last 90 seconds, no running scraper job, no website activity in
   the last 3 minutes, no database write in the last 30 seconds). Wait and repeat if it refuses.
3. **Queued scraper jobs.** `check` lists any scraper job an Admin has queued. A queued job is not
   a write, so it does not block maintenance, but it is **not touched** and it will run (live
   scraping of the approved public sites) the next time a worker starts. Therefore:
   * keep the worker stopped for the whole procedure, including after the corrections are applied,
     until step 9 is finished;
   * `apply` and `revert` refuse until you add `--acknowledge-queued-jobs`, which confirms you
     accept that the job stays queued and will run later;
   * decide beforehand whether that job should run at all. The application has no Cancel action
     for a queued job, so if it must not run, that needs a separate decision before the worker is
     started again;
   * the job only concerns the records on the pages it scrapes. Running it after the corrections
     (not before) keeps the plan, the backup and the verification consistent.
4. **Backup, outside Git.**
   `python manage.py corrections_maintenance backup --dest-dir D:\path\outside\the\repo`
   Records the file, its size and sha256 in a `.manifest.json` beside it. The backup is checked
   (SQLite integrity, foreign keys, identical to the live data). A folder inside the repository
   is refused.
5. **Regenerate the plan from the current data.**
   `python manage.py corrections_maintenance plan --workbook <workbook.xlsx> --out plan.json`
   Read the counts and the exclusions. Nothing is changed.
6. **Approve explicitly.**
   `python manage.py corrections_maintenance approve --plan plan.json --kinds state_in_region,region_duplicate_of_state,unspecified_name,source_provenance,contact_provenance,contact_status --approved-by "Name" --out approval.json`
   List only the kinds that have been approved (for example leave out `contact_status` until the
   two status corrections are confirmed). "All" is not accepted. The approval records who approved
   it and fingerprints the exact plan and workbook.
7. **Dry run** (changes nothing):
   `python manage.py corrections_maintenance apply --workbook <workbook.xlsx> --approval approval.json --backup-manifest <backup>.manifest.json --confirm-stopped --acknowledge-queued-jobs`
   (the last flag only when a job is queued). It re-checks that the system is quiet, that the backup is intact, outside Git, less than 60
   minutes old and identical to the live data (any change since the backup is "intervening
   activity" and is refused), regenerates the plan and requires it to match the approval exactly,
   applies the approved kinds inside one transaction, then verifies the result and rehearses the
   rollback, and finally discards everything.
8. **Apply for real:** the same command with `--execute`. All-or-nothing: if any item cannot be
   applied, any check fails, or the rollback rehearsal does not restore the original data exactly,
   nothing is committed. A `.rollback.json` is written beside the backup.
9. **Check the result.** The command prints the dashboard counts before and after. Start only the
   website first (the launcher starts both, so use it only once the queued job is accepted, or
   start `runserver` by hand), open the dashboard and spot-check a corrected bank. Start the
   worker last.
10. **Roll back if needed.**
   `python manage.py corrections_maintenance revert --rollback-file <backup>.rollback.json --confirm-stopped`
   (dry run), then add `--execute` (and `--acknowledge-queued-jobs` if a job is queued). Allow at least
   30 seconds after an `apply --execute` first: the quiet check refuses while the database was written
   recently. It is refused if the database changed after the corrections
   were applied; in that case restore the verified backup file instead.

## What the command verifies before it commits

* Only the approved kinds were applied, and only the five tables a correction may touch changed;
  every other table (users, drafts, templates, sessions, activity log, and so on) is identical.
* Row counts: banks, contacts and opportunities unchanged; new source rows equal the number of
  approved provenance corrections.
* Only the records named in the approved corrections changed.
* Dashboard Contacted and Not Yet Contacted counts moved by exactly the number of approved
  status corrections.
* The rollback, applied inside the same transaction, restores the original data exactly.

## Limits

* A queued scraper job is left untouched and will run when a worker next starts; there is no
  supported way to cancel it from the application.
* The "stopped" checks are heuristics plus the operator's `--confirm-stopped`. The transaction
  also holds the SQLite write lock while it runs, so a writer that is still running waits.
* Revert after later activity is refused by design; restore the backup instead.
* This procedure is for SQLite. A different database engine needs its own backup step.
