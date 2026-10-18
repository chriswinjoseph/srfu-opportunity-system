"""
Preview (and, on disposable databases only, apply) corrections to data that
was imported before the import rules were fixed.

* ``build_plan`` is read-only. It matches database records to the workbook by
  source evidence (never by database ID alone, and never by a similar name).
* ``apply_plan`` rechecks every item against the current data first, writes
  a rollback record, and is refused by the management command on the
  project's real database.
* ``revert_plan`` restores the recorded old values.

Rules: legitimately Contacted records are never reset; missing historical
dates and the acting Admin are never inferred.
"""

import json
import re
from collections import defaultdict
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from outreach.models import Bank, Contact, EmailDraft, Opportunity

from .evidence import map_organisation_status
from .ingest import IMPORT_METHOD
from .models import ContactSource, FieldProvenance, OrganisationSource
from .normalise import norm_email, norm_name, norm_state
from .workbook import SOURCE_KEY, parse_workbook

NOTE_PATTERN = re.compile(r"Source organisation ID:\s*(\S+)")
UNSPECIFIED = "(unspecified)"
LATER_OUTREACH_METHODS = ("phone", "manual_email", "email")

# Every kind of correction a plan can contain. Approval is always per kind.
ALL_KINDS = (
    "state_in_region",
    "region_duplicate_of_state",
    "unspecified_name",
    "source_provenance",
    "contact_provenance",
    "contact_status",
)

# A bank is "unedited since import" when its last-updated time is within this
# window of the time it was created (the importer saves a record more than once).
UNEDITED_TOLERANCE = timedelta(seconds=5)


def _unedited_since_import(bank):
    return bool(
        bank.date_added and bank.last_updated
        and bank.last_updated - bank.date_added <= UNEDITED_TOLERANCE
    )


class Plan:
    def __init__(self):
        self.fixes = []
        self.exclusions = []
        self.matched = {}
        self.summary = defaultdict(int)

    def fix(self, kind, **data):
        self.fixes.append({"kind": kind, **data})
        self.summary[kind] += 1

    def exclude(self, kind, reason, **data):
        self.exclusions.append({"kind": kind, "reason": reason, **data})
        self.summary["excluded_" + kind] += 1

    def to_dict(self):
        return {
            "summary": dict(self.summary),
            "matched_organisations": len(self.matched),
            "fixes": self.fixes,
            "exclusions": self.exclusions,
        }

    def to_text(self):
        lines = ["DATA CORRECTION PREVIEW (read-only; nothing was changed)", ""]
        lines.append(f"Workbook organisations matched by source evidence: {len(self.matched)}")

        for key in sorted(self.summary):
            lines.append(f"  {key}: {self.summary[key]}")

        lines.append("")
        lines.append("PROPOSED CHANGES")

        for item in self.fixes:
            if item["kind"] in ("source_provenance", "contact_provenance"):
                continue

            lines.append(
                f"- {item['kind']}: {item.get('organisation', '')} (workbook {item.get('workbook_id', '')}) "
                f"{item.get('field', '')}: {item.get('old')!r} -> {item.get('new')!r}"
            )

        lines.append("")
        lines.append("EXCLUSIONS")

        for item in self.exclusions:
            lines.append(f"- {item['kind']}: {item['reason']} ({item.get('organisation', item.get('workbook_id', ''))})")

        return "\n".join(lines)


# ----------------------------------------------------------------- matching
def _locate(parsed_groups, plan):
    """Match workbook organisations to banks by source evidence."""
    bank_ct = ContentType.objects.get_for_model(Bank)
    by_source = {
        s.source_org_id: s.object_id
        for s in OrganisationSource.objects.filter(source_key=SOURCE_KEY, content_type=bank_ct)
        if s.source_org_id
    }
    note_ids = defaultdict(set)

    for opp in Opportunity.objects.filter(content_type=bank_ct, outreach_method=IMPORT_METHOD):
        match = NOTE_PATTERN.search(opp.notes or "")

        if match:
            note_ids[match.group(1)].add(opp.object_id)

    banks = {b.pk: b for b in Bank.objects.all()}
    contacts_by_bank = defaultdict(list)

    for contact in Contact.objects.filter(content_type=bank_ct):
        contacts_by_bank[contact.object_id].append(contact)

    located = {}

    for group in parsed_groups:
        sid = group["source_org_id"]
        candidates = []

        if sid in by_source:
            candidates.append((by_source[sid], "source record"))
        elif sid in note_ids:
            for bank_id in note_ids[sid]:
                candidates.append((bank_id, "import note"))

        if len(candidates) > 1:
            plan.exclude("match", "The source ID points at more than one bank.", workbook_id=sid)
            continue

        if candidates:
            bank_id, basis = candidates[0]
            bank = banks.get(bank_id)

            # The source ID must also agree with the name; an ID alone is not enough.
            if bank is None or norm_name(bank.bank_name) != norm_name(group["name"]):
                plan.exclude("match", "The source ID matches a bank whose name differs from the workbook.", workbook_id=sid)
                continue

            located[sid] = (bank, basis)
            continue

        # No stored source evidence: only an exact name AND shared contact
        # emails (never a similar name) can recover the link.
        wanted = {norm_email(c["email"]) for c in group["contacts"]}
        same_name = [
            b for b in banks.values()
            if norm_name(b.bank_name) == norm_name(group["name"]) and norm_state(b.state or b.region) == group["state"]
        ]
        hits = [
            b for b in same_name
            if wanted and wanted <= {norm_email(c.email) for c in contacts_by_bank[b.pk]}
        ]

        if len(hits) == 1:
            located[sid] = (hits[0], "exact name, state and all contact emails")
        else:
            plan.exclude("match", "No source evidence links this workbook organisation to a bank.", workbook_id=sid)

    return located, contacts_by_bank


def _later_activity(bank):
    """Reasons a Contacted bank must NOT be reset (later outreach or responses)."""
    ct = ContentType.objects.get_for_model(Bank)
    reasons = []
    opps = list(Opportunity.objects.filter(content_type=ct, object_id=bank.pk))
    drafts = EmailDraft.objects.filter(opportunity__in=opps)

    if drafts.filter(workflow_status__in=("sent", "sending", "send_failed")).exists():
        reasons.append("an email was sent or is being sent")

    if drafts.exists():
        reasons.append("it has email drafts")

    for opp in opps:
        if opp.outreach_method != IMPORT_METHOD:
            reasons.append("later outreach was recorded")
            break

    if any(opp.status != "contacted" for opp in opps):
        reasons.append("a response status was recorded")

    if any(opp.contact_recorded_at or opp.date_contacted for opp in opps):
        reasons.append("a contact date was recorded")

    if len(opps) != 1:
        reasons.append("it does not have exactly one imported record")

    if bank.is_archived:
        reasons.append("the organisation is archived")

    return reasons, opps


def build_plan(workbook_bytes, filename="workbook.xlsx"):
    plan = Plan()
    parsed = parse_workbook(workbook_bytes, filename)

    if not parsed.ok:
        raise ValueError("; ".join(parsed.structure_errors))

    located, contacts_by_bank = _locate(parsed.groups, plan)
    plan.matched = {sid: bank.pk for sid, (bank, _basis) in located.items()}
    groups = {g["source_org_id"]: g for g in parsed.groups}
    bank_ct = ContentType.objects.get_for_model(Bank)

    for sid, (bank, basis) in located.items():
        group = groups[sid]
        status, _reasons = map_organisation_status(group["contacts"])
        label = bank.bank_name

        # 1. Delivery-failure-only banks imported as Contacted.
        if status == "not_yet_contacted" and bank.contact_status == "contacted":
            reasons, opps = _later_activity(bank)

            if reasons:
                plan.exclude(
                    "contact_status", "Not reset because " + "; ".join(sorted(set(reasons))) + ".",
                    organisation=label, workbook_id=sid,
                )
            else:
                opp = opps[0]
                plan.fix(
                    "contact_status", organisation=label, workbook_id=sid, bank_id=bank.pk,
                    field="contact_status", old="contacted", new="not_yet_contacted",
                    opportunity_id=opp.pk, opportunity_old=opp.status, opportunity_new="not_yet_contacted",
                    evidence=[c["status"] for c in group["contacts"]], basis=basis,
                )

        # Archived organisations are never changed by any other kind of correction.
        if bank.is_archived:
            plan.exclude("archived", "The organisation is archived, so nothing is changed.",
                         organisation=label, workbook_id=sid)
            continue

        # 2. State code stored in Region.
        region = (bank.region or "").strip()

        if not bank.state and region and region.upper() == group["state"] and norm_state(region) == group["state"]:
            plan.fix(
                "state_in_region", organisation=label, workbook_id=sid, bank_id=bank.pk,
                field="state", old="", new=group["state"], region_old=region, region_new="", basis=basis,
            )
        elif not bank.state and region and norm_state(region) != group["state"]:
            plan.exclude("state_in_region", "Region was edited and no longer holds the state code.",
                         organisation=label, workbook_id=sid)

        # 2b. State already set, Region still holding the same state code. The code is a
        # leftover of the earlier importer (not a deliberately entered region) only when
        # the workbook agrees, the bank was never edited, and no source supplied a Region.
        region_code = norm_state(region)

        if bank.state and region and region_code and region.upper() == region_code:
            if norm_state(bank.state) != group["state"] or region_code != group["state"]:
                plan.exclude("region_duplicate_of_state",
                             "The state code differs from the workbook, so it is uncertain.",
                             organisation=label, workbook_id=sid)
            elif not _unedited_since_import(bank):
                plan.exclude("region_duplicate_of_state",
                             "The bank was edited after import, so the Region may have been entered deliberately.",
                             organisation=label, workbook_id=sid)
            elif FieldProvenance.objects.filter(content_type=bank_ct, object_id=bank.pk, field="region").exists():
                plan.exclude("region_duplicate_of_state",
                             "A source supplied the Region, so it is not a leftover.",
                             organisation=label, workbook_id=sid)
            else:
                plan.fix(
                    "region_duplicate_of_state", organisation=label, workbook_id=sid, bank_id=bank.pk,
                    field="region", old=region, new="", state=bank.state, basis=basis,
                    evidence="Region equals the workbook state code, State is set, the bank was never edited, "
                             "and no source supplied a Region.",
                )

        # 3. "(unspecified)" contact names.
        wb_by_email = {norm_email(c["email"]): c for c in group["contacts"]}

        for contact in contacts_by_bank[bank.pk]:
            source_contact = wb_by_email.get(norm_email(contact.email))

            if source_contact is None:
                continue

            if (contact.contact_name or "").strip().lower() == UNSPECIFIED:
                if source_contact["name"] == "":
                    plan.fix(
                        "unspecified_name", organisation=label, workbook_id=sid, contact_id=contact.pk,
                        field="contact_name", old=contact.contact_name, new="",
                        source_contact_id=source_contact["source_contact_id"],
                    )
                else:
                    plan.exclude("unspecified_name", "The workbook has a real name for this contact.",
                                 organisation=label, workbook_id=sid)

        # 4. Source provenance that can be recovered from evidence.
        has_source = OrganisationSource.objects.filter(
            content_type=bank_ct, object_id=bank.pk, source_key=SOURCE_KEY
        ).exists()
        opp = Opportunity.objects.filter(
            content_type=bank_ct, object_id=bank.pk, outreach_method=IMPORT_METHOD
        ).order_by("date_created").first()

        if not has_source:
            if opp is None:
                plan.exclude("source_provenance", "No recorded import time exists, so none is inferred.",
                             organisation=label, workbook_id=sid)
            else:
                plan.fix(
                    "source_provenance", organisation=label, workbook_id=sid, bank_id=bank.pk,
                    source_org_id=sid, recorded_at=opp.date_created.isoformat(), basis=basis,
                    needs_verification=bool(group.get("needs_verification")),
                    extra={
                        "overall_status_in_file": group["overall_status_raw"],
                        "first_observed": group.get("first_observed"),
                        "last_observed": group.get("last_observed"),
                    },
                )

        for contact in contacts_by_bank[bank.pk]:
            source_contact = wb_by_email.get(norm_email(contact.email))

            if source_contact and not ContactSource.objects.filter(contact=contact).exists():
                plan.fix(
                    "contact_provenance", organisation=label, workbook_id=sid, contact_id=contact.pk,
                    source_contact=source_contact,
                )

    return plan


# ------------------------------------------------------------------- apply
def apply_plan(plan_dict, rollback_path=None):
    """
    Apply a plan produced by ``build_plan(...).to_dict()``. Every item is
    rechecked against the current data first; items that no longer match are
    skipped and reported. Returns ``(applied, skipped, rollback)``.
    """
    applied, skipped, rollback = [], [], []
    now = timezone.now()
    bank_ct = ContentType.objects.get_for_model(Bank)

    for fix in plan_dict["fixes"]:
        kind = fix["kind"]

        try:
            with transaction.atomic():
                if kind in ("contact_status", "state_in_region", "region_duplicate_of_state", "source_provenance") \
                        and Bank.objects.filter(pk=fix["bank_id"], is_archived=True).exists():
                    raise _Skip("the organisation is archived")

                if kind in ("unspecified_name", "contact_provenance") and Bank.objects.filter(
                    is_archived=True,
                    pk=Contact.objects.filter(pk=fix["contact_id"]).values_list("object_id", flat=True)[:1],
                ).exists():
                    raise _Skip("the organisation is archived")

                if kind == "contact_status":
                    bank = Bank.objects.get(pk=fix["bank_id"])
                    reasons, opps = _later_activity(bank)

                    if bank.contact_status != "contacted" or reasons:
                        raise _Skip("the record changed since the preview")

                    opp = opps[0]
                    rollback.append({"model": "Bank", "pk": bank.pk, "field": "contact_status", "old": bank.contact_status})
                    rollback.append({"model": "Opportunity", "pk": opp.pk, "field": "status", "old": opp.status})
                    rollback.append({"model": "Opportunity", "pk": opp.pk, "field": "notes", "old": opp.notes})
                    bank.contact_status = "not_yet_contacted"
                    bank.save(update_fields=["contact_status"])
                    opp.status = "not_yet_contacted"
                    opp.notes = (opp.notes + "\n" if opp.notes else "") + (
                        "Corrected: the workbook shows only a delivery failure, so the organisation was not contacted."
                    )
                    opp.save(update_fields=["status", "notes"])
                elif kind == "state_in_region":
                    bank = Bank.objects.get(pk=fix["bank_id"])

                    if bank.state or (bank.region or "").strip() != fix["region_old"]:
                        raise _Skip("the record changed since the preview")

                    rollback.append({"model": "Bank", "pk": bank.pk, "field": "state", "old": bank.state})
                    rollback.append({"model": "Bank", "pk": bank.pk, "field": "region", "old": bank.region})
                    bank.state = fix["new"]
                    bank.region = ""
                    bank.save(update_fields=["state", "region"])
                elif kind == "region_duplicate_of_state":
                    bank = Bank.objects.get(pk=fix["bank_id"])

                    if (
                        (bank.region or "").strip() != fix["old"]
                        or norm_state(bank.state) != norm_state(fix["state"])
                        or not _unedited_since_import(bank)
                    ):
                        raise _Skip("the record changed since the preview")

                    rollback.append({"model": "Bank", "pk": bank.pk, "field": "region", "old": bank.region})
                    bank.region = ""
                    bank.save(update_fields=["region"])
                elif kind == "unspecified_name":
                    contact = Contact.objects.get(pk=fix["contact_id"])

                    if (contact.contact_name or "").strip().lower() != UNSPECIFIED:
                        raise _Skip("the contact name changed since the preview")

                    rollback.append({"model": "Contact", "pk": contact.pk, "field": "contact_name", "old": contact.contact_name})
                    contact.contact_name = ""
                    contact.save(update_fields=["contact_name"])
                elif kind == "source_provenance":
                    bank = Bank.objects.get(pk=fix["bank_id"])

                    if OrganisationSource.objects.filter(content_type=bank_ct, object_id=bank.pk, source_key=SOURCE_KEY).exists():
                        raise _Skip("provenance already exists")

                    from datetime import datetime

                    recorded = datetime.fromisoformat(fix["recorded_at"])
                    source = OrganisationSource.objects.create(
                        content_type=bank_ct, object_id=bank.pk, source_key=SOURCE_KEY,
                        source_org_id=fix["source_org_id"], first_collected_at=recorded,
                        last_checked_at=recorded, requires_verification=fix["needs_verification"],
                        extra=fix["extra"],
                    )
                    rollback.append({"model": "OrganisationSource", "pk": source.pk, "created": True})
                elif kind == "contact_provenance":
                    contact = Contact.objects.get(pk=fix["contact_id"])

                    if ContactSource.objects.filter(contact=contact).exists():
                        raise _Skip("provenance already exists")

                    c = fix["source_contact"]
                    from .ingest import _parse_dt

                    created = ContactSource.objects.create(
                        contact=contact, source_key=SOURCE_KEY, source_contact_id=c["source_contact_id"],
                        name_needs_verification=c.get("name_needs_verification"),
                        affiliation_needs_verification=c.get("affiliation_needs_verification"),
                        first_observed_at=_parse_dt(c.get("first_observed")),
                        last_observed_at=_parse_dt(c.get("last_observed")),
                        outreach_evidence=c.get("status", ""), sent_flag=c.get("sent_flag"),
                        human_reply=c.get("human_reply"), contact_type=c.get("contact_type", ""),
                    )
                    rollback.append({"model": "ContactSource", "pk": created.pk, "created": True})

            applied.append(fix)
        except _Skip as reason:
            skipped.append({**fix, "skipped_because": str(reason)})
        except Exception as exc:
            skipped.append({**fix, "skipped_because": f"error: {type(exc).__name__}"})

    if rollback_path:
        with open(rollback_path, "w", encoding="utf-8") as handle:
            json.dump({"applied_at": now.isoformat(), "changes": rollback}, handle, indent=2)

    return applied, skipped, rollback


class _Skip(Exception):
    pass


def revert_plan(rollback):
    """Restore the recorded old values and remove rows the correction created."""
    from .models import ContactSource as CS, OrganisationSource as OS
    from outreach.models import Bank as B, Contact as C, Opportunity as O

    models = {"Bank": B, "Contact": C, "Opportunity": O, "OrganisationSource": OS, "ContactSource": CS}

    with transaction.atomic():
        for change in reversed(rollback):
            model = models[change["model"]]

            if change.get("created"):
                model.objects.filter(pk=change["pk"]).delete()
            else:
                model.objects.filter(pk=change["pk"]).update(**{change["field"]: change["old"]})
