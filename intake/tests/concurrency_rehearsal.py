"""
Genuinely simultaneous checks against the database engine the app uses.

Separate OS processes are released together by a barrier, each with its own
database connection, so SQLite's real file locking is exercised (the Django
test runner cannot do this: it uses one in-memory database).

NEVER run this against the real database. Point it at a disposable file:

    set DJANGO_SETTINGS_MODULE=<a settings module whose DATABASES NAME is a throw-away file>
    set INTAKE_DISPOSABLE_DB=1
    python intake/tests/concurrency_rehearsal.py [processes]

It migrates the disposable database, creates its own users and records, and
exits non-zero if any invariant fails. It is not collected by the test suite.
"""

import multiprocessing as mp
import os
import sys
import traceback
from collections import Counter

PROCESSES = int(sys.argv[1]) if len(sys.argv) > 1 else 8
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 3


def boot():
    import django

    django.setup()


def check_disposable():
    from django.conf import settings

    name = str(settings.DATABASES["default"]["NAME"])

    if os.environ.get("INTAKE_DISPOSABLE_DB") != "1" or os.path.basename(name) == "db.sqlite3":
        raise SystemExit("Refusing to run: this needs a disposable database (INTAKE_DISPOSABLE_DB=1).")

    return name


# --------------------------------------------------------------- child tasks
def child(task, barrier, queue, payload):
    try:
        boot()
        from django.db import connection

        connection.ensure_connection()
        barrier.wait()
        queue.put(("ok", TASKS[task](payload)))
    except Exception as exc:  # reported, never raised: the parent decides
        queue.put(("error", f"{type(exc).__name__}: {exc}", traceback.format_exc(limit=3)))


def t_confirm(payload):
    from accounts.models import User
    from intake.importer import ImportBusy, confirm_import

    user = User.objects.get(pk=payload["user"])

    try:
        confirm_import(payload["run"], user)

        return "confirmed"
    except ImportBusy as exc:
        return f"busy: {exc}"


def t_process(payload):
    from accounts.models import User
    from intake.ingest import process_submission
    from intake.matching import Submission
    from intake.models import IntakeRun

    user = User.objects.get(pk=payload["user"])
    run = IntakeRun.objects.get(pk=payload["run"])
    sub = Submission(
        org_type="bank", name=payload["name"], state="VIC", email=f"{payload['source_id'].lower()}@example.test",
        source_key="client_workbook", source_org_id=payload["source_id"], origin="import",
        row_ref="concurrency",
    )
    result = process_submission(run, sub, user)

    return f"{result.outcome}|{result.message[:70]}"


def t_claim(payload):
    from intake.scraper import claim_next_job

    run = claim_next_job()

    return f"claimed:{run.pk}" if run else "none"


def t_review(payload):
    from accounts.models import User
    from intake.reviews import ReviewError, decide_review

    user = User.objects.get(pk=payload["user"])

    try:
        decide_review(payload["review"], user, payload["decision"])

        return f"decided:{payload['decision']}"
    except ReviewError as exc:
        return f"refused: {exc}"


def t_change(payload):
    from accounts.models import User
    from intake.reviews import ReviewError, decide_change

    user = User.objects.get(pk=payload["user"])

    try:
        decide_change(payload["change"], user, payload["decision"])

        return f"decided:{payload['decision']}"
    except ReviewError as exc:
        return f"refused: {exc}"


TASKS = {"confirm": t_confirm, "process": t_process, "claim": t_claim, "review": t_review, "change": t_change}


# ------------------------------------------------------------------- parent
def race(task, payloads):
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(len(payloads))
    queue = ctx.Queue()
    procs = [ctx.Process(target=child, args=(task, barrier, queue, p)) for p in payloads]

    for proc in procs:
        proc.start()

    results = [queue.get(timeout=180) for _ in procs]

    for proc in procs:
        proc.join(timeout=30)

    return results


FAILURES = []


def expect(label, condition, detail=""):
    print(("PASS  " if condition else "FAIL  ") + label + (f"   [{detail}]" if detail and not condition else ""))

    if not condition:
        FAILURES.append(label)


def summarise(results):
    errors = [r for r in results if r[0] == "error"]
    values = Counter(r[1].split("|")[0].split(":")[0] if r[0] == "ok" else "ERROR" for r in results)

    return errors, values


def main():
    boot()
    from django.core.management import call_command

    print("Database:", check_disposable())
    call_command("migrate", verbosity=0, interactive=False)

    from accounts.models import User
    from intake.importer import create_preview
    from intake.models import (
        DuplicateReview, IntakeResult, IntakeRun, OrganisationSource, ProposedChange,
    )
    from intake.ingest import process_submission
    from intake.matching import Submission
    from outreach.models import Bank, Contact

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from intake.tests.helpers import default_workbook

    admin, _ = User.objects.get_or_create(
        email="admin@concurrency.test",
        defaults={"first_name": "Ada", "last_name": "Admin", "role": "admin"},
    )
    admin.role = "admin"
    admin.set_password("Pass-12345-xx!")
    admin.save()

    print(f"\n{PROCESSES} simultaneous processes per race, {ROUNDS} rounds each\n")

    # A. Confirming the same preview ----------------------------------------
    for round_no in range(ROUNDS):
        data = default_workbook()
        run, _p = create_preview(admin, data + b"" if round_no == 0 else data, f"round{round_no}.xlsx")
        banks_before = Bank.objects.count()
        results = race("confirm", [{"run": run.pk, "user": admin.pk}] * PROCESSES)
        errors, values = summarise(results)
        created = Bank.objects.count() - banks_before
        expect(f"A{round_no}: one confirmation wins, others are refused, no errors",
               not errors and values["confirmed"] == 1 and values["busy"] == PROCESSES - 1, str(results)[:300])
        expect(f"A{round_no}: no duplicate organisations or contacts", created in (0, 3) and Contact.objects.count() <= 5,
               f"created={created}")
        IntakeRun.objects.filter(pk=run.pk).update(status="successful")

    expect("A: first import created exactly the 3 banks and 5 contacts",
           Bank.objects.count() == 3 and Contact.objects.count() == 5,
           f"banks={Bank.objects.count()} contacts={Contact.objects.count()}")

    # B. The shared pipeline, many writers, one new organisation --------------
    run = IntakeRun.objects.create(kind="import", status="running", created_by=admin, source_key="client_workbook")
    results = race("process", [{"run": run.pk, "user": admin.pk, "name": "Zed Community Bank", "source_id": "Z1"}] * PROCESSES)
    errors, values = summarise(results)
    zed = Bank.objects.filter(bank_name="Zed Community Bank").count()
    sources = OrganisationSource.objects.filter(source_org_id="Z1").count()
    failed = IntakeResult.objects.filter(run=run, outcome="failed").count()
    expect("B: identical records processed at the same moment create exactly one bank",
           not errors and zed == 1 and sources == 1, f"banks={zed} sources={sources} {values}")
    expect("B: no write was lost to a database lock (zero 'failed' results)", failed == 0, f"failed={failed} {results[:2]}")
    expect("B: every other result matched the one created bank (nothing duplicated)",
           values["created"] == 1 and values["exact"] + values["unchanged"] == PROCESSES - 1, str(values))

    towns = ["Wombat Creek", "Quokka Bay", "Platypus Flat", "Kookaburra Ridge", "Echidna Vale",
             "Bilby Heights", "Numbat Springs", "Dingo Crossing", "Wallaby Point", "Cassowary Park"]
    distinct = [
        {"run": run.pk, "user": admin.pk, "name": f"{towns[i]} Community Bank", "source_id": f"D{i}"}
        for i in range(PROCESSES)
    ]
    results = race("process", distinct)
    errors, values = summarise(results)
    made = Bank.objects.filter(bank_name__in=[d["name"] for d in distinct]).count()
    expect("B: different records processed at the same moment are all saved", not errors and made == PROCESSES,
           f"saved={made}/{PROCESSES} {results[:2]}")

    # C. Worker claims ---------------------------------------------------------
    job = IntakeRun.objects.create(kind="scraper", status="queued", created_by=admin, source_key="scraper",
                                   options={"adapters": ["bendigo_community_banks"], "done_pages": []})
    results = race("claim", [{}] * PROCESSES)
    claimed = [r[1] for r in results if r[0] == "ok" and r[1].startswith("claimed")]
    job.refresh_from_db()
    expect("C: one queued job is claimed by exactly one of the simultaneous workers",
           len(claimed) == 1 and job.attempts == 1 and job.status == "running", f"{claimed} attempts={job.attempts}")

    jobs = [IntakeRun.objects.create(kind="scraper", status="queued", created_by=admin, source_key="scraper",
                                     options={"adapters": ["mvcc_sports_clubs"], "done_pages": []}) for _ in range(4)]
    results = race("claim", [{}] * PROCESSES)
    claimed = sorted(r[1] for r in results if r[0] == "ok" and r[1].startswith("claimed"))
    expect("C: four queued jobs and many workers: each job claimed exactly once",
           len(claimed) == 4 and len(set(claimed)) == 4 and all(IntakeRun.objects.get(pk=j.pk).attempts == 1 for j in jobs),
           str(claimed))

    # D. Review decisions ------------------------------------------------------
    alpha = Bank.objects.create(bank_name="Alpha Community Bank", state="VIC", region="Victoria")
    review_run = IntakeRun.objects.create(kind="import", status="running", created_by=admin, source_key="client_workbook")
    banks_before = Bank.objects.count()
    held = process_submission(
        review_run,
        Submission(org_type="bank", name="Alpha Community Bank Ltd", state="VIC", source_key="client_workbook",
                   source_org_id="A9", origin="import", row_ref="concurrency"),
        admin,
    )
    review = DuplicateReview.objects.filter(status="pending").latest("pk")
    expect("D: the similar record was held, not created", held.outcome == "review" and Bank.objects.count() == banks_before)
    decisions = ["create_separate", "use_existing", "reject"] * PROCESSES
    results = race("review", [{"review": review.pk, "user": admin.pk, "decision": decisions[i]} for i in range(PROCESSES)])
    errors, values = summarise(results)
    review.refresh_from_db()
    decided = [r[1] for r in results if r[0] == "ok" and r[1].startswith("decided")]
    created = Bank.objects.count() - banks_before
    expect("D: simultaneous conflicting decisions: exactly one is saved, none lost or doubled",
           not errors and len(decided) == 1 and review.status != "pending" and review.decision, f"{results}")
    expect("D: at most one organisation was created by the winning decision", created in (0, 1) and (
        created == 1) == (review.decision == "create_separate"), f"created={created} decision={review.decision}")

    # E. Proposed changes -------------------------------------------------------
    existing = Bank.objects.get(pk=alpha.pk)
    existing.public_email = "old@example.test"
    existing.save()
    change_run = IntakeRun.objects.create(kind="import", status="running", created_by=admin, source_key="client_workbook")
    from django.contrib.contenttypes.models import ContentType

    change = ProposedChange.objects.create(
        run=change_run, content_type=ContentType.objects.get_for_model(Bank), object_id=existing.pk,
        field="public_email", old_value="old@example.test", new_value="new@example.test", source_label="concurrency",
    )
    decisions = ["approve", "reject"] * PROCESSES
    results = race("change", [{"change": change.pk, "user": admin.pk, "decision": decisions[i]} for i in range(PROCESSES)])
    errors, values = summarise(results)
    change.refresh_from_db()
    existing.refresh_from_db()
    decided = [r[1] for r in results if r[0] == "ok" and r[1].startswith("decided")]
    expect("E: simultaneous approve/reject: exactly one decision, value consistent with it",
           not errors and len(decided) == 1 and (existing.public_email == "new@example.test") == (change.status == "approved"),
           f"{results} status={change.status} email={existing.public_email}")

    print()
    print("RESULT:", "ALL PASSED" if not FAILURES else f"{len(FAILURES)} FAILED")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
