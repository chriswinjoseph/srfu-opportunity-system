"""
Supported maintenance procedure for applying approved data corrections.

The older ``apply_data_corrections`` command refuses the project's own
database and is left exactly as it is. The live database is changed only
through the steps here, each of which can refuse:

1. ``backup``   - verified SQLite backup outside the repository, with a manifest.
2. ``plan``     - read-only preview, regenerated from the current data.
3. ``approve``  - a human records which kinds of correction are approved.
4. ``apply``    - re-checks everything, then applies ONLY the approved kinds,
                  all-or-nothing, verifying the result and a rollback rehearsal
                  before anything is committed.
5. ``revert``   - restores the recorded old values, with the same guards.

Nothing here renames the database, disables a safeguard or runs without an
explicit ``--execute``.
"""

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .corrections import ALL_KINDS, apply_plan, build_plan, revert_plan
from .models import IntakeRun
from .worker import worker_state

# Tables a correction may legitimately change; every other table must be identical.
CHANGING_TABLES = (
    "outreach_bank",
    "outreach_contact",
    "outreach_opportunity",
    "intake_organisationsource",
    "intake_contactsource",
)
ROW_CHECKED_TABLES = ("outreach_bank", "outreach_contact", "outreach_opportunity")

WEB_QUIET_SECONDS = 180
DB_QUIET_SECONDS = 30
BACKUP_MAX_AGE_MINUTES = 60


class MaintenanceError(Exception):
    """A safeguard refused. The message says what to do; nothing was changed."""


class _Rewind(Exception):
    pass


# ------------------------------------------------------------------ helpers
def sha256_file(path):
    digest = hashlib.sha256()

    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _tables(conn):
    return [
        r[0] for r in conn.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1"
        )
    ]


def _row_expression(conn, table):
    cols = [r[1] for r in conn.execute(f'pragma table_info("{table}")')]

    return " || '|' || ".join(f'quote("{c}")' for c in cols)


def fingerprint(conn):
    """Per table: row count and a hash of every row (type-independent text)."""
    result = {}

    for table in _tables(conn):
        digest = hashlib.sha256()
        count = 0

        for (text,) in conn.execute(f'select {_row_expression(conn, table)} from "{table}" order by 1'):
            digest.update(text.encode("utf-8"))
            digest.update(b"\n")
            count += 1

        result[table] = {"rows": count, "sha256": digest.hexdigest()}

    return result


def live_connection():
    connection.ensure_connection()

    return connection.connection


def row_hashes(conn, table):
    expr = _row_expression(conn, table)

    return {
        str(pk): hashlib.sha256(text.encode("utf-8")).hexdigest()
        for pk, text in conn.execute(f'select "id", {expr} from "{table}"')
    }


def _diff_tables(a, b):
    return sorted(t for t in set(a) | set(b) if a.get(t) != b.get(t))


def database_path():
    name = str(settings.DATABASES["default"]["NAME"])

    return Path(name) if name and not name.startswith(("file:", ":memory:")) and Path(name).is_file() else None


def _outside_repository(path):
    base = Path(settings.BASE_DIR).resolve()
    resolved = Path(path).resolve()

    return base != resolved and base not in resolved.parents


def canonical_fixes(plan_dict, kinds):
    fixes = [f for f in plan_dict["fixes"] if f["kind"] in kinds]

    return sorted(fixes, key=lambda f: json.dumps(f, sort_keys=True, default=str))


def plan_fingerprint(plan_dict, kinds):
    text = json.dumps(canonical_fixes(plan_dict, kinds), sort_keys=True, default=str)

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _counts_by_kind(plan_dict):
    counts = {}

    for fix in plan_dict["fixes"]:
        counts[fix["kind"]] = counts.get(fix["kind"], 0) + 1

    return counts


def dashboard_counts():
    """Contacted / Not Yet Contacted exactly as the dashboard counts them."""
    from outreach.views import _get_all_organisations

    rows = _get_all_organisations()
    counts = {"contacted": 0, "not_yet_contacted": 0}

    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] += 1

    return counts


# -------------------------------------------------------------- stop checks
def check_stopped(now=None, web_quiet=WEB_QUIET_SECONDS, db_quiet=DB_QUIET_SECONDS):
    """Reasons the website or worker may still be writing (empty list = quiet)."""
    from django.contrib.sessions.models import Session

    now = now or timezone.now()
    problems = []
    state = worker_state(now)

    if state["alive"]:
        problems.append("A background worker checked in within the last 90 seconds. Stop it first.")

    if IntakeRun.objects.filter(kind=IntakeRun.KIND_SCRAPER, status=IntakeRun.STATUS_RUNNING).exists():
        problems.append("A scraper job is marked as running.")

    latest = Session.objects.order_by("-expire_date").first()

    if latest is not None:
        last_activity = latest.expire_date - timedelta(seconds=settings.SESSION_COOKIE_AGE)
        idle = (now - last_activity).total_seconds()

        if idle < web_quiet:
            problems.append(
                f"A user was active on the website {int(max(idle, 0))} seconds ago. "
                f"Stop the website and wait at least {web_quiet} seconds."
            )

    path = database_path()

    if path is not None:
        age = now.timestamp() - path.stat().st_mtime

        if age < db_quiet:
            problems.append(f"The database file was written {int(max(age, 0))} seconds ago.")

    return problems


def queued_jobs():
    """Scraper jobs an Admin has queued. They stay untouched, and run when a worker next starts."""
    return [
        {"id": run.pk, "queued_at": run.created_at.isoformat(), "adapters": (run.options or {}).get("adapters", [])}
        for run in IntakeRun.objects.filter(kind=IntakeRun.KIND_SCRAPER, status=IntakeRun.STATUS_QUEUED).order_by("id")
    ]


def _require_queued_jobs_acknowledged(acknowledged):
    jobs = queued_jobs()

    if jobs and not acknowledged:
        listing = ", ".join(f"#{j['id']}" for j in jobs)
        raise MaintenanceError(
            f"Scraper job(s) {listing} are queued. The worker must stay stopped; they will run (live scraping) "
            "the next time a worker starts, so start the worker only after the corrections are verified. "
            "Re-run with --acknowledge-queued-jobs to confirm you accept that."
        )

    return jobs


# ------------------------------------------------------------------- backup
BACKUP_LOCK_TIMEOUT_SECONDS = 120


def _copy_database(source, target, timeout=BACKUP_LOCK_TIMEOUT_SECONDS):
    """SQLite online backup, abandoned with a clear message if the database stays locked."""
    started = time.monotonic()

    def progress(status, remaining, total):
        if time.monotonic() - started > timeout:
            raise MaintenanceError(
                "The database stayed locked while it was being backed up. "
                "Stop the website and worker, then try again."
            )

    source.backup(target, progress=progress)


def make_backup(dest_dir):
    dest_dir = Path(dest_dir)

    if not _outside_repository(dest_dir):
        raise MaintenanceError("The backup folder must be outside the repository (Git).")

    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"db.sqlite3.pre-corrections-{stamp}"

    if dest.exists():
        raise MaintenanceError(f"{dest} already exists.")

    live = live_connection()
    target = sqlite3.connect(str(dest))

    try:
        _copy_database(live, target)
    finally:
        target.close()

    manifest = verify_backup_file(dest, live)
    manifest["created_at"] = timezone.now().isoformat()
    manifest["source_database"] = str(settings.DATABASES["default"]["NAME"])
    manifest_path = dest.with_name(dest.name + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return dest, manifest_path, manifest


def verify_backup_file(path, live=None):
    """Integrity, foreign keys, and (when ``live`` is given) equality with the live data."""
    path = Path(path)

    if not path.is_file():
        raise MaintenanceError(f"Backup file not found: {path}")

    conn = sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True)

    try:
        integrity = conn.execute("pragma integrity_check").fetchall()

        if integrity != [("ok",)]:
            raise MaintenanceError("The backup failed SQLite's integrity check.")

        if conn.execute("pragma foreign_key_check").fetchall():
            raise MaintenanceError("The backup has foreign-key violations.")

        backup_fp = fingerprint(conn)
    finally:
        conn.close()

    if live is not None and _diff_tables(backup_fp, fingerprint(live)):
        raise MaintenanceError("The backup does not match the live database.")

    return {
        "backup_path": str(path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "integrity_check": "ok",
        "fingerprint": backup_fp,
    }


def verify_manifest(manifest_path, max_age_minutes=BACKUP_MAX_AGE_MINUTES, now=None):
    """The backup must be intact, outside Git, recent, and equal to the live data now."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    path = Path(manifest["backup_path"])

    if not _outside_repository(path):
        raise MaintenanceError("The backup is inside the repository.")

    current = verify_backup_file(path)

    if current["sha256"] != manifest["sha256"]:
        raise MaintenanceError("The backup file has changed since its manifest was written.")

    now = now or timezone.now()
    created = datetime.fromisoformat(manifest["created_at"])

    if now - created > timedelta(minutes=max_age_minutes):
        raise MaintenanceError(f"The backup is older than {max_age_minutes} minutes. Take a fresh one.")

    changed = _diff_tables(manifest["fingerprint"], fingerprint(live_connection()))

    if changed:
        raise MaintenanceError(
            "The database changed after the backup was taken (intervening activity in: "
            + ", ".join(changed) + "). Take a fresh backup and regenerate the plan."
        )

    return manifest


# ------------------------------------------------------------ plan / approve
def build_plan_file(workbook_path):
    data = Path(workbook_path).read_bytes()
    plan = build_plan(data, Path(workbook_path).name).to_dict()
    plan["meta"] = {
        "workbook_name": Path(workbook_path).name,
        "workbook_sha256": hashlib.sha256(data).hexdigest(),
        "generated_at": timezone.now().isoformat(),
        "database_fingerprint": fingerprint(live_connection()),
    }

    return plan


def make_approval(plan_dict, kinds, approved_by):
    kinds = [k.strip() for k in kinds if k.strip()]
    approved_by = (approved_by or "").strip()

    if not approved_by:
        raise MaintenanceError("Say who approved the corrections (--approved-by).")

    if not kinds or any(k not in ALL_KINDS for k in kinds):
        raise MaintenanceError("List each approved kind explicitly. Known kinds: " + ", ".join(ALL_KINDS))

    available = _counts_by_kind(plan_dict)
    missing = [k for k in kinds if not available.get(k)]

    if missing:
        raise MaintenanceError("The plan has no items of kind: " + ", ".join(missing))

    return {
        "approved_by": approved_by,
        "approved_at": timezone.now().isoformat(),
        "approved_kinds": kinds,
        "approved_counts": {k: available[k] for k in kinds},
        "plan_sha256": plan_fingerprint(plan_dict, kinds),
        "workbook_sha256": plan_dict["meta"]["workbook_sha256"],
    }


def _load_approval(approval, kinds_plan_fresh, workbook_sha):
    for key in ("approved_by", "approved_kinds", "plan_sha256", "workbook_sha256"):
        if not approval.get(key):
            raise MaintenanceError(f"The approval file is missing '{key}'.")

    kinds = approval["approved_kinds"]

    if not isinstance(kinds, list) or any(k not in ALL_KINDS for k in kinds):
        raise MaintenanceError("The approval lists an unknown kind of correction.")

    if approval["workbook_sha256"] != workbook_sha:
        raise MaintenanceError("The workbook is not the one that was approved.")

    return kinds


# ------------------------------------------------------------------- apply
def apply_approved(workbook_path, approval, manifest_path, rollback_dir=None, execute=False,
                   confirm_stopped=False, now=None, acknowledge_queued_jobs=False):
    """Apply only the approved kinds. All-or-nothing; commits only when ``execute``."""
    if not confirm_stopped:
        raise MaintenanceError("Confirm the website and worker are stopped (--confirm-stopped).")

    problems = check_stopped(now)

    if problems:
        raise MaintenanceError("The system is not quiet: " + " ".join(problems))

    jobs = _require_queued_jobs_acknowledged(acknowledge_queued_jobs)
    manifest = verify_manifest(manifest_path, now=now)
    data = Path(workbook_path).read_bytes()
    workbook_sha = hashlib.sha256(data).hexdigest()
    kinds = _load_approval(approval, None, workbook_sha)

    fresh = build_plan(data, Path(workbook_path).name).to_dict()

    if plan_fingerprint(fresh, kinds) != approval["plan_sha256"]:
        raise MaintenanceError(
            "The plan changed since it was approved. Approved: "
            f"{approval.get('approved_counts')}. Now: { {k: _counts_by_kind(fresh).get(k, 0) for k in kinds} }. "
            "Regenerate the plan and approve it again."
        )

    approved_plan = {"fixes": canonical_fixes(fresh, kinds)}
    live = live_connection()
    report = {"kinds": kinds, "counts": {k: sum(1 for f in approved_plan["fixes"] if f["kind"] == k) for k in kinds},
              "queued_jobs": jobs}

    with transaction.atomic():
        pre = fingerprint(live)
        pre_rows = {t: row_hashes(live, t) for t in ROW_CHECKED_TABLES}
        before_counts = dashboard_counts()

        applied, skipped, rollback = apply_plan(approved_plan, None)

        if skipped:
            raise MaintenanceError(
                f"{len(skipped)} item(s) could not be applied ("
                + "; ".join(sorted({s['skipped_because'] for s in skipped}))
                + "). Nothing was changed."
            )

        post = fingerprint(live)
        _verify_result(live, pre, post, pre_rows, approved_plan, before_counts, report)

        # Rehearse the rollback inside the same transaction, then undo the rehearsal.
        try:
            with transaction.atomic():
                revert_plan(rollback)

                if _diff_tables(pre, fingerprint(live)):
                    raise MaintenanceError("The rollback rehearsal did not restore the original data. Nothing was changed.")

                raise _Rewind
        except _Rewind:
            pass

        if _diff_tables(post, fingerprint(live)):
            raise MaintenanceError("The data was not restored after the rollback rehearsal. Nothing was changed.")

        report["rollback_rehearsal"] = "restored the original data exactly"
        rollback_path = None

        if execute:
            target_dir = Path(rollback_dir) if rollback_dir else Path(manifest["backup_path"]).parent
            rollback_path = target_dir / (Path(manifest["backup_path"]).name + ".rollback.json")
            rollback_path.write_text(json.dumps({
                "applied_at": timezone.now().isoformat(),
                "approved_by": approval["approved_by"],
                "plan_sha256": approval["plan_sha256"],
                "pre_fingerprint": pre,
                "post_fingerprint": post,
                "changes": rollback,
            }, indent=2), encoding="utf-8")
        else:
            transaction.set_rollback(True)

    report.update(applied=len(applied), committed=bool(execute), rollback_file=str(rollback_path) if rollback_path else None,
                  backup=manifest["backup_path"])

    return report


def _verify_result(live, pre, post, pre_rows, plan, before_counts, report):
    changed = _diff_tables(pre, post)
    unexpected = [t for t in changed if t not in CHANGING_TABLES]

    if unexpected:
        raise MaintenanceError("Unexpected tables changed: " + ", ".join(unexpected) + ". Nothing was changed.")

    kinds = [f["kind"] for f in plan["fixes"]]
    sources = kinds.count("source_provenance")
    contact_sources = kinds.count("contact_provenance")

    expected_rows = {
        "outreach_bank": pre["outreach_bank"]["rows"],
        "outreach_contact": pre["outreach_contact"]["rows"],
        "outreach_opportunity": pre["outreach_opportunity"]["rows"],
        "intake_organisationsource": pre["intake_organisationsource"]["rows"] + sources,
        "intake_contactsource": pre["intake_contactsource"]["rows"] + contact_sources,
    }

    for table, count in expected_rows.items():
        if post[table]["rows"] != count:
            raise MaintenanceError(f"{table} has {post[table]['rows']} rows, expected {count}. Nothing was changed.")

    targets = {"outreach_bank": set(), "outreach_contact": set(), "outreach_opportunity": set()}

    for fix in plan["fixes"]:
        if fix.get("bank_id") and fix["kind"] != "source_provenance":
            targets["outreach_bank"].add(str(fix["bank_id"]))

        if fix.get("contact_id") and fix["kind"] == "unspecified_name":
            targets["outreach_contact"].add(str(fix["contact_id"]))

        if fix.get("opportunity_id"):
            targets["outreach_opportunity"].add(str(fix["opportunity_id"]))

    for table in ROW_CHECKED_TABLES:
        after = row_hashes(live, table)
        touched = {pk for pk in after if pre_rows[table].get(pk) != after[pk]}

        if set(after) != set(pre_rows[table]) or not touched <= targets[table]:
            raise MaintenanceError(f"Records outside the approved corrections changed in {table}. Nothing was changed.")

    expected_status = sum(1 for f in plan["fixes"] if f["kind"] == "contact_status")
    after_counts = dashboard_counts()

    if (after_counts["contacted"] != before_counts["contacted"] - expected_status
            or after_counts["not_yet_contacted"] != before_counts["not_yet_contacted"] + expected_status):
        raise MaintenanceError("Dashboard counts do not match the approved status corrections. Nothing was changed.")

    report["dashboard_before"] = before_counts
    report["dashboard_after"] = after_counts


# ------------------------------------------------------------------- revert
def revert_applied(rollback_path, execute=False, confirm_stopped=False, now=None, acknowledge_queued_jobs=False):
    if not confirm_stopped:
        raise MaintenanceError("Confirm the website and worker are stopped (--confirm-stopped).")

    problems = check_stopped(now)

    if problems:
        raise MaintenanceError("The system is not quiet: " + " ".join(problems))

    jobs = _require_queued_jobs_acknowledged(acknowledge_queued_jobs)

    record = json.loads(Path(rollback_path).read_text(encoding="utf-8-sig"))
    live = live_connection()

    if _diff_tables(record["post_fingerprint"], fingerprint(live)):
        raise MaintenanceError(
            "The database changed after the corrections were applied, so an automatic revert is refused. "
            "Restore the verified backup instead."
        )

    with transaction.atomic():
        revert_plan(record["changes"])

        if _diff_tables(record["pre_fingerprint"], fingerprint(live)):
            raise MaintenanceError("The revert did not restore the original data. Nothing was changed.")

        if not execute:
            transaction.set_rollback(True)

    return {"reverted": len(record["changes"]), "committed": bool(execute), "queued_jobs": jobs}
