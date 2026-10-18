# Running and monitoring the live scraper (background jobs)

Scraping never runs inside a web request. The Admin page **Data > Scraper** queues a job;
a separate **worker** process runs it. If no worker is running, queued jobs simply wait:
the run page and the Scraper page say so ("Queued - not started. No background worker is
running") instead of showing progress.

## Why a database-backed queue

The project has no task broker and no deployment configuration, so jobs are rows in the
database (`IntakeRun`, kind *scraper*). Jobs survive restarts, need no extra service, and work
with the existing Django/SQLite setup.

## Start the worker

```
python manage.py run_intake_worker            # keep polling (normal)
python manage.py run_intake_worker --once     # run what is queued, then exit (for a scheduler)
```

Options: `--poll-seconds` (default 5), `--lease-seconds` (default 300), `--name`.

The worker must use **the same database file and settings** as the website, so it must run on
the same machine (SQLite is a single file). With a different database engine (see
"Hosting limits") it can run anywhere that reaches that database.

### Locally (development)

1. Terminal 1: `python manage.py runserver`
2. Terminal 2 (same virtual environment): `python manage.py run_intake_worker`
3. Queue a scrape as an Admin; the run page switches from "Queued - not started" to
   "Running", then shows the summary. Stop the worker with Ctrl+C: a job in progress is
   re-queued automatically once the lease expires (5 minutes by default).

### In hosting

Run the worker as a **second long-lived process next to the web process**, restarted
automatically if it exits. Examples (adapt paths):

* **Linux (systemd)**

  ```
  [Unit]
  Description=SRFU intake worker
  After=network.target

  [Service]
  WorkingDirectory=/srv/srfu
  ExecStart=/srv/srfu/venv/bin/python manage.py run_intake_worker
  Environment=DJANGO_SETTINGS_MODULE=srfu.settings
  Restart=always
  RestartSec=5
  User=srfu

  [Install]
  WantedBy=multi-user.target
  ```
* **Platform "worker" process** (Procfile-style hosts): add
  `worker: python manage.py run_intake_worker` beside the `web:` process.
* **Windows**: Task Scheduler "At startup" task running
  `venv\Scripts\python.exe manage.py run_intake_worker` (restart on failure), or a service
  wrapper such as NSSM.
* **No always-on process available**: schedule
  `python manage.py run_intake_worker --once` every minute (cron / Task Scheduler). A queued
  job then starts within a minute. The Scraper page will say "No background worker is running"
  between runs; that is expected in this mode.

Only one worker is normally needed. Several are safe: a job is claimed by one conditional
database update, so two workers can never run the same job (verified, see below).

## Monitoring

* **Admin pages.** A banner appears on the Scraper page and on a queued run when no worker has
  checked in during the last 90 seconds. A running job reports progress after every page.
* **Command line / health check.**

  ```
  python manage.py intake_status
  python manage.py intake_status --max-wait-minutes 10
  ```

  Prints whether a worker is running and how many jobs are queued or running. It exits with a
  non-zero code (and says why) if a job has waited longer than the limit with no worker
  running, or a running job has stopped reporting progress. Point a hosting health check or a
  scheduled monitor at it.
* **Logs.** Technical details are logged under the `intake`, `intake.scraper`, `intake.fetch`
  and `intake.worker` loggers. Admins only ever see short business-language messages.

## How it behaves

* **Claiming.** A queued job is claimed with one conditional update; the loser gets nothing.
* **Interrupted jobs.** If a worker stops, the job heartbeat goes stale. After the lease the
  next worker re-queues it (up to 3 attempts, then it is marked Failed). Finished pages are
  remembered and every record goes through the duplicate pipeline, so resuming never creates
  duplicates. A worker that finds its job was taken over (lease token changed) stops instead of
  double-processing.
* **Crashes.** If a job raises an unexpected error the worker records a safe failure on that
  job, logs the details, and carries on with the next job.
* **No overlapping runs.** A new job for a source that already has a queued or running job is
  refused.
* **Bounds.** Connect timeout 5 s, read timeout 15 s, 2 MB per page, at most 60 pages and 20
  minutes per run, a pause between requests, no retries of a failed page within a run.
* **Public pages only.** HTTPS pages on explicitly approved hosts (also after redirects),
  robots.txt respected, login pages and forbidden pages are not collected, an automated-access
  (bot-protection) check is reported and **not bypassed**, honest user-agent
  `SafeRoadsForUsCollector/1.0`.
* **Errors.** Page failures are recorded with a business-language message and the run
  continues.

## Legacy command-line entry points

The older commands no longer write organisations directly:

| Command | Now |
|---|---|
| `scrape_banks`, `scrape_clubs` | `--dry-run` previews approved pages through the shared fetcher; `--queue --admin-email <admin>` queues the same job as the Scraper page; without either, refuses with guidance. |
| `run_scraper`, `outreach.scraper.scrape_public_banks` | Retired (refuse / raise). They used a demo list, a browser-style user agent and their own duplicate rule. |
| `import_bank_contacts`, `import_seed` | Validate with the shared workbook rules (default / `--dry-run`); `--commit --admin-email <admin>` runs the same preview-and-confirm import as the Admin page. |
| `import_clubs` | Disabled for writing (own duplicate rule). `--dry-run` only counts rows. Use the Scraper or the Admin import with an `organisation_type` column. |

## Importing into the real database: order of operations

The client database holds the 168 organisations from the earlier command-line import: no source
IDs, the state stored in Region, `(unspecified)` as a contact name. Recommended order (Admin
decision, nothing here has been applied):

1. Back up the database.
2. Run the read-only preview and review it: `python manage.py plan_data_corrections <workbook> --json plan.json`
3. Rehearse the plan and its rollback on a disposable copy (`apply_data_corrections plan.json
   --rollback-file rollback.json`, then `... rollback.json --revert`). The command deliberately
   refuses to run against the project's own `db.sqlite3`, so applying corrections to the real
   database is a separate, still-unmade decision (it needs an approved procedure, such as a
   documented override, plus the backup above).
4. Apply the pending migrations, then use the Admin import. Legacy banks whose Region holds the
   state code are matched exactly (State is read from Region when blank), so the import links
   sources and provenance instead of holding every organisation for review.

## Hosting limits

* SQLite allows one writer at a time. Settings use `transaction_mode: IMMEDIATE` and a 30
  second wait so simultaneous imports, reviews and workers queue instead of failing with
  "database is locked" (before this setting, simultaneous writers lost records; see
  `intake/tests/concurrency_rehearsal.py`). It is safe for the expected Admin-only volume;
  heavy concurrent use, or running the web process and worker on different machines, needs
  PostgreSQL (the `IntakeLock` serialisation and conditional updates used here also work there,
  but concurrency has not been exercised on PostgreSQL).
* The Excel import confirmation still runs inside the web request (168 organisations take
  seconds). A much larger file should be moved onto the worker.
