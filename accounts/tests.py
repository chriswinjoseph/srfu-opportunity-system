from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AccessProtectionTests(TestCase):

    def setUp(self):
        self.password = "Testing123!"

        self.user = get_user_model().objects.create_user(
            email="access@example.com",
            first_name="Access",
            last_name="Tester",
            password=self.password,
        )

    def test_login_opens_new_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.email,
                "password": self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("outreach_dashboard"),
        )

    def test_logged_out_user_cannot_open_protected_pages(self):
        protected_urls = [
            reverse("outreach_dashboard"),
            reverse("bank_list"),
        ]

        for url in protected_urls:
            response = self.client.get(url)

            self.assertRedirects(
                response,
                f"{reverse('login')}?next={url}",
            )

    def test_old_dashboard_redirects_to_new_dashboard(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(
            response,
            reverse("outreach_dashboard"),
        )

    def test_logout_ends_session(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("login"))

        dashboard_response = self.client.get(
            reverse("outreach_dashboard")
        )

        self.assertEqual(dashboard_response.status_code, 302)

    def test_session_expiry_settings(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 3600)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)