#!/usr/bin/env bash
# Run every check in the repository and print one line per check: PASS, FAIL or NOT RUN.
# NOT RUN means a dependency was missing; it is not a pass. Exit 1 if anything failed,
# or if anything did not run and --strict was given (CI uses --strict).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2

STRICT=0; [ "${1:-}" = "--strict" ] && STRICT=1
PY="python3"; [ -x .venv/bin/python ] && PY=".venv/bin/python"
LOG="$(mktemp -d)"; trap 'rm -rf "$LOG"' EXIT
failed=0; skipped=0
# The browser tests skip themselves without Chrome, which would read as a pass. Look for it here.
if [ "$(uname)" = "Darwin" ]; then CHROME_DEFAULT="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; else CHROME_DEFAULT="/usr/bin/google-chrome"; fi
CHROME="${CHROME_PATH:-$CHROME_DEFAULT}"

report() { printf '%-8s %s\n' "$1" "$2"; }
run() {   # run <name> <command...>
  local name="$1"; shift
  if "$@" >"$LOG/out" 2>&1; then report PASS "$name"
  else report FAIL "$name"; sed 's/^/    /' "$LOG/out" | tail -40; failed=1; fi
}
skip() { report "NOT RUN" "$1 ($2)"; skipped=1; }

if "$PY" -c "import requests, bs4, lxml, markdown" 2>/dev/null; then
  run "python script tests" "$PY" -m unittest discover -s tests/python
else
  skip "python script tests" "install both requirements.txt files into .venv (see docs/maintaining.md)"
fi
run "build tests" "$PY" -m unittest discover -s tests/build
run "installer tests" "$PY" -m unittest discover -s tests/install
run "worker setup tests" "$PY" -m unittest discover -s tests/worker_setup

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
# shellcheck disable=SC2329  # called through run() below
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
