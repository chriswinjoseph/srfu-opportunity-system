"""
Admin Excel import: validate -> preview -> confirm -> results.

The preview writes no organisations. Confirming re-checks matching against
the current data, processes each organisation group in its own transaction
and can be confirmed only once.
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db.models import Exists, Q
from django.utils import timezone

from .evidence import SUCCESSFUL
from .ingest import finish_run, process_submission
from .matching import Submission, find_matches
from .models import IntakeResult, IntakeRun
from .reviews import require_admin
from .workbook import FORMAT_LABELS, FORMAT_SIMPLE, SOURCE_KEY, SOURCE_LABEL, parse_workbook


STALE_IMPORT_SECONDS = 15 * 60


class ImportBusy(Exception):
    """Another import is already running, or this one was already started."""


def _evidence_note(group):
    if group.get("format") == FORMAT_SIMPLE:
        return "\n".join(
            [
                "Imported from a single-sheet workbook.",
                f"Source organisation ID: {group['source_org_id']}",
                f"overall_status in the file: {group['overall_status_raw'] or '(blank)'}",
                "The file carries no outreach evidence, so it was not used to set Contacted. "
                "Contacted here is an Admin's decision on the held record.",
            ]
        )

    contacts = group["contacts"]
    sent = sum(1 for c in contacts if c["status"] in SUCCESSFUL)
    replies = sum(1 for c in contacts if c.get("human_reply"))

    return "\n".join(
        [
            "Imported from the client workbook.",
            f"Source organisation ID: {group['source_org_id']}",
            f"Contacts with a confirmed successful outgoing email: {sent} of {len(contacts)}",
            f"Human replies recorded: {replies}",
            "Replies are kept as evidence only. No Interested, Not Interested or Do Not Contact outcome was inferred.",
        ]
    )


def submission_from_group(group, filename):
    contacts = [dict(c) for c in group["contacts"]]
    first_email = next((c["email"] for c in contacts if c["email"]), "")
    optional = dict(group.get("optional") or {})
    organisation_email = optional.pop("email", "") or first_email
    comparable = ("region", "suburb", "postcode", "address", "website", "phone")
    collected = ["state"] + [k for k in comparable if k in optional] + (["email"] if organisation_email else [])

    return Submission(
        org_type=group["org_type"],
        name=group["name"],
        state=group["state"],
        email=organisation_email,
        **optional,
        source_key=SOURCE_KEY,
        source_org_id=group["source_org_id"],
        source_filename=filename,
        origin="import",
        row_ref=group["row_ref"],
        collected_fields=collected,
        evidence_status=group["evidence_status"],
        evidence_note=_evidence_note(group),
        extra={
            "evidence_reasons": group["evidence_reasons"],
            "needs_verification": bool(group.get("needs_verification")),
            "source_label": SOURCE_LABEL,
            "source_extra": {
                "overall_status_in_file": group["overall_status_raw"],
                "needs_verification_flag": group.get("needs_verification"),
                "any_human_reply": group.get("any_human_reply"),
                "all_contacts_replied": group.get("all_contacts_replied"),
                "first_observed": group.get("first_observed"),
                "last_observed": group.get("last_observed"),
                "import_format": group.get("format", ""),
                "contact_names_in_file": group.get("contact_names_in_file", ""),
                "emails_in_file": group.get("emails_in_file", ""),
            },
        },
        contacts=contacts,
    )


def create_preview(user, file_bytes, filename):
    """Validate the workbook and store a preview. Writes no organisations."""
    require_admin(user)
    parsed = parse_workbook(file_bytes, filename)

    run = IntakeRun.objects.create(
        kind=IntakeRun.KIND_IMPORT,
        source_key=SOURCE_KEY,
        source_label=SOURCE_LABEL,
        filename=filename[:255],
        file_sha256=parsed.sha256,
        created_by=user,
    )

    if not parsed.ok:
        run.status = IntakeRun.STATUS_FAILED
        run.error_message = " ".join(parsed.structure_errors)
        run.finished_at = timezone.now()
        run.save()

        return run, parsed

    preview = {"create": 0, "match": 0, "review": 0, "incomplete": 0, "contact_review": 0, "contact_problems": 0}

    for group in parsed.groups:
        sub = submission_from_group(group, filename)

        if group["evidence_status"] == "review":
            preview["review"] += 1
            continue

        match = find_matches(sub)

        if match.kind == "exact":
            preview["match"] += 1
        elif match.kind in ("likely", "conflict"):
            preview["review"] += 1
        else:
            preview["create"] += 1

    preview["incomplete"] = len(parsed.row_errors)
    problems = [p for g in parsed.groups for p in g["contact_problems"]]
    preview["contact_review"] = sum(1 for p in problems if p.get("outcome") == "review")
    preview["contact_problems"] = len(problems) - preview["contact_review"]

    run.payload = {
        "groups": parsed.groups,
        "row_errors": parsed.row_errors,
        "type_note": parsed.type_note,
        "format": parsed.format,
        "format_label": FORMAT_LABELS[parsed.format],
        "columns": parsed.columns,
    }
    run.totals = {
        "preview": preview,
        "organisations": len(parsed.groups),
        "organisation_rows": parsed.counts["organisation_rows"],
        "contact_rows": parsed.counts["contact_rows"],
        "contacts": sum(len(g["contacts"]) for g in parsed.groups),
        "evidence_contacted": sum(1 for g in parsed.groups if g["evidence_status"] == "contacted"),
        "evidence_not_yet": sum(1 for g in parsed.groups if g["evidence_status"] == "not_yet_contacted"),
        "evidence_review": sum(1 for g in parsed.groups if g["evidence_status"] == "review"),
    }
    run.save()

    return run, parsed


def previously_imported(run):
    return (
        IntakeRun.objects.filter(
            kind=IntakeRun.KIND_IMPORT, file_sha256=run.file_sha256,
            status__in=(IntakeRun.STATUS_SUCCESSFUL, IntakeRun.STATUS_PARTIAL),
        )
        .exclude(pk=run.pk)
        .order_by("-finished_at")
        .first()
    )


def confirm_import(run_id, user):
    """
    Confirm a preview and process it. Only the first confirmation proceeds;
    a repeated submission, or a second import started while one is running,
    changes nothing.
    """
    require_admin(user)
    now = timezone.now()

    # An import whose process died stops blocking others after a while. Re-importing
    # is safe: processed groups are matched, not duplicated.
    IntakeRun.objects.filter(
        kind=IntakeRun.KIND_IMPORT, status=IntakeRun.STATUS_RUNNING,
        heartbeat_at__lt=now - timedelta(seconds=STALE_IMPORT_SECONDS),
    ).update(
        status=IntakeRun.STATUS_FAILED, finished_at=now,
        error_message="This import was interrupted. Import the file again; records already saved will be matched, not duplicated.",
    )

    # One statement claims the run only if it is still awaiting confirmation
    # and no other import is running, so simultaneous confirmations (of the
    # same run or of two runs) cannot both proceed.
    claimed = (
        IntakeRun.objects.filter(
            pk=run_id, kind=IntakeRun.KIND_IMPORT, status=IntakeRun.STATUS_PREVIEWED
        )
        .exclude(
            Exists(
                IntakeRun.objects.filter(
                    kind=IntakeRun.KIND_IMPORT, status=IntakeRun.STATUS_RUNNING
                )
            )
        )
        .update(
            status=IntakeRun.STATUS_RUNNING, confirmed_by=user, confirmed_at=now,
            started_at=now, heartbeat_at=now, attempts=1,
        )
    )

    if not claimed:
        if IntakeRun.objects.filter(pk=run_id, status=IntakeRun.STATUS_PREVIEWED).exists():
            raise ImportBusy("Another import is running. Wait for it to finish.")

        raise ImportBusy("This import was already confirmed.")

    run = IntakeRun.objects.get(pk=run_id)
    payload = run.payload or {}
    groups = payload.get("groups", [])
    run.progress_total = len(groups) + len(payload.get("row_errors", []))
    run.save(update_fields=["progress_total"])

    try:
        for error in payload.get("row_errors", []):
            IntakeResult.objects.create(
                run=run, kind=IntakeResult.KIND_ORGANISATION, outcome=error.get("outcome", "failed"),
                row_ref=error["row_ref"], source_id=error.get("source_id", ""),
                name=error.get("name", "")[:255], field=error.get("field", ""),
                message=error["message"], action_required=error.get("action", ""),
            )
            _tick(run)

        for group in groups:
            sub = submission_from_group(group, run.filename)
            process_submission(run, sub, user)

            for problem in group.get("contact_problems", []):
                IntakeResult.objects.create(
                    run=run, kind=IntakeResult.KIND_CONTACT, outcome=problem.get("outcome", "failed"),
                    row_ref=problem["row_ref"], source_id=group["source_org_id"],
                    name=group["name"][:255], field=problem["field"],
                    message=problem["message"],
                    action_required=problem.get("action", "Correct the contact row and import again."),
                )

            _tick(run)

        finish_run(run)
    except Exception as exc:  # pragma: no cover - defensive
        finish_run(run, fatal="The import stopped because of a system error.")
        raise

    return run


def _tick(run):
    run.progress_done += 1
    run.heartbeat_at = timezone.now()
    run.save(update_fields=["progress_done", "heartbeat_at"])
