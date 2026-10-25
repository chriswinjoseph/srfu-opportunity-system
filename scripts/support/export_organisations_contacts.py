"""
Read-only export of organisations and contacts to CSV.

Run from the PROJECT FOLDER:

    python "<path>\\export_organisations_contacts.py" "<path to db.sqlite3>" "<output folder OUTSIDE the repository>"

Writes two UTF-8 files (with a byte-order mark so Excel opens them correctly):

    organisations_<timestamp>.csv   one row per Bank, Branch or Club
    contacts_<timestamp>.csv        one row per contact, with the organisation it belongs to
    export_<timestamp>.manifest.json  row counts and SHA-256 of each file

This is NOT a backup. It leaves out users, drafts, email history, imports, scraper runs and provenance.
Use backup_sqlite.py for a complete, restorable copy.

The database is opened read-only; nothing in it changes. The files hold personal information
(contact names, emails, phone numbers): keep them somewhere access-controlled, never commit them,
and delete copies that are no longer needed.
"""

import csv
import datetime
import hashlib
import json
import pathlib
import sqlite3
import sys

if len(sys.argv) != 3:
    sys.exit(__doc__)

src, out_dir = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
here = pathlib.Path.cwd().resolve()

if not src.is_file():
    sys.exit(f"Source database not found: {src}")

if (here / ".git").exists() and (out_dir == here or here in out_dir.parents):
    sys.exit("Refusing: the output folder is inside the repository. Choose a folder outside it.")

out_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
db = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
db.row_factory = sqlite3.Row

TYPES = {"bank": "outreach_bank", "branch": "outreach_branch", "club": "outreach_club"}
NAME = {"bank": "bank_name", "branch": "branch_name", "club": "club_name"}
type_id = {
    model: pk
    for pk, model in db.execute("select id, model from django_content_type where app_label = 'outreach'")
    if model in TYPES
}
missing = [t for t in TYPES if t not in type_id]

if missing:
    sys.exit(f"This does not look like an SRFU database (no content type for: {', '.join(missing)}).")

latest = {}

for row in db.execute("select content_type_id, object_id, status, date_contacted from outreach_opportunity order by id"):
    latest[(row["content_type_id"], row["object_id"])] = (row["status"], row["date_contacted"] or "")

org_columns = [
    "organisation_type", "id", "organisation_id", "name", "parent_bank", "state", "region", "suburb",
    "postcode", "address", "public_email", "public_phone", "website_url", "source_url", "contact_status",
    "latest_outcome", "date_contacted", "is_archived", "record_source",
]
orgs, names = [], {}

for kind, table in TYPES.items():
    has_parent = kind == "branch"
    columns = {r[1] for r in db.execute(f"pragma table_info({table})")}

    for row in db.execute(f"select * from {table} order by id"):
        record = dict(row)
        names[(kind, row["id"])] = record[NAME[kind]]
        outcome, contacted = latest.get((type_id[kind], row["id"]), ("", ""))
        parent = ""

        if has_parent and record.get("bank_id"):
            parent_row = db.execute("select bank_name from outreach_bank where id = ?", (record["bank_id"],)).fetchone()
            parent = parent_row[0] if parent_row else ""

        orgs.append({
            "organisation_type": kind,
            "id": record["id"],
            "organisation_id": record.get("organisation_id", ""),
            "name": record[NAME[kind]],
            "parent_bank": parent,
            **{c: record.get(c, "") if c in columns else "" for c in (
                "state", "region", "suburb", "postcode", "address", "public_email", "public_phone",
                "website_url", "source_url", "contact_status", "record_source")},
            "latest_outcome": outcome,
            "date_contacted": contacted,
            "is_archived": record.get("is_archived", ""),
        })

contacts = []
kind_of = {pk: kind for kind, pk in type_id.items()}

for row in db.execute("select * from outreach_contact order by id"):
    kind = kind_of.get(row["content_type_id"])
    contacts.append({
        "organisation_type": kind or f"unknown content type {row['content_type_id']}",
        "organisation_id_number": row["object_id"],
        "organisation_name": names.get((kind, row["object_id"]), "ORGANISATION NOT FOUND"),
        "contact_name": row["contact_name"],
        "role": row["role"],
        "email": row["email"],
        "phone": row["phone"],
        "source_url": row["source_url"],
        "last_verified": row["last_verified"] or "",
    })

db.close()
files = {}


def write(name, columns, rows):
    path = out_dir / f"{name}_{stamp}.csv"

    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    files[path.name] = {"rows": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


write("organisations", org_columns, orgs)
write("contacts", [
    "organisation_type", "organisation_id_number", "organisation_name", "contact_name", "role", "email",
    "phone", "source_url", "last_verified",
], contacts)
orphans = sum(1 for c in contacts if c["organisation_name"] == "ORGANISATION NOT FOUND" or c["organisation_type"].startswith("unknown"))
manifest = {"created": stamp, "source_database": src.name, "files": files, "contacts_without_an_organisation": orphans}
(out_dir / f"export_{stamp}.manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

for name, info in files.items():
    print(f"{name}: {info['rows']} rows")

print(f"Contacts without a matching organisation: {orphans}")
print("Written to", out_dir)
print("These files contain personal information. Store them access-controlled and do not commit them.")
sys.exit(1 if orphans else 0)
