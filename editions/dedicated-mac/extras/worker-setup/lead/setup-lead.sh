#!/bin/bash
# QA worker lead setup: connect this Mac (where you run your coding agent) to a QA worker Mac.
#
#   lead/setup-lead.sh --host <worker-user>@<worker-host> [--base ~/qa-worker]
#                         CHECK ONLY (default): SSH key, config, reachability, worker queue.
#   ... --apply           create an ed25519 key if there is none, write the config, then run
#                         `qa-submit --probe` (the only real end-to-end pass).
#   ... --probe           run the probe without changing anything else.
#
# Never runs password authentication for you: it prints the exact ssh-copy-id command instead.
# Compatible with macOS stock /bin/bash 3.2. Exit 0 only if no row is FAIL.

HERE=$(cd "$(dirname "$0")" && pwd)
SUBMIT=$HERE/qa-submit
CONFIG=${QA_WORKER_CONFIG:-$HOME/.config/qa-worker/config.json}
KEY=$HOME/.ssh/id_ed25519
APPLY=0; PROBE=0; HOST=""; BASE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --probe) PROBE=1 ;;
    --host) shift; HOST=$1 ;;
    --base) shift; BASE=$1 ;;
    --config) shift; CONFIG=$1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

cfg_get() {  # value of a top-level (or "worker"-nested) key in the config, via python3
  [ -f "$CONFIG" ] || return
  python3 - "$CONFIG" "$1" <<'EOF' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
if isinstance(d.get("worker"), dict):
    d = d["worker"]
v = d.get(sys.argv[2])
print("" if v is None else v)
EOF
}

[ -z "$HOST" ] && HOST=$(cfg_get host)
[ -z "$BASE" ] && BASE=$(cfg_get base)
# The literal "~/" is intended: qa-submit expands it on the worker, not on this Mac.
# shellcheck disable=SC2088
[ -z "$BASE" ] && BASE="~/qa-worker"
if [ -n "$HOST" ] && ! printf '%s' "$HOST" | grep -Eq '^[A-Za-z0-9_][A-Za-z0-9._-]*(@[A-Za-z0-9][A-Za-z0-9._-]*)?$'; then
  echo "invalid --host (expected user@host)" >&2; exit 2
fi
if ! printf '%s' "$BASE" | grep -Eq '^(~/|/)[A-Za-z0-9/._-]*$'; then
  echo "invalid --base (absolute path or ~/path)" >&2; exit 2
fi

ROWS=""; FAILS=0
row() {  # status name detail [fix]
  ROWS="$ROWS$(printf '%-7s %-22s %s' "$1" "$2" "$3")
"
  [ -n "$4" ] && [ "$1" != PASS ] && ROWS="$ROWS$(printf '%-7s %-22s fix: %s' "" "" "$4")
"
  [ "$1" = FAIL ] && FAILS=$((FAILS + 1))
}

pubkey() {
  local k
  for k in "$KEY.pub" "$HOME/.ssh/id_ecdsa.pub" "$HOME/.ssh/id_rsa.pub"; do
    [ -f "$k" ] && { printf '%s\n' "$k"; return; }
  done
}

write_config() {
  mkdir -p "$(dirname "$CONFIG")"
  python3 - "$CONFIG" "$HOST" "$BASE" <<'EOF'
import json, os, sys
path, host, base = sys.argv[1:4]
try:
    d = json.load(open(path))
except (OSError, ValueError):
    d = {}
# Readers prefer a nested "worker" block, so update it when present; else the top level.
t = d["worker"] if isinstance(d.get("worker"), dict) else d
t.update({"host": host, "base": base})
t.setdefault("effort", "medium")
t.setdefault("busyWaitSeconds", 1800)
t.setdefault("timeout", 3600)
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(d, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
EOF
}

# 1. SSH key
if [ "$APPLY" = 1 ] && [ -z "$(pubkey)" ]; then
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  ssh-keygen -q -t ed25519 -N "" -C "qa-worker-lead" -f "$KEY" && echo "created $KEY (ed25519)"
fi
PUB=$(pubkey)
if [ -n "$PUB" ]; then row PASS "SSH key" "$PUB"
else row FAIL "SSH key" "no SSH key in ~/.ssh" "lead/setup-lead.sh --apply   (or: ssh-keygen -t ed25519)"
fi

# 2. Config
if [ -z "$HOST" ]; then
  row FAIL "Config" "no worker host" "lead/setup-lead.sh --host <worker-user>@<worker-host> --apply"
else
  if [ "$APPLY" = 1 ]; then write_config && echo "wrote $CONFIG"; fi
  if [ "$(cfg_get host)" = "$HOST" ] && [ "$(cfg_get base)" = "$BASE" ]; then
    row PASS "Config" "$CONFIG -> $HOST $BASE"
  else
    row FAIL "Config" "$CONFIG missing or different" "lead/setup-lead.sh --host $HOST --base $BASE --apply"
  fi
fi

# 3. Reachable with key auth (BatchMode never prompts for a password)
REACH=0
if [ -n "$HOST" ]; then
  out=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" true 2>&1)
  rc=$?
  if [ "$rc" = 0 ]; then
    REACH=1; row PASS "Key authorised" "ssh $HOST works without a password"
  else
    case "$out" in
      *"Permission denied"*)
        row FAIL "Key authorised" "the worker refused this key" \
          "ssh-copy-id -i ${PUB:-$KEY.pub} $HOST   (asks for the worker user's password once)" ;;
      *"Host key verification failed"*|*"host key"*)
        row FAIL "Key authorised" "worker host key not trusted yet" \
          "ssh $HOST   (once, interactively; compare the fingerprint with the worker's before typing yes)" ;;
      *)
        row FAIL "Host reachable" "$(printf '%s' "$out" | tail -1)" \
          "Check the worker is on, on this network, and Remote Login is on (worker/install.sh shows it)." ;;
    esac
  fi
fi

# 4. Worker queue (via qa-submit --check, which uses the same config)
if [ "$REACH" = 1 ]; then
  if [ "$(cfg_get host)" = "$HOST" ]; then
    if chk=$(python3 "$SUBMIT" --config "$CONFIG" --check 2>&1); then
      row PASS "Worker set up" "queue, LaunchAgent and GUI self-check present"
    else
      row FAIL "Worker set up" "$(printf '%s' "$chk" | grep -i missing | tr '\n' ' ')" \
        "On the worker, in Terminal: worker/install.sh --apply"
    fi
  else
    row MANUAL "Worker set up" "write the config first" "lead/setup-lead.sh --host $HOST --apply"
  fi
fi

# 5. Probe: the only real pass
if [ "$APPLY" = 1 ] || [ "$PROBE" = 1 ]; then
  if [ "$FAILS" = 0 ]; then
    echo "running the probe (a few minutes)..."
    if python3 "$SUBMIT" --config "$CONFIG" --probe; then
      row PASS "Probe round trip" "example.com probe completed; look at the screenshot it names"
    else
      row FAIL "Probe round trip" "see qa-submit output above" "docs/TROUBLESHOOTING.md"
    fi
  else
    row MANUAL "Probe round trip" "skipped until the rows above pass" ""
  fi
else
  row MANUAL "Probe round trip" "not run in check-only mode" "lead/setup-lead.sh --probe"
fi

printf '\nQA worker lead check\n\n%-7s %-22s %s\n%-7s %-22s %s\n' STATUS REQUIREMENT DETAIL ------ ----------- ------
printf '%s' "$ROWS"
[ "$FAILS" = 0 ]
