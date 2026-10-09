from django.contrib.auth import views as auth_views
from django.urls import path

from . import user_views, views

urlpatterns = [
    path("login/", views.EmailLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard_view, name="dashboard"),

    # Admin-only user management
    path("users/", user_views.user_list, name="user_list"),
    path("users/add/", user_views.user_add, name="user_add"),
    path("users/activity/", user_views.user_activity, name="user_activity"),
    path("users/<int:user_id>/", user_views.user_options, name="user_options"),
    path("users/<int:user_id>/role/", user_views.user_role, name="user_role"),
    path("users/<int:user_id>/disable/", user_views.user_disable, name="user_disable"),
    path("users/<int:user_id>/enable/", user_views.user_enable, name="user_enable"),
    path(
        "users/<int:user_id>/resend-invitation/",
        user_views.user_resend_invitation,
        name="user_resend_invitation",
    ),
    path(
        "users/<int:user_id>/reassign-drafts/",
        user_views.user_reassign_drafts,
        name="user_reassign_drafts",
    ),

    path("forgot-password/", views.forgot_password_view, name="forgot_password"),

    # Django's built-in views handle the actual reset-confirm step securely
    # (token validation, expiry, setting the new password).
    path(
        "reset/<uidb64>/<token>/",
        views.PasswordSetupView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
