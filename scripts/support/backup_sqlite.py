"""
Verified backup of the SQLite database (read-only on the source).

Run from the PROJECT FOLDER (so the git commit of the code is recorded):

    python <path>\\backup_sqlite.py <path to db.sqlite3> <backup folder OUTSIDE the repository>

Writes db.sqlite3.<timestamp> and db.sqlite3.<timestamp>.manifest.json containing the SHA-256,
integrity and foreign-key results, the latest applied migration per app, and the git commit.
Exits 1 if the copy fails its checks. Nothing here changes the source database.
"""

import datetime
import hashlib
import json
import pathlib
import sqlite3
import subprocess
import sys

if len(sys.argv) != 3:
    sys.exit(__doc__)

src, dest_dir = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
here = pathlib.Path.cwd().resolve()

if not src.is_file():
    sys.exit(f"Source database not found: {src}")

if (here / ".git").exists() and (dest_dir == here or here in dest_dir.parents):
    sys.exit("Refusing: the backup folder is inside the repository. Choose a folder outside it.")

dest_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
dest = dest_dir / f"db.sqlite3.{stamp}"

source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
target = sqlite3.connect(dest)
source.backup(target)
target.close()
source.close()

check = sqlite3.connect(f"file:{dest.as_posix()}?mode=ro", uri=True)
integrity = check.execute("pragma integrity_check").fetchone()[0]
fk_violations = len(check.execute("pragma foreign_key_check").fetchall())
migrations = {}

for app, name in check.execute("select app, name from django_migrations order by id"):
    migrations[app] = name

check.close()

try:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
except Exception:
    commit = "UNKNOWN (run from the project folder)"

manifest = {
    "file": dest.name,
    "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
    "bytes": dest.stat().st_size,
    "integrity_check": integrity,
    "foreign_key_violations": fk_violations,
    "latest_migration_per_app": migrations,
    "git_commit": commit,
    "created": stamp,
}
(dest_dir / (dest.name + ".manifest.json")).write_text(json.dumps(manifest, indent=2))
print(f"Backup: {dest}")
print(f"integrity_check={integrity}  foreign_key_violations={fk_violations}  git_commit={commit}")

if integrity != "ok" or fk_violations:
    sys.exit("BACKUP FAILED ITS CHECKS: do not rely on it.")
