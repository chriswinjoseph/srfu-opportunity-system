"""Scraper completion statuses, summary counts, recovery, worker loop and page states (mocked pages only)."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from intake.fetch import FetchResult
from intake.models import DuplicateReview, IntakeResult, IntakeRun, ProposedChange, WorkerHeartbeat
from intake.scraper import claim_next_job, recover_stale_jobs, run_job, start_scrape
from intake.worker import beat
from outreach.management.commands.scrape_banks import PUBLIC_BRANCH_URLS
from outreach.models import Bank

from .helpers import IntakeTestCase
from .test_scraper import BANK_HTML as GOOD, CLUB_URL, FakeFetcher, club_html, make_run

BANK_URLS = PUBLIC_BRANCH_URLS["Victoria"]
BANK_ONLY = ["bendigo_community_banks"]


def fail(code):
    return FetchResult(False, "", 0, code=code)


class CompletionStatusTests(IntakeTestCase):
    """Successful / Partially Successful / Failed for every combination of results."""

    def finish(self, pages, **options):
        run = make_run(self.admin, adapters=BANK_ONLY, **options)

        return run_job(run, FakeFetcher(pages))

    def every(self, value):
        return {url: value for url in BANK_URLS}

    def test_all_pages_succeed_is_successful(self):
        towns = ["Alder", "Birchgrove", "Cobalt", "Drummond", "Emerald", "Fitzroy", "Glenorchy", "Hawthorn",
                 "Ivanhoe", "Jindivick", "Kyneton", "Lancefield"]
        pages = {url: f"<html><body><h1>Community Bank {towns[i]}</h1></body></html>" for i, url in enumerate(BANK_URLS)}

        run = self.finish(pages)

        self.assertEqual(run.status, IntakeRun.STATUS_SUCCESSFUL)
        self.assertEqual(run.totals["pages_failed"], 0)
        self.assertEqual(run.totals["created"], len(BANK_URLS))

    def test_every_page_failing_is_failed_and_creates_nothing(self):
        run = self.finish(self.every(fail("timeout")))

        self.assertEqual(run.status, IntakeRun.STATUS_FAILED)
        self.assertEqual(run.totals["pages_failed"], len(BANK_URLS))
        self.assertEqual(run.totals["processed"], 0)
        self.assertEqual(Bank.objects.count(), 0)

    def test_a_blocked_source_is_failed_and_says_it_is_not_bypassed(self):
        run = self.finish(self.every(fail("bot_challenge")))

        self.assertEqual(run.status, IntakeRun.STATUS_FAILED)
        result = IntakeResult.objects.filter(run=run).first()
        self.assertEqual(result.detail["code"], "bot_challenge")
        self.assertIn("not bypassed", result.action_required)
        self.assertIn("automated-access check", result.message)

    def test_some_pages_succeeding_and_some_failing_is_partial_and_keeps_the_good_work(self):
        run = self.finish({BANK_URLS[0]: GOOD, BANK_URLS[1]: fail("unreachable")})

        self.assertEqual(run.status, IntakeRun.STATUS_PARTIAL)
        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(run.totals["pages_failed"], len(BANK_URLS) - 1)

    def test_only_incomplete_results_are_partial_not_failed(self):
        with patch("intake.sources.extract_state", return_value=""):
            run = self.finish({BANK_URLS[0]: GOOD}, done_pages=list(BANK_URLS[1:]))

        self.assertEqual((run.totals["incomplete"], run.totals["created"], run.totals["failed"]), (1, 0, 0))
        self.assertEqual(run.status, IntakeRun.STATUS_PARTIAL)
        self.assertEqual(Bank.objects.count(), 0)

    def test_only_review_required_results_are_partial_not_failed(self):
        self.bank("Community Bank Testvile", "VIC")

        run = self.finish({BANK_URLS[0]: GOOD}, done_pages=list(BANK_URLS[1:]))

        self.assertEqual((run.totals["review"], run.totals["created"]), (1, 0))
        self.assertEqual(run.status, IntakeRun.STATUS_PARTIAL)
        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(DuplicateReview.objects.count(), 1)

    def test_zero_results_with_working_pages_is_successful_but_flagged_as_nothing_found(self):
        self.client.force_login(self.admin)
        run = make_run(self.admin, adapters=["mvcc_sports_clubs"], suburbs=["Niddrie"])
        run = run_job(run, FakeFetcher({CLUB_URL: club_html()}))

        page = self.client.get(reverse("intake_run", args=[run.pk]))

        self.assertEqual(run.status, IntakeRun.STATUS_SUCCESSFUL)
        self.assertEqual(run.totals["processed"], 0)
        self.assertContains(page, "no organisations were found to process")

    def test_a_source_that_loads_but_lists_nothing_is_reported_differently_from_a_blocked_one(self):
        run = make_run(self.admin, adapters=["mvcc_sports_clubs"])
        run = run_job(run, FakeFetcher({CLUB_URL: "<html><body><p>No clubs</p></body></html>"}))

        result = IntakeResult.objects.get(run=run)
        self.assertEqual(run.status, IntakeRun.STATUS_FAILED)
        self.assertEqual(result.detail["code"], "no_records")
        self.assertIn("listed no clubs", result.message)
        self.assertIn("reachable", result.action_required)
        self.assertNotIn("not bypassed", result.action_required)


class SummaryAndErrorDetailTests(IntakeTestCase):
    def test_counts_separate_pages_from_organisations_and_are_internally_consistent(self):
        self.bank("Community Bank Existing", "VIC")
        pages = {
            BANK_URLS[0]: GOOD,
            BANK_URLS[1]: "<html><body><h1>Community Bank Existing</h1></body></html>",
            BANK_URLS[2]: fail("timeout"),
        }
        run = make_run(self.admin, adapters=BANK_ONLY, done_pages=list(BANK_URLS[3:]))

        t = run_job(run, FakeFetcher(pages)).totals

        self.assertEqual(t["pages_processed"], len(BANK_URLS))
        self.assertEqual(t["pages_failed"], 1)
        self.assertEqual(t["processed"], 2)
        self.assertEqual((t["created"], t["exact_duplicates"], t["unchanged"] + t["updated"]), (1, 1, 1))
        self.assertEqual(t["records_failed"], 0)
        self.assertEqual(
            t["processed"],
            t["created"] + t["updated"] + t["unchanged"] + t["review"] + t["incomplete"] + t["records_failed"],
        )

    def test_each_failed_page_names_the_source_url_reason_and_action(self):
        run = make_run(self.admin, adapters=BANK_ONLY, done_pages=list(BANK_URLS[1:]))

        run_job(run, FakeFetcher({BANK_URLS[0]: FetchResult(False, "", 401, code="login_required")}))

        result = IntakeResult.objects.get(run=run)
        self.assertEqual(result.row_ref, BANK_URLS[0])
        self.assertEqual(result.field, "source page")
        self.assertIn("requires a login", result.message)
        self.assertIn("permitted source", result.action_required)

    def test_an_incomplete_result_names_url_organisation_field_and_action(self):
        run = make_run(self.admin, adapters=BANK_ONLY, done_pages=list(BANK_URLS[1:]))

        with patch("intake.sources.extract_state", return_value=""):
            run_job(run, FakeFetcher({BANK_URLS[0]: GOOD}))

        result = IntakeResult.objects.get(run=run)
        self.assertEqual(
            (result.outcome, result.row_ref, result.name, result.field),
            ("incomplete", BANK_URLS[0], "Community Bank Testville", "state"),
        )
        self.assertIn("No organisation was created", result.action_required)

    def test_the_run_page_shows_pages_and_organisations_separately(self):
        self.client.force_login(self.admin)
        run = run_job(make_run(self.admin, adapters=BANK_ONLY), FakeFetcher({BANK_URLS[0]: GOOD}))

        page = self.client.get(reverse("intake_run", args=[run.pk])).content.decode()

        for label in ("Pages processed", "Pages failed", "Organisations processed", "New organisations created",
                      "Existing organisations unchanged", "Exact duplicates matched", "Incomplete results"):
            self.assertIn(label, page)


class RecoveryAndRepeatTests(IntakeTestCase):
    def test_a_crash_mid_run_resumes_without_duplicates_or_refetching_finished_pages(self):
        class Crash(BaseException):
            pass

        class Crashing(FakeFetcher):
            def get(self, url):
                if url == BANK_URLS[1]:
                    raise Crash()

                return super().get(url)

        start_scrape(self.admin, ["bank"], ["VIC"])
        claimed = claim_next_job()

        with self.assertRaises(Crash):
            run_job(claimed, Crashing({BANK_URLS[0]: GOOD}))

        self.assertEqual(Bank.objects.count(), 1)
        IntakeRun.objects.filter(pk=claimed.pk).update(heartbeat_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(recover_stale_jobs(), [claimed.pk])
        resumed = claim_next_job()
        self.assertEqual((resumed.pk, resumed.attempts), (claimed.pk, 2))
        healthy = FakeFetcher(
            {BANK_URLS[0]: GOOD, BANK_URLS[1]: "<html><body><h1>Community Bank Other</h1></body></html>"}
        )

        run_job(resumed, healthy)

        self.assertNotIn(BANK_URLS[0], healthy.requested, "a finished page is not fetched again")
        self.assertEqual(Bank.objects.count(), 2)
        resumed.refresh_from_db()
        self.assertEqual(resumed.status, IntakeRun.STATUS_PARTIAL)

    def test_a_second_run_over_the_same_pages_creates_nothing_and_overwrites_nothing(self):
        bank = self.bank("Community Bank Testville", "VIC", public_phone="03 1111 2222")
        pages = {BANK_URLS[0]: GOOD}
        done = list(BANK_URLS[1:])
        run_job(make_run(self.admin, adapters=BANK_ONLY, done_pages=done), FakeFetcher(pages))
        proposals = ProposedChange.objects.count()

        run_job(make_run(self.admin, adapters=BANK_ONLY, done_pages=done), FakeFetcher(pages))

        bank.refresh_from_db()
        self.assertEqual(bank.public_phone, "03 1111 2222")
        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(proposals, 1)
        self.assertEqual(ProposedChange.objects.count(), proposals, "the same proposal is not queued twice")


class WorkerCommandTests(IntakeTestCase):
    def call(self, *args):
        out = StringIO()
        call_command("run_intake_worker", *args, stdout=out)

        return out.getvalue()

    def test_once_processes_a_queued_job_and_checks_in(self):
        run = start_scrape(self.admin, ["bank"], ["VIC"])

        def fake_run(job):
            return run_job(job, FakeFetcher({BANK_URLS[0]: GOOD}))

        with patch("intake.management.commands.run_intake_worker.run_job", side_effect=fake_run):
            output = self.call("--once")

        run.refresh_from_db()
        self.assertIn("finished", output)
        self.assertNotIn(run.status, (IntakeRun.STATUS_QUEUED, IntakeRun.STATUS_RUNNING))
        self.assertEqual(WorkerHeartbeat.objects.count(), 1)

    def test_only_one_of_two_workers_gets_a_job(self):
        start_scrape(self.admin, ["bank"], ["VIC"])

        self.assertIsNotNone(claim_next_job())
        self.assertIsNone(claim_next_job())

    def test_repeated_loop_errors_are_retried_a_bounded_number_of_times_then_reported(self):
        with patch("intake.management.commands.run_intake_worker.claim_next_job", side_effect=RuntimeError("db down")), \
                patch("intake.management.commands.run_intake_worker.time.sleep") as sleep:
            with self.assertRaises(CommandError) as ctx:
                self.call("--max-errors", "3", "--poll-seconds", "1")

        self.assertIn("stopped after 3 errors in a row", str(ctx.exception))
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4], "growing pause, none after the last error")

    def test_a_single_transient_error_does_not_stop_the_worker(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1

            if calls["n"] == 1:
                raise RuntimeError("blip")

            return None

        with patch("intake.management.commands.run_intake_worker.claim_next_job", side_effect=flaky), \
                patch("intake.management.commands.run_intake_worker.time.sleep"):
            output = self.call("--once")

        self.assertIn("Worker error 1 of 5", output)
        self.assertEqual(calls["n"], 2)

    def test_a_job_failure_is_recorded_on_the_job_and_the_worker_carries_on(self):
        run = start_scrape(self.admin, ["bank"], ["VIC"])

        with patch("intake.management.commands.run_intake_worker.run_job", side_effect=RuntimeError("boom")):
            output = self.call("--once")

        run.refresh_from_db()
        self.assertEqual(run.status, IntakeRun.STATUS_FAILED)
        self.assertIn("worker continues", output)
        self.assertNotIn("boom", run.error_message)


class ScraperPageAndPermissionTests(IntakeTestCase):
    def test_coverage_limits_and_the_blocked_source_are_shown_before_queueing(self):
        self.client.force_login(self.admin)

        page = self.client.get(reverse("intake_scraper")).content.decode()

        self.assertIn("23 October 2026", page)
        self.assertIn("automated-access check", page)
        self.assertIn("not bypassed", page)
        self.assertIn("No approved public source is configured, so none can be collected", page)
        self.assertIn("not national coverage", page)
        self.assertIn("VIC only", page)
        self.assertRegex(page, r'value="club"\s*>')  # Clubs are listed but not pre-selected
        self.assertNotRegex(page, r'value="club"\s+checked')
        self.assertRegex(page, r'value="bank"\s+checked')

    def test_the_page_says_when_the_service_is_stopped_and_a_queued_job_is_not_progressing(self):
        self.client.force_login(self.admin)
        run = start_scrape(self.admin, ["bank"], ["VIC"])

        scraper = self.client.get(reverse("intake_scraper")).content.decode()
        detail = self.client.get(reverse("intake_run", args=[run.pk])).content.decode()
        status = self.client.get(reverse("intake_run_status", args=[run.pk])).json()

        self.assertIn("is not running", scraper)
        self.assertIn("not started (service stopped)", scraper)
        self.assertIn("Queued - not started", detail)
        self.assertNotIn("Successful", detail)
        self.assertEqual((status["status"], status["worker_alive"]), ("queued", False))

    def test_a_running_job_with_a_stopped_service_is_not_presented_as_healthy(self):
        self.client.force_login(self.admin)
        run = make_run(self.admin, adapters=BANK_ONLY)
        IntakeRun.objects.filter(pk=run.pk).update(heartbeat_at=timezone.now() - timedelta(minutes=3))

        detail = self.client.get(reverse("intake_run", args=[run.pk])).content.decode()

        self.assertIn("Running - service stopped", detail)
        self.assertIn("has stopped making progress", detail)
        self.assertNotIn('id="run-worker-warning" hidden', detail)

    def test_the_service_is_shown_as_running_when_a_worker_has_checked_in(self):
        self.client.force_login(self.admin)
        run = start_scrape(self.admin, ["bank"], ["VIC"])
        beat("test-worker")

        detail = self.client.get(reverse("intake_run", args=[run.pk])).content.decode()

        self.assertIn("Waiting for the background service to pick this up", detail)

    def test_server_side_validation_refuses_unsupported_selections_from_a_crafted_post(self):
        self.client.force_login(self.admin)

        for data in (
            {"org_type": ["branch"], "state": ["VIC"]},
            {"org_type": ["bank", "nonsense"], "state": ["VIC"]},
            {"org_type": [], "state": ["VIC"]},
            {"org_type": ["bank"], "state": ["NSW"]},
            {"org_type": ["bank"], "state": ["XX"]},
        ):
            with self.subTest(data=data):
                response = self.client.post(reverse("intake_scraper"), data, follow=True)

                self.assertEqual(IntakeRun.objects.count(), 0)
                self.assertContains(response, "em-banner-error")

    def test_staff_cannot_queue_view_or_poll_scraper_jobs(self):
        run = start_scrape(self.admin, ["bank"], ["VIC"])
        self.client.force_login(self.staff)

        self.assertEqual(
            self.client.post(reverse("intake_scraper"), {"org_type": ["bank"], "state": ["VIC"]}).status_code, 403
        )
        self.assertEqual(self.client.get(reverse("intake_scraper")).status_code, 403)
        self.assertEqual(self.client.get(reverse("intake_run", args=[run.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("intake_run_status", args=[run.pk])).status_code, 403)
        self.assertEqual(IntakeRun.objects.count(), 1)
