# Lead setup

The lead is the Mac where you (or your coding agent) write QA briefs and review results. It
needs Python 3, `ssh`/`scp`, and network access to the worker.

## 1. Check, then apply

```bash
lead/setup-lead.sh --host <worker-user>@<worker-host>                 # read-only
lead/setup-lead.sh --host <worker-user>@<worker-host> --apply         # make changes, then probe
```

Rows:

| Row | Check | `--apply` |
|---|---|---|
| SSH key | a key in `~/.ssh` | creates `~/.ssh/id_ed25519` if there is none |
| Config | `~/.config/qa-worker/config.json` has host and base | writes it |
| Key authorised | `ssh -o BatchMode=yes` works, so no password prompt | **never** runs password auth. It prints the `ssh-copy-id` command for you to run once |
| Worker set up | `qa-submit --check`: queue folders, LaunchAgent, GUI self-check | none. Fix it on the worker with `worker/install.sh --apply` |
| Probe round trip | `qa-submit --probe` | runs it (also: `--probe`) |

The first `ssh` to a new worker asks you to trust its host key. Run `ssh <worker-user>@<worker-host>`
once, interactively. If you can, compare the fingerprint with the one the worker shows:
`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.

## 2. Config

`~/.config/qa-worker/config.json` (or `--config`, or `$QA_WORKER_CONFIG`):

```json
{
  "host": "<worker-user>@<worker-host>",
  "base": "~/qa-worker",
  "effort": "medium",
  "busyWaitSeconds": 1800,
  "timeout": 3600
}
```

- `base` is the queue folder on the worker. `~/` is resolved on the worker.
- `effort` is the reasoning effort for each job: `minimal`, `low`, `medium`, `high` or `xhigh`.
  Override it per run with `--effort`.
- `busyWaitSeconds` is how long to wait for a busy worker before giving up with exit `2` ("NOT SUBMITTED"), without
  submitting.
- `timeout` is how long to wait for the result before declaring the outcome unknown (exit `3`).

An existing settings file with these keys under a `"worker"` block is also accepted. Point at it
with `--config` or `$QA_WORKER_CONFIG`.

The model is not chosen by the brief or by the lead. The worker's operator chooses it with an
optional model pattern (see [TROUBLESHOOTING](TROUBLESHOOTING.md)); with none set, the worker runs
the first model listed by `codex debug models`. A `MODEL=` line in a brief is ignored.

## 3. Running a brief

```bash
lead/qa-submit path/to/brief.md                     # results in path/to/qa-worker-results/<job-id>/
lead/qa-submit --out ./qa-runs path/to/brief.md        # --keep-brief is only for non-sensitive briefs
```

A good brief names: the exact URL and build, the browser, the viewport, the user role, each
check with its expected result, the permitted actions (default: view only), and how to sign in.

- Test, staging or demo site: put the test username and password directly in one leading
  `ACCESS` JSON header. Its keys are `environment` (`test`, `staging` or `demo`), `username`
  and `password`; every value is a JSON string. Put the task below this header. Do not place
  credentials in free prose, filenames or any other header. Prepare this temporary file
  outside git; never include actual credential values in commands, docs or history.
  `qa-submit` purges an ACCESS brief on every terminal outcome, even if nothing was sent.
  `--keep-brief` is forbidden for it. Recreate it securely before an authorised retry.
- Live production: use an ACCESS header with only `environment: "production"` and
  `secureReference` (a non-empty string). Inline username/password keys are rejected.
  Put only a secure reference in the brief (for example "Keychain item
  `qa-prod-login`, readable in the worker's GUI session"). Check beforehand that the worker's
  **GUI session** can read it: the `GUI: Keychain unlocked` row. A credential stored on the lead
  is not on the worker.

`qa-submit` appends the result contract. The worker writes `result.json` with
`status` (`completed` / `partial` / `blocked`), `observations` (check, observed, as_expected,
evidence), `blockers` and `evidence`. Then **you** review the screenshots and decide. Exit `0`
means a valid result came back, not that the product passed.

Exit codes: `0` result written · `1` no valid result (evidence still collected) · `2` nothing
was sent: not configured, transport error, or worker busy ("NOT SUBMITTED"; non-sensitive briefs are kept, ACCESS briefs are purged) ·
`3` a sent job passed its deadline, so the outcome is unknown · `4` a sent job finished but its
results could not be collected. The job id and the worker path are printed; copy the folder by
hand and do not resubmit.
The job id is printed. The job is not cancelled and is never replayed automatically. Look at
`done/<job-id>/` on the worker before you resubmit, especially if the brief changed anything.

Credential declarations are validated before dispatch and independently by the worker.
The declared values are redacted literally from retained text; the worker does not guess
credentials from arbitrary prose. Normal screenshots remain available, but never capture
a login form or visible credentials. See [cleanup limits](TROUBLESHOOTING.md#credential-cleanup-and-interruption).
