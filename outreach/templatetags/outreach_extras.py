from django import template

from outreach.email_ui import status_css, status_label

register = template.Library()


@register.filter
def draft_status_label(status):
    return status_label(status)


@register.filter
def draft_status_css(status):
    return status_css(status)


# ---------------------------------------------------------------------
# Melbourne time
#
# Stored values stay timezone-aware (UTC). They are shown in
# Australia/Melbourne, whose offset changes with daylight saving, and
# are labelled AEDT or AEST. Django's own "T" format prints nothing for
# the ambiguous hour when clocks go back, so the label is taken from
# the converted value directly.
# ---------------------------------------------------------------------
from datetime import datetime  # noqa: E402

from django.utils import dateformat  # noqa: E402

from outreach.follow_up import MELBOURNE  # noqa: E402


def _local(value):
    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        return None

    return value.astimezone(MELBOURNE)


@register.filter
def melbourne(value, fmt="j M Y, g:i A"):
    """Date and time in Melbourne time with its AEDT/AEST label."""
    local = _local(value)

    if local is None:
        return value or ""

    return f"{dateformat.format(local, fmt)} {local.tzname()}"


@register.filter
def melbourne_clock(value):
    """Time of day in Melbourne time with its AEDT/AEST label."""
    return melbourne(value, "g:i A")


@register.filter
def melbourne_date(value, fmt="j M Y"):
    local = _local(value)

    if local is None:
        return value or ""

    return dateformat.format(local, fmt)


@register.filter
def melbourne_contact(value):
    """
    A contact moment. A date entered without a time is stored at
    midnight Melbourne time and is shown as a date only.
    """
    local = _local(value)

    if local is None:
        return value or ""

    if local.hour == 0 and local.minute == 0:
        return dateformat.format(local, "j M Y")

    return melbourne(value)
