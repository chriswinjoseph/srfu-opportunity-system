"""
Read-only list of email drafts that must be reconciled after a restore.

    python report_email_activity.py <preserved FAILED database> [--since 2026-10-20T09:00:00]
                                    [--restored <restored database>]

Lists every draft in the preserved database that is 'sending', flagged for reconciliation, or sent
at/after --since (UTC, as stored). With --restored, each row also shows that draft's status in the
RESTORED database, and flags the dangerous cases: a draft that was sent (or may have been sent)
after the backup but is still approved / failed / awaiting in the restored copy, so it could be
sent a second time.

IMPORTANT LIMITS
* 'smtp_confirmed' means the mail server ACCEPTED the message. It is not proof of delivery.
* The application does not store a Message-ID, so a row can only be matched to a mailbox record by
  recipient, subject and time.
* This script reports; it does not fix anything. The application has no supported command to clear
  a reconciliation flag or to mark a restored draft as sent (see the handover rollback checklist).

Both databases are opened read-only. Times in the database are UTC.
"""

import sqlite3
import sys

if len(sys.argv) < 2:
    sys.exit(__doc__)


def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


since = (arg("--since") or "").replace("T", " ") or None  # stored as "YYYY-MM-DD HH:MM:SS"
restored_path = arg("--restored")


def open_ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


failed = open_ro(sys.argv[1])
restored = open_ro(restored_path) if restored_path else None
sql = (
    "select draft_id, workflow_status, reconciliation_required, sent_at, smtp_confirmed_at, "
    "recipient_email, subject, send_failure_reason from outreach_emaildraft "
    "where workflow_status = 'sending' or reconciliation_required = 1"
)
params = []

if since:
    sql += " or (sent_at is not null and sent_at >= ?)"
    params.append(since)

rows = failed.execute(sql + " order by sent_at", params).fetchall()
print(f"{len(rows)} draft(s) in the preserved database need reconciling")
risky = 0

for draft_id, status, recon, sent_at, confirmed, recipient, subject, reason in rows:
    line = (f"- {draft_id} | preserved status={status} | reconcile_flag={bool(recon)} | sent_at={sent_at} "
            f"| smtp_accepted_at={confirmed} | to={recipient} | subject={subject!r}")

    if restored:
        got = restored.execute("select workflow_status, reconciliation_required from outreach_emaildraft where draft_id = ?", (draft_id,)).fetchone()

        if got is None:
            line += " | RESTORED: draft does not exist (its organisation may also look uncontacted)"
            risky += 1
        else:
            line += f" | RESTORED status={got[0]} reconcile_flag={bool(got[1])}"

            if got[0] in ("approved", "send_failed", "awaiting_approval", "draft", "changes_requested") and not got[1]:
                line += "  <-- COULD BE SENT AGAIN"
                risky += 1

    print(line)

    if reason:
        print(f"    note: {reason[:160]}")

if restored:
    print(f"{risky} row(s) could lead to a duplicate email if normal operation restarted now")
