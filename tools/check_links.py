#!/usr/bin/env python3
"""Check that every relative link in the repository's Markdown files points at a file that exists.

    python3 tools/check_links.py

Web links (http, https, mailto) and in-page anchors are not fetched or checked. Text inside
code fences and inline code is ignored. Exit 1 if any link is broken.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Test fixtures are sample reports whose images are created while the tests run.
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "fixtures"}
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)")


def markdown_files():
    for path in sorted(ROOT.rglob("*.md")):
        if not SKIP_DIRS.intersection(path.relative_to(ROOT).parts):
            yield path


def strip_code(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def main():
    broken, checked = [], 0
    for md in markdown_files():
        for match in LINK.finditer(strip_code(md.read_text(encoding="utf-8"))):
            target = match.group(1) or match.group(2)
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
                continue
            checked += 1
            path = target.split("#")[0].split("?")[0]
            resolved = (ROOT / path.lstrip("/")) if path.startswith("/") else (md.parent / path)
            if not resolved.exists():
                broken.append(f"{md.relative_to(ROOT)}: {target}")
    for line in broken:
        print(f"BROKEN {line}")
    print(f"{checked} relative links checked, {len(broken)} broken")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
