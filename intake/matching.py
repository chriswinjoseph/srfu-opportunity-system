"""
Exact and likely duplicate detection for banks, branches, clubs and contacts.

Conservative interpretation of the BA rules (documented in
docs/Intake-BA-Interpretations.md):

* A trusted source identifier matches first, but conflicting name/state
  evidence is held for review rather than trusted.
* A bank is an exact match only on the same normalised name AND state; a
  name alone is never sufficient.
* A missing location is never evidence of an exact match. Such records are
  likely duplicates, not exact ones.
* Likely duplicates are never merged automatically.
"""

from dataclasses import asdict, dataclass, field
from typing import Optional

from django.contrib.contenttypes.models import ContentType

from outreach.models import Bank, Branch, Club, Contact

from .models import ContactSource, OrganisationSource
from .normalise import (
    norm_email,
    norm_name,
    norm_phone,
    norm_place,
    norm_postcode,
    norm_state,
    norm_url,
    similarity,
)

ORG_MODELS = {"bank": Bank, "branch": Branch, "club": Club}
NAME_FIELD = {"bank": "bank_name", "branch": "branch_name", "club": "club_name"}
ORG_TYPES = tuple(ORG_MODELS)
TYPE_LABELS = {"bank": "Bank", "branch": "Branch", "club": "Club"}

LIKELY_SAME_STATE = 90
LIKELY_WITH_LOCATION = 80


@dataclass
class Submission:
    """One organisation (and its contacts) offered by an import or scraper."""

    org_type: str
    name: str
    state: str = ""
    region: str = ""
    suburb: str = ""
    postcode: str = ""
    address: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""
    source_url: str = ""
    club_type: str = ""
    parent_bank_name: str = ""
    parent_bank_state: str = ""
    source_key: str = ""
    source_org_id: str = ""
    source_filename: str = ""
    origin: str = "import"  # import | scraper
    row_ref: str = ""
    # Fields the source actually supplied (used to spot values that later
    # disappear from a website).
    collected_fields: list = field(default_factory=list)
    # Org-level outreach evidence from an import: contacted/not_yet_contacted
    evidence_status: Optional[str] = None
    evidence_note: str = ""
    extra: dict = field(default_factory=dict)
    contacts: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = {f for f in cls.__dataclass_fields__}

        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class MatchResult:
    kind: str  # exact | likely | conflict | none
    exact: Optional[tuple] = None  # (org_type, id)
    candidates: list = field(default_factory=list)
    reasons: list = field(default_factory=list)


def org_name(org):
    for name_field in NAME_FIELD.values():
        value = getattr(org, name_field, None)

        if value is not None:
            return value

    return ""


def org_type_of(org):
    return {Bank: "bank", Branch: "branch", Club: "club"}[type(org)]


def org_state(org):
    """
    The organisation's state code. Records imported before the state field was
    populated kept the state code in Region; that is the same fact in another
    field, so it is used when State is blank (a Region that is not a state,
    such as a metropolitan area, is ignored).
    """
    return norm_state(getattr(org, "state", "")) or norm_state(getattr(org, "region", ""))


def _describe(org, reasons, score=0):
    return {
        "type": org_type_of(org),
        "id": org.pk,
        "name": org_name(org),
        "state": getattr(org, "state", ""),
        "suburb": getattr(org, "suburb", ""),
        "postcode": getattr(org, "postcode", ""),
        "archived": bool(getattr(org, "is_archived", False)),
        "contact_status": org.contact_status,
        "reasons": list(reasons),
        "score": score,
    }


def resolve_parent_bank(sub):
    """The parent bank of a branch (by exact bank rules), or None."""
    if not sub.parent_bank_name:
        return None

    name = norm_name(sub.parent_bank_name)
    state = norm_state(sub.parent_bank_state or sub.state)

    if not name or not state:
        return None

    banks = [
        bank
        for bank in Bank.objects.all()
        if norm_name(bank.bank_name) == name and org_state(bank) == state
    ]

    return banks[0] if len(banks) == 1 else None


def _same(a, b):
    return bool(a) and bool(b) and a == b


def _is_exact(sub, org, parent):
    """The BA exact-duplicate rules for one existing organisation."""
    name_equal = norm_name(sub.name) == norm_name(org_name(org))

    if not name_equal:
        return False

    sub_state, org_st = norm_state(sub.state), org_state(org)
    sub_post = norm_postcode(sub.postcode)
    org_post = norm_postcode(getattr(org, "postcode", ""))
    sub_sub, org_sub = norm_place(sub.suburb), norm_place(getattr(org, "suburb", ""))

    if sub.org_type == "bank":
        return _same(sub_state, org_st)

    if sub.org_type == "branch":
        if parent is None or getattr(org, "bank_id", None) != parent.pk:
            return False

        return _same(sub_post, org_post) or (
            _same(sub_sub, org_sub) and _same(sub_state, org_st)
        )

    # club
    return _same(sub_state, org_st) and (
        _same(sub_post, org_post) or _same(sub_sub, org_sub)
    )


def find_source_match(sub):
    if not sub.source_key or not sub.source_org_id:
        return None

    source = OrganisationSource.objects.filter(
        source_key=sub.source_key, source_org_id=sub.source_org_id
    ).first()

    if source is None:
        return None

    model = source.content_type.model_class()

    return model.objects.filter(pk=source.object_id).first()


def find_matches(sub):
    reasons_by_org = {}
    scores = {}

    def add(org, reason, score=0):
        key = (org_type_of(org), org.pk)
        reasons_by_org.setdefault(key, [org, []])[1].append(reason)
        scores[key] = max(scores.get(key, 0), score)

    parent = resolve_parent_bank(sub) if sub.org_type == "branch" else None
    sub_state = norm_state(sub.state)
    sub_email = norm_email(sub.email)
    sub_phone = norm_phone(sub.phone)
    sub_web = norm_url(sub.website)

    # 1. Trusted source identifier.
    source_org = find_source_match(sub)
    conflict_reasons = []

    if source_org is not None:
        same_type = org_type_of(source_org) == sub.org_type
        target_state = org_state(source_org)
        name_score = similarity(sub.name, org_name(source_org))

        if (
            not same_type
            or (sub_state and target_state and sub_state != target_state)
            or name_score < LIKELY_WITH_LOCATION
        ):
            conflict_reasons.append(
                "The trusted source ID matches "
                f"'{org_name(source_org)}', but the name, state or type "
                "differs."
            )
            add(source_org, "Same trusted source ID, but conflicting details", name_score)
        else:
            return MatchResult(
                kind="exact",
                exact=(org_type_of(source_org), source_org.pk),
                candidates=[_describe(source_org, ["Trusted source identifier"], 100)],
                reasons=["Trusted source identifier"],
            )

    # 2. Exact rules and likely rules over the stored organisations.
    exact = []

    for org_type, model in ORG_MODELS.items():
        for org in model.objects.all():
            same_type = org_type == sub.org_type

            if same_type and _is_exact(sub, org, parent):
                exact.append(org)
                continue

            o_state = org_state(org)
            score = similarity(sub.name, org_name(org))
            o_sub = norm_place(getattr(org, "suburb", ""))
            o_post = norm_postcode(getattr(org, "postcode", ""))
            same_location = _same(norm_place(sub.suburb), o_sub) or _same(
                norm_postcode(sub.postcode), o_post
            )
            state_ok = _same(sub_state, o_state)
            state_unknown = not sub_state or not o_state

            if same_type:
                if norm_name(sub.name) == norm_name(org_name(org)) and state_ok:
                    add(
                        org,
                        "Same name and state, but the location is missing "
                        "or different, so this is not an exact match",
                        score,
                    )
                elif score >= LIKELY_SAME_STATE and state_ok:
                    add(org, f"Name {score:.0f}% similar in the same state", score)
                elif score >= LIKELY_SAME_STATE and state_unknown:
                    add(
                        org,
                        f"Name {score:.0f}% similar; the state is missing "
                        "on one record",
                        score,
                    )

                if (
                    score >= LIKELY_WITH_LOCATION
                    and score < LIKELY_SAME_STATE
                    and same_location
                ):
                    add(
                        org,
                        f"Name {score:.0f}% similar with the same suburb "
                        "or postcode",
                        score,
                    )
            else:
                if score >= LIKELY_SAME_STATE and (state_ok or state_unknown):
                    add(
                        org,
                        "Similar name and location, but a different "
                        f"organisation type ({TYPE_LABELS[org_type]})",
                        score,
                    )

                if (
                    sub.org_type == "branch"
                    and org_type == "bank"
                    and parent is None
                    and score >= LIKELY_WITH_LOCATION
                    and (state_ok or state_unknown)
                ):
                    add(
                        org,
                        "Looks like a bank and no parent bank was "
                        "supplied for this branch",
                        score,
                    )

            # Shared public email, phone or website with a different name.
            if score < LIKELY_SAME_STATE:
                if sub_email and norm_email(getattr(org, "public_email", "")) == sub_email:
                    add(org, "Same public email address", score)

                if sub_phone and norm_phone(getattr(org, "public_phone", "")) == sub_phone:
                    add(org, "Same public phone number", score)

                if sub_web and norm_url(getattr(org, "website_url", "")) == sub_web:
                    add(org, "Same public website", score)

    for org in exact:
        add(org, "Same type, name and location", 100)

    candidates = [
        _describe(org, reasons, scores[key])
        for key, (org, reasons) in reasons_by_org.items()
    ]
    candidates.sort(key=lambda c: -c["score"])

    # 3. Combine the evidence.
    if len(exact) > 1:
        conflict_reasons.append("More than one stored organisation is an exact match.")

    if source_org is not None and exact and any(o.pk != source_org.pk or type(o) is not type(source_org) for o in exact):
        conflict_reasons.append(
            "The source ID points at one organisation but the name and "
            "location match another."
        )

    if conflict_reasons:
        return MatchResult(kind="conflict", candidates=candidates, reasons=conflict_reasons)

    if len(exact) == 1:
        org = exact[0]

        return MatchResult(
            kind="exact",
            exact=(org_type_of(org), org.pk),
            candidates=[c for c in candidates if (c["type"], c["id"]) == (org_type_of(org), org.pk)],
            reasons=["Same type, normalised name and location"],
        )

    if candidates:
        return MatchResult(
            kind="likely",
            candidates=candidates,
            reasons=sorted({r for c in candidates for r in c["reasons"]}),
        )

    return MatchResult(kind="none")


def load_org(org_type, pk):
    return ORG_MODELS[org_type].objects.filter(pk=pk).first()


# ---------------------------------------------------------------- contacts
def match_contact(org, email, source_key="", source_contact_id=""):
    """
    ``("exact", contact)`` for a known contact of this organisation,
    ``("shared", [orgs])`` when the same email belongs to other
    organisations only, or ``("none", None)``.
    """
    if source_key and source_contact_id:
        linked = ContactSource.objects.filter(
            source_key=source_key, source_contact_id=source_contact_id
        ).select_related("contact").first()

        if linked is not None:
            return "exact", linked.contact

    email = norm_email(email)

    if not email:
        return "none", None

    content_type = ContentType.objects.get_for_model(type(org))
    same_org = [
        contact
        for contact in Contact.objects.filter(
            content_type=content_type, object_id=org.pk
        )
        if norm_email(contact.email) == email
    ]

    if same_org:
        return "exact", same_org[0]

    others = []

    for contact in Contact.objects.exclude(
        content_type=content_type, object_id=org.pk
    ):
        if norm_email(contact.email) == email:
            other = contact.content_type.model_class().objects.filter(
                pk=contact.object_id
            ).first()

            if other is not None:
                others.append(other)

    return ("shared", others) if others else ("none", None)
