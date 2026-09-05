"""
Scrape public bank data by region and add new banks to the database.

Usage:
    python manage.py scrape_banks --region Victoria

THIS IS A PLACEHOLDER IMPLEMENTATION.
The fetch_banks_for_region() function below returns fake/mock data instead
of actually scraping a real website, because the target site(s) have not
yet been confirmed by Savio/Shane (open question on FR-8).

Once a real target site is confirmed, only fetch_banks_for_region() needs
to change — everything else (duplicate detection, re-run safety, status
defaulting, CLI interface) is already built and tested against this
mock version, so swapping in real scraping logic later is a small,
contained change, not a rewrite.

Design decisions baked in here, matching open questions raised with Savio:
  - Re-runnable: running this twice for the same region does NOT create
    duplicates or crash — it just reports what's already there.
  - Duplicate detection reuses the exact same logic as import_seed
    (case-insensitive match on bank_name) — same rule, one source of truth.
  - Failure handling: if fetching a given region fails, it's reported and
    skipped, not allowed to crash the whole run.
"""

from django.core.management.base import BaseCommand, CommandError

from outreach.models import Bank


def fetch_banks_for_region(region):
    """
    PLACEHOLDER — returns fake bank data instead of real scraped data.

    Replace this function's body with real scraping logic once a target
    website is confirmed. It should return a list of dicts shaped like:
        [{"bank_name": ..., "website_url": ..., "public_email": ...,
          "public_phone": ..., "source_url": ...}, ...]

    Raising an exception here is treated as a fetch failure by the
    calling code below, and is reported without crashing the whole run.
    """
    mock_data = {
        "Victoria": [
            {
                "bank_name": "Example Community Bank - Geelong",
                "website_url": "https://example.com/geelong",
                "public_email": "geelong@example.com",
                "public_phone": "0352000000",
                "source_url": "https://example.com/geelong",
            },
            {
                "bank_name": "Example Community Bank - Ballarat",
                "website_url": "https://example.com/ballarat",
                "public_email": "ballarat@example.com",
                "public_phone": "0353000000",
                "source_url": "https://example.com/ballarat",
            },
        ],
        "New South Wales": [
            {
                "bank_name": "Example Community Bank - Newcastle",
                "website_url": "https://example.com/newcastle",
                "public_email": "newcastle@example.com",
                "public_phone": "0249000000",
                "source_url": "https://example.com/newcastle",
            },
        ],
    }

    if region not in mock_data:
        raise ValueError(f"No mock data configured for region '{region}'.")

    return mock_data[region]


class Command(BaseCommand):
    help = "Scrape (currently: mock-fetch) public bank data for a region."

    def add_arguments(self, parser):
        parser.add_argument(
            "--region",
            type=str,
            required=True,
            help="Region to scrape banks for, e.g. 'Victoria'.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and validate without writing to the database.",
        )

    def handle(self, *args, **options):
        region = options["region"]
        dry_run = options["dry_run"]

        try:
            fetched_banks = fetch_banks_for_region(region)
        except Exception as e:
            raise CommandError(f"Fetch failed for region '{region}': {e}")

        created_count = 0
        duplicate_count = 0

        for entry in fetched_banks:
            bank_name = entry.get("bank_name", "").strip()

            if not bank_name:
                self.stdout.write(
                    self.style.ERROR("Skipped a record with no bank_name.")
                )
                continue

            # Same duplicate rule as import_seed — one source of truth.
            if Bank.objects.filter(bank_name__iexact=bank_name).exists():
                duplicate_count += 1
                self.stdout.write(
                    self.style.WARNING(f"'{bank_name}' already exists — skipped.")
                )
                continue

            if dry_run:
                created_count += 1
                self.stdout.write(f"Would create '{bank_name}'")
                continue

            Bank.objects.create(
                bank_name=bank_name,
                region=region,
                website_url=entry.get("website_url", ""),
                public_email=entry.get("public_email", ""),
                public_phone=entry.get("public_phone", ""),
                source_url=entry.get("source_url", ""),
                contact_status="not_yet_contacted",
            )
            created_count += 1
            self.stdout.write(self.style.SUCCESS(f"Created '{bank_name}'"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Created: {created_count}"))
        self.stdout.write(self.style.WARNING(f"Duplicates skipped: {duplicate_count}"))
        if dry_run:
            self.stdout.write(
                self.style.NOTICE("Dry run only — nothing was written to the database.")
            )