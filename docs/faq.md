# Frequently asked questions

## Cost and usage

### How many tokens does a run use?

These figures come from our own use: 1,282 executor jobs between September and October 2026,
grouped into runs. The executor is the agent that drives the browser, and it does most of the
reading. The QA lead adds roughly 10,000 to 100,000 output tokens per light run (writing
briefs, reading screenshots, writing the report), and more for a deep one.

| Run | Typical time | Executor fresh input | Executor output | Executor total input, including cached |
|---|---|---|---|---|
| Light: one to three flows | 15-30 minutes | about 130,000 | about 9,000 | about 3 million |
| Medium: four to twelve flows | 30 minutes to 2 hours | about 340,000 | about 26,000 | about 8.5 million |
| Deep site audit | 2-6 hours | about 1.3 million | about 120,000 | about 36 million |

The largest deep audits we have run, at 45 to 70 browser jobs, used 100 to 270 million total
input tokens. Treat those as the top of the range.

Most input is cached. On every step the executor re-reads the same page state and
screenshots, so total input looks large, but only 3-5% of it is fresh. Providers charge cached
input at a fraction of the normal price, and it counts for much less against subscription
limits.

These are the figures from our runs, not a promise: a site with long pages, many screenshots or
a slow executor uses more. We have not yet measured what share of a subscription's usage
window a run takes; we will add that here once we have.

### Do I need an API key?

No. The skills run inside your coding agent, so a normal subscription to that agent is
enough. The check scripts use no AI at all: they are plain Python and Node programs.

### How do I keep usage down?

- Start with a light QA of the flows a change touched. Run a deep audit before a release,
  not after every commit.
- Give the brief a clear scope: the URLs, the flows and what "good" looks like.
- Start the QA in a fresh agent session. A long session carries its whole history into every
  step.

## Hardware and setup

### Do I need a Mac mini?

No. Only the dedicated QA Mac edition needs a second machine, and it can be any Mac that runs
the current ChatGPT desktop app. A Mac mini is simply the cheapest way to get one. The local
edition runs on your own computer, and the hosted QA bot edition runs on a server you host.
[Choosing an edition](choosing-an-edition.md) compares the three.

### Does it work on a Mac? On Linux or Windows?

- **Mac**: yes, all three editions.
- **Linux**: yes for the local and hosted QA bot editions. The dedicated QA Mac worker needs
  macOS.
- **Windows**: not tested. The skills are plain text and should work with any agent that
  reads them; the scripts and the installer are written for macOS and Linux.

### Does it work with only Claude Code, or only Codex?

Yes. The skills are plain instruction files that both Claude Code and Codex load as skills, and
the QA lead can be either. Other agents that can read a skills folder and run commands can
follow them too, but those two are the ones we use it with.

One exception: in the dedicated QA Mac edition, the worker Mac drives the browser with the
ChatGPT desktop app's computer use, so that Mac needs a ChatGPT account even if your QA lead is
Claude Code.

### How long does setup take?

- **Local**: a few minutes. Your agent runs the installer and shows you a dry run first. The
  check scripts are optional and need Python, Node and Chrome.
- **Hosted QA bot**: install the skills on the bot's machine, then give it a webhook that
  starts a run. The webhook is yours to build; the sender script is included.
- **Dedicated QA Mac**: the longest. You prepare a Mac with its own macOS user, switch on Remote
  Login, sign in to the ChatGPT app, then run the check-first installer. Its
  [README](../editions/dedicated-mac/extras/worker-setup/README.md) walks through it.

### Which edition should I start with?

Local. It shows you how the method works on your own machine with nothing else to set up. Move
to the hosted QA bot or the dedicated QA Mac when you want a tester that did not write the
change: the local edition can only give a preflight, never a release pass.

## Safety and data

### Can it change or break the site I test?

It is built not to. The skills tell the agent never to submit, publish, pay, send or delete
anything, and to stop at payment forms, phone codes and CAPTCHAs. The check scripts only load
pages and click one cookie-banner button. A page still runs its own code as it would for any
visitor. [Responsible use](responsible-use.md) has the details. Only test sites you own or
have permission to test.

### Can it test pages behind a login?

Yes, with a dedicated test account. Never use a real customer's account or your own. Each
edition's `environment.md` says how credentials reach the tester; they are never written into
reports or screenshots.

### Where does my data go?

The toolkit itself sends nothing anywhere and has no telemetry. Your coding agent's provider
sees what the agent reads, as with any other task you give it: pages, screenshots and the
report. The hosted QA bot edition sends each job to the webhook you configure.

### Does the worker Mac run with its safety prompts switched off?

Yes. Unattended computer use needs it, so the worker runs each brief with the agent's approval
prompts and sandbox off. That is why the installer will not set the worker up until you
acknowledge it, and why the worker should be a dedicated Mac and user with nothing personal on
it, running only briefs you wrote or trust.

## Reports

### What does a report look like?

See the [sample report](../examples/sample-report/README.md), made against the demo site
that ships with the toolkit. Every finding that rests on a screenshot shows the screenshot
directly under it.

### Can reports carry our own logo and colours?

Yes. A brand is a folder kept outside the toolkit: name, colours, logo, fonts, cover text and
voice. Point `QA_BRAND` at it and every exported report uses it.
[Branding your reports](branding.md) explains how.

### How is this different from Playwright tests or Lighthouse?

It works alongside them. Automated tests prove the paths you thought of still work. This
toolkit adds a tester's walk through the real site, with evidence and a severity on every
finding, plus headless checks that are hard to write as unit tests (consent behaviour, layout
across widths, leftover debug code). The release skill also ships Playwright templates for
the checks worth automating.

## Project

### Can I contribute?

Bug reports and ideas are welcome as GitHub issues. We do not accept pull requests at the
moment. See [CONTRIBUTING.md](../CONTRIBUTING.md).
