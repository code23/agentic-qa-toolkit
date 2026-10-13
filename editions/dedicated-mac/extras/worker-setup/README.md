# QA worker setup

Set up a dedicated Mac (the **worker**) to do visible, real-browser QA, and connect it to the Mac
where you run your coding agent (the **lead**).

The worker has a real, logged-in desktop session. The ChatGPT desktop app's bundled Codex CLI runs
there with the Computer Use plugin, so it can drive a real browser on a real screen. A
LaunchAgent runner watches a job folder. The lead sends a QA brief over SSH. The runner executes
it with `codex exec` and writes observations and screenshots. The lead collects them and judges.

```
 lead Mac                                   worker Mac (logged-in GUI session)
 ---------                                  ------------------------------------
 qa-submit brief.md  --SSH stdin-->  ~/qa-worker/jobs/<id>.task
                                     runner.sh (LaunchAgent) -> codex exec + Computer Use
                       <--scp--  ~/qa-worker/done/<id>/  result.json, screenshots, receipt.json
 you (or your agent) review the evidence and decide
```

**The lead judges, the worker only drives and evidences.** The worker never assigns severity,
priority or a pass/fail verdict. It reports what it checked, what it saw and the screenshots.

## Before you set this up

The runner starts every brief with `codex exec --dangerously-bypass-approvals-and-sandbox`
(see `worker/jobrun.py`). That flag turns off both the approval prompts and the sandbox of the
agent CLI. It is there because Computer Use drives the real screen unattended, with nobody at
the Mac to click "approve". The agent therefore runs with the full rights of the worker's macOS
user.

What that means in practice: anything that can steer the agent can act as that user. That
includes the text of a brief and the content of any page or app it opens, such as injected text
on a page under test. It can read or change that user's files, use its signed-in browsers and
apps, unlock and read Keychain items available to the GUI session, run shell commands and reach
the network. The runtime instructions tell the agent not to do these things unless the brief
names them, but that is a request to a model, not a technical barrier.

The installer makes you acknowledge this. `worker/install.sh --apply` refuses to install or
reload the runner, and changes nothing, unless you pass `--accept-unsandboxed`. That records a
small marker file, `<base>/unsandboxed-ack`, with the date and runner version. Check mode shows
whether it is recorded, and the runner starts no job without it: the job finishes `blocked` and
names the fix. There is no sandboxed mode, because Computer Use needs the bypass: either
acknowledge the risk or do not install the worker.

This is acceptable only under these conditions:

- The Mac and the macOS user are dedicated to this job. They hold no personal or company
  accounts, files or Keychain items beyond what QA needs.
- Briefs come only from people you trust.
- Use test accounts and test data only. Never real customer data or production credentials you
  could not afford to expose.
- Do not point the worker at sites you do not control or trust.
- Treat the Mac as exposed to whatever it browses: keep it off networks and shares you care
  about, and erase it when it changes hands (see [HANDOVER](docs/HANDOVER.md)).

## The two sides

| Side | What | Key files |
|---|---|---|
| Worker | A dedicated Mac and a dedicated macOS user, signed in to ChatGPT with **its operator's own account** | `worker/install.sh`, `worker/runner.sh` |
| Lead | Any Mac with SSH access to the worker | `lead/setup-lead.sh`, `lead/qa-submit` |

## Quick start

On the **worker**, logged in at its screen as the dedicated user (full guide: [docs/WORKER-SETUP.md](docs/WORKER-SETUP.md)):

```bash
git clone <this-repo> ~/qa-worker-setup
cd ~/qa-worker-setup/editions/dedicated-mac/extras/worker-setup
worker/install.sh            # check only: changes nothing, prints PASS/FAIL/WARN/MANUAL + fixes
worker/install.sh --apply --accept-unsandboxed   # read "Before you set this up" first; fixes what a
                                                 # script can, lists the manual steps, re-checks
```

On the **lead** (full guide: [docs/LEAD-SETUP.md](docs/LEAD-SETUP.md)):

```bash
lead/setup-lead.sh --host <worker-user>@<worker-host>            # check only
lead/setup-lead.sh --host <worker-user>@<worker-host> --apply    # key, config, then the probe
lead/qa-submit path/to/brief.md                                # run a real brief
```

The probe (`lead/qa-submit --probe`) is the only real end-to-end pass: a view-only check of
example.com that must come back with two observations and a screenshot. Every other row is a
precondition.

`qa-submit` exit codes: `0` result written, `1` finished without a valid result, `2` nothing
was sent (not configured, transport error, or the worker stayed busy: "NOT SUBMITTED"), `3` a sent
job passed its deadline, so the **outcome is unknown**, `4` a sent job finished but its results
could not be collected (copy `done/<job-id>/` by hand; do not resubmit).
A `3` is never a pass and the job is never replayed automatically.

## Policies

These are built into the worker's runtime instructions (`worker/runtime-instructions.template.md`)
and the result contract that `qa-submit` appends to every brief.

- **QA runs only when a person asks**, at the depth they ask for (a light check of the changed
  flows, or a deep audit). No scheduled QA jobs.
- **Logins.** Test, staging and demo sites: put the test username and password directly in the
  brief's leading `ACCESS` JSON header (see [LEAD-SETUP.md](docs/LEAD-SETUP.md)).
  Live production: never put credentials in the brief. Use a secure reference only, for
  example the name of a Keychain item that the worker's GUI session can read. Credentials never
  go into results, reports, logs, screenshots, git or memory. The lead deletes the brief file
  on every terminal submission outcome when `ACCESS` is declared, including rejection before
  sending; `--keep-brief` is forbidden for those briefs. The runner unlinks the queue brief
  before validation/execution, discards raw output, runs Codex with `--ephemeral`, redacts
  declared values from retained text and purges its private job folder before `.done`.
  See [credential cleanup limits](docs/TROUBLESHOOTING.md#credential-cleanup-and-interruption).
- **Observations, not verdicts.** The worker reports observations and evidence. It never assigns
  severity or a verdict.
- **Stop and report "blocked"** for MFA or CAPTCHA the brief does not cover, live payments,
  messages to real customers or people, and destructive actions.
- **Own accounts.** Each operator signs the worker in to ChatGPT with their own account. Never a
  shared login.
- **One screen, one job.** The runner runs jobs one at a time. `qa-submit` waits while the
  worker is busy. Nobody else should use the worker's desktop during a run.


## Repo layout

```
worker/install.sh                      check (default) / --apply / --json
worker/runner.sh                       the LaunchAgent job runner (bash 3.2)
worker/lockrun.py                      kernel flock job lock used by the runner (stdlib)
worker/jobrun.py                       private job execution, sanitization and purge (stdlib)
worker/launchagent.plist.template      label local.qa-worker.runner
worker/runtime-instructions.template.md  policies prepended to every job
worker/probe-brief.md                  the example.com setup probe
lead/qa-submit                       send a brief, collect evidence (Python 3 stdlib)
lead/setup-lead.sh                     check (default) / --apply / --probe
docs/                                  setup, troubleshooting, handover, after updates
```

The tests are in `tests/worker_setup/` at the repository root.

Docs: [WORKER-SETUP](docs/WORKER-SETUP.md) · [LEAD-SETUP](docs/LEAD-SETUP.md) ·
[TROUBLESHOOTING](docs/TROUBLESHOOTING.md) · [AFTER-UPDATES](docs/AFTER-UPDATES.md) ·
[HANDOVER](docs/HANDOVER.md)

## Development

From the repository root, run the unit tests with:

```bash
python3 -m unittest discover -s tests/worker_setup -v
```

They use stub commands, so they never touch the Mac they run on.
