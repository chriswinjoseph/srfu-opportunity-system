"""Sanitised fixtures: synthetic workbooks, users and organisations."""

import io

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from openpyxl import Workbook

from accounts.models import User
from intake.workbook import CONTACT_COLUMNS, ORGANISATION_COLUMNS
from outreach.models import Bank, Branch, Club

ORG_HEADER = [
    "organisation_id", "bank_name", "state", "num_contacts", "contact_names",
    "emails", "contact_types", "any_human_reply_received", "all_contacts_replied",
    "overall_status", "first_observed_date", "last_observed_date", "needs_verification_flag",
]
CON_HEADER = [
    "contact_id", "organisation_id", "bank_name", "state", "contact_name", "email",
    "contact_type", "name_needs_verification", "bank_affiliation_needs_verification",
    "first_observed_date", "last_observed_date", "sent_to_by_srfu", "human_reply_received",
    "contact_status",
]

SENT_REPLY = "sent_and_human_reply_received"
SENT_NO_REPLY = "sent_no_human_reply_found"
FAILURE = "delivery_failure_recorded"
INBOUND = "human_inbound_only"
COPIED = "copied_or_automated_only"


def org_row(oid="O_1", name="Alpha Community Bank", state="VIC", overall="Contacted", **extra):
    row = {
        "organisation_id": oid, "bank_name": name, "state": state, "num_contacts": 1,
        "contact_names": "", "emails": "", "contact_types": "shared_mailbox",
        "any_human_reply_received": "FALSE", "all_contacts_replied": "FALSE",
        "overall_status": overall, "first_observed_date": "2025-01-10",
        "last_observed_date": "2025-02-10", "needs_verification_flag": "TRUE",
    }
    row.update(extra)

    return row


def con_row(cid="C_1", oid="O_1", email="alpha@example.test", status=SENT_NO_REPLY,
            sent="TRUE", reply="FALSE", name="(unspecified)", **extra):
    row = {
        "contact_id": cid, "organisation_id": oid, "bank_name": "x", "state": "VIC",
        "contact_name": name, "email": email, "contact_type": "shared_mailbox",
        "name_needs_verification": "TRUE", "bank_affiliation_needs_verification": "FALSE",
        "first_observed_date": "2025-01-10", "last_observed_date": "2025-02-10",
        "sent_to_by_srfu": sent, "human_reply_received": reply, "contact_status": status,
    }
    row.update(extra)

    return row


def make_workbook(orgs, contacts, *, org_header=None, con_header=None, sheets=("Organisations", "Contacts")):
    wb = Workbook()
    wb.remove(wb.active)

    if "Organisations" in sheets:
        ws = wb.create_sheet("Organisations")
        header = org_header or ORG_HEADER
        ws.append(header)

        for row in orgs:
            ws.append([row.get(h) for h in header])

    if "Contacts" in sheets:
        ws = wb.create_sheet("Contacts")
        header = con_header or CON_HEADER
        ws.append(header)

        for row in contacts:
            ws.append([row.get(h) for h in header])

    buffer = io.BytesIO()
    wb.save(buffer)

    return buffer.getvalue()


def default_workbook():
    """Three organisations: sent/no reply, failure only, sent with a reply."""
    orgs = [
        org_row("O_1", "Alpha Community Bank", "VIC"),
        org_row("O_2", "Bravo Community Bank", "NSW", overall="Not Yet Contacted"),
        org_row("O_3", "Charlie Community Bank", "WA", overall="Partially Contacted"),
    ]
    contacts = [
        con_row("C_1", "O_1", "alpha@example.test", SENT_NO_REPLY),
        con_row("C_2", "O_1", "alpha2@example.test", SENT_REPLY, reply="TRUE", name="Pat Example"),
        con_row("C_3", "O_2", "bravo@example.test", FAILURE, sent="TRUE"),
        con_row("C_4", "O_3", "charlie@example.test", INBOUND, sent="FALSE", reply="TRUE"),
        con_row("C_5", "O_3", "charlie2@example.test", SENT_NO_REPLY),
    ]

    return make_workbook(orgs, contacts)


class IntakeTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@intake.test", first_name="Ada", last_name="Admin",
            password="Pass-12345-xx!", role="admin",
        )
        self.staff = User.objects.create_user(
            email="staff@intake.test", first_name="Sam", last_name="Staff",
            password="Pass-12345-xx!", role="staff",
        )
        self.bank_ct = ContentType.objects.get_for_model(Bank)

    def bank(self, name="Existing Bank", state="VIC", **kw):
        kw.setdefault("region", "Victoria")

        return Bank.objects.create(bank_name=name, state=state, **kw)

    def branch(self, bank, name="Main Branch", state="VIC", **kw):
        return Branch.objects.create(bank=bank, branch_name=name, state=state, **kw)

    def club(self, name="Sample FC", state="VIC", **kw):
        return Club.objects.create(club_name=name, state=state, **kw)
