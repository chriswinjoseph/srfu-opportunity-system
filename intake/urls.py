from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="intake_home"),
    path("import/", views.import_upload, name="intake_import"),
    path("import/template/", views.import_template, name="intake_import_template"),
    path("import/example/", views.import_example, name="intake_import_example"),
    path("runs/<int:run_id>/", views.run_detail, name="intake_run"),
    path("runs/<int:run_id>/confirm/", views.run_confirm, name="intake_confirm"),
    path("runs/<int:run_id>/status/", views.run_status, name="intake_run_status"),
    path("reviews/", views.review_list, name="intake_reviews"),
    path("reviews/<int:review_id>/", views.review_detail, name="intake_review"),
    path("changes/", views.change_list, name="intake_changes"),
    path("changes/<int:change_id>/decide/", views.change_decide, name="intake_change_decide"),
    path("scraper/", views.scraper_page, name="intake_scraper"),
]
