# Environment: hosted QA bot

This setup is one hosted machine running a QA bot. People and coding agents send it a job
(a URL, a depth and a short brief) and it reports back in its chat.

## Who does what

- **QA lead**: the bot itself, running these skills. Writes the charter, runs the headless
  scripts, reads every screenshot, assigns severity and writes the verdict.
- **Executor**: the bot's own desktop browser, or a browser subagent it starts with one chunk
  brief at a time. The executor reports observations only.

## Receiving a job

- Jobs arrive through the bot's webhook (see `extras/qa-send` and the `/qa-send` command) or
  are typed straight into the bot's chat.
- Depth `quick` is a focused check of the changed flows. `deep` uses `qa-site-audit`.
  `release` uses `qa-release`.
- QA runs only when someone asks. No scheduled runs unless the owner set one up.

## Delivering the report

- A report sent as a file is exported with qa-standards `scripts/report_export.py`, so its
  screenshots are inside it. Open the export and check before sending.
- A report posted as chat text attaches the screenshot for each visual finding next to that
  finding. Never send a report whose screenshots exist only in the run folder.

## Where things run

- Headless scripts and the executor's browser are on the same machine. The scripts launch
  their own headless browser with a throwaway profile; they never attach to the executor's
  browser.
- Run folders live under `$QA_RUNS` (set it in the bot's environment; default `~/qa-runs`).
- Clean first visit: a new private window, or the site's data cleared in browser settings.

## Credentials

- Never in a job brief, on any environment. The webhook payload is not a secret store.
- If a login is in scope, the owner gives the bot a dedicated test account through the bot's
  own secret storage. No test account: mark the logged-in coverage `blocked`.

## Limits of this setup

- The bot cannot reach localhost or private networks. Jobs need a public or preview URL.
- Mobile is emulated only. Say "emulated" in the report.
- Hosted machines often block some outbound ports. A check that cannot run for that reason is
  `not executed (network)`, never a pass.
- A job that names a branch or commit has not proved the deployed build matches it. Say
  "as reported by the job" unless the build was confirmed.

## Verdict

The standards' verdict rules apply: the bot did not write the change it is testing. State
the scope in brackets after the verdict when it is narrow, for example
"PASS WITH CONDITIONS (quick, logged-out only)".
