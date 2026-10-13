#!/usr/bin/env python3
"""Create, checkpoint, and validate a release-QA run folder."""

from __future__ import annotations
import os

import argparse
import csv
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSET_ROOT = SKILL_ROOT / "assets"
DEFAULT_RUN_ROOT = Path(os.environ.get("QA_RUNS", "~/qa-runs")).expanduser()
MODES = {"audit-only", "audit-and-repair"}
PHASE_STATUSES = {"in_progress", "completed", "blocked"}
EXECUTION_STATUSES = {
    "planned",
    "executed",
    "blocked",
    "not_applicable",
    "not_reachable",
    "not_executed",
}
VERIFICATION_STATUSES = {
    "",
    "independently-reproduced",
    "evidence-reviewed",
    "provisional",
}
VERDICTS = {"PASS", "PASS WITH CONDITIONS", "FAIL", "INCONCLUSIVE"}
# Verdict lines for setups whose environment note caps the verdict at a preflight.
PREFLIGHT_VERDICTS = {"PREFLIGHT: no blocking findings", "PREFLIGHT: findings"}
PASSING_VERDICTS = {"PASS", "PASS WITH CONDITIONS", "PREFLIGHT: no blocking findings"}


def base_verdict(text):
    """Return the verdict without a trailing scope note in brackets, or None if it is not an allowed verdict."""
    if text is None:
        return None
    base = re.sub(r"\s*\([^()]*\)\s*$", "", text.strip())
    return base if base in VERDICTS | PREFLIGHT_VERDICTS else None


REQUIRED_FILES = {
    "manifest.json",
    "charter.md",
    "coverage.csv",
    "defects.md",
    "report.md",
    "checkpoints.jsonl",
}
REQUIRED_COVERAGE_COLUMNS = {
    "id",
    "layer",
    "surface",
    "role",
    "state_or_case",
    "risk",
    "oracle",
    "execution",
    "verification",
    "evidence",
    "defect",
    "notes",
}
AUTHORITY_FIELDS = {
    "safe_test_mutations",
    "sandbox_provider",
    "money_cap",
    "merge",
    "deploy",
    "production_writes",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "release-qa"


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load_manifest(run_dir: Path) -> dict:
    path = run_dir / "manifest.json"
    if not path.is_file():
        raise ValueError(f"missing manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def command_init(args: argparse.Namespace) -> int:
    if args.mode not in MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(MODES))}")

    run_id = f"{slugify(args.project)}-{datetime.now().astimezone().date().isoformat()}"
    run_dir = Path(args.output).expanduser().resolve() if args.output else DEFAULT_RUN_ROOT / run_id
    if run_dir.exists():
        raise ValueError(f"refusing to overwrite existing run: {run_dir}")

    run_dir.mkdir(parents=True, exist_ok=False)
    for dirname in ("briefs", "evidence", "logs", "receipts", "screenshots"):
        (run_dir / dirname).mkdir()

    for filename in ("charter.md", "coverage.csv", "defects.md", "report.md"):
        shutil.copy2(ASSET_ROOT / filename, run_dir / filename)

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "project": args.project,
        "target": args.target,
        "repo": str(Path(args.repo).expanduser().resolve()) if args.repo not in ("none", "n/a") else args.repo,
        "environment": args.environment,
        "mode": args.mode,
        "tracking_issue": args.tracking_issue,
        "status": "initialized",
        "current_phase": "0-authority-and-baseline",
        "next_action": "Complete charter.md, authority fields, and the coverage inventory.",
        "authority": {
            "safe_test_mutations": None,
            "sandbox_provider": None,
            "money_cap": None,
            "merge": None,
            "deploy": None,
            "production_writes": False,
        },
        "top_risks": [],
    }
    write_json(run_dir / "manifest.json", manifest)
    (run_dir / "checkpoints.jsonl").write_text("", encoding="utf-8")
    print(run_dir)
    return 0


def command_checkpoint(args: argparse.Namespace) -> int:
    if args.status not in PHASE_STATUSES:
        raise ValueError(
            f"status must be one of: {', '.join(sorted(PHASE_STATUSES))}"
        )
    run_dir = Path(args.run).expanduser().resolve()
    manifest = load_manifest(run_dir)
    timestamp = utc_now()
    manifest.update(
        {
            "updated_at": timestamp,
            "status": args.status,
            "current_phase": args.phase,
            "next_action": args.next,
        }
    )
    write_json(run_dir / "manifest.json", manifest)
    event = {
        "timestamp": timestamp,
        "phase": args.phase,
        "status": args.status,
        "next_action": args.next,
    }
    with (run_dir / "checkpoints.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")
    print(f"checkpointed {manifest['run_id']}: {args.phase} ({args.status})")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run).expanduser().resolve()
    errors: list[str] = []

    missing = sorted(name for name in REQUIRED_FILES if not (run_dir / name).is_file())
    if missing:
        errors.append(f"missing files: {', '.join(missing)}")

    try:
        manifest = load_manifest(run_dir)
    except (ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        manifest = {}
    if not isinstance(manifest, dict):
        errors.append("manifest.json must hold a JSON object")
        manifest = {}

    for field in (
        "run_id",
        "project",
        "target",
        "repo",
        "environment",
        "mode",
        "tracking_issue",
        "status",
        "current_phase",
        "next_action",
    ):
        if not manifest.get(field):
            errors.append(f"manifest field is empty: {field}")
    mode = manifest.get("mode")
    if not isinstance(mode, str) or mode not in MODES:
        errors.append(f"invalid manifest mode: {mode!r}")

    authority = manifest.get("authority", {})
    if not isinstance(authority, dict):
        errors.append("manifest authority must be an object")
        authority = {}
    missing_authority = sorted(AUTHORITY_FIELDS - set(authority))
    if missing_authority:
        errors.append(f"missing authority fields: {', '.join(missing_authority)}")
    if args.final:
        unresolved = sorted(key for key in AUTHORITY_FIELDS if authority.get(key) is None)
        if unresolved:
            errors.append(f"unresolved authority fields: {', '.join(unresolved)}")

    coverage_path = run_dir / "coverage.csv"
    rows: list[dict[str, str]] = []
    if coverage_path.is_file():
        try:
            with coverage_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                headers = set(reader.fieldnames or [])
                missing_headers = sorted(REQUIRED_COVERAGE_COLUMNS - headers)
                if missing_headers:
                    errors.append(f"coverage.csv missing columns: {', '.join(missing_headers)}")
                rows = list(reader)
        except (csv.Error, UnicodeDecodeError) as exc:
            errors.append(f"coverage.csv cannot be read: {exc}")
            rows = []
        for index, row in enumerate(rows, start=2):
            execution = (row.get("execution") or "").strip()
            verification = (row.get("verification") or "").strip()
            if execution not in EXECUTION_STATUSES:
                errors.append(f"coverage.csv:{index} invalid execution: {execution!r}")
            if verification not in VERIFICATION_STATUSES:
                errors.append(
                    f"coverage.csv:{index} invalid verification: {verification!r}"
                )
            if not (row.get("id") or "").strip():
                errors.append(f"coverage.csv:{index} missing id")

    if args.final:
        status = manifest.get("status")
        if not isinstance(status, str) or status not in {"completed", "blocked"}:
            errors.append(
                "final validation requires manifest status completed or blocked"
            )
        if not rows:
            errors.append("final validation requires at least one coverage row")
        unfinished = [
            row.get("id", "<missing>")
            for row in rows
            if (row.get("execution") or "").strip() == "planned"
        ]
        if unfinished:
            errors.append(f"planned coverage remains: {', '.join(unfinished)}")
        for index, row in enumerate(rows, start=2):
            for field in ("layer", "surface", "risk", "oracle"):
                if not (row.get(field) or "").strip():
                    errors.append(f"coverage.csv:{index} missing {field}")
            if (
                (row.get("execution") or "").strip() == "executed"
                and not (row.get("evidence") or "").strip()
            ):
                errors.append(f"coverage.csv:{index} executed row has no evidence")
        for filename in ("charter.md", "report.md"):
            path = run_dir / filename
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                if "<complete" in text or "PENDING" in text:
                    errors.append(f"unresolved template marker in {filename}")

        top_risks = manifest.get("top_risks")
        if not isinstance(top_risks, list) or not top_risks:
            errors.append("final validation requires at least one top risk")
            top_risks = []
        if any(not isinstance(risk, str) for risk in top_risks):
            errors.append("every top risk must be text")
            top_risks = [risk for risk in top_risks if isinstance(risk, str)]

        for risk in top_risks:
            mapped = [row for row in rows if (row.get("risk") or "").strip() == risk]
            if not mapped:
                errors.append(f"top risk has no coverage row: {risk}")

        report_path = run_dir / "report.md"
        report_verdict = None
        if report_path.is_file():
            report_text = report_path.read_text(encoding="utf-8")
            written = re.findall(r"^Verdict:\s*(.+?)\s*$", report_text, re.MULTILINE)
            if len(written) > 1:
                errors.append(f"report.md has {len(written)} 'Verdict:' lines; exactly one is allowed")
            else:
                written_verdict = written[0] if written else None
                report_verdict = base_verdict(written_verdict)
                if report_verdict is None:
                    errors.append(f"invalid or missing report verdict: {written_verdict!r}")

        uncovered_top_risks = [
            risk
            for risk in top_risks
            if not any(
                (row.get("risk") or "").strip() == risk
                and (row.get("execution") or "").strip() == "executed"
                for row in rows
            )
        ]
        if uncovered_top_risks and report_verdict in PASSING_VERDICTS:
            errors.append(
                "passing verdict is invalid while top risks lack executed coverage: "
                + ", ".join(uncovered_top_risks)
            )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"valid release-QA run: {run_dir} "
        f"({len(rows)} coverage row{'s' if len(rows) != 1 else ''})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a new run folder")
    init_parser.add_argument("--project", required=True)
    init_parser.add_argument("--target", required=True)
    init_parser.add_argument("--repo", default="none", help="local repo path, or none")
    init_parser.add_argument("--environment", required=True)
    init_parser.add_argument("--mode", required=True, choices=sorted(MODES))
    init_parser.add_argument("--tracking-issue", default="draft-not-filed", help="tracker issue id/link, or draft-not-filed")
    init_parser.add_argument("--output")
    init_parser.set_defaults(func=command_init)

    checkpoint_parser = subparsers.add_parser(
        "checkpoint", help="record the current phase and next action"
    )
    checkpoint_parser.add_argument("--run", required=True)
    checkpoint_parser.add_argument("--phase", required=True)
    checkpoint_parser.add_argument("--status", required=True, choices=sorted(PHASE_STATUSES))
    checkpoint_parser.add_argument("--next", required=True)
    checkpoint_parser.set_defaults(func=command_checkpoint)

    validate_parser = subparsers.add_parser("validate", help="validate a run folder")
    validate_parser.add_argument("--run", required=True)
    validate_parser.add_argument("--final", action="store_true")
    validate_parser.set_defaults(func=command_validate)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, csv.Error) as exc:   # json.JSONDecodeError and UnicodeDecodeError are ValueErrors
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
