from django.contrib.auth.decorators import login_required
from django.db import models
from django.shortcuts import render

from .models import Bank, Club


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