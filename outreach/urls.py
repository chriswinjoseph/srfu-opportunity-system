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
        "api/organisations/",
        views.organisation_list_api,
        name="organisation_list_api",
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
        "organisation/<int:content_type_id>/<int:object_id>/generate-draft/",
        views.generate_email_draft,
        name="generate_email_draft",
    ),

    path(
        "email-draft/<uuid:draft_id>/update/",
        views.update_email_draft,
        name="update_email_draft",
    ),

    path(
        "email-draft/<uuid:draft_id>/submit-for-review/",
        views.submit_email_draft_for_review,
        name="submit_email_draft_for_review",
    ),

    path(
        "email-draft/<uuid:draft_id>/approve/",
        views.approve_email_draft,
        name="approve_email_draft",
    ),

    path(
        "email-draft/<uuid:draft_id>/reject/",
        views.reject_email_draft,
        name="reject_email_draft",
    ),

    path(
        "opportunities/<int:opportunity_id>/positive-response/",
        views.record_positive_response_api,
        name="record_positive_response_api",
    ),
]