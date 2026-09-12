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
        self.assertEqual(
            self.bank.contact_status,
            "interested",
        )
        self.assertEqual(
            self.opportunity.status,
            "interested",
        )

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
            {
                "Northside Youth FC",
                "Northside Netball Club",
            },
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

        self.assertEqual(
            self.bank.contact_status,
            "contacted",
        )


class AddOrganisationTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="fr10@example.com",
            first_name="FR10",
            last_name="Tester",
            password="Testing123!",
        )

        self.url = reverse("add_organisation")

        self.bank = Bank.objects.create(
            bank_name="Existing Test Bank",
            region="Victoria",
        )

    def test_logged_out_user_is_redirected_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertIn("next=", response.url)

    def test_logged_in_user_can_open_add_page(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "outreach/add_organisation.html",
        )
        self.assertContains(response, "Add Organisation")

    def test_logged_in_user_can_add_bank(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                "organisation_type": "bank",
                "bank_name": "FR10 Test Bank",
                "region": "Victoria",
                "website_url": "https://example.com",
                "public_email": "bank@example.com",
                "public_phone": "0312345678",
                "source_url": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        bank = Bank.objects.get(
            bank_name="FR10 Test Bank"
        )

        self.assertEqual(
            bank.contact_status,
            "not_yet_contacted",
        )

    def test_logged_in_user_can_add_branch(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                "organisation_type": "branch",
                "bank": self.bank.id,
                "branch_name": "Melbourne Test Branch",
                "address": "",
                "suburb": "Melbourne",
                "state": "Victoria",
                "postcode": "3000",
                "region": "Victoria",
                "public_email": "",
                "public_phone": "",
                "website_url": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        branch = Branch.objects.get(
            branch_name="Melbourne Test Branch"
        )

        self.assertEqual(branch.bank, self.bank)
        self.assertEqual(
            branch.contact_status,
            "not_yet_contacted",
        )

    def test_logged_in_user_can_add_club(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                "organisation_type": "club",
                "club_name": "FR10 Youth Club",
                "club_type": "Football",
                "suburb": "Melbourne",
                "state": "Victoria",
                "region": "Victoria",
                "website_url": "",
                "public_email": "",
                "public_phone": "",
                "supported_by_bank": self.bank.id,
                "supported_by_branch": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        club = Club.objects.get(
            club_name="FR10 Youth Club"
        )

        self.assertEqual(
            club.supported_by_bank,
            self.bank,
        )
        self.assertEqual(
            club.contact_status,
            "not_yet_contacted",
        )