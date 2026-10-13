"""worker/install.sh and worker/runner.sh against a stubbed fake worker Mac."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import time
import unittest
from pathlib import Path

from stubs import ROOT, FakeMac, rows, tree

INSTALL = ROOT / "worker/install.sh"
RUNNER = ROOT / "worker/runner.sh"
LABEL = "local.qa-worker.runner"


def run_install(mac: FakeMac, *args: str, ack: bool = True, **env: str) -> subprocess.CompletedProcess:
    # Most tests are about what --apply does once the operator has acknowledged unsandboxed execution.
    if ack and "--apply" in args and "--accept-unsandboxed" not in args:
        args += ("--accept-unsandboxed",)
    return subprocess.run(["/bin/bash", str(INSTALL), *args], env=mac.env(**env),
                          capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)


def run_runner(mac: FakeMac, *args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/bash", str(RUNNER), *args], env=mac.env(QA_WORKER_BASE=str(mac.base), **env),
                          capture_output=True, text=True, timeout=60)


def authorise_lead(mac: FakeMac) -> None:
    ssh = mac.home / ".ssh"
    ssh.mkdir(exist_ok=True)
    (ssh / "authorized_keys").write_text("ssh-ed25519 AAAAexample lead\n")


class CheckOnlyTest(unittest.TestCase):
    def setUp(self):
        self.mac = FakeMac()

    def tearDown(self):
        self.mac.cleanup()

    def test_check_only_is_read_only_and_reports(self):
        before = tree(self.mac.home)
        r = run_install(self.mac, "--json")
        self.assertEqual(r.returncode, 1, r.stderr)
        res = rows(r.stdout)
        self.assertEqual(tree(self.mac.home), before, "check-only mode must not write anything")
        self.assertEqual(res["macos"]["status"], "PASS")
        self.assertEqual(res["user"]["status"], "PASS")
        self.assertEqual(res["autologin"]["status"], "PASS")
        self.assertEqual(res["gui_session"]["status"], "PASS")
        self.assertEqual(res["chatgpt_app"]["status"], "PASS")
        self.assertIn("ChatGPT.app 1.2.3", res["chatgpt_app"]["detail"])
        self.assertEqual(res["codex_cli"]["detail"], "codex-cli 9.9.9")
        self.assertEqual(res["computer_use"]["status"], "PASS")
        self.assertNotIn("/somewhere", res["computer_use"]["detail"])
        self.assertEqual(res["model_catalog"]["detail"], "jobs will run model-alpha (pattern: none set)")
        self.assertEqual(res["runner"]["status"], "FAIL")
        self.assertEqual(res["launchagent"]["status"], "FAIL")
        self.assertEqual(res["lead_key"]["status"], "FAIL")
        self.assertEqual(res["gui_selfcheck"]["status"], "MANUAL")
        for row in res.values():
            self.assertIn(row["status"], ("PASS", "FAIL", "WARN", "MANUAL"))
            if row["status"] != "PASS":
                self.assertTrue(row["fix"], f"{row['id']} needs a fix")
        self.assertNotIn("exec", self.mac.calls().replace("codex-cli", ""))

    def test_table_output(self):
        r = run_install(self.mac)
        self.assertIn("STATUS  REQUIREMENT", r.stdout)
        self.assertIn("fix: worker/install.sh --apply", r.stdout)

    def test_failures_and_warnings(self):
        self.mac.flag("no_autologin")
        self.mac.flag("plugin_missing")
        self.mac.flag("logged_out")
        r = run_install(self.mac, "--json", FAKE_SLEEP="10", FAKE_IDLE="1200", FAKE_UID="501",
                        FAKE_GROUPS="staff admin", FAKE_CONSOLE="loginwindow", FAKE_MACOS="13.6")
        res = rows(r.stdout)
        self.assertEqual(res["macos"]["status"], "FAIL")
        self.assertEqual(res["user"]["status"], "WARN")
        self.assertEqual(res["autologin"]["status"], "FAIL")
        self.assertEqual(res["gui_session"]["status"], "FAIL")
        self.assertEqual(res["sleep"]["status"], "FAIL")
        self.assertIn("sudo pmset -a sleep 0 displaysleep 0", res["sleep"]["fix"])
        self.assertEqual(res["screensaver"]["status"], "WARN")
        self.assertEqual(res["computer_use"]["status"], "FAIL")
        self.assertIn("plugin add computer-use@openai-bundled", res["computer_use"]["fix"])
        self.assertEqual(res["codex_login"]["status"], "FAIL")

    def test_computer_use_variants(self):
        self.mac.flag("plugin_disabled")
        res = rows(run_install(self.mac, "--json").stdout)
        self.assertEqual(res["computer_use"]["status"], "FAIL")
        self.assertIn("installed, disabled", res["computer_use"]["detail"])
        self.mac.flag("plugin_disabled", False)
        self.mac.flag("plugin_unified")
        res = rows(run_install(self.mac, "--json").stdout)
        self.assertEqual(res["computer_use"]["status"], "PASS")
        self.assertIn("unified-computer-use@openai-bundled", res["computer_use"]["detail"])

    def test_pattern_matching_nothing_model_row_fails(self):
        self.mac.base.mkdir(parents=True)
        (self.mac.base / "model-pattern").write_text("nomatch-*\n")
        before = tree(self.mac.home)
        res = rows(run_install(self.mac, "--json").stdout)
        self.assertEqual(res["model_catalog"]["status"], "FAIL")
        self.assertIn("pattern: nomatch-*", res["model_catalog"]["detail"])
        self.assertEqual(tree(self.mac.home), before, "check mode must not write the pattern file or anything else")

    def test_model_row_shows_pattern_and_never_creates_the_file(self):
        before = tree(self.mac.home)
        res = rows(run_install(self.mac, "--json", QA_WORKER_MODEL="model-b*").stdout)
        self.assertEqual(res["model_catalog"]["status"], "PASS")
        self.assertEqual(res["model_catalog"]["detail"], "jobs will run model-beta (pattern: model-b*)")
        self.assertEqual(tree(self.mac.home), before)
        self.assertFalse((self.mac.base / "model-pattern").exists())

    def test_over_ssh_gui_rows_are_manual(self):
        r = run_install(self.mac, "--json", SSH_CONNECTION="1.2.3.4 5 6.7.8.9 22")
        data = json.loads(r.stdout)
        self.assertTrue(data["over_ssh"])
        res = rows(r.stdout)
        self.assertEqual(res["remote_login"]["status"], "PASS")
        for k in ("gui_selfcheck", "gui_codex", "gui_screen", "gui_keychain"):
            self.assertEqual(res[k]["status"], "MANUAL")

    def test_legacy_cli_path_found(self):
        mac = FakeMac(legacy_cli_path=True)
        try:
            r = run_install(mac, "--json")
            self.assertEqual(rows(r.stdout)["codex_cli"]["status"], "PASS")
        finally:
            mac.cleanup()

    def test_missing_app(self):
        r = run_install(self.mac, "--json", QA_WORKER_APP_PATH="/nonexistent/ChatGPT.app")
        res = rows(r.stdout)
        self.assertEqual(res["chatgpt_app"]["status"], "FAIL")
        self.assertEqual(res["codex_cli"]["status"], "FAIL")
        self.assertEqual(res["computer_use"]["status"], "MANUAL")


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.mac = FakeMac()
        authorise_lead(self.mac)

    def tearDown(self):
        self.mac.cleanup()

    def test_apply_then_all_pass(self):
        run_runner(self.mac, "--selfcheck")  # what the LaunchAgent does in the GUI session
        r = run_install(self.mac, "--apply", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        res = rows(r.stdout)
        bad = {k: v for k, v in res.items() if v["status"] in ("FAIL", "MANUAL")}
        self.assertEqual(bad, {})
        base = self.mac.base
        self.assertTrue((base / "runner.sh").is_file())
        plist = (self.mac.home / f"Library/LaunchAgents/{LABEL}.plist").read_text()
        self.assertIn(f"{base}/runner.sh", plist)
        self.assertIn(f"<string>{LABEL}</string>", plist)
        self.assertNotIn("__", plist)
        lint = subprocess.run(["plutil", "-lint", str(self.mac.home / f"Library/LaunchAgents/{LABEL}.plist")],
                              capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout)
        self.assertTrue((base / "runtime-instructions.md").is_file())
        self.assertIn(f"launchctl bootstrap gui/502 {self.mac.home}/Library/LaunchAgents/{LABEL}.plist", self.mac.calls())
        self.assertIn("Manual steps", r.stderr)
        self.assertEqual(res["gui_codex"]["status"], "PASS")
        self.assertIn("model-alpha (pattern: none set)", res["gui_codex"]["detail"])

    def test_apply_is_idempotent_and_keeps_edited_instructions(self):
        run_install(self.mac, "--apply")
        n_boot = self.mac.calls().count("bootstrap")
        instr = self.mac.base / "runtime-instructions.md"
        instr.write_text(instr.read_text() + "\nLocal rule added by the operator.\n")
        edited = instr.read_text()
        run_install(self.mac, "--apply")
        self.assertEqual(self.mac.calls().count("bootstrap"), n_boot, "unchanged install must not reload the agent")
        self.assertEqual(instr.read_text(), edited)
        # The template has not changed, so the copy for merging is the template itself.
        new = self.mac.base / "runtime-instructions.new.md"
        self.assertEqual(new.read_text(), (ROOT / "worker/runtime-instructions.template.md").read_text())

    def test_unedited_instructions_follow_template_updates(self):
        run_install(self.mac, "--apply")
        instr = self.mac.base / "runtime-instructions.md"
        stamp = self.mac.base / ".runtime-instructions.sha256"
        # Simulate an older template version that was installed unedited.
        instr.write_text("old template text\n")
        stamp.write_text(subprocess.run(["shasum", "-a", "256", str(instr)], capture_output=True, text=True).stdout.split()[0] + "\n")
        run_install(self.mac, "--apply")
        self.assertEqual(instr.read_text(), (ROOT / "worker/runtime-instructions.template.md").read_text())

    def test_apply_without_acknowledgement_changes_nothing(self):
        before = tree(self.mac.home)
        r = run_install(self.mac, "--apply", ack=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--accept-unsandboxed", r.stdout)
        self.assertIn("dedicated", r.stdout)
        self.assertEqual(tree(self.mac.home), before, "nothing may be created, installed or loaded")
        self.assertNotIn("bootstrap", self.mac.calls())
        self.assertNotIn("launchctl", self.mac.calls())

    def _planted(self) -> Path:
        self.mac.base.mkdir(parents=True, exist_ok=True)
        planted = self.mac.tmp / "planted"
        planted.write_text("PLANTED\n")
        planted.chmod(0o600)
        return planted

    def _assert_planted_untouched(self, planted: Path):
        self.assertEqual(planted.read_text(), "PLANTED\n")
        self.assertEqual(stat.S_IMODE(planted.stat().st_mode), 0o600)

    def test_marker_temp_name_symlink_is_not_followed(self):
        planted = self._planted()
        (self.mac.base / "unsandboxed-ack.tmp").symlink_to(planted)
        run_install(self.mac, "--apply", "--accept-unsandboxed", ack=False)
        self._assert_planted_untouched(planted)
        marker = self.mac.base / "unsandboxed-ack"
        self.assertTrue(marker.is_file() and not marker.is_symlink())
        self.assertIn("accepted unsandboxed execution", marker.read_text())

    def test_marker_symlink_is_refused(self):
        planted = self._planted()
        (self.mac.base / "unsandboxed-ack").symlink_to(planted)
        r = run_install(self.mac, "--apply", "--accept-unsandboxed", ack=False)
        self.assertNotEqual(r.returncode, 0)
        self._assert_planted_untouched(planted)
        self.assertTrue((self.mac.base / "unsandboxed-ack").is_symlink(), "must not replace or follow the link")
        self.assertFalse((self.mac.base / "runner.sh").exists())
        self.assertNotIn("launchctl", self.mac.calls())

    def test_marker_directory_is_refused(self):
        self._planted()
        (self.mac.base / "unsandboxed-ack").mkdir()
        r = run_install(self.mac, "--apply", "--accept-unsandboxed", ack=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.mac.base / "runner.sh").exists())
        self.assertNotIn("launchctl", self.mac.calls())

    def test_failed_marker_write_aborts_before_install(self):
        if os.geteuid() == 0:
            self.skipTest("root can write to a read-only folder")
        base = self.mac.base
        for d in ("jobs", "done", "logs/transcripts", "tmp"):
            (base / d).mkdir(parents=True)
        base.chmod(0o500)
        try:
            r = run_install(self.mac, "--apply", "--accept-unsandboxed", ack=False)
        finally:
            base.chmod(0o700)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((base / "unsandboxed-ack").exists())
        self.assertFalse((base / "runner.sh").exists())
        self.assertFalse((self.mac.home / f"Library/LaunchAgents/{LABEL}.plist").exists())
        self.assertNotIn("launchctl", self.mac.calls())

    def test_apply_with_flag_records_the_acknowledgement(self):
        r = run_install(self.mac, "--apply", "--accept-unsandboxed", ack=False)
        marker = self.mac.base / "unsandboxed-ack"
        self.assertTrue(marker.is_file(), r.stdout + r.stderr)
        text = marker.read_text()
        self.assertRegex(text, r"^accepted unsandboxed execution on \d{4}-\d\d-\d\d by runner \S+\n$")
        self.assertIn("bootstrap", self.mac.calls())

    def test_later_apply_without_flag_works_once_acknowledged(self):
        run_install(self.mac, "--apply", ack=True)
        r = run_install(self.mac, "--apply", "--json", ack=False)
        self.assertEqual(rows(r.stdout)["unsandboxed_ack"]["status"], "PASS", r.stderr)

    def test_check_mode_acknowledgement_row_both_ways(self):
        res = rows(run_install(self.mac, "--json").stdout)
        self.assertEqual(res["unsandboxed_ack"]["status"], "FAIL")
        self.assertIn("worker/install.sh --apply --accept-unsandboxed", res["unsandboxed_ack"]["fix"])
        self.mac.ack()
        res = rows(run_install(self.mac, "--json").stdout)
        self.assertEqual(res["unsandboxed_ack"]["status"], "PASS")
        self.assertIn("accepted unsandboxed execution", res["unsandboxed_ack"]["detail"])

    def test_apply_waits_then_aborts_while_job_running(self):
        self.mac.flag("job_running")
        r = run_install(self.mac, "--apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("still running", r.stdout)
        self.assertNotIn("bootstrap", self.mac.calls())
        self.assertFalse((self.mac.base / "runner.sh").exists())
        self.assertFalse((self.mac.base / "pause").exists(), "pause marker must be removed on abort")

    def test_interrupted_apply_removes_pause_marker(self):
        self.mac.flag("job_running")
        p = subprocess.Popen(["/bin/bash", str(INSTALL), "--apply", "--accept-unsandboxed"],
                             env=self.mac.env(QA_WORKER_APPLY_WAIT="60"),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
        pause = self.mac.base / "pause"
        for _ in range(200):
            if pause.exists():
                break
            time.sleep(0.05)
        self.assertTrue(pause.exists(), "apply should have created the pause marker")
        time.sleep(0.3)
        p.terminate()
        p.wait(10)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(pause.exists())

    def test_apply_adds_plugin_and_never_sudo_without_tty(self):
        self.mac.flag("plugin_missing")
        r = run_install(self.mac, "--apply", FAKE_SLEEP="10")
        calls = self.mac.calls()
        self.assertIn("codex plugin add computer-use@openai-bundled", calls)
        self.assertNotIn("sudo", calls)
        self.assertIn("sudo pmset -a sleep 0 displaysleep 0", r.stdout)
        self.assertIn("defaults -currentHost write com.apple.screensaver idleTime -int 0", calls)

    def test_apply_falls_back_to_unified_plugin_name(self):
        self.mac.flag("plugin_missing")
        self.mac.flag("classic_add_fails")
        run_install(self.mac, "--apply")
        calls = self.mac.calls()
        self.assertIn("codex plugin add computer-use@openai-bundled", calls)
        self.assertIn("codex plugin add unified-computer-use@openai-bundled", calls)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.mac = FakeMac()
        for d in ("jobs", "done"):
            (self.mac.base / d).mkdir(parents=True, exist_ok=True)
        (self.mac.base / "runtime-instructions.md").write_text("RUNTIME BASELINE\n")
        self.mac.ack()

    def tearDown(self):
        self.mac.cleanup()

    def test_job_runs_first_listed_model_via_stdin_and_drops_brief(self):
        brief = 'Check the page.\nPassword for test site: $(touch PWNED) `id` "quoted"\n'
        (self.mac.base / "jobs/job-1.task").write_text("EFFORT=high\nMODEL=model-gamma\n" + brief)
        r = run_runner(self.mac, "--once")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.mac.base / "done/job-1"
        self.assertTrue((out / ".done").exists())
        self.assertFalse((out / "prompt.task").exists())
        self.assertFalse((out / "prompt.clean").exists())
        self.assertEqual(list((self.mac.base / "tmp").iterdir()), [])
        args = (self.mac.state / "exec.args").read_text().splitlines()
        self.assertEqual(args[args.index("--model") + 1], "model-alpha")
        self.assertIn("model_reasoning_effort=high", args)
        self.assertEqual(args[-1], "-")
        self.assertTrue(args[args.index("-C") + 1].startswith(str(self.mac.base / "tmp/active-")))
        self.assertIn("--ephemeral", args)
        stdin = (self.mac.state / "exec.stdin").read_text()
        self.assertTrue(stdin.startswith("RUNTIME BASELINE\n"))
        self.assertTrue(stdin.endswith("TASK BRIEF:\n" + brief))
        self.assertNotIn("EFFORT=", stdin)
        self.assertFalse(list(self.mac.tmp.rglob("PWNED")))
        output = (out / "output.txt").read_text()
        self.assertIn("Executor output discarded", output)
        self.assertIn("EXIT=0", output)
        self.assertNotIn("transcript", output)
        self.assertFalse((self.mac.base / "logs/transcripts/job-1.log").exists())
        for f in out.iterdir():
            if f.is_file():
                self.assertNotIn("PWNED", f.read_text(errors="ignore"))
        receipt = json.loads((out / "receipt.json").read_text())
        self.assertEqual(receipt["model"], "model-alpha")
        self.assertEqual(receipt["requested_model"], "model-gamma")
        self.assertEqual(receipt["exit_code"], 0)
        log = (self.mac.base / "logs/runner.log").read_text()
        self.assertNotIn("PWNED", log)

    def test_no_model_fails_closed(self):
        for flag, pattern in (("catalog_garbage", None), ("pattern_nomatch", "nomatch-*")):
            with self.subTest(flag=flag):
                if pattern:
                    (self.mac.base / "model-pattern").write_text(pattern + "\n")
                else:
                    self.mac.flag(flag)
                jid = f"job-{flag.replace('_', '-')}"
                (self.mac.base / f"jobs/{jid}.task").write_text("brief\n")
                run_runner(self.mac, "--once")
                self.mac.flag(flag, False)
                self.assertFalse((self.mac.state / "exec.args").exists(), "must never run unrestricted")
                out = self.mac.base / f"done/{jid}"
                self.assertTrue((out / ".done").exists())
                result = json.loads((out / "result.json").read_text())
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["observations"], [])
                self.assertIn("no listed model matched", result["blockers"][0])
                self.assertIn(f"(pattern: {pattern or 'none set'})", result["blockers"][0])
                self.assertFalse((out / "prompt.task").exists())

    def test_runner_honours_pause_marker(self):
        (self.mac.base / "pause").touch()
        (self.mac.base / "jobs/job-p.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        self.assertTrue((self.mac.base / "jobs/job-p.task").exists())
        self.assertFalse((self.mac.state / "exec.args").exists())
        (self.mac.base / "pause").unlink()
        run_runner(self.mac, "--once")
        self.assertTrue((self.mac.base / "done/job-p/.done").exists())

    def test_bad_ids_and_duplicates_are_rejected_not_run(self):
        (self.mac.base / "jobs/-bad.task").write_text("x\n")
        (self.mac.base / "done/dup").mkdir()
        (self.mac.base / "jobs/dup.task").write_text("x\n")
        run_runner(self.mac, "--once")
        self.assertFalse((self.mac.state / "exec.args").exists())
        self.assertFalse((self.mac.base / "rejected/dup.duplicate.task").exists())
        self.assertEqual(list((self.mac.base / "jobs").glob("*.task")), [])

    def test_invalid_effort_and_exit_code(self):
        (self.mac.base / "jobs/job-2.task").write_text("EFFORT=extreme\nbrief\n")
        run_runner(self.mac, "--once", FAKE_EXEC_RC="7")
        args = (self.mac.state / "exec.args").read_text()
        self.assertIn("model_reasoning_effort=medium", args)
        self.assertIn("EXIT=7", (self.mac.base / "done/job-2/output.txt").read_text())

    def test_selfcheck_file(self):
        self.mac.keychain("locked")
        r = run_runner(self.mac, "--selfcheck")
        data = json.loads(r.stdout)
        self.assertTrue(data["in_gui_session"])
        self.assertTrue(data["screenshot_ok"])
        self.assertTrue(data["computer_use_installed"])
        self.assertTrue(data["login_ok"])
        self.assertEqual(data["login_kind"], "chatgpt")
        self.assertEqual(data["model"], "model-alpha")
        self.assertEqual(data["model_pattern"], "")
        self.assertTrue(data["keychain_found"])
        self.assertFalse(data["keychain_unlocked"])
        self.assertNotIn("/somewhere", data["computer_use_line"])

    def test_keychain_locked_is_not_reported_unlocked(self):
        # `security show-keychain-info` succeeds here although the keychain is locked.
        self.mac.keychain("locked")
        data = json.loads(run_runner(self.mac, "--selfcheck").stdout)
        self.assertFalse(data["keychain_unlocked"])
        self.assertEqual(data["keychain_state"], "locked")

    def test_keychain_unknown_is_manual_not_pass(self):
        authorise_lead(self.mac)
        self.mac.keychain("unknown")
        run_runner(self.mac, "--selfcheck")
        res = rows(run_install(self.mac, "--json").stdout)
        self.assertEqual(res["gui_keychain"]["status"], "MANUAL")
        self.mac.keychain("locked")
        run_runner(self.mac, "--selfcheck")
        self.assertEqual(rows(run_install(self.mac, "--json").stdout)["gui_keychain"]["status"], "WARN")
        self.mac.keychain("unlocked")
        run_runner(self.mac, "--selfcheck")
        self.assertEqual(rows(run_install(self.mac, "--json").stdout)["gui_keychain"]["status"], "PASS")

    def test_helper_modes(self):
        self.assertEqual(run_runner(self.mac, "--version").stdout.strip(),
                         subprocess.run(["sed", "-n", 's/^QA_WORKER_RUNNER_VERSION="\\(.*\\)"$/\\1/p', str(RUNNER)],
                                        capture_output=True, text=True).stdout.strip())
        self.assertEqual(run_runner(self.mac, "--find-app").stdout.strip(), str(self.mac.app))
        self.assertTrue(run_runner(self.mac, "--find-codex").stdout.strip().endswith("codex-cli/bin/codex"))
        self.assertEqual(run_runner(self.mac, "--pick-model").stdout.strip(), "model-alpha")
        self.assertEqual(run_runner(self.mac, "--model-pattern").stdout.strip(), "")

    def pick(self, **env):
        return run_runner(self.mac, "--pick-model", **env).stdout.strip()

    def test_pattern_matches_second_listed_model(self):
        (self.mac.base / "model-pattern").write_text("model-b*\n")
        self.assertEqual(self.pick(), "model-beta")
        (self.mac.base / "jobs/job-m.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        args = (self.mac.state / "exec.args").read_text().splitlines()
        self.assertEqual(args[args.index("--model") + 1], "model-beta")
        self.assertEqual(json.loads((self.mac.base / "done/job-m/receipt.json").read_text())["model"], "model-beta")

    def test_pattern_matching_nothing_runs_nothing(self):
        (self.mac.base / "model-pattern").write_text("model-hidden\n")  # hidden models are not listed
        self.assertEqual(self.pick(), "")
        (self.mac.base / "jobs/job-n.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        self.assertFalse((self.mac.state / "exec.args").exists())
        result = json.loads((self.mac.base / "done/job-n/result.json").read_text())
        self.assertEqual(result["status"], "blocked")
        self.assertIn("no listed model matched (pattern: model-hidden)", result["blockers"][0])

    def test_env_pattern_overrides_file(self):
        (self.mac.base / "model-pattern").write_text("model-b*\n")
        self.assertEqual(self.pick(QA_WORKER_MODEL="model-g*"), "model-gamma")
        self.assertEqual(self.pick(QA_WORKER_MODEL="   "), "model-beta", "a blank variable does not override")

    def test_runner_without_acknowledgement_runs_nothing(self):
        (self.mac.base / "unsandboxed-ack").unlink()
        (self.mac.base / "jobs/job-k.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        self.assertFalse((self.mac.state / "exec.args").exists(), "must never run unacknowledged")
        result = json.loads((self.mac.base / "done/job-k/result.json").read_text())
        self.assertEqual(result["status"], "blocked")
        self.assertIn("worker/install.sh --apply --accept-unsandboxed", result["blockers"][0])
        self.assertNotEqual(run_runner(self.mac, "--ack-state").returncode, 0)
        self.assertFalse(json.loads(run_runner(self.mac, "--selfcheck").stdout)["unsandboxed_ack"])

    def test_marker_that_is_not_a_readable_regular_file_is_not_an_acknowledgement(self):
        marker = self.mac.base / "unsandboxed-ack"
        good = marker.read_text()
        other = self.mac.tmp / "elsewhere"
        other.write_text(good)
        cases = ["symlink", "directory", "wrong content"]
        if os.geteuid() != 0:
            cases.append("unreadable")
        for case in cases:
            with self.subTest(case=case):
                if marker.is_dir() and not marker.is_symlink():
                    marker.rmdir()
                else:
                    marker.unlink()
                if case == "symlink":
                    marker.symlink_to(other)
                elif case == "directory":
                    marker.mkdir()
                elif case == "wrong content":
                    marker.write_text("hello\n")
                else:
                    marker.write_text(good)
                    marker.chmod(0)
                try:
                    self.assertNotEqual(run_runner(self.mac, "--ack-state").returncode, 0)
                    (self.mac.base / "jobs/job-z.task").write_text("brief\n")
                    run_runner(self.mac, "--once")
                    self.assertFalse((self.mac.state / "exec.args").exists())
                    result = json.loads((self.mac.base / "done/job-z/result.json").read_text())
                    self.assertIn("--accept-unsandboxed", result["blockers"][0])
                finally:
                    if case == "unreadable":
                        marker.chmod(0o600)
                    subprocess.run(["rm", "-rf", str(self.mac.base / "done/job-z")])

    def test_pattern_file_unreadable_during_catalogue_query_blocks(self):
        if os.geteuid() == 0:
            self.skipTest("root can read a mode-000 file")
        f = self.mac.base / "model-pattern"
        f.write_text("model-b*\n")
        self.mac.flag("lock_pattern_during_catalog")
        try:
            (self.mac.base / "jobs/job-r.task").write_text("brief\n")
            run_runner(self.mac, "--once")
        finally:
            f.chmod(0o600)
        self.assertFalse((self.mac.state / "exec.args").exists(), "the executor must never start")
        result = json.loads((self.mac.base / "done/job-r/result.json").read_text())
        self.assertEqual(result["status"], "blocked")
        self.assertIn("model pattern file could not be read", result["blockers"][0])

    def test_runner_with_acknowledgement_runs(self):
        self.assertEqual(run_runner(self.mac, "--ack-state").returncode, 0)
        self.assertTrue(json.loads(run_runner(self.mac, "--selfcheck").stdout)["unsandboxed_ack"])
        (self.mac.base / "jobs/job-y.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        self.assertTrue((self.mac.state / "exec.args").exists())

    def _assert_pattern_file_fails_closed(self):
        picked = run_runner(self.mac, "--pick-model")
        self.assertNotEqual(picked.returncode, 0)
        self.assertEqual(picked.stdout.strip(), "")
        self.assertNotEqual(run_runner(self.mac, "--model-pattern").returncode, 0)
        data = json.loads(run_runner(self.mac, "--selfcheck").stdout)
        self.assertFalse(data["model_pattern_ok"])
        self.assertEqual(data["model"], "")
        authorise_lead(self.mac)
        row = rows(run_install(self.mac, "--json").stdout)["model_catalog"]
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("model-pattern", row["fix"])
        (self.mac.base / "jobs/job-u.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        self.assertFalse((self.mac.state / "exec.args").exists(), "must never run with an unreadable pattern file")
        result = json.loads((self.mac.base / "done/job-u/result.json").read_text())
        self.assertEqual(result["status"], "blocked")
        self.assertIn("model pattern file could not be read", result["blockers"][0])

    def test_unreadable_pattern_file_blocks_and_runs_nothing(self):
        if os.geteuid() == 0:
            self.skipTest("root can read a mode-000 file")
        f = self.mac.base / "model-pattern"
        f.write_text("model-b*\n")
        f.chmod(0)
        try:
            self._assert_pattern_file_fails_closed()
        finally:
            f.chmod(0o600)

    def test_directory_at_pattern_path_blocks_and_runs_nothing(self):
        (self.mac.base / "model-pattern").mkdir()
        self._assert_pattern_file_fails_closed()

    def test_blank_pattern_file_behaves_as_absent(self):
        (self.mac.base / "model-pattern").write_text("\n  \t\n\n")
        self.assertEqual(self.pick(), "model-alpha")
        self.assertEqual(run_runner(self.mac, "--model-pattern").returncode, 0)
        self.assertEqual(json.loads(run_runner(self.mac, "--selfcheck").stdout)["model_pattern_ok"], True)
        (self.mac.base / "jobs/job-b.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        args = (self.mac.state / "exec.args").read_text().splitlines()
        self.assertEqual(args[args.index("--model") + 1], "model-alpha")

    def test_pattern_file_with_blank_lines_and_trailing_whitespace(self):
        (self.mac.base / "model-pattern").write_text("\n  \t\n  model-d*  \t\r\n\nmodel-b*\n")
        self.assertEqual(run_runner(self.mac, "--model-pattern").stdout.strip(), "model-d*")
        self.assertEqual(self.pick(), "model-delta")


if __name__ == "__main__":
    unittest.main()
