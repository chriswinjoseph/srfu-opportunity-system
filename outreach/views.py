from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import models
from django.shortcuts import render, get_object_or_404

from .models import Bank, Branch, Club, Opportunity


@login_required
def bank_list(request):
    banks = Bank.objects.all().order_by("bank_name")
    return render(request, "outreach/bank_list.html", {"banks": banks})


def get_supported_clubs(bank):
    """
    Given a Bank, return every Club it supports - either directly,
    or through one of its branches.
    """
    return Club.objects.filter(
        models.Q(supported_by_bank=bank) | models.Q(supported_by_branch__bank=bank)
    ).distinct().order_by("club_name")


def record_positive_response(opportunity):
    """
    THE TRIGGER + STATUS UPDATE for "bank responds positively -> surface
    supported clubs". See outreach/admin.py's mark_as_interested action
    for how this currently gets called (a stand-in for the real
    dashboard button, until UX delivers that design).
    """
    opportunity.status = "interested"
    opportunity.save()

    org = opportunity.organisation

    if isinstance(org, Bank):
        bank = org
    elif isinstance(org, Branch):
        bank = org.bank
    else:
        return Club.objects.none()

    return get_supported_clubs(bank)


STATUS_LABELS = dict(
    not_yet_contacted="Not Yet Contacted",
    contacted="Contacted",
    interested="Interested",
    not_interested="Not Interested",
    do_not_contact="Do Not Contact",
)


def _org_to_row(org, org_type):
    """Turn a Bank/Branch/Club model instance into a plain dict the
    dashboard template can display the same way regardless of type."""
    content_type = ContentType.objects.get_for_model(org)
    name = getattr(org, "bank_name", None) or getattr(org, "branch_name", None) \
        or getattr(org, "club_name", None)
    return {
        "id": org.pk,
        "content_type_id": content_type.pk,
        "name": name,
        "type": org_type,
        "region": getattr(org, "region", "") or "",
        "email": getattr(org, "public_email", "") or "",
        "phone": getattr(org, "public_phone", "") or "",
        "status": org.contact_status,
        "status_label": STATUS_LABELS.get(org.contact_status, org.contact_status),
    }


def _get_all_organisations(search="", org_type="", region=""):
    """Fetch Banks, Branches, and Clubs, apply the same filters to each,
    then combine them into one list of rows."""
    banks = Bank.objects.all()
    branches = Branch.objects.all()
    clubs = Club.objects.all()

    if search:
        banks = banks.filter(bank_name__icontains=search)
        branches = branches.filter(branch_name__icontains=search)
        clubs = clubs.filter(club_name__icontains=search)

    if region:
        banks = banks.filter(region__icontains=region)
        branches = branches.filter(region__icontains=region)
        clubs = clubs.filter(region__icontains=region)

    rows = []
    if org_type in ("", "bank"):
        rows += [_org_to_row(b, "Bank") for b in banks]
    if org_type in ("", "branch"):
        rows += [_org_to_row(b, "Branch") for b in branches]
    if org_type in ("", "club"):
        rows += [_org_to_row(c, "Club") for c in clubs]

    return rows


@login_required
def dashboard_view(request):
    search = request.GET.get("q", "").strip()
    org_type = request.GET.get("type", "")
    region = request.GET.get("region", "")

    all_rows = _get_all_organisations(search=search, org_type=org_type, region=region)

    not_yet = [r for r in all_rows if r["status"] == "not_yet_contacted"]
    contacted = [r for r in all_rows if r["status"] != "not_yet_contacted"]

    not_yet_page = Paginator(not_yet, 5).get_page(request.GET.get("not_yet_page"))
    contacted_page = Paginator(contacted, 5).get_page(request.GET.get("contacted_page"))

    total = len(all_rows)
    contacted_count = len(contacted)
    percent_contacted = round((contacted_count / total) * 100) if total else 0

    status_breakdown = {
        label: len([r for r in all_rows if r["status"] == key])
        for key, label in STATUS_LABELS.items()
        if key != "not_yet_contacted"
    }

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
    return render(request, "outreach/dashboard.html", context)


@login_required
def organisation_detail(request, content_type_id, object_id):
    content_type = get_object_or_404(ContentType, pk=content_type_id)
    org = get_object_or_404(content_type.model_class(), pk=object_id)

    opportunities = Opportunity.objects.filter(
        content_type=content_type, object_id=object_id
    ).order_by("-date_created")

    context = {
        "org": org,
        "org_type": content_type.model,
        "opportunities": opportunities,
    }
    return render(request, "outreach/organisation_detail.html", context)