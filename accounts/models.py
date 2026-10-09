from django.contrib.auth.base_user import BaseUserManager, AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.conf import settings
from django.db import models
from django.utils import timezone

from .roles import (
    OUTREACH_APP_LABEL,
    ROLE_ADMIN,
    ROLE_CHOICES,
    ROLE_STAFF,
    role_has_outreach_permission,
)


class UserManager(BaseUserManager):
    """Custom manager since our User model logs in with email, not username."""

    def create_user(self, email, first_name, last_name, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        if not first_name or not last_name:
            raise ValueError("Users must have a first and last name")

        email = self.normalize_email(email)
        user = self.model(email=email, first_name=first_name, last_name=last_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, first_name, last_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", ROLE_ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, first_name, last_name, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user. Login is by email (per Sprint 1 spec), not username.
    is_staff/is_superuser reused from PermissionsMixin for later role needs
    (e.g. "authorised SRFU user" for outreach approval in later sprints) —
    avoids a migration headache down the line.
    """

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # Application role: the source of truth for outreach permissions.
    # Django's is_staff only controls access to the Django admin site.
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default=ROLE_STAFF,
    )

    # True from invitation until the user sets their own password.
    # Distinct from a disabled account (is_active=False).
    invitation_pending = models.BooleanField(default=False)
    invitation_sent_at = models.DateTimeField(null=True, blank=True)

    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return self.email

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name

    @property
    def is_app_admin(self):
        return self.is_active and self.role == ROLE_ADMIN

    @property
    def account_state(self):
        if not self.is_active:
            return "disabled"
        if self.invitation_pending:
            return "pending"
        return "active"

    def has_perm(self, perm, obj=None):
        # Outreach permissions come from the role only. This bypasses the
        # superuser shortcut, groups and per-user permissions.
        if perm.split(".", 1)[0] == OUTREACH_APP_LABEL:
            return self.is_active and role_has_outreach_permission(
                self.role, perm
            )
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label):
        if app_label == OUTREACH_APP_LABEL:
            if not self.is_active:
                return False
            return self.role in (ROLE_ADMIN, ROLE_STAFF)
        return super().has_module_perms(app_label)


class UserActivity(models.Model):
    """Append-only audit trail of account management actions."""

    ACTION_CHOICES = [
        ("user_created", "User created"),
        ("first_admin_created", "First Admin created"),
        ("invitation_sent", "Invitation sent"),
        ("invitation_failed", "Invitation delivery failed"),
        ("invitation_resent", "Invitation resent"),
        ("invitation_accepted", "Password set from invitation"),
        ("role_changed", "Role changed"),
        ("account_disabled", "Account disabled"),
        ("account_enabled", "Account re-enabled"),
        ("drafts_reassigned", "Drafts reassigned"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activities_performed",
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activities_received",
    )
    actor_email = models.EmailField(blank=True)
    target_email = models.EmailField(blank=True)
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    previous_value = models.CharField(max_length=100, blank=True)
    new_value = models.CharField(max_length=100, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "user activities"

    def __str__(self):
        return f"{self.action} {self.target_email} @ {self.created_at:%Y-%m-%d %H:%M}"
