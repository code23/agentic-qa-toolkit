# Choosing an edition

All three editions install the same three skills. They differ in one file,
`qa-standards/environment.md`, which tells the agent who drives the browser, how credentials
reach it, what the setup cannot do and whether the verdict is capped.

## At a glance

| | Local | Hosted QA bot | Dedicated QA Mac |
|---|---|---|---|
| Who plans and judges (QA lead) | Your coding agent | The bot | Your coding agent |
| Who drives the browser (executor) | The same agent | The bot's own browser | A separate Mac |
| Can test localhost | Yes | No | No |
| Tester is separate from the author of the change | No | Yes | Yes |
| Browser | Whatever tool your agent has | Desktop browser on the host | Real Chrome on a real screen |
| Mobile | Emulated | Emulated | Narrowed window or emulated |
| Extra setup | None | A bot with a webhook | A worker Mac and SSH |
| Strongest verdict | Preflight | PASS | PASS |

## Local

Choose it when you want a check while you build, and you are happy to treat the result as a
preflight. The agent that wrote the change is the one testing it, so this edition may not
issue a release PASS. Its verdict lines start with `PREFLIGHT:`.

## Hosted QA bot

Choose it when you want to hand off "test this URL" and carry on working. A bot on a hosted
machine receives the job, tests with its own browser and reports in its chat. It cannot
reach localhost, so every job needs a public or preview URL. The edition includes `qa-send`,
a small command your coding agent uses to post a job to the bot's webhook.

You supply the bot. This edition gives it the method; it does not include a bot runtime.

## Dedicated QA Mac

Choose it for release sign-off. A separate Mac with a logged-in desktop session drives a
visible Chrome window, one job at a time, and sends back observations and screenshots. Your
coding agent stays the QA lead: it writes the briefs, reads every screenshot and decides.
The edition includes the worker setup: an installer that checks before it changes anything,
a runner, and the `qa-submit` command.

The worker runs briefs with the agent's approvals and sandbox switched off, so it must be a
dedicated Mac and user with nothing personal on it. The installer makes you acknowledge
that before it sets anything up.

## Using more than one

They combine well: Local while building, Hosted QA bot on every preview deploy, Dedicated QA
Mac before a release. Install each on the machine that plays that part. Do not install two
editions into the same skills folder; the second would replace the first one's
`environment.md`.
