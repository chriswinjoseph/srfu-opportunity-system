from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from outreach.models import Bank, Contact, EmailDraft, Opportunity
from outreach.tests import sync_role_with_permissions
from outreach.test_roles_and_organisations import WorkflowBase, make_user

User = get_user_model()


class ArchiveAndSendingTests(WorkflowBase):
    def archive(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse(
                "archive_organisation",
                args=[self.content_type.pk, self.bank.pk],
            )
        )

    def test_unresolved_sending_record_stays_visible_after_archive(self):
        draft = self.draft("sending", owner=self.staff)
        EmailDraft.objects.filter(pk=draft.pk).update(
            reconciliation_required=True,
            send_failure_reason="Delivery status is uncertain.",
            approved_by=self.admin,
            approved_version=draft.version,
            approved_at=timezone.now(),
        )

        self.archive()

        page = self.client.get(self.detail_url())

        self.assertContains(page, "archived-unresolved-send")
        self.assertContains(page, "reconciliation required, do not resend")
        self.assertContains(page, "Delivery status is uncertain.")

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sending")
        self.assertTrue(draft.reconciliation_required)

        # No further send is possible for it.
        with patch("outreach.views.EmailMessage.send") as mock_send:
            self.post("mark_email_draft_sent", draft)
            mock_send.assert_not_called()

    @patch("outreach.views.EmailMessage.send")
    def test_archive_between_check_and_claim_prevents_the_send(self, mock_send):
        # Ordered simulation of a race: the organisation is archived
        # after the early archived check but before the send is claimed.
        draft = self.approved()
        real_validate = __import__(
            "django.core.validators", fromlist=["validate_email"]
        ).validate_email

        def archive_then_validate(value):
            Bank.objects.filter(pk=self.bank.pk).update(is_archived=True)
            return real_validate(value)

        self.client.force_login(self.staff)

        with patch("outreach.views.validate_email", archive_then_validate):
            self.post("mark_email_draft_sent", draft)

        mock_send.assert_not_called()
        draft.refresh_from_db()
        self.bank.refresh_from_db()
        self.assertEqual(draft.workflow_status, "approved")
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")
        self.assertFalse(
            draft.workflow_history.filter(action="send_started").exists()
        )

    def test_edit_never_overwrites_a_concurrent_contact_status_change(self):
        # Ordered simulation: the organisation is contacted while the
        # edit form is being processed.
        self.client.force_login(self.admin)

        def contacted_meanwhile(*args, **kwargs):
            Bank.objects.filter(pk=self.bank.pk).update(
                contact_status="contacted"
            )
            return None

        with patch("outreach.views._find_exact_duplicate", contacted_meanwhile):
            self.client.post(
                reverse(
                    "edit_organisation",
                    args=[self.content_type.pk, self.bank.pk],
                ),
                {
                    "bank_name": "Edited While Contacted",
                    "state": "VIC",
                    "region": "Victoria",
                    "suburb": "Ballarat",
                    "postcode": "3350",
                    "public_email": "roles@example.com",
                },
            )

        self.bank.refresh_from_db()
        self.assertEqual(self.bank.bank_name, "Edited While Contacted")
        self.assertEqual(self.bank.contact_status, "contacted")

    def test_edit_never_undoes_a_concurrent_archive(self):
        self.client.force_login(self.admin)

        def archived_meanwhile(*args, **kwargs):
            Bank.objects.filter(pk=self.bank.pk).update(is_archived=True)
            return None

        with patch("outreach.views._find_exact_duplicate", archived_meanwhile):
            self.client.post(
                reverse(
                    "edit_organisation",
                    args=[self.content_type.pk, self.bank.pk],
                ),
                {
                    "bank_name": "Should Not Save",
                    "state": "VIC",
                    "region": "Victoria",
                    "suburb": "Ballarat",
                    "postcode": "3350",
                    "public_email": "roles@example.com",
                },
            )

        self.bank.refresh_from_db()
        self.assertTrue(self.bank.is_archived)
        self.assertEqual(self.bank.bank_name, "Roles Community Bank")

    def test_history_and_delivery_evidence_survive_archiving(self):
        draft = self.approved()
        with patch("outreach.views.EmailMessage.send", return_value=1):
            self.client.force_login(self.staff)
            self.post("mark_email_draft_sent", draft)

        before = draft.workflow_history.count()
        self.archive()

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sent")
        self.assertIsNotNone(draft.sent_at)
        self.assertEqual(draft.workflow_history.count(), before)


@override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
class NoTransactionDuringSmtpTests(TransactionTestCase):
    def test_send_claim_is_committed_before_smtp(self):
        admin = make_user("tx-admin@example.com", "admin")
        bank = Bank.objects.create(
            bank_name="Tx Bank", region="Victoria", state="VIC",
            suburb="Ballarat", postcode="3350",
            public_email="tx@example.com",
        )
        content_type = ContentType.objects.get_for_model(Bank)
        opportunity = Opportunity.objects.create(
            content_type=content_type, object_id=bank.pk,
            status="not_yet_contacted",
        )
        draft = EmailDraft.objects.create(
            opportunity=opportunity, recipient_email="tx@example.com",
            subject="S", body="Dear team, let us know. Regards.",
            workflow_status="approved", requested_by=admin,
            approved_by=admin, approved_at=timezone.now(),
            approved_version=1, is_incomplete=False,
        )

        observed = {}

        def fake_send(*args, **kwargs):
            observed["in_atomic_block"] = connection.in_atomic_block
            observed["status_visible"] = EmailDraft.objects.get(
                pk=draft.pk
            ).workflow_status
            return 1

        self.client.force_login(admin)

        with patch("outreach.views.EmailMessage.send", fake_send):
            self.client.post(
                reverse("mark_email_draft_sent", args=[draft.draft_id]),
                {"version": 1},
            )

        self.assertFalse(observed["in_atomic_block"])
        self.assertEqual(observed["status_visible"], "sending")


class AdminEntryPointTests(WorkflowBase):
    def setUp(self):
        super().setUp()
        self.dev = make_user(
            "dev-admin@example.com", "admin", is_staff=True, is_superuser=True
        )
        self.client.force_login(self.dev)

    def test_opportunities_are_read_only_in_django_admin(self):
        Opportunity.objects.filter(pk=self.opportunity.pk).update(
            status="do_not_contact"
        )
        url = f"/admin/outreach/opportunity/{self.opportunity.pk}/change/"

        self.assertEqual(self.client.get(url).status_code, 200)  # view only
        response = self.client.post(url, {"status": "not_yet_contacted"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.get("/admin/outreach/opportunity/add/").status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/admin/outreach/opportunity/{self.opportunity.pk}/delete/",
                {"post": "yes"},
            ).status_code,
            403,
        )

        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.status, "do_not_contact")

    def test_organisation_status_and_archive_state_cannot_be_edited(self):
        url = f"/admin/outreach/bank/{self.bank.pk}/change/"
        page = self.client.get(url)

        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="contact_status"')
        self.assertNotContains(page, 'name="is_archived"')

        self.client.post(
            url,
            {
                "bank_name": "Admin Corrected Name",
                "region": "Victoria",
                "state": "VIC",
                "contact_status": "contacted",
                "is_archived": "on",
                "website_url": "", "address": "", "suburb": "Ballarat",
                "postcode": "3350", "public_email": "roles@example.com",
                "public_phone": "", "source_url": "",
            },
        )

        self.bank.refresh_from_db()
        self.assertEqual(self.bank.bank_name, "Admin Corrected Name")
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")
        self.assertFalse(self.bank.is_archived)

    def test_admin_edit_does_not_overwrite_status_with_a_stale_form(self):
        from django.contrib import admin as django_admin
        from outreach.admin import BankAdmin

        stale = Bank.objects.get(pk=self.bank.pk)
        Bank.objects.filter(pk=self.bank.pk).update(contact_status="contacted")

        class FakeForm:
            changed_data = ["bank_name"]

        stale.bank_name = "Renamed"
        BankAdmin(Bank, django_admin.site).save_model(
            None, stale, FakeForm(), change=True
        )

        self.bank.refresh_from_db()
        self.assertEqual(self.bank.bank_name, "Renamed")
        self.assertEqual(self.bank.contact_status, "contacted")

    def test_archived_organisations_and_their_contacts_are_view_only(self):
        Bank.objects.filter(pk=self.bank.pk).update(is_archived=True)
        contact = Contact.objects.create(
            content_type=self.content_type,
            object_id=self.bank.pk,
            contact_name="Kept Contact",
        )

        bank_url = f"/admin/outreach/bank/{self.bank.pk}/change/"
        contact_url = f"/admin/outreach/contact/{contact.pk}/change/"

        self.assertEqual(self.client.get(bank_url).status_code, 200)
        self.assertEqual(
            self.client.post(bank_url, {"bank_name": "X", "region": "Y"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(contact_url, {"contact_name": "Changed"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/admin/outreach/contact/{contact.pk}/delete/", {"post": "yes"}
            ).status_code,
            403,
        )

        contact.refresh_from_db()
        self.assertEqual(contact.contact_name, "Kept Contact")

    def test_organisations_cannot_be_added_in_django_admin(self):
        for model in ("bank", "branch", "club"):
            self.assertEqual(
                self.client.get(f"/admin/outreach/{model}/add/").status_code,
                403,
                model,
            )

    def test_admin_email_change_still_invalidates_pending_approvals(self):
        draft = self.approved()

        self.client.post(
            f"/admin/outreach/bank/{self.bank.pk}/change/",
            {
                "bank_name": "Roles Community Bank", "region": "Victoria",
                "state": "VIC", "website_url": "", "address": "",
                "suburb": "Ballarat", "postcode": "3350",
                "public_email": "different@example.com",
                "public_phone": "", "source_url": "",
            },
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertIsNone(draft.approved_by)

    def test_staff_role_cannot_reach_any_admin_entry_point(self):
        self.client.force_login(
            make_user("sneaky@example.com", "staff", is_staff=True,
                      is_superuser=True)
        )

        for path in (
            "/admin/outreach/opportunity/",
            f"/admin/outreach/bank/{self.bank.pk}/change/",
            "/admin/outreach/contact/",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn("/admin/login/", response["Location"])


class RoleFixtureHelperTests(TestCase):
    """The legacy permission-to-role test helper must be explicit."""

    def grant(self, user, *codenames):
        from django.contrib.auth.models import Permission

        user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="outreach",
                codename__in=codenames,
            )
        )
        sync_role_with_permissions(user)
        user.refresh_from_db()

    def test_only_admin_level_permissions_produce_admin(self):
        cases = {
            ("generate_emaildraft",): "staff",
            ("generate_emaildraft", "send_emaildraft"): "staff",
            ("change_opportunity", "view_bank"): "staff",
            ("approve_emaildraft",): "admin",
            ("add_bank",): "admin",
        }

        for index, (codenames, expected) in enumerate(cases.items()):
            user = make_user(f"fixture{index}@example.com", "staff")
            self.grant(user, *codenames)
            self.assertEqual(user.role, expected, codenames)

    def test_no_permissions_means_no_recognised_role(self):
        user = make_user("nobody@example.com", "staff")
        sync_role_with_permissions(user)
        user.refresh_from_db()

        self.assertEqual(user.role, "")
        self.assertFalse(user.has_perm("outreach.generate_emaildraft"))

    def test_plain_staff_fixtures_are_not_promoted(self):
        user = make_user("plain@example.com", "staff")

        self.assertFalse(user.is_app_admin)
        self.assertFalse(user.has_perm("outreach.approve_emaildraft"))
