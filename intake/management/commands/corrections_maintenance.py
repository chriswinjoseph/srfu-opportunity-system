"""
Supported procedure for applying approved data corrections (see
docs/Data-Corrections-Maintenance.md). Run with the website and worker stopped.

    python manage.py corrections_maintenance check
    python manage.py corrections_maintenance backup --dest-dir D:\\backups
    python manage.py corrections_maintenance plan --workbook W.xlsx --out plan.json
    python manage.py corrections_maintenance approve --plan plan.json --kinds a,b --approved-by "Name" --out approval.json
    python manage.py corrections_maintenance apply --workbook W.xlsx --approval approval.json \\
        --backup-manifest <backup>.manifest.json --confirm-stopped            # dry run
    ... same command plus --execute                                           # commits
    python manage.py corrections_maintenance revert --rollback-file <backup>.rollback.json --confirm-stopped --execute

``apply`` and ``revert`` change nothing unless ``--execute`` is given.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from intake import maintenance
from intake.corrections import ALL_KINDS


class Command(BaseCommand):
    help = "Guarded maintenance procedure for approved client-data corrections."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)

        sub.add_parser("check", help="Report whether the website and worker look stopped.")

        backup = sub.add_parser("backup", help="Verified backup outside the repository.")
        backup.add_argument("--dest-dir", required=True)

        plan = sub.add_parser("plan", help="Read-only preview from the current data.")
        plan.add_argument("--workbook", required=True)
        plan.add_argument("--out", required=True)

        approve = sub.add_parser("approve", help="Record which kinds of correction are approved.")
        approve.add_argument("--plan", required=True)
        approve.add_argument("--kinds", required=True, help="Comma-separated; known: " + ", ".join(ALL_KINDS))
        approve.add_argument("--approved-by", required=True)
        approve.add_argument("--out", required=True)

        apply_ = sub.add_parser("apply", help="Apply only the approved kinds (dry run unless --execute).")
        apply_.add_argument("--workbook", required=True)
        apply_.add_argument("--approval", required=True)
        apply_.add_argument("--backup-manifest", required=True)
        apply_.add_argument("--rollback-dir", default="")
        apply_.add_argument("--confirm-stopped", action="store_true")
        apply_.add_argument("--acknowledge-queued-jobs", action="store_true",
                            help="Accept that queued scraper jobs will run when a worker next starts.")
        apply_.add_argument("--execute", action="store_true")

        revert = sub.add_parser("revert", help="Undo an applied run (dry run unless --execute).")
        revert.add_argument("--rollback-file", required=True)
        revert.add_argument("--confirm-stopped", action="store_true")
        revert.add_argument("--acknowledge-queued-jobs", action="store_true")
        revert.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        action = options["action"]

        try:
            getattr(self, "do_" + action)(options)
        except maintenance.MaintenanceError as error:
            raise CommandError(str(error))
        except (OSError, ValueError, KeyError) as error:
            raise CommandError(f"{type(error).__name__}: {error}")

    def _write_queued(self, jobs):
        for job in jobs:
            self.stdout.write(
                f"Queued scraper job #{job['id']} (queued {job['queued_at'][:16]}) is left untouched. "
                "Keep the worker stopped until the corrections are verified; it will run when a worker next starts."
            )

    # ------------------------------------------------------------------ steps
    def do_check(self, options):
        problems = maintenance.check_stopped()

        if problems:
            raise CommandError("Not quiet: " + " ".join(problems))

        self.stdout.write("OK: no worker, running job, recent website activity or recent database write.")
        self._write_queued(maintenance.queued_jobs())

    def do_backup(self, options):
        path, manifest_path, manifest = maintenance.make_backup(options["dest_dir"])
        self.stdout.write(f"Backup: {path}")
        self.stdout.write(f"Manifest: {manifest_path}")
        self.stdout.write(f"Size: {manifest['size']} bytes   sha256: {manifest['sha256']}")
        self.stdout.write("Verified: integrity check ok, no foreign-key violations, identical to the live database.")

    def do_plan(self, options):
        plan = maintenance.build_plan_file(options["workbook"])
        Path(options["out"]).write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
        self.stdout.write("Preview (nothing was changed):")

        for kind in ALL_KINDS:
            self.stdout.write(f"  {kind}: {plan['summary'].get(kind, 0)}")

        excluded = {k: v for k, v in plan["summary"].items() if k.startswith("excluded_")}
        self.stdout.write(f"  exclusions: {excluded or 'none'}")
        self.stdout.write(f"Plan written to {options['out']}")

    def do_approve(self, options):
        plan = json.loads(Path(options["plan"]).read_text(encoding="utf-8-sig"))
        approval = maintenance.make_approval(plan, options["kinds"].split(","), options["approved_by"])
        Path(options["out"]).write_text(json.dumps(approval, indent=2), encoding="utf-8")
        self.stdout.write(f"Approval recorded for {approval['approved_counts']} by {approval['approved_by']}.")
        self.stdout.write(f"Approval written to {options['out']}")

    def do_apply(self, options):
        approval = json.loads(Path(options["approval"]).read_text(encoding="utf-8-sig"))
        report = maintenance.apply_approved(
            options["workbook"], approval, options["backup_manifest"],
            rollback_dir=options["rollback_dir"] or None,
            execute=options["execute"], confirm_stopped=options["confirm_stopped"],
            acknowledge_queued_jobs=options["acknowledge_queued_jobs"],
        )
        mode = "COMMITTED" if report["committed"] else "DRY RUN (nothing was changed)"
        self._write_queued(report["queued_jobs"])
        self.stdout.write(f"{mode}: {report['applied']} correction(s) {report['counts']}")
        self.stdout.write(f"Dashboard counts: {report['dashboard_before']} -> {report['dashboard_after']}")
        self.stdout.write(f"Rollback rehearsal: {report['rollback_rehearsal']}")
        self.stdout.write(f"Backup: {report['backup']}")

        if report["rollback_file"]:
            self.stdout.write(f"Rollback file: {report['rollback_file']}")

    def do_revert(self, options):
        result = maintenance.revert_applied(
            options["rollback_file"], execute=options["execute"], confirm_stopped=options["confirm_stopped"],
            acknowledge_queued_jobs=options["acknowledge_queued_jobs"],
        )
        self._write_queued(result["queued_jobs"])
        mode = "COMMITTED" if result["committed"] else "DRY RUN (nothing was changed)"
        self.stdout.write(f"{mode}: reverted {result['reverted']} change(s); original data restored exactly.")
