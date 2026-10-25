"""
The shared pipeline that turns one submitted organisation (from an Excel
import or a scraper) into a result: created, matched, held for review,
incomplete or failed.

Rules (see docs/Intake-BA-Interpretations.md):

* Every organisation group is processed in its own transaction, so a
  failure leaves no partial records and other groups continue.
* A populated field is never replaced with a blank value, and a populated
  field is never overwritten without Admin approval. Blank fields may be
  filled. Different values become ProposedChange rows.
* Archived organisations are matched but never changed or restored.
* contact_status only changes from an import's confirmed evidence
  (Not Yet Contacted -> Contacted); scrapers never change it, and nothing
  here touches responses, drafts or Do Not Contact.
"""

import logging

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from outreach.models import Contact, Opportunity

from .matching import (
    ORG_MODELS,
    Submission,
    find_matches,
    load_org,
    match_contact,
    org_name,
    org_type_of,
    resolve_parent_bank,
)
from .models import (
    ContactSource,
    DuplicateReview,
    FieldProvenance,
    IntakeLock,
    IntakeResult,
    IntakeRun,
    OrganisationSource,
    ProposedChange,
)
from .normalise import norm_email, norm_name, norm_phone, norm_postcode, norm_state, norm_url

logger = logging.getLogger("intake")

IMPORT_METHOD = "Imported SRFU contact history"

# submission attribute -> model field
FIELD_MAP = {
    "state": "state",
    "region": "region",
    "suburb": "suburb",
    "postcode": "postcode",
    "address": "address",
    "email": "public_email",
    "phone": "public_phone",
    "website": "website_url",
    "source_url": "source_url",
}

COMPARE = {
    "state": norm_state,
    "postcode": norm_postcode,
    "public_email": norm_email,
    "public_phone": norm_phone,
    "website_url": norm_url,
}

RECORD_SOURCE = {"import": "Client Import", "scraper": "Scraper"}
PREVIEW_KEYS = ("preview", "organisations", "organisation_rows", "contact_rows", "contacts")


def _same_value(model_field, old, new):
    func = COMPARE.get(model_field, norm_name)

    return func(old) == func(new)


def take_lock():
    IntakeLock.objects.get_or_create(key="intake")
    IntakeLock.objects.filter(key="intake").update(counter=F("counter") + 1)


def _result(run, outcome, sub, *, kind="organisation", message="", action="",
            field="", target=None, detail=None, row_ref=None):
    ct = ContentType.objects.get_for_model(type(target)) if target is not None else None

    return IntakeResult.objects.create(
        run=run,
        kind=kind,
        outcome=outcome,
        row_ref=row_ref if row_ref is not None else sub.row_ref,
        source_id=sub.source_org_id,
        org_type=sub.org_type,
        name=sub.name[:255],
        field=field,
        message=message,
        action_required=action,
        target_content_type=ct,
        target_id=target.pk if target is not None else None,
        detail=detail or {},
    )


# ------------------------------------------------------------ public entry
def process_submission(run, sub, user, *, forced_evidence=None, ignore_prior_rejection=False):
    """
    Process one submission and return its IntakeResult. Data problems are
    reported as results; only unexpected system errors become 'failed'.
    """
    try:
        with transaction.atomic():
            take_lock()

            return _process(run, sub, user, forced_evidence, ignore_prior_rejection)
    except Exception:
        logger.exception("Intake record failed: %s %s", sub.source_key, sub.source_org_id)

        return _result(
            run,
            "failed",
            sub,
            message="The record could not be processed because of a system error. Nothing was saved for it.",
            action="Try the import or scrape again. If it keeps failing, contact support.",
        )


def _process(run, sub, user, forced_evidence, ignore_prior_rejection):
    sub_state = norm_state(sub.state)

    missing = []

    if not norm_name(sub.name):
        missing.append("name")

    if sub.org_type not in ORG_MODELS:
        missing.append("type")

    if not sub_state:
        missing.append("state")

    if missing:
        return _result(
            run,
            "incomplete",
            sub,
            field=", ".join(missing),
            message="A reliable " + ", ".join(missing) + " is required before an organisation can be created.",
            action="Check the source and supply the missing value. No organisation was created.",
            detail={"missing": missing},
        )

    sub.state = sub_state

    if not ignore_prior_rejection:
        rejected = DuplicateReview.objects.filter(
            source_key=sub.source_key,
            source_id=sub.source_org_id,
            kind__in=(DuplicateReview.KIND_DUPLICATE, DuplicateReview.KIND_EVIDENCE),
            status=DuplicateReview.STATUS_DECIDED,
            decision="reject",
        ).exists() if sub.source_org_id else False

        if rejected:
            return _result(
                run, "rejected", sub,
                message="An Admin rejected this record earlier, so it was skipped.",
                detail={"remembered_decision": True},
            )

    evidence = forced_evidence or sub.evidence_status

    if evidence == "review":
        return _hold(
            run, sub, DuplicateReview.KIND_EVIDENCE,
            reasons=sub.extra.get("evidence_reasons") or ["The outreach evidence conflicts."],
            matches=[],
            message="The outreach evidence for this organisation conflicts, so it was held for review. No status was guessed.",
            action="An Admin must confirm whether it is Contacted or Not Yet Contacted, or reject it.",
        )

    match = find_matches(sub)

    if match.kind in ("conflict", "likely"):
        return _hold(
            run, sub, DuplicateReview.KIND_DUPLICATE,
            reasons=match.reasons,
            matches=match.candidates,
            message="This looks like an existing organisation, so it was held for review and not merged.",
            action="An Admin must use the existing organisation, create a separate one, or reject this record.",
        )

    if match.kind == "exact":
        org = load_org(*match.exact)

        return apply_existing(run, sub, org, user, evidence)

    return create_new(run, sub, user, evidence)


def _hold(run, sub, kind, *, reasons, matches, message, action):
    pending = DuplicateReview.objects.filter(
        source_key=sub.source_key,
        source_id=sub.source_org_id,
        kind=kind,
        status=DuplicateReview.STATUS_PENDING,
    ).first() if sub.source_org_id else None

    result = _result(
        run, "review", sub,
        message=message, action=action,
        detail={"reasons": reasons, "kind": kind, "already_pending": bool(pending)},
    )

    if pending is not None:
        # A repeat run must not queue the same record twice.
        pending.run = run
        pending.result = result
        pending.submission = sub.to_dict()
        pending.matches = matches
        pending.reason = "; ".join(reasons)
        pending.save()
    else:
        DuplicateReview.objects.create(
            run=run, result=result, kind=kind,
            source_key=sub.source_key, source_id=sub.source_org_id,
            reason="; ".join(reasons), submission=sub.to_dict(), matches=matches,
        )

    return result


# ------------------------------------------------------------ provenance
def _provenance(org, model_field, sub, run, now, user=None, origin=None, verified=False):
    ct = ContentType.objects.get_for_model(type(org))
    origin = origin or sub.origin

    obj, created = FieldProvenance.objects.get_or_create(
        content_type=ct, object_id=org.pk, field=model_field,
        defaults=dict(
            origin=origin, source_key=sub.source_key, source_url=sub.source_url[:500],
            collected_at=now, last_checked_at=now,
            verified=verified, verified_by=user if verified else None,
            verified_at=now if verified else None,
        ),
    )

    if not created:
        obj.origin = origin
        obj.source_key = sub.source_key
        obj.source_url = sub.source_url[:500]
        obj.last_checked_at = now
        obj.not_found_since = None

        if verified:
            obj.verified = True
            obj.verified_by = user
            obj.verified_at = now

        obj.save()


def _link_source(org, sub, run, now, requires_verification=None):
    ct = ContentType.objects.get_for_model(type(org))
    collected = sorted(set(sub.collected_fields))
    source, created = OrganisationSource.objects.get_or_create(
        content_type=ct, object_id=org.pk, source_key=sub.source_key,
        defaults=dict(
            source_org_id=sub.source_org_id, source_url=sub.source_url[:500],
            source_filename=sub.source_filename, first_collected_at=now,
            last_checked_at=now, last_run=run, collected_fields=collected,
            requires_verification=bool(requires_verification),
            extra=sub.extra.get("source_extra", {}),
        ),
    )

    if not created:
        if sub.source_org_id and not source.source_org_id:
            source.source_org_id = sub.source_org_id

        source.last_checked_at = now
        source.last_run = run
        source.source_url = sub.source_url[:500] or source.source_url
        source.source_filename = sub.source_filename or source.source_filename
        source.collected_fields = sorted(set(source.collected_fields) | set(collected))

        if sub.extra.get("source_extra"):
            source.extra = sub.extra["source_extra"]

        if requires_verification:
            source.requires_verification = True

        source.save()

    return source


def _valid_email(value):
    value = (value or "").strip()

    try:
        validate_email(value)

        return value
    except ValidationError:
        return ""


# ------------------------------------------------------------- create new
def create_new(run, sub, user, evidence):
    now = timezone.now()
    model = ORG_MODELS[sub.org_type]
    parent = resolve_parent_bank(sub) if sub.org_type in ("branch", "club") else None

    if sub.org_type == "branch" and parent is None:
        return _result(
            run, "incomplete", sub, field="parent bank",
            message="A branch needs a known parent bank before it can be created.",
            action="Import or create the parent bank first, then import the branch again.",
        )

    status = "contacted" if (sub.origin == "import" and evidence == "contacted") else "not_yet_contacted"
    email = _valid_email(sub.email)
    warnings = []

    if sub.email and not email:
        warnings.append("The email address was not valid and was left empty.")

    common = dict(
        state=sub.state, region=sub.region, suburb=sub.suburb, postcode=sub.postcode,
        address=sub.address, public_email=email, public_phone=sub.phone,
        website_url=sub.website, contact_status=status,
        record_source=RECORD_SOURCE.get(sub.origin, sub.origin)[:50],
        created_by=user,
    )

    if sub.org_type == "bank":
        org = model.objects.create(bank_name=sub.name, source_url=sub.source_url, **common)
    elif sub.org_type == "branch":
        org = model.objects.create(branch_name=sub.name, bank=parent, source_url=sub.source_url, **common)
    else:
        org = model.objects.create(
            club_name=sub.name, club_type=sub.club_type, supported_by_bank=parent,
            source_url=sub.source_url, **common,
        )

    requires_verification = sub.origin == "scraper" or bool(sub.extra.get("needs_verification"))
    _link_source(org, sub, run, now, requires_verification)

    for attr, model_field in FIELD_MAP.items():
        value = getattr(sub, attr)

        if value and getattr(org, model_field, ""):
            _provenance(org, model_field, sub, run, now)

    if status == "contacted":
        Opportunity.objects.create(
            content_type=ContentType.objects.get_for_model(type(org)),
            object_id=org.pk, status="contacted",
            outreach_method=IMPORT_METHOD, notes=sub.evidence_note,
        )

    counts = _ingest_contacts(run, sub, org, user, now)

    return _result(
        run, "created", sub, target=org,
        message="A new organisation was created"
        + (" and marked Contacted from the confirmed outreach evidence." if status == "contacted" else " as Not Yet Contacted."),
        detail={**counts, "contact_status": status, "warnings": warnings},
    )


# ------------------------------------------------------- existing record
def apply_existing(run, sub, org, user, evidence):
    now = timezone.now()
    ct = ContentType.objects.get_for_model(type(org))
    existing_source = OrganisationSource.objects.filter(
        content_type=ct, object_id=org.pk, source_key=sub.source_key
    ).first()

    if getattr(org, "is_archived", False):
        _link_source(org, sub, run, now)

        return _result(
            run, "exact", sub, target=org,
            message="This matches an archived organisation. It was not changed or restored.",
            detail={"matched_existing": True, "archived": True},
        )

    changed_fields = []
    proposed = 0
    not_found = []
    previously_collected = set(existing_source.collected_fields) if existing_source else set()

    for attr, model_field in FIELD_MAP.items():
        if not hasattr(org, model_field):
            continue

        new = (getattr(sub, attr) or "").strip()
        old = getattr(org, model_field) or ""

        if not new:
            if old and attr in previously_collected and attr not in sub.collected_fields:
                _mark_not_found(org, model_field, now, sub)
                not_found.append(model_field)

            continue

        if not old:
            setattr(org, model_field, new)
            changed_fields.append(model_field)
            _provenance(org, model_field, sub, run, now)
        elif _same_value(model_field, old, new):
            _provenance(org, model_field, sub, run, now)
        else:
            if _propose_change(run, org, ct, model_field, old, new, sub):
                proposed += 1

    if (
        sub.origin == "import"
        and evidence == "contacted"
        and org.contact_status != "contacted"
    ):
        org.contact_status = "contacted"
        changed_fields.append("contact_status")

        if not Opportunity.objects.filter(content_type=ct, object_id=org.pk).exists():
            Opportunity.objects.create(
                content_type=ct, object_id=org.pk, status="contacted",
                outreach_method=IMPORT_METHOD, notes=sub.evidence_note,
            )

    if changed_fields:
        org.save(update_fields=sorted(set(changed_fields)))

    requires_verification = bool(not_found) or bool(sub.extra.get("needs_verification"))
    _link_source(org, sub, run, now, requires_verification)

    counts = _ingest_contacts(run, sub, org, user, now)
    wrote = bool(
        changed_fields or proposed or not_found
        or counts["contacts_created"] or counts["contacts_updated"] or counts["contacts_held"]
    )

    return _result(
        run, "updated" if wrote else "unchanged", sub, target=org,
        message=(
            "The matching organisation was kept and only blank fields were filled; "
            "different values were proposed for review."
            if wrote else "The matching organisation already has this information."
        ),
        detail={
            **counts, "matched_existing": True, "fields_filled": changed_fields,
            "changes_proposed": proposed, "not_found": not_found,
        },
    )


def _mark_not_found(org, model_field, now, sub):
    ct = ContentType.objects.get_for_model(type(org))
    prov, _created = FieldProvenance.objects.get_or_create(
        content_type=ct, object_id=org.pk, field=model_field,
        defaults=dict(origin=sub.origin, source_key=sub.source_key,
                      source_url=sub.source_url[:500], collected_at=now, last_checked_at=now),
    )
    prov.last_checked_at = now

    if prov.not_found_since is None:
        prov.not_found_since = now

    prov.save()


def _propose_change(run, org, ct, model_field, old, new, sub):
    already = ProposedChange.objects.filter(
        content_type=ct, object_id=org.pk, field=model_field,
        new_value=str(new), status=ProposedChange.STATUS_PENDING,
    ).exists()

    if already:
        return False

    ProposedChange.objects.create(
        run=run, content_type=ct, object_id=org.pk, field=model_field,
        old_value=str(old), new_value=str(new),
        source_label=sub.extra.get("source_label", sub.source_key),
        source_url=sub.source_url[:500],
    )

    return True


# --------------------------------------------------------------- contacts
def _ingest_contacts(run, sub, org, user, now):
    counts = {"contacts_created": 0, "contacts_updated": 0, "contacts_held": 0, "contacts_unchanged": 0}

    if getattr(org, "is_archived", False):
        return counts

    ct = ContentType.objects.get_for_model(type(org))

    for c in sub.contacts:
        email = (c.get("email") or "").strip()

        if not email:
            continue

        c_id = c.get("source_contact_id", "")
        kind, found = match_contact(org, email, sub.source_key, c_id)

        if kind == "shared":
            if _hold_contact(run, sub, org, c, found):
                counts["contacts_held"] += 1

            continue

        contact_name = c.get("name", "")
        role = c.get("contact_type", "")

        if kind == "exact":
            changed = []

            if not found.contact_name and contact_name:
                found.contact_name = contact_name
                changed.append("contact_name")

            if not found.role and role:
                found.role = role
                changed.append("role")

            if changed:
                found.save(update_fields=changed)

            source_changed = _store_contact_source(found, sub, run, c)
            counts["contacts_updated" if (changed or source_changed) else "contacts_unchanged"] += 1
        else:
            contact = Contact.objects.create(
                content_type=ct, object_id=org.pk, contact_name=contact_name,
                role=role, email=email,
            )
            _store_contact_source(contact, sub, run, c)
            counts["contacts_created"] += 1

    return counts


def _parse_dt(value):
    from datetime import datetime

    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _store_contact_source(contact, sub, run, c):
    c_id = c.get("source_contact_id", "")

    if not c_id or not sub.source_key:
        return False

    values = dict(
        last_run=run,
        name_needs_verification=c.get("name_needs_verification"),
        affiliation_needs_verification=c.get("affiliation_needs_verification"),
        first_observed_at=_parse_dt(c.get("first_observed")),
        last_observed_at=_parse_dt(c.get("last_observed")),
        outreach_evidence=c.get("status", ""),
        sent_flag=c.get("sent_flag"),
        human_reply=c.get("human_reply"),
        contact_type=c.get("contact_type", ""),
    )
    obj = ContactSource.objects.filter(contact=contact).first()

    if obj is None:
        existing = ContactSource.objects.filter(
            source_key=sub.source_key, source_contact_id=c_id
        ).first()

        if existing is not None and existing.contact_id != contact.pk:
            return False

        ContactSource.objects.create(
            contact=contact, source_key=sub.source_key, source_contact_id=c_id, **values
        )

        return True

    changed = False

    for key, value in values.items():
        if key != "last_run" and getattr(obj, key) != value:
            setattr(obj, key, value)
            changed = True

    obj.last_run = run
    obj.save()

    return changed


def _hold_contact(run, sub, org, c, others):
    c_id = c.get("source_contact_id", "")
    key = f"{sub.source_org_id}:{c_id}" if c_id else ""

    if key and DuplicateReview.objects.filter(
        source_key=sub.source_key, source_id=key, kind=DuplicateReview.KIND_CONTACT,
    ).exclude(decision="").filter(decision="reject").exists():
        return False

    pending = DuplicateReview.objects.filter(
        source_key=sub.source_key, source_id=key, kind=DuplicateReview.KIND_CONTACT,
        status=DuplicateReview.STATUS_PENDING,
    ).first() if key else None

    result = _result(
        run, "review", sub, kind="contact", target=org,
        row_ref=c.get("row_ref", sub.row_ref), field="email",
        message="The same email address already belongs to a different organisation, so this contact was held for review.",
        action="An Admin must confirm whether this shared mailbox should also be added here.",
        detail={"contact_email_domain": (c.get("email") or "").split("@")[-1]},
    )

    matches = [
        {"type": org_type_of(o), "id": o.pk, "name": org_name(o), "state": getattr(o, "state", ""),
         "reasons": ["Same contact email address"], "archived": bool(getattr(o, "is_archived", False))}
        for o in others
    ]
    payload = {"organisation": {"type": org_type_of(org), "id": org.pk, "name": org_name(org)}, "contact": c,
               "source_key": sub.source_key, "source_org_id": sub.source_org_id}

    if pending is not None:
        pending.run, pending.result, pending.submission, pending.matches = run, result, payload, matches
        pending.save()
    else:
        DuplicateReview.objects.create(
            run=run, result=result, kind=DuplicateReview.KIND_CONTACT,
            source_key=sub.source_key, source_id=key,
            reason="Shared contact email across organisations",
            submission=payload, matches=matches,
        )

    return True


# ------------------------------------------------------------ run totals
def summarise_run(run):
    totals = {
        "processed": 0, "created": 0, "updated": 0, "exact_duplicates": 0,
        "unchanged": 0, "review": 0, "incomplete": 0, "failed": 0, "rejected": 0,
        "contacts_created": 0, "contacts_updated": 0, "changes_proposed": 0,
        # Scraper pages are counted separately from organisations ("processed",
        # "created" ... count organisations; "failed" counts pages and records).
        "pages_processed": run.progress_done if run.kind == IntakeRun.KIND_SCRAPER else 0,
        "pages_failed": 0, "records_failed": 0,
    }

    for result in run.results.all():
        detail = result.detail or {}

        if result.kind == IntakeResult.KIND_STRUCTURE:
            continue

        if result.kind == IntakeResult.KIND_PAGE and result.outcome == "failed":
            totals["pages_failed"] += 1
        elif result.outcome == "failed":
            totals["records_failed"] += 1

        if result.kind == IntakeResult.KIND_ORGANISATION or result.kind == IntakeResult.KIND_PAGE:
            if result.kind == IntakeResult.KIND_ORGANISATION:
                totals["processed"] += 1

            if result.outcome in totals:
                totals[result.outcome] += 1

            if detail.get("matched_existing"):
                totals["exact_duplicates"] += 1

            totals["contacts_created"] += detail.get("contacts_created", 0)
            totals["contacts_updated"] += detail.get("contacts_updated", 0)
            totals["changes_proposed"] += detail.get("changes_proposed", 0)
        elif result.outcome == "review":
            totals["review"] += 1
        elif result.outcome == "failed":
            totals["failed"] += 1

    return totals


def finish_run(run, *, fatal=""):
    """Compute totals and the BA final status (Successful / Partial / Failed)."""
    totals = summarise_run(run)
    # Keep the figures recorded when the import was previewed.
    kept = {
        key: value for key, value in (run.totals or {}).items()
        if key in PREVIEW_KEYS or key.startswith("evidence_")
    }
    run.totals = {**kept, **totals}
    run.finished_at = timezone.now()
    run.error_message = fatal

    good = totals["created"] + totals["updated"] + totals["unchanged"] + totals["exact_duplicates"]
    trouble = totals["review"] + totals["incomplete"] + totals["failed"] + totals["rejected"]

    # Failed: nothing was processed. Records held for review or reported as
    # incomplete still count as processed, so a run that only holds them is
    # Partially Successful (see docs/Scraper-BA-Clarifications.md, item 2).
    only_failures = totals["failed"] and not (totals["review"] + totals["incomplete"] + totals["rejected"])

    if fatal and not good:
        run.status = IntakeRun.STATUS_FAILED
    elif totals["processed"] == 0 and totals["failed"]:
        run.status = IntakeRun.STATUS_FAILED
    elif not good and only_failures:
        run.status = IntakeRun.STATUS_FAILED
    elif trouble or fatal:
        run.status = IntakeRun.STATUS_PARTIAL
    else:
        run.status = IntakeRun.STATUS_SUCCESSFUL

    run.save()

    return run
