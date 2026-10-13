#!/usr/bin/env python3
"""Kernel-backed job lock for the QA worker runner (stdlib only, works with macOS /usr/bin/python3).

    lockrun.py probe <lockfile>                         prints "free" or "busy"
    lockrun.py run <lockfile> <infofile> <cmd> [args]   runs cmd while holding the lock;
                                                        exits 75 at once if it is busy
    lockrun.py held <lockfile> <fd>                     exit 0 only if fd is that file and
                                                        it is locked (used by --take-one)

The lock is flock(LOCK_EX) on a plain file that is never deleted. The kernel drops it when the
holder exits or is killed, so a stale lock cannot exist. `run` hands the locked descriptor to
cmd as fd 9 (QA_WORKER_LOCK_FD=9) and execs it, so the lock lives exactly as long as cmd.
The info file is for display only; nothing decides anything from it.
"""
import fcntl
import os
import sys
import time

LOCK_FD = 9
EX_TEMPFAIL = 75


def probe(path: str) -> str:
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return "free"
    except OSError:
        return "busy"
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return "free"
    except OSError:
        return "busy"  # held, or any error: be conservative
    finally:
        os.close(fd)


def held(path: str, fd: str) -> bool:
    """fd is open on the lock file itself AND its open file description owns the lock.

    flock locks belong to an open file description. Re-locking the inherited descriptor
    succeeds only if that description already holds the lock; a separately opened
    descriptor on the same file fails with EWOULDBLOCK while someone else holds it.
    Never unlock here: that would release the caller's real lock."""
    try:
        n = int(fd)
        a, b = os.fstat(n), os.stat(path)
    except (OSError, ValueError):
        return False
    if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
        return False
    if probe(path) != "busy":  # nobody holds it, so this descriptor cannot be the holder
        return False
    try:
        fcntl.flock(n, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def run(path: str, info: str, cmd: list) -> int:
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return EX_TEMPFAIL
    with open(info, "w") as fh:
        fh.write(f"pid {os.getpid()} since {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
    if fd != LOCK_FD:
        os.dup2(fd, LOCK_FD)
        os.close(fd)
    os.set_inheritable(LOCK_FD, True)
    os.environ["QA_WORKER_LOCK_FD"] = str(LOCK_FD)
    os.execvp(cmd[0], cmd)  # same pid: the lock now belongs to cmd


def main(argv: list) -> int:
    if len(argv) == 3 and argv[1] == "probe":
        print(probe(argv[2]))
        return 0
    if len(argv) == 4 and argv[1] == "held":
        return 0 if held(argv[2], argv[3]) else 1
    if len(argv) >= 5 and argv[1] == "run":
        return run(argv[2], argv[3], argv[4:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
