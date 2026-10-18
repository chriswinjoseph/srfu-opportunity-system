"""
Run queued scraper jobs outside the web request.

    python manage.py run_intake_worker            # keep polling
    python manage.py run_intake_worker --once     # process what is queued, then exit

Start it as a separate process next to the web server (or from a scheduler
such as cron / Task Scheduler with --once). A job whose worker stops is
re-queued automatically after the lease expires. See docs/Intake-Jobs.md.
"""

import logging
import os
import socket
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from intake.scraper import LEASE_SECONDS, claim_next_job, fail_job, recover_stale_jobs, run_job
from intake.worker import beat

logger = logging.getLogger("intake.worker")


class Command(BaseCommand):
    help = "Process queued live-scraper jobs (durable, database-backed)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Exit when no job is queued.")
        parser.add_argument("--poll-seconds", type=int, default=5)
        parser.add_argument("--lease-seconds", type=int, default=LEASE_SECONDS)
        parser.add_argument("--name", default="", help="Worker name (default: host-pid).")

    def handle(self, *args, **options):
        host = socket.gethostname()
        pid = os.getpid()
        name = options["name"] or f"{host}-{pid}"
        started = timezone.now()
        jobs_run = 0
        self.stdout.write(f"Intake worker '{name}' started. Press Ctrl+C to stop.")

        try:
            while True:
                beat(name, host=host, pid=pid, started_at=started, jobs_run=jobs_run)
                recovered = recover_stale_jobs(options["lease_seconds"])

                for pk in recovered:
                    self.stdout.write(f"Re-queued interrupted job {pk}.")

                run = claim_next_job()

                if run is not None:
                    self.stdout.write(f"Running scraper job {run.pk}...")

                    try:
                        finished = run_job(run)
                        self.stdout.write(f"Job {run.pk} finished: {finished.get_status_display()}.")
                    except Exception:
                        logger.exception("Scraper job %s failed", run.pk)
                        fail_job(run)
                        self.stdout.write(f"Job {run.pk} failed because of a system error; the worker continues.")

                    jobs_run += 1

                    continue

                if options["once"]:
                    return

                time.sleep(options["poll_seconds"])
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped. Any job in progress will be re-queued after the lease expires.")
