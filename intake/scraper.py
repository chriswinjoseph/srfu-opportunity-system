"""
The live scraper job: queued by an Admin, run outside the web request.

Durable job mechanism (see docs/Intake-Jobs.md): jobs are rows in the
database (IntakeRun, kind=scraper). A worker process
(``python manage.py run_intake_worker``) claims a queued job atomically,
keeps a heartbeat while it works, and a stale job whose worker died is
re-queued (up to MAX_ATTEMPTS). Re-running a page is safe because every
record goes through the shared duplicate pipeline, and finished pages are
remembered so they are not processed twice.
"""

import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .fetch import PublicFetcher
from .ingest import finish_run, process_submission
from .matching import Submission
from .models import IntakeResult, IntakeRun
from .normalise import norm_place
from .reviews import require_admin
from .sources import ADAPTERS, ORG_TYPE_LABELS, plan_coverage

logger = logging.getLogger("intake.scraper")

MAX_PAGES = 60
MAX_RUNTIME_SECONDS = 20 * 60
LEASE_SECONDS = 300
MAX_ATTEMPTS = 3
ACTIVE = (IntakeRun.STATUS_QUEUED, IntakeRun.STATUS_RUNNING)


class ScrapeError(Exception):
    """The scrape could not be queued; the message is safe to show."""


def start_scrape(user, org_types, states, suburbs=()):
    require_admin(user)
    org_types = list(org_types)

    if not org_types:
        raise ScrapeError("Choose at least one organisation type to collect.")

    unknown = [t for t in org_types if t not in ORG_TYPE_LABELS]

    if unknown:
        raise ScrapeError("Unsupported organisation type selected. Choose Bank, Branch or Club.")

    adapters, unsupported = plan_coverage(org_types, states, suburbs)

    if not adapters:
        raise ScrapeError(
            "No approved public source covers that selection. "
            + " ".join(unsupported)
        )

    keys = sorted({a.key for a in adapters})

    with transaction.atomic():
        active = IntakeRun.objects.filter(kind=IntakeRun.KIND_SCRAPER, status__in=ACTIVE)

        for other in active:
            if set(other.options.get("adapters", [])) & set(keys):
                raise ScrapeError(
                    "A scraper run for one of these sources is already queued or running. "
                    "Wait for it to finish."
                )

        return IntakeRun.objects.create(
            kind=IntakeRun.KIND_SCRAPER,
            status=IntakeRun.STATUS_QUEUED,
            source_key="scraper",
            source_label="Live scraper",
            created_by=user,
            options={
                "org_types": list(org_types),
                "states": [s.upper() for s in states],
                "suburbs": list(suburbs),
                "adapters": keys,
                "unsupported": unsupported,
                "done_pages": [],
            },
        )


# ------------------------------------------------------------------ queue
def claim_next_job(now=None):
    """Atomically claim the oldest queued scraper job, or None."""
    now = now or timezone.now()

    for candidate in IntakeRun.objects.filter(
        kind=IntakeRun.KIND_SCRAPER, status=IntakeRun.STATUS_QUEUED
    ).order_by("created_at", "id"):
        claimed = IntakeRun.objects.filter(
            pk=candidate.pk, status=IntakeRun.STATUS_QUEUED
        ).update(
            status=IntakeRun.STATUS_RUNNING, started_at=now, heartbeat_at=now,
            lease_token=secrets.token_hex(8), attempts=candidate.attempts + 1,
            confirmed_at=now, confirmed_by=candidate.created_by,
        )

        if claimed:
            return IntakeRun.objects.get(pk=candidate.pk)

    return None


def recover_stale_jobs(lease_seconds=LEASE_SECONDS, now=None):
    """Re-queue (or fail) running jobs whose worker stopped heartbeating."""
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=lease_seconds)
    recovered = []

    for run in IntakeRun.objects.filter(
        kind=IntakeRun.KIND_SCRAPER, status=IntakeRun.STATUS_RUNNING,
    ).filter(heartbeat_at__lt=cutoff):
        if run.attempts >= MAX_ATTEMPTS:
            updated = IntakeRun.objects.filter(
                pk=run.pk, status=IntakeRun.STATUS_RUNNING, heartbeat_at__lt=cutoff
            ).update(
                status=IntakeRun.STATUS_FAILED, finished_at=now,
                error_message="The run was interrupted too many times and was stopped.",
            )
        else:
            updated = IntakeRun.objects.filter(
                pk=run.pk, status=IntakeRun.STATUS_RUNNING, heartbeat_at__lt=cutoff
            ).update(status=IntakeRun.STATUS_QUEUED, lease_token="")

        if updated:
            recovered.append(run.pk)

    return recovered


# ------------------------------------------------------------------- job
def _record_to_submission(adapter, record, run):
    return Submission(
        org_type=adapter.org_type,
        name=record.get("name", ""),
        state=record.get("state", ""),
        suburb=record.get("suburb", ""),
        postcode=record.get("postcode", ""),
        email=record.get("email", ""),
        phone=record.get("phone", ""),
        website=record.get("website", ""),
        source_url=record.get("source_url", ""),
        club_type=record.get("club_type", ""),
        source_key=adapter.key,
        source_org_id=record.get("source_org_id", ""),
        origin="scraper",
        row_ref=record.get("source_url", ""),
        collected_fields=list(record.get("collected_fields", [])),
        extra={"source_label": adapter.label, "needs_verification": True},
    )


NO_ACCESS_CODES = ("blocked_host", "robots", "login_required", "forbidden", "bot_challenge")
RETRY_CODES = ("timeout", "unreachable", "http_error", "not_found", "too_large", "error")


def _page_action(code):
    if code in NO_ACCESS_CODES:
        return (
            "The source does not allow automated collection. This is not bypassed. "
            "A permitted source, or permission from the site owner, is needed before this page can be collected."
        )

    if code in RETRY_CODES:
        return "No data was collected from this page. It can be tried again on a later run."

    if code == "no_records":
        return (
            "The source was reachable but no organisations were found on the page. "
            "Check the page in a browser; if it does list organisations, ask the developer to review this source."
        )

    return (
        "The page loaded but no organisation could be recognised on it, so the source's layout may have changed. "
        "Ask the developer to review this source."
    )


def _page_problem(run, adapter, page, code, message):
    IntakeResult.objects.create(
        run=run, kind=IntakeResult.KIND_PAGE, outcome="failed",
        row_ref=page.url[:300], name="", org_type=adapter.org_type,
        field="source page",
        message=f"{adapter.label}: {message}",
        action_required=_page_action(code),
        detail={"code": code, "source_label": adapter.label},
    )


def fail_job(run, message="The run stopped because of a system error."):
    """Mark a running job failed (only if it is still running)."""
    return IntakeRun.objects.filter(pk=run.pk, status=IntakeRun.STATUS_RUNNING).update(
        status=IntakeRun.STATUS_FAILED, finished_at=timezone.now(), error_message=message
    )


def _lost_lease(run, token):
    """True when another worker has taken this job over (or it was stopped)."""
    if not token:
        return False

    current = IntakeRun.objects.filter(pk=run.pk).values("status", "lease_token").first()

    return current is None or current["status"] != IntakeRun.STATUS_RUNNING or current["lease_token"] != token


def run_job(run, fetcher=None, *, max_runtime=MAX_RUNTIME_SECONDS, now_func=timezone.now):
    """Run (or resume) a claimed scraper job to completion."""
    token = run.lease_token
    options = run.options
    adapters = [ADAPTERS[key] for key in options.get("adapters", []) if key in ADAPTERS]
    user = run.created_by
    started = now_func()
    suburbs = {norm_place(s) for s in options.get("suburbs", []) if s}
    states = options.get("states", [])
    notes = list(options.get("unsupported", []))

    plan = []

    for adapter in adapters:
        for page in adapter.pages(states, options.get("suburbs", [])):
            plan.append((adapter, page))

    plan = plan[:MAX_PAGES]
    run.progress_total = len(plan)
    run.save(update_fields=["progress_total"])

    if not plan:
        # Nothing could be visited, so the run cannot honestly be called successful.
        return finish_run(run, fatal="No pages to process: no approved source page matched this run.")

    done = set(options.get("done_pages", []))
    stopped_early = ""
    fetchers = {}

    for adapter, page in plan:
        if page.url in done:
            continue

        if (now_func() - started).total_seconds() > max_runtime:
            stopped_early = "The time limit was reached before every page was processed."
            break

        if _lost_lease(run, token):
            logger.warning("Scraper job %s was taken over by another worker; stopping.", run.pk)

            return IntakeRun.objects.get(pk=run.pk)

        IntakeRun.objects.filter(pk=run.pk).update(heartbeat_at=now_func())

        if adapter.key not in fetchers:
            fetchers[adapter.key] = fetcher or PublicFetcher(allowed_hosts=adapter.allowed_hosts)

        try:
            fetched = fetchers[adapter.key].get(page.url)

            if not fetched.ok:
                _page_problem(run, adapter, page, fetched.code, fetched.message)
                _mark_done(run, page.url)
                continue

            outcome = adapter.parse(page, fetched.text)

            if outcome.problem:
                _page_problem(run, adapter, page, outcome.code, outcome.problem)
                _mark_done(run, page.url)
                continue

            excluded = 0

            for record in outcome.records:
                # Only a source that declares suburbs can be filtered by suburb.
                if suburbs and adapter.suburbs and norm_place(record.get("suburb", "")) not in suburbs:
                    excluded += 1
                    continue

                process_submission(run, _record_to_submission(adapter, record, run), user)

            if excluded:
                notes.append(
                    f"{excluded} result(s) from {adapter.label} were outside the selected suburb filter and were not processed."
                )
        except Exception:
            logger.exception("Scraper page failed: %s", page.url)
            _page_problem(
                run, adapter, page, "error",
                "The page could not be processed because of a system error.",
            )

        _mark_done(run, page.url)

    run.refresh_from_db()
    run.options = {**run.options, "coverage_notes": notes}
    run.save(update_fields=["options"])

    return finish_run(run, fatal=stopped_early)


def _mark_done(run, url):
    run.refresh_from_db(fields=["options"])
    done = list(run.options.get("done_pages", []))

    if url not in done:
        done.append(url)

    run.options = {**run.options, "done_pages": done}
    run.progress_done = len(done)
    run.heartbeat_at = timezone.now()
    run.save(update_fields=["options", "progress_done", "heartbeat_at"])
