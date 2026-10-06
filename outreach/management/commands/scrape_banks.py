"""
Collect publicly available Community Bank information
from confirmed Bendigo Bank public branch pages.

Usage:
    python manage.py scrape_banks --region Victoria --dry-run

Optional:
    python manage.py scrape_banks --region Victoria --limit 5 --dry-run

This collector only uses public organisation information:
    - bank name
    - state / region
    - public phone
    - branch website URL
    - source URL

It does not collect private or sensitive information.
"""

import re
import time

import requests
from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand, CommandError

from outreach.models import Bank


HEADERS = {
    "User-Agent": (
        "SafeRoadsForUsStudentProject/1.0 "
        "(public organisation data only)"
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


def extract_state(text):
    match = re.search(
        r"\b(VIC|NSW|QLD|SA|WA|TAS|ACT|NT)\b",
        text,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return ""


def scrape_branch_page(session, url):
    response = session.get(
        url,
        headers=HEADERS,
        timeout=15,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    for tag in soup(
        ["script", "style", "noscript"]
    ):
        tag.decompose()

    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    # Try to find the main branch name
    bank_name = ""

    heading = soup.find("h1")

    if heading:
        bank_name = clean_text(
            heading.get_text(
                " ",
                strip=True,
            )
        )

    # Fallback to page title
    if not bank_name and soup.title:
        title = clean_text(
            soup.title.get_text(
                " ",
                strip=True,
            )
        )

        if "|" in title:
            title = title.split("|", 1)[0].strip()

        bank_name = title

    if not bank_name:
        raise ValueError(
            "Could not determine bank name."
        )

    if "community bank" not in bank_name.lower():
        raise ValueError(
            "Page is not recognised as a Community Bank page."
        )

    public_phone = extract_phone(
        page_text
    )

    state = extract_state(
        page_text
    )

    return {
        "bank_name": bank_name,
        "state": state,
        "website_url": url,
        "public_email": "",
        "public_phone": public_phone,
        "source_url": url,
    }


def fetch_banks_for_region(
    region,
    limit=None,
):
    urls = PUBLIC_BRANCH_URLS.get(
        region,
        [],
    )

    if not urls:
        raise ValueError(
            f"No public branch URLs configured for '{region}'."
        )

    if limit:
        urls = urls[:limit]

    session = requests.Session()

    results = []

    for index, url in enumerate(
        urls,
        start=1,
    ):
        try:
            bank = scrape_branch_page(
                session,
                url,
            )

            results.append(bank)

        except requests.RequestException as exc:
            print(
                f"Fetch failed for {url}: {exc}"
            )

        except ValueError as exc:
            print(
                f"Skipped {url}: {exc}"
            )

        if index < len(urls):
            time.sleep(0.5)

    return results


class Command(BaseCommand):
    help = (
        "Collect public Community Bank information "
        "from confirmed Bendigo Bank branch pages."
    )

    def add_arguments(
        self,
        parser,
    ):
        parser.add_argument(
            "--region",
            type=str,
            required=True,
            help="Region/state to collect, e.g. Victoria.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Collect and validate without writing "
                "to the database."
            ),
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional number of branch pages to test.",
        )

    def handle(
        self,
        *args,
        **options,
    ):
        region = options["region"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        if region not in PUBLIC_BRANCH_URLS:
            raise CommandError(
                f"No configured public source list for '{region}'."
            )

        if limit is not None and limit < 1:
            raise CommandError(
                "--limit must be greater than 0."
            )

        self.stdout.write(
            f"Collecting public Community Bank data "
            f"for {region}..."
        )

        try:
            fetched_banks = fetch_banks_for_region(
                region,
                limit=limit,
            )

        except Exception as exc:
            raise CommandError(
                f"Collection failed: {exc}"
            )

        created_count = 0
        duplicate_count = 0
        skipped_count = 0

        for entry in fetched_banks:
            bank_name = clean_text(
                entry.get("bank_name")
            )

            if not bank_name:
                skipped_count += 1

                self.stdout.write(
                    self.style.ERROR(
                        "Skipped record with no bank name."
                    )
                )

                continue

            existing_bank = (
                Bank.objects
                .filter(
                    bank_name__iexact=bank_name
                )
                .first()
            )

            if existing_bank:
                duplicate_count += 1

                self.stdout.write(
                    self.style.WARNING(
                        f"'{bank_name}' already exists — skipped."
                    )
                )

                continue

            state = clean_text(
                entry.get("state")
            )

            if not state:
                state = "VIC"

            if dry_run:
                created_count += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Would create: "
                        f"{bank_name} | "
                        f"{state} | "
                        f"{entry.get('public_phone', '')}"
                    )
                )

                continue

            Bank.objects.create(
                bank_name=bank_name,
                region=region,
                state=state,
                website_url=clean_text(
                    entry.get("website_url")
                ),
                public_email=clean_text(
                    entry.get("public_email")
                ),
                public_phone=clean_text(
                    entry.get("public_phone")
                ),
                source_url=clean_text(
                    entry.get("source_url")
                ),
                contact_status="not_yet_contacted",
                record_source="Public Web - Bendigo Bank",
            )

            created_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Created '{bank_name}'"
                )
            )

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                f"New records: {created_count}"
            )
        )

        self.stdout.write(
            self.style.WARNING(
                f"Duplicates skipped: {duplicate_count}"
            )
        )

        self.stdout.write(
            f"Invalid/skipped records: {skipped_count}"
        )

        if dry_run:
            self.stdout.write(
                self.style.NOTICE(
                    "Dry run only — nothing was written "
                    "to the database."
                )
            )