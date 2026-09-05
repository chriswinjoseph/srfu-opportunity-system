from django.urls import path
from . import views

urlpatterns = [
    path("banks/", views.bank_list, name="bank_list"),
]