import logging
import hashlib


import re


from datetime import timedelta


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

from django.db.models import Q


from django.http import Http404, JsonResponse


from django.shortcuts import get_object_or_404, redirect, render


from django.utils import timezone


from django.views.decorators.http import require_GET, require_POST


from .services import (
    generate_outreach_email,
    validate_generated_email,
)


from .forms import BankForm, BranchForm, ClubForm


from .models import (
    Bank,
    Branch,
    Club,
    Opportunity,
    EmailDraft,
    EmailGenerationLog,
    EmailTemplate,
)


from .status_transitions import (


    InvalidStatusTransition,


    record_positive_response,


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


    banks = Bank.objects.all().order_by("-date_added", "-id")


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


        "state": getattr(org, "state", "") or "",
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


    banks = Bank.objects.all()


    branches = Branch.objects.all()


    clubs = Club.objects.all()


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


        label: len(


            [


                row


                for row in all_rows


                if (


                    row["outcome_status"]


                    == status


                    and not row[


                        "status_conflict"


                    ]


                )


            ]


        )


        for status, label


        in OPPORTUNITY_OUTCOME_LABELS.items()


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


    }


    return render(


        request,


        "outreach/dashboard.html",


        context,


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

    latest_draft = (
        EmailDraft.objects.filter(
            opportunity__content_type=content_type,
            opportunity__object_id=object_id,
        )
        .order_by("-created_at")
        .first()
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
        "content_type_id": content_type_id,
        "object_id": object_id,
        "latest_draft": latest_draft,
        "active_templates": active_templates,
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


):


    """


    Look for an exact organisation duplicate using


    normalised name and location details.


    """


    if organisation_type == "bank":


        queryset = Bank.objects.all()


        submitted_name = (


            cleaned_data.get(


                "bank_name",


                "",


            )


        )


    elif organisation_type == "branch":


        queryset = Branch.objects.all()


        submitted_name = (


            cleaned_data.get(


                "branch_name",


                "",


            )


        )


    elif organisation_type == "club":


        queryset = Club.objects.all()


        submitted_name = (


            cleaned_data.get(


                "club_name",


                "",


            )


        )


    else:


        return None


    submitted_name = (


        _normalise_duplicate_value(


            submitted_name


        )


    )


    submitted_state = (


        _normalise_duplicate_value(


            cleaned_data.get(


                "state",


                "",


            )


        )


    )


    submitted_region = (


        _normalise_duplicate_value(


            cleaned_data.get(


                "region",


                "",


            )


        )


    )


    submitted_suburb = (


        _normalise_duplicate_value(


            cleaned_data.get(


                "suburb",


                "",


            )


        )


    )


    submitted_postcode = (


        _normalise_duplicate_value(


            cleaned_data.get(


                "postcode",


                "",


            )


        )


    )


    for organisation in queryset:


        existing_name = (


            _normalise_duplicate_value(


                _organisation_name(


                    organisation


                )


            )


        )


        existing_state = (


            _normalise_duplicate_value(


                getattr(


                    organisation,


                    "state",


                    "",


                )


            )


        )


        existing_region = (


            _normalise_duplicate_value(


                getattr(


                    organisation,


                    "region",


                    "",


                )


            )


        )


        existing_suburb = (


            _normalise_duplicate_value(


                getattr(


                    organisation,


                    "suburb",


                    "",


                )


            )


        )


        existing_postcode = (


            _normalise_duplicate_value(


                getattr(


                    organisation,


                    "postcode",


                    "",


                )


            )


        )


        name_matches = (


            existing_name


            == submitted_name


        )


        state_matches = (


            existing_state


            == submitted_state


        )


        region_matches = (


            existing_region


            == submitted_region


            if submitted_region


            else True


        )


        suburb_matches = (


            existing_suburb


            == submitted_suburb


            if submitted_suburb


            else True


        )


        postcode_matches = (


            existing_postcode


            == submitted_postcode


            if submitted_postcode


            else True


        )


        if (


            name_matches


            and state_matches


            and region_matches


            and suburb_matches


            and postcode_matches


        ):


            return organisation


    return None


def _find_likely_duplicate(


    organisation_type,


    cleaned_data,


):


    """


    Find an organisation that may be a duplicate.


    A possible duplicate is detected when:


    - the same public email is used, or


    - the same phone number is used, or


    - the same website is used, or


    - the name is very similar and the location matches.


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


    submitted_phone = _normalise_duplicate_value(


        cleaned_data.get(


            "public_phone",


            "",


        )


    )


    submitted_website = _normalise_duplicate_value(


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


        existing_phone = _normalise_duplicate_value(


            getattr(


                organisation,


                "public_phone",


                "",


            )


        )


        existing_website = _normalise_duplicate_value(


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


            name_similarity >= 0.80


        )


        same_location = (


            (


                bool(submitted_region)


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

    if (
        latest_opportunity
        and latest_opportunity.status == "do_not_contact"
    ):
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

    # If an AI-generated draft already exists,
    # another normal Generate Draft request is blocked.
    if (
        latest_existing_draft
        and not is_regeneration
    ):
        messages.warning(
            request,
            (
                "An AI draft already exists for this organisation. "
                "Please use Regenerate Draft if you want a new version."
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
            validation_issues="\n".join(
                validation_issues
            ),
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
    if not request.user.has_perm(
        "outreach.generate_emaildraft"
    ):
        messages.error(
            request,
            "You do not have permission to create email drafts.",
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

    subject = request.POST.get(
        "subject",
        "",
    ).strip()

    body = request.POST.get(
        "body",
        "",
    ).strip()

    outreach_purpose = request.POST.get(
        "outreach_purpose",
        "",
    ).strip()

    if not subject or not body:
        messages.error(
            request,
            "Subject and email body are required.",
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

    if latest_opportunity is None:
        latest_opportunity = Opportunity.objects.create(
            content_type=content_type,
            object_id=object_id,
            status="not_yet_contacted",
        )

    EmailDraft.objects.create(
        opportunity=latest_opportunity,
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

    draft = get_object_or_404(
        EmailDraft,
        draft_id=draft_id,
    )

    if draft.workflow_status != "draft":
        messages.error(
            request,
            "Only drafts can be edited.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
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
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    signature = ""

    if draft.template:
        signature = draft.template.signature or ""

    is_incomplete, validation_issues = validate_generated_email(
        subject,
        body,
        signature,
    )

    draft.subject = subject
    draft.body = body
    draft.is_incomplete = is_incomplete
    draft.validation_issues = "\n".join(
        validation_issues
    )

    draft.save(
        update_fields=[
            "subject",
            "body",
            "is_incomplete",
            "validation_issues",
            "updated_at",
        ]
    )

    if draft.is_incomplete:
        messages.warning(
            request,
            (
                "Draft changes were saved, but validation issues "
                "still remain. Please review the draft again."
            ),
        )
    else:
        messages.success(
            request,
            "Draft changes saved successfully.",
        )

    return redirect(
        "organisation_detail",
        content_type_id=draft.opportunity.content_type_id,
        object_id=draft.opportunity.object_id,
    )


@login_required
@require_POST
def submit_email_draft_for_review(request, draft_id):

    if not request.user.has_perm(
        "outreach.generate_emaildraft"
    ):
        messages.error(
            request,
            "You do not have permission to submit email drafts.",
        )

        return redirect(
            "outreach_dashboard"
        )

    draft = get_object_or_404(
        EmailDraft,
        draft_id=draft_id,
    )

    # ---------------------------------------------------------
    # Do Not Contact check
    # ---------------------------------------------------------
    if draft.opportunity.status == "do_not_contact":
        messages.error(
            request,
            "This organisation is marked Do Not Contact.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    # ---------------------------------------------------------
    # Only normal drafts can be submitted
    # ---------------------------------------------------------
    if draft.workflow_status != "draft":
        messages.error(
            request,
            "Only drafts can be submitted for approval.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    # ---------------------------------------------------------
    # Block incomplete AI drafts
    # ---------------------------------------------------------
    if draft.is_incomplete:
        messages.error(
            request,
            (
                "This draft has validation issues and cannot be "
                "submitted for approval yet. Please review and edit it first."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    # ---------------------------------------------------------
    # Subject and body must exist
    # ---------------------------------------------------------
    if (
        not draft.subject.strip()
        or not draft.body.strip()
    ):
        messages.error(
            request,
            "Subject and email body are required before submission.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    # ---------------------------------------------------------
    # Submit for approval
    # ---------------------------------------------------------
    draft.workflow_status = "needs_approving"

    draft.save(
        update_fields=[
            "workflow_status",
            "updated_at",
        ]
    )

    messages.success(
        request,
        "Draft submitted for approval successfully.",
    )

    return redirect(
        "organisation_detail",
        content_type_id=draft.opportunity.content_type_id,
        object_id=draft.opportunity.object_id,
    )

@login_required


@require_POST


def approve_email_draft(request, draft_id):


    if not request.user.has_perm(


        "outreach.change_emaildraft"


    ):


        messages.error(


            request,


            "You do not have permission to approve email drafts."


        )


        return redirect("outreach_dashboard")


    draft = get_object_or_404(


        EmailDraft,


        draft_id=draft_id,


    )


    if draft.opportunity.status == "do_not_contact":


        messages.error(


            request,


            "This organisation is marked Do Not Contact."


        )


        return redirect(


            "organisation_detail",


            content_type_id=draft.opportunity.content_type_id,


            object_id=draft.opportunity.object_id,


        )


    if draft.workflow_status != "needs_approving":


        messages.error(


            request,


            "Only drafts awaiting approval can be approved."


        )


        return redirect(


            "organisation_detail",


            content_type_id=draft.opportunity.content_type_id,


            object_id=draft.opportunity.object_id,


        )


    draft.workflow_status = "approved"


    draft.save(


        update_fields=[


            "workflow_status",


            "updated_at",


        ]


    )


    messages.success(


        request,


        "Draft approved successfully."


    )


    return redirect(


        "organisation_detail",


        content_type_id=draft.opportunity.content_type_id,


        object_id=draft.opportunity.object_id,


    )


@login_required
@require_POST
def reject_email_draft(request, draft_id):

    if not request.user.has_perm(
        "outreach.change_emaildraft"
    ):
        messages.error(
            request,
            "You do not have permission to reject email drafts.",
        )
        return redirect("outreach_dashboard")

    draft = get_object_or_404(
        EmailDraft,
        draft_id=draft_id,
    )

    if draft.workflow_status != "needs_approving":
        messages.error(
            request,
            "Only drafts awaiting approval can be rejected.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    rejection_reason = (
        request.POST.get("rejection_reason", "")
        .strip()
    )

    if not rejection_reason:
        messages.error(
            request,
            "Please provide a reason for rejecting this draft.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=draft.opportunity.content_type_id,
            object_id=draft.opportunity.object_id,
        )

    draft.workflow_status = "rejected"
    draft.rejection_reason = rejection_reason

    draft.save(
        update_fields=[
            "workflow_status",
            "rejection_reason",
            "updated_at",
        ]
    )

    messages.success(
        request,
        "Draft rejected successfully.",
    )

    return redirect(
        "organisation_detail",
        content_type_id=draft.opportunity.content_type_id,
        object_id=draft.opportunity.object_id,
    )
@login_required
@require_POST
def mark_email_draft_sent(request, draft_id):

    if not request.user.has_perm(
        "outreach.change_emaildraft"
    ):
        messages.error(
            request,
            "You do not have permission to mark email drafts as sent.",
        )

        return redirect(
            "outreach_dashboard"
        )

    draft = get_object_or_404(
        EmailDraft,
        draft_id=draft_id,
    )

    opportunity = draft.opportunity

    # ---------------------------------------------------------
    # Do Not Contact check
    # ---------------------------------------------------------

    if opportunity.status == "do_not_contact":
        messages.error(
            request,
            (
                "This organisation is marked Do Not Contact. "
                "The email cannot be marked as sent."
            ),
        )

        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    # ---------------------------------------------------------
    # Only an approved draft can be marked as sent
    # ---------------------------------------------------------

    if draft.workflow_status != "approved":
        messages.error(
            request,
            "Only approved drafts can be marked as sent.",
        )

        return redirect(
            "organisation_detail",
            content_type_id=opportunity.content_type_id,
            object_id=opportunity.object_id,
        )

    # ---------------------------------------------------------
    # Find the organisation
    # ---------------------------------------------------------

    model_class = (
        opportunity.content_type.model_class()
    )

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
        pk=opportunity.object_id,
    )

    # ---------------------------------------------------------
    # Mark sent + update contact status
    # Keep all related updates together
    # ---------------------------------------------------------

    with transaction.atomic():

        draft.workflow_status = "sent"

        draft.save(
            update_fields=[
                "workflow_status",
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

        opportunity.save(
            update_fields=[
                "status",
            ]
        )

    messages.success(
        request,
        (
            "Email draft marked as sent successfully. "
            "The organisation is now marked as Contacted."
        ),
    )

    return redirect(
        "organisation_detail",
        content_type_id=opportunity.content_type_id,
        object_id=opportunity.object_id,
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


    form_class = ORGANISATION_FORMS.get(


        organisation_type


    )


    if form_class is None:


        raise Http404(


            "Invalid organisation type."


        )


    permission_name = (


        f"outreach.add_{organisation_type}"


    )


    if not request.user.has_perm(


        permission_name


    ):


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


    duplicate_override_reason = (


        request.POST.get(


            "duplicate_override_reason",


            ""


        ).strip()


    )


    confirm_likely_duplicate = (


        request.POST.get(


            "confirm_likely_duplicate"


        )


        == "1"


    )


    override_reason_error = None


    if request.method == "POST":


        form = form_class(


            request.POST


        )


        if form.is_valid():


            # Exact duplicates are always blocked.


            duplicate_organisation = (


                _find_exact_duplicate(


                    organisation_type,


                    form.cleaned_data,


                )


            )


            if duplicate_organisation is None:


                # Always check for a possible duplicate.


                likely_duplicate_organisation = (


                    _find_likely_duplicate(


                        organisation_type,


                        form.cleaned_data,


                    )


                )


                can_save = True


                # Possible duplicate has been found.


                if likely_duplicate_organisation is not None:


                    # User has not confirmed yet.


                    if not confirm_likely_duplicate:


                        can_save = False


                    # User clicked Continue Anyway


                    # but did not provide a reason.


                    elif not duplicate_override_reason:


                        can_save = False


                        override_reason_error = (


                            "Please enter a reason for "


                            "continuing with this "


                            "possible duplicate."


                        )


                if can_save:


                    try:


                        with transaction.atomic():


                            # Check again immediately


                            # before saving.


                            duplicate_organisation = (


                                _find_exact_duplicate(


                                    organisation_type,


                                    form.cleaned_data,


                                )


                            )


                            if duplicate_organisation is None:


                                organisation = (


                                    form.save(


                                        commit=False


                                    )


                                )


                                # Default organisation status.


                                organisation.contact_status = (


                                    "not_yet_contacted"


                                )


                                # Creation audit information.


                                organisation.created_by = (


                                    request.user


                                )


                                organisation.record_source = (


                                    "Manual Entry"


                                )


                                # Record duplicate override audit


                                # only when an actual likely


                                # duplicate was found.


                                if (


                                    likely_duplicate_organisation


                                    is not None


                                    and confirm_likely_duplicate


                                ):


                                    organisation.duplicate_override_reason = (


                                        duplicate_override_reason


                                    )


                                    organisation.duplicate_override_at = (


                                        timezone.now()


                                    )


                                    organisation.duplicate_override_by = (


                                        request.user


                                    )


                                organisation.save()


                                form.save_m2m()


                                created_organisation = (


                                    organisation


                                )


                    except Exception:


                        messages.error(


                            request,


                            (


                                "The organisation could not "


                                "be saved. Please try again."


                            ),


                        )


                    else:


                        if created_organisation is not None:


                            messages.success(


                                request,


                                (


                                    "Organisation has been "


                                    "added successfully."


                                ),


                            )


                            form = form_class()


                            # Remove warning after a


                            # successful override/save.


                            likely_duplicate_organisation = None


                            duplicate_override_reason = ""


    else:


        form = form_class()


    context = {


        "form": form,


        "organisation_type": organisation_type,


        "duplicate_organisation": (


            duplicate_organisation


        ),


        "likely_duplicate_organisation": (


            likely_duplicate_organisation


        ),


        "created_organisation": (


            created_organisation


        ),


        "duplicate_override_reason": (


            duplicate_override_reason


        ),


        "override_reason_error": (


            override_reason_error


        ),


    }


    return render(


        request,


        "outreach/add_organisation.html",


        context,


    )