#!/usr/bin/env bash
# Run every check in the repository and print one line per check: PASS, FAIL, NOT RUN or N/A.
# NOT RUN means a dependency was missing; it is not a pass. N/A means the check does not
# apply on this operating system. Exit 1 if anything failed,
# or if anything did not run and --strict was given (CI uses --strict).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2

STRICT=0; [ "${1:-}" = "--strict" ] && STRICT=1
PY="python3"; [ -x .venv/bin/python ] && PY=".venv/bin/python"
LOG="$(mktemp -d)"; trap 'rm -rf "$LOG"' EXIT
# QA_CHECK_LOG_DIR keeps each check's full output (CI uploads it when a check fails).
KEEP="${QA_CHECK_LOG_DIR:-}"; [ -n "$KEEP" ] && mkdir -p "$KEEP"
failed=0; skipped=0
# The browser tests skip themselves without Chrome, which would read as a pass. Look for it here.
if [ "$(uname)" = "Darwin" ]; then CHROME_DEFAULT="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; else CHROME_DEFAULT="/usr/bin/google-chrome"; fi
CHROME="${CHROME_PATH:-$CHROME_DEFAULT}"

report() { printf '%-8s %s\n' "$1" "$2"; }
run() {   # run <name> <command...>
  local name="$1"; shift
  local rc=0
  "$@" >"$LOG/out" 2>&1 || rc=$?
  [ -n "$KEEP" ] && cp "$LOG/out" "$KEEP/${name// /-}.log"
  if [ "$rc" -eq 0 ]; then report PASS "$name"; return; fi
  report FAIL "$name"; failed=1
  # The lines that name what failed, then the end of the output.
  grep -n -E '^[[:space:]]*not ok|^(FAIL|ERROR):|# (fail|cancelled) [1-9]|failureType|\[run-tests\]|\[watchdog\]|Traceback' "$LOG/out" | head -30 | sed 's/^/    /'
  echo "    ..."; tail -40 "$LOG/out" | sed 's/^/    /'
}
skip() { report "NOT RUN" "$1 ($2)"; skipped=1; }

if "$PY" -c "import requests, bs4, lxml, markdown" 2>/dev/null; then
  run "python script tests" "$PY" -m unittest discover -s tests/python
else
  skip "python script tests" "install both requirements.txt files into .venv (see docs/maintaining.md)"
fi
run "build tests" "$PY" -m unittest discover -s tests/build
run "installer tests" "$PY" -m unittest discover -s tests/install
# The worker setup installs a macOS LaunchAgent and reads the macOS keychain and screen, so its
# tests are meaningful only on a Mac. Elsewhere this is "not applicable", which is not a skip.
if [ "$(uname)" = "Darwin" ]; then
  run "worker setup tests" "$PY" -m unittest discover -s tests/worker_setup
else
  report "N/A" "worker setup tests (macOS only)"
fi

if ! command -v node >/dev/null 2>&1; then
  skip "browser script tests" "node not found"
elif [ ! -d tests/node/node_modules/puppeteer-core ]; then
  skip "browser script tests" "run: (cd tests/node && npm ci)"
elif [ ! -x "$CHROME" ]; then
  skip "browser script tests" "Chrome not found at $CHROME; set CHROME_PATH"
else
  run "browser script tests" env CHROME_PATH="$CHROME" npm --prefix tests/node test
fi

run "package build scan" "$PY" tools/build.py --check
run "markdown links" "$PY" tools/check_links.py
# shellcheck disable=SC2317,SC2329  # called through run() below (older ShellCheck reports SC2317)
shell_syntax() { local f; while IFS= read -r f; do bash -n "$f" || return 1; done < <(git ls-files '*.sh'); }
run "shell syntax" shell_syntax
if command -v shellcheck >/dev/null 2>&1; then
  run "shellcheck" bash -c 'git ls-files "*.sh" | xargs shellcheck'
else
  skip "shellcheck" "shellcheck not found"
fi

find . -name __pycache__ -not -path './.venv/*' -not -path './tests/node/node_modules/*' -prune -exec rm -rf {} + 2>/dev/null
[ "$failed" -eq 0 ] || exit 1
[ "$STRICT" -eq 1 ] && [ "$skipped" -eq 1 ] && { echo "strict mode: a check did not run"; exit 1; }
exit 0
