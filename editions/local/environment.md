# Environment: on this machine, on demand

This setup is one machine: the developer's own. The coding agent runs these skills and drives
a browser itself, when the developer asks. Nothing is sent to another machine.

## Who does what

- **QA lead and executor are the same agent.** It writes the charter, drives the browser
  through whatever browser tool it has (a browser extension, a Playwright-style tool or a
  built-in browser), runs the headless scripts, and reports.
- Keep the two jobs apart anyway: first record observations and screenshots, then judge them.
- The executor rules say "browser UI only, no dev-tools protocols". Here that means: do the
  walk in one visible browser window the developer can watch. A browser tool that drives that
  window is allowed; a hidden second browser for the walk is not.

## Where things run

- Everything runs here, so localhost and private preview URLs are reachable.
- Run folders live under `$QA_RUNS` (default `~/qa-runs`), outside the project's repository.
- Clean first visit: a new private or guest window, or a separate browser profile.

## Rules that matter more on a personal machine

- Never test in a window signed in to the developer's own accounts. Use a private window or a
  separate profile, and only the dedicated test account.
- Close only the tabs this run opened.
- A dev-server page is not sign-off evidence. For anything visual, test a production-mode
  build or a deployed preview, and say which one was tested.

## Credentials

- The developer supplies the test account at run time through their own secret store or types
  it in themselves. Never write credentials into a brief, report or any file.

## Limits of this setup

- The agent that wrote the code is testing its own work, so nothing here is independent.
- Mobile is emulated only.
- Headless scripts need `puppeteer-core` and Chrome already installed; a missing dependency
  means that check is `blocked`, not skipped silently.

## Verdict cap

This setup produces a **preflight**, not a release decision.

- Allowed verdict lines: `PREFLIGHT: no blocking findings`, `PREFLIGHT: findings` or
  `INCONCLUSIVE`.
- Never write a bare `PASS`. A release or acceptance verdict needs a tester that did not
  write the change (the dedicated QA Mac or hosted QA bot editions).
- S1 and S2 candidates still need a second look: reproduce in a fresh private window or with
  a headless script before reporting them as verified.
