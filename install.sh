#!/usr/bin/env bash
# Install the Agentic QA Toolkit skills for one edition into an agent's skills folder.
#
#   ./install.sh --edition local --target ~/.claude/skills            # show what would happen
#   ./install.sh --edition local --target ~/.claude/skills --apply    # do it
#
# Without --apply nothing is written. An existing qa-* skill folder is never overwritten
# unless you pass --replace, which first moves it aside to <name>.bak-<timestamp>.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS=(qa-standards qa-site-audit qa-release)
EDITION="" TARGET="" APPLY=0 REPLACE=0

usage() {
  cat <<'USAGE'
Usage: ./install.sh --edition <local|hosted-bot|dedicated-mac> --target <skills folder> [--apply] [--replace]

  --edition   which setup you are installing for (see docs/choosing-an-edition.md)
  --target    your agent's skills folder, for example ~/.claude/skills or ~/.codex/skills
  --apply     copy the files; without it, only show what would happen
  --replace   if a qa-* skill is already there, move it to <name>.bak-<timestamp> and install fresh
  -h, --help  show this help
USAGE
}

fail() { echo "install: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --edition) [ $# -ge 2 ] || fail "--edition needs a value"; EDITION="$2"; shift 2 ;;
    --target)  [ $# -ge 2 ] || fail "--target needs a value"; TARGET="$2"; shift 2 ;;
    --apply)   APPLY=1; shift ;;
    --replace) REPLACE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "unknown option: $1" ;;
  esac
done

[ -n "$EDITION" ] || { usage >&2; fail "--edition is required"; }
[ -n "$TARGET" ]  || { usage >&2; fail "--target is required"; }
case "$EDITION" in local|hosted-bot|dedicated-mac) ;; *) fail "unknown edition: $EDITION" ;; esac
OVERLAY="$HERE/editions/$EDITION"
[ -f "$OVERLAY/environment.md" ] || fail "editions/$EDITION/environment.md is missing; is this a complete copy of the toolkit?"
for s in "${SKILLS[@]}"; do
  [ -f "$HERE/skills/$s/SKILL.md" ] || fail "skills/$s/SKILL.md is missing; is this a complete copy of the toolkit?"
done

TARGET="${TARGET/#\~/$HOME}"
# A ".." in the target could make an existing skills folder look empty until it is created.
case "/$TARGET/" in */../*) fail "--target must not contain '..'; give the folder's real path" ;; esac
VERSION="$(cat "$HERE/VERSION" 2>/dev/null || echo unknown)"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "Agentic QA Toolkit $VERSION, edition: $EDITION"
echo "Target: $TARGET"
[ "$APPLY" -eq 1 ] || echo "Dry run: nothing will be written. Add --apply to install."
echo

blocked=0
for s in "${SKILLS[@]}"; do
  if [ -e "$TARGET/$s" ]; then
    if [ "$REPLACE" -eq 1 ]; then
      echo "  replace  $s  (existing folder moves to $s.bak-$STAMP)"
    else
      echo "  EXISTS   $s  (not touched; pass --replace to move it aside and install fresh)"
      blocked=1
    fi
  else
    echo "  install  $s"
  fi
done
echo "  add      qa-standards/environment.md  (from editions/$EDITION)"
[ "$blocked" -eq 0 ] || fail "one or more skills are already installed; nothing was changed"
[ "$APPLY" -eq 1 ] || exit 0

mkdir -p "$TARGET"
for s in "${SKILLS[@]}"; do
  if [ -e "$TARGET/$s" ]; then
    # Checked again here on purpose: nothing is ever moved aside without --replace.
    [ "$REPLACE" -eq 1 ] || fail "$TARGET/$s exists and --replace was not given; nothing more was changed"
    mv "$TARGET/$s" "$TARGET/$s.bak-$STAMP"
  fi
  cp -R "$HERE/skills/$s" "$TARGET/$s"
done
find "$TARGET/qa-standards" "$TARGET/qa-site-audit" "$TARGET/qa-release" \( -name __pycache__ -o -name .DS_Store \) -prune -exec rm -rf {} +
cp "$OVERLAY/environment.md" "$TARGET/qa-standards/environment.md"
printf '%s %s\n' "$VERSION" "$EDITION" > "$TARGET/qa-standards/.installed"

echo
echo "Installed. Next:"
echo "  1. Read $OVERLAY/README.md for this edition's remaining setup."
if [ -d "$OVERLAY/extras" ]; then
  echo "  2. This edition has extra tools in $OVERLAY/extras; they are not installed by this script."
fi
echo "  Then ask your agent: \"Use qa-standards to QA <a flow> on <URL>.\""
