"""Correction preview/apply/rollback for data imported before the rules were fixed."""

import json
import os
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from intake.corrections import apply_plan, build_plan, revert_plan
from intake.models import ContactSource, OrganisationSource
from outreach.models import Bank, Contact, EmailDraft, Opportunity

from .helpers import (
    FAILURE, IntakeTestCase, SENT_NO_REPLY, SENT_REPLY, con_row, make_workbook, org_row,
)

NOTE = "Imported from the cleaned SRFU community-bank workbook.\nSource organisation ID: %s\nHuman replies recorded: 0"


def workbook():
    orgs = [
        org_row("O_1", "Alpha Community Bank", "VIC"),
        org_row("O_2", "Bravo Community Bank", "NSW", overall="Not Yet Contacted"),
        org_row("O_3", "Charlie Community Bank", "WA"),
        org_row("O_4", "Delta Community Bank", "SA", overall="Not Yet Contacted"),
        org_row("O_5", "Echo Community Bank", "QLD"),
    ]
    contacts = [
        con_row("C_1", "O_1", "alpha@example.test", SENT_NO_REPLY),
        con_row("C_2", "O_1", "alpha2@example.test", SENT_REPLY, reply="TRUE", name="Pat Example"),
        con_row("C_3", "O_2", "bravo@example.test", FAILURE),
        con_row("C_4", "O_3", "charlie@example.test", SENT_NO_REPLY),
        con_row("C_5", "O_4", "delta@example.test", FAILURE),
        con_row("C_6", "O_5", "echo@example.test", SENT_NO_REPLY),
    ]

    return make_workbook(orgs, contacts)


class LegacyData(IntakeTestCase):
    """Banks as the earlier importer left them: state code in Region, no source rows."""

    def legacy_bank(self, name, code, source_id, status="contacted", contact_email=None, contact_name="(unspecified)"):
        bank = Bank.objects.create(bank_name=name, region=code, state="", contact_status=status)
        opp = Opportunity.objects.create(
            content_type=self.bank_ct, object_id=bank.pk, status="contacted",
            outreach_method="Imported SRFU contact history", notes=NOTE % source_id,
        )
        if contact_email:
            Contact.objects.create(content_type=self.bank_ct, object_id=bank.pk, email=contact_email,
                                   contact_name=contact_name, role="shared_mailbox")

        return bank, opp

    def setUp(self):
        super().setUp()
        self.alpha, self.alpha_opp = self.legacy_bank("Alpha Community Bank", "VIC", "O_1", contact_email="alpha@example.test")
        Contact.objects.create(content_type=self.bank_ct, object_id=self.alpha.pk, email="alpha2@example.test",
                               contact_name="Pat Example", role="shared_mailbox")
        self.bravo, self.bravo_opp = self.legacy_bank("Bravo Community Bank", "NSW", "O_2", contact_email="bravo@example.test")
        self.charlie, _ = self.legacy_bank("Charlie Community Bank", "WA", "O_3", contact_email="charlie@example.test")
        self.delta, self.delta_opp = self.legacy_bank("Delta Community Bank", "SA", "O_4", contact_email="delta@example.test")
        EmailDraft.objects.create(opportunity=self.delta_opp, recipient_email="delta@example.test", subject="S", body="B",
                                  outreach_purpose="P", workflow_status="sent", requested_by=self.admin)
        self.data = workbook()

    def plan(self):
        return build_plan(self.data, "client.xlsx")

    def fixes(self, plan, kind):
        return [f for f in plan.fixes if f["kind"] == kind]


class PlanTests(LegacyData):
    def test_plan_is_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            self.plan()

        writes = [q["sql"] for q in queries if q["sql"].split()[0].upper() in ("INSERT", "UPDATE", "DELETE")]
        self.assertEqual(writes, [])

    def test_only_the_delivery_failure_only_bank_without_later_activity_is_reset(self):
        plan = self.plan()

        status = self.fixes(plan, "contact_status")
        self.assertEqual([f["organisation"] for f in status], ["Bravo Community Bank"])
        self.assertEqual((status[0]["old"], status[0]["new"]), ("contacted", "not_yet_contacted"))
        self.assertEqual((status[0]["opportunity_old"], status[0]["opportunity_new"]), ("contacted", "not_yet_contacted"))
        # Delta also has delivery-failure-only evidence but an email was sent later.
        excluded = [e for e in plan.exclusions if e["kind"] == "contact_status"]
        self.assertEqual([e["organisation"] for e in excluded], ["Delta Community Bank"])
        self.assertIn("an email was sent", excluded[0]["reason"])
        # Banks with successful evidence are never proposed for a reset.
        names = {f["organisation"] for f in status}
        self.assertFalse({"Alpha Community Bank", "Charlie Community Bank"} & names)

    def test_later_outreach_and_responses_block_a_reset(self):
        for change, text in (
            (lambda: Opportunity.objects.filter(pk=self.bravo_opp.pk).update(status="interested"), "response"),
            (lambda: Opportunity.objects.create(content_type=self.bank_ct, object_id=self.bravo.pk, status="contacted",
                                                outreach_method="phone"), "later outreach"),
            (lambda: Bank.objects.filter(pk=self.bravo.pk).update(is_archived=True), "archived"),
        ):
            with self.subTest(text=text):
                Bank.objects.filter(pk=self.bravo.pk).update(is_archived=False)
                Opportunity.objects.filter(object_id=self.bravo.pk, content_type=self.bank_ct).exclude(pk=self.bravo_opp.pk).delete()
                Opportunity.objects.filter(pk=self.bravo_opp.pk).update(status="contacted")
                change()

                plan = self.plan()

                self.assertEqual(self.fixes(plan, "contact_status"), [])
                self.assertTrue(any(text in e["reason"] for e in plan.exclusions if e["kind"] == "contact_status"))

    def test_unspecified_names_and_state_codes_in_region(self):
        plan = self.plan()

        names = self.fixes(plan, "unspecified_name")
        self.assertEqual(len(names), 4)           # alpha, bravo, charlie, delta; "Pat Example" is kept
        self.assertTrue(all(f["old"] == "(unspecified)" and f["new"] == "" for f in names))
        states = {f["organisation"]: (f["old"], f["new"], f["region_old"], f["region_new"]) for f in self.fixes(plan, "state_in_region")}
        self.assertEqual(states["Alpha Community Bank"], ("", "VIC", "VIC", ""))
        self.assertEqual(states["Delta Community Bank"], ("", "SA", "SA", ""))
        self.assertEqual(len(states), 4)

    def test_edited_values_are_excluded(self):
        Bank.objects.filter(pk=self.alpha.pk).update(region="Central Highlands")
        Contact.objects.filter(email="alpha@example.test").update(contact_name="Typed Later")

        plan = self.plan()

        self.assertNotIn("Alpha Community Bank", {f["organisation"] for f in self.fixes(plan, "state_in_region")})
        self.assertFalse([f for f in self.fixes(plan, "unspecified_name") if f["organisation"] == "Alpha Community Bank"])
        self.assertTrue(any(e["kind"] == "state_in_region" for e in plan.exclusions))

    def test_provenance_is_recovered_from_evidence_without_inventing_dates_or_admins(self):
        plan = self.plan()

        provenance = self.fixes(plan, "source_provenance")
        self.assertEqual({f["source_org_id"] for f in provenance}, {"O_1", "O_2", "O_3", "O_4"})
        for fix in provenance:
            self.assertTrue(fix["recorded_at"])            # the recorded import time of the old record
        self.assertEqual(len(self.fixes(plan, "contact_provenance")), 5)

    def test_matching_needs_source_evidence_not_a_name_alone(self):
        # Echo has a matching name but no import note and no contacts: not matched.
        Bank.objects.create(bank_name="Echo Community Bank", region="QLD", state="", contact_status="contacted")

        plan = self.plan()

        self.assertNotIn("O_5", plan.matched)
        reasons = " ".join(e["reason"] for e in plan.exclusions if e["kind"] == "match")
        self.assertIn("No source evidence", reasons)

    def test_a_source_id_alone_is_not_enough_if_the_name_differs(self):
        impostor, _ = self.legacy_bank("Totally Different Bank", "VIC", "O_5")

        plan = self.plan()

        self.assertNotIn("O_5", plan.matched)
        reasons = " ".join(e["reason"] for e in plan.exclusions if e["kind"] == "match")
        self.assertIn("name differs", reasons)
        self.assertEqual(Bank.objects.get(pk=impostor.pk).contact_status, "contacted")

    def test_a_name_and_all_contact_emails_can_recover_a_link_without_notes(self):
        bank = Bank.objects.create(bank_name="Echo Community Bank", region="QLD", state="", contact_status="contacted")
        Contact.objects.create(content_type=self.bank_ct, object_id=bank.pk, email="echo@example.test")

        plan = self.plan()

        self.assertEqual(plan.matched["O_5"], bank.pk)

    def test_command_prints_the_preview_and_changes_nothing(self):
        path = os.path.join(tempfile.mkdtemp(), "w.xlsx")
        with open(path, "wb") as handle:
            handle.write(self.data)
        out = StringIO()
        before = (Bank.objects.filter(contact_status="contacted").count(), Contact.objects.filter(contact_name="(unspecified)").count())

        call_command("plan_data_corrections", path, stdout=out)

        self.assertIn("read-only", out.getvalue())
        self.assertIn("Bravo Community Bank", out.getvalue())
        self.assertEqual(before, (Bank.objects.filter(contact_status="contacted").count(),
                                  Contact.objects.filter(contact_name="(unspecified)").count()))


class ApplyAndRollbackTests(LegacyData):
    def snapshot(self):
        return (
            list(Bank.objects.order_by("pk").values_list("pk", "contact_status", "state", "region")),
            list(Contact.objects.order_by("pk").values_list("pk", "contact_name")),
            list(Opportunity.objects.order_by("pk").values_list("pk", "status", "notes")),
            OrganisationSource.objects.count(), ContactSource.objects.count(),
        )

    def test_apply_on_a_disposable_database_then_roll_back(self):
        before = self.snapshot()
        plan = self.plan().to_dict()

        applied, skipped, rollback = apply_plan(plan)

        self.assertEqual(skipped, [])
        self.bravo.refresh_from_db(); self.alpha.refresh_from_db(); self.bravo_opp.refresh_from_db()
        self.assertEqual(self.bravo.contact_status, "not_yet_contacted")
        self.assertEqual(self.bravo_opp.status, "not_yet_contacted")
        self.assertIn("Corrected", self.bravo_opp.notes)
        self.assertEqual((self.alpha.state, self.alpha.region), ("VIC", ""))
        self.assertEqual(Contact.objects.filter(contact_name="(unspecified)").count(), 0)
        self.assertEqual(Contact.objects.filter(contact_name="Pat Example").count(), 1)
        self.assertEqual(OrganisationSource.objects.count(), 4)
        self.assertEqual(ContactSource.objects.count(), 5)
        # Legitimately Contacted banks stay Contacted.
        for bank in (self.alpha, self.charlie, self.delta):
            bank.refresh_from_db()
            self.assertEqual(bank.contact_status, "contacted")
        # The admin who did the original import is not invented.
        self.assertIsNone(OrganisationSource.objects.first().last_run)

        revert_plan(rollback)

        self.assertEqual(self.snapshot(), before)

    def test_apply_rechecks_and_skips_items_that_changed_since_the_preview(self):
        plan = self.plan().to_dict()
        # Later outreach is recorded after the preview.
        EmailDraft.objects.create(opportunity=self.bravo_opp, recipient_email="bravo@example.test", subject="S", body="B",
                                  outreach_purpose="P", workflow_status="sent", requested_by=self.admin)
        Contact.objects.filter(email="alpha@example.test").update(contact_name="Renamed")

        applied, skipped, _ = apply_plan(plan)

        self.bravo.refresh_from_db()
        self.assertEqual(self.bravo.contact_status, "contacted")
        reasons = {(s["kind"], s["skipped_because"]) for s in skipped}
        self.assertIn(("contact_status", "the record changed since the preview"), reasons)
        self.assertIn(("unspecified_name", "the contact name changed since the preview"), reasons)
        self.assertEqual(Contact.objects.get(email="alpha@example.test").contact_name, "Renamed")

    def test_applying_twice_changes_nothing_more(self):
        plan = self.plan().to_dict()
        apply_plan(plan)
        after_first = self.snapshot()

        applied, skipped, _ = apply_plan(plan)

        self.assertEqual(applied, [])
        self.assertEqual(self.snapshot(), after_first)

    def test_command_refuses_the_projects_own_database(self):
        path = os.path.join(tempfile.mkdtemp(), "plan.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.plan().to_dict(), handle, default=str)

        with patch("intake.management.commands.apply_data_corrections._is_project_database", return_value=True):
            with self.assertRaises(CommandError) as ctx:
                call_command("apply_data_corrections", path)

        self.assertIn("Refusing", str(ctx.exception))
        self.assertEqual(Bank.objects.get(pk=self.bravo.pk).contact_status, "contacted")

    def test_command_applies_and_reverts_on_a_disposable_copy(self):
        folder = tempfile.mkdtemp()
        plan_path, rollback_path = os.path.join(folder, "plan.json"), os.path.join(folder, "rollback.json")
        with open(plan_path, "w", encoding="utf-8") as handle:
            json.dump(self.plan().to_dict(), handle, default=str)
        before = self.snapshot()
        out = StringIO()

        with patch("intake.management.commands.apply_data_corrections._is_project_database", return_value=False):
            call_command("apply_data_corrections", plan_path, "--rollback-file", rollback_path, stdout=out)
            self.assertIn("Applied", out.getvalue())
            self.assertNotEqual(self.snapshot(), before)
            call_command("apply_data_corrections", rollback_path, "--revert", stdout=out)

        self.assertEqual(self.snapshot(), before)
