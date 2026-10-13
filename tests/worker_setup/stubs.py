"""Shared helpers: a fake worker Mac built from PATH stubs, so tests never depend on this Mac."""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "editions/dedicated-mac/extras/worker-setup"

FAKE_CODEX = r"""#!/bin/bash
# Fake bundled Codex CLI. Behaviour switches come from files in $FAKE_STATE.
S=$FAKE_STATE
echo "codex $*" >> "$S/calls.log"
case "$1" in
  --version) echo "codex-cli 9.9.9" ;;
  login) [ -e "$S/logged_out" ] && { echo "Not logged in"; exit 1; }; echo "Logged in using ChatGPT" ;;
  plugin)
    if [ "$2" = list ]; then
      echo "Marketplace \`openai-bundled\`"
      echo "/somewhere/marketplace"
      echo ""
      echo "PLUGIN                               STATUS              VERSION  SOURCE"
      echo "chrome@openai-bundled                installed, enabled  1.0.0    /somewhere/chrome"
      if [ -e "$S/plugin_missing" ]; then
        echo "computer-use@openai-bundled          not installed                /somewhere/plugins/computer-use"
      elif [ -e "$S/plugin_disabled" ]; then
        echo "computer-use@openai-bundled          installed, disabled 1.0.0    /somewhere/plugins/computer-use"
      elif [ -e "$S/plugin_unified" ]; then
        echo "unified-computer-use@openai-bundled  installed, enabled  2.0.0    /somewhere/plugins/unified"
      else
        echo "computer-use@openai-bundled          installed, enabled  1.0.0    /somewhere/plugins/computer-use"
      fi
    elif [ "$2" = add ]; then
      [ -e "$S/classic_add_fails" ] && [ "$3" = computer-use@openai-bundled ] && { echo "error: plugin not found" >&2; exit 1; }
      rm -f "$S/plugin_missing"; echo "added $3"
    fi ;;
  debug)
    [ -e "$S/catalog_garbage" ] && { echo "not json"; exit 0; }
    # Race: the pattern file becomes unreadable while a job's catalogue query runs (the runner's
    # self-check makes the first query, the job the second).
    n=$(cat "$S/debug_calls" 2>/dev/null || echo 0); echo $((n + 1)) > "$S/debug_calls"
    [ -e "$S/lock_pattern_during_catalog" ] && [ "$n" -ge 1 ] && chmod 000 "$QA_WORKER_BASE/model-pattern"
    cat <<'EOF'
{"models": [
 {"slug": "model-alpha", "visibility": "list", "priority": 0},
 {"slug": "model-beta", "visibility": "list", "priority": 1},
 {"slug": "model-gamma", "visibility": "list", "priority": 2},
 {"slug": "model-delta", "visibility": "list", "priority": 3},
 {"slug": "model-hidden", "visibility": "hide", "priority": -1}
]}
EOF
    ;;
  exec)
    if [ "$2" = --help ]; then
      [ -e "$S/no_ephemeral" ] || echo '--ephemeral Run without persisting session files'
      exit 0
    fi
    dir=""; prev=""
    for a in "$@"; do [ "$prev" = "-C" ] && dir=$a; prev=$a; done
    printf '%s\n' "$@" > "$S/exec.args"
    python3 "$QA_WORKER_TEST_LOCKRUN" probe "$QA_WORKER_BASE/.active.lock" > "$S/lock_during_exec"
    { : >&9; } 2>/dev/null && echo open > "$S/fd9_in_codex"
    cat > "$S/exec.stdin"
    echo "transcript line with the brief" >&2
    printf '{"status": "completed", "observations": [{"check": "synthetic fixture", "observed": "stub executor completed", "as_expected": true, "evidence": []}], "blockers": [], "evidence": []}\n' > "$dir/result.json"
    echo "final message"
    exit "${FAKE_EXEC_RC:-0}" ;;
esac
"""

STUBS = {
    "sw_vers": 'echo "${FAKE_MACOS:-26.5}"',
    "id": r'''case "$1" in
  -un) echo worker ;;
  -u) echo "${FAKE_UID:-502}" ;;
  -Gn) echo "${FAKE_GROUPS:-staff everyone}" ;;
  *) exec /usr/bin/id "$@" ;;
esac''',
    "defaults": r'''S=$FAKE_STATE
case "$*" in
  *autoLoginUser*) [ -e "$S/no_autologin" ] || echo worker ;;
  *"read com.apple.screensaver idleTime"*) [ -e "$S/screensaver_written" ] && echo 0 || echo "${FAKE_IDLE:-0}" ;;
  *"write com.apple.screensaver"*) echo "defaults $*" >> "$S/calls.log"; touch "$S/screensaver_written" ;;
  *CFBundleShortVersionString*) echo 1.2.3 ;;
  *) exit 1 ;;
esac''',
    "fdesetup": 'echo "FileVault is Off."',
    "scutil": 'cat >/dev/null; echo "  Name : ${FAKE_CONSOLE:-worker}"',
    "pmset": r'''echo "pmset $*" >> "$FAKE_STATE/calls.log"
[ "$1" = -g ] || exit 0
echo "System-wide power settings:"
echo " sleep                ${FAKE_SLEEP:-0}"
echo " displaysleep         ${FAKE_DISPLAYSLEEP:-0}"''',
    "sysadminctl": 'echo "2026-01-01 sysadminctl[1:2] screenLock is off" >&2',
    "mdfind": 'printf "%s\\n" "$FAKE_APP"',
    "launchctl": r'''S=$FAKE_STATE
echo "launchctl $*" >> "$S/calls.log"
case "$1" in
  print) label=${2##*/}; grep -qx "$label" "$S/loaded" 2>/dev/null ;;
  bootstrap) label=$(basename "$3" .plist); echo "$label" >> "$S/loaded" ;;
  bootout) label=${2##*/}
    grep -qx "$label" "$S/stuck" 2>/dev/null && exit 0  # pretends success but stays loaded
    grep -vx "$label" "$S/loaded" > "$S/loaded.tmp" 2>/dev/null; mv "$S/loaded.tmp" "$S/loaded" ;;
esac''',
    "nc": "exit 0",
    "xcode-select": "echo /Library/Developer/CommandLineTools",
    # "Running" when flagged.
    "pgrep": '[ -e "$FAKE_STATE/job_running" ]',
    "sudo": 'echo "sudo $*" >> "$FAKE_STATE/calls.log"; exit 1',
    "screencapture": 'for a; do f=$a; done; printf "PNGDATA" > "$f"',
    "security": r'''case "$1" in
  default-keychain) echo '    "/tmp/fake/login.keychain-db"' ;;
  # show-keychain-info succeeds even for a locked keychain, which is why it must not be trusted.
  show-keychain-info) echo "Keychain no-timeout" >&2 ;;
esac''',
}


class FakeMac:
    """A temp HOME plus a stub bin dir and a fake ChatGPT.app bundle."""

    def __init__(self, legacy_cli_path: bool = False) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="qa-worker-test-"))
        self.home = self.tmp / "home"
        self.state = self.tmp / "state"
        self.bin = self.tmp / "bin"
        for d in (self.home, self.state, self.bin):
            d.mkdir()
        self.app = self.tmp / "Apps" / "ChatGPT.app"
        cli = self.app / "Contents/Resources" / ("codex" if legacy_cli_path else "codex-cli/bin/codex")
        cli.parent.mkdir(parents=True)
        self._write(cli, FAKE_CODEX)
        for name, body in STUBS.items():
            self._write(self.bin / name, "#!/bin/bash\n" + body + "\n")
        self._write(self.bin / "python3", f'#!/bin/bash\nexec "{sys.executable}" "$@"\n')
        # Keychain lock-state probe (the real one asks the Security framework of the host Mac).
        self.kc_probe = self.tmp / "kc-probe"
        self._write(self.kc_probe, '#!/bin/bash\ncat "$FAKE_STATE/kc_state" 2>/dev/null || echo unlocked\n')
        self.base = self.home / "qa-worker"

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.write_text(text)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def ack(self) -> None:
        """Record the unsandboxed-execution acknowledgement, as install.sh --accept-unsandboxed does."""
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "unsandboxed-ack").write_text("accepted unsandboxed execution on 2026-01-01 by runner test\n")

    def keychain(self, state: str) -> None:
        (self.state / "kc_state").write_text(state + "\n")

    def flag(self, name: str, on: bool = True) -> None:
        p = self.state / name
        if on:
            p.touch()
        elif p.exists():
            p.unlink()

    def env(self, **extra: str) -> dict:
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.home),
            "FAKE_STATE": str(self.state),
            "FAKE_APP": str(self.app),
            "QA_WORKER_SELFCHECK_WAIT": "1",
            "QA_WORKER_APPLY_WAIT": "2",
            "QA_WORKER_KEYCHAIN_PROBE": str(self.kc_probe),
            "QA_WORKER_TEST_LOCKRUN": str(ROOT / "worker/lockrun.py"),
            "LANG": "C",
        }
        env.update(extra)
        return env

    def calls(self) -> str:
        p = self.state / "calls.log"
        return p.read_text() if p.exists() else ""

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def tree(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


def rows(json_text: str) -> dict:
    data = json.loads(json_text)
    return {r["id"]: r for r in data["results"]}


def make_exec(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
