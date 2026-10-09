import re
import smtplib
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import services
from accounts.models import UserActivity
from accounts.roles import ROLE_ADMIN

User = get_user_model()

PASSWORD = "Testing123!"
BASE = "https://srfu.example.org"


def link_in(text):
    return re.search(r"https?://\S+/accounts/reset/\S+", text).group(0)


def token_of(link):
    return link.rstrip("/").split("/")[-1]


@override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
class InvitationSecretHandlingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            "inv-admin@example.com", "Inv", "Admin", PASSWORD, role=ROLE_ADMIN
        )
        self.client.force_login(self.admin)

    def create(self):
        return self.client.post(
            reverse("user_add"),
            {"full_name": "Pat Pending", "email": "pat@example.org",
             "role": "staff"},
            follow=True,
        )

    def test_link_is_only_in_the_email_never_in_pages_or_audit_records(self):
        response = self.create()
        user = User.objects.get(email="pat@example.org")

        link = link_in(mail.outbox[0].body)
        token = token_of(link)

        pages = [response.content.decode()]
        for name in ("user_list", "user_activity"):
            pages.append(self.client.get(reverse(name)).content.decode())
        pages.append(
            self.client.get(
                reverse("user_options", args=[user.pk])
            ).content.decode()
        )

        for html in pages:
            self.assertNotIn(token, html)
            self.assertNotIn("/accounts/reset/", html)

        for activity in UserActivity.objects.all():
            blob = " ".join(
                str(getattr(activity, field.name, ""))
                for field in activity._meta.fields
            )
            self.assertNotIn(token, blob)
            self.assertNotIn("/accounts/reset/", blob)

    def test_delivery_failure_logs_and_errors_contain_no_link_or_token(self):
        # Pre-compute the token the failed invitation would have used.
        with patch(
            "accounts.services.send_mail",
            side_effect=smtplib.SMTPException("relay refused"),
        ), self.assertLogs("accounts", level="DEBUG") as logs:
            response = self.create()

        user = User.objects.get(email="pat@example.org")
        token = default_token_generator.make_token(user)

        self.assertNotIn(token, "\n".join(logs.output))
        self.assertNotIn("/accounts/reset/", "\n".join(logs.output))
        self.assertNotIn(token, response.content.decode())
        self.assertNotIn("relay refused", response.content.decode())
        self.assertEqual(len(mail.outbox), 0)

        failed = UserActivity.objects.get(action="invitation_failed")
        self.assertNotIn(token, failed.detail)
        self.assertEqual(failed.detail, "Email delivery failed.")

    def test_resend_failure_is_also_clean(self):
        self.create()
        user = User.objects.get(email="pat@example.org")

        with patch(
            "accounts.services.send_mail",
            side_effect=smtplib.SMTPException("relay refused"),
        ), self.assertLogs("accounts", level="DEBUG") as logs:
            response = self.client.post(
                reverse("user_resend_invitation", args=[user.pk]), follow=True
            )

        self.assertNotIn("/accounts/reset/", "\n".join(logs.output))
        self.assertNotIn("/accounts/reset/", response.content.decode())
        self.assertNotIn("relay refused", response.content.decode())


@override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
class FirstAdminRecoveryTests(TestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command(
            "create_first_admin",
            "--email", "first@example.org",
            "--name", "First Admin",
            "--base-url", BASE,
            *args,
            stdout=out,
        )
        return out.getvalue()

    def test_failed_delivery_error_output_has_no_link_or_token(self):
        with patch(
            "accounts.services.send_mail",
            side_effect=smtplib.SMTPException("relay refused"),
        ), self.assertLogs("accounts", level="DEBUG") as logs:
            with self.assertRaises(CommandError) as ctx:
                self.run_command()

        user = User.objects.get(email="first@example.org")
        token = default_token_generator.make_token(user)

        # Server logs keep the diagnostic error, but never the link or
        # token; the operator-facing message shows neither the link nor
        # the internal error text.
        log_text = "\n".join(logs.output)
        self.assertNotIn(token, log_text)
        self.assertNotIn("/accounts/reset/", log_text)

        message = str(ctx.exception)
        self.assertNotIn(token, message)
        self.assertNotIn("/accounts/reset/", message)
        self.assertNotIn("relay refused", message)

        for activity in UserActivity.objects.all():
            self.assertNotIn(token, activity.detail)

    def test_recovery_after_failed_delivery_with_no_usable_admin(self):
        with patch(
            "accounts.services.send_mail",
            side_effect=smtplib.SMTPException("relay refused"),
        ):
            with self.assertRaises(CommandError):
                self.run_command()

        # No Admin can sign in yet: a pending, password-less account.
        user = User.objects.get()
        self.assertTrue(user.invitation_pending)
        self.assertFalse(user.has_usable_password())

        # Recovery: run the command again, asking for the link to be
        # printed because mail is not working.
        output = self.run_command("--print-link")
        link = link_in(output)

        self.assertEqual(User.objects.count(), 1)

        response = self.client.get(link, follow=True)
        set_url = response.redirect_chain[-1][0]
        self.client.post(
            set_url,
            {"new_password1": "Recovered-1Pass!",
             "new_password2": "Recovered-1Pass!"},
        )

        login = self.client.post(
            reverse("login"),
            {"username": "first@example.org",
             "password": "Recovered-1Pass!"},
        )
        self.assertRedirects(
            login, reverse("outreach_dashboard"),
            fetch_redirect_response=False,
        )

        user.refresh_from_db()
        self.assertEqual(user.role, ROLE_ADMIN)
        self.assertFalse(user.invitation_pending)

    def test_rerun_invalidates_the_earlier_link(self):
        first = link_in(self.run_command("--print-link"))
        second = link_in(self.run_command("--print-link"))

        self.assertNotEqual(first, second)
        self.assertFalse(self.client.get(first).context["validlink"])

    def test_print_link_is_explicit_and_never_stored(self):
        output = self.run_command("--print-link")
        token = token_of(link_in(output))

        self.assertEqual(len(mail.outbox), 0)

        for activity in UserActivity.objects.all():
            blob = " ".join(
                str(getattr(activity, f.name, ""))
                for f in activity._meta.fields
            )
            self.assertNotIn(token, blob)

        # Without the flag the link is emailed, never printed.
        mail.outbox.clear()
        quiet = self.run_command()
        self.assertNotIn("/accounts/reset/", quiet)
        self.assertEqual(len(mail.outbox), 1)
