"""
Password-reset and invitation email failures: neutral responses, consistent state,
working retries, and logs that never carry secrets, links, addresses or raw errors.

All delivery is mocked or sent to the local test outbox; nothing leaves this machine.
"""

import re
import smtplib
import socket
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import UserActivity
from accounts.roles import ROLE_ADMIN, ROLE_STAFF

User = get_user_model()

PASSWORD = "Testing123!"
SECRET = "hunter2-smtp-secret"

FAILURES = {
    "authentication": smtplib.SMTPAuthenticationError(
        535, f"5.7.8 Username and Password not accepted {SECRET}".encode()
    ),
    "connection refused": ConnectionRefusedError(f"[WinError 10061] refused by smtp.{SECRET}.example"),
    "connect error": smtplib.SMTPConnectError(421, f"service not available {SECRET}"),
    "server disconnected": smtplib.SMTPServerDisconnected(f"Connection unexpectedly closed {SECRET}"),
    "recipient refused": smtplib.SMTPRecipientsRefused(
        {"person@example.org": (550, f"mailbox unavailable {SECRET}".encode())}
    ),
    "message rejected": smtplib.SMTPDataError(554, f"message rejected {SECRET}".encode()),
    "timeout": TimeoutError(f"timed out talking to {SECRET}"),
    "socket timeout": socket.timeout(f"timed out {SECRET}"),
    "unexpected error": RuntimeError(f"boom {SECRET}"),
}


def test_classification_is_safe_and_specific():
    from accounts.services import classify_email_failure

    expected = {
        "authentication": "authentication",
        "connection refused": "connection",
        "connect error": "connection",
        "server disconnected": "connection",
        "recipient refused": "recipient_refused",
        "message rejected": "smtp_rejected",
        "timeout": "timeout",
        "socket timeout": "timeout",
        "unexpected error": "other",
    }

    for name, error in FAILURES.items():
        kind, error_type, code = classify_email_failure(error)
        assert kind == expected[name], (name, kind)
        assert SECRET not in f"{kind} {error_type} {code}"


def link_in(text):
    return re.search(r"https?://\S+/accounts/reset/\S+", text).group(0)


def normalised(response):
    html = response.content.decode()
    return re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", html)


def fail_with(error):
    return patch("django.core.mail.EmailMessage.send", side_effect=error)


class ClassificationTests(TestCase):
    def test_classification_is_safe_and_specific(self):
        test_classification_is_safe_and_specific()


@override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
class PasswordResetFailureTests(TestCase):
    def setUp(self):
        self.eligible = User.objects.create_user("eligible@example.org", "El", "Igible", PASSWORD, role=ROLE_STAFF)
        self.disabled = User.objects.create_user("disabled@example.org", "Di", "Sabled", PASSWORD, role=ROLE_STAFF, is_active=False)
        self.pending = User.objects.create_user("pending@example.org", "Pe", "Nding", PASSWORD, role=ROLE_STAFF, invitation_pending=True)

    def request_reset(self, email):
        return self.client.post(reverse("forgot_password"), {"email": email})

    def test_every_smtp_failure_gives_the_neutral_page_not_a_500(self):
        for name, error in FAILURES.items():
            with self.subTest(failure=name):
                with fail_with(error):
                    response = self.request_reset("eligible@example.org")

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "If an account exists with that email")

    def test_response_is_identical_for_every_kind_of_address(self):
        with fail_with(FAILURES["authentication"]):
            failed = normalised(self.request_reset("eligible@example.org"))

        mail.outbox.clear()
        sent = normalised(self.request_reset("eligible@example.org"))
        self.assertEqual(len(mail.outbox), 1)
        others = [
            normalised(self.request_reset(address))
            for address in ("nobody@example.org", "disabled@example.org", "pending@example.org")
        ]

        for page in [failed] + others:
            self.assertEqual(page, sent)

        # Nothing was sent to the ineligible addresses.
        self.assertEqual(len(mail.outbox), 1)

    def test_a_failed_request_changes_no_account_state(self):
        before = (self.eligible.password, self.eligible.is_active, self.eligible.invitation_pending)
        activity_before = UserActivity.objects.count()

        with fail_with(FAILURES["timeout"]):
            self.request_reset("eligible@example.org")

        self.eligible.refresh_from_db()
        self.assertEqual((self.eligible.password, self.eligible.is_active, self.eligible.invitation_pending), before)
        self.assertEqual(UserActivity.objects.count(), activity_before)
        self.assertTrue(self.eligible.check_password(PASSWORD))

    def test_a_retry_after_a_failure_works_and_the_link_is_single_use(self):
        with fail_with(FAILURES["connection refused"]):
            self.request_reset("eligible@example.org")

        self.assertEqual(len(mail.outbox), 0)
        self.request_reset("eligible@example.org")
        self.assertEqual(len(mail.outbox), 1)

        link = link_in(mail.outbox[0].body)
        page = self.client.get(link, follow=True)
        post_url = page.redirect_chain[-1][0] if page.redirect_chain else link
        done = self.client.post(post_url, {"new_password1": "Another-Pass-456!", "new_password2": "Another-Pass-456!"})
        self.assertEqual(done.status_code, 302)
        self.eligible.refresh_from_db()
        self.assertTrue(self.eligible.check_password("Another-Pass-456!"))

        again = self.client.get(link, follow=True)
        self.assertContains(again, "invalid", status_code=200)

    def test_disabled_and_pending_accounts_get_no_email_and_no_access(self):
        for email in ("disabled@example.org", "pending@example.org"):
            self.request_reset(email)

        self.assertEqual(len(mail.outbox), 0)

    def test_failure_logs_are_sanitised(self):
        for name, error in FAILURES.items():
            with self.subTest(failure=name):
                with self.assertLogs("accounts", level="WARNING") as captured:
                    with fail_with(error):
                        self.request_reset("eligible@example.org")

                text = "\n".join(captured.output)
                for forbidden in (SECRET, "eligible@example.org", "example.org", "/accounts/reset/", "Traceback", "password"):
                    self.assertNotIn(forbidden, text, forbidden)

                self.assertIn(type(error).__name__, text)

    def test_nothing_secret_reaches_the_response(self):
        with fail_with(FAILURES["authentication"]):
            response = self.request_reset("eligible@example.org")

        html = response.content.decode()

        for forbidden in (SECRET, "535", "SMTP", "Traceback", "/accounts/reset/"):
            self.assertNotIn(forbidden, html, forbidden)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="127.0.0.1",
        EMAIL_PORT=1,
        EMAIL_TIMEOUT=2,
    )
    def test_a_real_local_connection_failure_is_handled(self):
        # Port 1 on this computer refuses the connection: no external traffic.
        response = self.request_reset("eligible@example.org")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "If an account exists with that email")


@override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
class InvitationFailureTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("inv-admin@example.com", "Inv", "Admin", PASSWORD, role=ROLE_ADMIN)
        self.staff_user = User.objects.create_user("plain-staff@example.com", "Plain", "Staff", PASSWORD, role=ROLE_STAFF)
        self.client.force_login(self.admin)

    def create(self, email="pat@example.org"):
        return self.client.post(
            reverse("user_add"),
            {"full_name": "Pat Pending", "email": email, "role": "staff"},
            follow=True,
        )

    def options(self, user):
        return self.client.get(reverse("user_options", args=[user.pk])).content.decode()

    def actions(self, user):
        return list(UserActivity.objects.filter(target=user).order_by("id").values_list("action", flat=True))

    def test_every_failure_leaves_a_pending_account_with_a_delivery_failed_state(self):
        for index, (name, error) in enumerate(FAILURES.items()):
            with self.subTest(failure=name):
                email = f"person{index}@example.org"

                with fail_with(error):
                    response = self.create(email)

                self.assertEqual(response.status_code, 200)
                user = User.objects.get(email=email)
                self.assertTrue(user.invitation_pending)
                self.assertFalse(user.has_usable_password())
                self.assertEqual(self.actions(user), ["user_created", "invitation_failed"])
                page = self.options(user)
                self.assertIn("Invitation delivery failed", page)
                self.assertIn("Resend Invitation", page)
                self.assertNotIn(SECRET, page)

    def test_resend_after_a_failure_works_and_clears_the_failed_state(self):
        with fail_with(FAILURES["authentication"]):
            self.create()

        user = User.objects.get(email="pat@example.org")
        mail.outbox.clear()
        self.client.post(reverse("user_resend_invitation", args=[user.pk]), follow=True)

        self.assertEqual(len(mail.outbox), 1)
        user.refresh_from_db()
        self.assertTrue(user.invitation_pending)
        self.assertIsNotNone(user.invitation_sent_at)
        self.assertEqual(self.actions(user), ["user_created", "invitation_failed", "invitation_resent"])
        self.assertNotIn("Invitation delivery failed", self.options(user))

    def test_a_failed_resend_cancels_the_earlier_link_and_shows_failed_not_last_sent(self):
        self.create()
        user = User.objects.get(email="pat@example.org")
        first_link = link_in(mail.outbox[0].body)

        with fail_with(FAILURES["timeout"]):
            self.client.post(reverse("user_resend_invitation", args=[user.pk]), follow=True)

        user.refresh_from_db()
        self.assertTrue(user.invitation_pending)
        self.assertEqual(self.actions(user)[-1], "invitation_failed")
        page = self.options(user)
        self.assertIn("Invitation delivery failed", page)
        self.assertNotIn("Invitation last sent", page)
        # The earlier link no longer works.
        self.assertContains(self.client.get(first_link, follow=True), "invalid")

        mail.outbox.clear()
        self.client.post(reverse("user_resend_invitation", args=[user.pk]), follow=True)
        self.assertEqual(len(mail.outbox), 1)
        new_link = link_in(mail.outbox[0].body)
        self.assertNotEqual(new_link, first_link)

        self.client.logout()
        page = self.client.get(new_link, follow=True)
        post_url = page.redirect_chain[-1][0]
        done = self.client.post(post_url, {"new_password1": "Another-Pass-456!", "new_password2": "Another-Pass-456!"})
        self.assertEqual(done.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.invitation_pending)
        self.assertEqual(self.actions(user)[-1], "invitation_accepted")
        # Single use.
        self.assertContains(self.client.get(new_link, follow=True), "invalid")

    def test_a_disabled_account_cannot_be_sent_an_invitation(self):
        with fail_with(FAILURES["authentication"]):
            self.create()

        user = User.objects.get(email="pat@example.org")
        user.is_active = False
        user.save(update_fields=["is_active"])
        mail.outbox.clear()
        self.client.post(reverse("user_resend_invitation", args=[user.pk]), follow=True)

        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn("invitation_resent", self.actions(user))

    def test_only_an_admin_can_resend(self):
        with fail_with(FAILURES["authentication"]):
            self.create()

        user = User.objects.get(email="pat@example.org")
        self.client.force_login(self.staff_user)
        mail.outbox.clear()
        response = self.client.post(reverse("user_resend_invitation", args=[user.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_failure_logs_are_sanitised(self):
        for index, (name, error) in enumerate(FAILURES.items()):
            with self.subTest(failure=name):
                email = f"logcheck{index}@example.org"

                with self.assertLogs("accounts", level="WARNING") as captured:
                    with fail_with(error):
                        self.create(email)

                text = "\n".join(captured.output)
                for forbidden in (SECRET, email, "example.org", "/accounts/reset/", "Traceback", "password"):
                    self.assertNotIn(forbidden, text, forbidden)

                self.assertIn(type(error).__name__, text)

    def test_nothing_secret_reaches_pages_or_the_activity_history(self):
        with fail_with(FAILURES["authentication"]):
            response = self.create()

        user = User.objects.get(email="pat@example.org")
        pages = [response.content.decode(), self.options(user), self.client.get(reverse("user_activity")).content.decode()]
        details = " ".join(UserActivity.objects.values_list("detail", flat=True))

        for text in pages + [details]:
            for forbidden in (SECRET, "535", "Traceback", "/accounts/reset/"):
                self.assertNotIn(forbidden, text, forbidden)

    def test_success_sends_one_email_with_a_working_single_use_link(self):
        self.create()
        user = User.objects.get(email="pat@example.org")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.actions(user), ["user_created", "invitation_sent"])
        self.assertIn("Invitation last sent", self.options(user))
        self.assertNotIn("Invitation delivery failed", self.options(user))

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="127.0.0.1",
        EMAIL_PORT=1,
        EMAIL_TIMEOUT=2,
    )
    def test_a_real_local_connection_failure_is_handled(self):
        response = self.create("local-fail@example.org")

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="local-fail@example.org")
        self.assertEqual(self.actions(user), ["user_created", "invitation_failed"])
        self.assertIn("Invitation delivery failed", self.options(user))
