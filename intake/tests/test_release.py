"""Release hardening: legacy entry points, worker operation, atomic claims and unsupported types."""

import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from intake.fetch import PublicFetcher
from intake.importer import ImportBusy, confirm_import, create_preview
from intake.models import IntakeResult, IntakeRun
from intake.scraper import claim_next_job, fail_job, recover_stale_jobs, run_job, start_scrape
from intake.worker import ALIVE_SECONDS, beat, worker_state
from outreach.models import Bank, Club, Contact

from .helpers import ORG_HEADER, IntakeTestCase, con_row, default_workbook, make_workbook, org_row
from .test_scraper import BANK_HTML, BANK_URLS, FakeFetcher, FakeSession, make_run


def no_network(*args, **kwargs):
    raise AssertionError("The network must not be used.")


class LegacyScraperCommandTests(IntakeTestCase):
    def run_command(self, name, *args, **kwargs):
        out = StringIO()
        call_command(name, *args, stdout=out, **kwargs)

        return out.getvalue()

    def test_commands_that_used_to_write_directly_now_refuse_and_write_nothing(self):
        with patch("requests.Session.get", side_effect=no_network), patch("requests.get", side_effect=no_network):
            for name, args, kwargs in (
                ("scrape_banks", (), {"region": "Victoria"}),
                ("scrape_clubs", (), {}),
                ("run_scraper", (), {}),
                ("run_scraper", (), {"url": "https://example.test/"}),
            ):
                with self.subTest(name=name):
                    with self.assertRaises(CommandError) as caught:
                        self.run_command(name, *args, **kwargs)

                    self.assertIn("no longer writes organisations directly", str(caught.exception))

        self.assertEqual((Bank.objects.count(), Club.objects.count(), IntakeRun.objects.count()), (0, 0, 0))

    def test_retired_demo_scraper_function_fails_loudly(self):
        from outreach.scraper import scrape_public_banks

        with self.assertRaises(RuntimeError):
            scrape_public_banks()

        self.assertEqual(Bank.objects.count(), 0)

    def test_scrape_dry_run_previews_approved_pages_and_writes_nothing(self):
        fake = FakeFetcher({BANK_URLS[0]: BANK_HTML})

        with patch("intake.legacy.PublicFetcher", return_value=fake):
            output = self.run_command("scrape_banks", region="Victoria", dry_run=True, limit=1)

        self.assertIn("Would collect: Community Bank Testville", output)
        self.assertIn("Nothing was written", output)
        self.assertEqual(fake.requested, [BANK_URLS[0]])
        self.assertEqual((Bank.objects.count(), IntakeRun.objects.count()), (0, 0))

    def test_scrape_dry_run_uses_the_shared_fetcher_so_robots_rules_apply(self):
        session = FakeSession(robots="User-agent: *\nDisallow: /")

        def fetcher(**kwargs):
            return PublicFetcher(session=session, delay=0, **kwargs)

        with patch("intake.legacy.PublicFetcher", side_effect=fetcher):
            output = self.run_command("scrape_banks", region="Victoria", dry_run=True, limit=1)

        self.assertIn("robots rules do not allow", output)
        self.assertEqual([url for url, _ in session.calls], ["https://www.bendigobank.com.au/robots.txt"])

    def test_queue_hands_work_to_the_shared_job_and_needs_an_active_admin(self):
        for email in ("", "nobody@intake.test", self.staff.email):
            with self.subTest(email=email):
                with self.assertRaises(CommandError):
                    self.run_command("scrape_clubs", queue=True, admin_email=email)

        self.assertEqual(IntakeRun.objects.count(), 0)

        output = self.run_command("scrape_clubs", queue=True, admin_email=self.admin.email)
        run = IntakeRun.objects.get()

        self.assertEqual((run.status, run.created_by), ("queued", self.admin))
        self.assertEqual(run.options["adapters"], ["mvcc_sports_clubs"])
        self.assertIn("run_intake_worker", output)
        self.assertEqual(Club.objects.count(), 0)                      # nothing is collected by the command itself

        with self.assertRaises(CommandError):                          # no overlapping run for the same source
            self.run_command("scrape_clubs", queue=True, admin_email=self.admin.email)

    def test_dry_run_and_queue_cannot_be_combined(self):
        with self.assertRaises(CommandError):
            self.run_command("scrape_banks", region="Victoria", dry_run=True, queue=True, admin_email=self.admin.email)

    def test_disabled_admin_cannot_be_used_to_queue(self):
        self.admin.is_active = False
        self.admin.save()

        with self.assertRaises(CommandError):
            self.run_command("scrape_banks", region="Victoria", queue=True, admin_email=self.admin.email)


class LegacyImportCommandTests(IntakeTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "client.xlsx"
        self.path.write_bytes(default_workbook())

    def run_command(self, name, *args, **kwargs):
        out = StringIO()
        call_command(name, *args, stdout=out, **kwargs)

        return out.getvalue()

    def test_dry_run_validates_with_the_shared_rules_and_writes_nothing(self):
        for name in ("import_bank_contacts", "import_seed"):
            with self.subTest(name=name):
                output = self.run_command(name, str(self.path), dry_run=True)

                self.assertIn("Valid workbook: 3 organisation(s), 5 contact(s)", output)
                self.assertIn("Nothing was written", output)

        self.assertEqual((Bank.objects.count(), Contact.objects.count(), IntakeRun.objects.count()), (0, 0, 0))

    def test_default_is_validation_only_never_a_silent_write(self):
        self.run_command("import_seed", str(self.path))

        self.assertEqual(Bank.objects.count(), 0)

    def test_commit_runs_the_shared_import_and_repeat_creates_nothing(self):
        with self.assertRaises(CommandError):
            self.run_command("import_bank_contacts", str(self.path), commit=True)

        self.assertEqual(Bank.objects.count(), 0)

        output = self.run_command("import_bank_contacts", str(self.path), commit=True, admin_email=self.admin.email)

        self.assertIn("Import run", output)
        self.assertEqual(Bank.objects.count(), 3)
        self.assertEqual(
            sorted(Bank.objects.values_list("contact_status", flat=True)),
            ["contacted", "contacted", "not_yet_contacted"],           # never a third status
        )
        first_run = IntakeRun.objects.get()
        self.assertEqual(first_run.created_by, self.admin)
        self.assertEqual(first_run.filename, "client.xlsx")

        self.run_command("import_seed", str(self.path), commit=True, admin_email=self.admin.email)

        self.assertEqual((Bank.objects.count(), Contact.objects.count()), (3, 5))

    def test_commit_by_staff_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_command("import_seed", str(self.path), commit=True, admin_email=self.staff.email)

        self.assertEqual(Bank.objects.count(), 0)

    def test_invalid_files_are_refused_clearly(self):
        bad = Path(self.tmp.name) / "bad.csv"
        bad.write_text("a,b")

        with self.assertRaises(CommandError):
            self.run_command("import_seed", str(bad), dry_run=True)

        with self.assertRaises(CommandError):
            self.run_command("import_bank_contacts", str(Path(self.tmp.name) / "missing.xlsx"), dry_run=True)

    def test_club_import_is_disabled_but_can_still_count_rows(self):
        csv_path = Path(self.tmp.name) / "clubs.csv"
        csv_path.write_text("club_name,suburb,state\nA FC,Essendon,VIC\nB FC,Flemington,VIC\n")

        with self.assertRaises(CommandError) as caught:
            self.run_command("import_clubs", str(csv_path))

        self.assertIn("no longer writes organisations directly", str(caught.exception))
        self.assertIn("2 row(s) found", self.run_command("import_clubs", str(csv_path), dry_run=True))
        self.assertEqual(Club.objects.count(), 0)


class WorkerOperationTests(IntakeTestCase):
    def test_worker_state_reflects_recent_heartbeats(self):
        self.assertEqual(worker_state(), {"alive": False, "last_seen": None})

        now = timezone.now()
        beat("w1", now=now - timedelta(seconds=ALIVE_SECONDS + 30))
        self.assertFalse(worker_state(now)["alive"])

        beat("w1", now=now - timedelta(seconds=10))
        self.assertTrue(worker_state(now)["alive"])

    def test_a_running_job_with_a_fresh_heartbeat_counts_as_a_live_worker(self):
        run = make_run(self.admin)
        IntakeRun.objects.filter(pk=run.pk).update(heartbeat_at=timezone.now())

        self.assertTrue(worker_state()["alive"])

    def test_intake_status_flags_jobs_waiting_without_a_worker(self):
        out = StringIO()
        call_command("intake_status", stdout=out)
        self.assertIn("NOT running", out.getvalue())

        run = start_scrape(self.admin, ["bank"], ["VIC"])
        call_command("intake_status", stdout=StringIO())                   # fresh job: not yet a problem

        IntakeRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(minutes=30))

        with self.assertRaises(CommandError) as caught:
            call_command("intake_status", stdout=StringIO())

        self.assertIn(f"Job {run.pk}", str(caught.exception))

        beat("w1")
        out = StringIO()
        call_command("intake_status", stdout=out)
        self.assertIn("Worker: running", out.getvalue())

    def test_intake_status_flags_a_running_job_that_stopped_reporting(self):
        run = make_run(self.admin)
        IntakeRun.objects.filter(pk=run.pk).update(heartbeat_at=timezone.now() - timedelta(hours=1))
        beat("w1")

        with self.assertRaises(CommandError):
            call_command("intake_status", stdout=StringIO())

    def test_worker_survives_a_job_that_crashes_and_records_a_safe_failure(self):
        first = start_scrape(self.admin, ["bank"], ["VIC"])
        out = StringIO()

        with patch("intake.management.commands.run_intake_worker.run_job", side_effect=RuntimeError("secret detail")):
            call_command("run_intake_worker", once=True, stdout=out)

        first.refresh_from_db()
        self.assertEqual(first.status, "failed")
        self.assertNotIn("secret detail", first.error_message)
        self.assertNotIn("secret detail", out.getvalue())
        self.assertIn("worker continues", out.getvalue())
        self.assertTrue(worker_state()["alive"])                           # the worker announced itself

    def test_worker_runs_each_queued_job_once_and_then_exits(self):
        run = start_scrape(self.admin, ["bank"], ["VIC"])
        fake = FakeFetcher({url: BANK_HTML for url in BANK_URLS})

        with patch("intake.scraper.PublicFetcher", return_value=fake):
            call_command("run_intake_worker", once=True, stdout=StringIO())
            call_command("run_intake_worker", once=True, stdout=StringIO())

        run.refresh_from_db()
        self.assertIn(run.status, ("successful", "partial"))
        self.assertEqual(run.attempts, 1)
        self.assertEqual(sorted(fake.requested), sorted(BANK_URLS))        # every page fetched exactly once

    def test_a_job_can_only_be_claimed_by_one_worker(self):
        start_scrape(self.admin, ["bank"], ["VIC"])

        first = claim_next_job()
        second = claim_next_job()

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(first.attempts, 1)

    def test_retries_are_bounded_and_recovery_ignores_live_jobs(self):
        run = start_scrape(self.admin, ["bank"], ["VIC"])
        now = timezone.now()

        for attempt in range(1, 4):
            claimed = claim_next_job(now)
            self.assertEqual(claimed.attempts, attempt)
            self.assertEqual(recover_stale_jobs(300, now + timedelta(seconds=10)), [])   # still beating
            self.assertEqual(recover_stale_jobs(300, now + timedelta(hours=1)), [run.pk])
            run.refresh_from_db()
            now += timedelta(hours=2)

        self.assertEqual(run.status, "failed")
        self.assertIn("interrupted too many times", run.error_message)
        self.assertIsNone(claim_next_job())

    def test_fail_job_only_touches_a_running_job(self):
        run = start_scrape(self.admin, ["bank"], ["VIC"])

        self.assertEqual(fail_job(run), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")

    def test_a_worker_that_lost_its_lease_stops_instead_of_double_processing(self):
        start_scrape(self.admin, ["bank"], ["VIC"])
        run = claim_next_job()
        IntakeRun.objects.filter(pk=run.pk).update(lease_token="another-worker")
        fake = FakeFetcher({url: BANK_HTML for url in BANK_URLS})

        run_job(run, fetcher=fake)

        self.assertEqual(fake.requested, [])
        self.assertEqual(Bank.objects.count(), 0)
        self.assertEqual(IntakeRun.objects.get(pk=run.pk).status, "running")   # left to its new owner


class BotChallengeTests(IntakeTestCase):
    STUB = (
        '<html><head><META NAME="robots" CONTENT="noindex,nofollow"><script '
        'src="/_Incapsula_Resource?SWJIYLWA=abc"></script><body></body></html>'
    )

    def test_an_automated_access_check_is_reported_and_not_bypassed(self):
        from intake.sources import ADAPTERS
        from .test_scraper import CLUB_URL, FakeResponse

        session = FakeSession({CLUB_URL: FakeResponse(200, CLUB_URL, self.STUB.encode())})
        fetcher = PublicFetcher(session=session, allowed_hosts=ADAPTERS["mvcc_sports_clubs"].allowed_hosts, delay=0)

        fetched = fetcher.get(CLUB_URL)

        self.assertFalse(fetched.ok)
        self.assertEqual(fetched.code, "bot_challenge")
        self.assertIn("automated-access check", fetched.message)
        self.assertEqual(len(session.calls), 2)                           # robots.txt + the page, no retries or workarounds

    def test_a_blocked_source_is_a_failed_page_not_an_empty_success(self):
        from .test_scraper import CLUB_URL, FakeResponse

        run = make_run(self.admin, adapters=("mvcc_sports_clubs",))
        session = FakeSession({CLUB_URL: FakeResponse(200, CLUB_URL, self.STUB.encode())})
        finished = run_job(run, fetcher=PublicFetcher(session=session, allowed_hosts=["mvcc.vic.gov.au"], delay=0))
        problem = IntakeResult.objects.get(run=finished)

        self.assertEqual((finished.status, problem.outcome, problem.detail["code"]), ("failed", "failed", "bot_challenge"))
        self.assertIn("automated-access check", problem.message)
        self.assertEqual(Club.objects.count(), 0)


class ImportClaimTests(IntakeTestCase):
    def preview(self):
        run, _parsed = create_preview(self.admin, default_workbook(), "client.xlsx")

        return run

    def test_a_second_confirmation_changes_nothing(self):
        run = self.preview()
        confirm_import(run.pk, self.admin)
        banks = Bank.objects.count()

        with self.assertRaises(ImportBusy):
            confirm_import(run.pk, self.admin)

        self.assertEqual(Bank.objects.count(), banks)

    def test_a_running_import_blocks_another_but_a_dead_one_does_not(self):
        first, second = self.preview(), self.preview()
        IntakeRun.objects.filter(pk=first.pk).update(status="running", heartbeat_at=timezone.now())

        with self.assertRaises(ImportBusy) as caught:
            confirm_import(second.pk, self.admin)

        self.assertIn("Another import is running", str(caught.exception))
        self.assertEqual(Bank.objects.count(), 0)

        IntakeRun.objects.filter(pk=first.pk).update(heartbeat_at=timezone.now() - timedelta(hours=1))
        confirm_import(second.pk, self.admin)

        first.refresh_from_db()
        self.assertEqual(first.status, "failed")
        self.assertIn("interrupted", first.error_message)
        self.assertEqual(Bank.objects.count(), 3)


class UnsupportedTypeTests(IntakeTestCase):
    def test_an_unsupported_organisation_type_is_held_for_review_not_imported(self):
        header = ORG_HEADER + ["organisation_type"]
        data = make_workbook(
            [
                org_row("O_1", "Alpha Community Bank", organisation_type="Bank"),
                org_row("O_2", "Charity Thing", organisation_type="Charity"),
            ],
            [con_row("C_1", "O_1", "alpha@example.test")],
            org_header=header,
        )
        run, _parsed = create_preview(self.admin, data, "typed.xlsx")
        finished = confirm_import(run.pk, self.admin)

        held = IntakeResult.objects.get(run=finished, source_id="O_2")

        self.assertEqual(held.outcome, "review")
        self.assertIn("held for review", held.message)
        self.assertIn("import the file again", held.action_required)
        self.assertEqual(list(Bank.objects.values_list("bank_name", flat=True)), ["Alpha Community Bank"])
        self.assertEqual(finished.status, "partial")
        self.assertEqual(finished.totals["review"], 1)
        self.assertEqual(finished.totals["failed"], 0)


class LegacyStateInRegionTests(IntakeTestCase):
    """Banks imported before State was populated kept the state code in Region."""

    def test_a_state_code_in_region_counts_as_the_state_for_exact_matching(self):
        from intake.matching import Submission, find_matches

        legacy = self.bank("Alpha Community Bank", state="", region="VIC")
        sub = Submission(org_type="bank", name="alpha community bank", state="VIC")

        match = find_matches(sub)

        self.assertEqual(match.kind, "exact")
        self.assertEqual(match.candidates[0]["id"], legacy.pk)

    def test_a_region_that_is_not_a_state_is_not_treated_as_one(self):
        from intake.matching import Submission, find_matches

        self.bank("Alpha Community Bank", state="", region="Metropolitan Melbourne")

        match = find_matches(Submission(org_type="bank", name="Alpha Community Bank", state="VIC"))

        self.assertNotEqual(match.kind, "exact")                         # held for review instead

    def test_importing_over_legacy_banks_matches_them_without_duplicates(self):
        legacy = self.bank("Alpha Community Bank", state="", region="VIC")
        run, _parsed = create_preview(self.admin, default_workbook(), "client.xlsx")
        finished = confirm_import(run.pk, self.admin)

        self.assertEqual(Bank.objects.filter(bank_name="Alpha Community Bank").count(), 1)
        self.assertEqual(finished.totals["created"], 2)                  # Bravo and Charlie only
        self.assertEqual(finished.totals["exact_duplicates"], 1)
        legacy.refresh_from_db()
        self.assertEqual((legacy.state, legacy.region), ("VIC", "VIC"))   # blank filled, nothing replaced


class OptionalOrganisationColumnTests(IntakeTestCase):
    """Future imports of branches and clubs can supply their own details."""

    def typed(self, orgs, contacts=()):
        header = ORG_HEADER + [
            "organisation_type", "parent_bank_name", "parent_bank_state", "suburb", "postcode",
            "website_url", "public_phone", "public_email", "club_type",
        ]

        return make_workbook(orgs, list(contacts), org_header=header)

    def run_file(self, data):
        run, _parsed = create_preview(self.admin, data, "typed.xlsx")

        return confirm_import(run.pk, self.admin)

    def test_a_branch_with_a_known_parent_bank_is_created_under_it(self):
        parent = self.bank("Alpha Community Bank", state="VIC")
        data = self.typed([org_row(
            "B_1", "Alpha Eltham Branch", "VIC", overall="Not Yet Contacted",
            organisation_type="Branch", parent_bank_name="Alpha Community Bank", suburb="Eltham",
            postcode="3095", public_phone="03 9555 0100",
        )])

        finished = self.run_file(data)

        from outreach.models import Branch

        branch = Branch.objects.get()
        self.assertEqual((branch.bank, branch.suburb, branch.postcode, branch.contact_status), (parent, "Eltham", "3095", "not_yet_contacted"))
        self.assertEqual(finished.totals["created"], 1)

    def test_a_branch_without_a_known_parent_is_reported_incomplete_not_created(self):
        from outreach.models import Branch

        data = self.typed([org_row("B_1", "Orphan Branch", "VIC", organisation_type="Branch")])

        finished = self.run_file(data)

        self.assertEqual(Branch.objects.count(), 0)
        self.assertEqual(finished.totals["incomplete"], 1)

    def test_a_club_keeps_its_own_details_and_never_invents_missing_ones(self):
        data = self.typed([org_row(
            "K_1", "Northside Netball Club", "VIC", overall="Not Yet Contacted",
            organisation_type="Club", suburb="Essendon", postcode="3040", club_type="Netball",
        )])

        self.run_file(data)

        club = Club.objects.get()
        self.assertEqual((club.suburb, club.postcode, club.club_type), ("Essendon", "3040", "Netball"))
        self.assertEqual((club.public_phone, club.website_url, club.contact_status), ("", "", "not_yet_contacted"))
