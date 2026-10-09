from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, UserActivity
from .roles import ROLE_ADMIN


def _admin_site_allowed(request):
    # Django admin access needs the Django staff flag AND the application
    # Admin role, so a demoted user cannot keep using the admin site.
    user = request.user
    return bool(
        user.is_active
        and user.is_staff
        and user.role == ROLE_ADMIN
    )


admin.site.has_permission = _admin_site_allowed


class UserAdmin(BaseUserAdmin):
    """
    Read-only view of accounts. Roles, status, invitations and
    permissions are managed through User Management, which enforces the
    last-Admin, self-change, audit and session rules. Allowing edits here
    would bypass all of them.
    """

    ordering = ["email"]
    list_display = [
        "email",
        "first_name",
        "last_name",
        "role",
        "is_active",
        "invitation_pending",
        "date_joined",
    ]
    list_filter = ["role", "is_active", "invitation_pending"]
    search_fields = ["email", "first_name", "last_name"]
    actions = None

    fieldsets = (
        (None, {"fields": ("email",)}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        (
            "Access",
            {
                "fields": (
                    "role",
                    "is_active",
                    "invitation_pending",
                    "is_staff",
                    "is_superuser",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    readonly_fields = [
        "email",
        "first_name",
        "last_name",
        "role",
        "is_active",
        "invitation_pending",
        "is_staff",
        "is_superuser",
        "last_login",
        "date_joined",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "actor_email", "target_email"]
    list_filter = ["action"]
    search_fields = ["actor_email", "target_email"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(User, UserAdmin)
