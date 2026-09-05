"""
Import Shane's starter dataset (Bank records) from a CSV export.

Usage:
    python manage.py import_seed path/to/banks.csv

Expected CSV columns (case-insensitive header match):
    bank_name       (required)
    region          (required)
    website_url     (optional)
    public_email    (optional)
    public_phone    (optional)
    status          (optional — see STATUS_MAP below)

If Shane's real export uses different column names, only STATUS_MAP and
COLUMN_MAP below need to change — the rest of the logic stays the same.

Implements:
  - AC1: new orgs with no prior outreach history default to Not Yet Contacted
  - AC7: rows flagged as previously contacted are imported as Contacted
  - FR-7: duplicate detection (matched on bank_name, case-insensitive) —
    duplicates are skipped and reported, not overwritten or duplicated
"""

import csv

from django.core.management.base import BaseCommand, CommandError

from outreach.models import Bank


# Maps expected CSV headers to Bank model field names.
# Adjust the left-hand keys if Shane's actual export uses different headers.
COLUMN_MAP = {
    "bank_name": "bank_name",
    "region": "region",
    "website_url": "website_url",
    "public_email": "public_email",
    "public_phone": "public_phone",
}

REQUIRED_COLUMNS = ["bank_name", "region"]

# Recognised values (case-insensitive) that mean "already contacted".
# Anything not matched here defaults to not_yet_contacted (AC1).
CONTACTED_VALUES = {
    "contacted", "yes", "true", "already contacted", "previously contacted",
}


class Command(BaseCommand):
    help = "Import Shane's starter dataset of banks from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path",
            type=str,
            help="Path to the CSV file to import.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate the file without writing to the database.",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        dry_run = options["dry_run"]

        try:
            f = open(csv_path, newline="", encoding="utf-8-sig")
        except FileNotFoundError:
            raise CommandError(f"File not found: {csv_path}")

        created_count = 0
        duplicate_count = 0
        error_count = 0
        errors = []

        with f:
            reader = csv.DictReader(f)

            reader.fieldnames = [
                (name or "").strip().lower().replace(" ", "_")
                for name in reader.fieldnames
            ]

            missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
            if missing:
                raise CommandError(
                    f"CSV is missing required column(s): {', '.join(missing)}. "
                    f"Found columns: {', '.join(reader.fieldnames)}"
                )

            for row_num, row in enumerate(reader, start=2):
                bank_name = (row.get("bank_name") or "").strip()
                region = (row.get("region") or "").strip()

                if not bank_name or not region:
                    error_count += 1
                    errors.append(
                        f"Row {row_num}: missing required field "
                        f"(bank_name or region) — skipped."
                    )
                    continue

                if Bank.objects.filter(bank_name__iexact=bank_name).exists():
                    duplicate_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Row {row_num}: '{bank_name}' already exists — skipped."
                        )
                    )
                    continue

                status_raw = (row.get("status") or "").strip().lower()
                contact_status = (
                    "contacted" if status_raw in CONTACTED_VALUES
                    else "not_yet_contacted"
                )

                if dry_run:
                    created_count += 1
                    self.stdout.write(
                        f"Row {row_num}: would create '{bank_name}' "
                        f"(status={contact_status})"
                    )
                    continue

                Bank.objects.create(
                    bank_name=bank_name,
                    region=region,
                    website_url=(row.get("website_url") or "").strip(),
                    public_email=(row.get("public_email") or "").strip(),
                    public_phone=(row.get("public_phone") or "").strip(),
                    contact_status=contact_status,
                )
                created_count += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Created: {created_count}"))
        self.stdout.write(self.style.WARNING(f"Duplicates skipped: {duplicate_count}"))
        if error_count:
            self.stdout.write(self.style.ERROR(f"Rows with errors: {error_count}"))
            for e in errors:
                self.stdout.write(self.style.ERROR(f"  {e}"))

        if dry_run:
            self.stdout.write(
                self.style.NOTICE("Dry run only — nothing was written to the database.")
            )