import smtplib
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

from outreach.views import EmailNotSentError



from django.contrib.auth import get_user_model



from django.contrib.auth.models import Permission



from django.contrib.contenttypes.models import ContentType



from django.db import IntegrityError, transaction



from django.test import TestCase



from django.urls import reverse



from django.utils import timezone



from .models import (



    Bank,



    Branch,



    Club,



    Opportunity,



    EmailDraft,



    EmailGenerationLog,



    EmailTemplate,



)



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



        # Give this user permission to manually create



        # Banks, Branches and Clubs.



        permissions = Permission.objects.filter(



            content_type__app_label="outreach",



            codename__in=[



                "add_bank",



                "add_branch",



                "add_club",



            ],



        )



        self.user.user_permissions.add(



            *permissions



        )



        self.url = reverse(



            "add_organisation"



        )



        self.bank = Bank.objects.create(



            bank_name="Existing Test Bank",



            region="Victoria",



            state="VIC",



            postcode="3000",



        )



    def test_logged_out_user_is_redirected_to_login(self):



        response = self.client.get(



            self.url



        )



        self.assertEqual(



            response.status_code,



            302,



        )



        self.assertIn(



            reverse("login"),



            response.url,



        )



        self.assertIn(



            "next=",



            response.url,



        )



    def test_authorised_user_can_open_add_page(self):



        self.client.force_login(



            self.user



        )



        response = self.client.get(



            self.url



        )



        self.assertEqual(



            response.status_code,



            200,



        )



        self.assertTemplateUsed(



            response,



            "outreach/add_organisation.html",



        )



        self.assertContains(



            response,



            "Add Organisation",



        )



    def test_user_without_permission_cannot_open_add_page(self):



        self.user.user_permissions.clear()



        self.client.force_login(



            self.user



        )



        response = self.client.get(



            self.url



        )



        self.assertEqual(



            response.status_code,



            403,



        )



        self.assertContains(



            response,



            "You don't have permission",



            status_code=403,



        )



    def test_authorised_user_can_add_bank(self):



        self.client.force_login(



            self.user



        )



        response = self.client.post(



            self.url,



            {



                "organisation_type": "bank",



                "bank_name": "FR10 Test Bank",



                "state": "VIC",



                "region": "Melbourne",



                "suburb": "",



                "postcode": "3000",



                "website_url": "https://example.com",



                "public_email": "bank@example.com",



                "public_phone": "0312345678",



                "source_url": "",



            },



            follow=True,



        )



        # Successful creation remains on the



        # Add Organisation page.



        self.assertEqual(



            response.status_code,



            200,



        )



        bank = Bank.objects.get(



            bank_name="FR10 Test Bank"



        )



        self.assertEqual(



            bank.contact_status,



            "not_yet_contacted",



        )



        self.assertEqual(



            bank.created_by,



            self.user,



        )



        self.assertEqual(



            bank.record_source,



            "Manual Entry",



        )



        self.assertIsNotNone(



            bank.organisation_id



        )



        self.assertContains(



            response,



            "has been added successfully.",



        )



    def test_authorised_user_can_add_branch(self):



        self.client.force_login(



            self.user



        )



        response = self.client.post(



            self.url,



            {



                "organisation_type": "branch",



                "bank": self.bank.id,



                "branch_name": "Melbourne Test Branch",



                "address": "",



                "suburb": "Melbourne",



                "state": "VIC",



                "postcode": "3000",



                "region": "Melbourne",



                 "public_email": "branch@example.com",



                "public_phone": "",



                "website_url": "",



            },



             follow=True,



        )



        self.assertEqual(



            response.status_code,



            200,



        )



        branch = Branch.objects.get(



            branch_name="Melbourne Test Branch"



        )



        self.assertEqual(



            branch.bank,



            self.bank,



        )



        self.assertEqual(



            branch.contact_status,



            "not_yet_contacted",



        )



        self.assertEqual(



            branch.created_by,



            self.user,



        )



        self.assertEqual(



            branch.record_source,



            "Manual Entry",



        )



        self.assertIsNotNone(



            branch.organisation_id



        )



    def test_authorised_user_can_add_club(self):



        self.client.force_login(



            self.user



        )



        response = self.client.post(



            self.url,



            {



                "organisation_type": "club",



                "club_name": "FR10 Youth Club",



                "club_type": "Football",



                "suburb": "Melbourne",



                "state": "VIC",



                "postcode": "3000",



                "region": "Melbourne",



                "website_url": "",



                "public_email": "branch@example.com",



                "public_phone": "",



                "supported_by_bank": self.bank.id,



                "supported_by_branch": "",



            },



            follow=True,



        )



        self.assertEqual(



            response.status_code,



            200,



        )



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



        self.assertEqual(



            club.created_by,



            self.user,



        )



        self.assertEqual(



            club.record_source,



            "Manual Entry",



        )



        self.assertIsNotNone(



            club.organisation_id



        )



    def test_missing_required_fields_do_not_create_bank(self):



        self.client.force_login(



            self.user



        )



        response = self.client.post(



            self.url,



            {



                "organisation_type": "bank",



                "bank_name": "",



                "state": "",



                "region": "",



                "suburb": "",



                "postcode": "",



                "website_url": "",



                "public_email": "branch@example.com",



                "public_phone": "",



                "source_url": "",



            },



        )



        self.assertEqual(



            response.status_code,



            200,



        )



        self.assertFalse(



            Bank.objects.filter(



                bank_name=""



            ).exists()



        )



        self.assertContains(



            response,



            "This field is required",



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



        "sort_by": "name",



        "sort_dir": "asc",



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



class EmailDraftWorkflowTests(TestCase):



    def setUp(self):



        self.user = get_user_model().objects.create_user(



            email="ai-test@example.com",



            first_name="AI",



            last_name="Tester",



            password="Testing123!",



        )



        permissions = Permission.objects.filter(



            content_type__app_label="outreach",



            codename__in=[



                "generate_emaildraft",



                "change_emaildraft",



                "approve_emaildraft",



                "send_emaildraft",



            ],



        )



        self.user.user_permissions.add(



            *permissions



        )



        self.bank = Bank.objects.create(



            bank_name="AI Test Community Bank",



            region="Victoria",



            public_email="bank@example.com",



            contact_status="not_yet_contacted",



        )



        self.content_type = (



            ContentType.objects.get_for_model(



                self.bank



            )



        )



        self.template = EmailTemplate.objects.create(



            name="Test Outreach Template",



            version="v1",



            purpose="Community partnership outreach",



            template_body=(



                "Introduce Safe Roads For Us and discuss "



                "a possible community partnership."



            ),



            sender_name="Shane",



            sender_role="Safe Roads For Us",



            project_details=(



                "Safe Roads For Us supports safer roads "



                "and community initiatives."



            ),



            call_to_action=(



                "Please let us know if you would be open "



                "to a short conversation."



            ),



            signature=(



                "Kind regards,\n"



                "Shane\n"



                "Safe Roads For Us"



            ),



            is_active=True,



        )



        self.generate_url = reverse(



            "generate_email_draft",



            args=[



                self.content_type.pk,



                self.bank.pk,



            ],



        )



        self.client.force_login(



            self.user



        )



    def create_opportunity(



        self,



        status="not_yet_contacted",



    ):



        return Opportunity.objects.create(



            content_type=self.content_type,



            object_id=self.bank.pk,



            status=status,



        )



    def create_draft(



        self,



        workflow_status="draft",



        opportunity=None,



    ):



        if opportunity is None:



            opportunity = self.create_opportunity()



        return EmailDraft.objects.create(



            opportunity=opportunity,



            recipient_email=self.bank.public_email,



            subject="Test Subject",



            body="Test email body.",



            outreach_purpose=(



                "Explore a possible community collaboration."



            ),



            workflow_status=workflow_status,



            generation_status="success",



            requested_by=self.user,



            trigger_source="manual",



        )



    def make_approved_draft(self):

        draft = self.create_draft(

            workflow_status="approved"

        )



        draft.approved_by = self.user

        draft.approved_at = timezone.now()

        draft.approved_version = draft.version



        draft.save(

            update_fields=[

                "approved_by",

                "approved_at",

                "approved_version",

            ]

        )



        return draft



    def generation_data(



        self,



        purpose="Explore a possible community collaboration.",



    ):



        return {



            "template_id": self.template.id,



            "outreach_purpose": purpose,



        }



    @patch(



        "outreach.views.generate_outreach_email"



    )



    def test_successful_generation_creates_draft_and_audit_log(



        self,



        mock_generate,



    ):



        mock_generate.return_value = (



            "Generated Subject",



            "Generated email body.",



            100,



            50,



            150,



            False,



            "",



        )



        response = self.client.post(



            self.generate_url,



            self.generation_data(),



        )



        self.assertEqual(



            response.status_code,



            302,



        )



        draft = EmailDraft.objects.get()



        self.assertEqual(



            draft.subject,



            "Generated Subject",



        )



        self.assertEqual(



            draft.body,



            "Generated email body.",



        )



        self.assertEqual(



            draft.workflow_status,



            "draft",



        )



        self.assertEqual(



            draft.generation_status,



            "success",



        )



        self.assertEqual(



            draft.trigger_source,



            "manual",



        )



        self.assertEqual(



            draft.requested_by,



            self.user,



        )



        log = EmailGenerationLog.objects.get()



        self.assertEqual(



            log.status,



            "success",



        )



        self.bank.refresh_from_db()



        self.assertEqual(



            self.bank.contact_status,



            "not_yet_contacted",



        )





    @patch(



        "outreach.views.generate_outreach_email"



    )





    def test_generation_failure_does_not_create_draft(



        self,



        mock_generate,



    ):



        mock_generate.side_effect = RuntimeError(



            "Test AI failure"



        )



        response = self.client.post(



            self.generate_url,



            self.generation_data(



                "Explore community collaboration."



            ),



            follow=True,



        )



        self.assertEqual(



            response.status_code,



            200,



        )



        self.assertFalse(



            EmailDraft.objects.exists()



        )



        log = EmailGenerationLog.objects.get()



        self.assertEqual(



            log.status,



            "failed",



        )



        self.assertIn(



            "RuntimeError",



            log.error_message,



        )



        self.bank.refresh_from_db()



        self.assertEqual(



            self.bank.contact_status,



            "not_yet_contacted",



        )



    @patch(



        "outreach.views.generate_outreach_email"



    )



    def test_timeout_is_recorded_as_timed_out(



        self,



        mock_generate,



    ):



        import openai



        mock_generate.side_effect = (



            openai.APITimeoutError(



                request=None



            )



        )



        response = self.client.post(



            self.generate_url,



            self.generation_data(



                "Explore community collaboration."



            ),



            follow=True,



        )



        self.assertEqual(



            response.status_code,



            200,



        )



        self.assertFalse(



            EmailDraft.objects.exists()



        )



        log = EmailGenerationLog.objects.get()



        self.assertEqual(



            log.status,



            "timed_out",



        )



    @patch(



        "outreach.views.generate_outreach_email"



    )



    def test_do_not_contact_blocks_generation(



        self,



        mock_generate,



    ):



        self.create_opportunity(



            status="do_not_contact"



        )



        response = self.client.post(



            self.generate_url,



            self.generation_data(



                "Explore community collaboration."



            ),



            follow=True,



        )



        self.assertEqual(



            response.status_code,



            200,



        )



        mock_generate.assert_not_called()



        self.assertFalse(



            EmailDraft.objects.exists()



        )



        self.assertContains(



            response,



            "Do Not Contact",



        )



    @patch(



        "outreach.views.generate_outreach_email"



    )



    def test_rate_limit_blocks_generation(



        self,



        mock_generate,



    ):



        for _ in range(5):



            EmailGenerationLog.objects.create(



                content_type=self.content_type,



                object_id=self.bank.pk,



                requested_by=self.user,



                trigger_source="manual",



                status="success",



                error_message="",



            )



        response = self.client.post(



            self.generate_url,



            self.generation_data(



                "Explore community collaboration."



            ),



            follow=True,



        )



        self.assertEqual(



            response.status_code,



            200,



        )



        mock_generate.assert_not_called()



        self.assertFalse(



            EmailDraft.objects.exists()



        )



        self.assertContains(



            response,



            "Too many email generation requests",



        )



    @patch(



        "outreach.views.generate_outreach_email"



    )



    def test_missing_email_blocks_generation(



        self,



        mock_generate,



    ):



        self.bank.public_email = ""



        self.bank.save(



            update_fields=[



                "public_email",



            ]



        )



        response = self.client.post(



            self.generate_url,



            self.generation_data(



                "Explore community collaboration."



            ),



            follow=True,



        )



        self.assertEqual(



            response.status_code,



            200,



        )



        mock_generate.assert_not_called()



        self.assertFalse(



            EmailDraft.objects.exists()



        )



        self.assertContains(



            response,



            "A valid recipient email is required",



        )



    @patch(



        "outreach.views.generate_outreach_email"



    )



    def test_user_without_permission_cannot_generate(



        self,



        mock_generate,



    ):



        self.user.user_permissions.clear()



        response = self.client.post(



            self.generate_url,



            self.generation_data(



                "Explore community collaboration."



            ),



        )



        self.assertEqual(



            response.status_code,



            302,



        )



        mock_generate.assert_not_called()



        self.assertFalse(



            EmailDraft.objects.exists()



        )



    def test_submit_draft_for_review(self):



        draft = self.create_draft()



        url = reverse(



            "submit_email_draft_for_review",



            args=[



                draft.draft_id,



            ],



        )



        response = self.client.post(



            url



        )



        self.assertEqual(



            response.status_code,



            302,



        )



        draft.refresh_from_db()



        self.assertEqual(



            draft.workflow_status,



            "awaiting_approval",



        )



        self.bank.refresh_from_db()



        self.assertEqual(



            self.bank.contact_status,



            "not_yet_contacted",



        )



    def test_reject_returns_draft_for_editing(self):



        draft = self.create_draft(



            workflow_status="awaiting_approval"



        )



        url = reverse(



            "reject_email_draft",



            args=[



                draft.draft_id,



            ],



        )



        response = self.client.post(



            url,



            {



                "version": draft.version, "rejection_reason": (



                    "Please revise the wording."



                ),



            },



        )



        self.assertEqual(



            response.status_code,



            302,



        )



        draft.refresh_from_db()



        self.assertEqual(



            draft.workflow_status,



            "changes_requested",



        )



        self.assertEqual(



            draft.rejection_reason,



            "Please revise the wording.",



        )



    def test_pending_draft_can_be_approved(self):



        draft = self.create_draft(



            workflow_status="awaiting_approval"



        )



        url = reverse(



            "approve_email_draft",



            args=[



                draft.draft_id,



            ],



        )



        response = self.client.post(url, {"version": draft.version})



        self.assertEqual(



            response.status_code,



            302,



        )



        draft.refresh_from_db()



        self.assertEqual(



            draft.workflow_status,



            "approved",



        )



        self.assertEqual(



            draft.approved_by,



            self.user,



        )



        self.assertIsNotNone(



            draft.approved_at,



        )



        self.assertEqual(



            draft.approved_version,



            draft.version,



        )



        self.bank.refresh_from_db()



        self.assertEqual(



            self.bank.contact_status,



            "not_yet_contacted",



        )



    def test_do_not_contact_blocks_approval(self):



        opportunity = self.create_opportunity(



            status="do_not_contact"



        )



        draft = self.create_draft(



            workflow_status="awaiting_approval",



            opportunity=opportunity,



        )



        url = reverse(



            "approve_email_draft",



            args=[



                draft.draft_id,



            ],



        )



        response = self.client.post(



            url, {"version": draft.version}, follow=True,



        )



        self.assertEqual(



            response.status_code,



            200,



        )



        draft.refresh_from_db()



        self.assertEqual(



            draft.workflow_status,



            "awaiting_approval",



        )



        self.assertContains(



            response,



            "Do Not Contact",



        )

    def test_editing_approved_draft_invalidates_approval(self):
        draft = self.create_draft(
            workflow_status="approved"
        )
        draft.approved_by = self.user
        draft.approved_at = timezone.now()
        draft.approved_version = draft.version
        draft.save(
            update_fields=[
                "approved_by",
                "approved_at",
                "approved_version",
            ]
        )

        original_version = draft.version

        url = reverse(
            "update_email_draft",
            args=[draft.draft_id],
        )

        response = self.client.post(
            url,
            {
                "subject": "Changed Subject",
                "body": "Changed body.",
                "version": original_version,
            },
        )

        self.assertEqual(response.status_code, 302)

        draft.refresh_from_db()

        self.assertEqual(draft.subject, "Changed Subject")
        self.assertEqual(draft.body, "Changed body.")
        self.assertEqual(draft.workflow_status, "draft")
        self.assertIsNone(draft.approved_by)
        self.assertIsNone(draft.approved_at)
        self.assertIsNone(draft.approved_version)
        self.assertEqual(
            draft.version,
            original_version + 1,
        )
        self.assertEqual(
            draft.last_edited_by,
            self.user,
        )
        self.assertTrue(
            draft.workflow_history.filter(
                action="approval_invalidated"
            ).exists()
        )

    def test_stale_draft_version_is_rejected(self):
        draft = self.create_draft()

        original_version = draft.version

        # Simulate another user saving a newer version first.
        draft.subject = "Newer saved subject"
        draft.version += 1
        draft.save(
            update_fields=[
                "subject",
                "version",
                "updated_at",
            ]
        )

        url = reverse(
            "update_email_draft",
            args=[draft.draft_id],
        )

        response = self.client.post(
            url,
            {
                "subject": "Stale user subject",
                "body": "Stale user body.",
                "version": original_version,
            },
            follow=True,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        draft.refresh_from_db()

        self.assertEqual(
            draft.subject,
            "Newer saved subject",
        )
        self.assertEqual(
            draft.version,
            original_version + 1,
        )
        self.assertNotEqual(
            draft.subject,
            "Stale user subject",
        )
        self.assertContains(
            response,
            "This draft has been changed by another user since you opened it",
        )

    def test_awaiting_approval_draft_can_be_withdrawn_for_editing(self):
        draft = self.create_draft(
            workflow_status="awaiting_approval"
        )

        url = reverse(
            "withdraw_email_draft",
            args=[draft.draft_id],
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)

        draft.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(
            draft.workflow_status,
            "draft",
        )
        self.assertEqual(
            self.bank.contact_status,
            "not_yet_contacted",
        )
        self.assertIsNone(draft.approved_by)
        self.assertIsNone(draft.approved_at)
        self.assertIsNone(draft.approved_version)

        history = draft.workflow_history.filter(
            action="withdrawn"
        ).first()

        self.assertIsNotNone(history)
        self.assertEqual(
            history.from_status,
            "awaiting_approval",
        )
        self.assertEqual(
            history.to_status,
            "draft",
        )
        self.assertEqual(
            history.performed_by,
            self.user,
        )

    @patch("outreach.views.EmailMessage.send")
    def test_successful_send_marks_draft_and_organisation_contacted(
        self,
        mock_send,
    ):
        mock_send.return_value = 1

        draft = self.make_approved_draft()

        url = reverse(
            "mark_email_draft_sent",
            args=[draft.draft_id],
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)

        draft.refresh_from_db()
        self.bank.refresh_from_db()
        draft.opportunity.refresh_from_db()

        self.assertEqual(draft.workflow_status, "sent")
        self.assertEqual(draft.sent_by, self.user)
        self.assertIsNotNone(draft.sent_at)
        self.assertEqual(
            self.bank.contact_status,
            "contacted",
        )
        self.assertEqual(
            draft.opportunity.status,
            "contacted",
        )
        self.assertTrue(
            draft.workflow_history.filter(
                action="send_started"
            ).exists()
        )
        self.assertTrue(
            draft.workflow_history.filter(
                action="sent"
            ).exists()
        )

        mock_send.assert_called_once()

    @patch("outreach.views.EmailMessage.send")
    def test_failed_send_keeps_organisation_not_contacted(
        self,
        mock_send,
    ):
        mock_send.side_effect = smtplib.SMTPConnectError(421, "Test SMTP failure")

        draft = self.make_approved_draft()
        url = reverse(
            "mark_email_draft_sent",
            args=[draft.draft_id],
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)

        draft.refresh_from_db()
        self.bank.refresh_from_db()
        draft.opportunity.refresh_from_db()

        self.assertEqual(
            draft.workflow_status,
            "send_failed",
        )
        self.assertEqual(
            self.bank.contact_status,
            "not_yet_contacted",
        )
        self.assertEqual(
            draft.opportunity.status,
            "not_yet_contacted",
        )
        self.assertIn(
            "Test SMTP failure",
            draft.send_failure_reason,
        )
        self.assertTrue(
            draft.workflow_history.filter(
                action="send_started"
            ).exists()
        )
        self.assertTrue(
            draft.workflow_history.filter(
                action="send_failed"
            ).exists()
        )

    @patch("outreach.views.EmailMessage.send")
    def test_failed_send_can_be_retried_successfully(
        self,
        mock_send,
    ):
        draft = self.make_approved_draft()
        url = reverse(
            "mark_email_draft_sent",
            args=[draft.draft_id],
        )

        mock_send.side_effect = smtplib.SMTPConnectError(421, "Test SMTP failure")

        first_response = self.client.post(url)
        self.assertEqual(
            first_response.status_code,
            302,
        )

        draft.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(
            draft.workflow_status,
            "send_failed",
        )
        self.assertEqual(
            self.bank.contact_status,
            "not_yet_contacted",
        )

        mock_send.reset_mock()
        mock_send.side_effect = None
        mock_send.return_value = 1

        retry_response = self.client.post(url)
        self.assertEqual(
            retry_response.status_code,
            302,
        )

        draft.refresh_from_db()
        self.bank.refresh_from_db()
        draft.opportunity.refresh_from_db()

        self.assertEqual(
            draft.workflow_status,
            "sent",
        )
        self.assertEqual(
            self.bank.contact_status,
            "contacted",
        )
        self.assertEqual(
            draft.opportunity.status,
            "contacted",
        )
        self.assertTrue(
            draft.workflow_history.filter(
                action="send_failed"
            ).exists()
        )
        self.assertTrue(
            draft.workflow_history.filter(
                action="sent"
            ).exists()
        )

        mock_send.assert_called_once()

    @patch("outreach.views.EmailMessage.send")
    def test_send_timeout_does_not_mark_organisation_contacted(
        self,
        mock_send,
    ):
        mock_send.side_effect = TimeoutError(
            "Test timeout"
        )

        draft = self.make_approved_draft()
        url = reverse(
            "mark_email_draft_sent",
            args=[draft.draft_id],
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)

        draft.refresh_from_db()
        self.bank.refresh_from_db()
        draft.opportunity.refresh_from_db()

        self.assertEqual(
            draft.workflow_status,
            "sending",
        )
        self.assertEqual(
            self.bank.contact_status,
            "not_yet_contacted",
        )
        self.assertEqual(
            draft.opportunity.status,
            "not_yet_contacted",
        )
        self.assertTrue(draft.send_failure_reason)
        self.assertTrue(
            draft.workflow_history.filter(
                action="send_started"
            ).exists()
        )

    @patch("outreach.views.EmailMessage.send")
    def test_sending_draft_cannot_be_sent_again(
        self,
        mock_send,
    ):
        draft = self.create_draft(
            workflow_status="sending"
        )

        draft.approved_by = self.user
        draft.approved_at = timezone.now()
        draft.approved_version = draft.version
        draft.save(
            update_fields=[
                "approved_by",
                "approved_at",
                "approved_version",
            ]
        )

        url = reverse(
            "mark_email_draft_sent",
            args=[draft.draft_id],
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)

        draft.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(
            draft.workflow_status,
            "sending",
        )
        self.assertEqual(
            self.bank.contact_status,
            "not_yet_contacted",
        )

        mock_send.assert_not_called()

    # -----------------------------------------------------
    # A. No approver available
    # -----------------------------------------------------
    def remove_approve_permission(self):
        self.user.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="outreach",
                codename="approve_emaildraft",
            )
        )

    def test_submit_without_approver_keeps_awaiting_and_flags(self):
        self.remove_approve_permission()

        draft = self.create_draft()

        response = self.client.post(
            reverse(
                "submit_email_draft_for_review",
                args=[draft.draft_id],
            )
        )

        self.assertEqual(response.status_code, 302)

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertTrue(draft.approver_unavailable)
        self.assertIsNone(draft.approved_by)
        self.assertTrue(
            draft.workflow_history.filter(
                action="no_approver_available"
            ).exists()
        )

    def test_submit_without_approver_notifies_admin(self):
        from django.core import mail

        self.remove_approve_permission()

        # An inactive superuser must not count as an available
        # approver, and must not be notified.
        get_user_model().objects.create_superuser(
            email="gone@example.com",
            first_name="Test",
            last_name="User",
            password="Testing123!",
            is_active=False,
        )
        mail.outbox.clear()

        draft = self.create_draft()

        self.client.post(
            reverse(
                "submit_email_draft_for_review",
                args=[draft.draft_id],
            )
        )

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertTrue(draft.approver_unavailable)
        # No active admin exists, so nothing can be emailed, but the
        # durable flag and history above remain.
        self.assertEqual(len(mail.outbox), 0)

    def test_notify_admins_emails_active_superuser(self):
        from django.core import mail
        from .approvals import notify_admins

        get_user_model().objects.create_superuser(
            email="pm@example.com",
            first_name="Test",
            last_name="User",
            password="Testing123!",
        )
        mail.outbox.clear()

        self.assertTrue(notify_admins("Subject", "Message"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("pm@example.com", mail.outbox[0].to)

    def test_submit_with_approver_does_not_flag_unavailable(self):
        approver = get_user_model().objects.create_user(
            email="approver@example.com",
            first_name="Test",
            last_name="User",
            password="Testing123!",
        )
        approver.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="outreach",
                codename="approve_emaildraft",
            )
        )

        draft = self.create_draft()

        self.client.post(
            reverse(
                "submit_email_draft_for_review",
                args=[draft.draft_id],
            )
        )

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertFalse(draft.approver_unavailable)
        self.assertFalse(
            draft.workflow_history.filter(
                action="no_approver_available"
            ).exists()
        )

    # -----------------------------------------------------
    # B. Overdue approval
    # -----------------------------------------------------
    @override_settings(EMAIL_APPROVAL_OVERDUE_HOURS=24)
    def test_overdue_approval_is_flagged_but_not_decided(self):
        from django.core import mail
        from .approvals import flag_overdue_approvals

        get_user_model().objects.create_superuser(
            email="pm@example.com",
            first_name="Test",
            last_name="User",
            password="Testing123!",
        )
        draft = self.create_draft(workflow_status="awaiting_approval")
        draft.submitted_at = timezone.now() - timedelta(hours=25)
        draft.save(update_fields=["submitted_at"])
        mail.outbox.clear()

        self.assertTrue(draft.is_approval_overdue)

        flagged = flag_overdue_approvals()

        self.assertEqual([d.pk for d in flagged], [draft.pk])

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertIsNone(draft.approved_by)
        self.assertIsNotNone(draft.overdue_flagged_at)
        self.assertTrue(
            draft.workflow_history.filter(action="approval_overdue").exists()
        )
        self.assertEqual(len(mail.outbox), 1)

        # Flagged only once.
        self.assertEqual(flag_overdue_approvals(), [])
        self.assertEqual(
            draft.workflow_history.filter(action="approval_overdue").count(),
            1,
        )

    @override_settings(EMAIL_APPROVAL_OVERDUE_HOURS=24)
    def test_recent_approval_is_not_overdue(self):
        from .approvals import flag_overdue_approvals

        draft = self.create_draft(workflow_status="awaiting_approval")
        draft.submitted_at = timezone.now() - timedelta(hours=1)
        draft.save(update_fields=["submitted_at"])

        self.assertFalse(draft.is_approval_overdue)
        self.assertEqual(flag_overdue_approvals(), [])

        draft.refresh_from_db()
        self.assertIsNone(draft.overdue_flagged_at)

    @override_settings(EMAIL_APPROVAL_OVERDUE_HOURS=1)
    def test_overdue_threshold_is_configurable(self):
        draft = self.create_draft(workflow_status="awaiting_approval")
        draft.submitted_at = timezone.now() - timedelta(hours=2)
        draft.save(update_fields=["submitted_at"])

        self.assertTrue(draft.is_approval_overdue)

    @override_settings(EMAIL_APPROVAL_OVERDUE_HOURS=1)
    def test_overdue_command_flags_without_changing_status(self):
        draft = self.create_draft(workflow_status="awaiting_approval")
        draft.submitted_at = timezone.now() - timedelta(hours=2)
        draft.save(update_fields=["submitted_at"])

        call_command("flag_overdue_approvals", stdout=StringIO())

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertIsNotNone(draft.overdue_flagged_at)

    # -----------------------------------------------------
    # C. Recipient email changes after approval
    # -----------------------------------------------------
    @patch("outreach.views.EmailMessage.send")
    def test_recipient_change_invalidates_approval_and_blocks_send(
        self,
        mock_send,
    ):
        draft = self.make_approved_draft()
        approved_version = draft.version

        self.bank.public_email = "new-contact@example.com"
        self.bank.save()

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "draft")
        self.assertIsNone(draft.approved_by)
        self.assertIsNone(draft.approved_at)
        self.assertIsNone(draft.approved_version)
        self.assertGreater(draft.version, approved_version)

        history = draft.workflow_history.get(action="recipient_changed")
        self.assertEqual(history.from_status, "approved")
        self.assertEqual(history.to_status, "draft")
        self.assertEqual(history.version, approved_version)
        self.assertEqual(history.recipient_email_snapshot, "bank@example.com")

        response = self.client.post(
            reverse("mark_email_draft_sent", args=[draft.draft_id])
        )
        self.assertEqual(response.status_code, 302)

        mock_send.assert_not_called()
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

    def test_recipient_change_returns_awaiting_draft_to_draft(self):
        draft = self.create_draft(workflow_status="awaiting_approval")

        self.bank.public_email = "other@example.com"
        self.bank.save()

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "draft")
        self.assertTrue(
            draft.workflow_history.filter(action="recipient_changed").exists()
        )

    def test_unchanged_recipient_keeps_approval(self):
        draft = self.make_approved_draft()

        self.bank.region = "New South Wales"
        self.bank.public_email = "BANK@example.com"
        self.bank.save()

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "approved")
        self.assertIsNotNone(draft.approved_version)
        self.assertFalse(
            draft.workflow_history.filter(action="recipient_changed").exists()
        )

    def test_reapproval_possible_after_recipient_update(self):
        draft = self.make_approved_draft()

        self.bank.public_email = "new-contact@example.com"
        self.bank.save()

        draft.refresh_from_db()
        self.client.post(
            reverse("update_email_draft", args=[draft.draft_id]),
            {
                "version": draft.version,
                "subject": "Updated subject",
                "body": "Updated body.",
            },
        )
        # Template-validation heuristics are covered elsewhere.
        EmailDraft.objects.filter(pk=draft.pk).update(is_incomplete=False)

        self.client.post(
            reverse("submit_email_draft_for_review", args=[draft.draft_id])
        )
        draft.refresh_from_db()
        self.client.post(reverse("approve_email_draft", args=[draft.draft_id]), {"version": draft.version})

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "approved")
        self.assertEqual(draft.recipient_email, "new-contact@example.com")
        self.assertEqual(draft.approved_version, draft.version)

    # -----------------------------------------------------
    # D. SMTP success but database finalisation fails
    # -----------------------------------------------------
    @patch("outreach.views.EmailMessage.send")
    def test_finalisation_failure_preserves_evidence_and_blocks_resend(
        self,
        mock_send,
    ):
        mock_send.return_value = 1

        draft = self.make_approved_draft()
        url = reverse("mark_email_draft_sent", args=[draft.draft_id])

        with patch.object(
            Bank,
            "save",
            side_effect=RuntimeError("database unavailable"),
        ):
            response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        mock_send.assert_called_once()

        draft.refresh_from_db()
        self.bank.refresh_from_db()
        draft.opportunity.refresh_from_db()

        self.assertEqual(draft.workflow_status, "sending")
        self.assertTrue(draft.reconciliation_required)
        self.assertIsNotNone(draft.smtp_confirmed_at)
        self.assertIsNone(draft.sent_at)
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")
        self.assertEqual(draft.opportunity.status, "not_yet_contacted")
        self.assertTrue(
            draft.workflow_history.filter(
                action="reconciliation_required"
            ).exists()
        )

        # A second attempt must never send a duplicate email.
        mock_send.reset_mock()
        second = self.client.post(url)
        self.assertEqual(second.status_code, 302)
        mock_send.assert_not_called()

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sending")

    @patch("outreach.views.EmailMessage.send")
    def test_reconciliation_flag_blocks_send_even_if_status_reset(
        self,
        mock_send,
    ):
        draft = self.make_approved_draft()
        draft.reconciliation_required = True
        draft.save(update_fields=["reconciliation_required"])

        self.client.post(
            reverse("mark_email_draft_sent", args=[draft.draft_id])
        )

        mock_send.assert_not_called()

    @patch("outreach.views.EmailMessage.send")
    def test_successful_send_records_smtp_confirmation(self, mock_send):
        mock_send.return_value = 1

        draft = self.make_approved_draft()
        self.client.post(
            reverse("mark_email_draft_sent", args=[draft.draft_id])
        )

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "sent")
        self.assertFalse(draft.reconciliation_required)
        self.assertIsNotNone(draft.smtp_confirmed_at)

    # -----------------------------------------------------
    # E. Unresolved placeholders
    # -----------------------------------------------------
    def test_submit_blocked_for_placeholders_in_body_and_subject(self):
        samples = [
            ("Subject", "Dear [Name], please reply."),
            ("Subject", "Dear {{ contact_name }}, please reply."),
            ("Hello {organisation}", "Dear team, please reply."),
            ("Subject", "Dear <name>, please reply."),
            ("Subject", "Dear %(name)s, please reply."),
            ("Subject", "Dear ${name}, please reply."),
            ("Subject", "Dear [INSERT RECIPIENT], please reply."),
        ]

        for subject, body in samples:
            with self.subTest(subject=subject, body=body):
                draft = self.create_draft()
                draft.subject = subject
                draft.body = body
                draft.save(update_fields=["subject", "body"])

                response = self.client.post(
                    reverse(
                        "submit_email_draft_for_review",
                        args=[draft.draft_id],
                    ),
                    follow=True,
                )

                draft.refresh_from_db()

                self.assertEqual(draft.workflow_status, "draft")
                self.assertContains(
                    response,
                    "unresolved placeholders",
                )
                self.assertFalse(
                    draft.workflow_history.filter(
                        action="submitted"
                    ).exists()
                )

                draft.opportunity.delete()

    def test_submit_allowed_after_placeholders_corrected(self):
        draft = self.create_draft()
        draft.body = "Dear [Name], please reply."
        draft.save(update_fields=["body"])

        url = reverse(
            "submit_email_draft_for_review",
            args=[draft.draft_id],
        )

        self.client.post(url)
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

        draft.body = "Dear Sam, please reply."
        draft.save(update_fields=["body"])

        self.client.post(url)
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")

    def test_find_unresolved_placeholders_ignores_normal_text(self):
        from .services import find_unresolved_placeholders

        self.assertEqual(
            find_unresolved_placeholders(
                "Road safety partnership",
                "Dear Sam, we saw 3 [1] items (see below) at 5 < 6 > 4. "
                "Kind regards, Shane",
            ),
            [],
        )
        self.assertEqual(
            find_unresolved_placeholders("[Name]", "Hi {name}"),
            ["[Name]", "{name}"],
        )

from .models import Contact
from .models import EmailDraftHistory



class ManualOrganisationEntryRequirementTests(TestCase):
    """Sprint 2 Week 2 - Add Organisation (Manual Entry) coverage."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="manual-entry@example.com",
            first_name="Manual",
            last_name="Entry",
            password="Testing123!",
        )
        self.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="outreach",
                codename__in=["add_bank", "add_branch", "add_club"],
            )
        )
        self.url = reverse("add_organisation")
        self.client.force_login(self.user)

    def bank_data(self, **overrides):
        data = {
            "organisation_type": "bank",
            "bank_name": "Community Bank Ballarat",
            "state": "VIC",
            "suburb": "Ballarat",
            "postcode": "3350",
            "website_url": "",
            "public_email": "",
            "public_phone": "",
            "source_url": "",
        }
        data.update(overrides)
        return data

    # --- FR-03 / FR-05
    def test_whitespace_only_required_fields_are_rejected(self):
        response = self.client.post(
            self.url,
            self.bank_data(bank_name="   ", postcode="   ", state=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Bank.objects.count(), 0)
        form = response.context["form"]
        self.assertIn("bank_name", form.errors)
        self.assertIn("postcode", form.errors)
        self.assertIn("state", form.errors)

    def test_values_are_trimmed_and_valid_values_preserved_on_error(self):
        response = self.client.post(
            self.url,
            self.bank_data(
                bank_name="  Trim Me Bank  ",
                postcode="12",
                suburb="  Ballarat ",
            ),
        )

        self.assertEqual(Bank.objects.count(), 0)
        self.assertContains(response, "Trim Me Bank")
        self.assertContains(response, "Enter a valid 4-digit")

        self.client.post(self.url, self.bank_data(bank_name="  Trim Me Bank  "))
        self.assertEqual(Bank.objects.get().bank_name, "Trim Me Bank")

    # --- FR-02 / FR-06
    def test_unsupported_organisation_type_is_rejected(self):
        response = self.client.post(
            self.url,
            self.bank_data(organisation_type="charity"),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Bank.objects.count(), 0)

    def test_branch_requires_parent_bank(self):
        response = self.client.post(
            self.url,
            {
                "organisation_type": "branch",
                "branch_name": "Orphan Branch",
                "state": "VIC",
                "postcode": "3350",
            },
        )

        self.assertIn("bank", response.context["form"].errors)
        self.assertEqual(Branch.objects.count(), 0)

    # --- FR-07
    def test_state_whitelist_is_enforced(self):
        for state in ("Victoria", "XX", "vic", "NZ"):
            with self.subTest(state=state):
                response = self.client.post(
                    self.url,
                    self.bank_data(state=state),
                )
                self.assertIn("state", response.context["form"].errors)

        self.assertEqual(Bank.objects.count(), 0)

    def test_every_valid_state_accepted_with_matching_postcode(self):
        samples = {
            "ACT": "2600",
            "NSW": "2000",
            "NT": "0800",
            "QLD": "4000",
            "SA": "5000",
            "TAS": "7000",
            "VIC": "3000",
            "WA": "6000",
        }

        for state, postcode in samples.items():
            with self.subTest(state=state):
                response = self.client.post(
                    self.url,
                    self.bank_data(
                        bank_name=f"Bank {state}",
                        state=state,
                        postcode=postcode,
                        suburb=f"Suburb {state}",
                    ),
                )
                self.assertEqual(response.status_code, 302)

        self.assertEqual(Bank.objects.count(), 8)

    def test_postcode_must_be_four_digits(self):
        for postcode in ("335", "33500", "abcd", "33 5"):
            with self.subTest(postcode=postcode):
                response = self.client.post(
                    self.url,
                    self.bank_data(postcode=postcode),
                )
                self.assertIn(
                    "postcode",
                    response.context["form"].errors,
                )

        self.assertEqual(Bank.objects.count(), 0)

    def test_postcode_must_be_compatible_with_state(self):
        response = self.client.post(
            self.url,
            self.bank_data(state="WA", postcode="3350"),
        )

        self.assertEqual(Bank.objects.count(), 0)
        self.assertIn("postcode", response.context["form"].errors)
        self.assertContains(response, "is not valid for WA")

    # --- FR-08
    def test_invalid_phone_email_and_url_are_rejected(self):
        response = self.client.post(
            self.url,
            self.bank_data(
                public_phone="12345",
                public_email="not-an-email",
                website_url="not a url",
            ),
        )

        errors = response.context["form"].errors
        self.assertIn("public_phone", errors)
        self.assertIn("public_email", errors)
        self.assertIn("website_url", errors)
        self.assertEqual(Bank.objects.count(), 0)

    def test_valid_australian_phone_formats_accepted(self):
        for index, phone in enumerate(
            (
                "0412 345 678",
                "(03) 9123 4567",
                "+61 3 9555 0000",
                "1300 123 456",
                "13 12 34",
            )
        ):
            with self.subTest(phone=phone):
                response = self.client.post(
                    self.url,
                    self.bank_data(
                        bank_name=f"Phone Bank {index}",
                        suburb=f"Suburb {index}",
                        postcode=str(3350 + index),
                        public_phone=phone,
                    ),
                )
                self.assertEqual(response.status_code, 302)

    def test_phone_with_invalid_area_code_rejected(self):
        for phone in ("0112345678", "0912345678", "03 1234"):
            with self.subTest(phone=phone):
                response = self.client.post(
                    self.url,
                    self.bank_data(public_phone=phone),
                )
                self.assertIn(
                    "public_phone",
                    response.context["form"].errors,
                )

    # --- FR-04 / edge case 1 / FR-11
    def test_organisation_created_without_any_contact_information(self):
        response = self.client.post(self.url, self.bank_data())

        self.assertEqual(response.status_code, 302)

        bank = Bank.objects.get()
        self.assertEqual(bank.public_email, "")
        self.assertEqual(bank.public_phone, "")
        self.assertEqual(bank.contact_status, "not_yet_contacted")
        self.assertEqual(bank.record_source, "Manual Entry")

        opportunity = Opportunity.objects.get(object_id=bank.pk)
        self.assertEqual(opportunity.status, "not_yet_contacted")

        # Outreach is unavailable until a valid recipient exists.
        self.assertEqual(Contact.objects.count(), 0)

    def test_optional_details_saved_without_marking_contacted(self):
        self.client.post(
            self.url,
            self.bank_data(
                public_email="hello@example.com",
                public_phone="03 9123 4567",
                website_url="https://example.com",
                address="1 Sturt St",
                contact_name="Alex Smith",
                contact_role="Manager",
                notes="Met at expo.",
            ),
        )

        bank = Bank.objects.get()
        self.assertEqual(bank.address, "1 Sturt St")
        self.assertEqual(bank.contact_status, "not_yet_contacted")

        contact = Contact.objects.get()
        self.assertEqual(contact.contact_name, "Alex Smith")
        self.assertEqual(contact.role, "Manager")

        opportunity = Opportunity.objects.get()
        self.assertEqual(opportunity.status, "not_yet_contacted")
        self.assertEqual(opportunity.notes, "Met at expo.")

    # --- FR-09
    def test_exact_duplicate_is_normalised_and_links_to_existing(self):
        self.client.post(self.url, self.bank_data())
        existing = Bank.objects.get()

        response = self.client.post(
            self.url,
            self.bank_data(
                bank_name="  community   BANK, ballarat! ",
                suburb="BALLARAT",
            ),
        )

        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(response.context["duplicate_organisation"], existing)
        self.assertContains(
            response,
            reverse(
                "organisation_detail",
                args=[
                    ContentType.objects.get_for_model(Bank).id,
                    existing.pk,
                ],
            ),
        )

    def test_same_name_in_different_state_is_not_exact_duplicate(self):
        self.client.post(self.url, self.bank_data())

        response = self.client.post(
            self.url,
            self.bank_data(state="NSW", postcode="2000", suburb="Sydney"),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Bank.objects.count(), 2)

    # --- FR-10 / edge case 3
    def test_likely_duplicate_requires_confirmation_then_stores_override(self):
        self.client.post(
            self.url,
            self.bank_data(
                public_phone="03 9123 4567",
                website_url="https://www.ballarat-bank.example.com/",
            ),
        )

        similar = self.bank_data(
            bank_name="Totally Different Name",
            suburb="Geelong",
            postcode="3220",
            public_phone="(03) 9123-4567",
            website_url="http://ballarat-bank.example.com",
        )

        first = self.client.post(self.url, similar)
        self.assertEqual(first.status_code, 200)
        self.assertIsNotNone(first.context["likely_duplicate_organisation"])
        self.assertEqual(Bank.objects.count(), 1)

        no_reason = self.client.post(
            self.url,
            {**similar, "confirm_likely_duplicate": "1"},
        )
        self.assertEqual(Bank.objects.count(), 1)
        self.assertIsNotNone(no_reason.context["override_reason_error"])

        done = self.client.post(
            self.url,
            {
                **similar,
                "confirm_likely_duplicate": "1",
                "duplicate_override_reason": "Different branch office.",
            },
        )
        self.assertEqual(done.status_code, 302)

        created = Bank.objects.get(bank_name="Totally Different Name")
        self.assertEqual(created.duplicate_override_by, self.user)
        self.assertEqual(
            created.duplicate_override_reason,
            "Different branch office.",
        )
        self.assertIsNotNone(created.duplicate_override_at)

    def test_same_email_is_likely_duplicate(self):
        self.client.post(
            self.url,
            self.bank_data(public_email="shared@example.com"),
        )

        response = self.client.post(
            self.url,
            self.bank_data(
                bank_name="Other Org",
                suburb="Bendigo",
                postcode="3550",
                public_email="SHARED@example.com",
            ),
        )

        self.assertEqual(Bank.objects.count(), 1)
        self.assertIsNotNone(response.context["likely_duplicate_organisation"])

    # --- FR-12 / FR-13 / FR-14
    def test_success_message_redirect_and_audit_fields(self):
        response = self.client.post(
            self.url,
            self.bank_data(),
            follow=True,
        )

        bank = Bank.objects.get()
        content_type = ContentType.objects.get_for_model(Bank)

        self.assertRedirects(
            response,
            reverse(
                "organisation_detail",
                args=[content_type.id, bank.pk],
            ),
        )
        self.assertContains(
            response,
            "Community Bank Ballarat has been added successfully.",
        )
        self.assertContains(response, "Not Yet Contacted")

        self.assertEqual(bank.created_by, self.user)
        self.assertIsNotNone(bank.date_added)
        self.assertIsNotNone(bank.organisation_id)
        self.assertEqual(bank.record_source, "Manual Entry")
        self.assertEqual(Opportunity.objects.filter(object_id=bank.pk).count(), 1)

    # --- FR-01
    def test_user_without_permission_creates_nothing(self):
        self.user.user_permissions.clear()

        response = self.client.post(self.url, self.bank_data())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Bank.objects.count(), 0)
        self.assertEqual(Opportunity.objects.count(), 0)

    # --- FR-16
    def test_system_failure_creates_no_partial_record_and_hides_error(self):
        with patch(
            "outreach.views.Opportunity.objects.create",
            side_effect=RuntimeError("secret database detail"),
        ):
            response = self.client.post(self.url, self.bank_data())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Bank.objects.count(), 0)
        self.assertContains(response, "could not be saved")
        self.assertNotContains(response, "secret database detail")
        self.assertContains(response, "Community Bank Ballarat")

        # Retry succeeds.
        retry = self.client.post(self.url, self.bank_data())
        self.assertEqual(retry.status_code, 302)
        self.assertEqual(Bank.objects.count(), 1)

    # --- FR-17
    def test_double_submit_creates_exactly_one_record(self):
        first = self.client.post(self.url, self.bank_data())
        second = self.client.post(self.url, self.bank_data())

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(Opportunity.objects.count(), 1)

    def test_race_between_precheck_and_save_creates_one_record(self):
        """
        Another submission commits after this request's first duplicate
        check but before its save: the in-transaction re-check must stop
        the second record.
        """
        from . import views

        real_find = views._find_exact_duplicate
        calls = {"count": 0}

        def racing_find(organisation_type, cleaned_data):
            calls["count"] += 1

            if calls["count"] == 1:
                Bank.objects.create(
                    bank_name="Community Bank Ballarat",
                    region="VIC",
                    state="VIC",
                    suburb="Ballarat",
                    postcode="3350",
                )
                return None

            return real_find(organisation_type, cleaned_data)

        with patch.object(
            views,
            "_find_exact_duplicate",
            racing_find,
        ), patch.object(
            views,
            "_find_likely_duplicate",
            return_value=None,
        ):
            # The first check is the pre-check; the second runs inside
            # the transaction after the competing record exists.
            response = self.client.post(self.url, self.bank_data())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Bank.objects.count(), 1)
        self.assertIsNotNone(response.context["duplicate_organisation"])

    def test_creation_lock_row_is_used(self):
        from .models import OrganisationCreationLock

        self.client.post(self.url, self.bank_data())

        lock = OrganisationCreationLock.objects.get(key="add_organisation")
        self.assertEqual(lock.counter, 1)

    # --- FR-18
    def test_script_markup_is_escaped_when_displayed(self):
        payload = "<script>alert('xss')</script>"

        response = self.client.post(
            self.url,
            self.bank_data(
                bank_name=payload,
                contact_name=payload,
                notes=payload,
            ),
            follow=True,
        )

        bank = Bank.objects.get()
        self.assertEqual(bank.bank_name, payload)

        content = response.content.decode()
        self.assertNotIn(payload, content)
        self.assertIn("&lt;script&gt;alert(", content)

        # Also escaped on the validation-error redisplay of the form.
        error_page = self.client.post(
            self.url,
            self.bank_data(bank_name=payload, postcode="12"),
        )
        self.assertNotIn(payload, error_page.content.decode())

    # --- FR-03: region OR suburb (genuine value, state never copied)
    def test_region_without_suburb_is_valid(self):
        response = self.client.post(
            self.url,
            self.bank_data(region="Gippsland", suburb=""),
        )

        self.assertEqual(response.status_code, 302)

        bank = Bank.objects.get()
        self.assertEqual(bank.region, "Gippsland")
        self.assertEqual(bank.suburb, "")

    def test_suburb_without_region_is_valid_and_state_not_copied(self):
        response = self.client.post(
            self.url,
            self.bank_data(region="", suburb="Ballarat"),
        )

        self.assertEqual(response.status_code, 302)

        bank = Bank.objects.get()
        self.assertEqual(bank.suburb, "Ballarat")
        self.assertEqual(bank.region, "")
        self.assertEqual(bank.state, "VIC")

    def test_both_region_and_suburb_empty_is_invalid(self):
        response = self.client.post(
            self.url,
            self.bank_data(
                region="",
                suburb="",
                bank_name="Keep Me Bank",
                postcode="3350",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Bank.objects.count(), 0)

        errors = response.context["form"].errors
        self.assertIn("region", errors)
        self.assertIn("suburb", errors)
        self.assertContains(response, "Enter a region or a suburb")

        # Other entered values are preserved.
        self.assertContains(response, "Keep Me Bank")
        self.assertEqual(
            response.context["form"]["postcode"].value(),
            "3350",
        )

    def test_whitespace_only_region_and_suburb_is_invalid(self):
        response = self.client.post(
            self.url,
            self.bank_data(region="   ", suburb="   "),
        )

        self.assertEqual(Bank.objects.count(), 0)
        self.assertIn("region", response.context["form"].errors)
        self.assertIn("suburb", response.context["form"].errors)

    def test_region_or_suburb_required_for_branch_and_club(self):
        bank = Bank.objects.create(
            bank_name="Parent Bank",
            region="VIC",
            state="VIC",
            suburb="Melbourne",
            postcode="3000",
        )

        branch_data = {
            "organisation_type": "branch",
            "bank": bank.pk,
            "branch_name": "Some Branch",
            "state": "VIC",
            "postcode": "3350",
            "region": "",
            "suburb": "  ",
        }
        club_data = {
            "organisation_type": "club",
            "club_name": "Some Club",
            "state": "VIC",
            "postcode": "3350",
            "region": "",
            "suburb": "",
        }

        for data in (branch_data, club_data):
            with self.subTest(type=data["organisation_type"]):
                response = self.client.post(self.url, data)
                self.assertIn("region", response.context["form"].errors)

                ok = self.client.post(
                    self.url,
                    {**data, "region": "Central Highlands"},
                )
                self.assertEqual(ok.status_code, 302)

        self.assertEqual(Branch.objects.count(), 1)
        self.assertEqual(Club.objects.count(), 1)

from .models import Contact


import smtplib
import ssl

from django.db import connection
from django.test.utils import CaptureQueriesContext


class EmailApprovalHardeningTests(TestCase):
    """
    Business-logic tests for the approval workflow (BA TC-01..TC-20).

    Concurrency note: the test database is SQLite (in-memory), which
    does not support parallel writers inside a test. Competing
    decisions are therefore tested as strictly ordered requests (the
    second must be refused because the first already changed the
    state/version), plus a query-level assertion that every
    transition takes the write lock before reading. True parallel
    contention should be exercised against the production database.
    """

    setUp = EmailDraftWorkflowTests.setUp
    create_opportunity = EmailDraftWorkflowTests.create_opportunity
    create_draft = EmailDraftWorkflowTests.create_draft
    make_approved_draft = EmailDraftWorkflowTests.make_approved_draft

    # ---------------------------------------------------- helpers
    def url(self, name, draft):
        return reverse(name, args=[draft.draft_id])

    def history_actions(self, draft):
        return list(
            draft.workflow_history.values_list("action", flat=True)
        )

    def other_user(self, perms=()):
        user = get_user_model().objects.create_user(
            email=f"other-{len(perms)}-{get_user_model().objects.count()}@example.com",
            first_name="Other",
            last_name="User",
            password="Testing123!",
        )
        user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="outreach",
                codename__in=list(perms),
            )
        )
        return user

    def edit(self, draft, subject="Edited subject", body="Edited body."):
        draft.refresh_from_db()
        self.client.post(
            self.url("update_email_draft", draft),
            {
                "version": draft.version,
                "subject": subject,
                "body": body,
            },
        )
        EmailDraft.objects.filter(pk=draft.pk).update(is_incomplete=False)
        draft.refresh_from_db()

    # ---------------------------------------- TC-14 content at approval
    @patch("outreach.views.EmailMessage.send")
    def test_approval_blocked_for_invalid_content(self, mock_send):
        cases = {
            "missing subject": {"subject": ""},
            "missing body": {"body": "   "},
            "placeholder in body": {"body": "Dear [Name], please reply."},
            "placeholder in subject": {"subject": "Hello {{ org }}"},
            "incomplete": {"is_incomplete": True},
        }

        for label, changes in cases.items():
            with self.subTest(label):
                draft = self.create_draft(
                    workflow_status="awaiting_approval"
                )
                for field, value in changes.items():
                    setattr(draft, field, value)
                draft.save()

                response = self.client.post(
                    self.url("approve_email_draft", draft),
                    {"version": draft.version},
                    follow=True,
                )

                draft.refresh_from_db()

                self.assertEqual(draft.workflow_status, "awaiting_approval")
                self.assertIsNone(draft.approved_version)
                self.assertNotIn("approved", self.history_actions(draft))
                self.assertContains(response, "cannot be approved")

        mock_send.assert_not_called()

    # ---------------------------------------- viewed version (stale pages)
    def test_stale_approve_after_withdraw_edit_resubmit_is_refused(self):
        draft = self.create_draft(workflow_status="awaiting_approval")
        viewed_version = draft.version

        self.client.post(self.url("withdraw_email_draft", draft))
        self.edit(draft)
        self.client.post(self.url("submit_email_draft_for_review", draft))

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertGreater(draft.version, viewed_version)

        history_before = self.history_actions(draft)

        stale = self.client.post(
            self.url("approve_email_draft", draft),
            {"version": viewed_version},
            follow=True,
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertIsNone(draft.approved_version)
        self.assertEqual(self.history_actions(draft), history_before)
        self.assertContains(stale, "changed since you opened it")

        fresh = self.client.post(
            self.url("approve_email_draft", draft),
            {"version": draft.version},
        )
        self.assertEqual(fresh.status_code, 302)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "approved")
        self.assertEqual(draft.approved_version, draft.version)

    def test_stale_or_missing_version_on_reject_changes_nothing(self):
        draft = self.create_draft(workflow_status="awaiting_approval")
        history_before = self.history_actions(draft)

        for data in (
            {"rejection_reason": "Fix it"},
            {"rejection_reason": "Fix it", "version": "abc"},
            {"rejection_reason": "Fix it", "version": draft.version + 1},
        ):
            self.client.post(self.url("reject_email_draft", draft), data)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertEqual(draft.rejection_reason, "")
        self.assertEqual(self.history_actions(draft), history_before)

    def test_approve_without_version_is_refused(self):
        draft = self.create_draft(workflow_status="awaiting_approval")

        self.client.post(self.url("approve_email_draft", draft))

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertNotIn("approved", self.history_actions(draft))

    # ---------------------------------------- TC-17 competing decisions
    def test_second_competing_decision_is_refused(self):
        for first, second in (
            ("approve_email_draft", "reject_email_draft"),
            ("reject_email_draft", "approve_email_draft"),
        ):
            with self.subTest(first=first):
                draft = self.create_draft(
                    workflow_status="awaiting_approval"
                )
                data = {
                    "version": draft.version,
                    "rejection_reason": "Needs work",
                }

                self.client.post(self.url(first, draft), data)
                self.client.post(self.url(second, draft), data)

                draft.refresh_from_db()
                decisions = [
                    a
                    for a in self.history_actions(draft)
                    if a in ("approved", "changes_requested")
                ]
                self.assertEqual(len(decisions), 1)
                expected = (
                    "approved"
                    if first == "approve_email_draft"
                    else "changes_requested"
                )
                self.assertEqual(decisions, [expected])

    def test_transitions_take_the_write_lock_before_reading(self):
        draft = self.create_draft(workflow_status="awaiting_approval")

        with CaptureQueriesContext(connection) as queries:
            self.client.post(
                self.url("approve_email_draft", draft),
                {"version": draft.version},
            )

        statements = [q["sql"] for q in queries.captured_queries]
        lock_index = next(
            i
            for i, sql in enumerate(statements)
            if sql.startswith('UPDATE "outreach_emaildraft" SET "version"')
        )
        first_draft_read = next(
            i
            for i, sql in enumerate(statements)
            if sql.startswith("SELECT") and '"outreach_emaildraft"' in sql
        )
        self.assertLessEqual(lock_index, first_draft_read)

    # ---------------------------------------- cancel versus send
    @patch("outreach.views.EmailMessage.send")
    def test_cancel_cannot_overwrite_sending(self, mock_send):
        draft = self.make_approved_draft()
        EmailDraft.objects.filter(pk=draft.pk).update(
            workflow_status="sending"
        )

        self.client.post(
            self.url("cancel_email_draft", draft),
            {"cancellation_reason": "Changed my mind"},
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sending")
        self.assertNotIn("cancelled", self.history_actions(draft))
        mock_send.assert_not_called()

    @patch("outreach.views.EmailMessage.send")
    def test_cancelled_draft_cannot_be_sent(self, mock_send):
        draft = self.make_approved_draft()

        self.client.post(
            self.url("cancel_email_draft", draft),
            {"cancellation_reason": "No longer needed"},
        )
        self.client.post(self.url("mark_email_draft_sent", draft))

        draft.refresh_from_db()
        self.bank.refresh_from_db()
        self.assertEqual(draft.workflow_status, "cancelled")
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")
        mock_send.assert_not_called()

    # ---------------------------------------- unknown delivery
    def test_unknown_delivery_errors_flag_reconciliation_and_block_resend(self):
        errors = [
            TimeoutError("timed out"),
            smtplib.SMTPServerDisconnected("dropped"),
            ConnectionResetError("reset"),
            ssl.SSLError("tls broke"),
        ]

        for error in errors:
            with self.subTest(error=type(error).__name__):
                draft = self.make_approved_draft()
                url = self.url("mark_email_draft_sent", draft)

                with patch(
                    "outreach.views.EmailMessage.send",
                    side_effect=error,
                ) as mock_send:
                    self.client.post(url)
                    self.client.post(url)

                draft.refresh_from_db()
                self.bank.refresh_from_db()

                self.assertEqual(draft.workflow_status, "sending")
                self.assertTrue(draft.reconciliation_required)
                self.assertIn("uncertain", draft.send_failure_reason)
                self.assertEqual(self.bank.contact_status, "not_yet_contacted")
                self.assertIn(
                    "reconciliation_required",
                    self.history_actions(draft),
                )
                self.assertNotIn("send_failed", self.history_actions(draft))
                # The second attempt must not call the mail backend.
                self.assertEqual(mock_send.call_count, 1)

                draft.opportunity.delete()

    def test_confirmed_failure_remains_retryable(self):
        draft = self.make_approved_draft()
        url = self.url("mark_email_draft_sent", draft)

        with patch(
            "outreach.views.EmailMessage.send",
            side_effect=smtplib.SMTPAuthenticationError(535, b"bad login"),
        ):
            self.client.post(url)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "send_failed")
        self.assertFalse(draft.reconciliation_required)

        with patch(
            "outreach.views.EmailMessage.send",
            return_value=1,
        ) as mock_send:
            self.client.post(url)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sent")
        mock_send.assert_called_once()

    # ---------------------------------------- reject rules
    def test_reject_without_reason_keeps_awaiting_approval(self):
        draft = self.create_draft(workflow_status="awaiting_approval")
        history_before = self.history_actions(draft)

        for reason in ("", "   "):
            self.client.post(
                self.url("reject_email_draft", draft),
                {"version": draft.version, "rejection_reason": reason},
            )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertEqual(self.history_actions(draft), history_before)

    @patch("outreach.views.EmailMessage.send")
    def test_reject_edit_resubmit_approve_latest_version(self, mock_send):
        mock_send.return_value = 1
        draft = self.create_draft(workflow_status="awaiting_approval")
        rejected_version = draft.version

        self.client.post(
            self.url("reject_email_draft", draft),
            {"version": draft.version, "rejection_reason": "Too vague"},
        )
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "changes_requested")

        # A rejected version can never be sent.
        self.client.post(self.url("mark_email_draft_sent", draft))
        mock_send.assert_not_called()

        self.edit(draft)
        self.assertEqual(draft.workflow_status, "draft")
        self.assertGreater(draft.version, rejected_version)

        self.client.post(self.url("submit_email_draft_for_review", draft))
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")

        self.client.post(
            self.url("approve_email_draft", draft),
            {"version": draft.version},
        )
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "approved")
        self.assertEqual(draft.approved_version, draft.version)
        self.assertNotEqual(draft.approved_version, rejected_version)

        history = self.history_actions(draft)
        self.assertIn("changes_requested", history)
        self.assertIn("edited", history)
        self.assertEqual(history.count("submitted"), 1)
        self.assertIn("approved", history)
        mock_send.assert_not_called()

    # ---------------------------------------- send blocked states
    @patch("outreach.views.EmailMessage.send")
    def test_send_blocked_before_approval(self, mock_send):
        for status in ("draft", "awaiting_approval", "changes_requested"):
            with self.subTest(status=status):
                draft = self.create_draft(workflow_status=status)

                self.client.post(self.url("mark_email_draft_sent", draft))

                draft.refresh_from_db()
                self.bank.refresh_from_db()
                self.assertEqual(draft.workflow_status, status)
                self.assertEqual(self.bank.contact_status, "not_yet_contacted")
                self.assertNotIn("send_started", self.history_actions(draft))

                draft.opportunity.delete()

        mock_send.assert_not_called()

    # ---------------------------------------- permissions
    @patch("outreach.views.EmailMessage.send")
    def test_permission_denied_for_submit_approve_reject_and_send(
        self,
        mock_send,
    ):
        self.user.user_permissions.clear()

        draft = self.create_draft()
        self.client.post(self.url("submit_email_draft_for_review", draft))
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

        awaiting = self.create_draft(workflow_status="awaiting_approval")
        self.client.post(
            self.url("approve_email_draft", awaiting),
            {"version": awaiting.version},
        )
        self.client.post(
            self.url("reject_email_draft", awaiting),
            {"version": awaiting.version, "rejection_reason": "No"},
        )
        awaiting.refresh_from_db()
        self.assertEqual(awaiting.workflow_status, "awaiting_approval")
        self.assertEqual(
            self.history_actions(awaiting),
            [],
        )

        approved = self.make_approved_draft()
        self.client.post(self.url("mark_email_draft_sent", approved))
        approved.refresh_from_db()
        self.bank.refresh_from_db()
        self.assertEqual(approved.workflow_status, "approved")
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")

        mock_send.assert_not_called()

    # ---------------------------------------- cancellation
    def test_cancel_records_history_and_clears_approval(self):
        for status in ("awaiting_approval", "approved"):
            with self.subTest(status=status):
                draft = (
                    self.make_approved_draft()
                    if status == "approved"
                    else self.create_draft(workflow_status=status)
                )

                self.client.post(
                    self.url("cancel_email_draft", draft),
                    {"cancellation_reason": "Wrong organisation"},
                )

                draft.refresh_from_db()
                self.bank.refresh_from_db()
                self.assertEqual(draft.workflow_status, "cancelled")
                self.assertIsNone(draft.approved_version)
                self.assertEqual(draft.cancelled_by, self.user)
                self.assertEqual(self.bank.contact_status, "not_yet_contacted")

                entry = draft.workflow_history.get(action="cancelled")
                self.assertEqual(entry.from_status, status)
                self.assertEqual(entry.to_status, "cancelled")
                self.assertEqual(entry.reason, "Wrong organisation")

                draft.opportunity.delete()

    def test_cancel_requires_reason(self):
        draft = self.create_draft(workflow_status="awaiting_approval")

        self.client.post(
            self.url("cancel_email_draft", draft),
            {"cancellation_reason": "  "},
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertNotIn("cancelled", self.history_actions(draft))

    # ---------------------------------------- Do Not Contact (TC-15)
    @patch("outreach.views.EmailMessage.send")
    def test_do_not_contact_blocks_submit_approve_and_send_with_audit(
        self,
        mock_send,
    ):
        opportunity = self.create_opportunity(status="do_not_contact")

        draft = self.create_draft(opportunity=opportunity)
        self.client.post(self.url("submit_email_draft_for_review", draft))
        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "draft")

        awaiting = self.create_draft(
            workflow_status="awaiting_approval",
            opportunity=opportunity,
        )
        self.client.post(
            self.url("approve_email_draft", awaiting),
            {"version": awaiting.version},
        )
        awaiting.refresh_from_db()
        self.assertEqual(awaiting.workflow_status, "awaiting_approval")

        approved = self.create_draft(
            workflow_status="approved",
            opportunity=opportunity,
        )
        approved.approved_version = approved.version
        approved.save(update_fields=["approved_version"])
        self.client.post(self.url("mark_email_draft_sent", approved))
        approved.refresh_from_db()
        self.assertEqual(approved.workflow_status, "approved")

        self.bank.refresh_from_db()
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")
        mock_send.assert_not_called()

        for blocked in (draft, awaiting, approved):
            entry = blocked.workflow_history.get(
                action="blocked_do_not_contact"
            )
            self.assertIn("Do Not Contact", entry.reason)
            self.assertEqual(entry.performed_by, self.user)

    def test_unclassified_exception_is_treated_as_unknown_delivery(self):
        draft = self.make_approved_draft()
        url = self.url("mark_email_draft_sent", draft)

        with patch(
            "outreach.views.EmailMessage.send",
            side_effect=ValueError("something unexpected"),
        ) as mock_send:
            self.client.post(url)
            self.client.post(url)

        draft.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(draft.workflow_status, "sending")
        self.assertTrue(draft.reconciliation_required)
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")
        self.assertIn("reconciliation_required", self.history_actions(draft))
        self.assertNotIn("send_failed", self.history_actions(draft))
        self.assertEqual(mock_send.call_count, 1)

    def test_known_non_delivery_errors_remain_retryable(self):
        errors = [
            smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no")}),
            smtplib.SMTPSenderRefused(550, b"no", "me@example.com"),
            ConnectionRefusedError("refused"),
            EmailNotSentError("Email backend reported that no message was sent."),
        ]

        for error in errors:
            with self.subTest(error=type(error).__name__):
                draft = self.make_approved_draft()

                with patch(
                    "outreach.views.EmailMessage.send",
                    side_effect=error,
                ):
                    self.client.post(
                        self.url("mark_email_draft_sent", draft)
                    )

                draft.refresh_from_db()
                self.assertEqual(draft.workflow_status, "send_failed")
                self.assertFalse(draft.reconciliation_required)

                draft.opportunity.delete()

    def test_email_timeout_setting_is_finite(self):
        from django.conf import settings as django_settings

        self.assertIsNotNone(django_settings.EMAIL_TIMEOUT)
        self.assertGreater(django_settings.EMAIL_TIMEOUT, 0)

    def test_unexpected_runtime_error_requires_reconciliation(self):
        draft = self.make_approved_draft()
        url = self.url("mark_email_draft_sent", draft)

        with patch(
            "outreach.views.EmailMessage.send",
            side_effect=RuntimeError("unexpected backend failure"),
        ) as mock_send:
            self.client.post(url)
            self.client.post(url)

        draft.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(draft.workflow_status, "sending")
        self.assertTrue(draft.reconciliation_required)
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")
        self.assertNotIn("send_failed", self.history_actions(draft))
        self.assertEqual(mock_send.call_count, 1)

    def test_backend_returning_zero_is_confirmed_and_retryable(self):
        draft = self.make_approved_draft()
        url = self.url("mark_email_draft_sent", draft)

        with patch(
            "outreach.views.EmailMessage.send",
            return_value=0,
        ):
            self.client.post(url)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "send_failed")
        self.assertFalse(draft.reconciliation_required)

        with patch(
            "outreach.views.EmailMessage.send",
            return_value=1,
        ) as mock_send:
            self.client.post(url)

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sent")
        mock_send.assert_called_once()

    def test_unexpected_send_count_is_unknown_delivery(self):
        draft = self.make_approved_draft()

        with patch(
            "outreach.views.EmailMessage.send",
            return_value=2,
        ):
            self.client.post(self.url("mark_email_draft_sent", draft))

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sending")
        self.assertTrue(draft.reconciliation_required)

    # ------------------------------------------------------------------
    # Recipient change versus send claim.
    # These are ORDERED / INTERLEAVED (simulated) tests, not parallel
    # contention tests.
    # ------------------------------------------------------------------
    def test_recipient_change_while_sending_does_not_overwrite_sending(self):
        draft = self.make_approved_draft()
        EmailDraft.objects.filter(pk=draft.pk).update(
            workflow_status="sending"
        )
        version = draft.version

        self.bank.public_email = "changed@example.com"
        self.bank.save()

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "sending")
        self.assertEqual(draft.version, version)
        self.assertEqual(draft.approved_version, version)
        self.assertEqual(draft.recipient_email, "bank@example.com")

        entry = draft.workflow_history.get(action="recipient_changed")
        self.assertEqual(entry.from_status, "sending")
        self.assertEqual(entry.to_status, "sending")
        self.assertIn("already being sent", entry.reason)

    def test_recipient_change_does_not_touch_sent_draft(self):
        draft = self.make_approved_draft()
        EmailDraft.objects.filter(pk=draft.pk).update(
            workflow_status="sent"
        )

        self.bank.public_email = "changed@example.com"
        self.bank.save()

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "sent")
        self.assertFalse(
            draft.workflow_history.filter(action="recipient_changed").exists()
        )

    def test_stale_candidate_cannot_overwrite_a_claimed_send(self):
        """
        Interleaving: the invalidation reads the draft as Approved, then
        the send claim commits before the invalidation writes. The
        conditional update must not overwrite Sending.
        """
        from . import models as outreach_models

        draft = self.make_approved_draft()
        real = outreach_models._lock_recipient_candidates

        def read_then_claim(content_type, object_id):
            stale = real(content_type, object_id)
            EmailDraft.objects.filter(pk=draft.pk).update(
                workflow_status="sending"
            )
            return stale

        with patch.object(
            outreach_models,
            "_lock_recipient_candidates",
            side_effect=read_then_claim,
        ):
            self.bank.public_email = "changed@example.com"
            self.bank.save()

        draft.refresh_from_db()

        self.assertEqual(draft.workflow_status, "sending")
        self.assertEqual(draft.approved_version, draft.version)
        self.assertFalse(
            draft.workflow_history.filter(
                action="recipient_changed",
                to_status="draft",
            ).exists()
        )

    @patch("outreach.views.EmailMessage.send")
    def test_send_claim_after_invalidation_sends_nothing(self, mock_send):
        draft = self.make_approved_draft()
        stale_approved_version = draft.approved_version

        self.bank.public_email = "changed@example.com"
        self.bank.save()

        # A request that loaded the draft before the change still has
        # the old approved version; the claim must not match.
        claimed = EmailDraft.objects.filter(
            pk=draft.pk,
            workflow_status__in=["approved", "send_failed"],
            version=stale_approved_version,
        ).update(workflow_status="sending")

        self.assertEqual(claimed, 0)
        self.client.post(self.url("mark_email_draft_sent", draft))
        mock_send.assert_not_called()



class PendingApprovalsQueueTests(TestCase):
    """TC-01: submitted drafts are visible to authorised approvers."""

    create_opportunity = EmailDraftWorkflowTests.create_opportunity
    create_draft = EmailDraftWorkflowTests.create_draft
    make_approved_draft = EmailDraftWorkflowTests.make_approved_draft

    def setUp(self):
        EmailDraftWorkflowTests.setUp(self)
        self.queue_url = reverse("pending_approvals")

    def pending(self, **kwargs):
        draft = self.create_draft(workflow_status="awaiting_approval")
        for field, value in kwargs.items():
            setattr(draft, field, value)
        draft.save()
        return draft

    def rows(self, response):
        return [row["draft"].pk for row in response.context["rows"]]

    def test_approver_sees_queue_with_details_and_review_link(self):
        draft = self.pending(subject="Partnership <b>proposal</b>")
        draft.submitted_at = timezone.now()
        draft.save(update_fields=["submitted_at"])
        EmailDraftHistory.objects.create(
            draft=draft,
            action="submitted",
            from_status="draft",
            to_status="awaiting_approval",
            version=draft.version,
            performed_by=self.user,
        )

        response = self.client.get(self.queue_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rows(response), [draft.pk])
        self.assertContains(response, "AI Test Community Bank")
        self.assertContains(response, "Partnership &lt;b&gt;proposal&lt;/b&gt;")
        self.assertNotContains(response, "<b>proposal</b>")
        self.assertContains(response, "AI Tester")

        review_url = reverse(
            "organisation_detail",
            args=[self.content_type.pk, self.bank.pk],
        )
        self.assertContains(response, f'href="{review_url}"')

    def test_missing_submission_data_shows_not_recorded(self):
        self.pending()

        response = self.client.get(self.queue_url)

        self.assertContains(response, "Not recorded")

    def test_only_awaiting_approval_drafts_are_listed(self):
        awaiting = self.pending()

        for status in (
            "draft",
            "changes_requested",
            "approved",
            "sending",
            "sent",
            "send_failed",
            "cancelled",
        ):
            self.create_draft(workflow_status=status)

        response = self.client.get(self.queue_url)

        self.assertEqual(self.rows(response), [awaiting.pk])

    def test_empty_state(self):
        response = self.client.get(self.queue_url)

        self.assertEqual(self.rows(response), [])
        self.assertContains(response, "No drafts are awaiting approval.")

    def test_draft_leaves_queue_after_each_transition(self):
        transitions = {
            "approve": lambda d: self.client.post(
                reverse("approve_email_draft", args=[d.draft_id]),
                {"version": d.version},
            ),
            "reject": lambda d: self.client.post(
                reverse("reject_email_draft", args=[d.draft_id]),
                {"version": d.version, "rejection_reason": "Fix"},
            ),
            "withdraw": lambda d: self.client.post(
                reverse("withdraw_email_draft", args=[d.draft_id])
            ),
            "cancel": lambda d: self.client.post(
                reverse("cancel_email_draft", args=[d.draft_id]),
                {"cancellation_reason": "No longer needed"},
            ),
        }

        for name, action in transitions.items():
            with self.subTest(name):
                draft = self.pending()
                self.assertIn(
                    draft.pk,
                    self.rows(self.client.get(self.queue_url)),
                )

                action(draft)

                self.assertNotIn(
                    draft.pk,
                    self.rows(self.client.get(self.queue_url)),
                )
                draft.opportunity.delete()

    def test_user_without_approval_permission_is_denied(self):
        self.pending()
        self.user.user_permissions.clear()

        response = self.client.get(self.queue_url)

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, "Test Subject", status_code=403)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(self.queue_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    @patch("outreach.views.EmailMessage.send")
    def test_viewing_queue_changes_nothing(self, mock_send):
        draft = self.pending()
        history_count = EmailDraftHistory.objects.count()
        version = draft.version

        self.client.get(self.queue_url)
        self.client.get(reverse("outreach_dashboard"))

        draft.refresh_from_db()
        self.bank.refresh_from_db()

        self.assertEqual(draft.workflow_status, "awaiting_approval")
        self.assertEqual(draft.version, version)
        self.assertIsNone(draft.approved_by)
        self.assertEqual(self.bank.contact_status, "not_yet_contacted")
        self.assertEqual(EmailDraftHistory.objects.count(), history_count)
        mock_send.assert_not_called()

    def test_dashboard_link_visible_only_to_approvers(self):
        self.pending()

        approver_page = self.client.get(reverse("outreach_dashboard"))
        self.assertContains(approver_page, self.queue_url)
        self.assertContains(approver_page, "Pending Approvals (1)")

        self.user.user_permissions.clear()
        other_page = self.client.get(reverse("outreach_dashboard"))
        self.assertNotContains(other_page, self.queue_url)

    def test_review_link_still_enforces_version_checks(self):
        draft = self.pending()

        response = self.client.post(
            reverse("approve_email_draft", args=[draft.draft_id]),
            {"version": draft.version + 1},
        )

        draft.refresh_from_db()
        self.assertEqual(draft.workflow_status, "awaiting_approval")
