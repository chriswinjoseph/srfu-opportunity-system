"""Guarded maintenance procedure for approved data corrections."""

import json
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from intake import maintenance
from intake.corrections import ALL_KINDS, build_plan
from intake.maintenance import MaintenanceError
from intake.models import ContactSource, FieldProvenance, OrganisationSource
from intake.worker import beat
from outreach.models import Bank, Contact, Opportunity

from .test_corrections import LegacyData, NOTE


def snapshot():
    return maintenance.fingerprint(maintenance.live_connection())


def dump_copy(source, target, timeout=None):
    """Stand-in for the online backup inside the test transaction on the in-memory test database."""
    target.executescript("\n".join(source.iterdump()))


class RegionDuplicatePlanTests(LegacyData):
    """The kind that clears a Region still holding the same state code as State."""

    def setUp(self):
        super().setUp()
        # An Echo bank whose State was filled later (for example by a scraper), Region untouched.
        self.echo, _ = self.legacy_bank("Echo Community Bank", "QLD", "O_5", contact_email="echo@example.test")
        Bank.objects.filter(pk=self.echo.pk).update(state="QLD")

    def region_fixes(self, plan):
        return [f for f in plan.fixes if f["kind"] == "region_duplicate_of_state"]

    def region_exclusions(self, plan):
        return [e for e in plan.exclusions if e["kind"] == "region_duplicate_of_state"]

    def test_confirmed_leftover_code_is_proposed_and_state_is_preserved(self):
        plan = build_plan(self.data, "client.xlsx")

        fixes = self.region_fixes(plan)
        self.assertEqual([f["organisation"] for f in fixes], ["Echo Community Bank"])
        self.assertEqual((fixes[0]["old"], fixes[0]["new"], fixes[0]["state"]), ("QLD", "", "QLD"))

    def test_uncertain_cases_are_excluded_with_a_reason(self):
        cases = (
            ("edited after import", lambda: Bank.objects.filter(pk=self.echo.pk).update(
                last_updated=timezone.now() + timedelta(hours=1)), "edited after import"),
            ("a source supplied the Region", lambda: FieldProvenance.objects.create(
                content_type=self.bank_ct, object_id=self.echo.pk, field="region", origin="scraper",
                source_key="x", collected_at=timezone.now(), last_checked_at=timezone.now()), "supplied the Region"),
            ("state differs from the workbook", lambda: Bank.objects.filter(pk=self.echo.pk).update(state="NSW"),
             "differs from the workbook"),
        )

        for label, change, reason in cases:
            with self.subTest(label):
                Bank.objects.filter(pk=self.echo.pk).update(state="QLD", last_updated=self.echo.last_updated)
                FieldProvenance.objects.filter(object_id=self.echo.pk, field="region").delete()
                change()

                plan = build_plan(self.data, "client.xlsx")

                self.assertEqual(self.region_fixes(plan), [])
                self.assertTrue(any(reason in e["reason"] for e in self.region_exclusions(plan)), label)

    def test_a_place_name_is_never_treated_as_a_leftover_code(self):
        Bank.objects.filter(pk=self.echo.pk).update(region="Queensland")

        plan = build_plan(self.data, "client.xlsx")

        self.assertEqual(self.region_fixes(plan), [])

    def test_archived_banks_are_never_changed(self):
        Bank.objects.filter(pk=self.echo.pk).update(is_archived=True)

        plan = build_plan(self.data, "client.xlsx")

        self.assertEqual(self.region_fixes(plan), [])
        self.assertTrue(any(e["kind"] == "archived" for e in plan.exclusions))
        self.assertFalse([f for f in plan.fixes if f.get("bank_id") == self.echo.pk])


class MaintenanceBase(LegacyData):
    def setUp(self):
        super().setUp()
        patcher = patch("intake.maintenance._copy_database", side_effect=dump_copy)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.echo, _ = self.legacy_bank("Echo Community Bank", "QLD", "O_5", contact_email="echo@example.test")
        Bank.objects.filter(pk=self.echo.pk).update(state="QLD")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.workbook_path = self.tmp / "client.xlsx"
        self.workbook_path.write_bytes(self.data)

    def backup(self):
        _path, manifest_path, _manifest = maintenance.make_backup(self.tmp / "backups")

        return manifest_path

    def approval(self, kinds):
        plan = maintenance.build_plan_file(self.workbook_path)

        return maintenance.make_approval(plan, kinds, "BA Tester")

    def apply(self, kinds, execute=False, **kwargs):
        approval = self.approval(kinds)
        manifest = self.backup()

        return maintenance.apply_approved(
            self.workbook_path, approval, manifest, execute=execute, confirm_stopped=True, **kwargs
        )


class RealBackupCopyTests(LegacyData):
    def test_online_backup_copies_a_file_database_exactly(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            source = sqlite3.connect(str(Path(tmp) / "live.sqlite3"))
            source.execute("create table t (id integer primary key, name text)")
            source.executemany("insert into t (name) values (?)", [("a",), ("b",)])
            source.commit()
            target = sqlite3.connect(str(Path(tmp) / "copy.sqlite3"))
            maintenance._copy_database(source, target)
            target.close()

            check = sqlite3.connect(str(Path(tmp) / "copy.sqlite3"))
            self.assertEqual(maintenance.fingerprint(check), maintenance.fingerprint(source))
            check.close()
            source.close()

    def test_a_locked_database_gives_up_with_a_clear_message(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            source = sqlite3.connect(str(Path(tmp) / "live.sqlite3"), isolation_level=None)
            source.execute("create table t (id integer)")
            blocker = sqlite3.connect(str(Path(tmp) / "live.sqlite3"), isolation_level=None)
            blocker.execute("begin exclusive")
            target = sqlite3.connect(str(Path(tmp) / "copy.sqlite3"))

            with self.assertRaisesMessage(MaintenanceError, "stayed locked"):
                maintenance._copy_database(source, target, timeout=1)

            blocker.execute("rollback")
            for conn in (source, blocker, target):
                conn.close()


class BackupTests(MaintenanceBase):
    def test_backup_is_verified_and_outside_the_repository(self):
        path, manifest_path, manifest = maintenance.make_backup(self.tmp / "backups")

        self.assertTrue(path.is_file())
        self.assertEqual(manifest["integrity_check"], "ok")
        self.assertNotIn(Path(settings.BASE_DIR).resolve(), path.resolve().parents)
        self.assertEqual(manifest["fingerprint"], snapshot())
        maintenance.verify_manifest(manifest_path)

    def test_backup_inside_the_repository_is_refused_and_not_created(self):
        target = Path(settings.BASE_DIR) / "must_not_exist_backup_dir"

        with self.assertRaisesMessage(MaintenanceError, "outside the repository"):
            maintenance.make_backup(target)

        self.assertFalse(target.exists())

    def test_old_or_stale_backups_are_refused(self):
        manifest = self.backup()

        with self.assertRaisesMessage(MaintenanceError, "older than"):
            maintenance.verify_manifest(manifest, now=timezone.now() + timedelta(minutes=61))

        Bank.objects.filter(pk=self.echo.pk).update(public_phone="03 9555 1234")

        with self.assertRaisesMessage(MaintenanceError, "intervening activity"):
            maintenance.verify_manifest(manifest)

    def test_a_tampered_backup_is_refused(self):
        path, manifest_path, _ = maintenance.make_backup(self.tmp / "backups")
        manifest = json.loads(manifest_path.read_text())
        manifest["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))

        with self.assertRaisesMessage(MaintenanceError, "changed since its manifest"):
            maintenance.verify_manifest(manifest_path)


class StoppedChecks(MaintenanceBase):
    def test_apply_needs_the_explicit_confirmation(self):
        approval = self.approval(["unspecified_name"])
        manifest = self.backup()

        with self.assertRaisesMessage(MaintenanceError, "--confirm-stopped"):
            maintenance.apply_approved(self.workbook_path, approval, manifest, execute=True)

    def test_a_live_worker_a_running_job_or_recent_web_activity_blocks_it(self):
        approval = self.approval(["unspecified_name"])
        manifest = self.backup()
        before = snapshot()

        beat("worker-1")
        with self.assertRaisesMessage(MaintenanceError, "worker"):
            maintenance.apply_approved(self.workbook_path, approval, manifest, execute=True, confirm_stopped=True)

        from intake.models import WorkerHeartbeat, IntakeRun
        WorkerHeartbeat.objects.all().delete()

        IntakeRun.objects.create(kind="scraper", status="running", source_key="scraper")
        with self.assertRaisesMessage(MaintenanceError, "running"):
            maintenance.apply_approved(self.workbook_path, approval, manifest, execute=True, confirm_stopped=True)
        IntakeRun.objects.all().delete()

        Session.objects.create(
            session_key="abc", session_data="",
            expire_date=timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE),
        )
        with self.assertRaisesMessage(MaintenanceError, "active on the website"):
            maintenance.apply_approved(self.workbook_path, approval, manifest, execute=True, confirm_stopped=True)

        Session.objects.all().delete()
        # Every refusal happened before anything was written.
        self.assertEqual(Bank.objects.get(pk=self.alpha.pk).region, "VIC")
        self.assertEqual(Contact.objects.get(email="alpha@example.test").contact_name, "(unspecified)")
        self.assertEqual(snapshot()["outreach_bank"], before["outreach_bank"])


class ApplyTests(MaintenanceBase):
    def test_dry_run_changes_nothing(self):
        before = snapshot()

        report = self.apply(list(ALL_KINDS))

        self.assertFalse(report["committed"])
        self.assertEqual(snapshot(), before)
        self.assertEqual(report["rollback_rehearsal"], "restored the original data exactly")
        self.assertIsNone(report["rollback_file"])

    def test_execute_applies_only_the_approved_kinds(self):
        report = self.apply(["state_in_region", "unspecified_name"], execute=True)

        self.assertTrue(report["committed"])
        self.assertEqual(Bank.objects.get(pk=self.alpha.pk).state, "VIC")
        self.assertEqual(Bank.objects.get(pk=self.alpha.pk).region, "")
        self.assertEqual(Contact.objects.get(email="alpha@example.test").contact_name, "")
        # Not approved, so untouched:
        self.assertEqual(Bank.objects.get(pk=self.bravo.pk).contact_status, "contacted")
        self.assertEqual(Bank.objects.get(pk=self.echo.pk).region, "QLD")
        self.assertEqual(OrganisationSource.objects.count(), 0)
        self.assertEqual(ContactSource.objects.count(), 0)
        rollback_file = Path(report["rollback_file"])
        self.assertTrue(rollback_file.is_file())
        self.assertNotIn(Path(settings.BASE_DIR).resolve(), rollback_file.resolve().parents)

    def test_region_duplicate_and_status_corrections_with_dashboard_counts(self):
        report = self.apply(["region_duplicate_of_state", "contact_status"], execute=True)

        self.assertEqual(Bank.objects.get(pk=self.echo.pk).region, "")
        self.assertEqual(Bank.objects.get(pk=self.echo.pk).state, "QLD")
        self.assertEqual(Bank.objects.get(pk=self.bravo.pk).contact_status, "not_yet_contacted")
        self.assertEqual(report["dashboard_after"]["contacted"], report["dashboard_before"]["contacted"] - 1)
        self.assertEqual(report["dashboard_after"]["not_yet_contacted"], report["dashboard_before"]["not_yet_contacted"] + 1)
        # Later successful outreach (Delta, an email was sent) is not reset.
        self.assertEqual(Bank.objects.get(pk=self.delta.pk).contact_status, "contacted")

    def test_provenance_rows_are_created_and_counted(self):
        self.apply(["source_provenance", "contact_provenance"], execute=True)

        self.assertEqual(OrganisationSource.objects.count(), 5)     # alpha, bravo, charlie, delta, echo
        self.assertEqual(ContactSource.objects.count(), 6)

    def test_approval_must_be_explicit_and_match_the_plan(self):
        plan = maintenance.build_plan_file(self.workbook_path)

        for kinds, who, text in (
            ([], "BA", "explicitly"),
            (["everything"], "BA", "explicitly"),
            (["state_in_region"], "  ", "who approved"),
            (["bogus"], "BA", "explicitly"),
        ):
            with self.subTest(kinds=kinds, who=who):
                with self.assertRaisesMessage(MaintenanceError, text):
                    maintenance.make_approval(plan, kinds, who)

        approval = maintenance.make_approval(plan, ["unspecified_name"], "BA Tester")
        manifest = self.backup()
        tampered = {**approval, "approved_kinds": ["unspecified_name", "contact_status"]}

        with self.assertRaisesMessage(MaintenanceError, "plan changed"):
            maintenance.apply_approved(self.workbook_path, tampered, manifest, execute=True, confirm_stopped=True)

        wrong_book = {**approval, "workbook_sha256": "f" * 64}

        with self.assertRaisesMessage(MaintenanceError, "not the one that was approved"):
            maintenance.apply_approved(self.workbook_path, wrong_book, manifest, execute=True, confirm_stopped=True)

        self.assertEqual(Contact.objects.get(email="alpha@example.test").contact_name, "(unspecified)")

    def test_activity_after_approval_stops_the_run(self):
        approval = self.approval(["state_in_region"])
        # Someone edits an organisation after the approval; a fresh backup is taken afterwards.
        Bank.objects.filter(pk=self.alpha.pk).update(region="Central Highlands")
        manifest = self.backup()

        with self.assertRaisesMessage(MaintenanceError, "plan changed"):
            maintenance.apply_approved(self.workbook_path, approval, manifest, execute=True, confirm_stopped=True)

        self.assertEqual(Bank.objects.get(pk=self.alpha.pk).region, "Central Highlands")

    def test_one_item_that_cannot_apply_stops_everything(self):
        before = snapshot()
        approval = self.approval(["state_in_region"])
        manifest = self.backup()
        skipped = [{"kind": "state_in_region", "skipped_because": "the record changed since the preview"}]

        with patch("intake.maintenance.apply_plan", return_value=([], skipped, [])):
            with self.assertRaisesMessage(MaintenanceError, "Nothing was changed"):
                maintenance.apply_approved(self.workbook_path, approval, manifest, execute=True, confirm_stopped=True)

        self.assertEqual(snapshot(), before)

    def test_a_failed_rollback_rehearsal_blocks_the_commit(self):
        before = snapshot()
        approval = self.approval(["state_in_region", "contact_status"])
        manifest = self.backup()

        with patch("intake.maintenance.revert_plan"):             # rollback that restores nothing
            with self.assertRaisesMessage(MaintenanceError, "rollback rehearsal"):
                maintenance.apply_approved(self.workbook_path, approval, manifest, execute=True, confirm_stopped=True)

        self.assertEqual(snapshot(), before)
        self.assertEqual(Bank.objects.get(pk=self.alpha.pk).region, "VIC")

    def test_archived_banks_and_everything_else_stay_untouched(self):
        Bank.objects.filter(pk=self.charlie.pk).update(is_archived=True)
        before = snapshot()

        self.apply(list(ALL_KINDS), execute=True)

        after = snapshot()
        archived = Bank.objects.get(pk=self.charlie.pk)
        self.assertTrue(archived.is_archived)
        self.assertEqual((archived.state, archived.region), ("", "WA"))
        for table in ("accounts_user", "outreach_emaildraft", "outreach_emailtemplate", "accounts_useractivity"):
            self.assertEqual(before[table], after[table], table)

    def test_revert_restores_the_original_data_and_refuses_after_new_activity(self):
        before = snapshot()
        report = self.apply(list(ALL_KINDS), execute=True)
        self.assertNotEqual(snapshot(), before)

        Bank.objects.filter(pk=self.echo.pk).update(public_phone="03 9555 9999")
        with self.assertRaisesMessage(MaintenanceError, "Restore the verified backup"):
            maintenance.revert_applied(report["rollback_file"], execute=True, confirm_stopped=True)
        Bank.objects.filter(pk=self.echo.pk).update(public_phone="")

        dry = maintenance.revert_applied(report["rollback_file"], execute=False, confirm_stopped=True)
        self.assertFalse(dry["committed"])
        self.assertNotEqual(snapshot(), before)

        maintenance.revert_applied(report["rollback_file"], execute=True, confirm_stopped=True)
        self.assertEqual(snapshot(), before)


class CommandTests(MaintenanceBase):
    def run_command(self, *args):
        out = StringIO()
        call_command("corrections_maintenance", *args, stdout=out)

        return out.getvalue()

    def test_full_procedure_through_the_command(self):
        out = self.run_command("check")
        self.assertIn("OK", out)

        out = self.run_command("backup", "--dest-dir", str(self.tmp / "backups"))
        manifest = out.split("Manifest: ")[1].splitlines()[0]
        self.assertIn("Verified", out)

        plan_file, approval_file = str(self.tmp / "plan.json"), str(self.tmp / "approval.json")
        out = self.run_command("plan", "--workbook", str(self.workbook_path), "--out", plan_file)
        self.assertIn("Preview (nothing was changed)", out)
        self.run_command("approve", "--plan", plan_file, "--kinds", "unspecified_name,state_in_region",
                         "--approved-by", "BA Tester", "--out", approval_file)

        before = snapshot()
        out = self.run_command("apply", "--workbook", str(self.workbook_path), "--approval", approval_file,
                               "--backup-manifest", manifest, "--confirm-stopped")
        self.assertIn("DRY RUN (nothing was changed)", out)
        self.assertEqual(snapshot(), before)

        out = self.run_command("apply", "--workbook", str(self.workbook_path), "--approval", approval_file,
                               "--backup-manifest", manifest, "--confirm-stopped", "--execute")
        self.assertIn("COMMITTED", out)
        self.assertEqual(Bank.objects.get(pk=self.alpha.pk).region, "")

        rollback = out.split("Rollback file: ")[1].splitlines()[0]
        out = self.run_command("revert", "--rollback-file", rollback, "--confirm-stopped", "--execute")
        self.assertIn("original data restored exactly", out)
        self.assertEqual(snapshot(), before)

    def test_json_files_written_with_a_byte_order_mark_are_accepted(self):
        manifest = self.backup()
        approval = self.tmp / "approval.json"
        approval.write_bytes(b"\xef\xbb\xbf" + json.dumps(self.approval(["unspecified_name"])).encode())

        out = self.run_command("apply", "--workbook", str(self.workbook_path), "--approval", str(approval),
                               "--backup-manifest", str(manifest), "--confirm-stopped")

        self.assertIn("DRY RUN", out)

    def test_a_tampered_approval_without_a_byte_order_mark_is_rejected_for_the_mismatch(self):
        manifest = self.backup()
        approval = self.approval(["unspecified_name", "contact_status"])
        tampered = {**approval, "approved_kinds": ["unspecified_name"]}       # a kind quietly removed
        path = self.tmp / "approval_tampered.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")               # valid UTF-8, no BOM
        self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        before = snapshot()

        with self.assertRaises(CommandError) as raised:
            self.run_command("apply", "--workbook", str(self.workbook_path), "--approval", str(path),
                             "--backup-manifest", str(manifest), "--confirm-stopped", "--execute")

        message = str(raised.exception)
        self.assertIn("plan changed since it was approved", message)
        self.assertNotIn("JSONDecodeError", message)
        self.assertEqual(snapshot(), before)

    def test_queued_scraper_jobs_must_be_acknowledged_and_are_left_untouched(self):
        from intake.models import IntakeRun

        job = IntakeRun.objects.create(kind="scraper", status="queued", source_key="scraper",
                                       options={"adapters": ["bendigo_community_banks"]})
        approval = self.approval(["unspecified_name"])
        manifest = self.backup()
        self.assertEqual([j["id"] for j in maintenance.queued_jobs()], [job.pk])

        with self.assertRaisesMessage(MaintenanceError, "--acknowledge-queued-jobs"):
            maintenance.apply_approved(self.workbook_path, approval, manifest, execute=True, confirm_stopped=True)

        self.assertEqual(Contact.objects.get(email="alpha@example.test").contact_name, "(unspecified)")

        report = maintenance.apply_approved(self.workbook_path, approval, manifest, execute=True,
                                            confirm_stopped=True, acknowledge_queued_jobs=True)

        self.assertEqual([j["id"] for j in report["queued_jobs"]], [job.pk])
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts, job.started_at), ("queued", 0, None))   # not started, not changed
        self.assertIn("Queued scraper job", self.run_command("check"))

        with self.assertRaisesMessage(MaintenanceError, "--acknowledge-queued-jobs"):
            maintenance.revert_applied(report["rollback_file"], execute=True, confirm_stopped=True)

    def test_the_command_refuses_without_confirmation(self):
        manifest = self.backup()
        approval = self.tmp / "approval.json"
        approval.write_text(json.dumps(self.approval(["unspecified_name"])))

        with self.assertRaisesMessage(CommandError, "--confirm-stopped"):
            self.run_command("apply", "--workbook", str(self.workbook_path), "--approval", str(approval),
                             "--backup-manifest", str(manifest), "--execute")

    def test_the_existing_command_still_refuses_the_project_database(self):
        from intake.management.commands.apply_data_corrections import _is_project_database

        with patch.dict(settings.DATABASES["default"], {"NAME": Path(settings.BASE_DIR) / "db.sqlite3"}):
            self.assertTrue(_is_project_database())
