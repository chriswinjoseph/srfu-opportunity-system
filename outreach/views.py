from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import BankForm, BranchForm, ClubForm
from .models import Bank, Branch, Club, Opportunity
from .status_transitions import (
    InvalidStatusTransition,
    record_positive_response,
)


CONTACT_STATUS_LABELS = {
    "not_yet_contacted": "Not Yet Contacted",
    "contacted": "Contacted",
}


OPPORTUNITY_OUTCOME_LABELS = {
    "interested": "Interested",
    "not_interested": "Not Interested",
    "do_not_contact": "Do Not Contact",
}


@login_required
def bank_list(request):
    banks = Bank.objects.all().order_by("bank_name")

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

    Contact status and opportunity outcome are kept separate. A response
    outcome on a Not Yet Contacted organisation is flagged for review.
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
        "region": getattr(org, "region", "") or "",
        "email": getattr(org, "public_email", "") or "",
        "phone": getattr(org, "public_phone", "") or "",
        "status": org.contact_status,
        "outcome_status": outcome_status,
        "status_conflict": status_conflict,
        "status_label": status_label,
    }


def _get_all_organisations(search="", org_type="", region=""):
    """
    Fetch Banks, Branches and Clubs, apply filters and combine them
    into one dashboard list.
    """
    banks = Bank.objects.all()
    branches = Branch.objects.all()
    clubs = Club.objects.all()

    if search:
        banks = banks.filter(
            bank_name__icontains=search,
        )
        branches = branches.filter(
            branch_name__icontains=search,
        )
        clubs = clubs.filter(
            club_name__icontains=search,
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

    rows.sort(key=lambda row: row["name"].lower())

    return rows


@login_required
def dashboard_view(request):
    search = request.GET.get("q", "").strip()
    org_type = request.GET.get("type", "")
    region = request.GET.get("region", "").strip()

    all_rows = _get_all_organisations(
        search=search,
        org_type=org_type,
        region=region,
    )

    not_yet = [
        row
        for row in all_rows
        if row["status"] == "not_yet_contacted"
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
        request.GET.get("not_yet_page")
    )

    contacted_page = Paginator(
        contacted,
        5,
    ).get_page(
        request.GET.get("contacted_page")
    )

    total = len(all_rows)
    contacted_count = len(contacted)

    percent_contacted = (
        round((contacted_count / total) * 100)
        if total
        else 0
    )

    # Count only outcomes that agree with the organisation being contacted.
    status_breakdown = {
        label: len(
            [
                row
                for row in all_rows
                if (
                    row["outcome_status"] == status
                    and not row["status_conflict"]
                )
            ]
        )
        for status, label
        in OPPORTUNITY_OUTCOME_LABELS.items()
    }

    status_breakdown["Needs Review"] = len(
        [
            row
            for row in all_rows
            if row["status_conflict"]
        ]
    )

    context = {
        "not_yet_page": not_yet_page,
        "contacted_page": contacted_page,
        "percent_contacted": percent_contacted,
        "not_yet_count": len(not_yet),
        "contacted_count": contacted_count,
        "status_breakdown": status_breakdown,
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

    if model_class not in (Bank, Branch, Club):
        raise Http404("Organisation not found.")

    org = get_object_or_404(
        model_class,
        pk=object_id,
    )

    opportunities = Opportunity.objects.filter(
        content_type=content_type,
        object_id=object_id,
    ).order_by("-date_created")

    context = {
        "org": org,
        "org_type": content_type.model,
        "opportunities": opportunities,
    }

    return render(
        request,
        "outreach/organisation_detail.html",
        context,
    )


ORGANISATION_FORMS = {
    "bank": BankForm,
    "branch": BranchForm,
    "club": ClubForm,
}


@login_required
def add_organisation(request):
    """
    Allow a logged-in user to add a Bank, Branch or Club.

    New organisations start as Not Yet Contacted.
    """
    organisation_type = (
        request.POST.get("organisation_type")
        or request.GET.get("type")
        or "bank"
    ).lower()

    form_class = ORGANISATION_FORMS.get(
        organisation_type
    )

    if form_class is None:
        raise Http404("Invalid organisation type.")

    if request.method == "POST":
        form = form_class(request.POST)

        if form.is_valid():
            organisation = form.save()

            content_type = ContentType.objects.get_for_model(
                organisation
            )

            return redirect(
                "organisation_detail",
                content_type_id=content_type.pk,
                object_id=organisation.pk,
            )
    else:
        form = form_class()

    context = {
        "form": form,
        "organisation_type": organisation_type,
    }

    return render(
        request,
        "outreach/add_organisation.html",
        context,
    )