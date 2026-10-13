"""release_qa_run.py: init / checkpoint / validate for a release-QA run folder."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

import qa_support as qs

SCRIPT = qs.RELEASE_SCRIPT
R = qs.load_module("qa_release_run", SCRIPT)

COLUMNS = ["id", "layer", "surface", "role", "state_or_case", "risk", "oracle", "execution", "verification", "evidence", "defect", "notes"]
LAYOUT_DIRS = ["briefs", "evidence", "logs", "receipts", "screenshots"]
LAYOUT_FILES = ["manifest.json", "charter.md", "coverage.csv", "defects.md", "report.md", "checkpoints.jsonl"]
RISK = "checkout takes payment once"


def row(rid="C-01", risk=RISK, execution="executed", **kw):
    r = {"id": rid, "layer": "journey", "surface": "/checkout", "role": "customer", "state_or_case": "happy path", "risk": risk,
         "oracle": "order total equals basket total", "execution": execution, "verification": "evidence-reviewed",
         "evidence": "evidence/c-01.png", "defect": "", "notes": ""}
    r.update(kw)
    return r


class RunCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = self.tmp / "runs" / "example-shop"

    def cli(self, *args, env=None):
        return qs.run_script(SCRIPT, *args, env=env, cwd=self.tmp)

    def init(self, **overrides):
        args = {"--project": "Example Shop", "--target": "https://shop.example.com", "--environment": "staging",
                "--mode": "audit-only", "--output": str(self.run_dir)}
        args.update(overrides)
        flat = [x for kv in args.items() for x in kv]
        return self.cli("init", *flat)

    def manifest(self):
        return json.loads((self.run_dir / "manifest.json").read_text())

    def save_manifest(self, **changes):
        m = self.manifest()
        m.update(changes)
        (self.run_dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")

    def write_rows(self, rows, columns=COLUMNS):
        with (self.run_dir / "coverage.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    def finish(self, verdict="PASS", rows=None, top_risks=(RISK,), status="completed"):
        """Turn a freshly initialised run into one that passes --final."""
        self.save_manifest(status=status, top_risks=list(top_risks),
                           authority={"safe_test_mutations": "none", "sandbox_provider": "n/a", "money_cap": "none",
                                      "merge": "no", "deploy": "no", "production_writes": False})
        self.write_rows([row()] if rows is None else rows)
        (self.run_dir / "charter.md").write_text("# Charter\n\nGoal: check the shop before release.\n", encoding="utf-8")
        (self.run_dir / "report.md").write_text(f"# Release QA Report\n\nVerdict: {verdict}\n\nSummary text.\n", encoding="utf-8")

    def validate(self, *extra):
        return self.cli("validate", "--run", self.run_dir, *extra)


class Init(RunCase):
    def test_creates_the_documented_layout(self):
        r = self.init()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Path(r.stdout.strip()).resolve(), self.run_dir.resolve())
        for d in LAYOUT_DIRS:
            self.assertTrue((self.run_dir / d).is_dir(), d)
        for f in LAYOUT_FILES:
            self.assertTrue((self.run_dir / f).is_file(), f)
        self.assertEqual((self.run_dir / "checkpoints.jsonl").read_text(), "")
        header = (self.run_dir / "coverage.csv").read_text().splitlines()[0].split(",")
        self.assertEqual(header, COLUMNS)

    def test_manifest_content(self):
        self.init(**{"--repo": "none", "--tracking-issue": "SHOP-12"})
        m = self.manifest()
        self.assertEqual((m["project"], m["target"], m["environment"], m["mode"]), ("Example Shop", "https://shop.example.com", "staging", "audit-only"))
        self.assertEqual((m["status"], m["current_phase"], m["repo"], m["tracking_issue"]), ("initialized", "0-authority-and-baseline", "none", "SHOP-12"))
        self.assertEqual(m["schema_version"], 1)
        self.assertRegex(m["run_id"], r"^example-shop-\d{4}-\d{2}-\d{2}$")
        self.assertEqual(m["top_risks"], [])
        self.assertIs(m["authority"]["production_writes"], False)
        self.assertEqual({k for k, v in m["authority"].items() if v is None},
                         {"safe_test_mutations", "sandbox_provider", "money_cap", "merge", "deploy"})
        self.assertEqual(set(m["authority"]), R.AUTHORITY_FIELDS)

    def test_default_tracking_issue_and_repo_path_resolution(self):
        repo = self.tmp / "some-repo"
        repo.mkdir()
        self.init(**{"--repo": str(repo)})
        m = self.manifest()
        self.assertEqual(m["tracking_issue"], "draft-not-filed")
        self.assertEqual(Path(m["repo"]), repo.resolve())

    def test_refuses_to_overwrite_an_existing_run(self):
        self.assertEqual(self.init().returncode, 0)
        marker = self.run_dir / "evidence" / "keep.txt"
        marker.write_text("precious", encoding="utf-8")
        before = (self.run_dir / "manifest.json").read_text()
        r = self.init(**{"--project": "Something else"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing to overwrite", r.stderr)
        self.assertEqual(marker.read_text(), "precious")
        self.assertEqual((self.run_dir / "manifest.json").read_text(), before)

    def test_refuses_an_existing_empty_folder_too(self):
        self.run_dir.mkdir(parents=True)
        self.assertEqual(self.init().returncode, 1)

    def test_default_location_is_qa_runs_env_then_project_slug_and_date(self):
        root = self.tmp / "qa-runs-root"
        r = self.cli("init", "--project", "Example Shop!", "--target", "https://shop.example.com", "--environment", "staging",
                     "--mode", "audit-and-repair", env={"QA_RUNS": str(root)})
        self.assertEqual(r.returncode, 0, r.stderr)
        made = Path(r.stdout.strip())
        self.assertEqual(made.parent.resolve(), root.resolve())
        self.assertRegex(made.name, r"^example-shop-\d{4}-\d{2}-\d{2}$")
        self.assertTrue((made / "manifest.json").is_file())

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(self.cli("init", "--project", "x").returncode, 2)
        self.assertEqual(self.init(**{"--mode": "yolo"}).returncode, 2)
        self.assertEqual(self.cli("nonsense").returncode, 2)
        self.assertFalse(self.run_dir.exists())

    def test_slugify(self):
        self.assertEqual(R.slugify("  Example Shop & Co. "), "example-shop-co")
        self.assertEqual(R.slugify("???"), "release-qa")


class Checkpoint(RunCase):
    def test_updates_the_manifest_and_appends_one_event_per_call(self):
        self.init()
        for phase, status, nxt in (("1-inventory", "in_progress", "list routes"), ("1-inventory", "completed", "start phase 2"),
                                   ("2-execute", "blocked", "wait for credentials")):
            r = self.cli("checkpoint", "--run", self.run_dir, "--phase", phase, "--status", status, "--next", nxt)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"{phase} ({status})", r.stdout)
        events = [json.loads(l) for l in (self.run_dir / "checkpoints.jsonl").read_text().splitlines()]
        self.assertEqual([(e["phase"], e["status"], e["next_action"]) for e in events],
                         [("1-inventory", "in_progress", "list routes"), ("1-inventory", "completed", "start phase 2"),
                          ("2-execute", "blocked", "wait for credentials")])
        self.assertTrue(all(e["timestamp"] for e in events))
        m = self.manifest()
        self.assertEqual((m["status"], m["current_phase"], m["next_action"]), ("blocked", "2-execute", "wait for credentials"))
        self.assertGreaterEqual(m["updated_at"], m["created_at"])

    def test_invalid_status_is_a_usage_error_and_changes_nothing(self):
        self.init()
        r = self.cli("checkpoint", "--run", self.run_dir, "--phase", "p", "--status", "done", "--next", "n")
        self.assertEqual(r.returncode, 2)
        self.assertEqual((self.run_dir / "checkpoints.jsonl").read_text(), "")

    def test_missing_run_folder_exits_1(self):
        r = self.cli("checkpoint", "--run", self.tmp / "nowhere", "--phase", "p", "--status", "completed", "--next", "n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing manifest", r.stderr)


class BaseVerdict(unittest.TestCase):
    def test_plain_verdicts(self):
        for v in ("PASS", "PASS WITH CONDITIONS", "FAIL", "INCONCLUSIVE", "PREFLIGHT: no blocking findings", "PREFLIGHT: findings"):
            self.assertEqual(R.base_verdict(v), v)

    def test_bracketed_scope_note_is_stripped(self):
        self.assertEqual(R.base_verdict("PASS WITH CONDITIONS (staging only; payments mocked)"), "PASS WITH CONDITIONS")
        self.assertEqual(R.base_verdict("  FAIL (checkout blocked)  "), "FAIL")
        self.assertEqual(R.base_verdict("PREFLIGHT: findings (no browser available)"), "PREFLIGHT: findings")

    def test_anything_else_is_not_a_verdict(self):
        for v in (None, "", "PENDING", "pass", "PASSED", "PASS (a) (b) extra", "PASS: all good", "PREFLIGHT: ok", "PASS (unclosed", "(PASS)"):
            self.assertIsNone(R.base_verdict(v), v)


class Validate(RunCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.init().returncode, 0)

    def test_fresh_run_passes_the_non_final_check(self):
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("valid release-QA run", r.stdout)
        self.assertIn("0 coverage rows", r.stdout)

    def test_fresh_run_fails_the_final_check(self):
        r = self.validate("--final")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unresolved authority fields", r.stderr)
        self.assertIn("at least one coverage row", r.stderr)
        self.assertIn("unresolved template marker", r.stderr)

    def test_a_finished_run_validates(self):
        self.finish()
        r = self.validate("--final")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 coverage row)", r.stdout)

    def test_missing_files_and_manifest_are_reported(self):
        (self.run_dir / "report.md").unlink()
        (self.run_dir / "manifest.json").unlink()
        r = self.validate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing files: manifest.json, report.md", r.stderr)
        self.assertIn("missing manifest", r.stderr)

    def test_broken_manifest_json_is_an_error_not_a_crash(self):
        (self.run_dir / "manifest.json").write_text("{nope", encoding="utf-8")
        r = self.validate()
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_invalid_mode_and_empty_fields(self):
        self.save_manifest(mode="yolo", next_action="")
        r = self.validate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("invalid manifest mode", r.stderr)
        self.assertIn("manifest field is empty: next_action", r.stderr)

    def test_invalid_coverage_rows_are_reported_with_line_numbers(self):
        self.write_rows([row("C-01"), row("C-02", execution="done"), row("C-03", verification="trust-me"), row("")])
        r = self.validate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("coverage.csv:3 invalid execution: 'done'", r.stderr)
        self.assertIn("coverage.csv:4 invalid verification: 'trust-me'", r.stderr)
        self.assertIn("coverage.csv:5 missing id", r.stderr)

    def test_missing_coverage_columns(self):
        self.write_rows([{"id": "C-01", "execution": "executed"}], columns=["id", "execution"])
        r = self.validate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("coverage.csv missing columns", r.stderr)

    def test_final_requires_completed_or_blocked_status(self):
        self.finish(status="in_progress")
        r = self.validate("--final")
        self.assertEqual(r.returncode, 1)
        self.assertIn("status completed or blocked", r.stderr)
        self.finish(status="blocked", verdict="INCONCLUSIVE")
        self.assertEqual(self.validate("--final").returncode, 0)

    def test_final_rejects_planned_rows_executed_rows_without_evidence_and_blank_fields(self):
        self.finish(rows=[row("C-01"), row("C-02", execution="planned"), row("C-03", evidence=""), row("C-04", oracle="")])
        r = self.validate("--final")
        self.assertEqual(r.returncode, 1)
        self.assertIn("planned coverage remains: C-02", r.stderr)
        self.assertIn("executed row has no evidence", r.stderr)
        self.assertIn("missing oracle", r.stderr)

    def test_final_rejects_unresolved_template_markers(self):
        self.finish()
        (self.run_dir / "charter.md").write_text("Goal: <complete>\n", encoding="utf-8")
        r = self.validate("--final")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unresolved template marker in charter.md", r.stderr)

    def test_final_needs_a_top_risk_with_a_coverage_row(self):
        self.finish(top_risks=[])
        r = self.validate("--final")
        self.assertEqual(r.returncode, 1)
        self.assertIn("at least one top risk", r.stderr)
        self.finish(top_risks=[RISK, "refunds reach the right card"])
        r = self.validate("--final")
        self.assertEqual(r.returncode, 1)
        self.assertIn("top risk has no coverage row: refunds reach the right card", r.stderr)

    def test_verdict_must_be_present_and_valid(self):
        for text in ("# Report\n\nNo verdict line here.\n", "# Report\n\nVerdict: PENDING\n", "# Report\n\nVerdict: ALL GOOD\n"):
            with self.subTest(text):
                self.finish()
                (self.run_dir / "report.md").write_text(text, encoding="utf-8")
                r = self.validate("--final")
                self.assertEqual(r.returncode, 1)
                self.assertIn("invalid or missing report verdict", r.stderr)

    def test_verdict_with_a_bracketed_scope_note_is_accepted(self):
        self.finish(verdict="PASS WITH CONDITIONS (staging only; payment provider mocked)")
        r = self.validate("--final")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_preflight_verdict_lines_are_accepted(self):
        for v in ("PREFLIGHT: no blocking findings", "PREFLIGHT: findings"):
            with self.subTest(v):
                self.finish(verdict=v)
                self.assertEqual(self.validate("--final").returncode, 0)

    def test_passing_verdict_is_refused_when_a_top_risk_has_no_executed_coverage(self):
        passing = ("PASS", "PASS WITH CONDITIONS", "PASS (scoped)", "PREFLIGHT: no blocking findings")
        for execution in ("blocked", "not_executed", "not_reachable", "not_applicable"):
            for verdict in passing:
                with self.subTest(execution=execution, verdict=verdict):
                    self.finish(verdict=verdict, rows=[row(execution=execution, evidence="")])
                    r = self.validate("--final")
                    self.assertEqual(r.returncode, 1)
                    self.assertIn("passing verdict is invalid while top risks lack executed coverage: " + RISK, r.stderr)

    def test_non_passing_verdicts_are_allowed_without_executed_coverage(self):
        for verdict in ("FAIL", "INCONCLUSIVE", "FAIL (checkout blocked)", "PREFLIGHT: findings"):
            with self.subTest(verdict):
                self.finish(verdict=verdict, rows=[row(execution="blocked", evidence="")])
                r = self.validate("--final")
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_one_executed_row_is_enough_for_the_risk(self):
        self.finish(rows=[row("C-01", execution="blocked", evidence=""), row("C-02", execution="executed")])
        self.assertEqual(self.validate("--final").returncode, 0)

    def test_malformed_manifest_values_report_errors_instead_of_crashing(self):
        for label, change, extra in (("authority null", {"authority": None}, ()), ("authority null, final", {"authority": None}, ("--final",)),
                                     ("authority list", {"authority": []}, ()), ("authority list, final", {"authority": []}, ("--final",)),
                                     ("top_risks string", {"top_risks": "checkout"}, ("--final",))):
            with self.subTest(label):
                self.finish()
                self.save_manifest(**change)
                r = self.validate(*extra)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertNotIn("Traceback", r.stderr)

    def test_manifest_that_is_not_an_object_reports_errors_instead_of_crashing(self):
        (self.run_dir / "manifest.json").write_text("[]", encoding="utf-8")
        r = self.validate()
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_wrong_typed_mode_and_status_are_errors_not_crashes(self):
        for field, value in (("mode", []), ("mode", {}), ("mode", 7), ("status", {}), ("status", ["completed"]), ("status", {"a": 1}), ("status", 3)):
            for extra in ((), ("--final",)):
                with self.subTest(field=field, value=value, final=bool(extra)):
                    self.finish()
                    self.save_manifest(**{field: value})
                    r = self.validate(*extra)
                    self.assertEqual(r.returncode, 1, r.stdout)
                    self.assertTrue(r.stderr.startswith("ERROR:"), r.stderr)
                    self.assertNotIn("Traceback", r.stderr)

    def test_oversized_csv_field_is_an_error_not_a_crash(self):
        (self.run_dir / "coverage.csv").write_text(",".join(COLUMNS) + "\n" + "C-01,journey,/x,customer,case,risk,oracle,executed,,ev,," + "n" * 300_000 + "\n",
                                                  encoding="utf-8")
        for extra in ((), ("--final",)):
            r = self.validate(*extra)
            self.assertEqual(r.returncode, 1)
            self.assertIn("coverage.csv cannot be read", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_binary_files_are_errors_not_crashes(self):
        self.finish()
        for name in ("coverage.csv", "report.md", "charter.md", "manifest.json"):
            with self.subTest(name):
                self.finish()
                (self.run_dir / name).write_bytes(b"\xff\xfe\x00 not utf-8 \xc3\x28")
                r = self.validate("--final")
                self.assertEqual(r.returncode, 1)
                self.assertNotIn("Traceback", r.stderr)

    def test_rows_with_extra_or_missing_cells_do_not_crash(self):
        self.finish()
        header = ",".join(COLUMNS)
        (self.run_dir / "coverage.csv").write_text(f"{header}\nC-01,journey\nC-02,journey,/x,r,c,{RISK},o,executed,,ev,,n,extra,cells\n", encoding="utf-8")
        r = self.validate("--final")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_exactly_one_verdict_line_is_required(self):
        for text in ("Verdict: FAIL\n\nLater.\n\nVerdict: PASS\n", "Verdict: PASS\nVerdict: PASS\n", "Verdict: INCONCLUSIVE\n\nVerdict: FAIL (scope)\n"):
            with self.subTest(text):
                self.finish()
                (self.run_dir / "report.md").write_text("# Report\n\n" + text, encoding="utf-8")
                r = self.validate("--final")
                self.assertEqual(r.returncode, 1)
                self.assertIn("2 'Verdict:' lines; exactly one is allowed", r.stderr)
        self.finish()
        (self.run_dir / "report.md").write_text("# Report\n\nThe verdict: below is discussed.\n\nVerdict: PASS\n", encoding="utf-8")
        self.assertEqual(self.validate("--final").returncode, 0)   # prose that merely mentions a verdict is not a second line

    def test_a_top_risk_that_is_not_text_does_not_crash(self):
        self.finish()
        self.save_manifest(top_risks=[RISK, {"risk": "object"}, 7])
        r = self.validate("--final")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
