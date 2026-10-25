"""
Safety guard: confirm which database the current settings resolve to, BEFORE any write.

Run from the PROJECT FOLDER with the same environment variables you will use for the write:

    python scripts/support/assert_database_path.py "D:\\path\\to\\expected.sqlite3"

Prints the resolved database file and exits 0 only if it equals the expected path AND is not the
project's own db.sqlite3. Exit 1 otherwise. Reads settings only; nothing is written.
"""

import os
import sys

if len(sys.argv) != 2:
    sys.exit(__doc__)

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "srfu.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

resolved = os.path.normcase(os.path.abspath(str(settings.DATABASES["default"]["NAME"])))
expected = os.path.normcase(os.path.abspath(sys.argv[1]))
project_db = os.path.normcase(os.path.abspath(os.path.join(os.getcwd(), "db.sqlite3")))

print("Settings module :", os.environ["DJANGO_SETTINGS_MODULE"])
print("Resolved database:", resolved)

if resolved == project_db:
    sys.exit("REFUSED: this is the project's own db.sqlite3.")

if resolved != expected:
    sys.exit(f"REFUSED: expected {expected}")

print("OK: the resolved database is the expected one.")
