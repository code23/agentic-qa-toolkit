# Agentic QA Toolkit: local edition

QA on your own machine, on demand. Your coding agent drives a browser itself and reports what
it found. Nothing is sent anywhere. Use this edition for quick checks while you build,
including sites that only run on localhost.

This edition gives you a **preflight**, not a release decision: the agent that built the
change is the one testing it. For sign-off, use the dedicated QA Mac or hosted QA bot edition.

## What's in the package

| Path | What it is |
|---|---|
| `skills/qa-standards/` | Charter, severity S1-S4, priority P1-P4, defect format, evidence rules, verdict rules. Read first. |
| `skills/qa-standards/environment.md` | How this edition works: browser, credentials, limits and the preflight verdict cap. |
| `skills/qa-site-audit/` | Whole-site, read-only audit: method references and headless check scripts. |
| `skills/qa-release/` | Pre-release QA programme: charter, coverage matrix, defect register, report templates, Playwright templates. |

## Install

1. From the repository root run `./install.sh --edition local --target <your agent's skills folder>`,
   check the output, then run it again with `--apply`. From a release zip, copy the three
   folders in `skills/` into your agent's skills folder instead.
2. Give the agent a browser tool if it does not have one.
3. Report scripts (`report_check.py`, `report_export.py`, used whenever a report
   has screenshots): Python 3.9+ with `markdown`, and Chrome for a PDF. Optional, for the headless
   scripts: Node 22.12+, `puppeteer-core` 25 and Google Chrome; Python
   3.9+ with `requests`, `beautifulsoup4` and `lxml`. Install `puppeteer-core` in a scratch
   folder and point `NODE_PATH` at it. Do not run `npm install` inside the skill folder.
4. Optional: set `QA_RUNS` to where run folders should live (default `~/qa-runs`).

## How a run goes

1. You ask for QA of a flow or page, with the URL.
2. The agent writes a short charter, walks the flow in a private browser window and takes
   screenshots.
3. It re-checks each finding, then reports findings with a preflight verdict line.

## Safety

Read-only by default. Test accounts and test data only, never a window signed in to your own
accounts. The run stops at a payment form, a phone code, an ID check or a CAPTCHA. The full
rules are at the top of each skill.
