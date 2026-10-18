"""
Collect publicly available Community Bank information
from confirmed Bendigo Bank public branch pages.

Usage:
    python manage.py scrape_banks --region Victoria --dry-run

Optional:
    python manage.py scrape_banks --region Victoria --limit 5 --dry-run

Collecting is done by the shared scraper job (duplicate checks, review, source
records), never written directly by this command:
    python manage.py scrape_banks --region Victoria --queue --admin-email admin@example.org
    python manage.py run_intake_worker --once

This collector only uses public organisation information:
    - bank name
    - state / region
    - public phone
    - branch website URL
    - source URL

It does not collect private or sensitive information.
"""

import re

from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand, CommandError



HEADERS = {
    "User-Agent": (
        "SafeRoadsForUsCollector/1.0 "
        "(public organisation information only; "
        "Safe Roads For Us outreach project)"
    )
}


PUBLIC_BRANCH_URLS = {
    "Victoria": [
        "https://www.bendigobank.com.au/branch/vic/community-bank-monbulk-district/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-bright/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-donald-district/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-seddon/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-mt-eliza/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-balwyn/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-heyfield-district/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-upwey-district/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-trafalgar-district/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-doreen-mernda/",
        "https://www.bendigobank.com.au/branch/vic/community-bank-ballan-district/",
    ]
}


def clean_text(value):
    if value is None:
        return ""

    return " ".join(str(value).split()).strip()


def extract_phone(text):
    patterns = [
        r"\(0\d\)\s*\d{4}\s*\d{4}",
        r"0\d\s*\d{4}\s*\d{4}",
        r"1[38]00\s*\d{3}\s*\d{3}",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return clean_text(match.group(0))

    return ""


STATE_CODES = ("VIC", "NSW", "QLD", "SA", "WA", "TAS", "ACT", "NT")


def extract_state(text, url=""):
    """
    A reliable state code, or "" when it cannot be established.

    The branch URL path (/branch/<state>/...) is the most reliable
    evidence. Otherwise only an UPPERCASE code that is the single distinct
    code on the page is accepted, so ordinary words ("act", "sa") are never
    mistaken for a state.
    """
    path_match = re.search(r"/branch/([a-z]{2,3})/", (url or "").lower())

    if path_match and path_match.group(1).upper() in STATE_CODES:
        return path_match.group(1).upper()

    found = {
        match.group(1)
        for match in re.finditer(
            r"\b(VIC|NSW|QLD|SA|WA|TAS|ACT|NT)\b",
            text or "",
        )
    }

    return found.pop() if len(found) == 1 else ""


class Command(BaseCommand):
    help = (
        "Preview or queue the public Community Bank collection. This command no "
        "longer writes banks directly: --dry-run previews approved pages, and "
        "--queue hands the work to the shared scraper job (duplicate checks, "
        "review and source records)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--region", type=str, required=True, help="Region/state to collect, e.g. Victoria.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Fetch and validate the approved pages without writing to the database.",
        )
        parser.add_argument("--limit", type=int, default=None, help="Optional number of branch pages to test.")
        parser.add_argument(
            "--queue", action="store_true",
            help="Queue the same background job as the Admin Scraper page (needs --admin-email).",
        )
        parser.add_argument("--admin-email", type=str, default="", help="Active Admin the run is recorded against.")

    def handle(self, *args, **options):
        from intake import legacy  # imported here: intake.sources imports this module

        region = options["region"]

        if region not in PUBLIC_BRANCH_URLS:
            raise CommandError(f"No configured public source list for '{region}'.")

        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be greater than 0.")

        if options["dry_run"] and options["queue"]:
            raise CommandError("Use either --dry-run or --queue, not both.")

        state = legacy.state_code(region)

        if options["dry_run"]:
            legacy.preview_source(self, "bendigo_community_banks", states=[state], limit=options["limit"])
        elif options["queue"]:
            legacy.queue_source(self, "bank", admin_email=options["admin_email"], states=[state])
        else:
            raise legacy.direct_write_disabled(
                "scrape_banks",
                "Use the Admin Scraper page (Data > Scraper), or run this command with --queue "
                "--admin-email <admin> and then start the worker (python manage.py run_intake_worker). "
                "Use --dry-run to preview.",
            )
