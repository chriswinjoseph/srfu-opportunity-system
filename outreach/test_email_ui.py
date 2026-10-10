import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts import services
from outreach.models import (
    Bank,
    EmailDraft,
    EmailGenerationLog,
    EmailTemplate,
    Opportunity,
)
from outreach.test_roles_and_organisations import WorkflowBase, make_user

User = get_user_model()

# A body that passes the existing validation (greeting, call to action,
# closing, and 120-150 words).
GOOD_BODY = (
    "Dear team, we would like to talk with you about road safety in your "
    "community. Our volunteers work with local clubs, schools and "
    "businesses to share practical advice that helps families travel "
    "more safely every day. "
    + " ".join(["Together"] * 90)
    + " Please let us know if you are available to meet. Kind regards, SRFU."
)


class EmailUiBase(WorkflowBase):
    def modal_url(self, bank=None, **params):
        bank = bank or self.bank
        url = reverse("email_modal", args=[self.content_type.pk, bank.pk])
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{url}?{query}" if query else url

    def modal(self, user=None, **params):
        if user is not None:
            self.client.force_login(user)
        return self.client.get(self.modal_url(**params))

    def template_obj(self):
        return EmailTemplate.objects.create(
            name="UI Template", version="v1", purpose="Outreach",
            template_body="Body", sender_name="SRFU Team",
            sender_role="Coordinator", project_details="Details",
            call_to_action="Reply", signature="SRFU Team", is_active=True,
        )

    def state(self):
        return (
            EmailDraft.objects.count(),
            EmailGenerationLog.objects.count(),
            Bank.objects.get(pk=self.bank.pk).contact_status,
            Opportunity.objects.filter(pk=self.opportunity.pk)
            .values_list("status", flat=True)
            .first(),
        )


class DashboardEmailEntryTests(EmailUiBase):
    def test_dashboard_email_button_is_enabled_and_wired(self):
        self.client.force_login(self.staff)

        page = self.client.get(reverse("outreach_dashboard"))
        html = page.content.decode()

        self.assertNotContains(page, "Email workflow is not available yet.")
        self.assertContains(page, 'data-field="email-button"')
        self.assertContains(page, "data-email-modal-url-template")
        self.assertContains(page, 'id="emailModal"')
        self.assertContains(page, "email_modal.js")
        self.assertNotRegex(
            html, r'<button[^>]*disabled[^>]*>\s*Email\s*</button>'
        )

    def test_dashboard_js_posts_nothing_on_click(self):
        # The dashboard only ever opens the dialog with a GET request.
        from pathlib import Path

        script = Path("static/js/dashboard.js").read_text(encoding="utf-8")
        modal = Path("static/js/email_modal.js").read_text(encoding="utf-8")

        self.assertIn('method: "GET"', modal)
        self.assertNotIn('method: "POST"', modal)
        self.assertNotIn("fetch(", script.split("function openEmailDialog")[1]
                         .split("function createOrganisationCard")[0])

    def test_opening_and_reopening_changes_nothing_and_never_calls_ai(self):
        before = self.state()

        with patch("outreach.views.generate_outreach_email") as ai:
            for panel in ("", "generate", "preview", "reject", "send"):
                for user in (self.staff, self.admin):
                    response = self.modal(
                        user, **({"panel": panel} if panel else {})
                    )
                    self.assertEqual(response.status_code, 200)
            ai.assert_not_called()

        self.assertEqual(self.state(), before)

    def test_modal_is_get_only_and_requires_login(self):
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.post(self.modal_url()).status_code, 405
        )

        self.client.logout()
        response = self.client.get(self.modal_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_modal_shows_the_exact_organisation_and_recipient(self):
        other = Bank.objects.create(
            bank_name="Second Bank", region="Victoria", state="VIC",
            public_email="second@example.com",
            contact_status="not_yet_contacted",
        )
        first = self.modal(self.staff).content.decode()
        second = self.client.get(self.modal_url(bank=other)).content.decode()

        self.assertIn(f'data-org-key="{self.content_type.pk}-{self.bank.pk}"', first)
        self.assertIn("Roles Community Bank", first)
        self.assertIn("roles@example.com", first)
        self.assertNotIn("Second Bank", first)

        self.assertIn(f'data-org-key="{self.content_type.pk}-{other.pk}"', second)
        self.assertIn("second@example.com", second)
        self.assertNotIn("roles@example.com", second)

    def test_js_guards_against_stale_responses(self):
        from pathlib import Path

        modal = Path("static/js/email_modal.js").read_text(encoding="utf-8")

        self.assertIn("requestId !== requestCounter", modal)
        self.assertIn("controller.abort()", modal)
        self.assertIn("fragment.dataset.orgKey !== expectedKey", modal)


class ModalAvailabilityTests(EmailUiBase):
    def assert_unavailable(self, text):
        page = self.modal(self.staff)
        self.assertContains(page, text)
        self.assertNotContains(page, reverse(
            "create_manual_email_draft",
            args=[self.content_type.pk, self.bank.pk],
        ))
        self.assertNotContains(page, "Generate New Message")

    def test_no_draft_allows_compose_and_generate_when_permitted(self):
        page = self.modal(self.staff)

        self.assertContains(page, reverse(
            "create_manual_email_draft",
            args=[self.content_type.pk, self.bank.pk],
        ))
        self.assertContains(page, "Generate New Message")
        self.assertContains(page, "Save Draft")
        self.assertContains(page, "Purpose of outreach")
        # Name and recipient are read-only fields.
        self.assertRegex(page.content.decode(), r'id="em-name"[^>]*readonly')
        self.assertRegex(page.content.decode(), r'id="em-to"[^>]*readonly')

    def test_archived_organisation(self):
        Bank.objects.filter(pk=self.bank.pk).update(is_archived=True)
        self.assert_unavailable("archived")

    def test_do_not_contact(self):
        Opportunity.objects.filter(pk=self.opportunity.pk).update(
            status="do_not_contact"
        )
        self.assert_unavailable("Do Not Contact")

    def test_contacted_organisation_gets_no_new_initial_path(self):
        Bank.objects.filter(pk=self.bank.pk).update(contact_status="contacted")
        self.assert_unavailable("already been contacted")

    def test_missing_or_invalid_recipient(self):
        for value in ("", "not-an-email"):
            Bank.objects.filter(pk=self.bank.pk).update(public_email=value)
            self.assert_unavailable("valid recipient email")

    def test_contacted_organisation_keeps_read_only_history(self):
        draft = self.draft("sent", owner=self.staff)
        EmailDraft.objects.filter(pk=draft.pk).update(
            sent_by=self.admin, sent_at=timezone.now()
        )
        Bank.objects.filter(pk=self.bank.pk).update(contact_status="contacted")

        page = self.modal(self.staff)

        self.assertContains(page, "was already sent by")
        self.assertNotContains(page, "Save Draft")
        self.assertNotContains(page, reverse("update_email_draft", args=[draft.draft_id]))

    def test_server_stays_authoritative_if_the_dashboard_is_stale(self):
        # The dialog was opened while the organisation could be contacted;
        # it is then marked Do Not Contact. The POST is still refused.
        draft = self.draft(owner=self.staff)
        self.modal(self.staff)
        Opportunity.objects.filter(pk=self.opportunity.pk).update(
            status="do_not_contact"
        )

        self.post("save_and_submit_email_draft", draft,
                  subject="Hello", body=GOOD_BODY)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

    def test_disabled_user_cannot_open_the_dialog(self):
        services.disable_user(self.admin, self.staff)
        self.client.force_login(self.staff)

        response = self.client.get(self.modal_url())

        self.assertEqual(response.status_code, 403)


class ModalDraftStateTests(EmailUiBase):
    def test_owner_gets_an_editor_with_save_and_submit(self):
        draft = self.draft(owner=self.staff)
        # The template signature must appear as its own line in the body.
        EmailDraft.objects.filter(pk=draft.pk).update(
            body=GOOD_BODY + "\nSRFU Team", template=self.template_obj()
        )

        page = self.modal(self.staff)

        self.assertContains(page, reverse("update_email_draft", args=[draft.draft_id]))
        self.assertContains(page, reverse("save_and_submit_email_draft", args=[draft.draft_id]))
        self.assertContains(page, "Submit for Approval")
        self.assertContains(page, "Clear")
        # An AI-generated draft can be regenerated (with confirmation).
        self.assertContains(page, "Generate New Message")
        self.assertContains(page, "confirm_regenerate")
        self.assertNotContains(page, 'data-field="manual-draft-note"')

    def test_manual_draft_has_no_regeneration_option(self):
        # The server only regenerates AI drafts, so the dialog offers no
        # Generate button for a manual draft.
        self.draft(owner=self.staff)

        page = self.modal(self.staff)

        self.assertNotContains(page, "Generate New Message")
        self.assertNotContains(page, 'data-panel="generate"')
        self.assertContains(page, 'data-field="manual-draft-note"')
        self.assertContains(page, "written manually")

    def test_short_manual_draft_is_not_offered_for_submission(self):
        # Saved by the manual-create view without validation: the dialog
        # still checks it with the existing validation before offering Submit.
        draft = self.draft(owner=self.staff)
        EmailDraft.objects.filter(pk=draft.pk).update(body="Too short.")

        page = self.modal(self.staff)

        self.assertContains(page, "Validation issues")
        self.assertContains(page, "word count")
        self.assertNotContains(
            page, reverse("save_and_submit_email_draft", args=[draft.draft_id])
        )

        detail = self.client.get(self.detail_url())
        self.assertContains(detail, "Validation issues")
        self.assertNotContains(
            detail, reverse("save_and_submit_email_draft", args=[draft.draft_id])
        )

    def test_unrelated_staff_and_previous_assignee_see_read_only(self):
        draft = self.draft(owner=self.staff)
        previous = make_user("prev@example.com", "staff")
        services.reassign_unfinished_drafts(self.admin, self.staff, previous)
        services.reassign_unfinished_drafts(self.admin, previous, self.staff2)
        unrelated = make_user("unrel@example.com", "staff")

        for user in (previous, unrelated):
            page = self.modal(user)
            self.assertNotContains(page, reverse("update_email_draft", args=[draft.draft_id]))
            self.assertNotContains(page, "Submit for Approval")
            self.assertContains(page, "only its owner or an Admin")

        for user in (self.staff, self.staff2):
            page = self.modal(user)
            self.assertContains(page, reverse("update_email_draft", args=[draft.draft_id]))

    def test_pending_review_label_and_review_controls(self):
        draft = self.draft("awaiting_approval", owner=self.staff)
        approve = reverse("approve_email_draft", args=[draft.draft_id])
        reject = reverse("reject_email_draft", args=[draft.draft_id])

        staff_page = self.modal(self.staff)
        self.assertContains(staff_page, "Pending Review")
        self.assertNotContains(staff_page, approve)
        self.assertNotContains(staff_page, reject)
        self.assertNotContains(staff_page, "Request Changes")
        self.assertContains(staff_page, "Waiting for an Admin")

        admin_page = self.modal(self.admin)
        self.assertContains(admin_page, approve)
        self.assertContains(admin_page, reject)
        self.assertContains(admin_page, "Reject Reason/Comment")

    def test_approved_shows_approval_info_copy_and_separate_send(self):
        draft = self.approved(owner=self.staff)

        page = self.modal(self.staff)

        self.assertContains(page, "Approved by Alex Smith")
        self.assertContains(page, "Copy Recipient Email")
        self.assertContains(page, "Copy Subject")
        self.assertContains(page, "Copy Message")
        self.assertNotContains(page, "Copy Email")
        self.assertContains(page, reverse("mark_email_draft_sent", args=[draft.draft_id]))
        self.assertContains(page, "Send Email")

    def test_send_blocked_for_stale_approval_and_reconciliation(self):
        draft = self.approved(owner=self.staff)
        EmailDraft.objects.filter(pk=draft.pk).update(version=5)

        self.assertNotContains(
            self.modal(self.staff),
            reverse("mark_email_draft_sent", args=[draft.draft_id]),
        )

        sending = self.draft("sending", owner=self.staff)
        EmailDraft.objects.filter(pk=sending.pk).update(
            reconciliation_required=True,
            created_at=timezone.now() + timezone.timedelta(minutes=5),
        )
        page = self.modal(self.staff)
        self.assertNotContains(
            page, reverse("mark_email_draft_sent", args=[sending.draft_id])
        )
        self.assertContains(page, "cannot be sent again")

    def test_user_content_is_escaped(self):
        draft = self.draft(owner=self.staff)
        EmailDraft.objects.filter(pk=draft.pk).update(
            subject="<script>alert(1)</script>",
            body="</textarea><img src=x onerror=alert(2)>",
        )

        for user in (self.staff, self.staff2):
            html = self.modal(user).content.decode()
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertNotIn("<img src=x", html)

        detail = self.client.get(self.detail_url()).content.decode()
        self.assertNotIn("<script>alert(1)</script>", detail)
        self.assertNotIn("<img src=x", detail)


class SaveAndSubmitTests(EmailUiBase):
    def good_draft(self, **kw):
        draft = self.draft(**kw)
        EmailDraft.objects.filter(pk=draft.pk).update(body=GOOD_BODY)
        draft.refresh_from_db()
        return draft

    def test_submit_uses_the_content_visible_in_the_editor(self):
        draft = self.good_draft(owner=self.staff)
        self.client.force_login(self.staff)

        response = self.post(
            "save_and_submit_email_draft", draft,
            subject="Edited subject",
            body=GOOD_BODY + " Edited just now.",
            next="/outreach/dashboard/?open_email=1-2",
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertEqual(draft.subject, "Edited subject")
        self.assertTrue(draft.body.endswith("Edited just now."))
        self.assertEqual(response["Location"], "/outreach/dashboard/?open_email=1-2")
        self.assertIsNotNone(draft.submitted_at)

    def test_submit_failure_after_save_keeps_draft_and_says_so(self):
        from unittest import mock

        from django.contrib import messages as dj_messages

        draft = self.good_draft(owner=self.staff)
        self.client.force_login(self.staff)

        def failing_submit(request, draft_id):
            dj_messages.error(request, "Submission was refused.")
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect("/outreach/dashboard/")

        before = EmailDraft.objects.count()

        with mock.patch(
            "outreach.views.submit_email_draft_for_review", failing_submit
        ):
            response = self.post(
                "save_and_submit_email_draft", draft,
                subject="Saved subject", body=GOOD_BODY + " Kept.",
                next="/outreach/dashboard/?open_email=1-2",
            )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertEqual(draft.subject, "Saved subject")
        self.assertTrue(draft.body.endswith("Kept."))
        self.assertEqual(EmailDraft.objects.count(), before)
        self.assertIn("stash=", response["Location"])

        texts = [m.message for m in dj_messages.get_messages(response.wsgi_request)]
        self.assertTrue(any("saved as a draft" in t for t in texts))

        # Retry submits the same draft: still one draft, now pending.
        retry = self.post(
            "save_and_submit_email_draft", draft,
            subject="Saved subject", body=GOOD_BODY + " Kept.",
            next="/outreach/dashboard/?open_email=1-2",
        )
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertEqual(EmailDraft.objects.count(), before)

    def test_save_draft_saves_without_submitting(self):
        draft = self.good_draft(owner=self.staff)
        self.client.force_login(self.staff)

        self.post("update_email_draft", draft, subject="Only saved", body=GOOD_BODY)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertEqual(draft.subject, "Only saved")

    def test_stale_version_saves_and_submits_nothing(self):
        draft = self.good_draft(owner=self.staff)
        self.client.force_login(self.staff)

        self.client.post(
            reverse("save_and_submit_email_draft", args=[draft.draft_id]),
            {"version": 99, "subject": "Stale", "body": GOOD_BODY},
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertEqual(draft.subject, "Hello")

    def test_validation_failure_keeps_input_for_the_dialog(self):
        draft = self.good_draft(owner=self.staff)
        self.client.force_login(self.staff)

        response = self.post(
            "save_and_submit_email_draft", draft,
            subject="", body="Typed text I must not lose",
            next=f"/outreach/dashboard/?open_email={self.content_type.pk}-{self.bank.pk}",
            org_key=f"{self.content_type.pk}-{self.bank.pk}",
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertEqual(draft.subject, "Hello")
        self.assertIn("open_email=", response["Location"])

        token = re.search(r"stash=([\w-]+)", response["Location"]).group(1)
        page = self.client.get(self.modal_url(reopen=1, stash=token))

        self.assertContains(page, "Typed text I must not lose")
        self.assertContains(page, "Subject and email body are required.")

        # The saved input is used once, and never without its token.
        again = self.client.get(self.modal_url(stash=token))
        self.assertNotContains(again, "Typed text I must not lose")
        self.assertNotContains(
            self.client.get(self.modal_url()), "Typed text I must not lose"
        )

    def test_incomplete_content_is_saved_but_not_submitted(self):
        draft = self.good_draft(owner=self.staff)
        self.client.force_login(self.staff)

        self.post(
            "save_and_submit_email_draft", draft,
            subject="Subject", body="Dear [Name], hello.",
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertTrue(draft.is_incomplete)

        page = self.modal(self.staff)
        self.assertContains(page, "Validation issues")
        self.assertNotContains(
            page, reverse("save_and_submit_email_draft", args=[draft.draft_id])
        )

    def test_unrelated_staff_and_previous_assignee_are_denied(self):
        draft = self.good_draft(owner=self.staff)
        previous = make_user("prev2@example.com", "staff")
        services.reassign_unfinished_drafts(self.admin, self.staff, previous)
        services.reassign_unfinished_drafts(self.admin, previous, self.staff2)
        unrelated = make_user("unrel2@example.com", "staff")

        for user in (previous, unrelated):
            self.client.force_login(user)
            self.post("save_and_submit_email_draft", draft,
                      subject="Hijack", body=GOOD_BODY)
            draft.refresh_from_db()
            self.assertEqual(draft.workflow_status, "draft")
            self.assertEqual(draft.subject, "Hello")

        self.client.force_login(self.staff2)
        self.post("save_and_submit_email_draft", draft,
                  subject="By assignee", body=GOOD_BODY)
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertEqual(draft.requested_by, self.staff)

    def test_editing_an_approved_draft_invalidates_approval_and_can_be_reapproved(self):
        draft = self.approved(owner=self.admin)
        self.client.force_login(self.admin)

        self.post("save_and_submit_email_draft", draft,
                  subject="Changed after approval", body=GOOD_BODY)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertIsNone(draft.approved_by)
        self.assertIsNone(draft.approved_version)

        self.post("approve_email_draft", draft)
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "approved")
        self.assertEqual(draft.approved_by, self.admin)
        self.assertEqual(draft.approved_version, draft.version)

    def test_post_only_and_csrf_protected(self):
        draft = self.good_draft(owner=self.staff)
        self.client.force_login(self.staff)

        self.assertEqual(
            self.client.get(
                reverse("save_and_submit_email_draft", args=[draft.draft_id])
            ).status_code,
            405,
        )

        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.staff)
        response = strict.post(
            reverse("save_and_submit_email_draft", args=[draft.draft_id]),
            {"version": 1, "subject": "x", "body": GOOD_BODY},
        )
        self.assertEqual(response.status_code, 403)

    def test_unsafe_next_urls_are_ignored(self):
        for bad in (
            "https://evil.example/",
            "//evil.example/outreach/",
            "/accounts/login/",
            "javascript:alert(1)",
            "/outreach/\\evil",
            "",
        ):
            draft = self.good_draft(owner=self.staff)
            self.client.force_login(self.staff)

            response = self.post("update_email_draft", draft,
                                 subject="Safe", body=GOOD_BODY, next=bad)

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], self.detail_url(), bad)
            EmailDraft.objects.filter(pk=draft.pk).delete()

    def test_reject_requires_a_reason_and_creator_sees_feedback(self):
        draft = self.draft("awaiting_approval", owner=self.staff)
        self.client.force_login(self.admin)

        self.post("reject_email_draft", draft, rejection_reason="")
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")

        self.post("reject_email_draft", draft, rejection_reason="Needs fixing")
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "changes_requested")

        page = self.modal(self.staff)
        self.assertContains(page, "Needs fixing")
        self.assertContains(page, "Changes Requested")

        # The creator can edit and resubmit.
        self.post_as = self.client.force_login(self.staff)
        self.post("save_and_submit_email_draft", draft,
                  subject="Fixed", body=GOOD_BODY)
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")


class GenerationViaDialogTests(EmailUiBase):
    def setUp(self):
        super().setUp()
        self.template = self.template_obj()
        from django.core.cache import cache

        cache.clear()

    def generate(self, user, **extra):
        self.client.force_login(user)
        data = {
            "outreach_purpose": "Introduce our road safety program",
            "template_id": self.template.pk,
            "next": "/outreach/dashboard/?open_email=1-1&panel=preview",
            "org_key": f"{self.content_type.pk}-{self.bank.pk}",
            "panel_on_error": "generate",
        }
        data.update(extra)
        response = self.client.post(
            reverse("generate_email_draft", args=[self.content_type.pk, self.bank.pk]),
            data,
        )
        self.last_location = response["Location"]
        return response

    def ai_result(self, subject="Generated subject", incomplete=False):
        return (subject, GOOD_BODY, 10, 20, 30, incomplete, [])

    @patch("outreach.views.generate_outreach_email")
    def test_generation_creates_one_draft_and_shows_a_preview(self, ai):
        ai.return_value = self.ai_result()

        response = self.generate(self.staff)

        self.assertEqual(ai.call_count, 1)
        self.assertEqual(EmailDraft.objects.count(), 1)
        draft = EmailDraft.objects.get()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertEqual(draft.requested_by, self.staff)
        self.assertEqual(response["Location"], "/outreach/dashboard/?open_email=1-1&panel=preview")
        self.assertNotIn("stash=", response["Location"])

        page = self.client.get(self.modal_url(panel="preview"))
        self.assertContains(page, "Generated subject")
        self.assertContains(page, "Use This Draft")
        self.assertContains(page, "Generate Email Preview")

        # Using or viewing the draft does not approve, send or contact.
        self.bank.refresh_from_db()
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")
        self.assertEqual(EmailDraft.objects.count(), 1)
        self.assertEqual(ai.call_count, 1)

    @patch("outreach.views.generate_outreach_email")
    def test_second_generation_does_not_create_a_second_draft(self, ai):
        ai.return_value = self.ai_result()
        self.generate(self.staff)
        self.generate(self.staff)

        self.assertEqual(EmailDraft.objects.count(), 1)
        self.assertEqual(ai.call_count, 1)

    @patch("outreach.views.generate_outreach_email")
    def test_regeneration_needs_confirmation_and_keeps_history(self, ai):
        ai.return_value = self.ai_result("Version one")
        self.generate(self.staff)
        ai.return_value = self.ai_result("Version two")

        self.generate(self.staff, regenerate="1")
        self.assertEqual(EmailDraft.objects.count(), 1)

        self.generate(self.staff, regenerate="1", confirm_regenerate="1")

        drafts = list(EmailDraft.objects.order_by("created_at"))
        self.assertEqual([d.subject for d in drafts], ["Version one", "Version two"])
        self.assertEqual(drafts[1].version, 2)

    @patch("outreach.views.generate_outreach_email")
    def test_failure_keeps_purpose_shows_retry_and_hides_internals(self, ai):
        ai.side_effect = RuntimeError("secret internal stack detail")

        self.generate(self.staff)

        self.assertEqual(EmailDraft.objects.count(), 0)

        token = re.search(r"stash=([\w-]+)", self.last_location).group(1)
        page = self.client.get(self.modal_url(reopen=1, stash=token))
        html = page.content.decode()

        self.assertIn("Introduce our road safety program", html)
        self.assertIn('data-panel="generate"', html)
        self.assertNotIn("secret internal stack detail", html)
        self.assertNotIn("Traceback", html)
        self.assertRegex(html, r'data-initial-panel="generate"')

        # Retry works.
        ai.side_effect = None
        ai.return_value = self.ai_result()
        from django.core.cache import cache

        cache.clear()
        self.generate(self.staff)
        self.assertEqual(EmailDraft.objects.count(), 1)

    @patch("outreach.views.generate_outreach_email")
    def test_ownership_unavailable_states_and_permissions_still_apply(self, ai):
        ai.return_value = self.ai_result()

        Opportunity.objects.filter(pk=self.opportunity.pk).update(status="do_not_contact")
        self.generate(self.staff)
        Opportunity.objects.filter(pk=self.opportunity.pk).update(status="not_yet_contacted")
        Bank.objects.filter(pk=self.bank.pk).update(is_archived=True)
        self.generate(self.staff)
        Bank.objects.filter(pk=self.bank.pk).update(is_archived=False, contact_status="contacted")
        self.generate(self.staff)

        ai.assert_not_called()
        self.assertEqual(EmailDraft.objects.count(), 0)

    @patch("outreach.views.generate_outreach_email")
    def test_template_selection_never_authorises_sending(self, ai):
        ai.return_value = self.ai_result()
        self.generate(self.staff)
        draft = EmailDraft.objects.get()

        with patch("outreach.views.EmailMessage.send") as send:
            self.client.force_login(self.admin)
            self.post("mark_email_draft_sent", draft)
            send.assert_not_called()

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")


class OrganisationPageHistoryTests(EmailUiBase):
    def three_drafts(self):
        now = timezone.now()
        old_cancelled = self.draft("cancelled", owner=self.staff)
        middle = self.draft("draft", owner=self.staff)
        newest = self.draft("awaiting_approval", owner=self.staff)
        for index, draft in enumerate((old_cancelled, middle, newest)):
            EmailDraft.objects.filter(pk=draft.pk).update(
                created_at=now + timezone.timedelta(minutes=index),
                subject=f"Subject {index}",
            )
        return old_cancelled, middle, newest

    def test_rows_are_newest_first_with_correct_ids_and_actions(self):
        old, middle, newest = self.three_drafts()
        self.client.force_login(self.admin)

        html = self.client.get(self.detail_url()).content.decode()

        positions = [html.index(f'id="draft-{d.draft_id}"') for d in (newest, middle, old)]
        self.assertEqual(positions, sorted(positions))

        # Approve is offered only for the Pending Review draft, using its id.
        self.assertIn(reverse("approve_email_draft", args=[newest.draft_id]), html)
        self.assertNotIn(reverse("approve_email_draft", args=[middle.draft_id]), html)
        self.assertNotIn(reverse("approve_email_draft", args=[old.draft_id]), html)

        # The older Draft is superseded: read-only, not editable.
        self.assertNotIn(reverse("update_email_draft", args=[middle.draft_id]), html)
        self.assertIn("older version", html)
        # A cancelled draft has no actions at all.
        for name in ("update_email_draft", "cancel_email_draft", "mark_email_draft_sent"):
            self.assertNotIn(reverse(name, args=[old.draft_id]), html)

    def test_html_ids_are_unique_across_rows(self):
        self.three_drafts()
        self.client.force_login(self.admin)

        html = self.client.get(self.detail_url()).content.decode()
        ids = re.findall(r'\sid="([^"]+)"', html)

        self.assertEqual(len(ids), len(set(ids)), [i for i in ids if ids.count(i) > 1])

    def test_staff_never_get_approve_or_request_changes(self):
        _, _, newest = self.three_drafts()
        self.client.force_login(self.staff)

        html = self.client.get(self.detail_url()).content.decode()

        self.assertNotIn(reverse("approve_email_draft", args=[newest.draft_id]), html)
        self.assertNotIn(reverse("reject_email_draft", args=[newest.draft_id]), html)
        self.assertNotIn("Request Changes", html)
        self.assertIn("Pending Review", html)

    def test_selected_draft_is_opened_and_wrong_ids_are_ignored(self):
        old, middle, newest = self.three_drafts()
        self.client.force_login(self.admin)

        html = self.client.get(f"{self.detail_url()}?draft={middle.draft_id}").content.decode()
        self.assertRegex(html, rf'<details class="em-row" id="draft-{middle.draft_id}" open')
        self.assertNotRegex(html, rf'id="draft-{newest.draft_id}" open')

        bogus = self.client.get(f"{self.detail_url()}?draft=00000000-0000-0000-0000-000000000000")
        self.assertEqual(bogus.status_code, 200)

    def test_pending_approvals_opens_the_selected_older_draft(self):
        # The queue entry is not the newest historical entry.
        first = self.draft("awaiting_approval", owner=self.staff)
        newer = self.draft("cancelled", owner=self.staff)
        EmailDraft.objects.filter(pk=first.pk).update(submitted_at=timezone.now())
        EmailDraft.objects.filter(pk=newer.pk).update(
            created_at=timezone.now() + timezone.timedelta(minutes=5)
        )

        self.client.force_login(self.admin)
        queue = self.client.get(reverse("pending_approvals"))
        link = f"{self.detail_url()}?draft={first.draft_id}"

        self.assertContains(queue, f'href="{link}"')

        html = self.client.get(link).content.decode()
        self.assertRegex(html, rf'id="draft-{first.draft_id}" open')

        self.post("approve_email_draft", first)
        first.refresh_from_db()
        newer.refresh_from_db()
        self.assertEqual(first.workflow_status, "approved")
        self.assertEqual(newer.workflow_status, "cancelled")

    def test_history_has_no_per_row_query_growth(self):
        def query_count(rows):
            EmailDraft.objects.all().delete()
            for index in range(rows):
                draft = self.draft("cancelled", owner=self.staff)
                draft.workflow_history.create(
                    action="created", from_status="", to_status="draft",
                    version=1, performed_by=self.staff,
                )
            self.client.force_login(self.admin)
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(self.detail_url())
            return len(ctx)

        few, many = query_count(2), query_count(9)

        self.assertLessEqual(many, few + 2)

    def test_empty_state_labels_and_statuses_are_separate(self):
        self.client.force_login(self.staff)
        html = self.client.get(self.detail_url()).content.decode()

        self.assertIn("No emails found.", html)
        self.assertIn("Contact status:", html)
        self.assertIn("Not provided", html)
        self.assertIn("Organisation Name:", html)

        for status, label in (
            ("draft", "Draft"), ("awaiting_approval", "Pending Review"),
            ("changes_requested", "Changes Requested"), ("approved", "Approved"),
            ("sent", "Sent"), ("send_failed", "Send Failed"),
            ("cancelled", "Cancelled"), ("sending", "Sending"),
        ):
            EmailDraft.objects.all().delete()
            self.draft(status, owner=self.staff)
            self.assertIn(f"Status: {label}", self.client.get(self.detail_url()).content.decode())

    def test_copy_buttons_have_distinct_labels(self):
        self.draft("approved", owner=self.staff)
        self.client.force_login(self.staff)

        html = self.client.get(self.detail_url()).content.decode()

        self.assertIn("Copy Recipient Email", html)
        self.assertIn("Copy Subject", html)
        self.assertIn("Copy Message", html)
        self.assertNotIn("Copy Email", html)
        self.assertIn('aria-live="polite"', html)

    def test_cancel_requires_reason_and_keeps_history(self):
        draft = self.draft("draft", owner=self.staff)
        self.client.force_login(self.staff)

        self.post("cancel_email_draft", draft, cancellation_reason="")
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

        self.post("cancel_email_draft", draft, cancellation_reason="Not needed")
        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "cancelled")
        self.assertTrue(EmailDraft.objects.filter(pk=draft.pk).exists())
        self.assertTrue(draft.workflow_history.filter(action="cancelled").exists())

    def test_sent_row_shows_who_and_when_and_has_no_send(self):
        draft = self.approved(owner=self.staff)
        with patch("outreach.views.EmailMessage.send", return_value=1):
            self.client.force_login(self.staff)
            self.post("mark_email_draft_sent", draft)

        self.client.force_login(self.admin)
        html = self.client.get(self.detail_url()).content.decode()

        self.assertIn("Sent by:", html)
        self.assertIn("Sam Staff", html)
        self.assertNotIn(reverse("mark_email_draft_sent", args=[draft.draft_id]), html)

    def test_archived_organisation_rows_are_read_only(self):
        draft = self.draft("draft", owner=self.staff)
        Bank.objects.filter(pk=self.bank.pk).update(is_archived=True)
        self.client.force_login(self.admin)

        html = self.client.get(self.detail_url()).content.decode()

        self.assertNotIn(reverse("update_email_draft", args=[draft.draft_id]), html)
        self.assertNotIn(reverse("cancel_email_draft", args=[draft.draft_id]), html)
        self.assertIn("read-only", html)

    def test_navigation_and_sidebar_on_detail_page(self):
        self.client.force_login(self.admin)
        html = self.client.get(self.detail_url()).content.decode()
        nav = re.search(r'<nav class="topbar-nav".*?</nav>', html, re.S).group(0)

        self.assertLess(nav.index(reverse("outreach_dashboard")), nav.index(reverse("user_list")))
        self.assertIn('class="sidebar"', html)
        self.assertIn("Contact", html)

        self.client.force_login(self.staff)
        html = self.client.get(self.detail_url()).content.decode()
        nav = re.search(r'<nav class="topbar-nav".*?</nav>', html, re.S).group(0)
        self.assertNotIn(reverse("user_list"), nav)
        self.assertNotIn(reverse("edit_organisation", args=[self.content_type.pk, self.bank.pk]), html)

    def test_response_recording_and_external_outreach_are_preserved(self):
        Bank.objects.filter(pk=self.bank.pk).update(contact_status="contacted")
        Opportunity.objects.filter(pk=self.opportunity.pk).update(status="contacted")
        self.client.force_login(self.staff)

        html = self.client.get(self.detail_url()).content.decode()

        self.assertIn("Record Follow-Up Outreach", html)
        self.assertIn(reverse("record_response_view", args=[self.opportunity.pk]), html)
        self.assertIn("Record Not Interested", html)
