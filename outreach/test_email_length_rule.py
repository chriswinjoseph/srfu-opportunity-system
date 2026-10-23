from django.test import SimpleTestCase
from django.urls import reverse

from outreach.models import EmailDraft, EmailTemplate
from outreach.services import (
    count_email_words,
    email_word_count_issue,
    validate_generated_email,
)
from outreach.test_roles_and_organisations import WorkflowBase

SIGNATURE = "SRFU Team\nSafe Roads For Us"


def body_with_words(total, signature=""):
    """A body that passes every other check, with exactly `total` words
    before the signature."""
    opening = "Dear team, please let us know if you are available."
    closing = "Kind regards,"
    fixed = len(opening.split()) + len(closing.split())
    text = f"{opening} {' '.join(['road'] * (total - fixed))} {closing}"
    assert len(text.split()) == total

    return f"{text} {signature}".strip() if signature else text


def issues_for(body, signature=""):
    _incomplete, issues = validate_generated_email("Subject", body, signature)
    return [issue for issue in issues if "word count" in issue.lower()]


class WordCountRuleTests(SimpleTestCase):
    def test_boundaries_are_inclusive(self):
        for words, ok in ((89, False), (90, True), (120, True), (121, False)):
            with self.subTest(words=words):
                self.assertEqual(issues_for(body_with_words(words)) == [], ok)

    def test_old_range_no_longer_applies(self):
        self.assertEqual(issues_for(body_with_words(100)), [])
        self.assertNotEqual(issues_for(body_with_words(130)), [])
        self.assertNotEqual(issues_for(body_with_words(150)), [])

    def test_signature_is_not_counted(self):
        # 120 words plus a 6-word signature is still 120.
        body = body_with_words(120, SIGNATURE)
        self.assertEqual(len(body.split()), 126)
        self.assertEqual(count_email_words(body, SIGNATURE), 120)
        self.assertEqual(issues_for(body, SIGNATURE), [])

        # 121 words plus the signature is too long.
        self.assertNotEqual(issues_for(body_with_words(121, SIGNATURE), SIGNATURE), [])

        # 89 words plus the signature would reach 95 if it were counted.
        self.assertNotEqual(issues_for(body_with_words(89, SIGNATURE), SIGNATURE), [])

    def test_text_that_is_not_the_closing_signature_is_counted(self):
        # The signature is excluded only when it closes the body.
        body = body_with_words(121) + " extra"
        self.assertEqual(count_email_words(body, "Kind regards,"), 122)

    def test_no_signature_means_the_whole_body_is_counted(self):
        self.assertEqual(count_email_words(body_with_words(100), ""), 100)

    def test_message_states_the_required_range(self):
        message = email_word_count_issue(body_with_words(80))

        self.assertIn("80", message)
        self.assertIn("90", message)
        self.assertIn("120", message)
        self.assertIn("excluding the signature", message)
        self.assertEqual(email_word_count_issue(body_with_words(100)), "")


class PromptTests(SimpleTestCase):
    def test_prompt_asks_for_90_to_120_words(self):
        import inspect

        from outreach import services

        source = inspect.getsource(services.generate_outreach_email)

        self.assertIn("between 90 and 120 words inclusive", source)
        self.assertNotIn("120 to 150", source)


class ServerSideEnforcementTests(WorkflowBase):
    """Direct requests cannot get around the length rule."""

    def template(self):
        return EmailTemplate.objects.create(
            name="Intro", version="v1", purpose="Outreach",
            template_body="Body", sender_name="SRFU Team",
            sender_role="Coordinator", project_details="Details",
            call_to_action="Reply", signature=SIGNATURE, is_active=True,
        )

    def short_draft(self, status="draft", words=40, owner=None):
        draft = self.draft(status, owner)
        EmailDraft.objects.filter(pk=draft.pk).update(
            body=body_with_words(words), is_incomplete=False
        )
        draft.refresh_from_db()

        return draft

    def test_manual_draft_is_validated_when_created(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("create_manual_email_draft", args=[self.content_type.pk, self.bank.pk]),
            {
                "subject": "Hi",
                "body": body_with_words(40),
                "outreach_purpose": "Collaboration",
            },
        )

        self.assertEqual(response.status_code, 302)
        draft = EmailDraft.objects.get(trigger_source="manual_draft")
        self.assertTrue(draft.is_incomplete)
        self.assertIn("word count", draft.validation_issues.lower())

    def test_valid_manual_draft_is_complete(self):
        self.client.force_login(self.staff)

        self.client.post(
            reverse("create_manual_email_draft", args=[self.content_type.pk, self.bank.pk]),
            {
                "subject": "Hi",
                "body": body_with_words(100),
                "outreach_purpose": "Collaboration",
            },
        )

        draft = EmailDraft.objects.get(trigger_source="manual_draft")
        self.assertFalse(draft.is_incomplete)

    def test_edit_applies_the_rule(self):
        draft = self.draft(owner=self.staff)
        self.client.force_login(self.staff)

        for words, incomplete in ((89, True), (90, False), (120, False), (121, True)):
            with self.subTest(words=words):
                draft.refresh_from_db()
                self.post(
                    "update_email_draft", draft,
                    subject="Hello", body=body_with_words(words),
                )
                draft.refresh_from_db()
                self.assertEqual(draft.is_incomplete, incomplete)

    def test_direct_submit_of_a_short_draft_is_refused(self):
        # is_incomplete was never set (or was cleared) but the text is short.
        draft = self.short_draft()
        self.client.force_login(self.staff)

        response = self.post("submit_email_draft_for_review", draft)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")
        self.assertEqual(response.status_code, 302)

    def test_direct_submit_of_an_over_length_draft_is_refused(self):
        draft = self.short_draft(words=121)
        self.client.force_login(self.staff)

        self.post("submit_email_draft_for_review", draft)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

    def test_direct_submit_of_a_valid_length_draft_still_works(self):
        for words in (90, 120):
            with self.subTest(words=words):
                draft = self.short_draft(words=words)
                self.client.force_login(self.staff)

                self.post("submit_email_draft_for_review", draft)

                draft.refresh_from_db()
                self.assertEqual(draft.workflow_status, "awaiting_approval")
                EmailDraft.objects.filter(pk=draft.pk).delete()

    def test_save_and_submit_of_a_short_draft_is_refused(self):
        draft = self.draft(owner=self.staff)
        self.client.force_login(self.staff)

        self.post(
            "save_and_submit_email_draft", draft,
            subject="Hello", body=body_with_words(40),
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

    def test_direct_approval_of_a_wrong_length_draft_is_refused(self):
        for words in (40, 121):
            with self.subTest(words=words):
                draft = self.short_draft("awaiting_approval", words=words)
                self.client.force_login(self.admin)

                self.post("approve_email_draft", draft)

                draft.refresh_from_db()
                self.assertEqual(draft.workflow_status, "awaiting_approval")
                self.assertIsNone(draft.approved_at)
                EmailDraft.objects.filter(pk=draft.pk).delete()

    def test_approval_of_a_valid_length_draft_still_works(self):
        draft = self.short_draft("awaiting_approval", words=100)
        self.client.force_login(self.admin)

        self.post("approve_email_draft", draft)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "approved")

    def test_template_signature_is_excluded_on_submit(self):
        # 120 words plus the 6-word signature is 126 in total: valid.
        draft = self.draft(owner=self.staff, template=self.template())
        EmailDraft.objects.filter(pk=draft.pk).update(
            body=body_with_words(120, SIGNATURE), is_incomplete=False
        )
        self.client.force_login(self.staff)

        self.post("submit_email_draft_for_review", draft)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")

    def test_template_draft_too_short_without_its_signature_is_refused(self):
        # 89 words plus the 6-word signature is 95 in total, but only 89 count.
        draft = self.draft(owner=self.staff, template=self.template())
        EmailDraft.objects.filter(pk=draft.pk).update(
            body=body_with_words(89, SIGNATURE), is_incomplete=False
        )
        self.client.force_login(self.staff)

        self.post("submit_email_draft_for_review", draft)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")


class LengthNoteTests(WorkflowBase):
    """The screens explain the rule the same way the server applies it."""

    def test_manual_draft_screens_say_every_word_is_counted(self):
        draft = self.draft(owner=self.staff)
        self.client.force_login(self.staff)

        for url in (
            reverse("email_modal", args=[self.content_type.pk, self.bank.pk]),
            reverse("organisation_detail", args=[self.content_type.pk, self.bank.pk]),
        ):
            with self.subTest(url=url):
                page = self.client.get(url)

                self.assertContains(page, "90&ndash;120 words")
                self.assertContains(page, "every word is counted")
                self.assertNotContains(page, "template signature at the very end")

    def test_template_draft_screens_say_the_final_signature_is_not_counted(self):
        template = EmailTemplate.objects.create(
            name="Intro", version="v1", purpose="Outreach",
            template_body="Body", sender_name="SRFU Team",
            sender_role="Coordinator", project_details="Details",
            call_to_action="Reply", signature=SIGNATURE, is_active=True,
        )
        self.draft(owner=self.staff, template=template)
        self.client.force_login(self.staff)

        for url in (
            reverse("email_modal", args=[self.content_type.pk, self.bank.pk]),
            reverse("organisation_detail", args=[self.content_type.pk, self.bank.pk]),
        ):
            with self.subTest(url=url):
                page = self.client.get(url)

                self.assertContains(page, "90&ndash;120 words")
                self.assertContains(page, "template signature at the very end")
                self.assertNotContains(page, "every word is counted")
