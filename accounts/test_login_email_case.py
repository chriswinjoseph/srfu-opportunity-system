from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.roles import ROLE_STAFF

User = get_user_model()

PASSWORD = "Testing123!"


class LoginEmailCaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "Pat.Example@Example.org", "Pat", "Example", PASSWORD, role=ROLE_STAFF
        )

    def login(self, email, password=PASSWORD):
        self.client.logout()

        return self.client.post(
            reverse("login"), {"username": email, "password": password}
        )

    def test_any_capitalisation_of_the_email_signs_in(self):
        for email in (
            "Pat.Example@Example.org",
            "pat.example@example.org",
            "PAT.EXAMPLE@EXAMPLE.ORG",
            "  pat.example@example.org  ",
        ):
            with self.subTest(email=email):
                response = self.login(email)

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], reverse("outreach_dashboard"))

    def test_a_lowercase_account_accepts_an_uppercase_email(self):
        User.objects.create_user("lower@example.org", "Lo", "Wer", PASSWORD, role=ROLE_STAFF)

        self.assertEqual(self.login("LOWER@Example.ORG").status_code, 302)

    def test_a_wrong_password_or_unknown_email_still_fails_with_the_same_message(self):
        wrong = self.login("PAT.EXAMPLE@EXAMPLE.ORG", "not-the-password")
        unknown = self.login("nobody@example.org")

        self.assertEqual(wrong.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        self.assertContains(wrong, "Please enter a correct email or password.")
        self.assertContains(unknown, "Please enter a correct email or password.")

    def test_a_disabled_account_is_still_refused_whatever_the_capitalisation(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        response = self.login("PAT.EXAMPLE@EXAMPLE.ORG")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "disabled")

    def test_a_pending_invitation_cannot_sign_in(self):
        User.objects.filter(pk=self.user.pk).update(invitation_pending=True)
        self.user.set_unusable_password()
        self.user.save()

        self.assertEqual(self.login("PAT.EXAMPLE@EXAMPLE.ORG").status_code, 200)
