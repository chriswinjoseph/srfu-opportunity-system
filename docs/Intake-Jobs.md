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

### Windows: double-click launchers (no commands)

In the project folder:

| File | What it does |
|---|---|
| `Start-SRFU.bat` | Starts the website and the background scraper service, waits until both report ready, opens the login page. Safe to double-click again: anything already running is detected and not started twice. If it fails it says why and points to `logs\`. |
| `Status-SRFU.bat` | Shows whether the website and the service are running. Changes nothing. |
| `Stop-SRFU.bat` | Stops the website and service started for this folder. |

Each is a thin wrapper around `scripts\start-demo.ps1` (below). Operator notes:

* **Starting the service runs any scrape that is already queued.** The launcher prints a
  notice when jobs are waiting. Check the Scraper page first if a queued job should not run yet.
* **Website-only use still needs the service.** The Admin queues and watches scrapes in the
  browser, but a background process must be running somewhere. On this machine it is the
  service these launchers start; the computer must stay on and the launcher must have been
  run since the last restart. The pages show "service stopped" (not "running", never
  "successful") if it is not.
* **Stopping** ends the processes immediately. A scrape part-way through keeps the pages it
  finished; after the next start it is picked up again (up to 5 minutes later, when its lease
  expires) and does not repeat finished pages or duplicate records.
* **Restarts.** The launcher does not restart a crashed process. Inside the service, an
  unexpected error in its main loop is retried with a growing pause up to 5 times in a row
  (`--max-errors`), after which it stops with a message in `logs\worker.err.log` and a non-zero
  exit. Double-click `Start-SRFU.bat` again to bring it back. In hosting the platform's restart
  policy does this (see "In hosting").
* The website runs with Django's development server, which is fine for a single-machine demo
  and is not a production web server.

### Windows local demo (one command)

`scripts\start-demo.ps1` starts the website and the worker together, using the project's
virtual environment (`.venv`, then `venv`, whichever has the packages installed):

```
powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1            # start both
powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Status    # what is running
powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Stop      # stop both
```

Options: `-OpenBrowser` (open the login page when ready), `-Port` (default 8000), `-VenvPath`, `-SettingsModule` and `-ExtraPythonPath`
(to run against another settings file, for example a disposable database),
`-StartupTimeoutSeconds` (default 45).

What it does, in order:

1. Finds a virtual environment that has the required packages.
2. Confirms `DJANGO_SECRET_KEY` and `OPENAI_API_KEY` are set (in `.env` or the environment;
   values are never printed).
3. Runs `manage.py check` and `manage.py migrate --check`. It **never runs migrations**: if
   the database needs them it stops and tells you to back up and migrate yourself.
4. Looks for this project's existing website and worker processes and for another program on
   the port. A process that is already running is reported and **not started again**; a busy
   port stops the launch before anything starts.
5. Starts the website (`runserver --noreload`) and the worker as separate hidden processes,
   with logs in `logs\web.*.log` and `logs\worker.*.log` (ignored by git).
6. Waits until the login page answers and the worker has checked in. If either stops or does
   not report in time it prints the last log lines, stops whatever it started, and exits with
   code 1.

It does not start a scrape. The worker only processes jobs an Admin has queued on the Scraper
page; it only claims `queued` scraper runs and uses the same claim, lease and permission rules
described below. `-Stop` is safe at any time: a job that is mid-run is re-queued after its
lease and resumes without creating duplicates.

If the Scraper page shows that "the background service that runs scrapes is not running",
the worker is stopped: run the launcher (or `-Status` to check). Users see only that
plain-language notice; the commands stay here.

Duplicate detection recognises processes started by the launcher, processes started by hand
from the project folder with the project's virtual environment, and a worker started some
other way (found through the heartbeat it writes). `-Stop` only stops processes it can
identify as this project's in the first two ways; note that it therefore also stops a
`runserver` you started by hand with the project's virtual environment.

This launcher is for a single Windows demo machine. It does not restart a process that
crashes later, and it is not a production deployment.

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

### Hosting checklist for the worker (not yet decided; nothing here is deployed)

* a managed process running `python manage.py run_intake_worker` beside the web process;
* restart policy: restart on exit, with a short delay (the command already stops itself after
  5 consecutive loop errors so a platform restart policy, not an endless internal loop, handles
  persistent faults);
* health check: `python manage.py intake_status` (exit 1 when a job waits too long with no
  worker, or a running job stops reporting);
* the same database as the website (PostgreSQL if they run on separate machines), the same
  environment values, and HTTPS egress to the approved hosts only.

The hosting platform is undecided, so this is a requirement to be met, not a statement that
production is ready (see the handover list below).

## Monitoring

* **Admin pages.** A banner appears on the Scraper page and on a queued **or running** run when
  no worker has checked in during the last 90 seconds ("Queued - not started" / "Running -
  service stopped"). A running job reports progress after every page, and the run page updates
  itself every few seconds until the run finishes.
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
* **Errors.** Page failures are recorded with a business-language message, the source URL, the
  reason and the action required, and the run continues. A source that blocks automated access
  is reported differently from one that loaded but listed nothing.
* **Run status.** Successful: every page worked and every result was processed. Partially
  Successful: some work was saved and something failed, was incomplete or awaits review.
  Failed: nothing was processed (every page failed, every record failed, or there was nothing
  to visit). Queued and Running are progress states only. Open points are in
  `Scraper-BA-Clarifications.md`.
* **Counts.** The scraper summary shows page counts (processed, failed) separately from
  organisation counts. Exact duplicates are matched existing organisations and therefore also
  appear under Updated or Unchanged.
* **Coverage.** Only Bank (11 Bendigo Community Bank pages, VIC) has a working source. Clubs
  have a configured council source that blocked automated access when last checked; Branches
  have none. Unsupported selections are refused when queued.

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

## Handover: what is needed before the worker can be set up in hosting

The repository contains no deployment configuration (no Procfile, Dockerfile, platform file,
service definition or production web server), so nothing here has been assumed or deployed.
Two Playwright specs default to a `*.up.railway.app` address, which suggests an earlier
deployment, but nothing in the repository confirms the platform. To add the worker as a
managed, auto-restarting process the following is needed from the client or hosting owner:

1. **Platform and plan** (for example Railway, Render, Azure, a Windows or Linux server), and who
   owns the account and its costs.
2. **How the website is run there** (a production web server such as gunicorn on Linux or
   waitress on Windows is not yet a dependency) and the process or start command it uses.
3. **Database.** The worker and the website must share one database. On a platform where they
   run as separate services, SQLite cannot be shared; that needs PostgreSQL (connection details,
   a driver in `requirements.txt`, and a backup plan). Existing data would need migrating.
4. **Static files and HTTPS settings**: the public address, `DJANGO_ALLOWED_HOSTS`, CSRF trusted
   origins, and how `staticfiles` is served.
5. **Environment values** held in the platform's secret store: `DJANGO_SECRET_KEY`,
   `OPENAI_API_KEY`, the SMTP settings.
6. **Outbound access.** The worker must be able to reach only the approved public hosts over
   HTTPS; any firewall or egress rule needs to allow them.
7. **Restart policy and monitoring**: how the platform restarts a failed worker and where
   `python manage.py intake_status` can be used as a health check.

Once those are known, the worker is added as a separate process (`python manage.py
run_intake_worker`) with automatic restart, as in the examples above.

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
