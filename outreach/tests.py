from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Bank, Branch, Club, Opportunity
from .status_transitions import (
    InvalidStatusTransition,
    update_organisation_contact_status,
)


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

        content_type = ContentType.objects.get_for_model(
            self.bank
        )

        self.opportunity = Opportunity.objects.create(
            content_type=content_type,
            object_id=self.bank.id,
            status="contacted",
        )

        self.url = reverse(
            "record_positive_response_api",
            args=[self.opportunity.id],
        )

    def test_positive_response_updates_only_opportunity(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url)

        self.bank.refresh_from_db()
        self.opportunity.refresh_from_db()

        self.assertEqual(response.status_code, 200)

        # The organisation remains Contacted.
        self.assertEqual(
            self.bank.contact_status,
            "contacted",
        )

        # Only the response outcome becomes Interested.
        self.assertEqual(
            self.opportunity.status,
            "interested",
        )

        self.assertEqual(
            response.json()["organisation_status"],
            "contacted",
        )
        self.assertEqual(
            response.json()["opportunity_status"],
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
        branch.refresh_from_db()
        branch_club.refresh_from_db()

        self.assertEqual(
            direct_club.contact_status,
            "not_yet_contacted",
        )
        self.assertEqual(
            branch.contact_status,
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
        self.opportunity.refresh_from_db()

        self.assertEqual(
            self.bank.contact_status,
            "contacted",
        )
        self.assertEqual(
            self.opportunity.status,
            "contacted",
        )

    def test_response_rejected_when_organisation_not_contacted(self):
        self.bank.contact_status = "not_yet_contacted"
        self.bank.save(update_fields=["contact_status"])

        self.client.force_login(self.user)

        with self.assertLogs(
            "outreach.status_transitions",
            level="WARNING",
        ):
            response = self.client.post(self.url)

        self.bank.refresh_from_db()
        self.opportunity.refresh_from_db()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self.bank.contact_status,
            "not_yet_contacted",
        )
        self.assertEqual(
            self.opportunity.status,
            "contacted",
        )

    def test_terminal_do_not_contact_response_is_rejected(self):
        self.opportunity.status = "do_not_contact"
        self.opportunity.save(update_fields=["status"])

        self.client.force_login(self.user)

        response = self.client.post(self.url)

        self.bank.refresh_from_db()
        self.opportunity.refresh_from_db()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self.bank.contact_status,
            "contacted",
        )
        self.assertEqual(
            self.opportunity.status,
            "do_not_contact",
        )

    def test_duplicate_positive_response_is_idempotent(self):
        self.client.force_login(self.user)

        first_response = self.client.post(self.url)
        second_response = self.client.post(self.url)

        self.bank.refresh_from_db()
        self.opportunity.refresh_from_db()

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            self.bank.contact_status,
            "contacted",
        )
        self.assertEqual(
            self.opportunity.status,
            "interested",
        )
        self.assertEqual(
            Opportunity.objects.filter(
                pk=self.opportunity.pk
            ).count(),
            1,
        )

    def test_club_cannot_trigger_supported_club_lookup(self):
        club = Club.objects.create(
            club_name="Test Club",
            contact_status="contacted",
        )

        content_type = ContentType.objects.get_for_model(club)

        opportunity = Opportunity.objects.create(
            content_type=content_type,
            object_id=club.pk,
            status="contacted",
        )

        url = reverse(
            "record_positive_response_api",
            args=[opportunity.pk],
        )

        self.client.force_login(self.user)
        response = self.client.post(url)

        opportunity.refresh_from_db()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            opportunity.status,
            "contacted",
        )


class ContactStatusTransitionTests(TestCase):

    def setUp(self):
        self.bank = Bank.objects.create(
            bank_name="Transition Test Bank",
            region="Victoria",
            contact_status="not_yet_contacted",
        )

    def test_confirmed_contact_can_change_to_contacted(self):
        updated_bank = update_organisation_contact_status(
            self.bank,
            "contacted",
            contact_confirmed=True,
            actor="test-user",
        )

        self.assertEqual(
            updated_bank.contact_status,
            "contacted",
        )

        self.bank.refresh_from_db()

        self.assertEqual(
            self.bank.contact_status,
            "contacted",
        )

    def test_unconfirmed_contact_is_rejected(self):
        with self.assertLogs(
            "outreach.status_transitions",
            level="WARNING",
        ):
            with self.assertRaises(InvalidStatusTransition):
                update_organisation_contact_status(
                    self.bank,
                    "contacted",
                    contact_confirmed=False,
                    actor="test-user",
                )

        self.bank.refresh_from_db()

        self.assertEqual(
            self.bank.contact_status,
            "not_yet_contacted",
        )

    def test_opportunity_outcome_cannot_be_contact_status(self):
        with self.assertRaises(InvalidStatusTransition):
            update_organisation_contact_status(
                self.bank,
                "interested",
                contact_confirmed=True,
                actor="test-user",
            )

        self.bank.refresh_from_db()

        self.assertEqual(
            self.bank.contact_status,
            "not_yet_contacted",
        )

    def test_contacted_cannot_return_to_not_yet_contacted(self):
        self.bank.contact_status = "contacted"
        self.bank.save(update_fields=["contact_status"])

        with self.assertRaises(InvalidStatusTransition):
            update_organisation_contact_status(
                self.bank,
                "not_yet_contacted",
                actor="test-user",
            )

        self.bank.refresh_from_db()

        self.assertEqual(
            self.bank.contact_status,
            "contacted",
        )

    def test_database_constraint_rejects_invalid_status(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Bank.objects.filter(
                    pk=self.bank.pk
                ).update(
                    contact_status="interested"
                )

        self.bank.refresh_from_db()

        self.assertEqual(
            self.bank.contact_status,
            "not_yet_contacted",
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
class DashboardStatusConflictTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="conflict@example.com",
            first_name="Conflict",
            last_name="Tester",
            password="Testing123!",
        )

        self.club = Club.objects.create(
            club_name="Conflict Test Club",
            contact_status="not_yet_contacted",
        )

        content_type = ContentType.objects.get_for_model(
            self.club
        )

        Opportunity.objects.create(
            content_type=content_type,
            object_id=self.club.pk,
            status="interested",
        )

    def test_conflicting_status_is_flagged_for_review(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("outreach_dashboard")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Conflict Test Club",
        )
        self.assertContains(
            response,
            "Needs Review",
        )

        status_breakdown = response.context[
            "status_breakdown"
        ]

        self.assertEqual(
            status_breakdown["Interested"],
            0,
        )
        self.assertEqual(
            status_breakdown["Needs Review"],
            1,
        )