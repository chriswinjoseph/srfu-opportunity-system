"""
Read-only check that the database's applied migrations equal the migrations in the checked-out code.

Run from the PROJECT FOLDER with the project's virtual environment active (works in PowerShell):

    python <path>\\check_db_matches_code.py

Uses DJANGO_SETTINGS_MODULE (default srfu.settings) and the same environment variables the site uses.
Prints the database file it inspected. Exit code 0 = MATCH, 1 = MISMATCH.

This compares migration names only. It does NOT prove full compatibility: also follow the rollback
checklist (matching code release and dependencies, email reconciliation, application checks).
"""

import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "srfu.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.migrations.loader import MigrationLoader  # noqa: E402

loader = MigrationLoader(connection)
code = set(loader.graph.nodes)
applied = set(loader.applied_migrations)
ahead = sorted(applied - code)
behind = sorted(code - applied)

print("Database inspected :", settings.DATABASES["default"]["NAME"])
print("DB AHEAD OF CODE   :", ahead or "none")
print("DB BEHIND CODE     :", behind or "none")
print("RESULT             :", "MATCH" if not ahead and not behind else "MISMATCH")
sys.exit(0 if not ahead and not behind else 1)
