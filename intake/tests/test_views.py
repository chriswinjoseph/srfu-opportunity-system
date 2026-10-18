"""Admin-only pages: access control, the import workflow end to end, reviews and the scraper page."""

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from intake.worker import beat
from intake.models import DuplicateReview, IntakeRun, ProposedChange
from outreach.models import Bank

from .helpers import IntakeTestCase, con_row, default_workbook, make_workbook, org_row


def upload(data, name="client.xlsx"):
    return SimpleUploadedFile(name, data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class AccessTests(IntakeTestCase):
    GET_URLS = ("intake_home", "intake_import", "intake_reviews", "intake_changes", "intake_scraper")

    def setUp(self):
        super().setUp()
        self.run_obj = IntakeRun.objects.create(kind="import", status="previewed", created_by=self.admin, payload={"groups": []})
        self.review = DuplicateReview.objects.create(run=self.run_obj, kind="duplicate", submission={"name": "X"})
        self.change = ProposedChange.objects.create(
            content_type=self.bank_ct, object_id=self.bank("B", "VIC").pk, field="public_email", new_value="n@example.test",
        )

    def targets(self):
        gets = [reverse(n) for n in self.GET_URLS] + [
            reverse("intake_run", args=[self.run_obj.pk]),
            reverse("intake_run_status", args=[self.run_obj.pk]),
            reverse("intake_review", args=[self.review.pk]),
        ]
        posts = [
            reverse("intake_import"), reverse("intake_confirm", args=[self.run_obj.pk]),
            reverse("intake_review", args=[self.review.pk]),
            reverse("intake_change_decide", args=[self.change.pk]), reverse("intake_scraper"),
        ]

        return gets, posts

    def test_anonymous_users_are_sent_to_login(self):
        gets, posts = self.targets()

        for url in gets:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("login"), response["Location"])

        for url in posts:
            response = self.client.post(url, {"decision": "reject"})
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("login"), response["Location"])

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "pending")

    def test_staff_get_403_everywhere_and_change_nothing(self):
        self.client.force_login(self.staff)
        gets, posts = self.targets()

        for url in gets:
            self.assertEqual(self.client.get(url).status_code, 403, url)

        for url in posts:
            self.assertEqual(self.client.post(url, {"decision": "approve"}).status_code, 403, url)

        self.review.refresh_from_db(); self.change.refresh_from_db(); self.run_obj.refresh_from_db()
        self.assertEqual((self.review.status, self.change.status, self.run_obj.status), ("pending", "pending", "previewed"))
        self.assertEqual(IntakeRun.objects.count(), 1)

    def test_disabled_admin_cannot_use_the_pages(self):
        self.client.force_login(self.admin)
        type(self.admin).objects.filter(pk=self.admin.pk).update(is_active=False)

        gets, posts = self.targets()

        for url in gets:
            self.assertNotEqual(self.client.get(url).status_code, 200, url)

        for url in posts:
            self.assertNotEqual(self.client.post(url, {"decision": "reject"}).status_code, 200, url)

        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "pending")

    def test_admin_can_open_every_page(self):
        self.client.force_login(self.admin)
        gets, _posts = self.targets()

        for url in gets:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_import_and_scraper_links_are_only_shown_to_admins(self):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("outreach_dashboard")).content.decode()
        self.assertNotIn(reverse("intake_import"), page)
        self.assertNotIn(reverse("intake_scraper"), page)

        self.client.force_login(self.admin)
        page = self.client.get(reverse("outreach_dashboard")).content.decode()
        self.assertIn(reverse("intake_import"), page)
        self.assertIn(reverse("intake_scraper"), page)

    def test_the_old_scrape_endpoint_no_longer_scrapes_in_the_request(self):
        self.client.force_login(self.admin)

        with patch("intake.fetch.PublicFetcher.get", side_effect=AssertionError("fetched")), \
                patch("requests.Session.get", side_effect=AssertionError("fetched")):
            response = self.client.post(reverse("scrape_organisations"))

        self.assertRedirects(response, reverse("intake_scraper"), fetch_redirect_response=False)
        self.assertEqual(Bank.objects.filter(record_source="Public Web - Bendigo Bank").count(), 0)

        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(reverse("scrape_organisations")).status_code, 403)


class ImportPageTests(IntakeTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_invalid_uploads_show_clear_errors_and_save_nothing(self):
        for data, name, text in (
            (b"a,b", "x.csv", "Only Microsoft Excel"),
            (b"junk", "x.xlsx", "could not be opened"),
            (make_workbook([], [], sheets=("Organisations",)), "x.xlsx", "missing the sheet"),
        ):
            with self.subTest(name=name, text=text):
                response = self.client.post(reverse("intake_import"), {"workbook": upload(data, name)})

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, text)

        response = self.client.post(reverse("intake_import"), {})
        self.assertContains(response, "Choose an Excel")
        self.assertEqual(Bank.objects.count(), 0)

    def test_full_workflow_upload_preview_confirm_results(self):
        response = self.client.post(reverse("intake_import"), {"workbook": upload(default_workbook())})
        run = IntakeRun.objects.get()

        self.assertRedirects(response, reverse("intake_run", args=[run.pk]), fetch_redirect_response=False)
        preview = self.client.get(reverse("intake_run", args=[run.pk]))
        self.assertContains(preview, "Preview")
        self.assertContains(preview, "Confirm and import")
        self.assertContains(preview, "imported as Banks")
        self.assertEqual(Bank.objects.count(), 0)

        done = self.client.post(reverse("intake_confirm", args=[run.pk]), follow=True)

        self.assertContains(done, "Organisations created")
        self.assertContains(done, "Successful")
        self.assertEqual(Bank.objects.count(), 3)
        run.refresh_from_db()
        self.assertEqual(run.confirmed_by, self.admin)

        again = self.client.post(reverse("intake_confirm", args=[run.pk]), follow=True)
        self.assertContains(again, "already confirmed")
        self.assertEqual(Bank.objects.count(), 3)

    def test_previewing_the_same_file_again_warns_and_repeat_import_adds_nothing(self):
        for _ in range(2):
            self.client.post(reverse("intake_import"), {"workbook": upload(default_workbook())})
            run = IntakeRun.objects.order_by("-pk").first()
            page = self.client.get(reverse("intake_run", args=[run.pk]))
            self.client.post(reverse("intake_confirm", args=[run.pk]))

        self.assertContains(page, "already imported")
        self.assertEqual(Bank.objects.count(), 3)
        self.assertEqual(IntakeRun.objects.order_by("-pk").first().totals["created"], 0)

    def test_results_page_lists_problems_with_actions_and_filters(self):
        data = make_workbook(
            [org_row("O_1", "Good Community Bank", "VIC"), org_row("O_2", "Odd Bank", "Atlantis")],
            [con_row("C_1", "O_1")],
        )
        self.client.post(reverse("intake_import"), {"workbook": upload(data)})
        run = IntakeRun.objects.get()

        preview = self.client.get(reverse("intake_run", args=[run.pk]))
        self.assertContains(preview, "Rows that cannot be imported")
        self.assertContains(preview, "Atlantis".lower() if False else "state or territory")

        self.client.post(reverse("intake_confirm", args=[run.pk]))
        page = self.client.get(reverse("intake_run", args=[run.pk]), {"outcome": "failed"})

        self.assertContains(page, "Partially Successful")
        self.assertContains(page, "Enter a valid Australian state")
        self.assertNotContains(page, "Good Community Bank")

    def test_review_page_decision_flow(self):
        existing = self.bank("Alpha Community Bank Ltd", "VIC")
        self.client.post(reverse("intake_import"), {"workbook": upload(make_workbook(
            [org_row("O_1", "Alpha Community Bank", "VIC")], [con_row("C_1", "O_1", "alpha@example.test")]))})
        run = IntakeRun.objects.get()
        self.client.post(reverse("intake_confirm", args=[run.pk]))
        review = DuplicateReview.objects.get()

        listing = self.client.get(reverse("intake_reviews"))
        self.assertContains(listing, "Alpha Community Bank")

        page = self.client.get(reverse("intake_review", args=[review.pk]))
        self.assertContains(page, "Possible matching organisations")
        self.assertContains(page, "Alpha Community Bank Ltd")
        self.assertContains(page, "similar in the same state")

        response = self.client.post(reverse("intake_review", args=[review.pk]),
                                    {"decision": "use_existing", "target": f"bank:{existing.pk}"}, follow=True)
        self.assertContains(response, "Your decision was saved")
        review.refresh_from_db()
        self.assertEqual(review.status, "decided")

        again = self.client.post(reverse("intake_review", args=[review.pk]), {"decision": "reject"}, follow=True)
        self.assertContains(again, "already been decided")
        self.assertEqual(Bank.objects.count(), 1)

    def test_bad_review_input_is_reported_safely(self):
        run = IntakeRun.objects.create(kind="import", status="successful")
        review = DuplicateReview.objects.create(run=run, kind="duplicate", submission={"name": "X", "org_type": "bank"})

        response = self.client.post(reverse("intake_review", args=[review.pk]),
                                    {"decision": "use_existing", "target": "bank:abc"}, follow=True)

        self.assertContains(response, "Choose which existing organisation")
        response = self.client.post(reverse("intake_review", args=[review.pk]), {"decision": "nonsense"}, follow=True)
        self.assertContains(response, "not available")

    def test_change_page_approve_and_reject(self):
        bank = self.bank("Alpha Community Bank", "VIC", public_email="old@example.test")
        change = ProposedChange.objects.create(content_type=self.bank_ct, object_id=bank.pk, field="public_email",
                                               old_value="old@example.test", new_value="new@example.test", source_label="client")

        page = self.client.get(reverse("intake_changes"))
        self.assertContains(page, "old@example.test")
        self.assertContains(page, "new@example.test")

        self.client.post(reverse("intake_change_decide", args=[change.pk]), {"decision": "approve"})

        bank.refresh_from_db()
        self.assertEqual(bank.public_email, "new@example.test")
        response = self.client.post(reverse("intake_change_decide", args=[change.pk]), {"decision": "reject"}, follow=True)
        self.assertContains(response, "already been decided")
        self.assertEqual(self.client.post(reverse("intake_change_decide", args=[99999]), {"decision": "approve"}).status_code, 404)


class ScraperPageTests(IntakeTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_page_lists_sources_and_only_supported_options(self):
        page = self.client.get(reverse("intake_scraper"))

        self.assertContains(page, "Bendigo Bank Community Bank branch pages")
        self.assertContains(page, "Moonee Valley City Council")
        self.assertContains(page, "(no approved source)")           # branches
        self.assertContains(page, "(no source)")                    # other states
        self.assertContains(page, "Queue scrape")

    def test_queueing_creates_a_background_job_and_shows_progress_page(self):
        response = self.client.post(reverse("intake_scraper"), {"org_type": ["bank", "club"], "state": ["VIC"]})
        run = IntakeRun.objects.get()

        self.assertRedirects(response, reverse("intake_run", args=[run.pk]), fetch_redirect_response=False)
        self.assertEqual(run.status, "queued")
        page = self.client.get(reverse("intake_run", args=[run.pk]))
        # No worker has checked in, so the page must not look as if it is progressing.
        self.assertContains(page, "Queued - not started")
        self.assertContains(page, "background service that runs scrapes is not running")
        self.assertNotContains(page, 'id="run-worker-warning" hidden')    # warning is visible
        self.assertNotContains(page, "run_intake_worker")      # operator commands stay out of the user-facing page
        self.assertNotContains(page, "manage.py")
        self.assertContains(page, "system operator")
        status = self.client.get(reverse("intake_run_status", args=[run.pk])).json()
        self.assertEqual((status["status"], status["finished"], status["worker_alive"]), ("queued", False, False))

        beat("test-worker")
        page = self.client.get(reverse("intake_run", args=[run.pk]))
        self.assertContains(page, "Waiting for the background service to pick this up")
        self.assertContains(page, 'id="run-worker-warning" hidden')      # warning hidden
        self.assertTrue(self.client.get(reverse("intake_run_status", args=[run.pk])).json()["worker_alive"])

    def test_unsupported_selection_and_overlap_show_clear_messages(self):
        response = self.client.post(reverse("intake_scraper"), {"org_type": ["branch"], "state": ["NSW"]}, follow=True)
        self.assertContains(response, "No approved public source")

        self.client.post(reverse("intake_scraper"), {"org_type": ["bank"], "state": ["VIC"]})
        response = self.client.post(reverse("intake_scraper"), {"org_type": ["bank"], "state": ["VIC"]}, follow=True)
        self.assertContains(response, "already queued or running")
        self.assertEqual(IntakeRun.objects.count(), 1)

    def test_finished_scraper_run_shows_totals_and_coverage_notes(self):
        run = IntakeRun.objects.create(
            kind="scraper", status="partial", created_by=self.admin, progress_done=3, progress_total=4,
            totals={"processed": 5, "created": 2, "failed": 1, "review": 1},
            options={"coverage_notes": ["Branch: no approved public source is configured."]},
        )

        page = self.client.get(reverse("intake_run", args=[run.pk]))

        self.assertContains(page, "Coverage notes")
        self.assertContains(page, "Branch: no approved public source")
        self.assertContains(page, "3 of 4 pages processed")
        self.assertContains(page, "Partially Successful")
