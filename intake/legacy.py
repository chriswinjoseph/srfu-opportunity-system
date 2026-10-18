"""
Shared behaviour for the older command-line import and scraper commands.

Those commands used to write organisations directly with their own,
weaker duplicate rules. They now go through the same pipeline as the Admin
pages (validation, duplicate detection, review, provenance) or refuse with
guidance. Nothing here writes an organisation, contact or status except
through ``intake.importer`` / ``intake.scraper``.
"""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

from .fetch import PublicFetcher
from .importer import ImportBusy, confirm_import, create_preview
from .scraper import ScrapeError, start_scrape
from .sources import ADAPTERS
from .workbook import parse_workbook

STATE_CODES = {
    "victoria": "VIC",
    "new south wales": "NSW",
    "queensland": "QLD",
    "south australia": "SA",
    "western australia": "WA",
    "tasmania": "TAS",
    "northern territory": "NT",
    "australian capital territory": "ACT",
}


def state_code(value):
    value = (value or "").strip()

    return STATE_CODES.get(value.lower(), value.upper())


def admin_from_email(email):
    """The active Admin the run is recorded against, or a clear error."""
    if not email:
        raise CommandError(
            "--admin-email is required so the run can be recorded against an Admin."
        )

    user = get_user_model().objects.filter(email__iexact=email.strip()).first()

    if user is None or not user.is_active or not user.has_perm("outreach.add_bank"):
        raise CommandError(
            "That email does not belong to an active Admin. Only an Admin can start an import or scraper run."
        )

    return user


def direct_write_disabled(command_name, replacement):
    return CommandError(
        f"'{command_name}' no longer writes organisations directly, because that skipped the shared "
        f"validation, duplicate and review rules. {replacement}"
    )


# ------------------------------------------------------------------ scrapers
def preview_source(command, adapter_key, *, states=(), limit=None, fetcher=None):
    """Fetch and parse approved pages and print them. Writes nothing."""
    adapter = ADAPTERS[adapter_key]
    pages = adapter.pages(list(states))

    if limit:
        pages = pages[:limit]

    fetcher = fetcher or PublicFetcher(allowed_hosts=adapter.allowed_hosts)
    shown = 0

    for page in pages:
        fetched = fetcher.get(page.url)

        if not fetched.ok:
            command.stdout.write(f"Not collected ({page.url}): {fetched.message}")
            continue

        outcome = adapter.parse(page, fetched.text)

        if outcome.problem:
            command.stdout.write(f"Not collected ({page.url}): {outcome.problem}")
            continue

        for record in outcome.records[: limit or None]:
            shown += 1
            command.stdout.write(
                "Would collect: "
                + " | ".join(
                    str(record.get(key, "")) for key in ("name", "state", "suburb", "phone", "email")
                )
            )

    command.stdout.write(f"{shown} record(s) previewed. Nothing was written to the database.")


def queue_source(command, org_type, *, admin_email, states=()):
    """Queue the same background job the Admin Scraper page queues."""
    user = admin_from_email(admin_email)

    try:
        run = start_scrape(user, [org_type], [s for s in states if s])
    except ScrapeError as error:
        raise CommandError(str(error)) from error

    command.stdout.write(
        f"Queued scraper run #{run.pk}. Start the background worker to process it: "
        "python manage.py run_intake_worker (see docs/Intake-Jobs.md)."
    )

    return run


# ------------------------------------------------------------------ imports
def run_workbook(command, path, *, admin_email, apply):
    """
    ``apply=False``: validate with the shared parser and report; nothing is
    saved. ``apply=True``: the same preview/confirm the Admin page performs.
    """
    file = Path(path)

    if not file.exists():
        raise CommandError(f"Workbook not found: {file}")

    if file.suffix.lower() != ".xlsx":
        raise CommandError("The import file must be an .xlsx workbook.")

    data = file.read_bytes()

    if not apply:
        parsed = parse_workbook(data, file.name)

        if not parsed.ok:
            raise CommandError("; ".join(parsed.structure_errors))

        statuses = {}

        for group in parsed.groups:
            statuses[group["evidence_status"]] = statuses.get(group["evidence_status"], 0) + 1

        command.stdout.write(
            f"Valid workbook: {len(parsed.groups)} organisation(s), "
            f"{sum(len(g['contacts']) for g in parsed.groups)} contact(s), "
            f"{len(parsed.row_errors)} row(s) that cannot be imported. "
            f"Evidence statuses: {statuses}. Nothing was written to the database."
        )

        return None

    user = admin_from_email(admin_email)
    run, _parsed = create_preview(user, data, file.name)

    if run.status != run.STATUS_PREVIEWED:
        raise CommandError(run.error_message or "The workbook could not be previewed.")

    try:
        finished = confirm_import(run.pk, user)
    except ImportBusy as error:
        raise CommandError(str(error)) from error

    command.stdout.write(
        f"Import run #{finished.pk}: {finished.get_status_display()}. "
        f"Totals: {finished.totals}. Review held records in the Admin Data pages."
    )

    return finished
