from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Bank, Club


@login_required
def bank_list(request):
    banks = Bank.objects.all().order_by("bank_name")
    return render(request, "outreach/bank_list.html", {"banks": banks})


def get_supported_clubs(bank):
    """
    Given a Bank, return every Club it currently supports.
    """
    return Club.objects.filter(supported_by_bank=bank).order_by("club_name")