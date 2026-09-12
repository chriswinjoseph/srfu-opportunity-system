from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from .models import Bank, Branch, Club, Opportunity


class PositiveResponseTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            password="Testing123!",
        )

        self.bank = Bank.objects.create(
            bank_name="Riverside Community Bank",
            region="North",
            contact_status="contacted",
        )

        content_type = ContentType.objects.get_for_model(self.bank)

        self.opportunity = Opportunity.objects.create(
            content_type=content_type,
            object_id=self.bank.id,
            status="contacted",
        )

        self.url = reverse(
            "record_positive_response_api",
            args=[self.opportunity.id],
        )

    def test_positive_response_updates_status(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url)

        self.bank.refresh_from_db()
        self.opportunity.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.bank.contact_status, "interested")
        self.assertEqual(self.opportunity.status, "interested")

    def test_returns_direct_and_branch_clubs_without_changing_them(self):
        direct_club = Club.objects.create(
            club_name="Northside Youth FC",
            supported_by_bank=self.bank,
        )

        branch = Branch.objects.create(
            bank=self.bank,
            branch_name="North Branch",
        )

        branch_club = Club.objects.create(
            club_name="Northside Netball Club",
            supported_by_branch=branch,
        )

        self.client.force_login(self.user)
        response = self.client.post(self.url)

        club_names = {
            club["name"]
            for club in response.json()["clubs"]
        }

        self.assertEqual(
            club_names,
            {"Northside Youth FC", "Northside Netball Club"},
        )

        direct_club.refresh_from_db()
        branch_club.refresh_from_db()

        self.assertEqual(
            direct_club.contact_status,
            "not_yet_contacted",
        )
        self.assertEqual(
            branch_club.contact_status,
            "not_yet_contacted",
        )

    def test_returns_empty_list_when_no_clubs_are_linked(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["clubs"], [])

    def test_logged_out_user_cannot_use_endpoint(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)

        self.bank.refresh_from_db()
        self.assertEqual(self.bank.contact_status, "contacted")