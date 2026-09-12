from django.urls import path

from . import views


urlpatterns = [
    path(
        "banks/",
        views.bank_list,
        name="bank_list",
    ),
    path(
        "dashboard/",
        views.dashboard_view,
        name="outreach_dashboard",
    ),
    path(
        "organisations/add/",
        views.add_organisation,
        name="add_organisation",
    ),
    path(
        "organisation/<int:content_type_id>/<int:object_id>/",
        views.organisation_detail,
        name="organisation_detail",
    ),
    path(
        "opportunities/<int:opportunity_id>/positive-response/",
        views.record_positive_response_api,
        name="record_positive_response_api",
    ),
]