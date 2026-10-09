import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from .models import EmailDraft, EmailDraftHistory

logger = logging.getLogger(__name__)


def get_available_approvers():
    """Active, set-up users with the Admin role (who may approve)."""
    User = get_user_model()

    return User.objects.filter(
        role="admin",
        is_active=True,
        invitation_pending=False,
    )


def get_admin_recipients():
    """Email addresses of active Admins (PM/admin contacts)."""
    return [
        email
        for email in get_available_approvers().values_list(
            "email", flat=True
        )
        if email
    ]


def notify_admins(subject, message, extra_recipients=()):
    recipients = sorted(
        set(get_admin_recipients()) | set(extra_recipients)
    )

    if not recipients:
        logger.warning(
            "No admin recipients available for notification: %s",
            subject,
        )
        return False

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception:
        # The durable flag/history remains the source of truth.
        logger.exception(
            "Could not send admin notification: %s",
            subject,
        )
        return False

    return True


def flag_overdue_approvals():
    """
    Flag drafts that have been Awaiting Approval for longer than
    settings.EMAIL_APPROVAL_OVERDUE_HOURS. Drafts stay in Awaiting
    Approval; each is flagged once. Returns the drafts newly flagged.
    """
    cutoff = timezone.now() - timedelta(
        hours=settings.EMAIL_APPROVAL_OVERDUE_HOURS
    )

    candidates = EmailDraft.objects.filter(
        workflow_status="awaiting_approval",
        submitted_at__isnull=False,
        submitted_at__lte=cutoff,
        overdue_flagged_at__isnull=True,
    )

    flagged = []

    for draft in candidates:
        updated = EmailDraft.objects.filter(
            pk=draft.pk,
            workflow_status="awaiting_approval",
            overdue_flagged_at__isnull=True,
        ).update(overdue_flagged_at=timezone.now())

        if updated != 1:
            continue

        draft.refresh_from_db()

        EmailDraftHistory.objects.create(
            draft=draft,
            action="approval_overdue",
            from_status="awaiting_approval",
            to_status="awaiting_approval",
            version=draft.version,
            reason=(
                "Approval not completed within "
                f"{settings.EMAIL_APPROVAL_OVERDUE_HOURS} hours. "
                "The draft remains Awaiting Approval."
            ),
            recipient_email_snapshot=draft.recipient_email,
            subject_snapshot=draft.subject,
            body_snapshot=draft.body,
        )

        extra = []
        if draft.requested_by and draft.requested_by.email:
            extra.append(draft.requested_by.email)

        notify_admins(
            "Email draft approval overdue",
            (
                f"Draft {draft.draft_id} has been awaiting approval "
                f"since {draft.submitted_at:%Y-%m-%d %H:%M} UTC and "
                "is overdue. Please approve or request changes."
            ),
            extra_recipients=extra,
        )

        flagged.append(draft)

    return flagged
