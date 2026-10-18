"""Admin review of held records and proposed changes."""

from django.core.exceptions import PermissionDenied

from intake.ingest import process_submission
from intake.matching import Submission
from intake.models import (
    DuplicateReview, FieldProvenance, IntakeRun, OrganisationSource, ProposedChange,
)
from intake.reviews import ReviewError, decide_change, decide_review
from outreach.models import Bank, Contact, EmailDraft, Opportunity

from .helpers import IntakeTestCase, con_row, make_workbook, org_row
from .test_import import do_import


def hold_one(test, existing_name="Alpha Community Bank Ltd"):
    """Create an existing bank, then import a similar one so it is held."""
    existing = test.bank(existing_name, "VIC")
    run, _ = do_import(test.admin, make_workbook(
        [org_row("O_1", "Alpha Community Bank", "VIC")],
        [con_row("C_1", "O_1", "alpha@example.test")],
    ))

    return existing, run, DuplicateReview.objects.get(kind="duplicate")


class DuplicateReviewTests(IntakeTestCase):
    def test_held_record_shows_candidates_and_reasons(self):
        existing, run, review = hold_one(self)

        self.assertEqual(review.status, DuplicateReview.STATUS_PENDING)
        self.assertEqual(review.matches[0]["id"], existing.pk)
        self.assertIn("similar", review.matches[0]["reasons"][0])
        self.assertEqual(Bank.objects.count(), 1)

    def test_use_existing_links_the_source_and_fills_blanks_only(self):
        existing, run, review = hold_one(self)
        Bank.objects.filter(pk=existing.pk).update(public_email="")

        decide_review(review.pk, self.admin, "use_existing", target=("bank", existing.pk))

        existing.refresh_from_db()
        review.refresh_from_db()
        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(existing.public_email, "alpha@example.test")
        self.assertEqual(existing.contact_status, "contacted")
        self.assertTrue(OrganisationSource.objects.filter(object_id=existing.pk, source_org_id="O_1").exists())
        self.assertEqual(review.decided_by, self.admin)
        self.assertIsNotNone(review.decided_at)
        self.assertEqual(review.decision, "use_existing")
        run.refresh_from_db()
        self.assertEqual(run.totals["review"], 0)
        self.assertEqual(run.totals["updated"], 1)

    def test_create_separate_records_the_decision(self):
        existing, run, review = hold_one(self)

        decide_review(review.pk, self.admin, "create_separate", note="Different branch")

        review.refresh_from_db()
        self.assertEqual(Bank.objects.count(), 2)
        self.assertTrue(Bank.objects.filter(bank_name="Alpha Community Bank").exists())
        self.assertEqual(review.decision, "create_separate")
        self.assertEqual(review.note, "Different branch")
        self.assertEqual(review.target_id, Bank.objects.get(bank_name="Alpha Community Bank").pk)

    def test_reject_creates_nothing_and_is_remembered_on_repeat(self):
        existing, run, review = hold_one(self)

        decide_review(review.pk, self.admin, "reject")

        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(run.results.get(name="Alpha Community Bank").outcome, "rejected")

        again, _ = do_import(self.admin, make_workbook(
            [org_row("O_1", "Alpha Community Bank", "VIC")], [con_row("C_1", "O_1", "alpha@example.test")],
        ))

        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(DuplicateReview.objects.filter(status="pending").count(), 0)
        self.assertEqual(again.results.get(name="Alpha Community Bank").outcome, "rejected")

    def test_repeat_import_does_not_queue_the_same_record_twice(self):
        existing, run, review = hold_one(self)

        do_import(self.admin, make_workbook(
            [org_row("O_1", "Alpha Community Bank", "VIC")], [con_row("C_1", "O_1", "alpha@example.test")],
        ))

        self.assertEqual(DuplicateReview.objects.filter(kind="duplicate", status="pending").count(), 1)

    def test_a_decision_can_only_be_saved_once(self):
        existing, run, review = hold_one(self)
        decide_review(review.pk, self.admin, "create_separate")
        count = Bank.objects.count()

        with self.assertRaises(ReviewError):
            decide_review(review.pk, self.admin, "create_separate")

        self.assertEqual(Bank.objects.count(), count)

    def test_use_existing_must_choose_one_of_the_candidates(self):
        existing, run, review = hold_one(self)
        stranger = self.bank("Stranger Bank", "VIC")

        with self.assertRaises(ReviewError):
            decide_review(review.pk, self.admin, "use_existing", target=("bank", stranger.pk))

        with self.assertRaises(ReviewError):
            decide_review(review.pk, self.admin, "use_existing")

        review.refresh_from_db()
        self.assertEqual(review.status, DuplicateReview.STATUS_PENDING)

    def test_create_separate_is_refused_if_an_exact_duplicate_appeared_meanwhile(self):
        existing, run, review = hold_one(self)
        self.bank("Alpha Community Bank", "VIC")      # created after the record was held

        with self.assertRaises(ReviewError):
            decide_review(review.pk, self.admin, "create_separate")

        review.refresh_from_db()
        self.assertEqual(review.status, DuplicateReview.STATUS_PENDING)
        self.assertEqual(Bank.objects.filter(bank_name="Alpha Community Bank").count(), 1)

    def test_use_existing_with_an_archived_bank_never_restores_it(self):
        existing, run, review = hold_one(self)
        Bank.objects.filter(pk=existing.pk).update(is_archived=True)

        decide_review(review.pk, self.admin, "use_existing", target=("bank", existing.pk))

        existing.refresh_from_db()
        self.assertTrue(existing.is_archived)
        self.assertEqual(existing.contact_status, "not_yet_contacted")
        self.assertFalse(Contact.objects.filter(object_id=existing.pk, content_type=self.bank_ct).exists())

    def test_do_not_contact_and_drafts_are_untouched_by_a_decision(self):
        existing, run, review = hold_one(self)
        opp = Opportunity.objects.create(content_type=self.bank_ct, object_id=existing.pk, status="do_not_contact")
        draft = EmailDraft.objects.create(
            opportunity=opp, recipient_email="a@example.test", subject="S", body="B",
            outreach_purpose="P", workflow_status="draft", requested_by=self.admin,
        )

        decide_review(review.pk, self.admin, "use_existing", target=("bank", existing.pk))

        opp.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual(opp.status, "do_not_contact")
        self.assertEqual(draft.workflow_status, "draft")

    def test_only_active_admins_can_decide(self):
        existing, run, review = hold_one(self)

        for user in (self.staff, None):
            with self.assertRaises(PermissionDenied):
                decide_review(review.pk, user or type("A", (), {"is_authenticated": False})(), "reject")

        self.admin.is_active = False

        with self.assertRaises(PermissionDenied):
            decide_review(review.pk, self.admin, "reject")

        review.refresh_from_db()
        self.assertEqual(review.status, DuplicateReview.STATUS_PENDING)

    def test_evidence_conflict_decisions(self):
        data = make_workbook(
            [org_row("O_1", "Echo Community Bank", "VIC")],
            [con_row("C_1", "O_1", status="sent_no_human_reply_found", sent="FALSE")],
        )
        run, _ = do_import(self.admin, data)
        review = DuplicateReview.objects.get(kind="evidence")

        decide_review(review.pk, self.admin, "accept_not_yet_contacted")

        bank = Bank.objects.get()
        self.assertEqual(bank.contact_status, "not_yet_contacted")
        self.assertEqual(Contact.objects.count(), 1)
        run.refresh_from_db()
        self.assertEqual(run.totals["review"], 0)
        self.assertEqual(run.totals["created"], 1)

    def test_evidence_conflict_can_be_accepted_as_contacted_or_rejected(self):
        for decision, expected in (("accept_contacted", "contacted"), ("reject", None)):
            with self.subTest(decision=decision):
                Bank.objects.all().delete()
                DuplicateReview.objects.all().delete()
                data = make_workbook(
                    [org_row("O_1", "Echo Community Bank", "VIC")],
                    [con_row("C_1", "O_1", status="sent_no_human_reply_found", sent="FALSE")],
                )
                do_import(self.admin, data)
                review = DuplicateReview.objects.get(kind="evidence", status="pending")

                decide_review(review.pk, self.admin, decision)

                if expected:
                    self.assertEqual(Bank.objects.get().contact_status, expected)
                else:
                    self.assertEqual(Bank.objects.count(), 0)

    def test_shared_email_contact_decisions(self):
        other = self.bank("Other Bank", "QLD")
        Contact.objects.create(content_type=self.bank_ct, object_id=other.pk, email="alpha@example.test")
        do_import(self.admin, make_workbook([org_row("O_1", "Alpha Community Bank", "VIC")],
                                            [con_row("C_1", "O_1", "alpha@example.test")]))
        review = DuplicateReview.objects.get(kind="contact")
        alpha = Bank.objects.get(bank_name="Alpha Community Bank")

        decide_review(review.pk, self.admin, "create_separate")

        self.assertTrue(Contact.objects.filter(object_id=alpha.pk, email="alpha@example.test").exists())
        self.assertTrue(Contact.objects.filter(object_id=other.pk, email="alpha@example.test").exists())

    def test_shared_email_contact_can_be_rejected(self):
        other = self.bank("Other Bank", "QLD")
        Contact.objects.create(content_type=self.bank_ct, object_id=other.pk, email="alpha@example.test")
        do_import(self.admin, make_workbook([org_row("O_1", "Alpha Community Bank", "VIC")],
                                            [con_row("C_1", "O_1", "alpha@example.test")]))
        review = DuplicateReview.objects.get(kind="contact")

        decide_review(review.pk, self.admin, "reject")

        alpha = Bank.objects.get(bank_name="Alpha Community Bank")
        self.assertFalse(Contact.objects.filter(object_id=alpha.pk).exists())


class ProposedChangeTests(IntakeTestCase):
    def proposal(self):
        bank = self.bank("Alpha Community Bank", "VIC", public_email="old@example.test")
        run = IntakeRun.objects.create(kind="import", status="successful", created_by=self.admin)
        sub = Submission(org_type="bank", name="Alpha Community Bank", state="VIC", email="new@example.test",
                         source_key="client_workbook", source_org_id="O_1", origin="import", collected_fields=["email"])
        process_submission(run, sub, self.admin)

        return bank, ProposedChange.objects.get()

    def test_different_values_are_proposed_with_old_new_and_source(self):
        bank, change = self.proposal()

        bank.refresh_from_db()
        self.assertEqual(bank.public_email, "old@example.test")
        self.assertEqual((change.old_value, change.new_value, change.field),
                         ("old@example.test", "new@example.test", "public_email"))
        self.assertEqual(change.source_label, "client_workbook")

    def test_a_blank_value_never_replaces_a_populated_field(self):
        bank = self.bank("Alpha Community Bank", "VIC", public_email="old@example.test", public_phone="03 9555 0000")
        run = IntakeRun.objects.create(kind="import", status="successful", created_by=self.admin)
        sub = Submission(org_type="bank", name="Alpha Community Bank", state="VIC", email="", phone="",
                         source_key="s", source_org_id="X", origin="import")

        process_submission(run, sub, self.admin)

        bank.refresh_from_db()
        self.assertEqual((bank.public_email, bank.public_phone), ("old@example.test", "03 9555 0000"))
        self.assertEqual(ProposedChange.objects.count(), 0)

    def test_approving_applies_the_value_and_records_verification(self):
        bank, change = self.proposal()

        decide_change(change.pk, self.admin, "approve")

        bank.refresh_from_db()
        change.refresh_from_db()
        self.assertEqual(bank.public_email, "new@example.test")
        self.assertEqual(change.status, ProposedChange.STATUS_APPROVED)
        self.assertEqual(change.decided_by, self.admin)
        prov = FieldProvenance.objects.get(object_id=bank.pk, field="public_email")
        self.assertTrue(prov.verified)
        self.assertEqual(prov.verified_by, self.admin)
        self.assertEqual(prov.origin, "admin_review")

    def test_rejecting_keeps_the_current_value(self):
        bank, change = self.proposal()

        decide_change(change.pk, self.admin, "reject")

        bank.refresh_from_db()
        self.assertEqual(bank.public_email, "old@example.test")
        self.assertEqual(ProposedChange.objects.get().status, ProposedChange.STATUS_REJECTED)

    def test_a_stale_proposal_is_not_applied(self):
        bank, change = self.proposal()
        Bank.objects.filter(pk=bank.pk).update(public_email="edited@example.test")

        result = decide_change(change.pk, self.admin, "approve")

        bank.refresh_from_db()
        self.assertEqual(result.status, ProposedChange.STATUS_STALE)
        self.assertEqual(bank.public_email, "edited@example.test")

    def test_archived_organisations_are_not_changed_by_an_approval(self):
        bank, change = self.proposal()
        Bank.objects.filter(pk=bank.pk).update(is_archived=True)

        with self.assertRaises(ReviewError):
            decide_change(change.pk, self.admin, "approve")

        bank.refresh_from_db()
        self.assertEqual(bank.public_email, "old@example.test")
        self.assertTrue(bank.is_archived)

    def test_change_decisions_are_single_use_and_admin_only(self):
        bank, change = self.proposal()

        with self.assertRaises(PermissionDenied):
            decide_change(change.pk, self.staff, "approve")

        decide_change(change.pk, self.admin, "reject")

        with self.assertRaises(ReviewError):
            decide_change(change.pk, self.admin, "approve")

    def test_an_invalid_proposed_email_is_refused(self):
        bank = self.bank("Alpha Community Bank", "VIC", public_email="old@example.test")
        change = ProposedChange.objects.create(
            content_type=self.bank_ct, object_id=bank.pk, field="public_email",
            old_value="old@example.test", new_value="not-an-email",
        )

        with self.assertRaises(ReviewError):
            decide_change(change.pk, self.admin, "approve")

        bank.refresh_from_db()
        self.assertEqual(bank.public_email, "old@example.test")
