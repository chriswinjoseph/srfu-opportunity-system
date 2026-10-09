"""
Account management operations.

Every operation runs in a single transaction so a failure never leaves a
partial account, role or permission change. Operations that could remove
the last active Admin take a lock first and re-read the current roles, so
concurrent requests cannot leave the system without an Admin.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import UserActivity
from .roles import ROLE_ADMIN, ROLE_CHOICES

logger = logging.getLogger(__name__)

User = get_user_model()

VALID_ROLES = {value for value, _ in ROLE_CHOICES}

# Drafts that are still in progress (not sent, sending or cancelled).
UNFINISHED_DRAFT_STATUSES = (
    "draft",
    "awaiting_approval",
    "changes_requested",
    "approved",
    "send_failed",
)


class AccountOperationError(Exception):
    """A rule was violated; the message is safe to show to the user."""


def role_label(role):
    return dict(ROLE_CHOICES).get(role, role)


def _log(actor, target, action, previous="", new="", detail=""):
    return UserActivity.objects.create(
        actor=actor,
        target=target,
        actor_email=getattr(actor, "email", "") or "",
        target_email=getattr(target, "email", "") or "",
        action=action,
        previous_value=previous,
        new_value=new,
        detail=detail,
    )


def _lock_admins():
    """
    Take the write lock first (a no-op UPDATE; SQLite ignores
    select_for_update), then return a fresh read of every Admin.
    """
    User.objects.filter(role=ROLE_ADMIN).update(role=F("role"))
    return list(User.objects.select_for_update().filter(role=ROLE_ADMIN))


def _is_active_admin(user):
    return (
        user.role == ROLE_ADMIN
        and user.is_active
        and not user.invitation_pending
    )


def _require_admin(actor):
    if actor is None or not actor.is_app_admin:
        raise AccountOperationError(
            "Only an Admin can manage user accounts."
        )


def invitation_url(request, user, base_url=None):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse(
        "password_reset_confirm",
        kwargs={"uidb64": uid, "token": token},
    )

    if base_url:
        return base_url.rstrip("/") + path

    return request.build_absolute_uri(path)


def send_invitation_email(request, user, base_url=None):
    """
    Email a secure password-setup link. Returns True on delivery,
    False on any delivery failure (details are logged, not shown).
    """
    message = render_to_string(
        "accounts/email/invitation_email.txt",
        {
            "user": user,
            "invitation_url": invitation_url(request, user, base_url),
            "role_label": role_label(user.role),
        },
    )

    try:
        send_mail(
            subject="You have been invited to Safe Roads For Us",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Invitation email could not be sent.")
        return False

    return True


def split_name(full_name):
    parts = (full_name or "").split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def create_invited_user(actor, full_name, email, role, action="user_created"):
    """
    Create a pending account with no usable password. The caller sends
    the invitation. ``actor`` may be None only for first-Admin setup.
    """
    if actor is not None:
        _require_admin(actor)

    if role not in VALID_ROLES:
        raise AccountOperationError("Please choose a role.")

    first_name, last_name = split_name(full_name)
    email = User.objects.normalize_email(email).strip().lower()

    with transaction.atomic():
        if User.objects.filter(email__iexact=email).exists():
            raise AccountOperationError(
                "A user with this email address already exists."
            )

        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            invitation_pending=True,
        )
        user.set_unusable_password()
        user.save()

        _log(actor, user, action, new=role)

    return user


def record_invitation_result(actor, user, delivered, resent=False):
    if delivered:
        User.objects.filter(pk=user.pk).update(
            invitation_sent_at=timezone.now()
        )
        _log(
            actor,
            user,
            "invitation_resent" if resent else "invitation_sent",
        )
    else:
        _log(
            actor,
            user,
            "invitation_failed",
            detail="Email delivery failed.",
        )


def prepare_resend(actor, user):
    """
    Rotate the pending account's credential state so earlier links stop
    working, ready for a new invitation. Admin only; pending only.
    """
    _require_admin(actor)

    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)

        if not locked.is_active:
            raise AccountOperationError(
                "Re-enable this account before sending an invitation."
            )

        if not locked.invitation_pending:
            raise AccountOperationError(
                "This user has already set their password."
            )

        locked.set_unusable_password()
        locked.save(update_fields=["password"])

    return locked


def change_role(actor, target, new_role):
    _require_admin(actor)

    if new_role not in VALID_ROLES:
        raise AccountOperationError("Please choose a role.")

    if actor.pk == target.pk:
        raise AccountOperationError(
            "You cannot change your own role. "
            "Another Admin must do this."
        )

    with transaction.atomic():
        # Re-check the acting Admin and the target against current data.
        current_admins = _lock_admins()
        actor_now = User.objects.get(pk=actor.pk)
        locked = User.objects.select_for_update().get(pk=target.pk)

        if not actor_now.is_app_admin:
            raise AccountOperationError(
                "Only an Admin can manage user accounts."
            )

        if locked.role == new_role:
            raise AccountOperationError(
                f"This user is already {role_label(new_role)}."
            )

        previous = locked.role

        if previous == ROLE_ADMIN:
            remaining = [
                admin
                for admin in current_admins
                if admin.pk != locked.pk and _is_active_admin(admin)
            ]
            if not remaining:
                raise AccountOperationError(
                    "At least one active Admin must remain."
                )

        locked.role = new_role

        update_fields = ["role"]

        if new_role != ROLE_ADMIN:
            # Defence in depth: nothing legacy may keep Admin power.
            locked.is_superuser = False
            locked.is_staff = False
            update_fields += ["is_superuser", "is_staff"]

        locked.save(update_fields=update_fields)

        if new_role != ROLE_ADMIN:
            locked.groups.clear()
            locked.user_permissions.clear()

        _log(actor, locked, "role_changed", previous, new_role)

    return locked


def disable_user(actor, target):
    _require_admin(actor)

    if actor.pk == target.pk:
        raise AccountOperationError(
            "You cannot disable your own account."
        )

    with transaction.atomic():
        current_admins = _lock_admins()
        actor_now = User.objects.get(pk=actor.pk)
        locked = User.objects.select_for_update().get(pk=target.pk)

        if not actor_now.is_app_admin:
            raise AccountOperationError(
                "Only an Admin can manage user accounts."
            )

        if not locked.is_active:
            raise AccountOperationError(
                "This account is already disabled."
            )

        if _is_active_admin(locked):
            remaining = [
                admin
                for admin in current_admins
                if admin.pk != locked.pk and _is_active_admin(admin)
            ]
            if not remaining:
                raise AccountOperationError(
                    "The last active Admin cannot be disabled."
                )

        locked.is_active = False
        locked.save(update_fields=["is_active"])

        _log(actor, locked, "account_disabled")

    return locked


def enable_user(actor, target):
    _require_admin(actor)

    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=target.pk)

        if locked.is_active:
            raise AccountOperationError(
                "This account is already enabled."
            )

        locked.is_active = True
        locked.save(update_fields=["is_active"])

        _log(actor, locked, "account_enabled")

    return locked


def owner_q(user):
    """Drafts whose effective owner is ``user`` (assignee wins)."""
    return Q(assigned_to=user) | Q(
        assigned_to__isnull=True,
        requested_by=user,
    )


def unfinished_drafts_for(user):
    from outreach.models import EmailDraft

    return (
        EmailDraft.objects.filter(
            workflow_status__in=UNFINISHED_DRAFT_STATUSES,
        )
        .filter(owner_q(user))
        .select_related("opportunity", "opportunity__content_type")
        .order_by("-updated_at")
    )


def reassign_unfinished_drafts(actor, source, destination):
    from outreach.models import EmailDraft, EmailDraftHistory

    _require_admin(actor)

    if destination is None or not destination.is_active:
        raise AccountOperationError(
            "Choose an active user to receive the drafts."
        )

    if destination.invitation_pending:
        raise AccountOperationError(
            "Choose a user who has completed account setup."
        )

    if source.pk == destination.pk:
        raise AccountOperationError(
            "Choose a different user to receive the drafts."
        )

    with transaction.atomic():
        drafts = list(
            EmailDraft.objects.select_for_update()
            .filter(
                workflow_status__in=UNFINISHED_DRAFT_STATUSES,
            )
            .filter(owner_q(source))
        )

        for draft in drafts:
            # Ownership only: version, status and approval are untouched.
            EmailDraft.objects.filter(pk=draft.pk).update(
                assigned_to=destination,
            )

            EmailDraftHistory.objects.create(
                draft=draft,
                action="reassigned",
                from_status=draft.workflow_status,
                to_status=draft.workflow_status,
                version=draft.version,
                performed_by=actor,
                reason=(
                    f"Reassigned from {source.email} "
                    f"to {destination.email}."
                ),
                recipient_email_snapshot=draft.recipient_email,
                subject_snapshot=draft.subject,
                body_snapshot=draft.body,
            )

        if drafts:
            _log(
                actor,
                source,
                "drafts_reassigned",
                previous=source.email,
                new=destination.email,
                detail=f"{len(drafts)} draft(s) reassigned.",
            )

    return len(drafts)
