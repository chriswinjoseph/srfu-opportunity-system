"""
Monitor the background worker and queued jobs (read-only).

    python manage.py intake_status
    python manage.py intake_status --max-wait-minutes 10   # exit code 1 if unhealthy

Exit code 1 means a job has been waiting too long with no worker running,
or a running job has stopped heartbeating. Suitable for a hosting health
check or a scheduled monitor.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from intake.models import IntakeRun
from intake.scraper import LEASE_SECONDS
from intake.worker import worker_state


class Command(BaseCommand):
    help = "Show whether a worker is running and the state of queued scraper jobs."

    def add_arguments(self, parser):
        parser.add_argument("--max-wait-minutes", type=int, default=10)

    def handle(self, *args, **options):
        now = timezone.now()
        state = worker_state(now)
        queued = IntakeRun.objects.filter(kind=IntakeRun.KIND_SCRAPER, status=IntakeRun.STATUS_QUEUED)
        running = IntakeRun.objects.filter(kind=IntakeRun.KIND_SCRAPER, status=IntakeRun.STATUS_RUNNING)
        problems = []

        if state["last_seen"]:
            self.stdout.write(
                f"Worker: {'running' if state['alive'] else 'NOT running'} "
                f"(last seen {state['last_seen'].isoformat(timespec='seconds')})"
            )
        else:
            self.stdout.write("Worker: NOT running (no worker has ever checked in)")

        self.stdout.write(f"Queued jobs: {queued.count()}   Running jobs: {running.count()}")

        waiting_limit = now - timedelta(minutes=options["max_wait_minutes"])

        for job in queued.filter(created_at__lt=waiting_limit):
            if not state["alive"]:
                problems.append(f"Job {job.pk} has waited since {job.created_at:%Y-%m-%d %H:%M} and no worker is running.")

        stale = now - timedelta(seconds=LEASE_SECONDS)

        for job in running.filter(heartbeat_at__lt=stale):
            problems.append(f"Job {job.pk} is marked running but has not reported progress since {job.heartbeat_at:%Y-%m-%d %H:%M}.")

        if problems:
            raise CommandError(" ".join(problems))

        self.stdout.write("OK")
