"""
Import banks, contacts and outreach history from the cleaned SRFU Excel workbook.

This command no longer writes organisations directly. The older version used
its own duplicate and status rules; the import now runs through the same
pipeline as the Admin Data Import page (validation, duplicate detection,
review, provenance, evidence-based status).

    python manage.py import_bank_contacts path/to/workbook.xlsx --dry-run
    python manage.py import_bank_contacts path/to/workbook.xlsx --commit --admin-email admin@example.org
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Import banks, contacts and outreach history from the cleaned SRFU Excel workbook. Validates with the shared rules; --commit runs the same "
        "preview-and-confirm import as the Admin page (needs --admin-email)."
    )

    def add_arguments(self, parser):
        parser.add_argument("workbook_path", help="Path to the cleaned .xlsx workbook.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Validate and report without saving (the default).")
        mode.add_argument("--commit", action="store_true", help="Run the shared import and save the results.")
        parser.add_argument("--admin-email", default="", help="Active Admin the import is recorded against.")

    def handle(self, *args, **options):
        from intake import legacy

        legacy.run_workbook(
            self,
            options["workbook_path"],
            admin_email=options["admin_email"],
            apply=bool(options["commit"]),
        )
