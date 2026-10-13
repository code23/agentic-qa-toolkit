#!/bin/bash
# QA worker setup.
#
#   worker/install.sh            CHECK ONLY (default). Read-only: prints one row per requirement
#                                with PASS / FAIL / WARN / MANUAL and the exact fix.
#   worker/install.sh --apply    Fix everything scriptable (idempotent), print the numbered manual
#                                steps scripts cannot do, then re-run the checks.
#   worker/install.sh --apply --accept-unsandboxed
#                                Required once: acknowledges that jobs run with the agent CLI's
#                                approvals and sandbox off. Without it --apply changes nothing.
#   worker/install.sh --json     Machine-readable output (combine with --apply if wanted).
#   worker/install.sh --base DIR Queue folder (default ~/qa-worker, or $QA_WORKER_BASE).
#
# Run it on the worker Mac as the dedicated worker user, ideally in Terminal in the GUI session.
# Over SSH it still works, but GUI-only facts come from the runner's self-check file.
# Exit 0 only if no row is FAIL. Compatible with macOS stock /bin/bash 3.2.
#
# Every external command is called by name (never an absolute path) so tests can put stubs
# first on PATH. Overrides: QA_WORKER_BASE, QA_WORKER_APP_PATH, QA_WORKER_CODEX.

HERE=$(cd "$(dirname "$0")" && pwd)
RUNNER_SRC=$HERE/runner.sh
LOCKRUN_SRC=$HERE/lockrun.py
JOBRUN_SRC=$HERE/jobrun.py
PLIST_TEMPLATE=$HERE/launchagent.plist.template
INSTRUCTIONS_TEMPLATE=$HERE/runtime-instructions.template.md

LABEL="local.qa-worker.runner"
MIN_MACOS_MAJOR=14
SELFCHECK_MAX_AGE=${QA_WORKER_SELFCHECK_MAX_AGE:-86400}

APPLY=0
ACCEPT=0
JSON=0
BASE=${QA_WORKER_BASE:-$HOME/qa-worker}
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --accept-unsandboxed) ACCEPT=1 ;;
    --json) JSON=1 ;;
    --base) shift; BASE=$1 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done
BASE=${BASE%/}
case "$BASE" in
  /*) ;;
  *) echo "--base must be an absolute path" >&2; exit 2 ;;
esac
if printf '%s' "$BASE" | grep -q '[^A-Za-z0-9/._ -]'; then
  echo "--base may only contain letters, digits, space and / . _ -" >&2; exit 2
fi

LA_DIR=$HOME/Library/LaunchAgents
PLIST=$LA_DIR/$LABEL.plist
ME=$(id -un)
UID_NUM=$(id -u)
SELFCHECK_FILE=$BASE/logs/gui-selfcheck.json
OVER_SSH=0
[ -n "$SSH_CONNECTION" ] && OVER_SSH=1

# ---------------------------------------------------------------- result table
R_ID=(); R_NAME=(); R_STATUS=(); R_DETAIL=(); R_FIX=()
add() {
  local n=${#R_ID[@]}
  R_ID[n]=$1; R_NAME[n]=$2; R_STATUS[n]=$3; R_DETAIL[n]=$4; R_FIX[n]=$5
}
reset_results() { R_ID=(); R_NAME=(); R_STATUS=(); R_DETAIL=(); R_FIX=(); }

say() { if [ "$JSON" = 1 ]; then printf '%s\n' "$*" >&2; else printf '%s\n' "$*"; fi; }

json_str() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=$(printf '%s' "$s" | tr '\t\r\n' '   ' | tr -d '\000-\010\013\014\016-\037')
  printf '"%s"' "$s"
}

redact() { sed -E 's/[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}/<redacted>/g'; }

# Flat-JSON reader for the self-check file (one key per line, written by runner.sh).
sc_get() {
  [ -f "$SELFCHECK_FILE" ] || return
  sed -n -e "s/^ *\"$1\": *\"\(.*\)\",\{0,1\}$/\1/p" -e "s/^ *\"$1\": *\([^\",]*\),\{0,1\}$/\1/p" "$SELFCHECK_FILE" | head -1
}

file_mtime() { stat -f %m "$1" 2>/dev/null || echo 0; }

agent_loaded() { launchctl print "gui/$UID_NUM/$1" >/dev/null 2>&1; }

job_running() { bash "$RUNNER_SRC" --executor-running; }  # one shared implementation

# ---------------------------------------------------------------- checks
APP=""; CODEX=""

check_macos() {
  local v major
  v=$(sw_vers -productVersion 2>/dev/null)
  major=${v%%.*}
  if [ -z "$v" ]; then
    add macos "macOS version" FAIL "sw_vers unavailable" "Run this on macOS $MIN_MACOS_MAJOR or later."
  elif [ "$major" -ge "$MIN_MACOS_MAJOR" ] 2>/dev/null; then
    add macos "macOS version" PASS "macOS $v" ""
  else
    add macos "macOS version" FAIL "macOS $v" "Update to macOS $MIN_MACOS_MAJOR or later (System Settings > General > Software Update)."
  fi
}

check_user() {
  local admin=no
  case " $(id -Gn 2>/dev/null) " in *" admin "*) admin=yes ;; esac
  if [ "$admin" = yes ] || [ "$UID_NUM" = 501 ]; then
    add user "Dedicated worker user" WARN "uid $UID_NUM, admin=$admin (looks like a main or admin account)" \
      "Use a dedicated standard (non-admin) macOS user that exists only to run the QA worker; do admin tasks from another account."
  else
    add user "Dedicated worker user" PASS "uid $UID_NUM, standard user" ""
  fi
}

check_autologin() {
  local al fv
  al=$(defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser 2>/dev/null)
  fv=$(fdesetup status 2>/dev/null)
  if [ "$al" = "$ME" ]; then
    add autologin "Automatic login" PASS "logs in as this user after a restart" ""
  else
    local d="not set"
    [ -n "$al" ] && d="set to a different user"
    case "$fv" in *"is On"*) d="$d; FileVault is On, which disables automatic login" ;; esac
    add autologin "Automatic login" FAIL "$d" \
      "System Settings > Users & Groups > Automatically log in as: this user (requires FileVault off; use an admin account)."
  fi
}

check_gui_session() {
  local cu
  cu=$(printf 'show State:/Users/ConsoleUser\n' | scutil 2>/dev/null | awk '/ Name :/ {print $3; exit}')
  if [ "$cu" = "$ME" ]; then
    add gui_session "GUI session" PASS "this user owns the screen" ""
  elif [ -z "$cu" ] || [ "$cu" = "loginwindow" ]; then
    add gui_session "GUI session" FAIL "nobody is logged in at the screen" \
      "Log in to this user at the Mac's screen (or via Screen Sharing) and leave the session running."
  else
    add gui_session "GUI session" FAIL "another user owns the screen" \
      "Log the other user out (or switch to this user) so this user's GUI session is the active console."
  fi
}

check_sleep() {
  local pm sl ds
  pm=$(pmset -g 2>/dev/null)
  sl=$(printf '%s\n' "$pm" | awk '$1=="sleep" {print $2; exit}')
  ds=$(printf '%s\n' "$pm" | awk '$1=="displaysleep" {print $2; exit}')
  if [ -z "$sl$ds" ]; then
    add sleep "Sleep disabled" MANUAL "could not read pmset" "Check System Settings > Energy/Displays: never sleep, display never off."
  elif [ "$sl" = 0 ] && [ "$ds" = 0 ]; then
    add sleep "Sleep disabled" PASS "sleep 0, displaysleep 0" ""
  else
    add sleep "Sleep disabled" FAIL "sleep ${sl:-?}, displaysleep ${ds:-?} (minutes)" \
      "From an admin account: sudo pmset -a sleep 0 displaysleep 0   (--apply offers this)"
  fi
}

check_screen_lock() {
  local out
  out=$(sysadminctl -screenLock status 2>&1)
  case "$out" in
    *"screenLock is off"*)
      add screen_lock "Screen lock off" PASS "no password after sleep or screen saver" "" ;;
    *"screenLock delay"*|*immediate*|*"screenLock is on"*)
      add screen_lock "Screen lock off" FAIL "$(printf '%s' "$out" | tail -1 | sed 's/.*\] *//')" \
        "System Settings > Lock Screen > Require password after screen saver begins or display is turned off: Never." ;;
    *)
      add screen_lock "Screen lock off" MANUAL "status unreadable from this session" \
        "Confirm System Settings > Lock Screen > Require password ...: Never." ;;
  esac
}

check_screensaver() {
  local t
  t=$(defaults -currentHost read com.apple.screensaver idleTime 2>/dev/null)
  if [ "$t" = 0 ]; then
    add screensaver "Screen saver off" PASS "idleTime 0" ""
  else
    add screensaver "Screen saver off" WARN "idleTime ${t:-default}" \
      "System Settings > Lock Screen > Start Screen Saver when inactive: Never   (--apply sets this)"
  fi
}

check_app() {
  local v
  APP=$(bash "$RUNNER_SRC" --find-app 2>/dev/null)
  if [ -z "$APP" ]; then
    add chatgpt_app "ChatGPT app" FAIL "no app with bundle id com.openai.codex found" \
      "Install the ChatGPT desktop app (the one that includes Codex) into /Applications, open it once."
    return
  fi
  v=$(defaults read "$APP/Contents/Info" CFBundleShortVersionString 2>/dev/null)
  add chatgpt_app "ChatGPT app" PASS "$(basename "$APP") ${v:-version unknown}" ""
}

check_codex() {
  local v
  CODEX=$(bash "$RUNNER_SRC" --find-codex 2>/dev/null)
  if [ -z "$CODEX" ]; then
    add codex_cli "Bundled Codex CLI" FAIL "not found inside the app bundle" \
      "Update the ChatGPT app; if it still fails, open an issue with: find /Applications/ChatGPT.app -name codex"
    return
  fi
  v=$("$CODEX" --version 2>/dev/null | head -1)
  if [ -n "$v" ]; then
    add codex_cli "Bundled Codex CLI" PASS "$v" ""
  else
    add codex_cli "Bundled Codex CLI" FAIL "found but did not run" "Open the ChatGPT app once (first launch finishes install), then re-run."
  fi
}

check_login() {
  local out
  if [ -z "$CODEX" ]; then
    add codex_login "Codex signed in" MANUAL "no CLI to ask" "Fix the Codex CLI row first."
    return
  fi
  if out=$("$CODEX" login status 2>&1); then
    local kind="signed in"
    case "$out" in *ChatGPT*|*chatgpt*) kind="signed in with a ChatGPT account" ;; *"API key"*) kind="signed in with an API key" ;; esac
    add codex_login "Codex signed in" PASS "$kind" ""
  else
    local st=FAIL
    [ "$OVER_SSH" = 1 ] && st=WARN
    add codex_login "Codex signed in" "$st" "not signed in (as seen from this session)" \
      "In the GUI session: open ChatGPT, sign in with YOUR OWN account (never a shared login), then run: \"$CODEX\" login"
  fi
}

check_computer_use() {
  local out st line fix
  if [ -z "$CODEX" ]; then
    add computer_use "Computer Use plugin" MANUAL "no CLI to ask" "Fix the Codex CLI row first."
    return
  fi
  out=$(QA_WORKER_CODEX="$CODEX" bash "$RUNNER_SRC" --computer-use 2>/dev/null)
  st=$(printf '%s\n' "$out" | head -1)
  line=$(printf '%s\n' "$out" | sed -n 2p)
  fix="\"$CODEX\" plugin add computer-use@openai-bundled  (or unified-computer-use@openai-bundled, whichever 'plugin list' offers; --apply tries both), then quit and reopen ChatGPT."
  case "$st" in
    ok) add computer_use "Computer Use plugin" PASS "$line" "" ;;
    unknown) add computer_use "Computer Use plugin" MANUAL "this CLI cannot list plugins" "Update the ChatGPT app, then re-run." ;;
    *) add computer_use "Computer Use plugin" FAIL "$line" "$fix" ;;
  esac
}

check_model() {
  local m pat prc
  pat=$(QA_WORKER_BASE="$BASE" bash "$RUNNER_SRC" --model-pattern 2>/dev/null)
  prc=$?
  if [ "$prc" != 0 ]; then
    add model_catalog "Model for jobs" FAIL "the model pattern file $BASE/model-pattern exists but is not a readable regular file: jobs finish blocked" \
      "Make $BASE/model-pattern a readable regular file for this user, or remove it."
    return
  fi
  if [ -z "$CODEX" ]; then
    add model_catalog "Model for jobs" MANUAL "no CLI to ask" "Fix the Codex CLI row first."
    return
  fi
  m=$(QA_WORKER_BASE="$BASE" QA_WORKER_CODEX="$CODEX" bash "$RUNNER_SRC" --pick-model 2>/dev/null)
  if [ -n "$m" ]; then
    add model_catalog "Model for jobs" PASS "jobs will run $m (pattern: ${pat:-none set})" ""
  else
    add model_catalog "Model for jobs" FAIL "no listed model matched (pattern: ${pat:-none set}; or the catalog is unreadable or not signed in): jobs finish blocked" \
      "Sign in to ChatGPT/Codex in the GUI session and update the app; if you set a model pattern (QA_WORKER_MODEL or $BASE/model-pattern), make sure it matches a listed model. The runner never runs a job without a model."
  fi
}

check_python() {
  local p v
  p=$(command -v python3)
  if [ -z "$p" ] || { [ "$p" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; }; then
    add python3 "Python 3" FAIL "not installed" "xcode-select --install   (installs Apple's command line tools, which include python3)"
    return
  fi
  v=$(python3 -c 'import sys; print(sys.version.split()[0])' 2>/dev/null)
  if [ -n "$v" ]; then add python3 "Python 3" PASS "python $v" ""
  else add python3 "Python 3" FAIL "python3 does not run" "xcode-select --install"
  fi
}

check_runner() {
  local want have
  want=$(bash "$RUNNER_SRC" --version)
  if [ ! -f "$BASE/runner.sh" ]; then
    add runner "Runner installed" FAIL "no runner at $BASE/runner.sh" "worker/install.sh --apply"
    return
  fi
  have=$(sed -n 's/^QA_WORKER_RUNNER_VERSION="\(.*\)"$/\1/p' "$BASE/runner.sh" | head -1)
  if [ "$have" = "$want" ] && cmp -s "$RUNNER_SRC" "$BASE/runner.sh" && cmp -s "$LOCKRUN_SRC" "$BASE/lockrun.py" && cmp -s "$JOBRUN_SRC" "$BASE/jobrun.py"; then
    add runner "Runner installed" PASS "version $have" ""
  else
    add runner "Runner installed" FAIL "installed ${have:-unknown}, repo $want" "worker/install.sh --apply"
  fi
}

check_ack() {
  local line
  if line=$(QA_WORKER_BASE="$BASE" bash "$RUNNER_SRC" --ack-state 2>/dev/null); then
    add unsandboxed_ack "Unsandboxed run acknowledged" PASS "$line" ""
  else
    add unsandboxed_ack "Unsandboxed run acknowledged" FAIL "no acknowledgement at $BASE/unsandboxed-ack: the runner starts no job" \
      "Read the explanation, then run: worker/install.sh --apply --accept-unsandboxed"
  fi
}

check_launchagent() {
  if [ ! -f "$PLIST" ]; then
    add launchagent "LaunchAgent loaded" FAIL "$LABEL not installed" "worker/install.sh --apply"
  elif ! grep -q "$BASE/runner.sh" "$PLIST"; then
    add launchagent "LaunchAgent loaded" FAIL "$LABEL points at another folder" "worker/install.sh --apply"
  elif agent_loaded "$LABEL"; then
    add launchagent "LaunchAgent loaded" PASS "$LABEL" ""
  else
    add launchagent "LaunchAgent loaded" FAIL "$LABEL installed but not loaded" \
      "Log in to the GUI session, then: worker/install.sh --apply"
  fi
}

check_remote_login() {
  if [ "$OVER_SSH" = 1 ]; then
    add remote_login "Remote Login (SSH)" PASS "this check is running over SSH" ""
  elif nc -z -G 2 127.0.0.1 22 >/dev/null 2>&1; then
    add remote_login "Remote Login (SSH)" PASS "port 22 is listening" ""
  else
    add remote_login "Remote Login (SSH)" FAIL "port 22 is not listening" \
      "System Settings > General > Sharing > Remote Login: On; Allow access for: Only these users -> this user."
  fi
}

check_lead_key() {
  local n=0 ak=$HOME/.ssh/authorized_keys
  [ -f "$ak" ] && n=$(grep -Ec '^(ssh-|ecdsa-|sk-)' "$ak" 2>/dev/null)
  if [ "${n:-0}" -ge 1 ] 2>/dev/null; then
    add lead_key "Lead key authorised" PASS "$n key(s) in ~/.ssh/authorized_keys" ""
  else
    add lead_key "Lead key authorised" FAIL "no keys in ~/.ssh/authorized_keys" \
      "On the lead Mac run lead/setup-lead.sh; it prints the ssh-copy-id command to run once."
  fi
}

check_queue() {
  local pending=0 done_n=0 running=no
  [ -d "$BASE/jobs" ] && pending=$(find "$BASE/jobs" -maxdepth 1 -name '*.task' 2>/dev/null | wc -l | tr -d ' ')
  [ -d "$BASE/done" ] && done_n=$(find "$BASE/done" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  job_running && running=yes
  if [ -d "$BASE/jobs" ]; then
    add queue "Job queue" PASS "pending $pending, finished $done_n, running now: $running" ""
  else
    add queue "Job queue" FAIL "no queue at $BASE" "worker/install.sh --apply"
  fi
}

check_gui_selfcheck() {
  local fix="Make sure the GUI session is logged in and the LaunchAgent is loaded; worker/install.sh --apply refreshes the self-check."
  if [ ! -f "$SELFCHECK_FILE" ]; then
    add gui_selfcheck "GUI self-check" MANUAL "the runner has not written $SELFCHECK_FILE yet" "$fix"
    add gui_codex "GUI: Codex + Computer Use" MANUAL "needs the GUI self-check" "$fix"
    add gui_screen "GUI: screen capture" MANUAL "needs the GUI self-check" "$fix"
    add gui_keychain "GUI: Keychain unlocked" MANUAL "needs the GUI self-check" "$fix"
    return
  fi
  local age ver gui
  age=$(( $(date +%s) - $(file_mtime "$SELFCHECK_FILE") ))
  ver=$(sc_get runner_version)
  gui=$(sc_get in_gui_session)
  if [ "$gui" != true ]; then
    add gui_selfcheck "GUI self-check" FAIL "written outside the console GUI session" "$fix"
  elif [ "$age" -gt "$SELFCHECK_MAX_AGE" ]; then
    add gui_selfcheck "GUI self-check" WARN "$((age / 3600)) h old (runner $ver)" "$fix"
  else
    add gui_selfcheck "GUI self-check" PASS "$((age / 60)) min old (runner $ver)" ""
  fi

  local missing=""
  [ -n "$(sc_get codex_path)" ] || missing="$missing codex-cli"
  [ "$(sc_get login_ok)" = true ] || missing="$missing sign-in"
  [ "$(sc_get computer_use_installed)" = true ] || missing="$missing computer-use-plugin"
  if [ -z "$missing" ]; then
    add gui_codex "GUI: Codex + Computer Use" PASS "$(sc_get codex_version); model $(sc_get model) (pattern: $(sc_get model_pattern | grep . || echo none set))" ""
  else
    add gui_codex "GUI: Codex + Computer Use" FAIL "missing in the GUI session:$missing" \
      "In the GUI session: sign in to ChatGPT with your own account; codex plugin add computer-use@openai-bundled; reopen ChatGPT."
  fi

  if [ "$(sc_get screenshot_ok)" = true ]; then
    add gui_screen "GUI: screen capture" PASS "$(sc_get screenshot_bytes) bytes" ""
  else
    add gui_screen "GUI: screen capture" WARN "the runner could not capture the screen" \
      "Grant Screen Recording to ChatGPT (and to bash if macOS asked) in System Settings > Privacy & Security; the probe is the real proof."
  fi

  if [ "$(sc_get model_pattern_ok)" = false ]; then
    add gui_model_pattern "GUI: model pattern file" FAIL "the runner could not read $BASE/model-pattern in the GUI session: jobs finish blocked" \
      "Make $BASE/model-pattern a readable regular file for this user, or remove it."
  fi

  case "$(sc_get keychain_state)" in
    unlocked)
      add gui_keychain "GUI: Keychain unlocked" PASS "login keychain unlocked in the GUI session" "" ;;
    locked)
      add gui_keychain "GUI: Keychain unlocked" WARN "login keychain locked in the GUI session" \
        "Only needed for live-production secure references: keep the login keychain password equal to the user password so auto-login unlocks it." ;;
    *)
      add gui_keychain "GUI: Keychain unlocked" MANUAL "lock state could not be read ($(sc_get keychain_detail))" \
        "Open Keychain Access in the GUI session and check that the login keychain is unlocked (only needed for production secure references)." ;;
  esac
}

run_checks() {
  reset_results
  check_macos; check_user; check_autologin; check_gui_session; check_sleep
  check_screen_lock; check_screensaver; check_app; check_codex; check_login
  check_computer_use; check_model; check_python; check_runner; check_ack; check_launchagent
  check_remote_login; check_lead_key; check_queue; check_gui_selfcheck
}

count_status() {
  local i n=0
  for i in "${!R_STATUS[@]}"; do [ "${R_STATUS[$i]}" = "$1" ] && n=$((n + 1)); done
  printf '%s' "$n"
}

print_table() {
  local i
  printf '\nQA worker check (%s, base %s%s)\n\n' "$( [ "$APPLY" = 1 ] && echo after-apply || echo check-only)" "$BASE" \
    "$( [ "$OVER_SSH" = 1 ] && echo ', over SSH: GUI rows come from the runner self-check')"
  printf '%-7s %-26s %s\n' STATUS REQUIREMENT DETAIL
  printf '%-7s %-26s %s\n' ------ ----------- ------
  for i in "${!R_ID[@]}"; do
    printf '%-7s %-26s %s\n' "${R_STATUS[$i]}" "${R_NAME[$i]}" "${R_DETAIL[$i]}"
    [ -n "${R_FIX[$i]}" ] && [ "${R_STATUS[$i]}" != PASS ] && printf '%-7s %-26s fix: %s\n' "" "" "${R_FIX[$i]}"
  done
  printf '\nPASS %s  FAIL %s  WARN %s  MANUAL %s\n' "$(count_status PASS)" "$(count_status FAIL)" "$(count_status WARN)" "$(count_status MANUAL)"
}

print_json() {
  local i sep=""
  printf '{\n  "tool": "qa-worker-setup/install.sh",\n  "runner_version": %s,\n' "$(json_str "$(bash "$RUNNER_SRC" --version)")"
  printf '  "mode": %s,\n  "over_ssh": %s,\n  "base": %s,\n  "results": [\n' \
    "$(json_str "$( [ "$APPLY" = 1 ] && echo apply || echo check)")" "$( [ "$OVER_SSH" = 1 ] && echo true || echo false)" "$(json_str "$BASE")"
  for i in "${!R_ID[@]}"; do
    printf '%s    {"id": %s, "name": %s, "status": %s, "detail": %s, "fix": %s}' "$sep" \
      "$(json_str "${R_ID[$i]}")" "$(json_str "${R_NAME[$i]}")" "$(json_str "${R_STATUS[$i]}")" \
      "$(json_str "${R_DETAIL[$i]}")" "$(json_str "${R_FIX[$i]}")"
    sep=$',\n'
  done
  printf '\n  ],\n  "summary": {"PASS": %s, "FAIL": %s, "WARN": %s, "MANUAL": %s}\n}\n' \
    "$(count_status PASS)" "$(count_status FAIL)" "$(count_status WARN)" "$(count_status MANUAL)"
}

# ---------------------------------------------------------------- apply
render_instructions() { cat "$INSTRUCTIONS_TEMPLATE"; }
sha() { shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; }

install_instructions() {
  local target=$BASE/runtime-instructions.md stamp=$BASE/.runtime-instructions.sha256 new
  new=$(mktemp)
  render_instructions > "$new"
  if [ ! -e "$target" ]; then
    cp "$new" "$target"; sha "$target" > "$stamp"
    say "  - installed runtime instructions ($target)"
  elif cmp -s "$new" "$target"; then
    sha "$target" > "$stamp"
  elif [ -f "$stamp" ] && [ "$(sha "$target")" = "$(cat "$stamp")" ]; then
    cp "$new" "$target"; sha "$target" > "$stamp"
    say "  - updated unedited runtime instructions to the new template"
  else
    cp "$new" "$BASE/runtime-instructions.new.md"
    say "  - runtime instructions were edited locally: kept them; new template saved as runtime-instructions.new.md (merge by hand)"
  fi
  rm -f "$new"
}

install_runner_and_agent() {
  local changed=0 rendered
  if ! cmp -s "$RUNNER_SRC" "$BASE/runner.sh"; then
    cp "$RUNNER_SRC" "$BASE/runner.sh.new" && chmod 755 "$BASE/runner.sh.new" && mv "$BASE/runner.sh.new" "$BASE/runner.sh"
    changed=1
    say "  - installed runner $(bash "$RUNNER_SRC" --version) at $BASE/runner.sh"
  fi
  if ! cmp -s "$LOCKRUN_SRC" "$BASE/lockrun.py"; then
    cp "$LOCKRUN_SRC" "$BASE/lockrun.py.new" && mv "$BASE/lockrun.py.new" "$BASE/lockrun.py"
    changed=1
  fi
  if ! cmp -s "$JOBRUN_SRC" "$BASE/jobrun.py"; then
    cp "$JOBRUN_SRC" "$BASE/jobrun.py.new" && mv "$BASE/jobrun.py.new" "$BASE/jobrun.py"
    changed=1
  fi
  mkdir -p "$LA_DIR"
  rendered=$(mktemp)
  sed -e "s|__BASE__|$BASE|g" -e "s|__LABEL__|$LABEL|g" "$PLIST_TEMPLATE" > "$rendered"
  if ! cmp -s "$rendered" "$PLIST"; then
    mv "$rendered" "$PLIST"; chmod 644 "$PLIST"; changed=1
    say "  - wrote $PLIST"
  else
    rm -f "$rendered"
  fi
  if [ "$changed" = 1 ] || ! agent_loaded "$LABEL"; then
    launchctl bootout "gui/$UID_NUM/$LABEL" >/dev/null 2>&1
    if launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>/dev/null; then
      say "  - loaded LaunchAgent $LABEL"
    else
      say "  - could not load $LABEL (is this user logged in at the screen?); log in and re-run --apply"
    fi
  fi
}

apply_plugin() {
  [ -n "$CODEX" ] || return 0
  [ "$(QA_WORKER_CODEX="$CODEX" bash "$RUNNER_SRC" --computer-use 2>/dev/null | head -1)" = ok ] && return 0
  local p
  for p in computer-use@openai-bundled unified-computer-use@openai-bundled; do
    say "  - adding the Computer Use plugin ($p)"
    if "$CODEX" plugin add "$p" >/dev/null 2>&1; then
      say "    added; quit and reopen the ChatGPT app so it picks the plugin up"
      return 0
    fi
  done
  say "    failed; in Terminal in the GUI session run \"$CODEX\" plugin list and add the computer-use plugin it offers"
}

apply_power() {
  local pm sl ds
  defaults -currentHost write com.apple.screensaver idleTime -int 0 2>/dev/null && say "  - screen saver set to never start"
  pm=$(pmset -g 2>/dev/null)
  sl=$(printf '%s\n' "$pm" | awk '$1=="sleep" {print $2; exit}')
  ds=$(printf '%s\n' "$pm" | awk '$1=="displaysleep" {print $2; exit}')
  if [ "$sl" = 0 ] && [ "$ds" = 0 ]; then return 0; fi
  say "  - sleep is on. Computer Use needs an awake, unlocked display, so the worker must never sleep."
  if [ -t 0 ] && [ -t 1 ] && command -v sudo >/dev/null 2>&1; then
    say "    running: sudo pmset -a sleep 0 displaysleep 0   (asks for an admin password)"
    sudo pmset -a sleep 0 displaysleep 0 || say "    sudo failed; run that command from an admin account"
  else
    say "    not an interactive terminal: from an admin account run: sudo pmset -a sleep 0 displaysleep 0"
  fi
}

request_selfcheck() {
  agent_loaded "$LABEL" || return 0
  local before after i=0
  before=$(file_mtime "$SELFCHECK_FILE")
  touch "$BASE/selfcheck.request"
  say "  - asked the runner for a fresh GUI self-check (up to ${QA_WORKER_SELFCHECK_WAIT:-30}s)"
  while [ $i -lt "${QA_WORKER_SELFCHECK_WAIT:-30}" ]; do
    after=$(file_mtime "$SELFCHECK_FILE")
    [ "$after" != "$before" ] && [ ! -e "$BASE/selfcheck.request" ] && return 0
    sleep 1; i=$((i + 1))
  done
  say "    no fresh self-check yet; the runner writes one when it next starts in the GUI session"
}

print_manual_steps() {
  local n=1 i
  say ""
  say "Manual steps scripts cannot do (skip any already done):"
  say "  $n. System Settings > Privacy & Security > Accessibility and > Screen & System Audio Recording:"
  say "     allow ChatGPT and its Computer Use helper (it appears after the first Computer Use run)."; n=$((n + 1))
  say "  $n. Open ChatGPT in this GUI session and sign in with YOUR OWN account (never a shared login);"
  say "     then in Terminal: \"${CODEX:-codex}\" login status"; n=$((n + 1))
  say "  $n. System Settings > Users & Groups > Automatically log in as: this user (FileVault must be off)."; n=$((n + 1))
  say "  $n. System Settings > Lock Screen: require password after screen saver/display off: Never."; n=$((n + 1))
  say "  $n. System Settings > General > Sharing > Remote Login: On, only this user."; n=$((n + 1))
  say "  $n. On the lead Mac: lead/setup-lead.sh --host <worker-user>@<worker-host> (prints the ssh-copy-id command)."; n=$((n + 1))
  say "  $n. From the lead: lead/qa-submit --probe   (the only real end-to-end pass)."
  for i in "${!R_ID[@]}"; do
    case "${R_STATUS[$i]}" in FAIL|MANUAL) say "     still open: ${R_NAME[$i]}: ${R_FIX[$i]}" ;; esac
  done
}

# ---- pause protocol (see runner.sh take_one) ----
PAUSE_FILE=$BASE/pause
APPLY_WAIT=${QA_WORKER_APPLY_WAIT:-600}


# A job holds the runner's kernel lock (runner.sh --lock-state): prints what it says, returns 0.
active_job() {
  local st
  st=$(QA_WORKER_BASE="$BASE" bash "$RUNNER_SRC" --lock-state 2>/dev/null)
  [ "$st" = free ] && return 1
  printf '%s\n' "${st:-lock state unreadable}"  # busy, or unreadable: wait (conservative)
}

# Bounded wait until no job is active: no live active lock and no codex exec in any queue.
wait_until_idle() {
  local waited=0 job=""
  while :; do
    job=$(active_job)
    if [ -z "$job" ] && ! job_running; then return 0; fi
    if [ "$waited" -ge "$APPLY_WAIT" ]; then
      say "A QA job is still running (${job:-a codex exec in a job folder}) after ${APPLY_WAIT}s."
      say "Nothing was reloaded; re-run --apply when the worker is idle."
      return 1
    fi
    [ "$waited" = 0 ] && say "  - waiting up to ${APPLY_WAIT}s for the running QA job to finish"
    sleep 1
    waited=$((waited + 1))
  done
}

on_apply_exit() {
  rm -f "$PAUSE_FILE"
}

abort_apply() {
  rm -f "$PAUSE_FILE"
  return 1
}

explain_unsandboxed() {
  say "Not applied: unsandboxed execution has not been acknowledged."
  say ""
  say "This worker starts every QA brief with the agent CLI's approvals and sandbox turned off"
  say "(codex exec --dangerously-bypass-approvals-and-sandbox), because Computer Use drives the real"
  say "screen with nobody there to approve. The agent runs with the full rights of this macOS user."
  say "Anything that can steer it (a brief, or a page it opens) can act as that user."
  say ""
  say "Only continue if all of these are true:"
  say "  - this is a dedicated Mac and a dedicated macOS user;"
  say "  - it holds no personal data and no accounts or credentials beyond what QA needs;"
  say "  - you only send briefs you wrote or trust, against test accounts and sites you control."
  say ""
  say "To acknowledge and apply, run: worker/install.sh --apply --accept-unsandboxed"
  say "Nothing was changed."
}

# Refuses --apply until the operator has acknowledged, or acknowledges now with the flag.
require_ack() {
  [ "$ACCEPT" = 1 ] && return 0
  QA_WORKER_BASE="$BASE" bash "$RUNNER_SRC" --ack-state >/dev/null 2>&1 && return 0
  explain_unsandboxed
  return 1
}

# Writes the marker through a unique temporary file created by mktemp (never a fixed name, never
# following a link), then renames it into place. Refuses to touch a marker path that is a link or
# not a regular file, and verifies the result. Returns 1 on any failure.
record_ack() {
  [ "$ACCEPT" = 1 ] || return 0
  local marker=$BASE/unsandboxed-ack tmp want
  if [ -L "$marker" ] || { [ -e "$marker" ] && [ ! -f "$marker" ]; }; then
    say "  - refusing to write $marker: it is a link or not a regular file; remove it and re-run"
    return 1
  fi
  want="accepted unsandboxed execution on $(date '+%Y-%m-%d') by runner $(bash "$RUNNER_SRC" --version)"
  tmp=$(mktemp "$BASE/.unsandboxed-ack.XXXXXX") || { say "  - could not create a temporary file in $BASE"; return 1; }
  if printf '%s\n' "$want" > "$tmp" && chmod 644 "$tmp" && mv -f "$tmp" "$marker" \
    && [ -f "$marker" ] && [ ! -L "$marker" ] && [ "$(head -n 1 "$marker")" = "$want" ]; then
    say "  - recorded the unsandboxed-execution acknowledgement ($marker)"
    return 0
  fi
  rm -f "$tmp"
  say "  - could not record the acknowledgement at $marker; nothing was installed"
  return 1
}

do_apply() {
  say "Applying QA worker setup (base $BASE)"
  mkdir -p "$BASE/jobs" "$BASE/done" "$BASE/logs/transcripts" "$BASE/tmp"
  # 1. Stop new work: the runner honours the pause marker.
  touch "$PAUSE_FILE"
  # Any exit (error, Ctrl-C, kill) removes the pause marker.
  trap 'on_apply_exit' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM HUP
  # 2. Never bootout or replace a runner mid-job.
  wait_until_idle || { abort_apply; return 1; }
  record_ack || { abort_apply; return 1; }
  install_instructions
  install_runner_and_agent
  # 3. The new runner is loaded: let it take jobs again.
  rm -f "$PAUSE_FILE"
  CODEX=$(bash "$RUNNER_SRC" --find-codex 2>/dev/null)
  apply_plugin
  apply_power
  request_selfcheck
  return 0
}

# ---------------------------------------------------------------- main
if [ "$APPLY" = 1 ]; then
  require_ack || exit 2
  do_apply || exit 1
fi
run_checks
if [ "$JSON" = 1 ]; then print_json; else print_table; fi
[ "$APPLY" = 1 ] && print_manual_steps
[ "$(count_status FAIL)" = 0 ]
