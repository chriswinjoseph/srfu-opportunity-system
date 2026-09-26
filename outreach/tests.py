from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Bank, Branch, Club, Opportunity
from .status_transitions import (
    InvalidStatusTransition,
    bulk_update_organisation_contact_statuses,
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

        dashboard_response = self.client.get(
            reverse("outreach_dashboard")
        )

        self.assertEqual(
            dashboard_response.status_code,
            200,
        )

        status_breakdown = dashboard_response.context[
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

        api_response = self.client.get(
            reverse("organisation_list_api"),
            {
                "q": "Conflict Test Club",
                "type": "club",
            },
        )

        self.assertEqual(
            api_response.status_code,
            200,
        )

        results = api_response.json()["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["name"],
            "Conflict Test Club",
        )
        self.assertEqual(
            results[0]["contact_status"],
            "not_yet_contacted",
        )
        self.assertEqual(
            results[0]["opportunity_outcome"],
            "interested",
        )
        self.assertTrue(
            results[0]["status_conflict"]
        )



class BulkContactStatusTransitionTests(TestCase):
    def test_valid_updates_are_saved_when_another_update_is_invalid(self):
        valid_bank = Bank.objects.create(
            bank_name="Valid Bulk Bank",
            region="Victoria",
            contact_status="not_yet_contacted",
        )

        invalid_bank = Bank.objects.create(
            bank_name="Invalid Bulk Bank",
            region="Victoria",
            contact_status="contacted",
        )

        updated, errors = (
            bulk_update_organisation_contact_statuses(
                [
                    {
                        "organisation": valid_bank,
                        "new_status": "contacted",
                        "contact_confirmed": True,
                    },
                    {
                        "organisation": invalid_bank,
                        "new_status": "not_yet_contacted",
                    },
                ],
                actor="bulk-test-user",
            )
        )

        valid_bank.refresh_from_db()
        invalid_bank.refresh_from_db()

        self.assertEqual(
            valid_bank.contact_status,
            "contacted",
        )
        self.assertEqual(
            invalid_bank.contact_status,
            "contacted",
        )

        self.assertEqual(len(updated), 1)
        self.assertEqual(
            updated[0].pk,
            valid_bank.pk,
        )

        self.assertEqual(len(errors), 1)
        self.assertEqual(
            errors[0]["id"],
            invalid_bank.pk,
        )

class OrganisationListApiTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="api@example.com",
            first_name="API",
            last_name="Tester",
            password="Testing123!",
        )

        self.url = reverse(
            "organisation_list_api"
        )

        self.alpha_bank = Bank.objects.create(
            bank_name="Alpha Bank",
            region="Victoria",
            contact_status="contacted",
            public_email="alpha@example.com",
            public_phone="0311111111",
        )

        self.zeta_bank = Bank.objects.create(
            bank_name="Zeta Bank",
            region="New South Wales",
            contact_status="not_yet_contacted",
        )

        self.branch = Branch.objects.create(
            bank=self.alpha_bank,
            branch_name="Beta Branch",
            region="Victoria",
            contact_status="contacted",
        )

        self.club = Club.objects.create(
            club_name="Gamma Club",
            region="Queensland",
            contact_status="not_yet_contacted",
        )

        bank_content_type = (
            ContentType.objects.get_for_model(
                self.alpha_bank
            )
        )

        Opportunity.objects.create(
            content_type=bank_content_type,
            object_id=self.alpha_bank.pk,
            status="interested",
        )

        club_content_type = (
            ContentType.objects.get_for_model(
                self.club
            )
        )

        Opportunity.objects.create(
            content_type=club_content_type,
            object_id=self.club.pk,
            status="interested",
        )

    def test_logged_out_user_cannot_access_api(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)

    def test_api_only_accepts_get_requests(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)

    def test_api_returns_all_organisation_types(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            data["pagination"]["total_items"],
            4,
        )

        returned_types = {
            row["type"]
            for row in data["results"]
        }

        self.assertEqual(
            returned_types,
            {
                "bank",
                "branch",
                "club",
            },
        )

    def test_contact_status_and_outcome_remain_separate(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)
        results = response.json()["results"]

        alpha_result = next(
            row
            for row in results
            if row["name"] == "Alpha Bank"
        )

        self.assertEqual(
            alpha_result["contact_status"],
            "contacted",
        )
        self.assertEqual(
            alpha_result["opportunity_outcome"],
            "interested",
        )
        self.assertFalse(
            alpha_result["status_conflict"]
        )

        club_result = next(
            row
            for row in results
            if row["name"] == "Gamma Club"
        )

        self.assertEqual(
            club_result["contact_status"],
            "not_yet_contacted",
        )
        self.assertEqual(
            club_result["opportunity_outcome"],
            "interested",
        )
        self.assertTrue(
            club_result["status_conflict"]
        )

    def test_single_contact_status_filter(self):
        self.client.force_login(self.user)

        response = self.client.get(
            self.url,
            {
                "status": "contacted",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            data["pagination"]["total_items"],
            2,
        )

        self.assertEqual(
            {
                row["contact_status"]
                for row in data["results"]
            },
            {"contacted"},
        )

    def test_multiple_contact_status_filter_formats(self):
        self.client.force_login(self.user)

        repeated_response = self.client.get(
            (
                f"{self.url}"
                "?status=contacted"
                "&status=not_yet_contacted"
            )
        )

        comma_response = self.client.get(
            self.url,
            {
                "status": (
                    "contacted,not_yet_contacted"
                ),
            },
        )

        self.assertEqual(
            repeated_response.status_code,
            200,
        )
        self.assertEqual(
            comma_response.status_code,
            200,
        )

        self.assertEqual(
            repeated_response.json()[
                "pagination"
            ]["total_items"],
            4,
        )
        self.assertEqual(
            comma_response.json()[
                "pagination"
            ]["total_items"],
            4,
        )

    def test_combined_filters(self):
        self.client.force_login(self.user)

        response = self.client.get(
            self.url,
            {
                "q": "Alpha",
                "type": "bank",
                "region": "Victoria",
                "status": "contacted",
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            data["pagination"]["total_items"],
            1,
        )
        self.assertEqual(
            data["results"][0]["name"],
            "Alpha Bank",
        )

    def test_invalid_status_and_type_are_rejected(self):
        self.client.force_login(self.user)

        status_response = self.client.get(
            self.url,
            {
                "status": "interested",
            },
        )

        type_response = self.client.get(
            self.url,
            {
                "type": "school",
            },
        )

        self.assertEqual(
            status_response.status_code,
            400,
        )
        self.assertEqual(
            status_response.json()[
                "invalid_statuses"
            ],
            ["interested"],
        )

        self.assertEqual(
            type_response.status_code,
            400,
        )
        self.assertEqual(
            type_response.json()["invalid_type"],
            "school",
        )

    def test_invalid_sort_values_are_rejected(self):
        self.client.force_login(self.user)

        field_response = self.client.get(
            self.url,
            {
                "sort_by": "created",
            },
        )

        direction_response = self.client.get(
            self.url,
            {
                "sort_dir": "sideways",
            },
        )

        self.assertEqual(
            field_response.status_code,
            400,
        )
        self.assertEqual(
            direction_response.status_code,
            400,
        )

    def test_descending_name_sort(self):
        self.client.force_login(self.user)

        response = self.client.get(
            self.url,
            {
                "sort_by": "name",
                "sort_dir": "desc",
            },
        )

        names = [
            row["name"]
            for row in response.json()["results"]
        ]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            names,
            [
                "Zeta Bank",
                "Gamma Club",
                "Beta Branch",
                "Alpha Bank",
            ],
        )

    def test_pagination(self):
        self.client.force_login(self.user)

        response = self.client.get(
            self.url,
            {
                "page": 2,
                "page_size": 2,
            },
        )

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            data["pagination"]["page"],
            2,
        )
        self.assertEqual(
            data["pagination"]["total_pages"],
            2,
        )
        self.assertTrue(
            data["pagination"]["has_previous"]
        )
        self.assertFalse(
            data["pagination"]["has_next"]
        )
        self.assertEqual(
            [
                row["name"]
                for row in data["results"]
            ],
            [
                "Gamma Club",
                "Zeta Bank",
            ],
        )

    def test_invalid_pagination_values_are_rejected(self):
        self.client.force_login(self.user)

        invalid_parameters = [
            {"page": "zero"},
            {"page": "0"},
            {"page_size": "zero"},
            {"page_size": "0"},
            {"page_size": "51"},
            {"page": "99"},
        ]

        for parameters in invalid_parameters:
            with self.subTest(parameters=parameters):
                response = self.client.get(
                    self.url,
                    parameters,
                )

                self.assertEqual(
                    response.status_code,
                    400,
                )

    def test_empty_results_and_empty_out_of_range_page(self):
        self.client.force_login(self.user)

        empty_response = self.client.get(
            self.url,
            {
                "q": "Missing Organisation",
            },
        )

        out_of_range_response = self.client.get(
            self.url,
            {
                "q": "Missing Organisation",
                "page": 2,
            },
        )

        self.assertEqual(
            empty_response.status_code,
            200,
        )
        self.assertEqual(
            empty_response.json()["results"],
            [],
        )
        self.assertEqual(
            empty_response.json()[
                "pagination"
            ]["total_items"],
            0,
        )

        self.assertEqual(
            out_of_range_response.status_code,
            400,
        )