# QA toolkit: dedicated QA Mac edition

Real-browser QA on a dedicated Mac. Your coding agent (the lead) plans the run and judges the
evidence. A separate Mac (the worker) drives a visible Chrome window and sends back
observations and screenshots. Use this edition for release sign-off and acceptance checks.

## What's in the package

| Path | What it is |
|---|---|
| `skills/qa-standards/` | Charter, severity S1-S4, priority P1-P4, defect format, evidence rules, verdict rules. Read first. |
| `skills/qa-standards/environment.md` | How this edition works: who drives the browser, how jobs are sent, credentials, limits. |
| `skills/qa-site-audit/` | Whole-site, read-only audit: method references and headless check scripts. |
| `skills/qa-release/` | Pre-release QA programme: charter, coverage matrix, defect register, report templates, Playwright templates. |
| `extras/worker-setup/` | Sets up the worker Mac and connects the lead to it: a check-first installer, the runner, and the `qa-submit` command. |

## What you need

- **A worker Mac**: a dedicated Mac and a dedicated macOS user with a logged-in desktop
  session, the ChatGPT desktop app (its bundled Codex CLI and Computer Use plugin drive the
  browser) signed in with the operator's own account, and Remote Login (SSH) switched on.
- **A lead machine**: the Mac where your coding agent runs, with SSH access to the worker.

## Set up the worker Mac

Follow [extras/worker-setup/README.md](extras/worker-setup/README.md). The installer only
checks by default and prints what passes, what fails and how to fix it; `--apply` makes the
changes a script can make and lists the steps you must do by hand.

**Read this before you apply.** The worker runs every brief with the agent's approval
prompts and sandbox switched off, because driving a desktop browser unattended needs that.
The installer therefore refuses to set anything up until you pass `--accept-unsandboxed`,
and the runner refuses to run a job without that record. Use a dedicated Mac and a
dedicated macOS user with no personal data and no other credentials on it, and send it only
briefs you wrote or trust.

## Install (on the lead machine)

1. Install the skills: from the repository root run
   `./install.sh --edition dedicated-mac --target <your agent's skills folder>`, check the
   output, then run it again with `--apply`. From a release zip, copy the three folders in
   `skills/` into your agent's skills folder instead.
2. Connect the lead to the worker with `extras/worker-setup/lead/setup-lead.sh` and put
   `extras/worker-setup/lead/qa-submit` on your `PATH`. These paths are relative to this
   edition's folder: `editions/dedicated-mac/` in a clone of the repository, or the top
   folder of the release zip. Set `QA_SUBMIT=qa-submit`, and
   `QA_RUNS` to where run folders should live (default `~/qa-runs`).
3. Report scripts (`report_check.py`, `report_export.py`, used whenever a report
   has screenshots): Python 3.9+ with `markdown`, and Chrome for a PDF. For the headless scripts:
   Node 22.12+, `puppeteer-core` 25 and Google Chrome; Python 3.9+ with
   `requests`, `beautifulsoup4` and `lxml`. Install `puppeteer-core` in a scratch folder and
   point `NODE_PATH` at it. Do not run `npm install` inside the skill folder.
4. Send the probe job (`qa-submit --probe`) and check a screenshot comes back.

## How a run goes

1. You ask your agent for QA at a stated depth: one flow, a site audit or a release programme.
2. The lead writes the charter and one brief per flow, and sends each brief to the worker.
3. The worker drives the browser and returns observations and screenshots.
4. The lead runs the headless checks, reads every screenshot, re-checks each finding and
   writes the report with a verdict.

## Safety

Read-only by default. Test accounts and test data only. The run stops at a payment form, a
phone code, an ID check or a CAPTCHA. Nothing is filed, sent or published without your
approval. The full rules are at the top of each skill.
