"""
Apply a previewed plan to a DISPOSABLE database copy only.

    python manage.py apply_data_corrections plan.json --rollback-file rollback.json

The command refuses to run against the project's own database file
(db.sqlite3). Point DJANGO_SETTINGS_MODULE at a settings module that uses a
copy of the database to rehearse the corrections and the rollback.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from intake.corrections import apply_plan, revert_plan


def _is_project_database():
    name = settings.DATABASES["default"].get("NAME")

    return Path(str(name)).resolve() == (Path(settings.BASE_DIR) / "db.sqlite3").resolve()


class Command(BaseCommand):
    help = "Apply (or --revert) data corrections on a disposable database copy only."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Plan JSON (or the rollback file with --revert).")
        parser.add_argument("--rollback-file", default="data_corrections_rollback.json")
        parser.add_argument("--revert", action="store_true")

    def handle(self, *args, **options):
        if _is_project_database():
            raise CommandError(
                "Refusing to change the project's own database. Use a disposable copy "
                "with its own settings module."
            )

        data = json.loads(Path(options["path"]).read_text(encoding="utf-8"))

        if options["revert"]:
            revert_plan(data["changes"])
            self.stdout.write(f"Reverted {len(data['changes'])} change(s).")
            return

        applied, skipped, _rollback = apply_plan(data, options["rollback_file"])
        self.stdout.write(f"Applied {len(applied)} item(s); skipped {len(skipped)}.")

        for item in skipped:
            self.stdout.write(f"  skipped {item['kind']}: {item['skipped_because']}")

        self.stdout.write(f"Rollback written to {options['rollback_file']}")
