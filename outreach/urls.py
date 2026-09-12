from django.urls import path
from . import views

urlpatterns = [
    path("banks/", views.bank_list, name="bank_list"),
    path("dashboard/", views.dashboard_view, name="outreach_dashboard"),
    path(
        "organisation/<int:content_type_id>/<int:object_id>/",
        views.organisation_detail,
        name="organisation_detail",
    ),
]