# QA toolkit: hosted QA bot edition

QA run by a bot on a hosted machine. A coding agent or a person sends a URL and a short brief;
the bot tests it with its own browser and reports back in its chat. Use this edition for
hands-off checks of public, staging or preview URLs.

## What's in the package

| Path | What it is |
|---|---|
| `skills/qa-standards/` | Charter, severity S1-S4, priority P1-P4, defect format, evidence rules, verdict rules. Read first. |
| `skills/qa-standards/environment.md` | How this edition works: who drives the browser, how jobs arrive, credentials, limits. |
| `skills/qa-site-audit/` | Whole-site, read-only audit: method references and headless check scripts. |
| `skills/qa-release/` | Pre-release QA programme: charter, coverage matrix, defect register, report templates, Playwright templates. |
| `extras/qa-send` | Small sender script: posts a job to the bot's webhook. |
| `extras/commands/` | The `/qa-send` command for two coding agents (one file each). |
| `extras/config.example.json` | Placeholder config for the sender. |

## Install on the bot's machine

1. From the repository root run `./install.sh --edition hosted-bot --target <the bot's skills folder>`,
   check the output, then run it again with `--apply`. From a release zip, copy the three
   folders in `skills/` into the bot's skills folder instead.
2. Set `QA_RUNS` in the bot's environment (default `~/qa-runs`).
3. Report scripts (`report_check.py`, `report_export.py`, used whenever a report
   has screenshots): Python 3.9+ with `markdown`, and Chrome for a PDF. For the headless scripts:
   Node 22.12+, `puppeteer-core` 25 and Chrome or Chromium (`CHROME_PATH`);
   Python 3.9+ with `requests`, `beautifulsoup4` and `lxml`. Install `puppeteer-core` in a
   scratch folder and point `NODE_PATH` at it. Do not run `npm install` inside the skill folder.
4. Give the bot a webhook that accepts the job fields below and starts a run.

## Install on each developer machine (optional)

Paths below are relative to this edition's folder: `editions/hosted-bot/` in a clone of the
repository, or the top folder of the release zip.

1. Put `extras/qa-send` on your `PATH` and make it executable.
2. Copy `extras/config.example.json` to `~/.config/qa-send/config.json`, set permissions to
   owner-only, and fill in your webhook URL and key yourself. The URL must be https.
3. Copy the matching file from `extras/commands/` into your coding agent's commands folder.

## Job fields

`url` (required), `depth` (`quick`, `deep` or `release`), `brief`, `project`, `branch`,
`commit`. No credentials and no customer data in any field. The sender refuses a URL that
carries a username or password, a local or private address, a config file other users can
read, and any redirect from the webhook.

## Safety

Read-only by default. Test accounts and test data only. The run stops at a payment form, a
phone code, an ID check or a CAPTCHA. Nothing is filed, sent or published without the
owner's approval. The full rules are at the top of each skill.
