# Environment: dedicated QA Mac

This setup has two machines. The **lead** is the machine where your coding agent runs these
skills. The **worker** is a dedicated Mac with a real, logged-in desktop session, where an
agent with computer-use drives a visible Chrome window like a person would.

## Who does what

- **QA lead**: the agent on the lead machine. Writes the charter and briefs, runs the headless
  scripts, reads every screenshot, assigns severity and writes the verdict.
- **Executor**: the worker Mac. It receives one brief per job, drives the browser UI and
  returns observations and screenshots. It never assigns severity or a verdict.

## Sending a job

- Send each brief with the worker's submit command, `qa-submit` (in this edition's
  `extras/worker-setup/lead/`). `QA_SUBMIT` holds its path if it is not on `PATH`.
- One job at a time. If the worker is busy, wait; do not start a second job.
- A job that passes its deadline has an **unknown outcome**. It is never a pass and is never
  resubmitted automatically. Collect what exists and report the gap.
- Before the first real job of the day, send the built-in probe (`qa-submit --probe`, a
  view-only check of a public page) and confirm a screenshot comes back.
- `qa-submit` exit codes: `0` result written; `1` finished without a valid result; `2` nothing
  was sent; `3` the deadline passed, outcome unknown; `4` finished but results not collected.
  Only `0` gives you evidence to judge, and even then it is observations, not a pass.

## Where things run

- Headless scripts in `qa-site-audit/scripts/` run on the **lead** machine, each with its own
  throwaway browser profile. Never run them on the worker's desktop session.
- No shell toolchain on the worker Mac for a QA job: no scanners, command-line HTTP clients,
  OS scripting or package installs there. A hard rule, not a fallback. The worker drives the
  browser; everything else runs on the lead machine.
- Run folders live under `$QA_RUNS` on the lead machine (default `~/qa-runs`). Copy each job's
  screenshots into the run folder before judging them.
- Clean first visit: the brief tells the executor to use a new private window.

## Credentials

- Test, staging and demo sites: the test username and password go in the brief's `ACCESS`
  header. `qa-submit` deletes the brief once it is sent and the worker redacts the values
  from what it keeps (see the worker setup's troubleshooting guide for the limits).
- Production: never in a brief. Give only a reference, such as the name of a keychain item the
  worker's own session can read.
- Either way, credentials never appear in results, reports, screenshots, logs or git.

## Limits of this setup

- The worker tests what a real desktop browser shows. Mobile widths are a narrowed desktop
  window or emulation, not a phone; label them so.
- The worker cannot reach a site that only runs on the lead machine's localhost. Use a
  deployed or preview URL.
- MFA, CAPTCHA, payment forms and ID checks stop the job. Report them as blocked.

## Verdict

No extra cap. The executor is independent of the lead and uses a real browser, so the verdict
rules in the standards apply as written.
