from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import services
from outreach.approvals import get_admin_recipients, get_available_approvers
from outreach.models import (
    Bank,
    Club,
    EmailDraft,
    Opportunity,
)

User = get_user_model()

PASSWORD = "Testing123!"


def make_user(email, role, **extra):
    return User.objects.create_user(
        email=email,
        first_name=extra.pop("first_name", "Test"),
        last_name=extra.pop("last_name", "User"),
        password=PASSWORD,
        role=role,
        **extra,
    )


class WorkflowBase(TestCase):
    def setUp(self):
        self.admin = make_user(
            "admin@example.com", "admin",
            first_name="Alex", last_name="Smith",
        )
        self.admin2 = make_user("admin2@example.com", "admin")
        self.staff = make_user(
            "staff@example.com", "staff",
            first_name="Sam", last_name="Staff",
        )
        self.staff2 = make_user("staff2@example.com", "staff")

        self.bank = Bank.objects.create(
            bank_name="Roles Community Bank",
            region="Victoria",
            state="VIC",
            suburb="Ballarat",
            postcode="3350",
            public_email="roles@example.com",
            contact_status="not_yet_contacted",
        )
        self.content_type = ContentType.objects.get_for_model(Bank)
        self.opportunity = Opportunity.objects.create(
            content_type=self.content_type,
            object_id=self.bank.pk,
            status="not_yet_contacted",
        )

    def draft(self, status="draft", owner=None, **extra):
        draft = EmailDraft.objects.create(
            opportunity=self.opportunity,
            recipient_email=self.bank.public_email,
            subject="Hello",
            body="Dear team, please let us know. Kind regards, SRFU.",
            outreach_purpose="Collaboration",
            workflow_status=status,
            generation_status="success",
            requested_by=owner or self.staff,
            trigger_source="manual",
            is_incomplete=False,
            **extra,
        )

        if status == "awaiting_approval":
            draft.submitted_at = timezone.now()
            draft.save(update_fields=["submitted_at"])

        return draft

    def approved(self, owner=None):
        draft = self.draft("approved", owner)
        draft.approved_by = self.admin
        draft.approved_at = timezone.now()
        draft.approved_version = draft.version
        draft.save()
        return draft

    def detail_url(self):
        return reverse(
            "organisation_detail",
            args=[self.content_type.pk, self.bank.pk],
        )

    def post(self, name, draft, **data):
        data.setdefault("version", draft.version)
        return self.client.post(
            reverse(name, args=[draft.draft_id]), data
        )


class DraftOwnershipTests(WorkflowBase):
    def edit(self, draft, user):
        self.client.force_login(user)
        return self.post(
            "update_email_draft", draft, subject="Changed", body="Changed body"
        )

    def test_staff_cannot_edit_a_draft_owned_by_someone_else(self):
        draft = self.draft(owner=self.staff)

        response = self.edit(draft, self.staff2)

        draft.refresh_from_db()
        self.assertEqual(draft.subject, "Hello")
        self.assertEqual(draft.version, 1)
        self.assertEqual(response.status_code, 302)

    def test_owner_assignee_and_admin_can_edit(self):
        for user in (self.staff, self.admin):
            draft = self.draft(owner=self.staff)
            self.edit(draft, user)
            draft.refresh_from_db()
            self.assertEqual(draft.subject, "Changed", user.email)

        assigned = self.draft(owner=self.staff, assigned_to=self.staff2)
        self.edit(assigned, self.staff2)
        assigned.refresh_from_db()
        self.assertEqual(assigned.subject, "Changed")

    def test_assignment_keeps_the_creator_and_adds_the_assignee(self):
        draft = self.draft(owner=self.staff, assigned_to=self.staff2)

        # Creator identity is never overwritten by assignment.
        self.assertEqual(draft.requested_by, self.staff)

        for user in (self.staff, self.staff2):
            fresh = EmailDraft.objects.get(pk=draft.pk)
            self.edit(fresh, user)
            fresh.refresh_from_db()
            self.assertEqual(fresh.subject, "Changed", user.email)
            EmailDraft.objects.filter(pk=draft.pk).update(subject="Hello")

    def test_previous_assignee_and_unrelated_staff_are_blocked(self):
        previous = make_user("previous@example.com", "staff")
        unrelated = make_user("unrelated@example.com", "staff")
        draft = self.draft(owner=self.staff)

        services.reassign_unfinished_drafts(self.admin, self.staff, previous)
        services.reassign_unfinished_drafts(self.admin, previous, self.staff2)

        draft.refresh_from_db()
        self.assertEqual(draft.requested_by, self.staff)
        self.assertEqual(draft.assigned_to, self.staff2)

        for user in (previous, unrelated):
            self.edit(draft, user)
            draft.refresh_from_db()
            self.assertEqual(draft.subject, "Hello", user.email)
            self.assertFalse(draft.user_can_modify(user))

        self.assertTrue(draft.user_can_modify(self.staff))
        self.assertTrue(draft.user_can_modify(self.staff2))
        self.assertTrue(draft.user_can_modify(self.admin))

    def test_disabled_users_are_blocked_regardless_of_ownership(self):
        draft = self.draft(owner=self.staff, assigned_to=self.staff2)

        services.disable_user(self.admin, self.staff)
        services.disable_user(self.admin, self.staff2)

        for user in (self.staff, self.staff2):
            user.refresh_from_db()
            self.assertFalse(draft.user_can_modify(user))

    def test_assignee_keeps_state_and_version_restrictions(self):
        assignee_draft = self.draft(owner=self.staff, assigned_to=self.staff2)
        self.client.force_login(self.staff2)

        # A stale version is rejected for the assignee too.
        self.client.post(
            reverse("update_email_draft", args=[assignee_draft.draft_id]),
            {"version": 99, "subject": "Stale", "body": "Stale body"},
        )
        assignee_draft.refresh_from_db()
        self.assertEqual(assignee_draft.subject, "Hello")

        # A sent draft cannot be edited by anyone.
        sent = self.draft("sent", owner=self.staff, assigned_to=self.staff2)
        self.post("update_email_draft", sent, subject="Nope", body="Nope")
        sent.refresh_from_db()
        self.assertEqual(sent.subject, "Hello")
        self.assertEqual(sent.workflow_status, "sent")

    def test_reassignment_lists_follow_the_effective_owner(self):
        draft = self.draft(owner=self.staff)

        services.reassign_unfinished_drafts(self.admin, self.staff, self.staff2)

        self.assertNotIn(draft, services.unfinished_drafts_for(self.staff))
        self.assertIn(draft, services.unfinished_drafts_for(self.staff2))

    def test_staff_cannot_submit_withdraw_or_cancel_others_drafts(self):
        self.client.force_login(self.staff2)

        draft = self.draft(owner=self.staff)
        self.post("submit_email_draft_for_review", draft)
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

        awaiting = self.draft("awaiting_approval", owner=self.staff)
        self.post("withdraw_email_draft", awaiting)
        awaiting.refresh_from_db()
        self.assertEqual(awaiting.workflow_status, "awaiting_approval")

        self.post("cancel_email_draft", draft)
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

    def test_owner_can_submit_and_edit_controls_hidden_from_others(self):
        draft = self.draft(owner=self.staff)

        self.client.force_login(self.staff)
        page = self.client.get(self.detail_url())
        self.assertContains(
            page, reverse("update_email_draft", args=[draft.draft_id])
        )

        self.client.force_login(self.staff2)
        page = self.client.get(self.detail_url())
        self.assertNotContains(
            page, reverse("update_email_draft", args=[draft.draft_id])
        )
        self.assertNotContains(
            page,
            reverse("submit_email_draft_for_review", args=[draft.draft_id]),
        )
        self.assertContains(page, "only its owner or an Admin")


class ApprovalPermissionTests(WorkflowBase):
    def test_staff_cannot_approve_or_reject_and_draft_is_unchanged(self):
        draft = self.draft("awaiting_approval", owner=self.staff)
        self.client.force_login(self.staff)

        self.post("approve_email_draft", draft)
        self.post("reject_email_draft", draft, rejection_reason="No")

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertIsNone(draft.approved_by)

    def test_approval_controls_hidden_from_staff_and_shown_to_admin(self):
        draft = self.draft("awaiting_approval", owner=self.staff)
        approve_url = reverse("approve_email_draft", args=[draft.draft_id])

        self.client.force_login(self.staff)
        self.assertNotContains(
            self.client.get(self.detail_url()), approve_url
        )

        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.detail_url()), approve_url)

    def test_pending_approvals_is_admin_only(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("pending_approvals"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "You do not have permission to access this page.",
            status_code=403,
        )

        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("pending_approvals")).status_code, 200
        )

    @patch("outreach.views.EmailMessage.send")
    def test_admin_approves_own_draft_without_sending(self, mock_send):
        draft = self.draft("awaiting_approval", owner=self.admin)
        self.client.force_login(self.admin)

        self.post("approve_email_draft", draft)

        draft.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(draft.workflow_status, "approved")
        self.assertEqual(draft.approved_by, self.admin)
        self.assertEqual(draft.approved_version, draft.version)
        mock_send.assert_not_called()
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")

    def test_admin_submit_then_approve_is_required(self):
        draft = self.draft("draft", owner=self.admin)
        self.client.force_login(self.admin)

        self.post("approve_email_draft", draft)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

    def test_editing_an_approved_draft_removes_the_approval(self):
        draft = self.approved(owner=self.staff)

        self.client.force_login(self.staff)
        self.post("update_email_draft", draft, subject="New", body="New body")

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertIsNone(draft.approved_by)
        self.assertIsNone(draft.approved_version)

    def test_approvers_and_notifications_follow_the_admin_role(self):
        make_user(
            "legacy@example.com", "staff", is_superuser=True, is_staff=True
        )
        pending = make_user("pend@example.com", "admin")
        pending.invitation_pending = True
        pending.save()
        disabled = make_user("off@example.com", "admin", is_active=False)

        approvers = set(get_available_approvers())

        self.assertEqual(approvers, {self.admin, self.admin2})
        self.assertNotIn(disabled, approvers)
        self.assertEqual(
            sorted(get_admin_recipients()),
            ["admin2@example.com", "admin@example.com"],
        )


@override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
class SendingTests(WorkflowBase):
    @patch("outreach.views.EmailMessage.send")
    def test_staff_sends_admin_approved_draft_and_others_see_who_and_when(
        self, mock_send
    ):
        mock_send.return_value = 1
        draft = self.approved(owner=self.staff)

        self.client.force_login(self.staff)
        self.post("mark_email_draft_sent", draft)

        draft.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(draft.workflow_status, "sent")
        self.assertEqual(draft.sent_by, self.staff)
        self.assertIsNotNone(draft.sent_at)
        self.assertEqual(self.bank.contact_status, "contacted")

        # Another user (an Admin) sees who sent it and when, and no
        # Send control.
        self.client.force_login(self.admin)
        page = self.client.get(self.detail_url())
        self.assertContains(page, "This email was already sent by Sam Staff on")
        self.assertContains(page, draft.sent_at.strftime("%Y"))
        self.assertNotContains(
            page, reverse("mark_email_draft_sent", args=[draft.draft_id])
        )

    @patch("outreach.views.EmailMessage.send")
    def test_uncertain_delivery_notifies_admins_and_blocks_resend(
        self, mock_send
    ):
        import smtplib

        mock_send.side_effect = smtplib.SMTPServerDisconnected("dropped")
        draft = self.approved()

        with patch("outreach.views.notify_admins") as notify:
            self.client.force_login(self.staff)
            self.post("mark_email_draft_sent", draft)
            self.client.force_login(self.admin)
            self.post("mark_email_draft_sent", draft)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sending")
        self.assertTrue(draft.reconciliation_required)
        self.assertEqual(mock_send.call_count, 1)
        notify.assert_called()
        self.bank.refresh_from_db()
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")

    @patch("outreach.views.EmailMessage.send")
    def test_confirmed_non_delivery_is_retryable_by_any_sender(
        self, mock_send
    ):
        import smtplib

        draft = self.approved()
        mock_send.side_effect = smtplib.SMTPConnectError(421, "down")

        self.client.force_login(self.staff)
        self.post("mark_email_draft_sent", draft)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "send_failed")

        mock_send.side_effect = None
        mock_send.return_value = 1
        self.client.force_login(self.admin)
        self.post("mark_email_draft_sent", draft)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sent")
        self.assertEqual(draft.sent_by, self.admin)

    @patch("outreach.views.EmailMessage.send")
    def test_second_sender_cannot_send_a_duplicate(self, mock_send):
        mock_send.return_value = 1
        draft = self.approved()

        self.client.force_login(self.admin)
        self.post("mark_email_draft_sent", draft)
        self.client.force_login(self.staff)
        self.post("mark_email_draft_sent", draft)

        self.assertEqual(mock_send.call_count, 1)

    @patch("outreach.views.EmailMessage.send")
    def test_staff_cannot_send_an_unapproved_draft(self, mock_send):
        draft = self.draft("awaiting_approval", owner=self.staff)

        self.client.force_login(self.staff)
        self.post("mark_email_draft_sent", draft)

        mock_send.assert_not_called()
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")

    def test_send_control_not_offered_for_unapproved_draft(self):
        draft = self.draft("awaiting_approval", owner=self.staff)

        self.client.force_login(self.staff)

        self.assertNotContains(
            self.client.get(self.detail_url()),
            reverse("mark_email_draft_sent", args=[draft.draft_id]),
        )


class OrganisationManagementTests(WorkflowBase):
    def edit_url(self):
        return reverse(
            "edit_organisation", args=[self.content_type.pk, self.bank.pk]
        )

    def archive_url(self):
        return reverse(
            "archive_organisation", args=[self.content_type.pk, self.bank.pk]
        )

    def payload(self, **overrides):
        data = {
            "bank_name": "Roles Community Bank",
            "state": "VIC",
            "region": "Victoria",
            "address": "",
            "suburb": "Ballarat",
            "postcode": "3350",
            "website_url": "",
            "public_email": "roles@example.com",
            "public_phone": "",
            "source_url": "",
        }
        data.update(overrides)
        return data

    def test_staff_cannot_edit_archive_or_add(self):
        self.client.force_login(self.staff)

        self.assertEqual(self.client.get(self.edit_url()).status_code, 403)
        response = self.client.post(
            self.edit_url(), self.payload(bank_name="Hacked")
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post(self.archive_url()).status_code, 403)

        self.bank.refresh_from_db()
        self.assertEqual(self.bank.bank_name, "Roles Community Bank")
        self.assertFalse(self.bank.is_archived)

        response = self.client.post(
            reverse("add_organisation"),
            dict(self.payload(bank_name="Staff Made"), organisation_type="bank"),
        )
        self.assertFalse(Bank.objects.filter(bank_name="Staff Made").exists())

    def test_staff_do_not_see_management_controls(self):
        self.client.force_login(self.staff)
        page = self.client.get(self.detail_url())

        self.assertNotContains(page, self.edit_url())
        self.assertNotContains(page, self.archive_url())
        self.assertNotContains(
            self.client.get(reverse("outreach_dashboard")),
            reverse("add_organisation"),
        )

        self.client.force_login(self.admin)
        page = self.client.get(self.detail_url())
        self.assertContains(page, self.edit_url())
        self.assertContains(page, self.archive_url())

    def test_admin_edits_and_contact_status_is_preserved(self):
        Bank.objects.filter(pk=self.bank.pk).update(contact_status="contacted")
        self.client.force_login(self.admin)

        response = self.client.post(
            self.edit_url(),
            self.payload(bank_name="Renamed Bank", public_phone="03 5333 1234"),
        )

        self.assertRedirects(response, self.detail_url())
        self.bank.refresh_from_db()
        self.assertEqual(self.bank.bank_name, "Renamed Bank")
        self.assertEqual(self.bank.contact_status, "contacted")

    def test_edit_validates_and_keeps_input(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.edit_url(),
            self.payload(bank_name="Typed Name", public_email="bad"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Typed Name")
        self.bank.refresh_from_db()
        self.assertEqual(self.bank.bank_name, "Roles Community Bank")

    def test_edit_cannot_create_an_exact_duplicate(self):
        Bank.objects.create(
            bank_name="Other Bank",
            region="Victoria",
            state="VIC",
            suburb="Ballarat",
            postcode="3350",
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            self.edit_url(), self.payload(bank_name="other bank")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.bank.refresh_from_db()
        self.assertEqual(self.bank.bank_name, "Roles Community Bank")

    def test_changing_the_email_invalidates_an_approved_draft(self):
        draft = self.approved()
        self.client.force_login(self.admin)

        self.client.post(
            self.edit_url(), self.payload(public_email="new@example.com")
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertIsNone(draft.approved_by)

    def test_archive_hides_and_blocks_contact(self):
        self.client.force_login(self.admin)

        self.client.post(self.archive_url())

        self.bank.refresh_from_db()
        self.assertTrue(self.bank.is_archived)
        self.assertEqual(self.bank.archived_by, self.admin)
        self.assertIsNotNone(self.bank.archived_at)

        self.assertNotContains(
            self.client.get(reverse("bank_list")), "Roles Community Bank"
        )
        self.assertNotContains(
            self.client.get(reverse("organisation_list_api")),
            "Roles Community Bank",
        )

        # Archived organisations cannot be edited or contacted.
        self.client.post(self.edit_url(), self.payload(bank_name="Nope"))
        self.bank.refresh_from_db()
        self.assertEqual(self.bank.bank_name, "Roles Community Bank")

        draft = self.draft("awaiting_approval", owner=self.admin)
        self.post("approve_email_draft", draft)
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")

        approved = self.approved()
        with patch("outreach.views.EmailMessage.send") as mock_send:
            self.post("mark_email_draft_sent", approved)
            mock_send.assert_not_called()

        # The record, its drafts and history are preserved.
        self.assertTrue(Bank.objects.filter(pk=self.bank.pk).exists())
        self.assertTrue(EmailDraft.objects.filter(pk=draft.pk).exists())

    def test_edit_works_for_clubs_and_archive_is_permission_checked(self):
        club = Club.objects.create(
            club_name="Roles Club",
            region="Victoria",
            state="VIC",
            suburb="Ballarat",
            postcode="3350",
        )
        club_ct = ContentType.objects.get_for_model(Club)

        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.post(
                reverse("archive_organisation", args=[club_ct.pk, club.pk])
            ).status_code,
            403,
        )

        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(
                reverse("edit_organisation", args=[club_ct.pk, club.pk])
            ).status_code,
            200,
        )
