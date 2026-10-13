"""The runner's kernel-backed job lock (worker/lockrun.py) and how runner/install use it."""
from __future__ import annotations

import os
import fcntl
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from stubs import ROOT, FakeMac
from test_install import authorise_lead, run_install, run_runner

LOCKRUN = ROOT / "worker/lockrun.py"


def probe(path: Path) -> str:
    return subprocess.run([sys.executable, str(LOCKRUN), "probe", str(path)],
                          capture_output=True, text=True).stdout.strip()


def hold(lock: Path, info: Path) -> subprocess.Popen:
    """A holder process: takes the lock and sleeps."""
    p = subprocess.Popen([sys.executable, str(LOCKRUN), "run", str(lock), str(info), "sleep", "60"])
    for _ in range(100):
        if p.poll() is not None:
            raise AssertionError(f"holder exited before readiness: {p.returncode}")
        try:
            ready = f"pid {p.pid} " in info.read_text()
        except FileNotFoundError:
            ready = False
        if ready:
            # probe itself takes LOCK_EX briefly. Do not let the readiness
            # observer win that lock before the holder has acquired it.
            if probe(lock) != "busy":
                p.kill()
                p.wait()
                raise AssertionError("ready holder does not hold the kernel lock")
            return p
        time.sleep(0.05)
    p.kill()
    p.wait()
    raise AssertionError("holder never took the lock")


class LockrunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="qa-worker-lock-test-"))
        self.lock, self.info = self.tmp / ".active.lock", self.tmp / ".active.info"

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)])

    def test_probe_missing_file_is_free_and_creates_nothing(self):
        self.assertEqual(probe(self.lock), "free")
        self.assertFalse(self.lock.exists())

    def test_second_holder_gets_busy(self):
        p = hold(self.lock, self.info)
        try:
            r = subprocess.run([sys.executable, str(LOCKRUN), "run", str(self.lock), str(self.info), "true"])
            self.assertEqual(r.returncode, 75)
            self.assertIn(f"pid {p.pid}", self.info.read_text())
        finally:
            p.kill()
            p.wait()

    def test_probe_lock_during_startup_causes_nonblocking_admission_failure(self):
        """Reproduce the old test-readiness race with real flock operations."""
        opened, acquire = self.tmp / "opened", self.tmp / "acquire"
        driver = r'''
import importlib.util, pathlib, sys, time
spec=importlib.util.spec_from_file_location('lockrun',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
actual=m.fcntl.flock
def pause(fd, flags):
    pathlib.Path(sys.argv[4]).touch()
    while not pathlib.Path(sys.argv[5]).exists(): time.sleep(.01)
    return actual(fd,flags)
m.fcntl.flock=pause
sys.exit(m.run(sys.argv[2],sys.argv[3],['sleep','60']))
'''
        p = subprocess.Popen([sys.executable, "-c", driver, str(LOCKRUN), str(self.lock), str(self.info),
                              str(opened), str(acquire)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        fd = None
        try:
            for _ in range(100):
                if opened.exists(): break
                time.sleep(.01)
            self.assertTrue(opened.exists())
            # This is the exact exclusive-lock interval in production probe().
            fd = os.open(self.lock, os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquire.touch()
            stdout, stderr = p.communicate(timeout=5)
            self.assertEqual(p.returncode, 75)
            self.assertEqual(stdout + stderr, b"")
            self.assertFalse(self.info.exists())
        finally:
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            if p.poll() is None:
                p.kill()
            p.wait()

    def test_holder_readiness_does_not_compete_for_startup_lock(self):
        for _ in range(10):
            p = hold(self.lock, self.info)
            try:
                self.assertEqual(probe(self.lock), "busy")
            finally:
                p.kill()
                p.wait()

    def test_held_rejects_separately_opened_descriptor_while_another_holds(self):
        p = hold(self.lock, self.info)
        try:
            # A caller that merely opens the lock file on fd 9 must not pass as the holder.
            r = subprocess.run(["/bin/sh", "-c", f'exec 9<"{self.lock}"; "{sys.executable}" "{LOCKRUN}" held "{self.lock}" 9'])
            self.assertEqual(r.returncode, 1)
        finally:
            p.kill()
            p.wait()

    def test_held_rejects_separately_opened_descriptor_on_free_lock(self):
        self.lock.touch()
        r = subprocess.run(["/bin/sh", "-c", f'exec 9<"{self.lock}"; "{sys.executable}" "{LOCKRUN}" held "{self.lock}" 9'])
        self.assertEqual(r.returncode, 1)
        self.assertEqual(probe(self.lock), "free")

    def test_held_accepts_the_inherited_locked_descriptor(self):
        r = subprocess.run([sys.executable, str(LOCKRUN), "run", str(self.lock), str(self.info),
                            sys.executable, str(LOCKRUN), "held", str(self.lock), "9"])
        self.assertEqual(r.returncode, 0)

    def test_sigkilled_holder_frees_the_lock_at_once(self):
        p = hold(self.lock, self.info)
        os.kill(p.pid, signal.SIGKILL)
        p.wait()
        self.assertEqual(probe(self.lock), "free")
        r = subprocess.run([sys.executable, str(LOCKRUN), "run", str(self.lock), str(self.info), "true"])
        self.assertEqual(r.returncode, 0)


class RunnerLockTest(unittest.TestCase):
    def setUp(self):
        self.mac = FakeMac()
        for d in ("jobs", "done"):
            (self.mac.base / d).mkdir(parents=True, exist_ok=True)
        self.mac.ack()
        self.lock = self.mac.base / ".active.lock"
        self.info = self.mac.base / ".active.info"

    def tearDown(self):
        self.mac.cleanup()

    def test_job_runs_under_the_lock_and_codex_does_not_inherit_it(self):
        (self.mac.base / "jobs/job-a.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        self.assertTrue((self.mac.base / "done/job-a/.done").exists())
        self.assertEqual((self.mac.state / "lock_during_exec").read_text().strip(), "busy")
        self.assertFalse((self.mac.state / "fd9_in_codex").exists(), "codex must not hold the lock fd")
        self.assertEqual(probe(self.lock), "free")
        self.assertIn("pid ", self.info.read_text())

    def test_runner_skips_while_lock_is_held(self):
        p = hold(self.lock, self.info)
        try:
            (self.mac.base / "jobs/job-b.task").write_text("brief\n")
            run_runner(self.mac, "--once")
            self.assertTrue((self.mac.base / "jobs/job-b.task").exists())
            self.assertTrue(run_runner(self.mac, "--lock-state").stdout.startswith("busy"))
        finally:
            p.kill()
            p.wait()
        self.assertEqual(run_runner(self.mac, "--lock-state").stdout.strip(), "free")
        run_runner(self.mac, "--once")
        self.assertTrue((self.mac.base / "done/job-b/.done").exists())

    def test_surviving_executor_blocks_the_next_job(self):
        # e.g. --take-one was SIGKILLed: the lock is free but its codex exec still drives the screen.
        self.mac.flag("job_running")
        (self.mac.base / "jobs/job-o.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        self.assertTrue((self.mac.base / "jobs/job-o.task").exists())
        self.assertFalse((self.mac.state / "exec.args").exists())
        self.assertIn("still running", (self.mac.base / "logs/runner.log").read_text())
        self.mac.flag("job_running", False)
        run_runner(self.mac, "--once")
        self.assertTrue((self.mac.base / "done/job-o/.done").exists())

    def test_executor_check_with_real_pgrep(self):
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        self.assertEqual(run_runner(self.mac, "--executor-running", **env).returncode, 1, "must not match itself")
        fake = subprocess.Popen([sys.executable, "-c",
                                 "import os; os.execv('/bin/sh', ['codex', '-c', 'sleep 30; :', 'exec', '--model', "
                                 f"'m', '-C', '{self.mac.base}/done/job-z'])"])
        try:
            time.sleep(0.3)
            self.assertEqual(run_runner(self.mac, "--executor-running", **env).returncode, 0)
        finally:
            fake.kill()
            fake.wait()
        self.assertEqual(run_runner(self.mac, "--executor-running", **env).returncode, 1)

    def test_take_one_refuses_without_the_lock(self):
        (self.mac.base / "jobs/job-t.task").write_text("brief\n")
        for extra in ({}, {"QA_WORKER_LOCK_FD": "9"}):
            with self.subTest(extra=extra):
                r = run_runner(self.mac, "--take-one", **extra)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("use lockrun.py", r.stderr)
                self.assertTrue((self.mac.base / "jobs/job-t.task").exists())
                self.assertFalse((self.mac.state / "exec.args").exists())

    def test_runs_every_queued_job_in_one_cycle(self):
        for i in range(3):
            (self.mac.base / f"jobs/job-{i}.task").write_text("brief\n")
        run_runner(self.mac, "--once")
        for i in range(3):
            self.assertTrue((self.mac.base / f"done/job-{i}/.done").exists())


class InstallLockTest(unittest.TestCase):
    def setUp(self):
        self.mac = FakeMac()
        authorise_lead(self.mac)
        self.mac.base.mkdir(parents=True)

    def tearDown(self):
        self.mac.cleanup()

    def test_apply_waits_while_held_then_proceeds_when_free(self):
        p = hold(self.mac.base / ".active.lock", self.mac.base / ".active.info")
        try:
            r = run_install(self.mac, "--apply")
            self.assertEqual(r.returncode, 1)
            self.assertIn("still running", r.stdout)
            self.assertNotIn("bootstrap", self.mac.calls())
            self.assertFalse((self.mac.base / "pause").exists())
        finally:
            p.kill()
            p.wait()
        run_install(self.mac, "--apply")
        self.assertIn("bootstrap", self.mac.calls())
        self.assertTrue((self.mac.base / "lockrun.py").is_file())
        self.assertFalse((self.mac.base / "pause").exists())


if __name__ == "__main__":
    unittest.main()
