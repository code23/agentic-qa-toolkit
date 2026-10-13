#!/usr/bin/env python3
"""One locked job's sensitive lifetime. No transcript, prompt file, or archive.

All briefs are private; ACCESS is an optional leading JSON header that declares
inline non-production credentials for literal redaction. Undeclared credentials
are forbidden by the brief contract; content-based secret guessing is not used.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
EFFORTS = {"minimal", "low", "medium", "high", "xhigh"}


def access_header(value: str) -> list[str]:
    """Reject ambiguous declarations; production accepts references only."""
    d = json.loads(value)
    if not isinstance(d, dict):
        raise ValueError("invalid access")
    env = d.get("environment")
    if env == "production":
        if set(d) != {"environment", "secureReference"} or not isinstance(d["secureReference"], str) or not d["secureReference"]:
            raise ValueError("production requires secureReference")
        return []
    if env not in {"test", "staging", "demo"} or set(d) != {"environment", "username", "password"}:
        raise ValueError("invalid access")
    values = [d["username"], d["password"]]
    if any(not isinstance(v, str) or not v or len(v) > 4096 for v in values):
        raise ValueError("invalid credentials")
    return values


def blocked(reason: str) -> dict:
    return {"status": "blocked", "observations": [], "blockers": [reason], "evidence": []}


def redact(value, secrets):
    if isinstance(value, str):
        forms = set(secrets)
        for secret in secrets:
            # A copied ACCESS JSON literal inside a report string has already
            # been decoded once by json.loads(result.json). Match that escaped
            # representation too, including non-ASCII JSON escapes.
            forms.add(json.dumps(secret, ensure_ascii=True)[1:-1])
            forms.add(json.dumps(secret, ensure_ascii=False)[1:-1])
        for secret in sorted(forms, key=len, reverse=True):
            value = value.replace(secret, "<redacted>")
        return value
    if isinstance(value, list):
        return [redact(x, secrets) for x in value]
    if isinstance(value, dict):
        return {redact(k, secrets): redact(v, secrets) for k, v in value.items()}
    return value


def contract(data) -> dict:
    """Validate types before projecting each level to the actual result contract."""
    def strings(value):
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if not isinstance(data, dict) or data.get("status") not in ("completed", "partial", "blocked"):
        raise ValueError("invalid status")
    observations = data.get("observations")
    if not isinstance(observations, list) or not strings(data.get("blockers")) or not strings(data.get("evidence")):
        raise ValueError("invalid result")
    canonical = []
    for item in observations:
        if not isinstance(item, dict) or not isinstance(item.get("check"), str) or not isinstance(item.get("observed"), str):
            raise ValueError("invalid observation")
        if "as_expected" not in item or not isinstance(item["as_expected"], (bool, type(None))) or not strings(item.get("evidence")):
            raise ValueError("invalid observation")
        canonical.append({k: item[k] for k in ("check", "observed", "as_expected", "evidence")})
    if data["status"] in ("completed", "partial") and not canonical:
        raise ValueError("missing observations")
    if data["status"] == "blocked" and not canonical and not data["blockers"]:
        raise ValueError("missing blocker")
    return {"status": data["status"], "observations": canonical,
            "blockers": data["blockers"], "evidence": data["evidence"]}


def plain_dir(path: Path) -> None:
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise OSError("unsafe directory")


DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def same_inode(a, b) -> bool:
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def read_marker(parent: int, name: str) -> dict:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_size > 2048:
            raise OSError("unsafe marker")
        return json.loads(fh.read(2049))


def register_private(base: Path, private: Path) -> None:
    """A non-secret sibling proof survives unreadable roots and partial purges."""
    plain_dir(base)
    plain_dir(base / "tmp")
    st = private.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise OSError("unsafe private directory")
    data = {"kind": "qa-worker-private-v2", "folder": private.name, "uid": os.getuid(),
            "device": st.st_dev, "inode": st.st_ino}
    parent = os.open(base / "tmp", DIR_FLAGS)
    try:
        fd = os.open(private.name + ".owner.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
    finally:
        os.close(parent)


def cleanup_warning() -> None:
    try:
        sys.stderr.write("Private cleanup pending; worker recovery required\n")
    except Exception:
        pass


def owned_directory(parent: int, name: str, expected=None, retained=None) -> int:
    """Call only within a proven private tree; never chmod a symlink target."""
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode) or before.st_uid != os.getuid():
        raise OSError("unsafe directory")
    if expected is not None:
        if not same_inode(before, expected):
            raise OSError("root changed")
        # A retained creation descriptor permits mode-000 cleanup without a
        # pathname chmod. Restart recovery without one must fail closed.
        fd = os.dup(retained) if retained is not None else os.open(name, DIR_FLAGS, dir_fd=parent)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISDIR(opened.st_mode) or opened.st_uid != os.getuid()
                    or not same_inode(opened, expected)):
                raise OSError("root changed")
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not same_inode(current, expected):
                raise OSError("root changed")
            if opened.st_mode & 0o700 != 0o700:
                os.fchmod(fd, stat.S_IMODE(opened.st_mode) | 0o700)
            return fd
        except Exception:
            os.close(fd)
            raise
    if before.st_mode & 0o700 != 0o700:
        os.chmod(name, stat.S_IMODE(before.st_mode) | 0o700, dir_fd=parent, follow_symlinks=False)
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    opened = os.fstat(fd)
    if not same_inode(opened, before) or opened.st_uid != os.getuid():
        os.close(fd)
        raise OSError("directory changed")
    return fd


def purge_entries(directory: int, keep: set[str]) -> None:
    for name in os.listdir(directory):
        if name in keep:
            continue
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if before.st_uid != os.getuid():
            raise OSError("foreign owned entry")
        if stat.S_ISDIR(before.st_mode):
            child = owned_directory(directory, name)
            try:
                purge_entries(child, set())
            finally:
                os.close(child)
            current = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not same_inode(current, before):
                raise OSError("entry changed")
            os.rmdir(name, dir_fd=directory)
        else:
            # Unlink only this owned entry. Symlink targets and other hardlinks
            # are neither opened nor chmodded.
            current = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not same_inode(current, before):
                raise OSError("entry changed")
            os.unlink(name, dir_fd=directory)


def purge_private(base: Path, private: Path, retained=None) -> bool:
    """Fail closed and quiet; all exception text may contain credential paths.

    Keep ownership proof until removal and absence are verified. Recovery uses
    the same checks and never archives or follows private symlink targets.
    """
    parent = root = None
    try:
        plain_dir(base)
        plain_dir(base / "tmp")
        if private.parent != base / "tmp" or not re.fullmatch(r"active-[A-Za-z0-9_-]+", private.name):
            return False
        parent = os.open(base / "tmp", DIR_FLAGS)
        if os.fstat(parent).st_uid != os.getuid():
            return False
        owner_name = private.name + ".owner.json"
        outer = True
        try:
            marker = read_marker(parent, owner_name)
        except FileNotFoundError:
            outer = False
            marker = None
        try:
            before = os.stat(private.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            if not outer:
                return True
            if not isinstance(marker, dict) or set(marker) != {"kind", "folder", "uid", "device", "inode"}:
                return False
            if marker["kind"] != "qa-worker-private-v2" or marker["folder"] != private.name or marker["uid"] != os.getuid():
                return False
            os.unlink(owner_name, dir_fd=parent)
            return True
        if not stat.S_ISDIR(before.st_mode) or before.st_uid != os.getuid():
            return False
        expected = {"kind": "qa-worker-private-v2", "folder": private.name, "uid": os.getuid(),
                    "device": before.st_dev, "inode": before.st_ino}
        if outer:
            if marker != expected:
                return False
            root = owned_directory(parent, private.name, before, retained)
        else:
            # Legacy proof may only be read from an already-accessible root;
            # unrelated unmarked roots are never chmodded to inspect them.
            root = os.open(private.name, DIR_FLAGS, dir_fd=parent)
            if not same_inode(os.fstat(root), before):
                return False
            legacy = read_marker(root, ".qa-worker-private.json")
            if legacy != {"kind": "qa-worker-private-v1", "folder": private.name, "uid": os.getuid()}:
                return False
            os.fchmod(root, stat.S_IMODE(before.st_mode) | 0o700)
            # Upgrade a verified legacy root before deleting its inner proof.
            # An rmdir failure must leave recoverable identity outside the root.
            fd = os.open(owner_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            with os.fdopen(fd, "w") as fh:
                json.dump(expected, fh)
            outer = True
        purge_entries(root, {".qa-worker-private.json"})
        # Delete the inner proof last; the sibling proof remains for v2 roots.
        try:
            inner = os.stat(".qa-worker-private.json", dir_fd=root, follow_symlinks=False)
        except FileNotFoundError:
            inner = None
        if inner is not None:
            if inner.st_uid != os.getuid():
                return False
            os.unlink(".qa-worker-private.json", dir_fd=root)
        current = os.stat(private.name, dir_fd=parent, follow_symlinks=False)
        if not same_inode(current, before):
            return False
        os.rmdir(private.name, dir_fd=parent)
        try:
            os.stat(private.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            if outer:
                os.unlink(owner_name, dir_fd=parent)
            try:
                os.stat(owner_name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return True
            return False
        return False
    except Exception:
        return False
    finally:
        for fd in (root, parent):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


def take_brief(job: Path) -> str:
    """Unlink only the owned queue entry, never follow a job symlink."""
    plain_dir(job.parent)
    st = job.lstat()
    stage = job.parent / ("." + job.name[:-5] + ".tmp")
    companion = None
    if st.st_nlink == 2:
        try:
            candidate = stage.lstat()
            if stat.S_ISREG(candidate.st_mode) and candidate.st_uid == os.getuid() and (candidate.st_dev, candidate.st_ino) == (st.st_dev, st.st_ino):
                companion = candidate
        except FileNotFoundError:
            # Receiver may just have unlinked the companion after publication.
            st = job.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or (st.st_nlink != 1 and companion is None):
        # A symlink is an owned queue entry; remove that link, never its target.
        if (stat.S_ISLNK(st.st_mode) or stat.S_ISREG(st.st_mode)) and st.st_uid == os.getuid():
            job.unlink()
        raise OSError("unsafe job")
    fd = os.open(job, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
            raise OSError("job changed")
        if companion is not None:
            try:
                current = stage.lstat()
                if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
                    stage.unlink()
            except FileNotFoundError:
                pass
        job.unlink()  # no pathname copy survives any later validation or cancellation
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1
            return fh.read()
    finally:
        if fd >= 0:
            os.close(fd)


def recover(base: Path) -> bool:
    """Only runner-created private directories, with a matching ownership marker.

    Caller holds the kernel job lock and has checked for surviving executors.
    Never archive private folders, including after an uncatchable termination.
    """
    plain_dir(base)
    plain_dir(base / "tmp")
    complete = True
    for private in (base / "tmp").glob("active-*"):
        if private.name.endswith(".owner.json"):
            private = private.with_name(private.name[:-11])
        try:
            # Only known ownership proofs permit cleanup or hold new jobs.
            if not (private.with_name(private.name + ".owner.json").exists() or
                    (private / ".qa-worker-private.json").is_file()):
                continue
            complete = purge_private(base, private) and complete
        except Exception:
            complete = False
    return complete


def main(argv: list[str]) -> int:
    base, job, codex, model, version = Path(argv[1]), Path(argv[2]), argv[3], argv[4], argv[5]
    private = None
    private_fd = None
    child = None
    out = None
    result = blocked("Job did not finish")
    rc = 1
    started = int(time.time())
    secrets = []
    requested = ""
    effort = "medium"
    cleanup_ok = True

    def cancelled(signum, _frame):
        raise InterruptedError(signum)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, cancelled)
    try:
        for directory in (base, base / "jobs", base / "done", base / "tmp"):
            plain_dir(directory)
        text = take_brief(job)
        jid = job.name[:-5]
        if not ID.fullmatch(jid):
            return 0  # no retained copy, including for invalid names
        out = base / "done" / jid
        if out.exists() or out.is_symlink():
            out = None
            return 0  # duplicate brief purged; previous evidence untouched
        out.mkdir(mode=0o700)
        lines = text.splitlines(keepends=True)
        headers = []
        while lines and lines[0].startswith(("EFFORT=", "MODEL=", "ACCESS=")):
            headers.append(lines.pop(0).rstrip("\r\n"))
        access = [h[7:] for h in headers if h.startswith("ACCESS=")]
        if len(access) > 1:
            raise ValueError("duplicate access")
        if access:
            secrets = access_header(access[0])
        for header in headers:
            if header.startswith("EFFORT=") and header[7:] in EFFORTS:
                effort = header[7:]
            if header.startswith("MODEL=") and MODEL.fullmatch(header[6:]):
                requested = header[6:]
        if os.environ.get("QA_WORKER_ACK_MISSING"):
            result, rc = blocked("QA worker runner setup: unsandboxed execution has not been acknowledged on this worker; "
                                 "run worker/install.sh --apply --accept-unsandboxed; the job was not run"), 78
        elif os.environ.get("QA_WORKER_PATTERN_ERROR"):
            result, rc = blocked("QA worker runner setup: the model pattern file could not be read; the job was not run"), 78
        elif not codex:
            result, rc = blocked("QA worker runner setup: Codex CLI not found"), 127
        elif not model:
            pattern = "".join(c for c in os.environ.get("QA_WORKER_PATTERN_USED", "") if " " <= c <= "~")[:80]
            result, rc = blocked("QA worker runner setup: no listed model matched (pattern: %s); the job was not run"
                                 % (pattern or "none set")), 78
        else:
            help_result = subprocess.run([codex, "exec", "--help"], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, timeout=10)
            if help_result.returncode or b"--ephemeral" not in help_result.stdout:
                raise ValueError("ephemeral execution unavailable")
            private = Path(tempfile.mkdtemp(prefix="active-", dir=base / "tmp"))
            register_private(base, private)
            private_fd = os.open(private, DIR_FLAGS)
            (private / ".qa-worker-private.json").write_text(json.dumps(
                {"kind": "qa-worker-private-v1", "folder": private.name, "uid": os.getuid()}))
            baseline = base / "runtime-instructions.md"
            prompt = (baseline.read_text() + "\n\n---\n\nTASK BRIEF:\n") if baseline.is_file() else ""
            # Credentials remain directly in the in-memory brief sent on stdin.
            prompt += ("ACCESS=" + access[0] + "\n") if access else ""
            prompt += "".join(lines)
            child = subprocess.Popen([codex, "exec", "--model", model,
                                      "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check",
                                      "--ephemeral", "-C", str(private), "-c", "model_reasoning_effort=" + effort,
                                      "-c", 'history.persistence="none"',
                                      "-c", "log_dir=" + json.dumps(str(private / "native-log")),
                                      "-c", "sqlite_home=" + json.dumps(str(private / "native-state")), "-"],
                                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
            child.communicate(prompt.encode("utf-8"))
            rc = child.returncode
            rp = private / "result.json"
            if rp.is_symlink() or not rp.is_file() or rp.stat().st_nlink != 1 or rp.stat().st_size > 1048576:
                result = blocked("Executor did not produce a safe result.json")
            else:
                result = contract(json.loads(rp.read_text()))
                result = redact(result, secrets)
                evidence = result.get("evidence")
                kept = []
                if isinstance(evidence, list):
                    for name in evidence:
                        if not isinstance(name, str) or not ID.fullmatch(name) or not name.endswith(".png"):
                            continue
                        if any(secret in name for secret in secrets):
                            continue
                        source = private / name
                        if source.is_symlink() or not source.is_file() or source.stat().st_nlink != 1:
                            continue
                        # This detects plaintext canaries, not text rendered in pixels.
                        # The executor must still never capture credentials/login forms.
                        if secrets and any(secret.encode() in source.read_bytes() for secret in secrets):
                            continue
                        shutil.copyfile(source, out / name)
                        kept.append(name)
                result["evidence"] = kept
                if isinstance(result.get("observations"), list):
                    for observation in result["observations"]:
                        if isinstance(observation, dict):
                            names = observation.get("evidence", [])
                            observation["evidence"] = [n for n in names if n in kept] if isinstance(names, list) else []
    except InterruptedError:
        result, rc = blocked("Job cancelled by signal"), 130
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        # Exception messages can contain brief values: never retain or print them.
        result, rc = blocked("Job input or executor result rejected"), 65
    finally:
        # Ignore repeat termination while draining the owned process group and files.
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        try:
            if child is not None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
        except Exception:
            cleanup_ok = False
        if cleanup_ok and private is not None:
            cleanup_ok = purge_private(base, private, private_fd)
        if private_fd is not None:
            try:
                os.close(private_fd)
            except Exception:
                cleanup_ok = False
        if not cleanup_ok:
            # Never pass the underlying exception/path to logs or a report.
            cleanup_warning()
        if cleanup_ok and out is not None:
            result = redact(result, secrets)
            (out / "result.json").write_text(json.dumps(result) + "\n")
            (out / "output.txt").write_text("Executor output discarded for credential safety\nEXIT=%s\n" % rc)
            receipt = {"job": out.name, "runner_version": version, "model": model,
                       "requested_model": requested, "effort": effort, "exit_code": rc,
                       "started_at": started, "finished_at": int(time.time()),
                       "note": "Executor exit status is not a QA verdict; raw output is discarded."}
            (out / "receipt.json").write_text(json.dumps(redact(receipt, secrets)) + "\n")
            (out / ".done").touch()
    return 0 if cleanup_ok else 75


def entry(argv: list[str]) -> int:
    try:
        if len(argv) == 3 and argv[1] == "--recover":
            # The runner calls recovery only after taking the kernel job lock
            # and checking for surviving executors. A standalone call cannot
            # delete a live job's private directory.
            from lockrun import held
            if not held(str(Path(argv[2]) / ".active.lock"), os.environ.get("QA_WORKER_LOCK_FD", "-1")):
                cleanup_warning()
                return 75
            if recover(Path(argv[2])):
                return 0
            cleanup_warning()
            return 75
        return main(argv)
    except Exception:
        # Catch report/marker/entry errors too; traceback paths can be secrets.
        cleanup_warning()
        return 75


if __name__ == "__main__":
    sys.exit(entry(sys.argv))
