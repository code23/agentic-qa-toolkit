#!/usr/bin/env python3
"""Build the QA toolkit packages: the shared skills plus one edition's files each.

    python3 tools/build.py                  build every edition into dist/
    python3 tools/build.py --edition local  build one edition
    python3 tools/build.py --check          stage and scan every edition, write nothing

A package is refused (exit 1) if the scan finds a machine-specific path, a real-looking
email address, a secret pattern, a run artefact, or a skill whose name does not match its
folder. Maintainers can also refuse private words: put one per line in a file outside this
repository and point QA_TOOLKIT_DENYLIST at it (see docs/maintaining.md).
"""
import argparse
import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "skills"
EDITIONS = ROOT / "editions"
SKILLS = ("qa-standards", "qa-site-audit", "qa-release")
TEXT_SUFFIXES = {".md", ".py", ".js", ".ts", ".json", ".csv", ".txt", ".sh", ".template", ".plist", ""}
# Past-run artefacts and build debris never belong in a package.
BAD_NAMES = re.compile(r"(__pycache__|\.pyc$|\.DS_Store$|(^|/)findings\.json$|(^|/)regression\.(md|json)$|"
                       r"RESULT\.md$|\.(png|jpe?g|gif|webp|pdf|zip|tgz|har|log)$)", re.I)
PATTERNS = {
    # Someone's home folder or a mounted volume. System paths (/opt/homebrew, ~/Library/LaunchAgents) are fine.
    "machine path": re.compile(r"((?<![\w.:])/(?:Users|home)/(?!Shared(?![\w.-]))[A-Za-z0-9._-]*[A-Za-z0-9_](?![A-Za-z0-9_-])|(?<![\w.:])/workspace\b|(?<![\w.:])/Volumes/|\b[A-Za-z]:\\Users\\)"),
    # Real-looking addresses only: example.* domains, reserved test endings and name@IP strings are fine.
    "email address": re.compile(r"\b[\w.+-]+@(?!(?:[\w-]+\.)*example\.(?:com|org|net|co\.uk)(?!\.?[\w-])|(?:[\w-]+\.)+(?:local|invalid|test|example)(?!\.?[\w-])|\d{1,3}(?:\.\d{1,3}){3}(?!\.?[\w-]))[\w-]+(?:\.[\w-]+)+\b"),
    "secret pattern": re.compile(r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|xox[bp]-[A-Za-z0-9-]{10,}|"
                                 r"AKIA[0-9A-Z]{16}|Bearer [A-Za-z0-9_\-.]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY)"),
}
ZIP_TIME = (2026, 1, 1, 0, 0, 0)   # fixed, so the same source gives the same zip


def normalise(text):
    """Lower-case and turn every run of spaces, line breaks, hyphens and underscores into one space,
    so 'Blue-Harbor', 'blue_harbor' and a name split across two lines all read as 'blue harbor'."""
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text)   # zero-width characters hide nothing
    return re.sub(r"[\s\u00a0_-]+", " ", text.lower())


def deny_terms():
    """(term, regex) pairs from the file named by QA_TOOLKIT_DENYLIST; none if it is not set.
    Whole-word by default, with an optional plural or possessive ending. A leading '*' means
    the term is distinctive enough to refuse anywhere, even inside a longer word."""
    out = []
    path = os.environ.get("QA_TOOLKIT_DENYLIST")
    if not path:
        return out
    for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        anywhere, term = line.startswith("*"), normalise(line.lstrip("*")).strip()
        body = re.escape(term)
        out.append((term, re.compile(body if anywhere else r"(?<![a-z])" + body + r"(?:'?s)?(?![a-z])")))
    return out


def denied_in(text, terms):
    """Denied terms found in text, after normalising it."""
    flat = normalise(text)
    return [term for term, rx in terms if rx.search(flat)]


def stage(edition, dest):
    """Copy core skills, then lay the edition's files over them."""
    overlay = EDITIONS / edition
    for need in ("README.md", "environment.md"):
        if not (overlay / need).is_file():
            sys.exit(f"build: editions/{edition}/{need} is missing")
    shutil.copytree(CORE, dest / "skills", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    shutil.copy2(overlay / "environment.md", dest / "skills" / "qa-standards" / "environment.md")
    shutil.copy2(overlay / "README.md", dest / "README.md")
    if (overlay / "extras").is_dir():
        shutil.copytree(overlay / "extras", dest / "extras", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    (dest / "VERSION").write_text((ROOT / "VERSION").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy2(ROOT / "LICENSE", dest / "LICENSE")


def is_python(path, text):
    return path.suffix == ".py" or (path.suffix == "" and text.startswith("#!") and "python" in text.splitlines()[0])


def scan(dest):
    """Return (problems, notes). Problems refuse the package; notes are for a person to read."""
    problems, hosts, node_files = [], set(), []
    terms = deny_terms()
    for skill in SKILLS:
        md = dest / "skills" / skill / "SKILL.md"
        if not md.is_file():
            problems.append(f"skills/{skill}/SKILL.md is missing"); continue
        m = re.search(r"^name:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
        if not m or m.group(1).strip() != skill:
            problems.append(f"skills/{skill}/SKILL.md: name must be '{skill}'")
    for f in sorted(p for p in dest.rglob("*") if p.is_file()):
        rel = f.relative_to(dest).as_posix()
        if BAD_NAMES.search(rel):
            problems.append(f"{rel}: run artefact or build debris"); continue
        for term in denied_in(rel, terms):
            problems.append(f"{rel}: denied term '{term}' in the file path")
        for label, rx in PATTERNS.items():
            if rx.search(rel): problems.append(f"{rel}: {label} in the file path")
        if f.suffix not in TEXT_SUFFIXES:
            problems.append(f"{rel}: unexpected file type"); continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{rel}: not UTF-8 text"); continue
        lines, found = text.splitlines(), set()
        for n, line in enumerate(lines, 1):
            for term in denied_in(line, terms):
                found.add(term); problems.append(f"{rel}:{n}: denied term '{term}'")
        for term in denied_in(text, terms):   # catches a name split across lines
            if term not in found: problems.append(f"{rel}: denied term '{term}' (split across lines)")
        for n, line in enumerate(lines, 1):
            for label, rx in PATTERNS.items():
                if rx.search(line): problems.append(f"{rel}:{n}: {label}")
            hosts.update(h.lower() for h in re.findall(r"https?://([A-Za-z0-9.-]+)", line))
        if is_python(f, text):
            try: ast.parse(text)
            except SyntaxError as e: problems.append(f"{rel}: Python syntax error: {e}")
        elif f.suffix == ".js":
            node_files.append(f)
    notes = [f"hosts mentioned: {', '.join(sorted(hosts)) or 'none'}"]
    node = shutil.which("node")
    if node_files and node:
        for f in node_files:
            r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
            if r.returncode: problems.append(f"{f.relative_to(dest).as_posix()}: JavaScript syntax error")
        notes.append(f"JavaScript syntax: {len(node_files)} files checked")
    elif node_files:
        notes.append("JavaScript syntax: NOT CHECKED (node not found)")
    return problems, notes


def write_zip(dest, name, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(p for p in dest.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(f"{name}/{f.relative_to(dest).as_posix()}", ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if f.stat().st_mode & 0o111 else 0o644) << 16
            z.writestr(info, f.read_bytes())
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


def main():
    names = sorted(p.name for p in EDITIONS.iterdir() if p.is_dir())
    ap = argparse.ArgumentParser(description="Build the shareable QA toolkit packages.")
    ap.add_argument("--edition", choices=names + ["all"], default="all")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--check", action="store_true", help="stage and scan only; write no zip")
    a = ap.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    failed = False
    for edition in (names if a.edition == "all" else [a.edition]):
        name = f"qa-toolkit-{edition}-{version}"
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / name
            dest.mkdir()
            stage(edition, dest)
            problems, notes = scan(dest)
            count = sum(1 for p in dest.rglob("*") if p.is_file())
            if problems:
                failed = True
                print(f"REFUSED {name}: {len(problems)} problem(s)")
                for p in problems: print(f"  {p}")
                continue
            for n in notes: print(f"  [{edition}] {n}")
            if not os.environ.get("QA_TOOLKIT_DENYLIST"):
                print(f"  [{edition}] private word list: not used (QA_TOOLKIT_DENYLIST is not set)")
            if a.check:
                print(f"OK {name}: {count} files, scan clean (not written)")
            else:
                target, digest = write_zip(dest, name, Path(a.out))
                print(f"BUILT {target} ({count} files) sha256 {digest}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
