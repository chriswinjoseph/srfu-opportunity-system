"""Live scraper: sources, fetching, jobs and the shared duplicate/review rules (mocked pages only)."""

from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from intake.fetch import USER_AGENT, FetchResult, PublicFetcher
from intake.models import (
    DuplicateReview, FieldProvenance, IntakeResult, IntakeRun, OrganisationSource, ProposedChange,
)
from intake.scraper import (
    MAX_ATTEMPTS, ScrapeError, claim_next_job, recover_stale_jobs, run_job, start_scrape,
)
from intake.sources import ADAPTERS, plan_coverage
from outreach.management.commands.scrape_banks import PUBLIC_BRANCH_URLS, extract_state
from outreach.models import Bank, Club, EmailDraft, Opportunity

from .helpers import IntakeTestCase

BANK_URLS = PUBLIC_BRANCH_URLS["Victoria"]
BANK_HTML = "<html><body><h1>Community Bank Testville</h1><p>Call 03 9555 0100 today</p></body></html>"
CLUB_URL = "https://mvcc.vic.gov.au/live/my-neighbourhood/local-sports-clubs/"


def club_html(website=True, email="info@northside.example.test", name="Northside Netball Club"):
    link = '<a href="https://club.example.test/">%s</a>' % name if website else '<a href="/internal">%s</a>' % name

    return (
        "<html><body><h2>Netball Expand</h2>"
        f"<p>{link} Address: 1 Test St, Essendon VIC 3040 Email: {email} Phone: 03 9555 0200</p>"
        "</body></html>"
    )


class FakeFetcher:
    """A stand-in for the network: url -> html, or url -> a failure code."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        value = self.pages.get(url)

        if value is None:
            return FetchResult(False, url, 404, code="not_found")

        if isinstance(value, FetchResult):
            return value

        return FetchResult(True, url, 200, value)


class FakeResponse:
    def __init__(self, status=200, url="", body=b"<html></html>", encoding="utf-8"):
        self.status_code, self.url, self.encoding = status, url, encoding
        self._body = body
        self.text = body.decode("utf-8", "replace")

    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


class FakeSession:
    def __init__(self, responses=None, robots="User-agent: *\nAllow: /"):
        self.responses = responses or {}
        self.robots = robots
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))

        if url.endswith("/robots.txt"):
            return FakeResponse(200, url, self.robots.encode())

        return self.responses.get(url) or FakeResponse(200, url)


def make_run(user, adapters=("bendigo_community_banks", "mvcc_sports_clubs"), **options):
    return IntakeRun.objects.create(
        kind="scraper", status="running", created_by=user, source_key="scraper",
        options={"adapters": list(adapters), "done_pages": [], "unsupported": [], **options},
    )


class StateExtractionTests(IntakeTestCase):
    def test_state_comes_from_the_url_then_an_unambiguous_uppercase_code(self):
        self.assertEqual(extract_state("anything", "https://x.test/branch/nsw/community-bank-x/"), "NSW")
        self.assertEqual(extract_state("Our branch in VIC is open", ""), "VIC")

    def test_ordinary_words_and_ambiguity_are_not_a_state(self):
        # The old case-insensitive regex read "act" or "sa" as a state.
        self.assertEqual(extract_state("Please act on this and tell us sa what", ""), "")
        self.assertEqual(extract_state("Offices in VIC and NSW", ""), "")
        self.assertEqual(extract_state("", ""), "")


class FetcherTests(IntakeTestCase):
    def fetcher(self, session, **kw):
        return PublicFetcher(session, allowed_hosts=("www.bendigobank.com.au",), delay=0, **kw)

    def test_honest_user_agent_and_timeouts(self):
        url = BANK_URLS[0]
        session = FakeSession({url: FakeResponse(200, url, BANK_HTML.encode())})

        result = self.fetcher(session).get(url)

        self.assertTrue(result.ok)
        agents = {kw["headers"]["User-Agent"] for _u, kw in session.calls}
        self.assertEqual(agents, {USER_AGENT})
        self.assertIn("SafeRoadsForUs", USER_AGENT)
        self.assertNotIn("Mozilla", USER_AGENT)
        page_call = [kw for u, kw in session.calls if u == url][0]
        self.assertEqual(page_call["timeout"], (5, 15))

    def test_only_approved_https_hosts(self):
        session = FakeSession()
        fetcher = self.fetcher(session)

        for url in ("http://www.bendigobank.com.au/x", "https://evil.example.test/x", "ftp://www.bendigobank.com.au/"):
            self.assertEqual(fetcher.get(url).code, "blocked_host", url)

        self.assertEqual(session.calls, [])

    def test_redirect_to_another_host_is_refused(self):
        url = BANK_URLS[0]
        session = FakeSession({url: FakeResponse(200, "https://evil.example.test/landing")})

        self.assertEqual(self.fetcher(session).get(url).code, "blocked_host")

    def test_login_pages_are_not_collected(self):
        url = BANK_URLS[0]

        for response in (FakeResponse(401, url), FakeResponse(200, "https://www.bendigobank.com.au/login?next=x")):
            with self.subTest(status=response.status_code):
                result = self.fetcher(FakeSession({url: response})).get(url)
                self.assertFalse(result.ok)
                self.assertEqual(result.code, "login_required")
                self.assertIn("login", result.message)

    def test_forbidden_missing_and_server_errors_have_safe_messages(self):
        url = BANK_URLS[0]

        for status, code in ((403, "forbidden"), (404, "not_found"), (500, "http_error")):
            result = self.fetcher(FakeSession({url: FakeResponse(status, url)})).get(url)
            self.assertEqual(result.code, code)
            self.assertNotIn("Traceback", result.message)
            self.assertNotIn(str(status), result.message)

    def test_robots_rules_are_respected(self):
        url = BANK_URLS[0]
        session = FakeSession({url: FakeResponse(200, url)}, robots="User-agent: *\nDisallow: /branch/")

        result = self.fetcher(session).get(url)

        self.assertEqual(result.code, "robots")
        self.assertEqual([u for u, _k in session.calls if not u.endswith("robots.txt")], [])

    def test_oversized_pages_and_network_errors_are_bounded(self):
        url = BANK_URLS[0]
        big = FakeResponse(200, url, b"x" * 2_100_000)
        self.assertEqual(self.fetcher(FakeSession({url: big})).get(url).code, "too_large")

        class Boom(FakeSession):
            def get(self, url, **kw):
                if url.endswith("robots.txt"):
                    return super().get(url, **kw)

                raise ConnectionError("secret network detail")

        result = self.fetcher(Boom()).get(url)
        self.assertEqual(result.code, "unreachable")
        self.assertNotIn("secret", result.message)


class CoverageTests(IntakeTestCase):
    def test_only_declared_types_and_locations_are_supported(self):
        adapters, unsupported = plan_coverage(["bank", "branch", "club"], ["VIC", "NSW"])

        self.assertEqual({a.key for a in adapters}, {"bendigo_community_banks", "mvcc_sports_clubs"})
        text = " ".join(unsupported)
        self.assertIn("Branch: no approved public source", text)
        self.assertIn("NSW", text)

    def test_unsupported_selection_is_rejected_clearly(self):
        with self.assertRaises(ScrapeError) as ctx:
            start_scrape(self.admin, ["branch"], ["VIC"])

        self.assertIn("No approved public source", str(ctx.exception))
        self.assertEqual(IntakeRun.objects.count(), 0)


class QueueTests(IntakeTestCase):
    def test_only_admins_can_queue_and_nothing_is_fetched_in_the_request(self):
        with self.assertRaises(PermissionDenied):
            start_scrape(self.staff, ["bank"], ["VIC"])

        with patch("intake.scraper.PublicFetcher.get", side_effect=AssertionError("fetched in request")):
            run = start_scrape(self.admin, ["bank", "club"], ["VIC"])

        self.assertEqual(run.status, IntakeRun.STATUS_QUEUED)
        self.assertEqual(Bank.objects.count() + Club.objects.count(), 0)

    def test_an_overlapping_active_run_is_refused(self):
        start_scrape(self.admin, ["bank"], ["VIC"])

        with self.assertRaises(ScrapeError):
            start_scrape(self.admin, ["bank"], ["VIC"])

        self.assertEqual(IntakeRun.objects.count(), 1)

    def test_a_job_is_claimed_once(self):
        run = start_scrape(self.admin, ["bank"], ["VIC"])

        first = claim_next_job()
        second = claim_next_job()

        self.assertEqual(first.pk, run.pk)
        self.assertIsNone(second)
        first.refresh_from_db()
        self.assertEqual((first.status, first.attempts), ("running", 1))

    def test_a_stale_job_is_requeued_then_eventually_failed(self):
        run = start_scrape(self.admin, ["bank"], ["VIC"])
        claim_next_job()
        old = timezone.now() - timedelta(hours=1)
        IntakeRun.objects.filter(pk=run.pk).update(heartbeat_at=old)

        self.assertEqual(recover_stale_jobs(), [run.pk])
        run.refresh_from_db()
        self.assertEqual(run.status, IntakeRun.STATUS_QUEUED)

        IntakeRun.objects.filter(pk=run.pk).update(status="running", heartbeat_at=old, attempts=MAX_ATTEMPTS)
        recover_stale_jobs()
        run.refresh_from_db()
        self.assertEqual(run.status, IntakeRun.STATUS_FAILED)
        self.assertIn("interrupted", run.error_message)

    def test_a_fresh_job_is_not_recovered(self):
        start_scrape(self.admin, ["bank"], ["VIC"])
        claim_next_job()

        self.assertEqual(recover_stale_jobs(), [])


class ScraperJobTests(IntakeTestCase):
    def run_pages(self, pages, **options):
        run = make_run(self.admin, **options)
        fake = FakeFetcher(pages)

        return run_job(run, fake), fake

    def test_new_public_organisations_are_created_not_yet_contacted_with_sources(self):
        pages = {BANK_URLS[0]: BANK_HTML, CLUB_URL: club_html()}

        run, _ = self.run_pages(pages)

        bank = Bank.objects.get(bank_name="Community Bank Testville")
        club = Club.objects.get(club_name="Northside Netball Club")
        for org in (bank, club):
            self.assertEqual(org.contact_status, "not_yet_contacted")
            self.assertEqual(org.record_source, "Scraper")
        self.assertEqual(bank.state, "VIC")                     # from the URL, not guessed
        self.assertEqual(bank.source_url, BANK_URLS[0])         # source URL stored
        self.assertEqual(club.source_url, CLUB_URL)             # clubs now keep it too
        self.assertEqual((club.suburb, club.postcode, club.club_type), ("Essendon", "3040", "Netball"))
        self.assertEqual(club.public_email, "info@northside.example.test")
        source = OrganisationSource.objects.get(content_type=self.bank_ct, object_id=bank.pk)
        self.assertEqual(source.source_key, "bendigo_community_banks")
        self.assertTrue(source.requires_verification)
        self.assertIn("name", source.collected_fields)
        self.assertIsNotNone(source.first_collected_at)
        self.assertIsNotNone(source.last_checked_at)
        self.assertTrue(FieldProvenance.objects.filter(content_type=self.bank_ct, object_id=bank.pk, field="state").exists())
        # Public contact details never mean outreach happened.
        self.assertFalse(Opportunity.objects.exists())
        self.assertEqual(run.totals["created"], 2)

    def test_missing_optional_data_stays_empty(self):
        html = "<html><body><h1>Community Bank Quietville</h1></body></html>"

        self.run_pages({BANK_URLS[1]: html})

        bank = Bank.objects.get(bank_name="Community Bank Quietville")
        self.assertEqual((bank.public_phone, bank.public_email, bank.suburb, bank.postcode), ("", "", "", ""))

    def test_an_unreliable_result_is_held_as_incomplete(self):
        with patch("intake.sources.extract_state", return_value=""):
            run, _ = self.run_pages({BANK_URLS[0]: BANK_HTML})

        self.assertEqual(Bank.objects.count(), 0)
        result = IntakeResult.objects.get(outcome="incomplete")
        self.assertIn("state", result.field)
        self.assertEqual(result.row_ref, BANK_URLS[0])
        self.assertEqual(run.totals["incomplete"], 1)
        self.assertEqual(run.status, IntakeRun.STATUS_PARTIAL)

    def test_pages_that_are_not_what_they_claim_collect_nothing(self):
        run, _ = self.run_pages({BANK_URLS[0]: "<html><body><h1>Our Careers</h1></body></html>",
                                 BANK_URLS[1]: "<html><body></body></html>"}, adapters=["bendigo_community_banks"])

        self.assertEqual(Bank.objects.count(), 0)
        unrecognised = [r for r in IntakeResult.objects.filter(kind="page") if r.detail.get("code") == "unrecognised"]
        self.assertEqual(len(unrecognised), 2)

    def test_one_failing_page_does_not_stop_the_others(self):
        pages = {
            BANK_URLS[0]: FetchResult(False, BANK_URLS[0], 0, code="timeout"),
            BANK_URLS[1]: BANK_HTML,
            BANK_URLS[2]: FetchResult(False, BANK_URLS[2], 401, code="login_required"),
        }

        run, fake = self.run_pages(pages, adapters=["bendigo_community_banks"])

        self.assertEqual(Bank.objects.count(), 1)
        failures = IntakeResult.objects.filter(kind="page", outcome="failed")
        self.assertEqual(failures.count(), 2 + (len(BANK_URLS) - 3))      # the rest are 404s
        messages = " ".join(f.message for f in failures)
        self.assertIn("took too long", messages)
        self.assertIn("requires a login", messages)
        self.assertEqual(run.status, IntakeRun.STATUS_PARTIAL)

    def test_unexpected_errors_are_safe_and_do_not_stop_the_run(self):
        with patch("intake.sources.BendigoCommunityBanks.parse", side_effect=[RuntimeError("secret"), None]):
            def second(page, html):
                from intake.sources import ParseOutcome
                return ParseOutcome(problem="x")

            run, _ = self.run_pages({BANK_URLS[0]: BANK_HTML, BANK_URLS[1]: BANK_HTML}, adapters=["bendigo_community_banks"])

        self.assertNotIn("secret", " ".join(IntakeResult.objects.values_list("message", flat=True)))
        self.assertGreaterEqual(IntakeResult.objects.filter(kind="page").count(), 1)

    def test_an_existing_organisation_is_matched_never_duplicated_or_re_contacted(self):
        bank = self.bank("Community Bank Testville", "VIC", contact_status="contacted", public_phone="")
        opp = Opportunity.objects.create(content_type=self.bank_ct, object_id=bank.pk, status="interested")
        draft = EmailDraft.objects.create(opportunity=opp, recipient_email="a@example.test", subject="S", body="B",
                                          outreach_purpose="P", workflow_status="sent", requested_by=self.admin)

        run, _ = self.run_pages({BANK_URLS[0]: BANK_HTML}, adapters=["bendigo_community_banks"])

        self.assertEqual(Bank.objects.filter(bank_name="Community Bank Testville").count(), 1)
        bank.refresh_from_db(); opp.refresh_from_db(); draft.refresh_from_db()
        self.assertEqual(bank.contact_status, "contacted")
        self.assertEqual(opp.status, "interested")
        self.assertEqual(draft.workflow_status, "sent")
        self.assertEqual(bank.public_phone, "03 9555 0100")          # blank filled
        self.assertEqual(run.totals["exact_duplicates"], 1)

    def test_changed_information_is_proposed_not_applied(self):
        bank = self.bank("Community Bank Testville", "VIC", public_phone="03 1111 2222", website_url="https://old.example.test/")

        run, _ = self.run_pages({BANK_URLS[0]: BANK_HTML}, adapters=["bendigo_community_banks"])

        bank.refresh_from_db()
        self.assertEqual(bank.public_phone, "03 1111 2222")
        fields = {c.field: (c.old_value, c.new_value) for c in ProposedChange.objects.all()}
        self.assertEqual(fields["public_phone"], ("03 1111 2222", "03 9555 0100"))
        self.assertIn("website_url", fields)
        self.assertEqual(ProposedChange.objects.first().source_url, BANK_URLS[0])

    def test_a_removed_website_value_is_kept_and_marked_for_verification(self):
        self.run_pages({CLUB_URL: club_html(website=True)}, adapters=["mvcc_sports_clubs"])
        club = Club.objects.get()
        self.assertEqual(club.website_url, "https://club.example.test/")
        run = make_run(self.admin, adapters=["mvcc_sports_clubs"])

        run_job(run, FakeFetcher({CLUB_URL: club_html(website=False)}))

        club.refresh_from_db()
        self.assertEqual(club.website_url, "https://club.example.test/")      # preserved
        prov = FieldProvenance.objects.get(object_id=club.pk, field="website_url")
        self.assertIsNotNone(prov.not_found_since)
        self.assertTrue(OrganisationSource.objects.get(object_id=club.pk).requires_verification)

    def test_repeat_scrape_is_idempotent_and_updates_last_checked(self):
        pages = {BANK_URLS[0]: BANK_HTML, CLUB_URL: club_html()}
        self.run_pages(pages)
        source = OrganisationSource.objects.get(source_key="bendigo_community_banks")
        first_checked = source.last_checked_at
        counts = (Bank.objects.count(), Club.objects.count(), OrganisationSource.objects.count())

        run, _ = self.run_pages(pages)

        self.assertEqual((Bank.objects.count(), Club.objects.count(), OrganisationSource.objects.count()), counts)
        self.assertEqual(run.totals["created"], 0)
        self.assertEqual(run.totals["exact_duplicates"], 2)
        source.refresh_from_db()
        self.assertGreaterEqual(source.last_checked_at, first_checked)
        self.assertEqual(ProposedChange.objects.count(), 0)

    def test_scraped_records_follow_the_shared_duplicate_review_rules(self):
        # A manually created organisation with a similar name: held, never merged.
        self.club("Northside Netball", "VIC", suburb="Essendon")

        run, _ = self.run_pages({CLUB_URL: club_html()}, adapters=["mvcc_sports_clubs"])

        self.assertEqual(Club.objects.count(), 1)
        self.assertEqual(DuplicateReview.objects.filter(kind="duplicate").count(), 1)
        self.assertEqual(run.totals["review"], 1)

    def test_archived_existing_organisations_are_not_recreated_or_restored(self):
        archived = self.bank("Community Bank Testville", "VIC", is_archived=True)

        self.run_pages({BANK_URLS[0]: BANK_HTML}, adapters=["bendigo_community_banks"])

        archived.refresh_from_db()
        self.assertTrue(archived.is_archived)
        self.assertEqual(Bank.objects.filter(bank_name="Community Bank Testville").count(), 1)

    def test_suburb_filter_limits_clubs_and_is_reported(self):
        run, _ = self.run_pages({CLUB_URL: club_html()}, adapters=["mvcc_sports_clubs"], suburbs=["Niddrie"])

        self.assertEqual(Club.objects.count(), 0)
        self.assertIn("outside the selected suburb filter", " ".join(run.options["coverage_notes"]))

    def test_a_resumed_job_does_not_reprocess_finished_pages(self):
        run = make_run(self.admin, adapters=["bendigo_community_banks"], done_pages=list(BANK_URLS))
        fake = FakeFetcher({BANK_URLS[0]: BANK_HTML})

        run_job(run, fake)

        self.assertEqual(fake.requested, [])
        self.assertEqual(Bank.objects.count(), 0)

    def test_a_run_stops_at_its_time_limit_and_says_so(self):
        run = make_run(self.admin, adapters=["bendigo_community_banks"])
        fake = FakeFetcher({url: BANK_HTML for url in BANK_URLS})

        finished = run_job(run, fake, max_runtime=-1)

        self.assertIn("time limit", finished.error_message)
        self.assertEqual(finished.status, IntakeRun.STATUS_FAILED if not finished.totals["created"] else IntakeRun.STATUS_PARTIAL)

    def test_scraping_never_changes_existing_outreach_status(self):
        for status in ("not_yet_contacted", "contacted"):
            with self.subTest(status=status):
                Bank.objects.all().delete()
                bank = self.bank("Community Bank Testville", "VIC", contact_status=status)

                self.run_pages({BANK_URLS[0]: BANK_HTML}, adapters=["bendigo_community_banks"])

                bank.refresh_from_db()
                self.assertEqual(bank.contact_status, status)

    def test_adapters_are_explicit_and_declare_their_coverage(self):
        self.assertEqual(set(ADAPTERS), {"bendigo_community_banks", "mvcc_sports_clubs"})
        for adapter in ADAPTERS.values():
            self.assertEqual(adapter.states, ("VIC",))
            self.assertTrue(adapter.allowed_hosts)
