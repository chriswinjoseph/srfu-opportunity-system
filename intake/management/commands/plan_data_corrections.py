"""
Read-only preview of corrections to previously imported data.

    python manage.py plan_data_corrections path/to/workbook.xlsx [--json plan.json]

Nothing is changed. Item matching uses source evidence, and records with
later outreach, responses or edits are excluded and listed.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from intake.corrections import build_plan


class Command(BaseCommand):
    help = "Preview (read-only) corrections for previously imported data."

    def add_arguments(self, parser):
        parser.add_argument("workbook_path")
        parser.add_argument("--json", dest="json_path", help="Also write the plan as JSON.")

    def handle(self, *args, **options):
        path = Path(options["workbook_path"])

        if not path.exists():
            raise CommandError(f"Workbook not found: {path}")

        try:
            plan = build_plan(path.read_bytes(), path.name)
        except ValueError as error:
            raise CommandError(str(error))

        self.stdout.write(plan.to_text())

        if options["json_path"]:
            Path(options["json_path"]).write_text(json.dumps(plan.to_dict(), indent=2, default=str), encoding="utf-8")
            self.stdout.write(f"\nPlan written to {options['json_path']}")
