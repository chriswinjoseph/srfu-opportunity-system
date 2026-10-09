"""Admin-only user management. Every view checks the role on the server."""

import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .forms import AddUserForm
from .models import UserActivity
from .roles import ROLE_ADMIN, ROLE_CHOICES, ROLE_STAFF

logger = logging.getLogger(__name__)

User = get_user_model()

SYSTEM_ERROR_MESSAGE = (
    "Something went wrong and no changes were saved. Please try again."
)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_app_admin:
            raise PermissionDenied

        return view(request, *args, **kwargs)

    return wrapper


def _display_name(user):
    return user.get_full_name() or user.email


@admin_required
def user_list(request):
    search = request.GET.get("q", "").strip()

    users = User.objects.all().order_by("first_name", "last_name", "email")

    if search:
        from django.db.models import Q

        users = users.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
        )

    try:
        users = list(users)
    except DatabaseError:
        logger.exception("User list failed to load.")
        return render(
            request,
            "accounts/users/user_list.html",
            {"load_error": True, "search": search},
            status=500,
        )

    admins = [user for user in users if user.role == ROLE_ADMIN]
    staff = [user for user in users if user.role == ROLE_STAFF]

    return render(
        request,
        "accounts/users/user_list.html",
        {
            "admins": admins,
            "staff": staff,
            "total": len(users),
            "search": search,
        },
    )


@admin_required
def user_add(request):
    if request.method == "POST":
        form = AddUserForm(request.POST)

        if form.is_valid():
            try:
                user = services.create_invited_user(
                    request.user,
                    form.cleaned_data["full_name"],
                    form.cleaned_data["email"],
                    form.cleaned_data["role"],
                )
            except services.AccountOperationError as exc:
                form.add_error("email", str(exc))
            except DatabaseError:
                logger.exception("User creation failed.")
                form.add_error(None, SYSTEM_ERROR_MESSAGE)
            else:
                delivered = services.send_invitation_email(request, user)
                services.record_invitation_result(
                    request.user, user, delivered
                )

                if delivered:
                    messages.success(
                        request,
                        f"Account created. An invitation was sent to "
                        f"{user.email}.",
                    )
                else:
                    messages.warning(
                        request,
                        "Account created, but the invitation email could "
                        "not be sent. Use Resend invitation to try again.",
                    )

                return redirect("user_options", user_id=user.pk)
    else:
        form = AddUserForm()

    return render(
        request,
        "accounts/users/user_add.html",
        {"form": form, "roles": ROLE_CHOICES},
    )


@admin_required
def user_options(request, user_id):
    target = get_object_or_404(User, pk=user_id)

    return render(
        request,
        "accounts/users/user_options.html",
        {
            "target": target,
            "is_self": target.pk == request.user.pk,
            "unfinished_count": services.unfinished_drafts_for(
                target
            ).count(),
            "target_name": _display_name(target),
        },
    )


@admin_required
def user_role(request, user_id):
    target = get_object_or_404(User, pk=user_id)

    if target.pk == request.user.pk:
        messages.error(
            request,
            "You cannot change your own role. Another Admin must do this.",
        )
        return redirect("user_options", user_id=target.pk)

    new_role = ROLE_STAFF if target.role == ROLE_ADMIN else ROLE_ADMIN

    if request.method == "POST":
        try:
            services.change_role(request.user, target, new_role)
        except services.AccountOperationError as exc:
            messages.error(request, str(exc))
        except DatabaseError:
            logger.exception("Role change failed.")
            messages.error(request, SYSTEM_ERROR_MESSAGE)
        else:
            messages.success(
                request,
                f"{_display_name(target)} is now "
                f"{services.role_label(new_role)}.",
            )

        return redirect("user_options", user_id=target.pk)

    return render(
        request,
        "accounts/users/user_role.html",
        {
            "target": target,
            "target_name": _display_name(target),
            "current_role_label": services.role_label(target.role),
            "new_role": new_role,
            "new_role_label": services.role_label(new_role),
        },
    )


@admin_required
@require_POST
def user_disable(request, user_id):
    target = get_object_or_404(User, pk=user_id)

    try:
        services.disable_user(request.user, target)
        # The next request from the disabled user is rejected by the
        # middleware, which also destroys the session and shows the
        # required message.
    except services.AccountOperationError as exc:
        messages.error(request, str(exc))
    except DatabaseError:
        logger.exception("Disable failed.")
        messages.error(request, SYSTEM_ERROR_MESSAGE)
    else:
        messages.success(
            request,
            f"{_display_name(target)} has been disabled.",
        )

    return redirect("user_options", user_id=target.pk)


@admin_required
@require_POST
def user_enable(request, user_id):
    target = get_object_or_404(User, pk=user_id)

    try:
        services.enable_user(request.user, target)
    except services.AccountOperationError as exc:
        messages.error(request, str(exc))
    except DatabaseError:
        logger.exception("Re-enable failed.")
        messages.error(request, SYSTEM_ERROR_MESSAGE)
    else:
        messages.success(
            request,
            f"{_display_name(target)} has been re-enabled.",
        )

    return redirect("user_options", user_id=target.pk)


@admin_required
@require_POST
def user_resend_invitation(request, user_id):
    target = get_object_or_404(User, pk=user_id)

    try:
        pending = services.prepare_resend(request.user, target)
    except services.AccountOperationError as exc:
        messages.error(request, str(exc))
        return redirect("user_options", user_id=target.pk)
    except DatabaseError:
        logger.exception("Invitation resend failed.")
        messages.error(request, SYSTEM_ERROR_MESSAGE)
        return redirect("user_options", user_id=target.pk)

    delivered = services.send_invitation_email(request, pending)
    services.record_invitation_result(
        request.user, pending, delivered, resent=True
    )

    if delivered:
        messages.success(
            request,
            f"A new invitation was sent to {pending.email}.",
        )
    else:
        messages.warning(
            request,
            "The invitation email could not be sent. Please try again.",
        )

    return redirect("user_options", user_id=target.pk)


@admin_required
def user_reassign_drafts(request, user_id):
    source = get_object_or_404(User, pk=user_id)
    drafts = services.unfinished_drafts_for(source)

    candidates = (
        User.objects.filter(is_active=True, invitation_pending=False)
        .exclude(pk=source.pk)
        .order_by("first_name", "last_name", "email")
    )

    if request.method == "POST":
        destination = candidates.filter(
            pk=request.POST.get("destination") or 0
        ).first()

        try:
            count = services.reassign_unfinished_drafts(
                request.user, source, destination
            )
        except services.AccountOperationError as exc:
            messages.error(request, str(exc))
        except DatabaseError:
            logger.exception("Draft reassignment failed.")
            messages.error(request, SYSTEM_ERROR_MESSAGE)
        else:
            messages.success(
                request,
                f"{count} draft(s) reassigned to "
                f"{_display_name(destination)}.",
            )
            return redirect("user_options", user_id=source.pk)

    return render(
        request,
        "accounts/users/user_reassign.html",
        {
            "target": source,
            "target_name": _display_name(source),
            "drafts": drafts,
            "candidates": candidates,
        },
    )


@admin_required
def user_activity(request):
    activities = UserActivity.objects.select_related(
        "actor", "target"
    )[:200]

    return render(
        request,
        "accounts/users/user_activity.html",
        {"activities": activities},
    )
