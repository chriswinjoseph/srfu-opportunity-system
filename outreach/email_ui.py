"""
Presentation helpers for the email workflow UI (dashboard modal and the
organisation page).

Nothing here changes workflow state. The permission flags computed for
the UI only decide which controls are shown; every action is still
checked again, authoritatively, by the existing workflow views.
"""

import secrets
from functools import wraps

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme

from .services import validate_generated_email

# Display labels. The stored status values are unchanged.
STATUS_LABELS = {
    "draft": "Draft",
    "awaiting_approval": "Pending Review",
    "changes_requested": "Changes Requested",
    "approved": "Approved",
    "sending": "Sending",
    "sent": "Sent",
    "send_failed": "Send Failed",
    "cancelled": "Cancelled",
}

STATUS_CSS = {
    "draft": "grey",
    "awaiting_approval": "orange",
    "changes_requested": "red",
    "approved": "green",
    "sending": "orange",
    "sent": "green",
    "send_failed": "red",
    "cancelled": "grey",
}

EDITABLE_STATUSES = ("draft", "changes_requested", "approved")
OPEN_STATUSES = (
    "draft",
    "awaiting_approval",
    "changes_requested",
    "approved",
    "sending",
    "send_failed",
)
CANCELLABLE_STATUSES = (
    "draft",
    "awaiting_approval",
    "changes_requested",
    "approved",
    "send_failed",
)

SESSION_STASH_KEY = "email_form_stash"


def status_label(status):
    return STATUS_LABELS.get(status, status)


def status_css(status):
    return STATUS_CSS.get(status, "grey")


def safe_next_url(request, value):
    """
    Return ``value`` only if it is a same-site path inside the outreach
    application. Anything else (other hosts, schemes, protocol-relative
    URLs, other apps) is rejected.
    """
    value = (value or "").strip()

    if not value or not value.startswith("/outreach/"):
        return None

    if value.startswith("//") or "\\" in value:
        return None

    if not url_has_allowed_host_and_scheme(
        value,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return None

    return value


def org_key(content_type_id, object_id):
    return f"{content_type_id}-{object_id}"


def organisation_flags(organisation, has_do_not_contact):
    """The organisation-level conditions that restrict email actions."""
    recipient = (getattr(organisation, "public_email", "") or "").strip()

    try:
        from django.core.validators import validate_email

        validate_email(recipient)
        valid_recipient = True
    except Exception:
        valid_recipient = False

    flags = {
        "archived": bool(organisation.is_archived),
        "do_not_contact": bool(has_do_not_contact),
        "contacted": organisation.contact_status != "not_yet_contacted",
        "valid_recipient": valid_recipient,
        "recipient": recipient,
    }

    reasons = []

    if flags["archived"]:
        reasons.append(
            "This organisation is archived and cannot be contacted."
        )
    if flags["do_not_contact"]:
        reasons.append(
            "This organisation is marked Do Not Contact. "
            "New email outreach is unavailable."
        )
    if flags["contacted"]:
        reasons.append(
            "This organisation has already been contacted. "
            "New initial email outreach is unavailable."
        )
    if not flags["valid_recipient"]:
        reasons.append(
            "A valid recipient email address is required before an "
            "email can be created."
        )

    flags["reasons"] = reasons
    flags["can_start_outreach"] = not reasons

    return flags


def newest_open_draft_id(drafts):
    """Primary key of the newest draft that is not cancelled."""
    for draft in drafts:  # newest first
        if draft.workflow_status != "cancelled":
            return draft.pk

    return None


def compute_actions(draft, user, flags, newest_open_id):
    """
    Which controls to show for one draft, computed from that draft's own
    state and the current user. Never reuse another draft's result.
    """
    status = draft.workflow_status

    actions = {
        "issues": [],
        "can_edit": False,
        "can_submit": False,
        "can_withdraw": False,
        "can_cancel": False,
        "can_approve": False,
        "can_reject": False,
        "can_send": False,
        "can_retry_send": False,
        "superseded": False,
        "notes": [],
    }

    blocked = flags["archived"] or flags["do_not_contact"] or (
        flags["contacted"] and status != "sent"
    )

    can_author = (
        user.has_perm("outreach.generate_emaildraft")
        and draft.user_can_modify(user)
    )
    can_review = user.has_perm("outreach.approve_emaildraft")
    can_send_perm = user.has_perm("outreach.send_emaildraft")

    actions["superseded"] = (
        status in ("draft", "changes_requested")
        and newest_open_id is not None
        and draft.pk != newest_open_id
    )

    if flags["archived"]:
        actions["notes"].append("Archived organisations are read-only.")
    elif flags["do_not_contact"] and status != "sent":
        actions["notes"].append("Do Not Contact: no further actions.")
    elif flags["contacted"] and status not in ("sent", "cancelled"):
        actions["notes"].append(
            "The organisation has already been contacted."
        )

    if (
        status in ("draft", "changes_requested")
        and not can_author
        and not blocked
    ):
        actions["notes"].append(
            "You can view this draft, but only its owner or an Admin "
            "can edit or submit it."
        )

    if actions["superseded"]:
        actions["notes"].append(
            "A newer version exists. This older version is read-only."
        )

    if (
        status in EDITABLE_STATUSES
        and can_author
        and not blocked
        and not actions["superseded"]
    ):
        actions["can_edit"] = True

    if status in ("draft", "changes_requested"):
        # Stored issues, plus a live check of the saved text with the same
        # validation the edit view applies, so an incomplete draft is never
        # offered for submission (the server still enforces this).
        issues = [
            line
            for line in (draft.validation_issues or "").splitlines()
            if line.strip()
        ]

        if not issues:
            signature = draft.template.signature if draft.template else ""
            _incomplete, live = validate_generated_email(
                draft.subject, draft.body, signature or ""
            )
            issues = list(live)

        actions["issues"] = issues

    if (
        actions["can_edit"]
        and status in ("draft", "changes_requested")
        and not actions["issues"]
        and not draft.is_incomplete
    ):
        actions["can_submit"] = True

    if (
        status in ("draft", "changes_requested")
        and actions["issues"]
        and actions["can_edit"]
    ):
        actions["notes"].append(
            "Resolve the validation issues and save before submitting."
        )

    if status == "awaiting_approval" and can_author and not blocked:
        actions["can_withdraw"] = True

    if status == "awaiting_approval" and can_review and not blocked:
        actions["can_approve"] = True
        actions["can_reject"] = True

    send_ready = (
        can_send_perm
        and not blocked
        and not draft.reconciliation_required
        and draft.approved_version is not None
        and draft.approved_version == draft.version
    )

    if status == "approved" and send_ready:
        actions["can_send"] = True

    if status == "send_failed" and send_ready:
        actions["can_retry_send"] = True

    if (
        status in CANCELLABLE_STATUSES
        and can_author
        and not flags["archived"]
    ):
        actions["can_cancel"] = True

    if status == "sending":
        actions["notes"].append(
            "Delivery is unresolved. This email cannot be sent again "
            "until it has been reconciled."
            if draft.reconciliation_required
            else "This email is being sent."
        )

    return actions


def honour_next(view):
    """
    Let an existing POST workflow view return the user to the page they
    came from (for example the dashboard with the email dialog), without
    duplicating any of the view's rules. Only safe same-site paths under
    /outreach/ are honoured. When the action failed, the visible form
    content is kept in the session so the dialog can show it again.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)

        if request.method != "POST":
            return response

        next_url = safe_next_url(request, request.POST.get("next"))

        if next_url is None or not isinstance(
            response, HttpResponseRedirect
        ):
            return response

        if _request_failed(request):
            token = secrets.token_urlsafe(8)
            stash = dict(request.session.get(SESSION_STASH_KEY) or {})

            # Keep only a few recent entries; each is only ever used with
            # its own one-time token, so a stale or resurrected entry (for
            # example from a parallel request saving an older session)
            # can never be applied to a later dialog.
            while len(stash) >= 5:
                stash.pop(next(iter(stash)))

            stash[token] = {
                "org_key": _posted_org_key(request, kwargs),
                "draft_id": str(kwargs.get("draft_id") or ""),
                "subject": request.POST.get("subject", ""),
                "body": request.POST.get("body", ""),
                "purpose": request.POST.get("outreach_purpose", ""),
                "template_id": request.POST.get("template_id", ""),
                "rejection_reason": request.POST.get(
                    "rejection_reason", ""
                ),
                "panel": request.POST.get("panel_on_error", "compose"),
            }
            request.session[SESSION_STASH_KEY] = stash

            separator = "&" if "?" in next_url else "?"
            next_url = f"{next_url}{separator}stash={token}"

        response["Location"] = next_url

        return response

    return wrapper


def _request_failed(request):
    queued = getattr(
        getattr(request, "_messages", None), "_queued_messages", []
    )

    return any(
        getattr(message, "level", 0) >= messages.ERROR
        for message in queued
    )


def _posted_org_key(request, kwargs):
    if "content_type_id" in kwargs and "object_id" in kwargs:
        return org_key(kwargs["content_type_id"], kwargs["object_id"])

    return request.POST.get("org_key", "")


def pop_stash(request, key, token):
    """
    Return the saved form content for ``token`` if it belongs to this
    organisation, and forget it.
    """
    token = (token or "").strip()
    stash = request.session.get(SESSION_STASH_KEY) or {}
    entry = stash.get(token)

    if not entry or entry.get("org_key") != key:
        return None

    stash = dict(stash)
    del stash[token]
    request.session[SESSION_STASH_KEY] = stash

    return entry
