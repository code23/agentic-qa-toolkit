#!/bin/bash
# QA worker job runner. Runs on the worker Mac inside the logged-in GUI session (started by the
# LaunchAgent that worker/install.sh installs). Compatible with macOS stock /bin/bash 3.2.
#
# Queue layout under $QA_WORKER_BASE (default ~/qa-worker):
#   jobs/<id>.task      a brief, atomically renamed into place by the lead (lead/qa-submit)
#   done/<id>/          the job's working folder: output.txt, result.json, screenshots,
#                       receipt.json and finally .done (written last); raw output discarded
#   logs/               runner.log, gui-selfcheck.json (no new raw transcripts)
#
# Optional job header lines (first lines of the .task file):
#   EFFORT=<minimal|low|medium|high|xhigh>   reasoning effort (default medium)
#   MODEL=<slug>                             recorded but NOT followed: the operator chooses the
#                                            model, never the brief. Every job runs the first model
#                                            listed by `codex debug models` that matches the
#                                            operator's pattern (env QA_WORKER_MODEL, else the first
#                                            non-blank line of $BASE/model-pattern; a shell-style
#                                            glob), or the first listed model when no pattern is
#                                            set. Resolved per job. If none matches, the job is not
#                                            run: it finishes "blocked".
#
# Helper modes (used by install.sh and the tests):
#   --version  --find-app  --find-codex  --pick-model  --model-pattern  --ack-state  --computer-use  --lock-state  --take-one  --executor-running  --selfcheck  --once
QA_WORKER_RUNNER_VERSION="1.1.0"

BASE=${QA_WORKER_BASE:-$HOME/qa-worker}
JOBS=$BASE/jobs
DONE=$BASE/done
LOGS=$BASE/logs
TRANSCRIPTS=$LOGS/transcripts
TMPD=$BASE/tmp
MODEL_PATTERN_FILE=$BASE/model-pattern
ACK_FILE=$BASE/unsandboxed-ack
SELFCHECK_FILE=$LOGS/gui-selfcheck.json
SELFCHECK_REQUEST=$BASE/selfcheck.request
PAUSE=$BASE/pause
LOCKFILE=$BASE/.active.lock
LOCKINFO=$BASE/.active.info
SELF=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
LOCKRUN=$(dirname "$SELF")/lockrun.py
SELFCHECK_INTERVAL=${QA_WORKER_SELFCHECK_INTERVAL:-21600}
POLL=${QA_WORKER_RUNNER_POLL:-2}
APP_BUNDLE_ID="com.openai.codex"

log() { printf '[runner] %s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" >> "$LOGS/runner.log"; }

# JSON string literal for a value (no external tools beyond tr).
json_str() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=$(printf '%s' "$s" | tr '\t\r\n' '   ' | tr -d '\000-\010\013\014\016-\037')
  printf '"%s"' "$s"
}

redact() { sed -E 's/[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}/<redacted>/g'; }

# The desktop app that bundles the Codex CLI. Located by bundle id, never by a fixed path:
# app updates have renamed the bundle (Codex.app -> ChatGPT.app) without changing the id.
find_app() {
  if [ -n "$QA_WORKER_APP_PATH" ]; then
    [ -d "$QA_WORKER_APP_PATH" ] && printf '%s\n' "$QA_WORKER_APP_PATH"
    return
  fi
  local p found=""
  # Prefer /Applications, ignore copies in the Trash.
  # Splitting is intended: spaces were mapped to \001 above.
  for p in $(mdfind "kMDItemCFBundleIdentifier == '$APP_BUNDLE_ID'" 2>/dev/null | grep -v '/\.Trash/' | tr ' ' '\001'); do
    p=$(printf '%s' "$p" | tr '\001' ' ')
    [ -d "$p" ] || continue
    case "$p" in
      /Applications/*) printf '%s\n' "$p"; return ;;
      *) [ -z "$found" ] && found=$p ;;
    esac
  done
  if [ -z "$found" ]; then
    for p in /Applications/ChatGPT.app /Applications/Codex.app "$HOME/Applications/ChatGPT.app" "$HOME/Applications/Codex.app"; do
      [ -d "$p" ] && { found=$p; break; }
    done
  fi
  [ -n "$found" ] && printf '%s\n' "$found"
}

find_codex() {
  if [ -n "$QA_WORKER_CODEX" ]; then
    [ -x "$QA_WORKER_CODEX" ] && printf '%s\n' "$QA_WORKER_CODEX"
    return
  fi
  local app c
  app=$(find_app)
  [ -n "$app" ] || return
  for c in "$app/Contents/Resources/codex-cli/bin/codex" "$app/Contents/Resources/codex"; do
    [ -f "$c" ] && [ -x "$c" ] && { printf '%s\n' "$c"; return; }
  done
  c=$(find "$app/Contents" -maxdepth 5 -type f -name codex -perm -u+x 2>/dev/null | head -1)
  [ -n "$c" ] && printf '%s\n' "$c"
}

# Listed model slugs, in the CLI catalog's own order (priority).
listed_models() {
  local codex=$1
  [ -n "$codex" ] || return
  "$codex" debug models 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ms = d.get("models") if isinstance(d, dict) else d
ms = [m for m in (ms or []) if isinstance(m, dict) and m.get("visibility") == "list"
      and isinstance(m.get("priority"), (int, float))]
for m in sorted(ms, key=lambda m: m["priority"]):
    slug = str(m.get("slug", ""))
    if slug:
        print(slug)' 2>/dev/null
}

# The operator's model pattern, or nothing: $QA_WORKER_MODEL if it is not blank, else the first
# non-blank line of $MODEL_PATTERN_FILE, with surrounding whitespace removed. An absent or blank
# file means no pattern. A file that exists but is not a readable regular file is an error: it
# prints nothing and returns 1, so that callers fail closed instead of ignoring the restriction.
model_pattern() {
  local p raw
  # QA_WORKER_MODEL is an optional operator-set environment variable.
  # shellcheck disable=SC2153
  p=$(printf '%s\n' "$QA_WORKER_MODEL" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | awk 'NF {print; exit}')
  if [ -z "$p" ] && { [ -e "$MODEL_PATTERN_FILE" ] || [ -L "$MODEL_PATTERN_FILE" ]; }; then
    if [ ! -f "$MODEL_PATTERN_FILE" ] || [ ! -r "$MODEL_PATTERN_FILE" ]; then return 1; fi
    raw=$(cat "$MODEL_PATTERN_FILE" 2>/dev/null) || return 1
    p=$(printf '%s\n' "$raw" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | awk 'NF {print; exit}')
  fi
  printf '%s\n' "$p"
}

# Whether the operator has acknowledged unsandboxed execution (written by
# `install.sh --apply --accept-unsandboxed`). Prints the marker's first line and returns 0 if so;
# returns 1 otherwise. Jobs run with the agent CLI's approvals and sandbox off, so the runner
# starts none without it.
ack_recorded() {
  [ -f "$ACK_FILE" ] && [ ! -L "$ACK_FILE" ] && [ -r "$ACK_FILE" ] || return 1
  head -n 1 "$ACK_FILE" | grep '^accepted unsandboxed execution'
}

# The first model of $2 (one slug per line) matching the glob $1, or the first model when $1 is
# empty. Prints nothing if none matches.
select_model() {
  local pattern=$1 m
  # Splitting is intended: one slug per line.
  for m in $2; do
    if [ -z "$pattern" ]; then printf '%s\n' "$m"; return; fi
    # The pattern is an operator-supplied glob, so it is deliberately unquoted.
    # shellcheck disable=SC2254
    case "$m" in $pattern) printf '%s\n' "$m"; return ;; esac
  done
}

# The model jobs run: the first listed model matching the pattern, or the first listed model
# when no pattern is set. Prints nothing if none matches, and returns 1 if the pattern file
# cannot be read. The catalogue is queried first and the pattern is read once, after it.
pick_model() {
  local models pattern
  models=$(listed_models "$1")
  pattern=$(model_pattern) || return 1
  select_model "$pattern" "$models"
}

# Computer Use plugin state from `codex plugin list`. Prints "ok", "missing" or "unknown" on
# line 1 and a short summary on line 2. App updates have both renamed the plugin
# (computer-use / unified-computer-use) and silently dropped it, so any enabled variant counts.
cu_status() {
  local codex=$1
  [ -n "$codex" ] || { printf 'unknown\nno codex CLI\n'; return; }
  "$codex" plugin list 2>&1 | redact | awk '
    /unrecognized|unexpected argument|error:/ { err = 1 }
    $1 ~ /^(unified-)?computer-use@/ {
      st = ($2 == "not") ? "not installed" : $2 " " $3
      s = s (s ? "; " : "") $1 " " st
      if ($2 == "installed," && $3 == "enabled") ok = 1
      n++
    }
    END {
      if (ok) print "ok"; else if (!n && err) print "unknown"; else print "missing"
      print (n ? s : "no computer-use plugin listed")
    }'
}

# Login Keychain lock state WITHOUT unlocking it or showing UI: asks the Security framework
# (SecKeychainCopyDefault + SecKeychainGetStatus, kSecUnlockStateStatus). Prints
# "unlocked", "locked" or "unknown <reason>". `security show-keychain-info` is not used: it can
# succeed while the keychain is locked. QA_WORKER_KEYCHAIN_PROBE replaces the probe (tests).
keychain_state() {
  if [ -n "$QA_WORKER_KEYCHAIN_PROBE" ]; then "$QA_WORKER_KEYCHAIN_PROBE"; return; fi
  python3 -c '
import ctypes
try:
    sec = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Security.framework/Security")
    sec.SecKeychainCopyDefault.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    sec.SecKeychainGetStatus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kc = ctypes.c_void_p()
    if sec.SecKeychainCopyDefault(ctypes.byref(kc)) != 0 or not kc.value:
        print("unknown no default keychain")
    else:
        st = ctypes.c_uint32()
        rc = sec.SecKeychainGetStatus(kc, ctypes.byref(st))
        print("unknown status error %d" % rc if rc else ("unlocked" if st.value & 1 else "locked"))
except Exception as e:
    print("unknown %s" % type(e).__name__)' 2>/dev/null || echo "unknown python3 unavailable"
}

# GUI self-check: proves what THIS (GUI) session can do. SSH sessions see different
# Keychain/TCC state, so install.sh reads this file instead of guessing over SSH.
selfcheck() {
  mkdir -p "$LOGS"
  local now codex ver plugins cu_installed=false cu_line="" login_ok=false login_kind="unknown"
  local shot_ok=false shot_bytes=0 tmpimg kc kc_state kc_found=false kc_unlocked=false kc_detail=""
  local console me in_gui=false model="" models="" pattern pattern_ok=true ack_ok=false
  now=$(date +%s)
  me=$(id -un)
  console=$(printf 'show State:/Users/ConsoleUser\n' | scutil 2>/dev/null | awk '/ Name :/ {print $3; exit}')
  [ "$console" = "$me" ] && in_gui=true

  tmpimg=$(mktemp "${TMPDIR:-/tmp}/qa-worker-selfcheck.XXXXXX").png
  if screencapture -x "$tmpimg" >/dev/null 2>&1 && [ -s "$tmpimg" ]; then
    shot_ok=true
    shot_bytes=$(wc -c < "$tmpimg" | tr -d ' ')
  fi
  rm -f "$tmpimg" "${tmpimg%.png}"

  codex=$(find_codex)
  if [ -n "$codex" ]; then
    ver=$("$codex" --version 2>/dev/null | head -1)
    plugins=$(cu_status "$codex")
    cu_line=$(printf '%s\n' "$plugins" | sed -n 2p)
    [ "$(printf '%s\n' "$plugins" | head -1)" = ok ] && cu_installed=true
    if login=$("$codex" login status 2>&1); then
      login_ok=true
      case "$login" in
        *ChatGPT*|*chatgpt*) login_kind="chatgpt" ;;
        *"API key"*|*api*key*) login_kind="api-key" ;;
        *) login_kind="other" ;;
      esac
    fi
    models=$(listed_models "$codex")
  fi
  pattern=$(model_pattern) || { pattern=""; pattern_ok=false; }
  [ "$pattern_ok" = true ] && model=$(select_model "$pattern" "$models")
  ack_recorded >/dev/null && ack_ok=true

  kc=$(keychain_state | head -1)
  case "$kc" in
    unlocked) kc_found=true; kc_unlocked=true; kc_detail="unlocked" ;;
    locked) kc_found=true; kc_detail="locked" ;;
    *) kc_detail=${kc:-unknown} ;;
  esac
  kc_state=${kc%% *}
  [ -n "$kc_state" ] || kc_state=unknown

  {
    printf '{\n'
    printf '  "runner_version": %s,\n' "$(json_str "$QA_WORKER_RUNNER_VERSION")"
    printf '  "written_at": %s,\n' "$now"
    printf '  "in_gui_session": %s,\n' "$in_gui"
    printf '  "screenshot_ok": %s,\n' "$shot_ok"
    printf '  "screenshot_bytes": %s,\n' "${shot_bytes:-0}"
    printf '  "codex_path": %s,\n' "$(json_str "$codex")"
    printf '  "codex_version": %s,\n' "$(json_str "$ver")"
    printf '  "computer_use_installed": %s,\n' "$cu_installed"
    printf '  "computer_use_line": %s,\n' "$(json_str "$cu_line")"
    printf '  "login_ok": %s,\n' "$login_ok"
    printf '  "login_kind": %s,\n' "$(json_str "$login_kind")"
    printf '  "model": %s,\n' "$(json_str "$model")"
    printf '  "model_pattern": %s,\n' "$(json_str "$pattern")"
    printf '  "model_pattern_ok": %s,\n' "$pattern_ok"
    printf '  "unsandboxed_ack": %s,\n' "$ack_ok"
    printf '  "keychain_found": %s,\n' "$kc_found"
    printf '  "keychain_unlocked": %s,\n' "$kc_unlocked"
    printf '  "keychain_state": %s,\n' "$(json_str "$kc_state")"
    printf '  "keychain_detail": %s\n' "$(json_str "$kc_detail")"
    printf '}\n'
  } > "$SELFCHECK_FILE.tmp" && mv "$SELFCHECK_FILE.tmp" "$SELFCHECK_FILE"
  log "selfcheck gui=$in_gui screenshot=$shot_ok computer_use=$cu_installed login=$login_ok keychain_unlocked=$kc_unlocked"
}

run_job() {
  local codex model="" models="" pattern pattern_error="" ack_missing=""
  codex=$(find_codex)
  [ -n "$codex" ] && models=$(listed_models "$codex")
  # The pattern is read once, after the catalogue query; the model and the error flag come from
  # that one read so they cannot disagree.
  pattern=$(model_pattern) || pattern_error=1
  [ -z "$pattern_error" ] && model=$(select_model "$pattern" "$models")
  ack_recorded >/dev/null || ack_missing=1
  # Replace --take-one so signals reach the cleanup owner; fd 9 keeps the lock.
  QA_WORKER_PATTERN_USED=$pattern QA_WORKER_PATTERN_ERROR=$pattern_error QA_WORKER_ACK_MISSING=$ack_missing exec python3 "$(dirname "$SELF")/jobrun.py" "$BASE" "$1" "$codex" "$model" "$QA_WORKER_RUNNER_VERSION"
}

# Job lock, shared with install.sh --apply (which must never reload the runner mid-job).
# It is a kernel flock on $LOCKFILE taken by lockrun.py, which then execs `runner.sh --take-one`:
# the lock lives exactly as long as that process and the kernel drops it if it dies, so a stale
# lock cannot exist. --take-one checks $PAUSE only once it holds the lock, and install creates
# $PAUSE before it waits for the lock to be free: either the runner sees the pause or install
# sees the lock. codex runs with the lock fd closed so its helper processes cannot keep it.
# A Codex executor of any job in this queue still running as this user,
# e.g. after its --take-one was killed. "[e]xec" keeps pgrep from matching this check itself.
# install.sh uses this too (runner.sh --executor-running).
executor_running() { pgrep -u "$(id -u)" -f -- "[e]xec .*-C .*/(done/|tmp/active-)" >/dev/null 2>&1; }

take_one() {
  local job
  if [ -z "$QA_WORKER_LOCK_FD" ] || ! python3 "$LOCKRUN" held "$LOCKFILE" "$QA_WORKER_LOCK_FD"; then
    echo "runner.sh --take-one: not holding the job lock; use lockrun.py (the runner loop does)" >&2
    return 2
  fi
  [ -e "$PAUSE" ] && return 0
  if executor_running; then
    log "a codex exec from an earlier job is still running; not starting another job"
    return 75
  fi
  python3 "$(dirname "$SELF")/jobrun.py" --recover "$BASE" || return 75
  for job in "$JOBS"/*.task; do
    [ -e "$job" ] || [ -L "$job" ] || continue
    run_job "$job"
    return 0
  done
}

lock_state() {
  local st
  st=$(python3 "$LOCKRUN" probe "$LOCKFILE" 2>/dev/null)
  [ "$st" = free ] || st="busy $(tr '\n' ' ' < "$LOCKINFO" 2>/dev/null)"
  printf '%s\n' "$st"
}

main_loop() {
  local once=$1 last_check=0 now n paused_logged=0 active_pid="" job_rc
  umask 077
  mkdir -p "$JOBS" "$DONE" "$LOGS" "$TRANSCRIPTS" "$TMPD"
  # Background + builtin wait lets a service termination interrupt an active job.
  # The locked cleanup owner handles the signal and drains only its own group.
  trap 'if [ -n "$active_pid" ]; then kill -TERM "$active_pid" 2>/dev/null; wait "$active_pid"; fi; exit 130' TERM INT HUP
  log "up version=$QA_WORKER_RUNNER_VERSION codex=$(find_codex)"
  while true; do
    now=$(date +%s)
    if [ -e "$SELFCHECK_REQUEST" ] || [ $((now - last_check)) -ge "$SELFCHECK_INTERVAL" ]; then
      rm -f "$SELFCHECK_REQUEST"
      selfcheck
      last_check=$now
    fi
    if [ -e "$PAUSE" ]; then
      [ "$paused_logged" = 1 ] || log "paused by $PAUSE; not taking new jobs"
      paused_logged=1
    else
      paused_logged=0
      n=$(find "$JOBS" -maxdepth 1 -name '*.task' 2>/dev/null | wc -l)
      [ "$n" -gt 0 ] || n=1  # acquire once even on an empty queue, for safe recovery
      while [ "$n" -gt 0 ]; do  # one locked process per job; bounded so a stuck file cannot spin
        python3 "$LOCKRUN" run "$LOCKFILE" "$LOCKINFO" /bin/bash "$SELF" --take-one &
        active_pid=$!
        wait "$active_pid"
        job_rc=$?
        active_pid=""
        [ "$job_rc" = 0 ] || break
        n=$((n - 1))
      done
    fi
    [ "$once" = "1" ] && return 0
    sleep "$POLL"
  done
}

case "$1" in
  --version) printf '%s\n' "$QA_WORKER_RUNNER_VERSION" ;;
  --find-app) find_app ;;
  --find-codex) find_codex ;;
  --pick-model) pick_model "$(find_codex)" ;;
  --model-pattern) model_pattern ;;
  --ack-state) ack_recorded ;;
  --computer-use) cu_status "$(find_codex)" ;;
  --lock-state) lock_state ;;
  --take-one) take_one ;;
  --executor-running) executor_running ;;
  --selfcheck) selfcheck; cat "$SELFCHECK_FILE" ;;
  --once) main_loop 1 ;;
  "") main_loop 0 ;;
  *) echo "usage: runner.sh [--version|--find-app|--find-codex|--pick-model|--model-pattern|--ack-state|--computer-use|--lock-state|--take-one|--executor-running|--selfcheck|--once]" >&2; exit 2 ;;
esac
