"""
Import public club information from CSV or Excel.

Examples:

    python manage.py import_clubs path/to/clubs.xlsx --dry-run

    python manage.py import_clubs path/to/clubs.csv --dry-run

Real import:

    python manage.py import_clubs path/to/clubs.xlsx

Supported columns:

    club_name           required
    club_type           optional
    suburb              optional
    state               optional
    postcode            optional
    region              optional
    website_url         optional
    public_email        optional
    public_phone        optional
    source_url          optional
    supported_by_bank   optional
    supported_by_branch optional

New clubs default to:
    contact_status = not_yet_contacted

Duplicate rule:
    club_name + suburb + state

The importer:
    - supports CSV and XLSX
    - validates required fields
    - validates email addresses
    - prevents duplicates
    - supports dry-run
    - records the data source
    - optionally links clubs to an existing bank/branch
"""

import csv
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from openpyxl import load_workbook

from outreach.models import Bank, Branch, Club


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def normalise_header(value):
    return (
        clean_text(value)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def validate_public_email(value):
    value = clean_text(value)

    if not value:
        return ""

    try:
        validate_email(value)
        return value
    except ValidationError:
        return None


def read_csv(file_path):
    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise CommandError(
                "CSV file does not contain column headers."
            )

        reader.fieldnames = [
            normalise_header(header)
            for header in reader.fieldnames
        ]

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            yield row_number, row


def read_excel(file_path):
    try:
        workbook = load_workbook(
            file_path,
            data_only=True,
            read_only=True,
        )
    except Exception as exc:
        raise CommandError(
            f"Could not open Excel file: {exc}"
        )

    sheet = workbook.active

    rows = sheet.iter_rows(
        values_only=True
    )

    try:
        headers = next(rows)
    except StopIteration:
        raise CommandError(
            "Excel file is empty."
        )

    headers = [
        normalise_header(header)
        for header in headers
    ]

    for row_number, values in enumerate(
        rows,
        start=2,
    ):
        row = dict(
            zip(headers, values)
        )

        yield row_number, row


def get_rows(file_path):
    suffix = (
        Path(file_path)
        .suffix
        .lower()
    )

    if suffix == ".csv":
        yield from read_csv(
            file_path
        )

    elif suffix in {
        ".xlsx",
        ".xlsm",
    }:
        yield from read_excel(
            file_path
        )

    else:
        raise CommandError(
            "Unsupported file type. "
            "Use CSV or XLSX."
        )


def find_supported_bank(bank_name):
    bank_name = clean_text(
        bank_name
    )

    if not bank_name:
        return None

    return (
        Bank.objects
        .filter(
            bank_name__iexact=bank_name
        )
        .first()
    )


def find_supported_branch(
    branch_name,
    bank,
):
    branch_name = clean_text(
        branch_name
    )

    if not branch_name:
        return None

    query = Branch.objects.filter(
        branch_name__iexact=branch_name
    )

    if bank:
        query = query.filter(
            bank=bank
        )

    return query.first()


class Command(BaseCommand):
    help = (
        "Import public club information "
        "from CSV or Excel."
    )

    def add_arguments(
        self,
        parser,
    ):
        parser.add_argument(
            "file_path",
            type=str,
            help=(
                "Path to CSV or XLSX "
                "club dataset."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Validate without writing "
                "to the database."
            ),
        )

    def handle(
        self,
        *args,
        **options,
    ):
        file_path = options[
            "file_path"
        ]

        dry_run = options[
            "dry_run"
        ]

        if not Path(
            file_path
        ).exists():
            raise CommandError(
                f"File not found: "
                f"{file_path}"
            )

        created_count = 0
        duplicate_count = 0
        error_count = 0
        bank_links = 0
        branch_links = 0

        errors = []

        for (
            row_number,
            row,
        ) in get_rows(
            file_path
        ):
            club_name = clean_text(
                row.get(
                    "club_name"
                )
            )

            club_type = clean_text(
                row.get(
                    "club_type"
                )
            )

            suburb = clean_text(
                row.get(
                    "suburb"
                )
            )

            state = clean_text(
                row.get(
                    "state"
                )
            )

            postcode = clean_text(
                row.get(
                    "postcode"
                )
            )

            region = clean_text(
                row.get(
                    "region"
                )
            )

            website_url = clean_text(
                row.get(
                    "website_url"
                )
            )

            public_phone = clean_text(
                row.get(
                    "public_phone"
                )
            )

            source_url = clean_text(
                row.get(
                    "source_url"
                )
            )

            email_raw = clean_text(
                row.get(
                    "public_email"
                )
            )

            public_email = (
                validate_public_email(
                    email_raw
                )
            )

            if not club_name:
                error_count += 1

                errors.append(
                    f"Row {row_number}: "
                    "club_name is required."
                )

                continue

            if public_email is None:
                error_count += 1

                errors.append(
                    f"Row {row_number}: "
                    f"invalid email "
                    f"'{email_raw}'."
                )

                continue

            duplicate_query = (
                Club.objects.filter(
                    club_name__iexact=club_name
                )
            )

            if suburb:
                duplicate_query = (
                    duplicate_query.filter(
                        suburb__iexact=suburb
                    )
                )

            if state:
                duplicate_query = (
                    duplicate_query.filter(
                        state__iexact=state
                    )
                )

            if (
                duplicate_query
                .exists()
            ):
                duplicate_count += 1

                self.stdout.write(
                    self.style.WARNING(
                        f"Row {row_number}: "
                        f"'{club_name}' "
                        "already exists — skipped."
                    )
                )

                continue

            bank_name = clean_text(
                row.get(
                    "supported_by_bank"
                )
            )

            branch_name = clean_text(
                row.get(
                    "supported_by_branch"
                )
            )

            supported_bank = (
                find_supported_bank(
                    bank_name
                )
            )

            supported_branch = (
                find_supported_branch(
                    branch_name,
                    supported_bank,
                )
            )

            if (
                bank_name
                and not supported_bank
            ):
                self.stdout.write(
                    self.style.WARNING(
                        f"Row {row_number}: "
                        f"bank '{bank_name}' "
                        "was not found. "
                        "Club will still be imported."
                    )
                )

            if (
                branch_name
                and not supported_branch
            ):
                self.stdout.write(
                    self.style.WARNING(
                        f"Row {row_number}: "
                        f"branch '{branch_name}' "
                        "was not found. "
                        "Club will still be imported."
                    )
                )

            if dry_run:
                created_count += 1

                if supported_bank:
                    bank_links += 1

                if supported_branch:
                    branch_links += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Row {row_number}: "
                        f"would create "
                        f"'{club_name}' "
                        f"| {suburb} "
                        f"| {state}"
                    )
                )

                continue

            club = Club.objects.create(
                club_name=club_name,
                club_type=club_type,
                suburb=suburb,
                state=state,
                postcode=postcode,
                region=region,
                website_url=website_url,
                public_email=public_email,
                public_phone=public_phone,
                supported_by_bank=(
                    supported_bank
                ),
                supported_by_branch=(
                    supported_branch
                ),
                contact_status=(
                    "not_yet_contacted"
                ),
                record_source=(
                    "Public Dataset Import"
                ),
            )

            created_count += 1

            if club.supported_by_bank:
                bank_links += 1

            if club.supported_by_branch:
                branch_links += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Created "
                    f"'{club.club_name}'"
                )
            )

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                f"Clubs created: "
                f"{created_count}"
            )
        )

        self.stdout.write(
            self.style.WARNING(
                f"Duplicates skipped: "
                f"{duplicate_count}"
            )
        )

        self.stdout.write(
            f"Linked to banks: "
            f"{bank_links}"
        )

        self.stdout.write(
            f"Linked to branches: "
            f"{branch_links}"
        )

        if error_count:
            self.stdout.write(
                self.style.ERROR(
                    f"Rows with errors: "
                    f"{error_count}"
                )
            )

            for error in errors:
                self.stdout.write(
                    self.style.ERROR(
                        f"  {error}"
                    )
                )

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.NOTICE(
                    "Dry run only — "
                    "nothing was written "
                    "to the database."
                )
            )