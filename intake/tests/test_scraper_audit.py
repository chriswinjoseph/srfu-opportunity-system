"""Scraper audit regressions: result classification, counts, filters and validation (mocked pages only)."""

from intake.fetch import FetchResult
from intake.models import IntakeResult, IntakeRun
from intake.scraper import ScrapeError, run_job, start_scrape
from outreach.management.commands.scrape_banks import PUBLIC_BRANCH_URLS
from outreach.models import Bank, Club

from .helpers import IntakeTestCase, con_row, make_workbook, org_row
from .test_scraper import BANK_HTML, CLUB_URL, FakeFetcher, club_html, make_run

BANK_URLS = PUBLIC_BRANCH_URLS["Victoria"]
BANK_ONLY = ["bendigo_community_banks"]


class ReproScraperDefects(IntakeTestCase):
    def run_pages(self, pages, **options):
        run = make_run(self.admin, **options)

        return run_job(run, FakeFetcher(pages)), run

    def test_suburb_filter_is_not_applied_to_a_source_without_suburbs(self):
        # The page tells the Admin the suburb filter "was not applied" to banks.
        finished, _ = self.run_pages({BANK_URLS[0]: BANK_HTML}, adapters=BANK_ONLY, suburbs=["Niddrie"])

        self.assertEqual(Bank.objects.count(), 1)
        self.assertEqual(finished.totals["created"], 1)

    def test_unknown_organisation_types_are_rejected_not_widened_to_everything(self):
        with self.assertRaises(ScrapeError):
            start_scrape(self.admin, ["bank", "nonsense"], ["VIC"])

        with self.assertRaises(ScrapeError):
            start_scrape(self.admin, [], ["VIC"])

        self.assertEqual(IntakeRun.objects.count(), 0)

    def test_a_run_with_no_pages_is_not_reported_as_successful(self):
        run = make_run(self.admin, adapters=[])

        finished = run_job(run, FakeFetcher({}))

        self.assertEqual(finished.status, IntakeRun.STATUS_FAILED)
        self.assertIn("No pages", finished.error_message)


class ReproImportClassification(IntakeTestCase):
    def test_an_import_where_every_row_fails_is_failed_not_partial(self):
        from intake.importer import confirm_import, create_preview

        data = make_workbook([org_row("O_1", "Alpha Community Bank", "Atlantis")], [con_row("C_1", "O_1")])
        run, parsed = create_preview(self.admin, data, "x.xlsx")
        self.assertTrue(parsed.ok)

        confirm_import(run.pk, self.admin)

        run.refresh_from_db()
        self.assertEqual(run.status, IntakeRun.STATUS_FAILED)
        self.assertEqual(IntakeResult.objects.filter(run=run, outcome="failed").count(), 1)
