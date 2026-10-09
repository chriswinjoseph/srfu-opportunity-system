import logging
import smtplib
import socket
import ssl
from functools import wraps
import hashlib


import re
import requests
from django.core.mail import send_mail


from datetime import timedelta
from io import StringIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.management import call_command
from django.core.management.base import CommandError
from django.shortcuts import redirect
from django.core.mail import EmailMessage

from difflib import SequenceMatcher


import openai


from django.contrib import messages
from django.core.cache import cache


from django.contrib.auth.decorators import login_required


from django.contrib.contenttypes.models import ContentType


from django.core.exceptions import PermissionDenied


from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from django.db import transaction

from django.db.models import F, Prefetch, Q


from django.http import Http404, JsonResponse


from django.shortcuts import get_object_or_404, redirect, render


from django.utils import timezone


from django.views.decorators.http import require_GET, require_POST


from .services import (
    find_unresolved_placeholders,
    generate_outreach_email,
    validate_generated_email,
)

from .approvals import get_available_approvers, notify_admins


from .forms import AUSTRALIAN_STATES, BankForm, BranchForm, ClubForm


from .models import (
    Bank,
    Branch,
    Club,
    Contact,
    Opportunity,
    OrganisationCreationLock,
    EmailDraft,
    EmailDraftHistory,
    EmailTemplate,
    EmailGenerationLog,
)

from .status_transitions import (
    InvalidStatusTransition,
    record_positive_response,
    record_response,
)


logger = logging.getLogger(__name__)


CONTACT_STATUS_LABELS = {
    "not_yet_contacted": "Not Yet Contacted",
    "contacted": "Contacted",
}

OPPORTUNITY_OUTCOME_LABELS = {


    "interested": "Interested",


    "not_interested": "Not Interested",


    "do_not_contact": "Do Not Contact",


}


CONTACT_STATUS_CHOICES_API = {
    "not_yet_contacted",
    "contacted",
}

ORGANISATION_API_SORT_FIELDS = {


    "name",


    "region",


    "type",


    "status",


    "date_added",


}


@login_required


def bank_list(request):


    banks = Bank.objects.filter(is_archived=False).order_by("-date_added", "-id")


    return render(


        request,


        "outreach/bank_list.html",


        {"banks": banks},


    )


@login_required


@require_POST


def record_positive_response_api(request, opportunity_id):


    """


    Record a positive response.


    The organisation remains Contacted while the opportunity changes


    to Interested.


    """


    opportunity = get_object_or_404(


        Opportunity,


        pk=opportunity_id,


    )


    try:


        opportunity, supported_clubs = record_positive_response(


            opportunity,


            actor=request.user.pk,


        )


    except InvalidStatusTransition as error:


        return JsonResponse(


            {"error": str(error)},


            status=409,


        )


    clubs = [


        {


            "id": club.id,


            "name": club.club_name,


            "type": club.club_type,


            "region": club.region,


            "contact_status": club.contact_status,


        }


        for club in supported_clubs


    ]


    return JsonResponse(


        {


            "opportunity_id": opportunity.id,


            "organisation_status": (


                opportunity.organisation.contact_status


            ),


            "opportunity_status": opportunity.status,


            "clubs": clubs,


        }


    )


def _org_to_row(org, org_type):


    """


    Convert a Bank, Branch or Club into a common dashboard format.


    Contact status and opportunity outcome are kept separate.


    A response outcome on a Not Yet Contacted organisation is


    flagged for review.


    """


    content_type = ContentType.objects.get_for_model(org)


    name = (


        getattr(org, "bank_name", None)


        or getattr(org, "branch_name", None)


        or getattr(org, "club_name", None)


    )


    latest_opportunity = (


        Opportunity.objects.filter(


            content_type=content_type,


            object_id=org.pk,


        )


        .order_by("-date_created")


        .first()


    )


    outcome_status = ""


    if (


        latest_opportunity is not None


        and latest_opportunity.status


        in OPPORTUNITY_OUTCOME_LABELS


    ):


        outcome_status = latest_opportunity.status


    status_conflict = (


        org.contact_status == "not_yet_contacted"


        and bool(outcome_status)


    )


    if status_conflict:


        status_label = "Needs Review"


    else:


        status_label = OPPORTUNITY_OUTCOME_LABELS.get(


            outcome_status,


            CONTACT_STATUS_LABELS.get(


                org.contact_status,


                org.contact_status,


            ),


        )


    return {


        "id": org.pk,


        "content_type_id": content_type.pk,


        "name": name,


        "type": org_type,


        "state": (
    getattr(org, "state", "")
    or getattr(org, "region", "")
    or ""
),
"region": getattr(org, "region", "") or "",


        "email": getattr(org, "public_email", "") or "",


        "phone": getattr(org, "public_phone", "") or "",


        "date_added": getattr(org, "date_added", None),


        "status": org.contact_status,


        "outcome_status": outcome_status,


        "status_conflict": status_conflict,


        "status_label": status_label,


    }


def _get_all_organisations(


    search="",


    org_type="",


    region="",


):


    """


    Fetch Banks, Branches and Clubs, apply filters and combine


    them into one dashboard list.


    """


    banks = Bank.objects.filter(is_archived=False)


    branches = Branch.objects.filter(is_archived=False)


    clubs = Club.objects.filter(is_archived=False)


    if search:


        banks = banks.filter(

            Q(bank_name__icontains=search)

            | Q(state__icontains=search)

            | Q(region__icontains=search)

            | Q(suburb__icontains=search)

            | Q(postcode__icontains=search)

            | Q(public_email__icontains=search)

            | Q(public_phone__icontains=search)

        )


        branches = branches.filter(

            Q(branch_name__icontains=search)

            | Q(address__icontains=search)

            | Q(state__icontains=search)

            | Q(region__icontains=search)

            | Q(suburb__icontains=search)

            | Q(postcode__icontains=search)

            | Q(public_email__icontains=search)

            | Q(public_phone__icontains=search)

        )


        clubs = clubs.filter(

            Q(club_name__icontains=search)

            | Q(club_type__icontains=search)

            | Q(state__icontains=search)

            | Q(region__icontains=search)

            | Q(suburb__icontains=search)

            | Q(postcode__icontains=search)

            | Q(public_email__icontains=search)

            | Q(public_phone__icontains=search)

        )


    if region:


        banks = banks.filter(


            region__icontains=region,


        )


        branches = branches.filter(


            region__icontains=region,


        )


        clubs = clubs.filter(


            region__icontains=region,


        )


    rows = []


    if org_type in ("", "bank"):


        rows.extend(


            _org_to_row(bank, "Bank")


            for bank in banks


        )


    if org_type in ("", "branch"):


        rows.extend(


            _org_to_row(branch, "Branch")


            for branch in branches


        )


    if org_type in ("", "club"):


        rows.extend(


            _org_to_row(club, "Club")


            for club in clubs


        )


    rows.sort(


        key=lambda row: (


            row["date_added"].timestamp()


            if row["date_added"]


            else 0


        ),


        reverse=True,


    )


    return rows
@login_required
@require_POST
def record_response_view(request, opportunity_id):
    opportunity = get_object_or_404(
        Opportunity,
        pk=opportunity_id,
    )

    response_status = request.POST.get(
        "response_status",
        "",
    ).strip()

    if response_status not in {
        "not_interested",
        "do_not_contact",
    }:
        messages.error(
            request,
            "Please select a valid response.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    try:
        record_response(
            opportunity,
            response_status,
            actor=request.user.pk,
        )

    except InvalidStatusTransition as error:
        messages.error(
            request,
            str(error),
        )

    else:
        if response_status == "not_interested":
            messages.success(
                request,
                "Response recorded as Not Interested.",
            )
        else:
            messages.success(
                request,
                "Response recorded as Do Not Contact.",
            )

    return redirect(
        "organisation_detail",
        content_type_id=opportunity.content_type_id,
        object_id=opportunity.object_id,
    )
@login_required
@require_POST
def record_positive_response_view(request, opportunity_id):
    """
    Record a positive response from the organisation and display
    the supported clubs in a user-friendly page.
    """

    opportunity = get_object_or_404(
        Opportunity,
        pk=opportunity_id,
    )

    organisation = opportunity.organisation

    try:
        opportunity, supported_clubs = record_positive_response(
            opportunity,
            actor=request.user.pk,
        )

    except InvalidStatusTransition as error:
        return render(
            request,
            "outreach/positive_response_result.html",
            {
                "success": False,
                "error": str(error),
                "organisation": organisation,
                "opportunity": opportunity,
                "supported_clubs": [],
            },
            status=409,
        )

    return render(
        request,
        "outreach/positive_response_result.html",
        {
            "success": True,
            "organisation": organisation,
            "opportunity": opportunity,
            "supported_clubs": supported_clubs,
        },
    )


@login_required


@require_GET


def organisation_list_api(request):


    """


    Return organisations as filtered, sorted and paginated JSON.


    Query parameters:


    - q: partial name search


    - type: bank, branch or club


    - region: partial region match


    - status: organisation contact status


    - sort_by: date_added, name, region, type or status


    - sort_dir: asc or desc


    - page: positive integer


    - page_size: positive integer with a maximum of 50


    """


    search = request.GET.get(


        "q",


        "",


    ).strip()


    organisation_type = (


        request.GET.get(


            "type",


            "",


        )


        .strip()


        .lower()


    )


    region = request.GET.get(


        "region",


        "",


    ).strip()


    allowed_types = {


        "",


        "bank",


        "branch",


        "club",


    }


    if organisation_type not in allowed_types:


        return JsonResponse(


            {


                "error": "Invalid organisation type.",


                "invalid_type": organisation_type,


                "allowed_types": [


                    "bank",


                    "branch",


                    "club",


                ],


            },


            status=400,


        )


    status_values = []


    for raw_value in request.GET.getlist("status"):


        for value in raw_value.split(","):


            value = value.strip().lower()


            if value and value not in status_values:


                status_values.append(value)


    invalid_statuses = sorted(


        set(status_values)


        - CONTACT_STATUS_CHOICES_API


    )


    if invalid_statuses:


        return JsonResponse(


            {


                "error": "Invalid contact status.",


                "invalid_statuses": invalid_statuses,


                "allowed_statuses": sorted(


                    CONTACT_STATUS_CHOICES_API


                ),


            },


            status=400,


        )


    sort_by = (


        request.GET.get(


            "sort_by",


            "date_added",


        )


        .strip()


        .lower()


    )


    if sort_by not in ORGANISATION_API_SORT_FIELDS:


        return JsonResponse(


            {


                "error": "Invalid sort field.",


                "invalid_sort": sort_by,


                "allowed_sort_fields": sorted(


                    ORGANISATION_API_SORT_FIELDS


                ),


            },


            status=400,


        )


    sort_dir = (


        request.GET.get(


            "sort_dir",


            "desc",


        )


        .strip()


        .lower()


    )


    if sort_dir not in {"asc", "desc"}:


        return JsonResponse(


            {


                "error": (


                    "sort_dir must be either asc or desc."


                ),


            },


            status=400,


        )


    try:


        page_number = int(


            request.GET.get(


                "page",


                "1",


            )


        )


    except ValueError:


        return JsonResponse(


            {


                "error": (


                    "page must be a positive integer."


                ),


            },


            status=400,


        )


    if page_number < 1:


        return JsonResponse(


            {


                "error": (


                    "page must be a positive integer."


                ),


            },


            status=400,


        )


    try:


        page_size = int(


            request.GET.get(


                "page_size",


                "10",


            )


        )


    except ValueError:


        return JsonResponse(


            {


                "error": (


                    "page_size must be a "


                    "positive integer."


                ),


            },


            status=400,


        )


    if page_size < 1:


        return JsonResponse(


            {


                "error": (


                    "page_size must be a "


                    "positive integer."


                ),


            },


            status=400,


        )


    if page_size > 50:


        return JsonResponse(


            {


                "error": (


                    "page_size cannot exceed 50."


                ),


            },


            status=400,


        )


    rows = _get_all_organisations(


        search=search,


        org_type=organisation_type,


        region=region,


    )


    if status_values:


        rows = [


            row


            for row in rows


            if row["status"] in status_values


        ]


    summary = {


        "contact_status_counts": {


            status: sum(


                row["status"] == status


                for row in rows


            )


            for status in CONTACT_STATUS_LABELS


        },


        "opportunity_outcome_counts": {


            status: sum(


                (


                    row["outcome_status"]


                    == status


                    and not row["status_conflict"]


                )


                for row in rows


            )


            for status


            in OPPORTUNITY_OUTCOME_LABELS


        },


        "needs_review": sum(


            row["status_conflict"]


            for row in rows


        ),


    }


    sort_key_map = {


        "name": (


            lambda row: row["name"].lower()


        ),


        "region": (


            lambda row: row["region"].lower()


        ),


        "type": (


            lambda row: row["type"].lower()


        ),


        "status": (


            lambda row: row["status"]


        ),


        "date_added": (


            lambda row: (


                row["date_added"].timestamp()


                if row["date_added"]


                else 0


            )


        ),


    }


    rows.sort(


        key=lambda row: (


            sort_key_map[sort_by](row),


            row["name"].lower(),


            row["type"].lower(),


            row["id"],


        ),


        reverse=(


            sort_dir == "desc"


        ),


    )


    paginator = Paginator(


        rows,


        page_size,


    )


    if page_number > paginator.num_pages:


        return JsonResponse(


            {


                "error": "Page is out of range.",


                "requested_page": page_number,


                "total_pages": (


                    paginator.num_pages


                ),


            },


            status=400,


        )


    page = paginator.page(


        page_number


    )


    results = [
    {
        "id": row["id"],
        "content_type_id": (
            row["content_type_id"]
        ),
        "type": row["type"].lower(),
        "name": row["name"],
        "state": row["state"],
        "region": row["region"],
        "public_email": row["email"],
        "public_phone": row["phone"],
        "date_added": (
            row["date_added"].isoformat()
            if row["date_added"]
            else None
        ),
        "contact_status": row["status"],
        "contact_status_label": (
            CONTACT_STATUS_LABELS[
                row["status"]
            ]
        ),
        "opportunity_outcome": (
            row["outcome_status"]
            or None
        ),
        "status_conflict": (
            row["status_conflict"]
        ),
    }
    for row in page.object_list
]


    return JsonResponse(


        {


            "results": results,


            "pagination": {


                "page": page.number,


                "page_size": page_size,


                "total_items": paginator.count,


                "total_pages": (


                    paginator.num_pages


                ),


                "has_next": (


                    page.has_next()


                ),


                "has_previous": (


                    page.has_previous()


                ),


            },


            "filters": {


                "status": status_values,


                "type": (


                    organisation_type


                    or None


                ),


                "search": search or None,


                "region": region or None,


            },


            "sorting": {


                "sort_by": sort_by,


                "sort_dir": sort_dir,


            },


            "summary": summary,


        }


    )


@login_required


def dashboard_view(request):


    search = request.GET.get(


        "q",


        "",


    ).strip()


    org_type = request.GET.get(


        "type",


        "",


    )


    region = request.GET.get(


        "region",


        "",


    ).strip()


    all_rows = _get_all_organisations(


        search=search,


        org_type=org_type,


        region=region,


    )


    not_yet = [


        row


        for row in all_rows


        if row["status"]


        == "not_yet_contacted"


    ]


    contacted = [
    row
    for row in all_rows
    if row["status"] == "contacted"
]

    not_yet_page = Paginator(


        not_yet,


        5,


    ).get_page(


        request.GET.get(


            "not_yet_page"


        )


    )


    contacted_page = Paginator(


        contacted,


        5,


    ).get_page(


        request.GET.get(


            "contacted_page"


        )


    )


    total = len(all_rows)


    contacted_count = len(contacted)


    percent_contacted = (


        round(


            (contacted_count / total)


            * 100


        )


        if total


        else 0


    )


    status_breakdown = {
    "Interested": len(
        [
            row
            for row in all_rows
            if row["outcome_status"] == "interested"
            and not row["status_conflict"]
        ]
    ),
    "Not Interested": len(
        [
            row
            for row in all_rows
            if row["outcome_status"] == "not_interested"
            and not row["status_conflict"]
        ]
    ),
    "Do Not Contact": len(
        [
            row
            for row in all_rows
            if row["outcome_status"] == "do_not_contact"
            and not row["status_conflict"]
        ]
    ),
}

    status_breakdown[


        "Needs Review"


    ] = len(


        [


            row


            for row in all_rows


            if row["status_conflict"]


        ]


    )


    context = {


        "not_yet_page": not_yet_page,


        "contacted_page": contacted_page,


        "percent_contacted": (


            percent_contacted


        ),


        "not_yet_count": len(not_yet),


        "contacted_count": (


            contacted_count


        ),


        "status_breakdown": (


            status_breakdown


        ),


        "search": search,


        "org_type": org_type,


        "region": region,


    
        "can_review_approvals": request.user.has_perm(
            "outreach.approve_emaildraft"
        ),
        "pending_approval_count": (
            EmailDraft.objects.filter(
                workflow_status="awaiting_approval",
            ).count()
            if request.user.has_perm("outreach.approve_emaildraft")
            else 0
        ),
    }


    return render(


        request,


        "outreach/dashboard.html",


        context,


    )


@login_required
def pending_approvals(request):
    """
    Read-only queue of drafts currently Awaiting Approval, for users
    holding the approval permission. Viewing it never changes state.
    """
    if not request.user.has_perm("outreach.approve_emaildraft"):
        raise PermissionDenied

    drafts = (
        EmailDraft.objects
        .filter(workflow_status="awaiting_approval")
        .select_related("opportunity", "opportunity__content_type")
        .prefetch_related(
            Prefetch(
                "workflow_history",
                queryset=(
                    EmailDraftHistory.objects
                    .filter(action="submitted")
                    .select_related("performed_by")
                    .order_by("-created_at")
                ),
                to_attr="submission_events",
            )
        )
        .order_by("submitted_at", "created_at")
    )

    rows = []

    for draft in drafts:
        organisation = draft.opportunity.organisation
        event = (
            draft.submission_events[0]
            if draft.submission_events
            else None
        )

        rows.append(
            {
                "draft": draft,
                "organisation_name": (
                    _organisation_name(organisation)
                    if organisation is not None
                    else "Unknown organisation"
                ),
                "content_type_id": draft.opportunity.content_type_id,
                "object_id": draft.opportunity.object_id,
                "submitted_at": (
                    draft.submitted_at
                    or (event.created_at if event else None)
                ),
                "submitted_by": (
                    event.performed_by if event else None
                ),
            }
        )

    return render(
        request,
        "outreach/pending_approvals.html",
        {"rows": rows},
    )


@login_required
def organisation_detail(
    request,
    content_type_id,
    object_id,
):
    content_type = get_object_or_404(
        ContentType,
        pk=content_type_id,
    )

    model_class = content_type.model_class()

    if model_class not in (
        Bank,
        Branch,
        Club,
    ):
        raise Http404(
            "Organisation not found."
        )

    org = get_object_or_404(
        model_class,
        pk=object_id,
    )

    opportunities = (
        Opportunity.objects.filter(
            content_type=content_type,
            object_id=object_id,
        )
        .order_by("-date_created")
    )

    latest_opportunity = opportunities.first()

    has_do_not_contact = opportunities.filter(
        status="do_not_contact"
    ).exists()

    latest_draft = (
        EmailDraft.objects.filter(
            opportunity__content_type=content_type,
            opportunity__object_id=object_id,
        )
        .order_by("-created_at")
        .first()
    )
    email_workflow_history = []

    if latest_draft:
        email_workflow_history = (
        latest_draft.workflow_history
        .select_related("performed_by")
        .all()
    )

    # Only active/approved templates can be used.
    active_templates = (
        EmailTemplate.objects.filter(
            is_active=True,
        )
        .order_by("name", "version")
    )

    context = {
        "org": org,
        "org_type": content_type.model,
        "opportunities": opportunities,
        "latest_opportunity": latest_opportunity,
        "has_do_not_contact": has_do_not_contact,
        "content_type_id": content_type_id,
        "object_id": object_id,
        "latest_draft": latest_draft,
        "active_templates": active_templates,
        "email_workflow_history": email_workflow_history,
        "can_modify_draft": (
            latest_draft.user_can_modify(request.user)
            if latest_draft
            else False
        ),
        "can_manage_organisation": request.user.has_perm(
            f"outreach.change_{content_type.model}"
        ),
    }

    return render(
        request,
        "outreach/organisation_detail.html",
        context,
    )
# ---------------------------------------------------------


# Add Organisation helpers


# ---------------------------------------------------------


def _normalise_duplicate_value(value):


    """


    Normalise text used during duplicate checking.


    This ignores:


    - capitalisation


    - leading/trailing spaces


    - repeated spaces


    - common punctuation differences


    """


    value = (


        str(value or "")


        .strip()


        .lower()


    )


    value = re.sub(


        r"[^\w\s]",


        "",


        value,


    )


    value = re.sub(


        r"\s+",


        " ",


        value,


    )


    return value


def _normalise_phone(value):
    """Digits only, with +61 treated as a leading 0."""
    digits = re.sub(r"[^\d+]", "", str(value or ""))

    if digits.startswith("+61"):
        digits = "0" + digits[3:]

    return digits


def _normalise_website(value):
    """Ignore scheme, www., case and trailing slashes."""
    value = str(value or "").strip().lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)
    value = re.sub(r"^www\.", "", value)

    return value.rstrip("/")


_STATE_CODES = {code for code, _ in AUSTRALIAN_STATES if code}


def _organisation_state(organisation):
    """State code of an existing record ('' when not a known code)."""
    for attribute in ("state", "region"):
        value = str(
            getattr(organisation, attribute, "") or ""
        ).strip().upper()

        if value in _STATE_CODES:
            return value

    return ""


def _organisation_name(organisation):


    """


    Return the organisation's display name.


    """


    return (


        getattr(


            organisation,


            "bank_name",


            None,


        )


        or getattr(


            organisation,


            "branch_name",


            None,


        )


        or getattr(


            organisation,


            "club_name",


            None,


        )


        or ""


    )


def _find_exact_duplicate(
    organisation_type,
    cleaned_data,
    exclude=None,
):
    """
    Find an exact organisation duplicate.

    Exact duplicate:
    - same normalised organisation name
    - same organisation type
    - same suburb OR same postcode

    Suburb is optional, so postcode can be used as the
    location match when suburb is not available.
    """

    if organisation_type == "bank":
        queryset = Bank.objects.all()
        submitted_name = cleaned_data.get(
            "bank_name",
            "",
        )

    elif organisation_type == "branch":
        queryset = Branch.objects.all()
        submitted_name = cleaned_data.get(
            "branch_name",
            "",
        )

    elif organisation_type == "club":
        queryset = Club.objects.all()
        submitted_name = cleaned_data.get(
            "club_name",
            "",
        )

    else:
        return None

    submitted_name = _normalise_duplicate_value(
        submitted_name
    )

    submitted_suburb = _normalise_duplicate_value(
        cleaned_data.get(
            "suburb",
            "",
        )
    )

    submitted_postcode = _normalise_duplicate_value(
        cleaned_data.get(
            "postcode",
            "",
        )
    )

    submitted_state = str(
        cleaned_data.get("state", "") or ""
    ).strip().upper()

    for organisation in queryset:
        if exclude is not None and organisation.pk == exclude.pk:
            continue

        existing_name = _normalise_duplicate_value(
            _organisation_name(
                organisation
            )
        )

        existing_state = _organisation_state(organisation)

        # Different known states are different organisations.
        if (
            submitted_state
            and existing_state
            and submitted_state != existing_state
        ):
            continue

        existing_suburb = _normalise_duplicate_value(
            getattr(
                organisation,
                "suburb",
                "",
            )
        )

        existing_postcode = _normalise_duplicate_value(
            getattr(
                organisation,
                "postcode",
                "",
            )
        )

        name_matches = (
            submitted_name
            and submitted_name == existing_name
        )

        suburb_matches = (
            bool(submitted_suburb)
            and submitted_suburb == existing_suburb
        )

        postcode_matches = (
            bool(submitted_postcode)
            and submitted_postcode == existing_postcode
        )

        location_matches = (
            suburb_matches
            or postcode_matches
        )

        if (
            name_matches
            and location_matches
        ):
            return organisation

    return None


def _find_likely_duplicate(
    organisation_type,
    cleaned_data,
):
    """
    Find an organisation that may be a duplicate.

    Possible duplicate:
    - same public email
    - same phone number
    - same website
    - very similar name with matching location
    """

    if organisation_type == "bank":
        queryset = Bank.objects.all()

        submitted_name = cleaned_data.get(
            "bank_name",
            "",
        )

    elif organisation_type == "branch":
        queryset = Branch.objects.all()

        submitted_name = cleaned_data.get(
            "branch_name",
            "",
        )

    elif organisation_type == "club":
        queryset = Club.objects.all()

        submitted_name = cleaned_data.get(
            "club_name",
            "",
        )

    else:
        return None

    submitted_name = _normalise_duplicate_value(
        submitted_name
    )

    submitted_email = _normalise_duplicate_value(
        cleaned_data.get(
            "public_email",
            "",
        )
    )

    submitted_phone = _normalise_phone(
        cleaned_data.get(
            "public_phone",
            "",
        )
    )

    submitted_website = _normalise_website(
        cleaned_data.get(
            "website_url",
            "",
        )
    )

    submitted_region = _normalise_duplicate_value(
        cleaned_data.get(
            "region",
            "",
        )
    )

    submitted_suburb = _normalise_duplicate_value(
        cleaned_data.get(
            "suburb",
            "",
        )
    )

    submitted_postcode = _normalise_duplicate_value(
        cleaned_data.get(
            "postcode",
            "",
        )
    )

    for organisation in queryset:
        existing_name = _normalise_duplicate_value(
            _organisation_name(
                organisation
            )
        )

        existing_email = _normalise_duplicate_value(
            getattr(
                organisation,
                "public_email",
                "",
            )
        )

        existing_phone = _normalise_phone(
            getattr(
                organisation,
                "public_phone",
                "",
            )
        )

        existing_website = _normalise_website(
            getattr(
                organisation,
                "website_url",
                "",
            )
        )

        existing_region = _normalise_duplicate_value(
            getattr(
                organisation,
                "region",
                "",
            )
        )

        existing_suburb = _normalise_duplicate_value(
            getattr(
                organisation,
                "suburb",
                "",
            )
        )

        existing_postcode = _normalise_duplicate_value(
            getattr(
                organisation,
                "postcode",
                "",
            )
        )

        same_email = (
            bool(submitted_email)
            and submitted_email == existing_email
        )

        same_phone = (
            bool(submitted_phone)
            and submitted_phone == existing_phone
        )

        same_website = (
            bool(submitted_website)
            and submitted_website == existing_website
        )

        name_similarity = SequenceMatcher(
            None,
            submitted_name,
            existing_name,
        ).ratio()

        similar_name = (
            bool(submitted_name)
            and bool(existing_name)
            and name_similarity >= 0.80
        )

        # A shared state alone is too broad to count as "same
        # location"; require the suburb or postcode to match (the
        # region is only used when neither is known).
        same_location = (
            (
                not submitted_suburb
                and not submitted_postcode
                and bool(submitted_region)
                and submitted_region
                == existing_region
            )
            or (
                bool(submitted_suburb)
                and submitted_suburb
                == existing_suburb
            )
            or (
                bool(submitted_postcode)
                and submitted_postcode
                == existing_postcode
            )
        )

        if (
            same_email
            or same_phone
            or same_website
            or (
                similar_name
                and same_location
            )
        ):
            return organisation

    return None


ORGANISATION_FORMS = {


    "bank": BankForm,


    "branch": BranchForm,


    "club": ClubForm,


}


@login_required
@require_POST
def generate_email_draft(
    request,
    content_type_id,
    object_id,
):

    # ---------------------------------------------------------
    # 1. Permission check
    # ---------------------------------------------------------

    if not request.user.has_perm(
        "outreach.generate_emaildraft"
    ):
        messages.error(
            request,
            "You do not have permission to generate email drafts.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 2. Organisation check
    # ---------------------------------------------------------

    content_type = get_object_or_404(
        ContentType,
        pk=content_type_id,
    )

    model_class = content_type.model_class()

    if model_class not in (
        Bank,
        Branch,
        Club,
    ):
        raise Http404(
            "Organisation not found."
        )

    organisation = get_object_or_404(
        model_class,
        pk=object_id,
    )

    if organisation.is_archived:
        messages.error(
            request,
            "This organisation is archived and cannot be contacted.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )
    if organisation.contact_status != "not_yet_contacted":
        messages.error(
            request,
            (
                "A new initial outreach draft cannot be created because "
                "this organisation has already been contacted."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 3. Get generation inputs
    # ---------------------------------------------------------

    outreach_purpose = request.POST.get(
        "outreach_purpose",
        "",
    ).strip()

    template_id = request.POST.get(
        "template_id",
        "",
    ).strip()

    is_regeneration = (
        request.POST.get("regenerate") == "1"
    )

    regeneration_confirmed = (
        request.POST.get("confirm_regenerate") == "1"
    )

    trigger_source = (
        "regenerate"
        if is_regeneration
        else "manual"
    )

    # ---------------------------------------------------------
    # 4. Recipient email eligibility
    # ---------------------------------------------------------

    recipient_email = (
        organisation.public_email or ""
    ).strip()

    try:
        validate_email(
            recipient_email
        )

    except ValidationError:
        messages.error(
            request,
            (
                "A valid recipient email is required "
                "before a draft can be generated."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 5. Outreach purpose eligibility
    # ---------------------------------------------------------

    if not outreach_purpose:
        messages.error(
            request,
            "Please provide the purpose of the outreach.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 6. Approved template eligibility
    # ---------------------------------------------------------

    if not template_id:
        messages.error(
            request,
            "Please select an approved email template.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    if not template_id.isdigit():
        messages.error(
            request,
            "The selected email template is invalid.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    template = EmailTemplate.objects.filter(
        pk=template_id,
        is_active=True,
    ).first()

    if template is None:
        messages.error(
            request,
            (
                "The selected email template is unavailable "
                "or is not approved."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 7. Find latest opportunity
    # ---------------------------------------------------------

    latest_opportunity = (
        Opportunity.objects.filter(
            content_type=content_type,
            object_id=object_id,
        )
        .order_by("-date_created")
        .first()
    )

    # ---------------------------------------------------------
    # 8. Do Not Contact eligibility
    # ---------------------------------------------------------

    has_do_not_contact = Opportunity.objects.filter(
        content_type=content_type,
        object_id=object_id,
        status="do_not_contact",
    ).exists()

    if has_do_not_contact:
        messages.error(
            request,
            (
                "Email generation is unavailable because "
                "this organisation is marked Do Not Contact."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 9. Check existing AI draft / regeneration
    # ---------------------------------------------------------

    latest_existing_draft = (
        EmailDraft.objects.filter(
            opportunity__content_type=content_type,
            opportunity__object_id=object_id,
            template__isnull=False,
        )
        .order_by("-created_at")
        .first()
    )

    active_existing_draft = (
        EmailDraft.objects.filter(
            opportunity__content_type=content_type,
            opportunity__object_id=object_id,
            workflow_status__in=[
                "draft",
                "awaiting_approval",
                "changes_requested",
                "approved",
                "sending",
                "send_failed",
            ],
        )
        .order_by("-created_at")
        .first()
    )

    # A normal Generate action must not create a second active initial draft.
    if (
        active_existing_draft
        and not is_regeneration
    ):
        messages.warning(
            request,
            (
                "An active email draft already exists for this organisation. "
                "Please review the existing draft instead of creating another."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # Regeneration must be deliberately confirmed.
    if (
        is_regeneration
        and not regeneration_confirmed
    ):
        messages.error(
            request,
            (
                "Please confirm regeneration before "
                "creating a new draft version."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # Regeneration only makes sense if an AI draft exists.
    if (
        is_regeneration
        and latest_existing_draft is None
    ):
        messages.error(
            request,
            (
                "There is no existing AI draft to regenerate. "
                "Please generate a draft first."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 10. Stop AI generation after 3 consecutive failures
    # ---------------------------------------------------------

    recent_generation_logs = list(
        EmailGenerationLog.objects.filter(
            content_type=content_type,
            object_id=object_id,
            requested_by=request.user,
        )
        .order_by("-created_at")[:3]
    )

    three_consecutive_failures = (
        len(recent_generation_logs) == 3
        and all(
            log.status in {
                "failed",
                "timed_out",
            }
            for log in recent_generation_logs
        )
    )

    if three_consecutive_failures:
        messages.warning(
            request,
            (
                "AI email generation has failed 3 times. "
                "Please create the email manually instead."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 11. Rate limiting
    # Maximum 5 generation attempts in 5 minutes
    # ---------------------------------------------------------

    rate_limit_start = (
        timezone.now()
        - timedelta(minutes=5)
    )

    recent_attempts = (
        EmailGenerationLog.objects.filter(
            requested_by=request.user,
            created_at__gte=rate_limit_start,
        ).count()
    )

    if recent_attempts >= 5:
        messages.error(
            request,
            (
                "Too many email generation requests were made recently. "
                "Please wait a few minutes and try again."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 12. Prevent duplicate / double-click requests
    # ---------------------------------------------------------

    request_signature = (
        f"{request.user.pk}|"
        f"{content_type.pk}|"
        f"{object_id}|"
        f"{template.pk}|"
        f"{outreach_purpose.strip().lower()}|"
        f"{trigger_source}"
    )

    request_hash = hashlib.sha256(
        request_signature.encode("utf-8")
    ).hexdigest()

    generation_lock_key = (
        f"email_generation_lock_{request_hash}"
    )

    lock_acquired = cache.add(
        generation_lock_key,
        True,
        timeout=60,
    )

    if not lock_acquired:
        messages.error(
            request,
            (
                "This email generation request is already processing. "
                "Please wait for it to finish."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    # ---------------------------------------------------------
    # 13. Calculate audit attempt number
    # ---------------------------------------------------------

    previous_attempts = (
        EmailGenerationLog.objects.filter(
            content_type=content_type,
            object_id=object_id,
        ).count()
    )

    attempt_number = previous_attempts + 1

    # ---------------------------------------------------------
    # Everything after lock acquisition stays protected
    # ---------------------------------------------------------

    try:

        # -----------------------------------------------------
        # 14. Get verified organisation/contact information
        # -----------------------------------------------------

        organisation_name = str(
            organisation
        )

        contact = (
            organisation.contacts.order_by(
                "-last_verified",
                "-id",
            ).first()
        )

        contact_name = ""
        contact_role = ""

        if contact:
            contact_name = (
                getattr(
                    contact,
                    "contact_name",
                    "",
                )
                or ""
            )

            contact_role = (
                getattr(
                    contact,
                    "role",
                    "",
                )
                or ""
            )

        parent_bank = ""

        if isinstance(
            organisation,
            Branch,
        ):
            parent_bank = (
                organisation.bank.bank_name
            )

        elif isinstance(
            organisation,
            Club,
        ):
            if organisation.supported_by_bank:
                parent_bank = (
                    organisation
                    .supported_by_bank
                    .bank_name
                )

            elif organisation.supported_by_branch:
                parent_bank = (
                    organisation
                    .supported_by_branch
                    .bank
                    .bank_name
                )

        # -----------------------------------------------------
        # 15. Generate AI draft
        # -----------------------------------------------------

        try:
            (
                subject,
                body,
                input_tokens,
                output_tokens,
                total_tokens,
                is_incomplete,
                validation_issues,
            ) = generate_outreach_email(

                organisation_name=organisation_name,
                organisation_type=content_type.model,
                recipient_email=recipient_email,
                outreach_purpose=outreach_purpose,

                template_name=template.name,
                template_version=template.version,
                template_body=template.template_body,
                sender_name=template.sender_name,
                sender_role=template.sender_role,
                project_details=template.project_details,
                call_to_action=template.call_to_action,
                signature=template.signature,

                contact_name=contact_name,
                contact_role=contact_role,

                region=(
                    getattr(
                        organisation,
                        "region",
                        "",
                    )
                    or ""
                ),

                state=(
                    getattr(
                        organisation,
                        "state",
                        "",
                    )
                    or ""
                ),

                suburb=(
                    getattr(
                        organisation,
                        "suburb",
                        "",
                    )
                    or ""
                ),

                website=(
                    getattr(
                        organisation,
                        "website_url",
                        "",
                    )
                    or ""
                ),

                parent_bank=parent_bank,

                contact_status=(
                    getattr(
                        organisation,
                        "contact_status",
                        "",
                    )
                    or ""
                ),

                opportunity_status=(
                    latest_opportunity.status
                    if latest_opportunity
                    else ""
                ),
            )

        # -----------------------------------------------------
        # Timeout
        # -----------------------------------------------------

        except openai.APITimeoutError:

            logger.exception(
                (
                    "OpenAI API timed out while generating "
                    "email draft for organisation '%s'."
                ),
                organisation_name,
            )

            EmailGenerationLog.objects.create(
                content_type=content_type,
                object_id=object_id,
                opportunity=latest_opportunity,
                requested_by=request.user,
                trigger_source=trigger_source,
                status="timed_out",
                attempt_number=attempt_number,
                template_version=template.version,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                error_message="OpenAI API timeout.",
            )

            messages.error(
                request,
                (
                    "The AI service took too long to respond. "
                    "Please try again shortly."
                ),
            )

            return redirect(
                "organisation_detail",
                content_type_id=content_type_id,
                object_id=object_id,
            )

        # -----------------------------------------------------
        # Connection failure
        # -----------------------------------------------------

        except openai.APIConnectionError:

            logger.exception(
                (
                    "OpenAI connection error while generating "
                    "email draft for organisation '%s'."
                ),
                organisation_name,
            )

            EmailGenerationLog.objects.create(
                content_type=content_type,
                object_id=object_id,
                opportunity=latest_opportunity,
                requested_by=request.user,
                trigger_source=trigger_source,
                status="failed",
                attempt_number=attempt_number,
                template_version=template.version,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                error_message=(
                    "OpenAI API connection error."
                ),
            )

            messages.error(
                request,
                (
                    "The AI service could not be reached. "
                    "Please try again shortly."
                ),
            )

            return redirect(
                "organisation_detail",
                content_type_id=content_type_id,
                object_id=object_id,
            )

        # -----------------------------------------------------
        # API status failure
        # -----------------------------------------------------

        except openai.APIStatusError as error:

            logger.exception(
                (
                    "OpenAI API error while generating "
                    "email draft for organisation '%s'."
                ),
                organisation_name,
            )

            status_code = getattr(
                error,
                "status_code",
                None,
            )

            audit_status = (
                "timed_out"
                if status_code in {
                    408,
                    504,
                }
                else "failed"
            )

            EmailGenerationLog.objects.create(
                content_type=content_type,
                object_id=object_id,
                opportunity=latest_opportunity,
                requested_by=request.user,
                trigger_source=trigger_source,
                status=audit_status,
                attempt_number=attempt_number,
                template_version=template.version,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                error_message=(
                    f"OpenAI API error "
                    f"({status_code or 'unknown'})."
                ),
            )

            if status_code in {
                408,
                429,
                500,
                502,
                503,
                504,
            }:
                message = (
                    "The AI service is temporarily unavailable or busy. "
                    "Please try again shortly."
                )

            elif status_code in {
                401,
                403,
            }:
                message = (
                    "The AI service could not be accessed. "
                    "Please contact an administrator."
                )

            else:
                message = (
                    "The email draft could not be generated. "
                    "Please try again."
                )

            messages.error(
                request,
                message,
            )

            return redirect(
                "organisation_detail",
                content_type_id=content_type_id,
                object_id=object_id,
            )

        # -----------------------------------------------------
        # Prompt injection / invalid generation
        # -----------------------------------------------------

        except ValueError as error:

            error_message = str(
                error
            )

            if (
                "Potential prompt injection detected"
                in error_message
            ):

                logger.warning(
                    (
                        "Prompt injection detected while generating "
                        "email draft for organisation '%s': %s"
                    ),
                    organisation_name,
                    error_message,
                )

                EmailGenerationLog.objects.create(
                    content_type=content_type,
                    object_id=object_id,
                    opportunity=latest_opportunity,
                    requested_by=request.user,
                    trigger_source=trigger_source,
                    status="failed",
                    attempt_number=attempt_number,
                    template_version=template.version,
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    error_message=(
                        "Potential prompt injection detected."
                    ),
                )

                messages.error(
                    request,
                    (
                        "Potential unsafe instruction detected in the "
                        "organisation data. Please review the organisation "
                        "information before generating an email."
                    ),
                )

                return redirect(
                    "organisation_detail",
                    content_type_id=content_type_id,
                    object_id=object_id,
                )

            logger.exception(
                (
                    "Invalid AI generation result "
                    "for organisation '%s'."
                ),
                organisation_name,
            )

            EmailGenerationLog.objects.create(
                content_type=content_type,
                object_id=object_id,
                opportunity=latest_opportunity,
                requested_by=request.user,
                trigger_source=trigger_source,
                status="failed",
                attempt_number=attempt_number,
                template_version=template.version,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                error_message=error_message,
            )

            messages.error(
                request,
                (
                    "The AI returned an invalid email draft. "
                    "Please try again."
                ),
            )

            return redirect(
                "organisation_detail",
                content_type_id=content_type_id,
                object_id=object_id,
            )

        # -----------------------------------------------------
        # Unexpected generation failure
        # -----------------------------------------------------

        except Exception as error:

            logger.exception(
                (
                    "Unexpected error while generating "
                    "email draft for organisation '%s'."
                ),
                organisation_name,
            )

            EmailGenerationLog.objects.create(
                content_type=content_type,
                object_id=object_id,
                opportunity=latest_opportunity,
                requested_by=request.user,
                trigger_source=trigger_source,
                status="failed",
                attempt_number=attempt_number,
                template_version=template.version,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                error_message=(
                    "Unexpected generation error: "
                    f"{type(error).__name__}"
                ),
            )

            messages.error(
                request,
                (
                    "An unexpected error occurred while generating "
                    "the email draft. Please try again."
                ),
            )

            return redirect(
                "organisation_detail",
                content_type_id=content_type_id,
                object_id=object_id,
            )

        # -----------------------------------------------------
        # 16. Create opportunity only after successful generation
        # -----------------------------------------------------

        if latest_opportunity is None:
            latest_opportunity = (
                Opportunity.objects.create(
                    content_type=content_type,
                    object_id=object_id,
                    status="not_yet_contacted",
                )
            )

        # -----------------------------------------------------
        # 17. Calculate draft version
        # -----------------------------------------------------

        draft_version = 1
        regeneration_attempts = 0

        if latest_existing_draft:
            draft_version = (
                latest_existing_draft.version + 1
            )

            regeneration_attempts = (
                latest_existing_draft
                .regeneration_attempts
                + 1
            )

        # -----------------------------------------------------
        # 18. Save generated draft
        # -----------------------------------------------------

        draft = EmailDraft.objects.create(
            opportunity=latest_opportunity,
            template=template,
            template_version=template.version,
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            outreach_purpose=outreach_purpose,
            workflow_status="draft",
            generation_status="success",
            requested_by=request.user,
            trigger_source=trigger_source,
            version=draft_version,
            regeneration_attempts=regeneration_attempts,
            is_incomplete=is_incomplete,
            validation_issues="\n".join(validation_issues),
        )

        if is_incomplete:
            messages.warning(
                request,
                (
                    "The AI draft was generated, but some validation "
                    "checks failed. Please review and edit it before "
                    "submitting for approval."
                ),
            )

        # -----------------------------------------------------
        # 19. Audit successful generation
        # -----------------------------------------------------

        EmailGenerationLog.objects.create(
            content_type=content_type,
            object_id=object_id,
            opportunity=latest_opportunity,
            draft=draft,
            requested_by=request.user,
            trigger_source=trigger_source,
            status="success",
            attempt_number=attempt_number,
            template_version=template.version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            error_message="",
        )

        # -----------------------------------------------------
        # 20. Success message
        # -----------------------------------------------------

        if not is_incomplete:

            if is_regeneration:
                messages.success(
                    request,
                    (
                        f"Draft regenerated successfully as "
                        f"version {draft.version}. "
                        "Review and edit the new version before "
                        "submitting it for approval."
                    ),
                )

            else:
                messages.success(
                    request,
                    (
                        "Draft generated successfully. "
                        "Review and edit the email before "
                        "submitting it for approval."
                    ),
                )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    finally:

        # -----------------------------------------------------
        # Always release duplicate-request lock
        # -----------------------------------------------------

        cache.delete(
            generation_lock_key
        )
@login_required
@require_POST
def create_manual_email_draft(
    request,
    content_type_id,
    object_id,
):
    if not request.user.has_perm("outreach.generate_emaildraft"):
        messages.error(
            request,
            "You do not have permission to create email drafts.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    content_type = get_object_or_404(ContentType, pk=content_type_id)
    model_class = content_type.model_class()

    if model_class not in (Bank, Branch, Club):
        raise Http404("Organisation not found.")

    organisation = get_object_or_404(model_class, pk=object_id)

    if organisation.is_archived:
        messages.error(
            request,
            "This organisation is archived and cannot be contacted.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )
    if organisation.contact_status != "not_yet_contacted":
        messages.error(
            request,
            (
                "A new initial outreach draft cannot be created because "
                "this organisation has already been contacted."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    recipient_email = (organisation.public_email or "").strip()
    try:
        validate_email(recipient_email)
    except ValidationError:
        messages.error(
            request,
            "A valid recipient email is required before a draft can be created.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    if Opportunity.objects.filter(
        content_type=content_type,
        object_id=object_id,
        status="do_not_contact",
    ).exists():
        messages.error(
            request,
            (
                "A manual email draft cannot be created because "
                "this organisation is marked Do Not Contact."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    active_draft = (
        EmailDraft.objects.filter(
            opportunity__content_type=content_type,
            opportunity__object_id=object_id,
            workflow_status__in=[
                "draft",
                "awaiting_approval",
                "changes_requested",
                "approved",
                "sending",
                "send_failed",
            ],
        )
        .order_by("-created_at")
        .first()
    )

    if active_draft:
        messages.warning(
            request,
            (
                "An active email draft already exists for this organisation. "
                "Please review the existing draft instead of creating another."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    subject = request.POST.get("subject", "").strip()
    body = request.POST.get("body", "").strip()
    outreach_purpose = request.POST.get("outreach_purpose", "").strip()

    if not subject or not body or not outreach_purpose:
        messages.error(
            request,
            "Subject, email body, and outreach purpose are required.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    latest_opportunity = (
        Opportunity.objects.filter(
            content_type=content_type,
            object_id=object_id,
        )
        .order_by("-date_created")
        .first()
    )

    if latest_opportunity is None:
        latest_opportunity = Opportunity.objects.create(
            content_type=content_type,
            object_id=object_id,
            status="not_yet_contacted",
        )

    EmailDraft.objects.create(
        opportunity=latest_opportunity,
        recipient_email=recipient_email,
        subject=subject,
        body=body,
        outreach_purpose=outreach_purpose,
        workflow_status="draft",
        generation_status="success",
        requested_by=request.user,
        trigger_source="manual_draft",
    )

    messages.success(
        request,
        (
            "Manual email draft created successfully. "
            "Review it before submitting for approval."
        ),
    )
    return redirect(
        "organisation_detail",
        content_type_id=content_type_id,
        object_id=object_id,
    )

@login_required
@require_POST
def update_email_draft(request, draft_id):

    if not request.user.has_perm(
        "outreach.generate_emaildraft"
    ):
        messages.error(
            request,
            "You do not have permission to edit email drafts.",
        )
        return redirect("outreach_dashboard")

    # Used initially so we have a safe redirect target.
    draft = get_object_or_404(
        EmailDraft,
        draft_id=draft_id,
    )

    denied = _deny_unless_draft_owner(request, draft)
    if denied:
        return denied

    redirect_kwargs = {
        "content_type_id": draft.opportunity.content_type_id,
        "object_id": draft.opportunity.object_id,
    }

    # ---------------------------------------------------------
    # Version supplied by the page the user originally opened.
    # ---------------------------------------------------------
    posted_version = request.POST.get(
        "version",
        "",
    ).strip()

    try:
        posted_version = int(posted_version)

    except (TypeError, ValueError):
        messages.error(
            request,
            (
                "The draft version could not be verified. "
                "Please reload the page and try again."
            ),
        )

        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    subject = request.POST.get(
        "subject",
        "",
    ).strip()

    body = request.POST.get(
        "body",
        "",
    ).strip()

    if not subject or not body:
        messages.error(
            request,
            "Subject and email body are required.",
        )

        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    # ---------------------------------------------------------
    # Lock the draft while checking and saving.
    # This prevents two saves being processed simultaneously.
    # ---------------------------------------------------------
    with transaction.atomic():

        # Take the write lock first (effective on SQLite, where
        # select_for_update is a no-op), so an edit cannot interleave
        # with a send claim and overwrite the Sending status.
        EmailDraft.objects.filter(
            pk=draft.pk,
        ).update(version=F("version"))

        locked_draft = (
            EmailDraft.objects
            .select_for_update()
            .select_related(
                "opportunity",
                "opportunity__content_type",
                "template",
            )
            .get(pk=draft.pk)
        )

        opportunity = locked_draft.opportunity
        organisation = opportunity.organisation

        if organisation is None:
            raise Http404("Organisation not found.")

        # -----------------------------------------------------
        # Concurrent edit protection
        # -----------------------------------------------------
        if posted_version != locked_draft.version:

            messages.error(
                request,
                (
                    "This draft has been changed by another user "
                    "since you opened it. Your changes were not saved. "
                    "The latest version has been loaded; please review "
                    "it before editing again."
                ),
            )

            return redirect(
                "organisation_detail",
                content_type_id=opportunity.content_type_id,
                object_id=opportunity.object_id,
            )

        # -----------------------------------------------------
        # Current recipient email must still be valid
        # -----------------------------------------------------
        current_recipient_email = (
            getattr(
                organisation,
                "public_email",
                "",
            )
            or ""
        ).strip()

        try:
            validate_email(
                current_recipient_email
            )

        except ValidationError:
            messages.error(
                request,
                (
                    "The organisation does not currently have "
                    "a valid public email address."
                ),
            )

            return redirect(
                "organisation_detail",
                content_type_id=opportunity.content_type_id,
                object_id=opportunity.object_id,
            )

        # -----------------------------------------------------
        # Editable workflow states
        # -----------------------------------------------------
        if locked_draft.workflow_status not in {
            "draft",
            "changes_requested",
            "approved",
        }:
            messages.error(
                request,
                (
                    "This email draft cannot be edited "
                    "in its current status."
                ),
            )

            return redirect(
                "organisation_detail",
                content_type_id=opportunity.content_type_id,
                object_id=opportunity.object_id,
            )

        signature = (
            locked_draft.template.signature
            if locked_draft.template
            else ""
        )

        is_incomplete, validation_issues = (
            validate_generated_email(
                subject,
                body,
                signature or "",
            )
        )

        # -----------------------------------------------------
        # Preserve current workflow state for audit history
        # -----------------------------------------------------
        old_status = locked_draft.workflow_status

        # Changes Requested and Approved drafts return to Draft
        # when edited.
        if locked_draft.workflow_status in {
            "changes_requested",
            "approved",
        }:
            locked_draft.workflow_status = "draft"

        # Any previous approval becomes invalid after editing.
        locked_draft.approved_by = None
        locked_draft.approved_at = None
        locked_draft.approved_version = None

        # -----------------------------------------------------
        # Save current recipient snapshot and edited content
        # -----------------------------------------------------
        locked_draft.recipient_email = (
            current_recipient_email
        )

        locked_draft.subject = subject
        locked_draft.body = body
        locked_draft.is_incomplete = is_incomplete

        locked_draft.validation_issues = "\n".join(
            validation_issues
        )

        locked_draft.last_edited_by = request.user

        # Increment only after the concurrency check succeeds.
        locked_draft.version += 1

        locked_draft.save(
            update_fields=[
                "recipient_email",
                "subject",
                "body",
                "is_incomplete",
                "validation_issues",
                "workflow_status",
                "approved_by",
                "approved_at",
                "approved_version",
                "last_edited_by",
                "version",
                "updated_at",
            ]
        )

        # -----------------------------------------------------
        # Permanent workflow history
        # -----------------------------------------------------
        if old_status == "approved":

            record_email_draft_history(
                draft=locked_draft,
                action="approval_invalidated",
                performed_by=request.user,
                from_status="approved",
                to_status="draft",
                reason=(
                    "Approved draft was edited and "
                    "requires reapproval."
                ),
            )

        else:

            record_email_draft_history(
                draft=locked_draft,
                action="edited",
                performed_by=request.user,
                from_status=old_status,
                to_status=locked_draft.workflow_status,
            )

        saved_is_incomplete = (
            locked_draft.is_incomplete
        )

    # Transaction/row lock released here.

    if saved_is_incomplete:

        messages.warning(
            request,
            (
                "Draft changes were saved, but validation "
                "issues still remain. Please review the "
                "draft again."
            ),
        )

    else:

        messages.success(
            request,
            "Draft changes saved successfully.",
        )

    return redirect(
        "organisation_detail",
        **redirect_kwargs,
    )
def record_email_draft_history(
    draft,
    action,
    performed_by=None,
    from_status="",
    to_status="",
    reason="",
):
    EmailDraftHistory.objects.create(
        draft=draft,
        action=action,
        from_status=from_status,
        to_status=to_status,
        version=draft.version,
        performed_by=performed_by,
        reason=reason,
        recipient_email_snapshot=draft.recipient_email,
        subject_snapshot=draft.subject,
        body_snapshot=draft.body,
    )

def _deny_unless_draft_owner(request, draft):
    """
    Staff may change only drafts they own (created by them or assigned to
    them); Admins may change any draft. Returns a redirect when denied.
    """
    if draft.user_can_modify(request.user):
        return None

    messages.error(
        request,
        "You can only change drafts you created or that are assigned "
        "to you.",
    )

    return redirect(
        "organisation_detail",
        content_type_id=draft.opportunity.content_type_id,
        object_id=draft.opportunity.object_id,
    )


def serialised_draft_transition(view):
    """
    Run a workflow transition inside one transaction, holding a write
    lock on the draft first, so competing transitions are serialised.

    The no-op write (version = version) takes SQLite's database write
    lock and a row lock on PostgreSQL/MySQL; select_for_update then
    adds the explicit row lock where the database supports it. State
    checks, the state change and its history record all happen inside
    this transaction. Never wrap an SMTP call in this decorator.
    """

    @wraps(view)
    def wrapper(request, draft_id, *args, **kwargs):
        with transaction.atomic():
            locked = EmailDraft.objects.filter(
                draft_id=draft_id,
            ).update(version=F("version"))

            if locked:
                (
                    EmailDraft.objects
                    .select_for_update()
                    .get(draft_id=draft_id)
                )

            return view(request, draft_id, *args, **kwargs)

    return wrapper


def _viewed_version_error(request, draft):
    """
    The approver must decide on the version they actually saw.
    Returns an error message, or None when the version matches.
    """
    posted = request.POST.get("version", "").strip()

    try:
        posted_version = int(posted)
    except (TypeError, ValueError):
        return (
            "The draft version could not be verified. Please reload "
            "the page and review the latest version."
        )

    if posted_version != draft.version:
        return (
            "This draft has changed since you opened it. Please reload "
            "the page and review the latest version before deciding."
        )

    return None


def _record_blocked_do_not_contact(draft, user, stage):
    record_email_draft_history(
        draft=draft,
        action="blocked_do_not_contact",
        performed_by=user,
        from_status=draft.workflow_status,
        to_status=draft.workflow_status,
        reason=(
            f"{stage} blocked: the organisation is marked "
            "Do Not Contact."
        ),
    )


# Only these outcomes establish that the message was NOT delivered
# (refused before or at submission, or never connected). Anything
# else - timeouts, dropped connections, TLS faults mid-stream and any
# unclassified exception - may have been delivered, so it is held in
# Sending for manual reconciliation and can never be retried
# automatically.
#
# A bare RuntimeError is NOT in this list: only EmailNotSentError,
# raised below when the backend explicitly reports it sent nothing
# (sent_count == 0), is a confirmed non-delivery.
class EmailNotSentError(Exception):
    """The mail backend explicitly reported that nothing was sent."""


KNOWN_NON_DELIVERY_EXCEPTIONS = (
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPConnectError,
    smtplib.SMTPHeloError,
    smtplib.SMTPNotSupportedError,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPDataError,
    ssl.SSLCertVerificationError,
    ConnectionRefusedError,
    socket.gaierror,
    EmailNotSentError,
)


@login_required
@require_POST
@serialised_draft_transition
def submit_email_draft_for_review(request, draft_id):
    if not request.user.has_perm("outreach.generate_emaildraft"):
        messages.error(
            request,
            "You do not have permission to submit email drafts.",
        )
        return redirect("outreach_dashboard")

    draft = get_object_or_404(EmailDraft, draft_id=draft_id)

    denied = _deny_unless_draft_owner(request, draft)
    if denied:
        return denied
    opportunity = draft.opportunity
    organisation = opportunity.organisation

    if organisation is None:
        raise Http404("Organisation not found.")

    if organisation.is_archived:
        messages.error(
            request,
            "This organisation is archived and cannot be contacted.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )
    if organisation.contact_status != "not_yet_contacted":
        messages.error(
            request,
            "This organisation has already been contacted.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    if Opportunity.objects.filter(
        content_type=opportunity.content_type,
        object_id=opportunity.object_id,
        status="do_not_contact",
    ).exists():
        _record_blocked_do_not_contact(
            draft,
            request.user,
            "Submission",
        )
        messages.error(
            request,
            "This organisation is marked Do Not Contact.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    if draft.workflow_status != "draft":
        messages.error(
            request,
            "Only drafts can be submitted for approval.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    if draft.is_incomplete:
        messages.error(
            request,
            (
                "This draft has validation issues and cannot be submitted for "
                "approval yet. Please review and edit it first."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    if not draft.subject.strip() or not draft.body.strip():
        messages.error(
            request,
            "Subject and email body are required before submission.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    unresolved_placeholders = find_unresolved_placeholders(
        draft.subject,
        draft.body,
    )

    if unresolved_placeholders:
        messages.error(
            request,
            (
                "This draft still contains unresolved placeholders: "
                + ", ".join(unresolved_placeholders)
                + ". Please replace them before submitting for approval."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    recipient_email = (draft.recipient_email or "").strip()
    current_email = (getattr(organisation, "public_email", "") or "").strip()

    try:
        validate_email(recipient_email)
    except ValidationError:
        messages.error(
            request,
            "A valid recipient email is required before submission.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    if not current_email or recipient_email.lower() != current_email.lower():
        messages.error(
            request,
            (
                "The organisation email address has changed since this draft "
                "was created. Please create or update the draft before submission."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    old_status = draft.workflow_status

    approver_unavailable = not get_available_approvers().exists()

    draft.workflow_status = "awaiting_approval"
    draft.submitted_at = timezone.now()
    draft.overdue_flagged_at = None
    draft.approver_unavailable = approver_unavailable

    draft.save(
        update_fields=[
            "workflow_status",
            "submitted_at",
            "overdue_flagged_at",
            "approver_unavailable",
            "updated_at",
        ]
    )

    record_email_draft_history(
    draft=draft,
    action="submitted",
    performed_by=request.user,
    from_status=old_status,
    to_status="awaiting_approval",
)

    if approver_unavailable:
        # Stay in Awaiting Approval: never auto-approve or reject.
        record_email_draft_history(
            draft=draft,
            action="no_approver_available",
            performed_by=request.user,
            from_status="awaiting_approval",
            to_status="awaiting_approval",
            reason=(
                "No active user with approval permission is "
                "available. An approver must be assigned."
            ),
        )

        notify_admins(
            "Email draft needs an approver",
            (
                f"Draft {draft.draft_id} was submitted for approval "
                "but no active user holds the approve email draft "
                "permission. Please assign an approver."
            ),
        )

        messages.warning(
            request,
            (
                "Draft submitted, but no approver is currently "
                "available. An administrator has been flagged to "
                "assign one. The draft remains Awaiting Approval."
            ),
        )

    else:
        messages.success(
            request,
            "Draft submitted for approval successfully.",
        )
    return redirect(
        "organisation_detail",
        content_type_id=opportunity.content_type_id,
        object_id=opportunity.object_id,
    )

@login_required
@require_POST
@serialised_draft_transition
def approve_email_draft(request, draft_id):
    if not request.user.has_perm("outreach.approve_emaildraft"):
        messages.error(
            request,
            "You do not have permission to approve email drafts.",
        )
        return redirect("outreach_dashboard")

    draft = get_object_or_404(EmailDraft, draft_id=draft_id)
    opportunity = draft.opportunity
    organisation = opportunity.organisation

    if organisation is None:
        raise Http404("Organisation not found.")

    if draft.workflow_status != "awaiting_approval":
        messages.error(
            request,
            "Only drafts awaiting approval can be approved.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    version_error = _viewed_version_error(request, draft)

    if version_error:
        messages.error(request, version_error)
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    content_problems = []

    if not (draft.subject or "").strip():
        content_problems.append("the subject is missing")

    if not (draft.body or "").strip():
        content_problems.append("the email body is missing")

    unresolved = find_unresolved_placeholders(draft.subject, draft.body)

    if unresolved:
        content_problems.append(
            "it contains unresolved placeholders ("
            + ", ".join(unresolved)
            + ")"
        )

    if draft.is_incomplete:
        content_problems.append(
            "it has unresolved validation issues"
        )

    if content_problems:
        messages.error(
            request,
            (
                "This draft cannot be approved: "
                + "; ".join(content_problems)
                + ". Request changes so it can be corrected."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    if organisation.is_archived:
        messages.error(
            request,
            "This organisation is archived and cannot be contacted.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )
    if organisation.contact_status != "not_yet_contacted":
        messages.error(
            request,
            "This organisation has already been contacted.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    if Opportunity.objects.filter(
        content_type=opportunity.content_type,
        object_id=opportunity.object_id,
        status="do_not_contact",
    ).exists():
        _record_blocked_do_not_contact(
            draft,
            request.user,
            "Approval",
        )
        messages.error(
            request,
            "This organisation is marked Do Not Contact.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    recipient_email = (draft.recipient_email or "").strip()
    current_email = (getattr(organisation, "public_email", "") or "").strip()

    try:
        validate_email(recipient_email)
    except ValidationError:
        messages.error(
            request,
            "The draft recipient email is no longer valid.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    if not current_email or recipient_email.lower() != current_email.lower():
        messages.error(
            request,
            (
                "The organisation email address has changed since this draft "
                "was created. It cannot be approved until the draft is updated."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    old_status = draft.workflow_status

    draft.workflow_status = "approved"
    draft.approver_unavailable = False
    draft.approved_by = request.user
    draft.approved_at = timezone.now()
    draft.approved_version = draft.version

    draft.save(
    update_fields=[
        "workflow_status",
        "approver_unavailable",
        "approved_by",
        "approved_at",
        "approved_version",
        "updated_at",
    ]
)

    record_email_draft_history(
    draft=draft,
    action="approved",
    performed_by=request.user,
    from_status=old_status,
    to_status="approved",
    )

    messages.success(request, "Draft approved successfully.")
    return redirect(
        "organisation_detail",
        content_type_id=opportunity.content_type_id,
        object_id=opportunity.object_id,
    )
@login_required
@require_POST
@serialised_draft_transition
def withdraw_email_draft(request, draft_id):
    if not request.user.has_perm("outreach.generate_emaildraft"):
        messages.error(
            request,
            "You do not have permission to withdraw email drafts.",
        )
        return redirect("outreach_dashboard")

    draft = get_object_or_404(
        EmailDraft,
        draft_id=draft_id,
    )

    denied = _deny_unless_draft_owner(request, draft)
    if denied:
        return denied

    if draft.workflow_status != "awaiting_approval":
        messages.error(
            request,
            "Only drafts awaiting approval can be withdrawn for editing.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    old_status = draft.workflow_status

    draft.workflow_status = "draft"
    draft.approver_unavailable = False
    draft.approved_by = None
    draft.approved_at = None
    draft.approved_version = None

    draft.save(
        update_fields=[
            "workflow_status",
            "approver_unavailable",
            "approved_by",
            "approved_at",
            "approved_version",
            "updated_at",
        ]
    )

    record_email_draft_history(
        draft=draft,
        action="withdrawn",
        performed_by=request.user,
        from_status=old_status,
        to_status="draft",
        reason="Draft withdrawn from approval for further editing.",
    )

    messages.success(
        request,
        "Email draft withdrawn for editing.",
    )

    return redirect(
        "organisation_detail",
        content_type_id=draft.opportunity.content_type_id,
        object_id=draft.opportunity.object_id,
    )

@login_required
@require_POST
@serialised_draft_transition
def reject_email_draft(request, draft_id):
    if not request.user.has_perm("outreach.approve_emaildraft"):
        messages.error(
                request,
    "You do not have permission to request changes to email drafts.",
)
        return redirect("outreach_dashboard")

    draft = get_object_or_404(
        EmailDraft,
        draft_id=draft_id,
    )

    if draft.workflow_status != "awaiting_approval":
        messages.error(
            request,
            "Only drafts awaiting approval can have changes requested.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    version_error = _viewed_version_error(request, draft)

    if version_error:
        messages.error(request, version_error)
        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    rejection_reason = request.POST.get(
        "rejection_reason",
        "",
    ).strip()

    if not rejection_reason:
        messages.error(
            request,
            "Please provide a reason for requesting changes.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    old_status = draft.workflow_status

    draft.workflow_status = "changes_requested"
    draft.rejection_reason = rejection_reason
    draft.approver_unavailable = False
    draft.approved_by = None
    draft.approved_at = None
    draft.approved_version = None

    draft.save(
        update_fields=[
            "workflow_status",
            "rejection_reason",
            "approver_unavailable",
            "approved_by",
            "approved_at",
            "approved_version",
            "updated_at",
        ]
    )

    record_email_draft_history(
        draft=draft,
        action="changes_requested",
        performed_by=request.user,
        from_status=old_status,
        to_status="changes_requested",
        reason=rejection_reason,
    )

    messages.success(
        request,
        "Changes requested successfully.",
    )

    return redirect(
        "organisation_detail",
        content_type_id=draft.opportunity.content_type_id,
        object_id=draft.opportunity.object_id,
    )
@login_required
@require_POST
@serialised_draft_transition
def cancel_email_draft(request, draft_id):
    if not request.user.has_perm(
        "outreach.generate_emaildraft"
    ):
        messages.error(
            request,
            "You do not have permission to cancel email drafts.",
        )
        return redirect("outreach_dashboard")

    draft = get_object_or_404(
        EmailDraft,
        draft_id=draft_id,
    )

    denied = _deny_unless_draft_owner(request, draft)
    if denied:
        return denied

    if draft.workflow_status in {
        "sent",
        "sending",
        "cancelled",
    }:
        messages.error(
            request,
            (
                "This email draft cannot be cancelled "
                "in its current status."
            ),
        )
        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    cancellation_reason = request.POST.get(
        "cancellation_reason",
        "",
    ).strip()

    if not cancellation_reason:
        messages.error(
            request,
            "Please provide a reason for cancelling the draft.",
        )
        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )
    old_status = draft.workflow_status

    draft.workflow_status = "cancelled"
    draft.cancelled_by = request.user
    draft.cancelled_at = timezone.now()
    draft.cancellation_reason = cancellation_reason
    draft.approver_unavailable = False

    # Any previous approval is no longer valid.
    draft.approved_by = None
    draft.approved_at = None
    draft.approved_version = None

    draft.save(
        update_fields=[
            "workflow_status",
            "cancelled_by",
            "cancelled_at",
            "cancellation_reason",
            "approver_unavailable",
            "approved_by",
            "approved_at",
            "approved_version",
            "updated_at",
        ]
    )
    record_email_draft_history(
    draft=draft,
    action="cancelled",
    performed_by=request.user,
    from_status=old_status,
    to_status="cancelled",
    reason=cancellation_reason,
)

    messages.success(
        request,
        "Email draft cancelled successfully.",
    )

    return redirect(
        "organisation_detail",
        content_type_id=draft.opportunity.content_type_id,
        object_id=draft.opportunity.object_id,
    )

@login_required
@require_POST
def mark_email_draft_sent(request, draft_id):
    if not request.user.has_perm("outreach.send_emaildraft"):
        messages.error(
            request,
            "You do not have permission to send email drafts.",
        )
        return redirect("outreach_dashboard")

    draft = get_object_or_404(
        EmailDraft,
        draft_id=draft_id,
    )

    opportunity = draft.opportunity
    model_class = opportunity.content_type.model_class()

    if model_class not in (Bank, Branch, Club):
        raise Http404("Organisation not found.")

    organisation = get_object_or_404(
        model_class,
        pk=opportunity.object_id,
    )

    redirect_kwargs = {
        "content_type_id": opportunity.content_type_id,
        "object_id": opportunity.object_id,
    }

    if organisation.is_archived:
        messages.error(
            request,
            "This organisation is archived and cannot be contacted.",
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )
    if organisation.contact_status != "not_yet_contacted":
        messages.error(
            request,
            "This organisation has already been contacted.",
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    if Opportunity.objects.filter(
        content_type=opportunity.content_type,
        object_id=opportunity.object_id,
        status="do_not_contact",
    ).exists():
        _record_blocked_do_not_contact(
            draft,
            request.user,
            "Sending",
        )
        messages.error(
            request,
            (
                "This organisation is marked Do Not Contact. "
                "The email cannot be sent."
            ),
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    if draft.reconciliation_required:
        messages.error(
            request,
            (
                "This email was already sent but its record needs "
                "reconciliation. It cannot be sent again."
            ),
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    if draft.workflow_status not in {
        "approved",
        "send_failed",
    }:
        messages.error(
            request,
            "Only approved or previously failed email drafts can be sent.",
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    if (
        draft.approved_version is None
        or draft.approved_version != draft.version
    ):
        messages.error(
            request,
            (
                "This draft has changed since approval. "
                "It must be approved again before sending."
            ),
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    recipient_email = (
        draft.recipient_email or ""
    ).strip()

    current_email = (
        organisation.public_email or ""
    ).strip()

    try:
        validate_email(recipient_email)
        validate_email(current_email)
    except ValidationError:
        messages.error(
            request,
            "A valid current recipient email is required before sending.",
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    if recipient_email.lower() != current_email.lower():
        messages.error(
            request,
            (
                "The organisation email address has changed since this draft "
                "was approved. The draft must be reviewed and approved again."
            ),
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    if not draft.subject.strip() or not draft.body.strip():
        messages.error(
            request,
            "The email subject and body are required.",
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    old_status = draft.workflow_status

    # The claim is a short transaction (never held open during SMTP).
    # The conditional UPDATE takes the write lock first; the archive
    # state is then re-read, so an archive that committed after the
    # earlier check still prevents a new send.
    archived_during_claim = False

    with transaction.atomic():
        claimed = EmailDraft.objects.filter(
            pk=draft.pk,
            workflow_status__in=[
                "approved",
                "send_failed",
            ],
            version=draft.approved_version,
        ).update(
            workflow_status="sending",
            send_failure_reason="",
        )

        if claimed == 1 and type(organisation).objects.filter(
            pk=organisation.pk,
            is_archived=True,
        ).exists():
            archived_during_claim = True
            transaction.set_rollback(True)

    if archived_during_claim:
        messages.error(
            request,
            "This organisation is archived and cannot be contacted.",
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    if claimed != 1:
        messages.error(
            request,
            (
                "This email is already being processed or is no longer "
                "eligible to send."
            ),
        )
        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    draft.workflow_status = "sending"
    draft.send_failure_reason = ""

    record_email_draft_history(
        draft=draft,
        action="send_started",
        performed_by=request.user,
        from_status=old_status,
        to_status="sending",
    )

    try:
        email = EmailMessage(
            subject=draft.subject,
            body=draft.body,
            to=[recipient_email],
        )

        sent_count = email.send(
            fail_silently=False,
        )

        if sent_count == 0:
            raise EmailNotSentError(
                "Email backend reported that no message was sent."
            )

        if sent_count != 1:
            # Any other count is not understood: delivery is unknown.
            raise RuntimeError(
                "Email backend returned an unexpected send count "
                f"({sent_count})."
            )

    except KNOWN_NON_DELIVERY_EXCEPTIONS as exc:
        logger.exception(
            "Email send failed for draft %s.",
            draft.draft_id,
        )

        EmailDraft.objects.filter(
            pk=draft.pk,
            workflow_status="sending",
        ).update(
            workflow_status="send_failed",
            send_failure_reason=str(exc),
        )

        draft.workflow_status = "send_failed"
        draft.send_failure_reason = str(exc)

        record_email_draft_history(
            draft=draft,
            action="send_failed",
            performed_by=request.user,
            from_status="sending",
            to_status="send_failed",
            reason=str(exc),
        )

        messages.error(
            request,
            (
                "The email could not be sent. "
                "The organisation remains Not Yet Contacted."
            ),
        )

        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    except Exception as exc:
        # Anything not proven to be a non-delivery is treated as
        # "delivery unknown": the message may have been accepted.
        logger.exception(
            "Email delivery status unknown for draft %s.",
            draft.draft_id,
        )

        unknown_reason = (
            "Delivery status is uncertain "
            f"({type(exc).__name__}). The email may have been "
            "delivered. Manual reconciliation is required before "
            "any further send; do not resend automatically."
        )

        # Stays in "sending" and is flagged, so it can never be
        # claimed for another send.
        EmailDraft.objects.filter(
            pk=draft.pk,
        ).update(
            send_failure_reason=unknown_reason,
            reconciliation_required=True,
        )

        try:
            record_email_draft_history(
                draft=draft,
                action="reconciliation_required",
                performed_by=request.user,
                from_status="sending",
                to_status="sending",
                reason=unknown_reason,
            )
        except Exception:
            logger.critical(
                "Could not record unknown-delivery history for "
                "draft %s. MANUAL REVIEW REQUIRED.",
                draft.draft_id,
                exc_info=True,
            )

        notify_admins(
            "Email delivery status unknown",
            (
                f"Draft {draft.draft_id}: delivery status is "
                "uncertain. Do not resend. Reconcile manually."
            ),
        )

        messages.error(
            request,
            (
                "The email request timed out. Delivery status is uncertain, "
                "so the system will not resend it automatically."
            ),
        )

        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    sent_time = timezone.now()

    # Durable evidence of delivery, written before anything else so
    # that a later failure can never lead to an automatic resend.
    try:
        EmailDraft.objects.filter(
            pk=draft.pk,
        ).update(smtp_confirmed_at=sent_time)
    except Exception:
        logger.critical(
            "Email SENT for draft %s at %s but smtp_confirmed_at "
            "could not be stored.",
            draft.draft_id,
            sent_time.isoformat(),
            exc_info=True,
        )

    try:
        with transaction.atomic():
            locked_draft = (
                EmailDraft.objects
                .select_for_update()
                .get(pk=draft.pk)
            )

            if locked_draft.workflow_status != "sending":
                raise RuntimeError(
                    "Email workflow changed after the send was confirmed."
                )

            locked_draft.workflow_status = "sent"
            locked_draft.sent_by = request.user
            locked_draft.sent_at = sent_time
            locked_draft.send_failure_reason = ""

            locked_draft.save(
                update_fields=[
                    "workflow_status",
                    "sent_by",
                    "sent_at",
                    "send_failure_reason",
                    "updated_at",
                ]
            )

            organisation.contact_status = "contacted"
            organisation.save(
                update_fields=[
                    "contact_status",
                ]
            )

            opportunity.status = "contacted"
            opportunity.date_contacted = sent_time
            opportunity.outreach_method = "email"

            opportunity.save(
                update_fields=[
                    "status",
                    "date_contacted",
                    "outreach_method",
                ]
            )

            record_email_draft_history(
                draft=locked_draft,
                action="sent",
                performed_by=request.user,
                from_status="sending",
                to_status="sent",
            )

    except Exception:
        logger.exception(
            (
                "Email was sent for draft %s "
                "but database finalisation failed."
            ),
            draft.draft_id,
        )

        reconciliation_reason = (
            "The email backend confirmed a send, but the database could "
            "not finalise the outreach record. Reconciliation is required; "
            "do not resend automatically."
        )

        # The draft stays in "sending" (never eligible for send) and is
        # flagged for manual review. The organisation is NOT marked
        # Contacted because the finalisation transaction rolled back.
        try:
            EmailDraft.objects.filter(
                pk=draft.pk,
            ).update(
                send_failure_reason=reconciliation_reason,
                reconciliation_required=True,
                smtp_confirmed_at=sent_time,
            )

            record_email_draft_history(
                draft=draft,
                action="reconciliation_required",
                performed_by=request.user,
                from_status="sending",
                to_status="sending",
                reason=reconciliation_reason,
            )
        except Exception:
            logger.critical(
                "Email SENT for draft %s at %s; reconciliation flag "
                "could not be stored. MANUAL REVIEW REQUIRED.",
                draft.draft_id,
                sent_time.isoformat(),
                exc_info=True,
            )

        notify_admins(
            "Email sent but record needs reconciliation",
            (
                f"Draft {draft.draft_id} was sent but the database "
                "could not be finalised. Do not resend. Reconcile "
                "the record manually."
            ),
        )

        messages.error(
            request,
            (
                "The email was sent, but the outreach record could not be "
                "finalised. Do not resend this email until an administrator "
                "has reconciled the record."
            ),
        )

        return redirect(
            "organisation_detail",
            **redirect_kwargs,
        )

    messages.success(
        request,
        (
            "Email sent successfully. "
            "The organisation is now marked as Contacted."
        ),
    )

    return redirect(
        "organisation_detail",
        **redirect_kwargs,
    )


@login_required
def add_organisation(request):
    """
    Allow an authorised user to manually create a
    Bank, Branch or Club.

    New organisations always start as
    Not Yet Contacted.
    """

    organisation_type = (
        request.POST.get("organisation_type")
        or request.GET.get("type")
        or "bank"
    ).strip().lower()

    form_class = ORGANISATION_FORMS.get(organisation_type)

    if form_class is None:
        raise Http404("Invalid organisation type.")

    permission_name = f"outreach.add_{organisation_type}"

    if not request.user.has_perm(permission_name):
        form = form_class()

        context = {
            "form": form,
            "organisation_type": organisation_type,
            "permission_error": True,
        }

        return render(
            request,
            "outreach/add_organisation.html",
            context,
            status=403,
        )

    duplicate_organisation = None
    likely_duplicate_organisation = None
    created_organisation = None

    duplicate_override_reason = request.POST.get(
        "duplicate_override_reason",
        "",
    ).strip()

    confirm_likely_duplicate = (
        request.POST.get("confirm_likely_duplicate") == "1"
    )

    override_reason_error = None

    if request.method == "POST":
        form = form_class(request.POST)

        if form.is_valid():
            # Exact duplicates are always blocked.
            duplicate_organisation = _find_exact_duplicate(
                organisation_type,
                form.cleaned_data,
            )

            if duplicate_organisation is None:
                # Check for a possible duplicate.
                likely_duplicate_organisation = _find_likely_duplicate(
                    organisation_type,
                    form.cleaned_data,
                )

                can_save = True

                if likely_duplicate_organisation is not None:
                    # Possible duplicate found but user has not confirmed yet.
                    if not confirm_likely_duplicate:
                        can_save = False

                    # User confirmed but did not provide an override reason.
                    elif not duplicate_override_reason:
                        can_save = False
                        override_reason_error = (
                            "Please enter a reason for continuing with this "
                            "possible duplicate."
                        )

                if can_save:
                    try:
                        OrganisationCreationLock.objects.get_or_create(
                            key="add_organisation",
                        )

                        with transaction.atomic():
                            # Take the creation lock first (a write), so
                            # concurrent submissions are serialised and the
                            # re-check below sees any record they created.
                            OrganisationCreationLock.objects.filter(
                                key="add_organisation",
                            ).update(counter=F("counter") + 1)

                            # Check again immediately before saving.
                            duplicate_organisation = _find_exact_duplicate(
                                organisation_type,
                                form.cleaned_data,
                            )

                            if duplicate_organisation is None:
                                organisation = form.save(commit=False)
                                organisation.contact_status = "not_yet_contacted"
                                organisation.created_by = request.user
                                organisation.record_source = "Manual Entry"

                                if (
                                    likely_duplicate_organisation is not None
                                    and confirm_likely_duplicate
                                ):
                                    organisation.duplicate_override_reason = (
                                        duplicate_override_reason
                                    )
                                    organisation.duplicate_override_at = timezone.now()
                                    organisation.duplicate_override_by = request.user
                                    organisation.duplicate_override_match = (
                                        f"{type(likely_duplicate_organisation).__name__}: "
                                        f"{_organisation_name(likely_duplicate_organisation)} "
                                        f"(ID {likely_duplicate_organisation.pk})"
                                    )

                                organisation.save()
                                form.save_m2m()

                                organisation_content_type = (
                                    ContentType.objects.get_for_model(
                                        organisation
                                    )
                                )

                                # "No outcome yet" is represented by an
                                # Opportunity in Not Yet Contacted.
                                Opportunity.objects.create(
                                    content_type=organisation_content_type,
                                    object_id=organisation.pk,
                                    status="not_yet_contacted",
                                    notes=form.cleaned_data.get(
                                        "notes",
                                        "",
                                    ),
                                )

                                contact_name = form.cleaned_data.get(
                                    "contact_name",
                                    "",
                                )
                                contact_role = form.cleaned_data.get(
                                    "contact_role",
                                    "",
                                )

                                if contact_name or contact_role:
                                    Contact.objects.create(
                                        content_type=organisation_content_type,
                                        object_id=organisation.pk,
                                        contact_name=contact_name,
                                        role=contact_role,
                                        email=organisation.public_email,
                                        phone=organisation.public_phone,
                                    )

                                created_organisation = organisation

                    except Exception:
                        logger.exception(
                            "Manual organisation creation failed."
                        )
                        messages.error(
                            request,
                            "The organisation could not be saved. Please try again.",
                        )

                    else:
                        if created_organisation is not None:
                            organisation_name = _organisation_name(
                                created_organisation
                            )

                            messages.success(
                                request,
                                f"{organisation_name} has been added successfully.",
                            )

                            content_type = ContentType.objects.get_for_model(
                                created_organisation
                            )

                            return redirect(
                                "organisation_detail",
                                content_type_id=content_type.id,
                                object_id=created_organisation.pk,
                            )

    else:
        form = form_class()

    context = {
        "form": form,
        "organisation_type": organisation_type,
        "duplicate_organisation": duplicate_organisation,
        "duplicate_content_type_id": (
            ContentType.objects.get_for_model(
                duplicate_organisation
            ).id
            if duplicate_organisation is not None
            else None
        ),
        "likely_duplicate_organisation": likely_duplicate_organisation,
        "likely_duplicate_content_type_id": (
            ContentType.objects.get_for_model(
                likely_duplicate_organisation
            ).id
            if likely_duplicate_organisation is not None
            else None
        ),
        "created_organisation": created_organisation,
        "duplicate_override_reason": duplicate_override_reason,
        "override_reason_error": override_reason_error,
    }

    return render(
        request,
        "outreach/add_organisation.html",
        context,
    )

@login_required
@require_POST
def record_external_outreach(
    request,
    content_type_id,
    object_id,
):
    if not request.user.has_perm(
        "outreach.change_opportunity"
    ):
        messages.error(
            request,
            "You do not have permission to record external outreach.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    content_type = get_object_or_404(
        ContentType,
        pk=content_type_id,
    )

    model_class = content_type.model_class()

    if model_class not in (
        Bank,
        Branch,
        Club,
    ):
        raise Http404(
            "Organisation not found."
        )

    organisation = get_object_or_404(
        model_class,
        pk=object_id,
    )

    outreach_method = request.POST.get(
        "outreach_method",
        "",
    ).strip()

    allowed_methods = {
        "phone",
        "manual_email",
    }

    if outreach_method not in allowed_methods:
        messages.error(
            request,
            "Please select a valid outreach method.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    latest_opportunity = (
        Opportunity.objects.filter(
            content_type=content_type,
            object_id=object_id,
        )
        .order_by("-date_created")
        .first()
    )

    if (
        latest_opportunity
        and latest_opportunity.status == "do_not_contact"
    ):
        messages.error(
            request,
            "This organisation is marked Do Not Contact.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=content_type_id,
            object_id=object_id,
        )

    with transaction.atomic():
        if organisation.contact_status == "contacted":
            latest_opportunity = Opportunity.objects.create(
                content_type=content_type,
                object_id=object_id,
                status="contacted",
                date_contacted=timezone.now(),
                outreach_method=outreach_method,
                notes="Follow-up outreach recorded.",
            )

        elif latest_opportunity is None:
            latest_opportunity = Opportunity.objects.create(
                content_type=content_type,
                object_id=object_id,
                status="contacted",
                date_contacted=timezone.now(),
                outreach_method=outreach_method,
            )

        else:
            latest_opportunity.status = "contacted"
            latest_opportunity.date_contacted = timezone.now()
            latest_opportunity.outreach_method = outreach_method

            latest_opportunity.save(
                update_fields=[
                    "status",
                    "date_contacted",
                    "outreach_method",
                ]
            )

        organisation.contact_status = "contacted"

        organisation.save(
            update_fields=[
                "contact_status",
            ]
        )

    messages.success(
        request,
        "External outreach recorded successfully.",
    )

    return redirect(
        "organisation_detail",
        content_type_id=content_type_id,
        object_id=object_id,
    )
                                
@login_required
@permission_required(
    "outreach.add_bank",
    raise_exception=True,
)
def scrape_organisations(request):
    """
    Run the approved public-data organisation collectors.

    Only runs from a POST request.
    Existing organisations are skipped by the management commands.
    """

    if request.method != "POST":
        return redirect("dashboard")

    output = StringIO()

    try:
        # Community Banks - Victoria
        call_command(
            "scrape_banks",
            region="Victoria",
            stdout=output,
        )

        # Public sports clubs
        call_command(
            "scrape_clubs",
            stdout=output,
        )

    except CommandError as exc:
        messages.error(
            request,
            f"Organisation scraping failed: {exc}",
        )

        return redirect("dashboard")

    except Exception as exc:
        messages.error(
            request,
            f"Unable to complete organisation scraping: {exc}",
        )

        return redirect("dashboard")

    messages.success(
        request,
        "Organisation scraping completed successfully. "
        "New public organisations have been added and "
        "existing records were skipped.",
    )

    return redirect("dashboard")

# ---------------------------------------------------------
# Edit and archive an organisation (Admin only)
# ---------------------------------------------------------

def _get_managed_organisation(request, content_type_id, object_id):
    """
    Resolve the organisation and enforce the Admin-only permission on
    the server. Raises PermissionDenied for users without it.
    """
    content_type = get_object_or_404(ContentType, pk=content_type_id)
    model_class = content_type.model_class()

    if model_class not in (Bank, Branch, Club):
        raise Http404("Organisation not found.")

    if not request.user.has_perm(f"outreach.change_{content_type.model}"):
        raise PermissionDenied

    organisation = get_object_or_404(model_class, pk=object_id)

    return content_type, organisation


@login_required
def edit_organisation(request, content_type_id, object_id):
    content_type, organisation = _get_managed_organisation(
        request,
        content_type_id,
        object_id,
    )

    detail_redirect = redirect(
        "organisation_detail",
        content_type_id=content_type_id,
        object_id=object_id,
    )

    if organisation.is_archived:
        messages.error(
            request,
            "An archived organisation cannot be edited.",
        )
        return detail_redirect

    form_class = ORGANISATION_FORMS[content_type.model]

    def build_form(data=None):
        form = form_class(data, instance=organisation)

        # Contact-person and notes fields exist only for creation.
        for name in list(form.fields):
            if name not in form._meta.fields:
                del form.fields[name]

        return form

    if request.method == "POST":
        form = build_form(request.POST)

        if form.is_valid():
            duplicate = _find_exact_duplicate(
                content_type.model,
                form.cleaned_data,
                exclude=organisation,
            )

            if duplicate is not None:
                form.add_error(
                    None,
                    "Another organisation with the same name and "
                    "location already exists.",
                )
            else:
                model_class = type(organisation)
                field_names = list(form.fields)

                if hasattr(organisation, "last_updated"):
                    field_names.append("last_updated")

                with transaction.atomic():
                    # Take the write lock first, then re-read: a
                    # concurrent archive must not be undone, and a
                    # concurrent contact-status change must not be
                    # overwritten by this (possibly stale) instance.
                    model_class.objects.filter(
                        pk=organisation.pk,
                    ).update(is_archived=F("is_archived"))

                    now_archived = model_class.objects.filter(
                        pk=organisation.pk,
                        is_archived=True,
                    ).exists()

                    if not now_archived:
                        # Only the edited fields are written. Contact
                        # status, archive state, duplicate-override
                        # history and creation details are never touched.
                        # A changed public email invalidates pending
                        # drafts via the model signal.
                        organisation.save(update_fields=field_names)

                if now_archived:
                    messages.error(
                        request,
                        "An archived organisation cannot be edited.",
                    )
                else:
                    messages.success(
                        request,
                        "Organisation updated successfully.",
                    )

                return detail_redirect
    else:
        form = build_form()

    return render(
        request,
        "outreach/edit_organisation.html",
        {
            "form": form,
            "organisation": organisation,
            "content_type_id": content_type_id,
            "object_id": object_id,
        },
    )


@login_required
@require_POST
def archive_organisation(request, content_type_id, object_id):
    content_type, organisation = _get_managed_organisation(
        request,
        content_type_id,
        object_id,
    )

    with transaction.atomic():
        updated = type(organisation).objects.filter(
            pk=organisation.pk,
            is_archived=False,
        ).update(
            is_archived=True,
            archived_at=timezone.now(),
            archived_by=request.user,
        )

    if updated:
        messages.success(request, "Organisation archived.")
    else:
        messages.error(request, "This organisation is already archived.")

    return redirect(
        "organisation_detail",
        content_type_id=content_type_id,
        object_id=object_id,
    )
