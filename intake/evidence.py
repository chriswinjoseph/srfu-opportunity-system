"""
BA section 5: convert the detailed outreach evidence of the client dataset
into the binary contact_status.

``overall_status`` of the workbook is never used (it contains "Partially
Contacted" and depends on replies) and ``sent_to_by_srfu`` is never used on
its own (two delivery-failure contacts carry TRUE).

Replies are preserved separately. A reply never becomes Interested.
"""

SUCCESSFUL = ("sent_and_human_reply_received", "sent_no_human_reply_found")
NOT_SUCCESSFUL = (
    "delivery_failure_recorded",
    "human_inbound_only",
    "copied_or_automated_only",
    "no_outreach_history",
)
KNOWN = SUCCESSFUL + NOT_SUCCESSFUL

# What the supporting flags must say for each status (None = either).
EXPECTED_FLAGS = {
    "sent_and_human_reply_received": {"sent": True, "reply": True},
    "sent_no_human_reply_found": {"sent": True, "reply": False},
    "delivery_failure_recorded": {"sent": None, "reply": False},
    "human_inbound_only": {"sent": False, "reply": True},
    "copied_or_automated_only": {"sent": False, "reply": None},
    "no_outreach_history": {"sent": False, "reply": False},
}


def contact_conflicts(contact):
    """Reasons why one contact's status and flags contradict each other."""
    status = (contact.get("status") or "").strip()

    if not status:
        return []

    if status not in KNOWN:
        return [f"Unsupported outreach status '{status}'."]

    problems = []
    expected = EXPECTED_FLAGS[status]

    for flag, label in (("sent", "sent_flag"), ("reply", "human_reply")):
        wanted = expected[flag]
        actual = contact.get(label)

        if wanted is not None and actual is not None and wanted != actual:
            problems.append(
                f"Status '{status}' conflicts with {label}="
                f"{'TRUE' if actual else 'FALSE'}."
            )

    return problems


def map_organisation_status(contacts):
    """
    ``(status, reasons)`` where status is ``contacted``,
    ``not_yet_contacted`` or ``review`` (a result state, never a
    contact_status).

    One confirmed successful outgoing contact is enough for Contacted.
    """
    reasons = []

    for contact in contacts:
        reasons.extend(contact_conflicts(contact))

    if reasons:
        return "review", reasons

    if any((c.get("status") or "") in SUCCESSFUL for c in contacts):
        return "contacted", []

    return "not_yet_contacted", []
