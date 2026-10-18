"""
Is a background worker running? Used by the run page, the scraper page and
``intake_status`` so a queued job never looks like it is progressing when
nothing can pick it up.
"""

from datetime import timedelta

from django.utils import timezone

from .models import IntakeRun, WorkerHeartbeat

ALIVE_SECONDS = 90


def beat(name, *, host="", pid=None, started_at=None, jobs_run=None, now=None):
    now = now or timezone.now()
    defaults = {"host": host, "pid": pid, "heartbeat_at": now}

    if jobs_run is not None:
        defaults["jobs_run"] = jobs_run

    row, created = WorkerHeartbeat.objects.get_or_create(
        name=name, defaults={**defaults, "started_at": started_at or now}
    )

    if not created:
        for key, value in defaults.items():
            setattr(row, key, value)

        if started_at:
            row.started_at = started_at

        row.save()

    return row


def worker_state(now=None, alive_seconds=ALIVE_SECONDS):
    """``{"alive": bool, "last_seen": datetime | None}``."""
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=alive_seconds)
    newest = WorkerHeartbeat.objects.order_by("-heartbeat_at").first()
    last_seen = newest.heartbeat_at if newest else None
    running = (
        IntakeRun.objects.filter(
            kind=IntakeRun.KIND_SCRAPER, status=IntakeRun.STATUS_RUNNING,
            heartbeat_at__gte=cutoff,
        )
        .order_by("-heartbeat_at")
        .first()
    )

    if running is not None and (last_seen is None or running.heartbeat_at > last_seen):
        last_seen = running.heartbeat_at

    return {"alive": bool(last_seen and last_seen >= cutoff), "last_seen": last_seen}
