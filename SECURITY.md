# Security

## Reporting a problem

Please report security problems privately, not in a public issue. On this repository's
**Security** tab, choose **Report a vulnerability**. Include what you found, how to
reproduce it and which version you used.

You should get a first reply within five working days. Please give us reasonable time to
fix the problem before you share it publicly.

## What counts

- A script that sends data somewhere it should not, follows a redirect it should not, or
  writes a secret, token or personal data into its output.
- A way for a web page under test to make a script run commands, read local files or leave
  the hosts it was given.
- A flaw in the worker setup: the SSH transport, the job lock or credential clean-up.
- A skill instruction that would lead an agent to submit a form, make a payment, send a
  message or get around a login, CAPTCHA or identity check.

## What these tools do, so you can judge the risk

- The scripts load the pages you list in a headless browser. Each page runs as it would for
  any visitor, including its own third-party and analytics requests. The scripts' own
  requests are plain GETs; they never type into or submit a form themselves, and they
  block a page from navigating to a host you did not list or by any method other than GET.
  They cannot stop what a site's own script does when its cookie button is clicked. See
  [docs/responsible-use.md](docs/responsible-use.md).
- The worker Mac setup runs every brief with the agent's approval prompts and sandbox
  switched off. That is how unattended computer use works, and it is why the installer
  needs `--accept-unsandboxed` and the runner will not start a job without that record.
  Treat the worker as a machine that will do whatever a brief says: dedicated Mac, dedicated
  user, nothing personal on it, and only briefs you wrote or trust.
- `qa-send` posts a job to a webhook you configure. Its key lives in a file only you can
  read; the tool refuses to run if others can read it, and never follows a redirect.
- Nothing here phones home. There is no telemetry.

## Supported versions

Fixes are made on the latest release only.
