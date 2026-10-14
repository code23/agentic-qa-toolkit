# Agentic QA Toolkit

Skills and scripts that let a coding agent do website QA the way a senior tester would:
plan the run, test in a real browser, keep evidence, rate what it finds on a fixed scale and
give a verdict by rule.

It is for teams who already build with an AI coding agent and want its "I checked it, looks
fine" replaced by a report they can act on.

## What you get

| Skill | Use it for |
|---|---|
| `qa-standards` | Any QA job. The test charter, severity S1-S4, priority P1-P4, defect format, evidence rules and verdict rules. |
| `qa-site-audit` | A read-only audit of a whole site: layout at five widths, accessibility, performance, SEO, content, cookie consent and tracking, leftover debug code. |
| `qa-release` | A pre-release programme for a web product: every route and role in a coverage matrix, a defect register and a release verdict. |

The site audit comes with headless check scripts you can also run on their own. See
[docs/scripts.md](docs/scripts.md), and [examples/sample-report](examples/sample-report/) for
what a finished report looks like.

## Pick an edition

The method is the same everywhere. An edition says who drives the browser.

| Edition | Who drives the browser | Good for | Verdict |
|---|---|---|---|
| [Local](editions/local/README.md) | Your own coding agent, on your machine | Quick checks while you build, including localhost | Preflight only |
| [Hosted QA bot](editions/hosted-bot/README.md) | A bot on a hosted machine | Hands-off checks of public or preview URLs | Full |
| [Dedicated QA Mac](editions/dedicated-mac/README.md) | A separate Mac with a real desktop browser | Release sign-off and acceptance | Full |

Not sure? Start with Local. [docs/choosing-an-edition.md](docs/choosing-an-edition.md) has
the longer comparison.

## Quick start

### Let your agent install it

Paste this to your coding agent:

```text
Install the Agentic QA Toolkit from https://github.com/code23/agentic-qa-toolkit for me.
Clone it, read AGENTS.md in the repository and follow its install steps.
I want the Local edition. Show me the dry run before you apply anything.
```

Change "Local" to "Hosted QA bot" or "Dedicated QA Mac" if that is your setup. The agent
finds its own skills folder, shows you what it will copy, installs after you agree, and
checks the result. [AGENTS.md](AGENTS.md) is the script it follows; it is short enough to
read first.

### Or run it yourself

```bash
git clone https://github.com/code23/agentic-qa-toolkit.git
cd agentic-qa-toolkit
./install.sh --edition local --target ~/.claude/skills            # shows what it would do
./install.sh --edition local --target ~/.claude/skills --apply    # installs
```

Use your own agent's skills folder as the target.

### Then use it

Ask your agent:

```text
Use qa-standards to QA the sign-up flow on https://staging.example.com
```

You get a charter, a walk through the flow, findings in a fixed format with the screenshot
for each one shown beside it, and a verdict line. Reports export to a self-contained HTML
file or PDF with the images inside. To try the audit scripts with no site of your own, run them against the
[demo site](demo-site/README.md), which has faults planted on purpose.

Prefer a download? Each release on the repository's Releases page has one zip per edition,
with checksums.

## Safety

- **Read-only by default.** The agent looks, clicks through and opens, but does not submit,
  pay, send, invite or delete. Forms are typed into with test data to check validation and
  never submitted.
- **It stops** at a payment form, a phone code, an identity check or a CAPTCHA.
- **Test accounts only.** Never your own or a customer's.
- **Nothing is filed or sent** without your approval.
- **Only test sites you own or have permission to test.** See
  [docs/responsible-use.md](docs/responsible-use.md).

## Requirements

- An AI coding agent that supports skills (folders with a `SKILL.md`).
- For the scripts: Python 3.9+ with the packages in the two `requirements.txt` files under
  `skills/`, Node 22.12+ with `puppeteer-core` 25, and Chrome or Chromium.
- macOS or Linux. The Dedicated QA Mac edition needs a Mac for the worker.

## What's in the repository

```
skills/          the three skills, the same in every edition
editions/        one folder per edition: its README, environment note and extra tools
demo-site/       a made-up site with planted faults, for trying the scripts and for tests
examples/        a sample report
docs/            guides
tests/           offline tests for every script, the installer and the package build
tools/           package build, link check and the one-command check script
install.sh       installs one edition into your agent's skills folder
AGENTS.md        what an AI agent should do when asked to install or change this toolkit
```

## Documentation

- [Choosing an edition](docs/choosing-an-edition.md)
- [How a run works](docs/how-a-run-works.md)
- [The check scripts](docs/scripts.md)
- [Responsible use](docs/responsible-use.md)
- [Maintaining and releasing](docs/maintaining.md)

## Contributing

Issues are welcome: bugs, false positives, misses and ideas. Pull requests are not accepted
at the moment. See [CONTRIBUTING.md](CONTRIBUTING.md). Security problems go through
[SECURITY.md](SECURITY.md), not a public issue.

## Licence

[MIT](LICENSE).
