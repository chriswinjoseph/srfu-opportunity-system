"""Imported organisations are saved and visible to Staff; only Admins run imports and scrapes; held records are flagged."""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from intake.importer import confirm_import, create_preview
from intake.models import DuplicateReview, IntakeRun
from intake.scraper import start_scrape
from outreach.models import Bank

from .helpers import IntakeTestCase
from .test_import_simple import row, simple_workbook


def names(response):
    return [r["name"] for r in response.json()["results"]]


class ImportedOrganisationsAreVisibleTests(IntakeTestCase):
    def setUp(self):
        super().setUp()
        data = simple_workbook([
            row("S_1", "Visible Alpha Community Bank", "VIC", "Pat Example", "pat@example.test"),
            row("S_2", "Held Bravo Community Bank", "NSW", "", "", "Contacted"),
        ])
        run, _ = create_preview(self.admin, data, "v.xlsx")
        confirm_import(run.pk, self.admin)

    def test_saved_organisations_appear_for_admin_and_staff_on_the_dashboard_list(self):
        for user in (self.admin, self.staff):
            self.client.force_login(user)
            response = self.client.get(reverse("organisation_list_api"))

            self.assertEqual(response.status_code, 200)
            self.assertIn("Visible Alpha Community Bank", names(response), user.role)
            self.assertNotIn("Held Bravo Community Bank", names(response), "held records are not saved as organisations")

    def test_saved_organisation_detail_page_opens_for_staff(self):
        bank = Bank.objects.get(bank_name="Visible Alpha Community Bank")
        self.client.force_login(self.staff)

        response = self.client.get(reverse("organisation_detail", args=[ContentType.objects.get_for_model(Bank).pk, bank.pk]))

        self.assertContains(response, "Visible Alpha Community Bank")

    def test_saved_organisations_survive_a_fresh_session(self):
        self.client.logout()
        self.client.force_login(self.staff)

        self.assertEqual(Bank.objects.filter(bank_name="Visible Alpha Community Bank").count(), 1)
        self.assertIn("Visible Alpha Community Bank", names(self.client.get(reverse("organisation_list_api"))))

    def test_importing_the_same_file_again_creates_no_duplicates(self):
        data = simple_workbook([row("S_1", "Visible Alpha Community Bank", "VIC", "Pat Example", "pat@example.test")])
        run, _ = create_preview(self.admin, data, "again.xlsx")
        confirm_import(run.pk, self.admin)

        self.assertEqual(Bank.objects.filter(bank_name="Visible Alpha Community Bank").count(), 1)

    def test_a_similar_record_is_still_held_not_duplicated(self):
        data = simple_workbook([row("S_9", "Visible Alpha Community Bank Ltd Branch", "VIC")])
        run, _ = create_preview(self.admin, data, "similar.xlsx")
        confirm_import(run.pk, self.admin)

        self.assertEqual(Bank.objects.filter(bank_name__startswith="Visible Alpha").count(), 1)
        self.assertTrue(DuplicateReview.objects.filter(kind=DuplicateReview.KIND_DUPLICATE, status="pending").exists())


class StaffCannotImportOrScrapeTests(IntakeTestCase):
    def test_views_refuse_staff_for_every_import_and_scraper_action(self):
        self.client.force_login(self.staff)
        data = simple_workbook([row()])
        run, _ = create_preview(self.admin, data, "s.xlsx")

        for method, url, payload in (
            ("get", reverse("intake_import"), None),
            ("post", reverse("intake_import"), {"workbook": SimpleUploadedFile("s.xlsx", data)}),
            ("post", reverse("intake_confirm", args=[run.pk]), {}),
            ("get", reverse("intake_run", args=[run.pk]), None),
            ("get", reverse("intake_scraper"), None),
            ("post", reverse("intake_scraper"), {"org_type": ["bank"], "state": ["VIC"]}),
            ("get", reverse("intake_reviews"), None),
            ("get", reverse("intake_home"), None),
        ):
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url, payload) if payload is not None else getattr(self.client, method)(url)

                self.assertEqual(response.status_code, 403)

        run.refresh_from_db()
        self.assertEqual(run.status, IntakeRun.STATUS_PREVIEWED, "Staff cannot confirm an import")
        self.assertEqual(Bank.objects.count(), 0)
        self.assertEqual(IntakeRun.objects.filter(kind=IntakeRun.KIND_SCRAPER).count(), 0)

    def test_the_services_refuse_staff_even_without_the_views(self):
        data = simple_workbook([row()])
        run, _ = create_preview(self.admin, data, "s.xlsx")

        with self.assertRaises(PermissionDenied):
            create_preview(self.staff, data, "s.xlsx")

        with self.assertRaises(PermissionDenied):
            confirm_import(run.pk, self.staff)

        with self.assertRaises(PermissionDenied):
            start_scrape(self.staff, ["bank"], ["VIC"], [])

        self.assertEqual(Bank.objects.count(), 0)

    def test_the_dashboard_offers_staff_no_import_or_scraper_links(self):
        self.client.force_login(self.staff)

        html = self.client.get(reverse("outreach_dashboard")).content.decode()

        self.assertNotIn(reverse("intake_import"), html)
        self.assertNotIn(reverse("intake_scraper"), html)


class ReviewNavigationAndNoticeTests(IntakeTestCase):
    def hold_one(self):
        data = simple_workbook([row("S_2", "Held Bravo Community Bank", "NSW", "", "", "Contacted")])
        run, _ = create_preview(self.admin, data, "h.xlsx")
        confirm_import(run.pk, self.admin)

        return run

    def test_the_duplicates_tab_is_gone_from_the_data_navigation(self):
        self.client.force_login(self.admin)

        for name in ("intake_import", "intake_scraper", "intake_changes"):
            html = self.client.get(reverse(name)).content.decode()
            sidebar = html.split("</aside>")[0]

            self.assertNotIn("Duplicate Review", sidebar, name)
            self.assertNotIn(reverse("intake_reviews"), sidebar, name)

    def test_review_pages_and_records_are_intact_and_reachable_from_the_results(self):
        run = self.hold_one()
        self.client.force_login(self.admin)
        review = DuplicateReview.objects.get()

        results = self.client.get(reverse("intake_run", args=[run.pk]))

        self.assertContains(results, "Awaiting review")
        self.assertContains(results, reverse("intake_review", args=[review.pk]))
        self.assertContains(results, reverse("intake_reviews"))
        self.assertEqual(self.client.get(reverse("intake_reviews")).status_code, 200)
        self.assertEqual(self.client.get(reverse("intake_review", args=[review.pk])).status_code, 200)

    def test_admin_pages_and_dashboard_flag_records_awaiting_review_but_staff_do_not_see_it(self):
        self.hold_one()
        self.client.force_login(self.admin)

        for url in (reverse("outreach_dashboard"), reverse("intake_import"), reverse("intake_scraper")):
            self.assertContains(self.client.get(url), "awaiting review", msg_prefix=url)
            self.assertContains(self.client.get(url), reverse("intake_reviews"), msg_prefix=url)

        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(reverse("outreach_dashboard")), "pending-review-notice")

    def test_no_notice_when_nothing_is_waiting(self):
        self.client.force_login(self.admin)

        self.assertNotContains(self.client.get(reverse("outreach_dashboard")), "pending-review-notice")
        self.assertNotContains(self.client.get(reverse("intake_import")), "pending-review-notice")
