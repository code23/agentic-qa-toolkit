"""lead/qa-submit with fake ssh/scp on PATH; the "worker" is a local folder plus a thread."""
from __future__ import annotations

import json
import os
import shutil
import secrets
import runpy
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "editions/dedicated-mac/extras/worker-setup"
SUBMIT = ROOT / "lead/qa-submit"
SETUP = ROOT / "lead/setup-lead.sh"

# ssh stub: drop options, take the host, run the remote command locally with /bin/sh -c.
FAKE_SSH = r"""#!/bin/bash
while [ $# -gt 0 ]; do case "$1" in -o) shift 2 ;; -*) shift ;; *) break ;; esac; done
host=$1; shift
echo "ssh $host :: $*" >> "$FAKE_LOG"
[ -e "$FAKE_SSH_FAIL" ] && { echo "$(cat "$FAKE_SSH_FAIL")" >&2; exit 255; }
case "$*" in
  "python3 -c "*)
    [ "$FAKE_RECEIVE_FAIL" = 1 ] && { echo 'receiver rejected input' >&2; exit 2; }
    [ "$FAKE_RECEIVE_TRUNC" = 1 ] && { head -c 8 | /bin/sh -c "$*"; exit $?; } ;;
esac
exec /bin/sh -c "$*"
"""
# scp stub: strip "host:" from remote paths and copy locally.
FAKE_SCP = r"""#!/bin/bash
rec=""; args=()
while [ $# -gt 0 ]; do
  case "$1" in -o) shift 2; continue ;; -r) rec=-R ;; -q) ;; *) args+=("${1#*:}") ;; esac
  shift
done
echo "scp ${args[*]}" >> "$FAKE_LOG"
[ -e "$FAKE_SCP_FAIL" ] && {
  [ "$FAKE_SCP_PARTIAL" = 1 ] && cp "${args[0]}" "${args[1]}"
  echo "scp: connection lost" >&2; exit 1;
}
cp $rec "${args[0]}" "${args[1]}"
"""

GOOD = {"status": "completed",
        "observations": [{"check": "tab title", "observed": "Example Domain", "as_expected": True, "evidence": ["example-home.png"]},
                         {"check": "link", "observed": "present", "as_expected": True, "evidence": []}],
        "blockers": [], "evidence": ["example-home.png"]}


class FakeWorker(threading.Thread):
    """Plays the runner: picks up jobs/<id>.task and writes done/<id>/."""

    def __init__(self, base: Path, result: object | None, delay: float = 0.1, finish: bool = True):
        super().__init__(daemon=True)
        self.base, self.result, self.delay, self.finish = base, result, delay, finish
        self.seen: dict[str, str] = {}
        self.stop = False

    def run(self):
        while not self.stop:
            for job in (self.base / "jobs").glob("*.task"):
                jid = job.stem
                self.seen[jid] = job.read_text()
                out = self.base / "done" / jid
                out.mkdir(parents=True)
                job.unlink()
                time.sleep(self.delay)
                if self.result is not None:
                    (out / "result.json").write_text(self.result if isinstance(self.result, str) else json.dumps(self.result))
                (out / "example-home.png").write_bytes(b"PNG")
                (out / "output.txt").write_text("final\nEXIT=0\n")
                if self.finish:
                    (out / ".done").touch()
            time.sleep(0.02)


class SubmitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="qa-submit-test-"))
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.base = self.tmp / "worker/qa-worker"
        for d in (self.home, self.bin, self.base / "jobs", self.base / "done"):
            d.mkdir(parents=True)
        for name, body in (("ssh", FAKE_SSH), ("scp", FAKE_SCP)):
            p = self.bin / name
            p.write_text(body)
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
        self.log = self.tmp / "transport.log"
        self.cfg = self.home / ".config/qa-worker/config.json"
        self.cfg.parent.mkdir(parents=True)
        self.cfg.write_text(json.dumps({"host": "worker@qa-worker.local", "base": str(self.base),
                                        "busyWaitSeconds": 1, "timeout": 5}))
        self.brief = self.tmp / "briefs/brief.md"
        self.brief.parent.mkdir()
        self.brief.write_text('# Brief\nTest password: $(touch PWNED) `touch PWNED2` "q" \'s\'\n')
        self.worker: FakeWorker | None = None

    def tearDown(self):
        if self.worker:
            self.worker.stop = True
            self.worker.join(2)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, **extra):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home), "FAKE_LOG": str(self.log),
               "QA_WORKER_SUBMIT_POLL": "0.05", "QA_WORKER_SUBMIT_BUSY_POLL": "0.05", "LANG": "C.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1"}
        env.update(extra)
        return env

    def submit(self, *args, keep=True, **env):
        # Most tests reuse one brief file, so keep it unless the test is about deletion.
        args = (("--keep-brief",) if keep else ()) + args
        return subprocess.run([sys.executable, str(SUBMIT), *args], env=self.env(**env),
                              capture_output=True, text=True, timeout=60)

    def start_worker(self, result=GOOD, **kw):
        self.worker = FakeWorker(self.base, result, **kw)
        self.worker.start()

    def test_success_collects_only_that_job(self):
        (self.base / "done/other-job").mkdir()
        (self.base / "done/other-job/.done").touch()
        self.start_worker()
        r = self.submit(str(self.brief))
        self.assertEqual(r.returncode, 0, r.stderr)
        (jid, task), = self.worker.seen.items()
        self.assertTrue(task.startswith("EFFORT=medium\n# Brief\n"))
        self.assertIn('$(touch PWNED) `touch PWNED2` "q" \'s\'', task)
        self.assertIn("do not assign severity", task)
        self.assertFalse(list(self.tmp.rglob("PWNED*")))
        results = self.brief.parent / "qa-worker-results"
        self.assertEqual([p.name for p in results.iterdir()], [jid])
        self.assertTrue((results / jid / "result.json").is_file())
        log = self.log.read_text()
        self.assertIn("python3 -c", log)
        self.assertIn("os.link(stage", log)
        self.assertNotIn("PWNED", log, "brief text must never be part of a remote command")
        self.assertTrue(self.brief.exists())
        self.assertIn("status completed", r.stdout)

    def test_delete_brief_and_effort_override(self):
        self.start_worker()
        r = self.submit("--effort", "high", "--out", str(self.tmp / "out"), str(self.brief), keep=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.brief.exists())
        self.assertTrue(next(iter(self.worker.seen.values())).startswith("EFFORT=high\n"))
        self.assertEqual(len(list((self.tmp / "out").iterdir())), 1)

    def sensitive_brief(self, environment="test"):
        values = ["synthetic-user-" + secrets.token_hex(12), "synthetic-pass-" + secrets.token_hex(12)]
        self.brief.write_text("ACCESS=" + json.dumps({"environment": environment,
                              "username": values[0], "password": values[1]}) + "\nCheck page\n")
        return values

    def assert_sensitive_purged(self, values, response):
        self.assertFalse(self.brief.exists())
        self.assertEqual(list((self.base / "jobs").glob(".*.tmp")), [])
        for value in values:
            self.assertNotIn(value, response.stdout + response.stderr)
            for path in self.tmp.rglob("*"):
                if path.is_file():
                    self.assertNotIn(value.encode(), path.read_bytes(), str(path.relative_to(self.tmp)))

    def test_sensitive_brief_purged_on_config_rejection_keep_and_production_rejection(self):
        for options, environment in (({"HOME": str(self.tmp / "nohome")}, "test"), ({}, "production")):
            values = self.sensitive_brief(environment)
            response = self.submit(str(self.brief), keep=False, **options)
            self.assertEqual(response.returncode, 2)
            self.assert_sensitive_purged(values, response)
        values = self.sensitive_brief()
        response = self.submit(str(self.brief), keep=True)
        self.assertEqual(response.returncode, 2)
        self.assert_sensitive_purged(values, response)

    def test_sensitive_partial_scp_is_purged_on_transfer_failure(self):
        values = self.sensitive_brief()
        flag = self.tmp / "scp-failure"
        flag.touch()
        response = self.submit(str(self.brief), keep=False, FAKE_RECEIVE_TRUNC="1")
        self.assertEqual(response.returncode, 2)
        self.assert_sensitive_purged(values, response)

    def test_sensitive_busy_rejection_purges_local_brief(self):
        (self.base / "jobs/busy.task").write_text("unrelated queued job")
        values = self.sensitive_brief()
        response = self.submit("--timeout", "0.1", str(self.brief), keep=False)
        self.assertEqual(response.returncode, 2)
        self.assert_sensitive_purged(values, response)

    def test_sensitive_invalid_utf8_is_purged_before_rejection(self):
        values = self.sensitive_brief()
        self.brief.write_bytes(self.brief.read_bytes() + b"\xff")
        response = self.submit(str(self.brief), keep=False)
        self.assertEqual(response.returncode, 2)
        self.assert_sensitive_purged(values, response)

    def test_sensitive_receiver_symlink_cannot_redirect_payload(self):
        external = self.tmp / "external-queue"
        external.mkdir()
        (self.base / "jobs").rmdir()
        (self.base / "jobs").symlink_to(external)
        values = self.sensitive_brief()
        response = self.submit(str(self.brief), keep=False)
        self.assertEqual(response.returncode, 2)
        self.assert_sensitive_purged(values, response)
        self.assertEqual(list(external.iterdir()), [])

    def test_sensitive_success_purges_lead_and_transport_copies(self):
        self.start_worker()
        values = self.sensitive_brief()
        response = self.submit(str(self.brief), keep=False)
        self.assertEqual(response.returncode, 0)
        self.assert_sensitive_purged(values, response)

    def test_receiver_preserves_existing_task_and_rejects_directory_substitution(self):
        code = runpy.run_path(str(SUBMIT))["RECEIVE_CODE"]
        payload = "synthetic-receiver-" + secrets.token_hex(20)
        existing = self.base / "jobs/owned.task"
        existing.write_text("previous user-owned brief")
        response = subprocess.run([sys.executable, "-c", code, str(self.base), "owned", str(len(payload))],
                                  input=payload, capture_output=True, text=True)
        self.assertEqual(response.returncode, 2)
        self.assertEqual(existing.read_text(), "previous user-owned brief")
        self.assertFalse((self.base / "jobs/.owned.tmp").exists())
        receiver = subprocess.Popen([sys.executable, "-c", code, str(self.base), "race", str(len(payload))],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stage = self.base / "jobs/.race.tmp"
        for _ in range(100):
            if stage.exists(): break
            time.sleep(.01)
        self.assertTrue(stage.exists())
        self.assertEqual(stage.stat().st_mode & 0o777, 0o600)
        original = self.base / "held-jobs"
        (self.base / "jobs").rename(original)
        outside = self.tmp / "outside"
        outside.mkdir()
        (self.base / "jobs").symlink_to(outside)
        receiver.communicate(payload, timeout=5)
        self.assertEqual(receiver.returncode, 2)
        self.assertFalse((original / ".race.tmp").exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_brief_deleted_by_default_even_when_outcome_unknown(self):
        self.start_worker(finish=False)
        r = self.submit("--timeout", "0.5", str(self.brief), keep=False)
        self.assertEqual(r.returncode, 3)
        self.assertFalse(self.brief.exists())

    def test_brief_kept_when_never_sent(self):
        r = self.submit(str(self.brief), keep=False, HOME=str(self.tmp / "nohome"))
        self.assertEqual(r.returncode, 2)
        self.assertTrue(self.brief.exists())

    def test_legacy_delete_brief_flag_still_accepted(self):
        self.start_worker()
        r = self.submit("--delete-brief", str(self.brief), keep=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.brief.exists())

    def test_invalid_result_is_exit_1(self):
        for bad in ('{"verdict": "pass"}', "not json", {"status": "completed", "observations": "x"}):
            with self.subTest(bad=bad):
                if self.worker:
                    self.worker.stop = True
                self.start_worker(result=bad)
                self.assertEqual(self.submit(str(self.brief)).returncode, 1)
        self.worker.stop = True
        self.start_worker(result=None)
        self.assertEqual(self.submit(str(self.brief)).returncode, 1)

    def test_result_contract_is_enforced(self):
        obs = {"check": "c", "observed": "o", "as_expected": None, "evidence": ["a.png"]}
        base = {"status": "completed", "observations": [obs], "blockers": [], "evidence": ["a.png"]}
        bad = [
            {"status": "completed"},                                       # missing fields
            dict(base, status="pass"),                                     # status not allowed
            dict(base, observations=[{}]),                                 # empty observation
            dict(base, observations=[dict(obs, as_expected="yes")]),       # as_expected not bool/null
            dict(base, observations=[{k: v for k, v in obs.items() if k != "observed"}]),
            dict(base, observations=[dict(obs, evidence="a.png")]),        # evidence not a list
            dict(base, evidence=[1]),                                      # non-string evidence
            dict(base, blockers="none"),                                   # blockers not a list
            dict(base, observations=[]),                                   # completed with nothing observed
        ]
        for i, result in enumerate(bad):
            with self.subTest(i=i):
                if self.worker:
                    self.worker.stop = True
                    self.worker.join(1)
                self.start_worker(result=result)
                self.assertEqual(self.submit(str(self.brief)).returncode, 1, result)
        good = [base, dict(base, status="blocked", observations=[], blockers=["no access"], evidence=[])]
        for result in good:
            with self.subTest(result=result):
                self.worker.stop = True
                self.worker.join(1)
                self.start_worker(result=result)
                r = self.submit(str(self.brief))
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_deadline_is_unknown_exit_3(self):
        self.start_worker(finish=False)
        r = self.submit("--timeout", "0.5", str(self.brief))
        self.assertEqual(r.returncode, 3)
        self.assertIn("outcome unknown", r.stderr)
        jid = next(iter(self.worker.seen))
        self.assertIn(jid, r.stderr)
        self.assertFalse((self.brief.parent / "qa-worker-results").exists())
        self.assertEqual(len(self.worker.seen), 1, "never replayed")

    def test_done_after_deadline_is_unknown(self):
        # The marker appears while the lead sleeps between polls, after the deadline passed.
        self.start_worker(delay=0.8)
        t0 = time.time()
        r = self.submit("--timeout", "0.4", str(self.brief), QA_WORKER_SUBMIT_POLL="1.5")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("outcome unknown", r.stderr)
        self.assertLess(time.time() - t0, 1.4, "each wait must be bounded by the time remaining")

    def test_busy_worker_is_not_submitted(self):
        (self.base / "jobs/someone-elses.task").write_text("x")
        r = self.submit(str(self.brief), keep=False)
        # Nothing was sent: exit 2 (not 3, which means a sent job's outcome is unknown).
        self.assertEqual(r.returncode, 2)
        self.assertIn("NOT SUBMITTED", r.stderr)
        self.assertNotIn("submitted qa-worker-", r.stdout)
        self.assertTrue(self.brief.exists(), "an unsent brief must be kept for a retry")
        self.assertEqual(sorted(p.name for p in (self.base / "jobs").iterdir()), ["someone-elses.task"])

    def test_brief_kept_when_receiver_rejects(self):
        r = self.submit(str(self.brief), keep=False, FAKE_RECEIVE_FAIL="1")
        self.assertEqual(r.returncode, 2)
        self.assertTrue(self.brief.exists())

    def test_not_configured_and_bad_config(self):
        self.cfg.unlink()
        self.assertEqual(self.submit(str(self.brief)).returncode, 2)
        self.cfg.write_text(json.dumps({"host": "-oProxyCommand=evil", "base": "/x"}))
        self.assertEqual(self.submit(str(self.brief)).returncode, 2)
        self.cfg.write_text(json.dumps({"host": "w@h", "base": "/x; rm -rf ~"}))
        self.assertEqual(self.submit(str(self.brief)).returncode, 2)

    def test_settings_worker_block(self):
        self.cfg.unlink()
        nested = self.tmp / "nested/settings.json"
        nested.parent.mkdir()
        nested.write_text(json.dumps({"other": 1, "worker": {"host": "w@qa-worker.local", "base": str(self.base),
                                                           "busyWaitSeconds": 1, "timeout": 5}}))
        self.start_worker()
        r = self.submit(str(self.brief), QA_WORKER_CONFIG=str(nested))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_collect_failure_after_submit_is_exit_4(self):
        # Sent and finished, but scp of done/<id> fails: not "nothing sent" (2).
        self.start_worker()
        flag = self.tmp / "scp_fail_collect"
        stub = self.bin / "scp"
        stub.write_text(stub.read_text().replace(
            'cp $rec', '[ -n "$rec" ] && [ -e "$FAKE_SCP_COLLECT_FAIL" ] && { echo "scp: lost" >&2; exit 1; }\ncp $rec'))
        flag.touch()
        r = self.submit(str(self.brief), keep=False, FAKE_SCP_COLLECT_FAIL=str(flag))
        self.assertEqual(r.returncode, 4, r.stderr)
        jid = next(iter(self.worker.seen))
        self.assertIn(jid, r.stderr)
        self.assertIn(f"{self.base}/done/{jid}", r.stderr)
        self.assertIn("not collected", r.stderr)
        self.assertFalse(self.brief.exists(), "the job was sent, so the brief is deleted")
        self.assertEqual(len(self.worker.seen), 1, "never resubmitted")

    def test_recovery_command_is_shell_quoted(self):
        import shlex
        self.start_worker()
        stub = self.bin / "scp"
        stub.write_text(stub.read_text().replace('cp $rec', '[ -n "$rec" ] && { echo "scp: lost" >&2; exit 1; }\ncp $rec'))
        out = self.tmp / "my results $(touch PWNED)"
        r = self.submit("--out", str(out), str(self.brief))
        self.assertEqual(r.returncode, 4, r.stderr)
        jid = next(iter(self.worker.seen))
        cmd = r.stderr[r.stderr.index("scp -r "):].strip()
        self.assertEqual(shlex.split(cmd), ["scp", "-r", f"worker@qa-worker.local:{self.base}/done/{jid}", f"{out}/"])
        self.assertIn(shlex.quote(f"{out}/"), cmd)

    def test_transport_errors_are_exit_2(self):
        fail = self.tmp / "scp_fail"
        fail.touch()
        r = self.submit(str(self.brief), FAKE_RECEIVE_FAIL="1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("receiver rejected", r.stderr)
        sshfail = self.tmp / "ssh_fail"
        sshfail.write_text("ssh: connect to host qa-worker.local port 22: Connection refused")
        r = self.submit(str(self.brief), FAKE_SSH_FAIL=str(sshfail))
        self.assertEqual(r.returncode, 2)

    def test_tilde_base_resolved_on_worker(self):
        whome = self.tmp / "worker"
        self.cfg.write_text(json.dumps({"host": "w@qa-worker.local", "base": "~/qa-worker", "busyWaitSeconds": 1, "timeout": 5}))
        self.start_worker()
        # The fake ssh runs locally, so the worker's $HOME is whatever HOME the stub inherits.
        r = subprocess.run([sys.executable, str(SUBMIT), "--config", str(self.cfg), str(self.brief)],
                           env={**self.env(), "HOME": str(whome)}, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_probe(self):
        self.start_worker()
        r = self.submit("--probe", "--out", str(self.tmp / "probes"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PROBE OK", r.stdout)
        task = next(iter(self.worker.seen.values()))
        self.assertIn("https://example.com", task)

    def test_probe_that_does_not_hold_is_exit_1(self):
        partial = dict(GOOD, status="partial")
        self.start_worker(result=partial)
        r = self.submit("--probe", "--out", str(self.tmp / "probes"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not hold", r.stderr)

    def test_probe_brief_matches_worker_copy(self):
        ns: dict = {}
        src = SUBMIT.read_text()
        start = src.index('PROBE_BRIEF = """')
        exec(src[start:src.index('"""\n', start + 20) + 4], ns)
        self.assertEqual(ns["PROBE_BRIEF"], (ROOT / "worker/probe-brief.md").read_text())

    def test_check_mode(self):
        r = self.submit("--check")
        self.assertEqual(r.returncode, 2)
        self.assertIn("queue folders: ok", r.stdout)
        self.assertIn("MISSING", r.stdout)

    def test_requires_exactly_one_mode(self):
        self.assertEqual(self.submit().returncode, 2)
        self.assertEqual(self.submit("--probe", str(self.brief)).returncode, 2)


class SetupLeadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="qa-worker-lead-test-"))
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        p = self.bin / "ssh"
        p.write_text('#!/bin/bash\necho "$FAKE_SSH_ERR" >&2\nexit 255\n')
        p.chmod(0o755)
        p = self.bin / "python3"
        p.write_text(f'#!/bin/bash\nexec "{sys.executable}" "$@"\n')
        p.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_setup(self, *args, err="Permission denied (publickey)."):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home), "FAKE_SSH_ERR": err,
               "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(["/bin/bash", str(SETUP), *args], env=env, capture_output=True, text=True, timeout=60)

    def test_check_only_writes_nothing_and_prints_copy_id(self):
        r = self.run_setup("--host", "worker@qa-worker.local")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertIn("FAIL    SSH key", r.stdout)
        self.assertIn("ssh-copy-id -i", r.stdout)
        self.assertIn("MANUAL  Probe round trip", r.stdout)

    def test_apply_creates_key_and_config_but_no_probe_while_failing(self):
        r = self.run_setup("--host", "worker@qa-worker.local", "--apply")
        self.assertEqual(r.returncode, 1)
        self.assertTrue((self.home / ".ssh/id_ed25519.pub").exists())
        cfg = json.loads((self.home / ".config/qa-worker/config.json").read_text())
        self.assertEqual(cfg["host"], "worker@qa-worker.local")
        self.assertEqual(cfg["base"], "~/qa-worker")
        self.assertIn("PASS    Config", r.stdout)
        self.assertIn("skipped until the rows above pass", r.stdout)

    def test_apply_updates_nested_worker_block(self):
        cfg_path = self.home / ".config/qa-worker/config.json"
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(json.dumps({"other": 1, "worker": {"host": "old@qa-worker.local", "base": "~/old", "effort": "high"}}))
        r = self.run_setup("--host", "new@qa-worker.local", "--base", "~/qa-worker", "--apply")
        cfg = json.loads(cfg_path.read_text())
        self.assertEqual(cfg["worker"]["host"], "new@qa-worker.local")
        self.assertEqual(cfg["worker"]["base"], "~/qa-worker")
        self.assertEqual(cfg["worker"]["effort"], "high")
        self.assertEqual(cfg["other"], 1)
        self.assertNotIn("host", cfg)
        self.assertIn("PASS    Config", r.stdout)

    def test_unreachable_host(self):
        r = self.run_setup("--host", "worker@qa-worker.local", err="ssh: Could not resolve hostname qa-worker.local")
        self.assertIn("FAIL    Host reachable", r.stdout)

    def test_rejects_bad_host(self):
        self.assertEqual(self.run_setup("--host", "-oProxyCommand=x").returncode, 2)


if __name__ == "__main__":
    unittest.main()
