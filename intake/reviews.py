"""
Admin decisions on held records and proposed changes.

Every decision re-checks the current data and the Admin's permission when it
is saved. Archived organisations are never restored, and nothing here
touches Do Not Contact responses, drafts or email approval.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from outreach.models import Contact

from .ingest import (
    _ingest_contacts,
    _process,
    _provenance,
    apply_existing,
    create_new,
    summarise_run,
    take_lock,
)
from .matching import Submission, find_matches, load_org, org_name, org_type_of
from .models import (
    ContactSource,
    DuplicateReview,
    IntakeResult,
    OrganisationSource,
    ProposedChange,
)
from .normalise import norm_state


class ReviewError(Exception):
    """A decision could not be saved; the message is safe to show."""


def require_admin(user):
    if (
        not getattr(user, "is_authenticated", False)
        or not user.is_active
        or not user.has_perm("outreach.add_bank")
    ):
        raise PermissionDenied


def _merge_result(old, new):
    """Fold the outcome of a decision into the record that was on hold."""
    if old is None or new is None or old.pk == new.pk:
        return

    for name in ("kind", "outcome", "message", "action_required", "field",
                 "target_content_type", "target_id", "detail"):
        setattr(old, name, getattr(new, name))

    old.save()
    new.delete()


def _refresh_totals(run):
    run.totals = summarise_run(run)
    run.save(update_fields=["totals"])


DUPLICATE_DECISIONS = ("use_existing", "create_separate", "reject")
EVIDENCE_DECISIONS = ("accept_contacted", "accept_not_yet_contacted", "reject")
CONTACT_DECISIONS = ("create_separate", "reject")


def decide_review(review_id, user, decision, *, target=None, note=""):
    """
    Save an Admin decision. ``target`` is ``(org_type, id)`` for
    ``use_existing``. Returns the review.
    """
    require_admin(user)
    now = timezone.now()

    with transaction.atomic():
        take_lock()
        review = DuplicateReview.objects.select_related("run", "result").get(pk=review_id)

        allowed = {
            DuplicateReview.KIND_DUPLICATE: DUPLICATE_DECISIONS,
            DuplicateReview.KIND_EVIDENCE: EVIDENCE_DECISIONS,
            DuplicateReview.KIND_CONTACT: CONTACT_DECISIONS,
        }[review.kind]

        if decision not in allowed:
            raise ReviewError("That decision is not available for this item.")

        # Claim the review once. A repeated or concurrent submission finds
        # it already decided and changes nothing.
        claimed = DuplicateReview.objects.filter(
            pk=review.pk, status=DuplicateReview.STATUS_PENDING
        ).update(
            status=DuplicateReview.STATUS_DECIDED, decision=decision,
            decided_by=user, decided_at=now, note=note[:1000],
        )

        if not claimed:
            raise ReviewError("This item has already been decided.")

        old_result = review.result

        if decision == "reject":
            if old_result is not None:
                old_result.outcome = "rejected"
                old_result.message = "An Admin rejected this record. Nothing was created or changed."
                old_result.action_required = ""
                old_result.save()

            _refresh_totals(review.run)

            return review

        if review.kind == DuplicateReview.KIND_CONTACT:
            _decide_contact(review, user, now)
            _refresh_totals(review.run)

            return review

        sub = Submission.from_dict(review.submission)

        if review.kind == DuplicateReview.KIND_EVIDENCE:
            forced = "contacted" if decision == "accept_contacted" else "not_yet_contacted"
            new_result = _process(review.run, sub, user, forced, True)

            if new_result.outcome == "review":
                # It now needs a duplicate decision; that item replaces this one.
                if old_result is not None:
                    old_result.delete()
            else:
                _merge_result(old_result, new_result)

            _refresh_totals(review.run)

            return review

        # --- possible duplicate organisation
        evidence = sub.evidence_status if sub.evidence_status in ("contacted", "not_yet_contacted") else None

        if decision == "use_existing":
            org = _chosen_org(review, target)
            ct = ContentType.objects.get_for_model(type(org))
            review.target_content_type, review.target_id = ct, org.pk
            review.save(update_fields=["target_content_type", "target_id"])
            new_result = apply_existing(review.run, sub, org, user, evidence)
        else:
            _check_can_create_separately(sub)
            new_result = create_new(review.run, sub, user, evidence)

            if new_result.target_content_type_id:
                review.target_content_type_id = new_result.target_content_type_id
                review.target_id = new_result.target_id
                review.save(update_fields=["target_content_type", "target_id"])

        _merge_result(old_result, new_result)
        _refresh_totals(review.run)

        return review


def _chosen_org(review, target):
    if not target:
        raise ReviewError("Choose which existing organisation to use.")

    wanted = (target[0], int(target[1]))
    listed = {(m["type"], int(m["id"])) for m in review.matches}

    if wanted not in listed:
        raise ReviewError("That organisation is not one of the possible matches.")

    org = load_org(*wanted)

    if org is None:
        raise ReviewError("That organisation no longer exists. Reload the page.")

    return org


def _check_can_create_separately(sub):
    if sub.source_key and sub.source_org_id:
        linked = OrganisationSource.objects.filter(
            source_key=sub.source_key, source_org_id=sub.source_org_id
        ).first()

        if linked is not None:
            raise ReviewError(
                "This source ID is already linked to another organisation. "
                "Use the existing organisation or reject the record."
            )

    if find_matches(sub).kind == "exact":
        raise ReviewError(
            "An exact duplicate now exists, so a separate organisation cannot "
            "be created. Use the existing organisation instead."
        )


def _decide_contact(review, user, now):
    payload = review.submission
    org_info = payload["organisation"]
    org = load_org(org_info["type"], org_info["id"])

    if org is None or getattr(org, "is_archived", False):
        raise ReviewError("The organisation is archived or no longer exists, so no contact was added.")

    c = payload["contact"]
    ct = ContentType.objects.get_for_model(type(org))
    contact = Contact.objects.create(
        content_type=ct, object_id=org.pk, contact_name=c.get("name", ""),
        role=c.get("contact_type", ""), email=c["email"],
    )
    sub = Submission(
        org_type=org_info["type"], name=org_name(org),
        source_key=payload.get("source_key", ""), source_org_id=payload.get("source_org_id", ""),
    )

    from .ingest import _store_contact_source

    _store_contact_source(contact, sub, review.run, c)

    if review.result is not None:
        review.result.outcome = "created"
        review.result.message = "An Admin confirmed this contact. It was added as a separate contact."
        review.result.save()


# ----------------------------------------------------------------- changes
def decide_change(change_id, user, decision, *, note=""):
    require_admin(user)
    now = timezone.now()

    if decision not in ("approve", "reject"):
        raise ReviewError("That decision is not available.")

    with transaction.atomic():
        take_lock()
        change = ProposedChange.objects.get(pk=change_id)

        claimed = ProposedChange.objects.filter(
            pk=change.pk, status=ProposedChange.STATUS_PENDING
        ).update(decided_by=user, decided_at=now, note=note[:1000],
                 status=ProposedChange.STATUS_APPROVED if decision == "approve" else ProposedChange.STATUS_REJECTED)

        if not claimed:
            raise ReviewError("This change has already been decided.")

        if decision == "reject":
            return change

        org = change.content_type.model_class().objects.filter(pk=change.object_id).first()

        if org is None or getattr(org, "is_archived", False):
            raise ReviewError("The organisation is archived or no longer exists, so the change was not applied.")

        current = getattr(org, change.field, "") or ""

        if str(current) != change.old_value:
            ProposedChange.objects.filter(pk=change.pk).update(status=ProposedChange.STATUS_STALE)

            return ProposedChange.objects.get(pk=change.pk)

        value = change.new_value

        if change.field == "public_email":
            try:
                validate_email(value)
            except ValidationError:
                raise ReviewError("The proposed email address is not valid.")

        if change.field == "state":
            value = norm_state(value)

            if not value:
                raise ReviewError("The proposed state is not valid.")

        setattr(org, change.field, value)
        org.save(update_fields=[change.field])

        sub = Submission(
            org_type=org_type_of(org), name=org_name(org), source_key=change.source_label,
            source_url=change.source_url, origin="admin_review",
        )
        _provenance(org, change.field, sub, change.run, now, user=user, origin="admin_review", verified=True)

        ProposedChange.objects.filter(
            content_type=change.content_type, object_id=change.object_id,
            field=change.field, status=ProposedChange.STATUS_PENDING,
        ).update(status=ProposedChange.STATUS_STALE)

        return change
