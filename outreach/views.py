from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Bank


@login_required
def bank_list(request):
    banks = Bank.objects.all().order_by("bank_name")
    return render(request, "outreach/bank_list.html", {"banks": banks})