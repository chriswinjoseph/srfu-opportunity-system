"""Excel import: validation, evidence mapping, grouping, preview/confirm, repeat runs."""

from datetime import timezone as dt_tz
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType

from intake.evidence import map_organisation_status
from intake.importer import ImportBusy, confirm_import, create_preview
from intake.models import (
    ContactSource,
    DuplicateReview,
    IntakeResult,
    IntakeRun,
    OrganisationSource,
)
from intake.normalise import clean_contact_name, parse_bool
from intake.workbook import parse_workbook
from outreach.models import Bank, Contact, EmailDraft, Opportunity

from .helpers import (
    COPIED, FAILURE, INBOUND, SENT_NO_REPLY, SENT_REPLY, IntakeTestCase,
    con_row, default_workbook, make_workbook, org_row,
)


def do_import(user, data, name="client.xlsx"):
    run, parsed = create_preview(user, data, name)

    if not parsed.ok:
        return run, parsed

    return confirm_import(run.pk, user), parsed


class WorkbookValidationTests(IntakeTestCase):
    def test_unsupported_file_type_is_rejected_before_any_write(self):
        run, parsed = create_preview(self.admin, b"a,b\n1,2", "data.csv")

        self.assertFalse(parsed.ok)
        self.assertIn("Only Microsoft Excel", parsed.structure_errors[0])
        self.assertEqual(run.status, IntakeRun.STATUS_FAILED)
        self.assertEqual(Bank.objects.count(), 0)

    def test_corrupt_file_is_rejected(self):
        run, parsed = create_preview(self.admin, b"not really an xlsx", "data.xlsx")

        self.assertFalse(parsed.ok)
        self.assertIn("could not be opened", parsed.structure_errors[0])
        self.assertEqual(Bank.objects.count(), 0)

    def test_missing_sheet_and_missing_column_are_named(self):
        data = make_workbook([], [], sheets=("Contacts",))
        parsed = parse_workbook(data, "a.xlsx")
        self.assertIn("no 'Organisations' sheet", " ".join(parsed.structure_errors))

        header = [h for h in __import__("intake.tests.helpers", fromlist=["ORG_HEADER"]).ORG_HEADER if h != "state"]
        data = make_workbook([org_row()], [con_row()], org_header=header)
        parsed = parse_workbook(data, "a.xlsx")
        self.assertIn("state", " ".join(parsed.structure_errors))
        self.assertEqual(Bank.objects.count(), 0)

        run, _parsed = create_preview(self.admin, data, "a.xlsx")
        self.assertEqual(run.status, IntakeRun.STATUS_FAILED)
        self.assertIn("state", run.error_message)

    def test_workbook_without_organisation_rows_is_invalid(self):
        parsed = parse_workbook(make_workbook([], []), "a.xlsx")

        self.assertFalse(parsed.ok)
        self.assertIn("no readable rows", " ".join(parsed.structure_errors))

    def test_value_parsing(self):
        self.assertEqual(clean_contact_name("(unspecified)"), "")
        self.assertEqual(clean_contact_name("  (Unspecified) "), "")
        self.assertEqual(clean_contact_name("  Pat  Example "), "Pat Example")
        self.assertIs(parse_bool("TRUE"), True)
        self.assertIs(parse_bool("false"), False)
        self.assertIs(parse_bool(True), True)
        self.assertIsNone(parse_bool("maybe"))
        self.assertIsNone(parse_bool(None))

    def test_bad_rows_are_reported_but_valid_rows_continue(self):
        orgs = [
            org_row("O_1", "Good Community Bank", "VIC"),
            org_row("", "No Id Bank", "VIC"),
            org_row("O_3", "", "VIC"),
            org_row("O_4", "No State Bank", ""),
            org_row("O_1", "Repeated Id Bank", "VIC"),
        ]
        contacts = [
            con_row("C_1", "O_1", "good@example.test"),
            con_row("C_2", "O_1", "not-an-email"),
            con_row("C_3", "O_9", "orphan@example.test"),
        ]

        parsed = parse_workbook(make_workbook(orgs, contacts), "a.xlsx")

        self.assertTrue(parsed.ok)
        self.assertEqual(len(parsed.groups), 1)
        fields = {e["field"] for e in parsed.row_errors}
        self.assertTrue({"organisation_id", "bank_name", "state"} <= fields)
        self.assertEqual(len(parsed.groups[0]["contacts"]), 1)
        self.assertEqual(parsed.groups[0]["contact_problems"][0]["field"], "email")


class StatusEvidenceTests(IntakeTestCase):
    def status(self, *statuses_and_flags):
        contacts = [
            {"status": s, "sent_flag": sent, "human_reply": reply}
            for s, sent, reply in statuses_and_flags
        ]

        return map_organisation_status(contacts)[0]

    def test_ba_mapping_table(self):
        self.assertEqual(self.status((SENT_REPLY, True, True)), "contacted")
        self.assertEqual(self.status((SENT_NO_REPLY, True, False)), "contacted")
        self.assertEqual(self.status((FAILURE, True, False)), "not_yet_contacted")
        self.assertEqual(self.status((INBOUND, False, True)), "not_yet_contacted")
        self.assertEqual(self.status((COPIED, False, False)), "not_yet_contacted")
        self.assertEqual(self.status(), "not_yet_contacted")

    def test_one_successful_outgoing_contact_is_enough(self):
        self.assertEqual(
            self.status((FAILURE, True, False), (INBOUND, False, True), (SENT_NO_REPLY, True, False)),
            "contacted",
        )

    def test_delivery_failure_with_a_sent_flag_is_not_contacted(self):
        # sent_to_by_srfu alone is never used.
        self.assertEqual(self.status((FAILURE, True, False)), "not_yet_contacted")

    def test_conflicting_or_unsupported_evidence_is_held_for_review(self):
        for case in (
            ((SENT_NO_REPLY, False, False),),   # says sent, flag says not sent
            ((SENT_REPLY, True, False),),       # says replied, flag says no reply
            (("some_new_status", True, False),),
            ((INBOUND, True, True),),           # inbound only, but flagged as sent
        ):
            with self.subTest(case=case):
                self.assertEqual(self.status(*case), "review")


class ImportWorkflowTests(IntakeTestCase):
    def test_admin_import_creates_banks_contacts_and_binary_status(self):
        run, _ = do_import(self.admin, default_workbook())

        self.assertEqual(run.status, IntakeRun.STATUS_SUCCESSFUL)
        self.assertEqual(Bank.objects.count(), 3)
        alpha = Bank.objects.get(bank_name="Alpha Community Bank")
        bravo = Bank.objects.get(bank_name="Bravo Community Bank")
        charlie = Bank.objects.get(bank_name="Charlie Community Bank")

        self.assertEqual(alpha.contact_status, "contacted")
        self.assertEqual(bravo.contact_status, "not_yet_contacted")   # delivery failure only
        self.assertEqual(charlie.contact_status, "contacted")
        self.assertEqual({b.contact_status for b in Bank.objects.all()} - {"contacted", "not_yet_contacted"}, set())
        self.assertEqual(run.totals["created"], 3)
        self.assertEqual(run.totals["contacts_created"], 5)

    def test_multiple_contacts_create_one_organisation(self):
        do_import(self.admin, default_workbook())

        alpha = Bank.objects.get(bank_name="Alpha Community Bank")
        self.assertEqual(Contact.objects.filter(content_type=self.bank_ct, object_id=alpha.pk).count(), 2)
        self.assertEqual(Bank.objects.filter(bank_name="Alpha Community Bank").count(), 1)

    def test_unspecified_names_stay_empty_and_real_names_are_kept(self):
        do_import(self.admin, default_workbook())

        names = sorted(Contact.objects.values_list("contact_name", flat=True))
        self.assertNotIn("(unspecified)", names)
        self.assertIn("Pat Example", names)
        self.assertEqual(names.count(""), 4)

    def test_source_ids_and_evidence_are_kept_apart_from_internal_ids(self):
        run, _ = do_import(self.admin, default_workbook(), "client.xlsx")

        alpha = Bank.objects.get(bank_name="Alpha Community Bank")
        source = OrganisationSource.objects.get(object_id=alpha.pk, content_type=self.bank_ct)
        self.assertEqual(source.source_org_id, "O_1")
        self.assertEqual(source.source_key, "client_workbook")
        self.assertEqual(source.source_filename, "client.xlsx")
        self.assertNotEqual(str(alpha.organisation_id), source.source_org_id)
        self.assertTrue(source.requires_verification)
        self.assertEqual(source.extra["overall_status_in_file"], "Contacted")

        cs = ContactSource.objects.get(source_contact_id="C_2")
        self.assertEqual(cs.outreach_evidence, SENT_REPLY)
        self.assertIs(cs.human_reply, True)
        self.assertIs(cs.sent_flag, True)
        self.assertIs(cs.name_needs_verification, True)
        # Observed dates are Melbourne dates stored as timezone-aware instants.
        from intake.workbook import MELBOURNE

        self.assertEqual(cs.first_observed_at.astimezone(MELBOURNE).date().isoformat(), "2025-01-10")
        self.assertEqual(run.created_by, self.admin)
        self.assertEqual(alpha.created_by, self.admin)
        self.assertEqual(alpha.record_source, "Client Import")

    def test_a_human_reply_never_becomes_interested(self):
        do_import(self.admin, default_workbook())

        statuses = set(Opportunity.objects.values_list("status", flat=True))
        self.assertEqual(statuses, {"contacted"})
        charlie_opp = Opportunity.objects.get(object_id=Bank.objects.get(bank_name="Charlie Community Bank").pk)
        self.assertIn("No Interested", charlie_opp.notes)

    def test_overall_status_in_the_file_is_never_copied(self):
        # The file says Not Yet Contacted, but a successful email is recorded.
        orgs = [org_row("O_1", "Delta Community Bank", "VIC", overall="Not Yet Contacted")]
        run, _ = do_import(self.admin, make_workbook(orgs, [con_row("C_1", "O_1")]))

        self.assertEqual(Bank.objects.get().contact_status, "contacted")

    def test_conflicting_evidence_is_held_not_guessed(self):
        orgs = [org_row("O_1", "Echo Community Bank", "VIC")]
        contacts = [con_row("C_1", "O_1", status=SENT_NO_REPLY, sent="FALSE")]

        run, _ = do_import(self.admin, make_workbook(orgs, contacts))

        self.assertEqual(Bank.objects.count(), 0)
        review = DuplicateReview.objects.get()
        self.assertEqual(review.kind, DuplicateReview.KIND_EVIDENCE)
        self.assertEqual(run.status, IntakeRun.STATUS_PARTIAL)
        self.assertEqual(run.totals["review"], 1)

    def test_optional_fields_stay_optional_without_manual_form_rules(self):
        # Manual Add Organisation requires an email; imports do not.
        orgs = [org_row("O_1", "Foxtrot Community Bank", "SA")]

        do_import(self.admin, make_workbook(orgs, []))

        bank = Bank.objects.get()
        self.assertEqual(bank.public_email, "")
        self.assertEqual((bank.region, bank.suburb, bank.postcode), ("", "", ""))
        self.assertEqual(bank.state, "SA")
        self.assertEqual(bank.contact_status, "not_yet_contacted")

    def test_invalid_state_row_fails_without_stopping_other_rows(self):
        orgs = [org_row("O_1", "Good Community Bank", "VIC"), org_row("O_2", "Odd Bank", "Atlantis")]

        run, _ = do_import(self.admin, make_workbook(orgs, [con_row("C_1", "O_1")]))

        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(run.totals["failed"], 1)
        self.assertEqual(run.status, IntakeRun.STATUS_PARTIAL)
        failed = IntakeResult.objects.get(outcome="failed")
        self.assertEqual(failed.field, "state")
        self.assertTrue(failed.action_required)

    def test_preview_writes_nothing_and_confirm_runs_once(self):
        run, parsed = create_preview(self.admin, default_workbook(), "client.xlsx")

        self.assertEqual(Bank.objects.count(), 0)
        self.assertEqual(run.status, IntakeRun.STATUS_PREVIEWED)
        self.assertEqual(run.totals["preview"]["create"], 3)
        self.assertEqual(run.totals["evidence_contacted"], 2)
        self.assertEqual(run.totals["evidence_not_yet"], 1)

        confirm_import(run.pk, self.admin)
        count = Bank.objects.count()

        with self.assertRaises(ImportBusy):
            confirm_import(run.pk, self.admin)

        self.assertEqual(Bank.objects.count(), count)

    def test_second_import_cannot_start_while_one_is_running(self):
        run, _ = create_preview(self.admin, default_workbook(), "a.xlsx")
        IntakeRun.objects.create(kind=IntakeRun.KIND_IMPORT, status=IntakeRun.STATUS_RUNNING)

        with self.assertRaises(ImportBusy):
            confirm_import(run.pk, self.admin)

        self.assertEqual(Bank.objects.count(), 0)

    def test_matching_is_rechecked_when_the_preview_is_confirmed(self):
        run, _ = create_preview(self.admin, default_workbook(), "client.xlsx")
        self.assertEqual(run.totals["preview"]["create"], 3)

        # The same bank is created after the preview but before confirmation.
        self.bank("Alpha Community Bank", "VIC")
        run = confirm_import(run.pk, self.admin)

        self.assertEqual(Bank.objects.filter(bank_name="Alpha Community Bank").count(), 1)
        alpha_result = run.results.get(name="Alpha Community Bank")
        self.assertIn(alpha_result.outcome, ("updated", "unchanged"))

    def test_repeat_import_is_idempotent(self):
        first, _ = do_import(self.admin, default_workbook())
        snapshot = (Bank.objects.count(), Contact.objects.count(), Opportunity.objects.count(),
                    OrganisationSource.objects.count(), ContactSource.objects.count())

        second, _ = do_import(self.admin, default_workbook())

        self.assertEqual(
            (Bank.objects.count(), Contact.objects.count(), Opportunity.objects.count(),
             OrganisationSource.objects.count(), ContactSource.objects.count()),
            snapshot,
        )
        self.assertEqual(second.totals["created"], 0)
        self.assertEqual(second.totals["contacts_created"], 0)
        self.assertEqual(second.totals["exact_duplicates"], 3)
        self.assertEqual(second.status, IntakeRun.STATUS_SUCCESSFUL)

    def test_repeat_import_preserves_later_activity(self):
        do_import(self.admin, default_workbook())
        alpha = Bank.objects.get(bank_name="Alpha Community Bank")
        opp = Opportunity.objects.get(object_id=alpha.pk, content_type=self.bank_ct)
        Opportunity.objects.filter(pk=opp.pk).update(status="interested")
        Bank.objects.filter(pk=alpha.pk).update(public_email="manual@example.test", region="Central")

        do_import(self.admin, default_workbook())

        opp.refresh_from_db()
        alpha.refresh_from_db()
        self.assertEqual(opp.status, "interested")
        self.assertEqual(alpha.public_email, "manual@example.test")   # populated value kept
        self.assertEqual(alpha.region, "Central")
        self.assertEqual(alpha.contact_status, "contacted")

    def test_a_not_yet_contacted_org_is_never_downgraded_or_a_contacted_org_reset(self):
        # Already Contacted by later outreach; the file has no such evidence.
        bank = self.bank("Bravo Community Bank", "NSW", contact_status="contacted")

        do_import(self.admin, default_workbook())

        bank.refresh_from_db()
        self.assertEqual(bank.contact_status, "contacted")

    def test_existing_exact_bank_is_matched_and_blank_fields_filled(self):
        existing = self.bank("Alpha Community Bank", "VIC", public_email="")

        run, _ = do_import(self.admin, default_workbook())

        self.assertEqual(Bank.objects.filter(bank_name__iexact="Alpha Community Bank").count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.public_email, "alpha@example.test")     # blank filled
        self.assertEqual(existing.contact_status, "contacted")            # confirmed evidence
        self.assertTrue(OrganisationSource.objects.filter(object_id=existing.pk, source_org_id="O_1").exists())

    def test_different_values_become_proposals_not_overwrites(self):
        existing = self.bank("Alpha Community Bank", "VIC", public_email="keep@example.test")

        run, _ = do_import(self.admin, default_workbook())

        existing.refresh_from_db()
        self.assertEqual(existing.public_email, "keep@example.test")
        change = run.changes.get()
        self.assertEqual((change.field, change.old_value, change.new_value),
                         ("public_email", "keep@example.test", "alpha@example.test"))

    def test_same_name_in_a_different_state_is_a_different_organisation(self):
        # BA AC-08: an exact bank match needs the same name AND state, and a
        # likely duplicate must be in the same state, so this is created
        # separately; the existing bank is left untouched.
        existing = self.bank("Alpha Community Bank", "NSW")

        run, _ = do_import(self.admin, default_workbook())

        self.assertEqual(Bank.objects.filter(bank_name="Alpha Community Bank").count(), 2)
        self.assertEqual(DuplicateReview.objects.count(), 0)
        existing.refresh_from_db()
        self.assertEqual(existing.contact_status, "not_yet_contacted")
        self.assertEqual(existing.state, "NSW")

    def test_similar_name_in_the_same_state_is_held_for_review(self):
        existing = self.bank("Alpha Community Bank Ltd", "VIC")

        run, _ = do_import(self.admin, default_workbook())

        self.assertEqual(DuplicateReview.objects.filter(kind="duplicate").count(), 1)
        self.assertEqual(Bank.objects.filter(bank_name__startswith="Alpha").count(), 1)
        self.assertEqual(run.status, IntakeRun.STATUS_PARTIAL)
        existing.refresh_from_db()
        self.assertEqual(existing.contact_status, "not_yet_contacted")

    def test_archived_matches_are_not_recreated_or_restored(self):
        archived = self.bank("Alpha Community Bank", "VIC", is_archived=True, contact_status="not_yet_contacted")

        run, _ = do_import(self.admin, default_workbook())

        archived.refresh_from_db()
        self.assertTrue(archived.is_archived)
        self.assertEqual(archived.contact_status, "not_yet_contacted")
        self.assertEqual(Bank.objects.filter(bank_name="Alpha Community Bank").count(), 1)
        self.assertEqual(Contact.objects.filter(object_id=archived.pk, content_type=self.bank_ct).count(), 0)
        self.assertIn("archived", run.results.get(name="Alpha Community Bank").message)

    def test_a_failing_group_leaves_no_partial_records_and_others_continue(self):
        real_create = Contact.objects.create
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1

            if kwargs.get("email") == "bravo@example.test":
                raise RuntimeError("database exploded")

            return real_create(*args, **kwargs)

        with patch("intake.ingest.Contact.objects.create", side_effect=flaky):
            run, _ = do_import(self.admin, default_workbook())

        self.assertFalse(Bank.objects.filter(bank_name="Bravo Community Bank").exists())
        self.assertFalse(OrganisationSource.objects.filter(source_org_id="O_2").exists())
        self.assertTrue(Bank.objects.filter(bank_name="Alpha Community Bank").exists())
        self.assertTrue(Bank.objects.filter(bank_name="Charlie Community Bank").exists())
        failed = IntakeResult.objects.get(outcome="failed")
        self.assertNotIn("exploded", failed.message)
        self.assertEqual(run.status, IntakeRun.STATUS_PARTIAL)
        self.assertEqual(run.totals["failed"], 1)

    def test_import_never_touches_drafts_responses_or_do_not_contact(self):
        bank = self.bank("Alpha Community Bank", "VIC", contact_status="contacted")
        opp = Opportunity.objects.create(content_type=self.bank_ct, object_id=bank.pk, status="do_not_contact")
        draft = EmailDraft.objects.create(
            opportunity=opp, recipient_email="a@example.test", subject="S", body="B",
            outreach_purpose="P", workflow_status="sent", requested_by=self.admin,
        )

        do_import(self.admin, default_workbook())

        opp.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual(opp.status, "do_not_contact")
        self.assertEqual(draft.workflow_status, "sent")
        self.assertEqual(Opportunity.objects.filter(object_id=bank.pk, content_type=self.bank_ct).count(), 1)

    def test_shared_email_across_organisations_is_held_for_review(self):
        other = self.bank("Other Bank", "QLD")
        Contact.objects.create(content_type=self.bank_ct, object_id=other.pk, email="alpha@example.test")

        run, _ = do_import(self.admin, default_workbook())

        review = DuplicateReview.objects.get(kind=DuplicateReview.KIND_CONTACT)
        self.assertEqual(review.matches[0]["name"], "Other Bank")
        alpha = Bank.objects.get(bank_name="Alpha Community Bank")
        self.assertFalse(Contact.objects.filter(object_id=alpha.pk, email="alpha@example.test").exists())
        self.assertTrue(Contact.objects.filter(object_id=other.pk, email="alpha@example.test").exists())

    def test_duplicate_contact_in_the_same_organisation_is_not_repeated(self):
        bank = self.bank("Alpha Community Bank", "VIC")
        Contact.objects.create(content_type=self.bank_ct, object_id=bank.pk, email="ALPHA@example.test", contact_name="Kept Name")

        do_import(self.admin, default_workbook())

        contacts = Contact.objects.filter(object_id=bank.pk, content_type=self.bank_ct)
        self.assertEqual(contacts.filter(email__iexact="alpha@example.test").count(), 1)
        self.assertEqual(contacts.get(email__iexact="alpha@example.test").contact_name, "Kept Name")


class SuppliedWorkbookTests(IntakeTestCase):
    """The client workbook, imported only into the disposable test database."""

    PATH = "local_data/RMIT_Community_Bank_Contacts_Cleaned.xlsx"

    def read(self):
        import os

        if not os.path.exists(self.PATH):
            self.skipTest("The client workbook is not present on this machine.")

        with open(self.PATH, "rb") as handle:
            return handle.read()

    def test_supplied_workbook_import_and_repeat(self):
        data = self.read()

        run, parsed = do_import(self.admin, data, "RMIT_Community_Bank_Contacts_Cleaned.xlsx")

        self.assertTrue(parsed.ok)
        self.assertEqual(len(parsed.groups), 168)
        self.assertEqual(sum(len(g["contacts"]) for g in parsed.groups), 244)
        self.assertEqual(parsed.row_errors, [])
        self.assertEqual(run.totals["evidence_contacted"], 166)
        self.assertEqual(run.totals["evidence_not_yet"], 2)
        self.assertEqual(run.totals["review"], 0)

        banks = Bank.objects.all()
        self.assertEqual(banks.count(), 168)
        self.assertEqual(banks.filter(contact_status="contacted").count(), 166)
        self.assertEqual(banks.filter(contact_status="not_yet_contacted").count(), 2)
        self.assertEqual(Contact.objects.count(), 244)
        self.assertEqual(Contact.objects.filter(contact_name="").count(), 70)
        self.assertFalse(Contact.objects.filter(contact_name__iexact="(unspecified)").exists())
        self.assertEqual(banks.exclude(state="").count(), 168)
        self.assertEqual(ContactSource.objects.count(), 244)
        self.assertEqual(OrganisationSource.objects.count(), 168)

        first = (Bank.objects.count(), Contact.objects.count(), Opportunity.objects.count())

        repeat, _ = do_import(self.admin, data, "RMIT_Community_Bank_Contacts_Cleaned.xlsx")

        self.assertEqual((Bank.objects.count(), Contact.objects.count(), Opportunity.objects.count()), first)
        self.assertEqual(repeat.totals["created"], 0)
        self.assertEqual(repeat.totals["exact_duplicates"], 168)
        self.assertEqual(repeat.totals["contacts_created"], 0)
        self.assertEqual(repeat.status, IntakeRun.STATUS_SUCCESSFUL)
