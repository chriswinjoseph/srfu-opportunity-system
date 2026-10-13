"""
Helpers for follow-up outreach to organisations that are already Contacted.

Nothing here changes workflow state.
"""

from datetime import date, datetime, time

from zoneinfo import ZoneInfo

from django.utils import timezone

from .models import EmailDraft, Opportunity

MELBOURNE = ZoneInfo("Australia/Melbourne")

RESPONSE_STATUSES = ("interested", "not_interested", "do_not_contact")

RESPONSE_LABELS = {
    "interested": "Interested",
    "not_interested": "Not Interested",
    "do_not_contact": "Do Not Contact",
}

# Limits for the relevant history given to the AI as untrusted context.
MAX_PREVIOUS_EMAILS = 2
MAX_EMAIL_CHARS = 1500
MAX_NOTE_CHARS = 500
MAX_CONTACT_EVENTS = 5


def current_outcome(statuses_newest_first):
    """
    The organisation's response status, from its opportunities' statuses
    (newest first).

    Do Not Contact takes precedence if ANY opportunity has it. Otherwise
    the newest Interested / Not Interested response applies. Follow-up
    outreach creates "contacted" opportunities, which never hide a
    recorded response.
    """
    statuses = list(statuses_newest_first)

    if "do_not_contact" in statuses:
        return "do_not_contact"

    for status in statuses:
        if status in ("interested", "not_interested"):
            return status

    return ""


def organisation_outcome(content_type, object_id):
    return current_outcome(
        Opportunity.objects.filter(
            content_type=content_type,
            object_id=object_id,
        )
        .order_by("-date_created", "-id")
        .values_list("status", flat=True)
    )


def melbourne_now():
    return timezone.now().astimezone(MELBOURNE)


def parse_contact_datetime(date_text, time_text=""):
    """
    Interpret the user-entered contact date (and optional time) as
    Melbourne time. Returns ``(aware_datetime, error)``; exactly one of
    them is ``None``.
    """
    date_text = (date_text or "").strip()
    time_text = (time_text or "").strip()

    if not date_text:
        return None, "Enter the date the organisation was contacted."

    try:
        day = date.fromisoformat(date_text)
    except ValueError:
        return None, "Enter a valid contact date."

    if time_text:
        try:
            clock = time.fromisoformat(time_text)
        except ValueError:
            return None, "Enter a valid contact time."
    else:
        clock = time(0, 0)

    # zoneinfo resolves daylight saving; an ambiguous or skipped local
    # time is read with fold=0.
    value = datetime.combine(day, clock).replace(tzinfo=MELBOURNE)

    now = melbourne_now()

    if time_text:
        if value > now:
            return None, "The contact time cannot be in the future."
    elif day > now.date():
        return None, "The contact date cannot be in the future."

    return value, None


def follow_up_context(content_type, object_id):
    """
    Relevant, saved outreach history for one organisation, for the AI to
    use as untrusted reference text. Only this organisation's records,
    and no account or activity data.
    """
    drafts = (
        EmailDraft.objects.filter(
            opportunity__content_type=content_type,
            opportunity__object_id=object_id,
            workflow_status="sent",
        )
        .order_by("-sent_at", "-id")[:MAX_PREVIOUS_EMAILS]
    )

    previous_emails = [
        {
            "sent_on": (
                draft.sent_at.astimezone(MELBOURNE).strftime("%d %B %Y")
                if draft.sent_at
                else ""
            ),
            "subject": (draft.subject or "")[:200],
            "body": (draft.body or "")[:MAX_EMAIL_CHARS],
        }
        for draft in drafts
    ]

    opportunities = list(
        Opportunity.objects.filter(
            content_type=content_type,
            object_id=object_id,
        ).order_by("-date_created", "-id")
    )

    outcome = current_outcome(op.status for op in opportunities)

    contact_events = [
        {
            "date": op.date_contacted.astimezone(MELBOURNE).strftime(
                "%d %B %Y"
            ),
            "method": op.outreach_method or "",
            "note": (op.notes or "")[:MAX_NOTE_CHARS],
        }
        for op in opportunities
        if op.date_contacted
    ][:MAX_CONTACT_EVENTS]

    response_notes = [
        (op.notes or "")[:MAX_NOTE_CHARS]
        for op in opportunities
        if op.status in RESPONSE_STATUSES and op.notes
    ][:2]

    return {
        "recorded_response_status": RESPONSE_LABELS.get(outcome, ""),
        "recorded_response_notes": response_notes,
        "previous_sent_emails": previous_emails,
        "recorded_contacts": contact_events,
    }
