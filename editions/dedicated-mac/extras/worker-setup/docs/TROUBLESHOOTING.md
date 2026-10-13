# Troubleshooting

Start with `worker/install.sh`, run on the worker in Terminal in the GUI session. Each row
prints its fix. The lessons below are from running workers in practice.

## "Computer Use is not active", or the plugin disappeared

ChatGPT app updates have **silently removed the Computer Use plugin**. Restarting the app does
not bring it back. The `Computer Use plugin` row shows it.

```bash
codex plugin list | grep computer-use        # look for "installed, enabled"
codex plugin add computer-use@openai-bundled # or unified-computer-use@openai-bundled
```

Then quit and reopen ChatGPT. `install.sh --apply` tries both plugin names.

## The runner cannot find codex

App updates have **moved the bundled CLI**. The app was renamed from `Codex.app` to
`ChatGPT.app` and the CLI moved inside the bundle. The bundle id stayed `com.openai.codex`. The
runner never hard-codes one path. It finds the app by bundle id (`mdfind`) and then looks for
`Contents/Resources/codex-cli/bin/codex`, `Contents/Resources/codex`, then any `codex`
executable in the bundle. It does this again for every job. To force a path, set `QA_WORKER_CODEX`
in the LaunchAgent environment.

## It works over SSH but not in jobs (or the reverse)

SSH sessions and the GUI session see **different Keychain and privacy (TCC) state**. Over SSH
the login Keychain is usually locked and screen capture is refused. Inside the GUI session they
work. That is why the `GUI:` rows come from the runner's own self-check
(`~/qa-worker/logs/gui-selfcheck.json`). Things to know:

- Run GUI-dependent checks in the GUI session, never only over SSH.
- A loaded LaunchAgent is not proof of a working desktop. The probe is.
- A Keychain item on the lead is not on the worker. For production secure references, check
  that the item is readable in the GUI session.

## Screenshots are black, show the lock screen, or nothing happens

The screen must **never sleep or lock**. Check the `Sleep disabled`, `Screen lock off` and
`Screen saver off` rows. If the display went to sleep, wake it with Screen Sharing.

## Screenshots show the ChatGPT window instead of the site

The runtime instructions tell the worker to bring the browser to the front before each
screenshot. Repeat that in the brief for important checks. Always look at the evidence: a
screenshot of the wrong window proves nothing, in either direction.

## The Chrome plugin path does not work in jobs

The Chrome-extension browser backend (`chrome@openai-bundled`) can work inside the ChatGPT app
but **does not work under headless `codex exec`**: it reports the browser is not available.
Jobs use Computer Use, which does work under `codex exec`. Test the Chrome backend again after
updates if you want it, but do not depend on it.

## A different model ran than I asked for

Model ids change over time. The runner picks the model for every job from `codex debug models`,
in the catalog's own order. With no model pattern set it uses the first listed model. With a
pattern (a shell-style glob such as `name-*`) it uses the first listed model that matches. Set the
pattern with the `QA_WORKER_MODEL` environment variable, or in the file `<base>/model-pattern`
(for example `~/qa-worker/model-pattern`; the first non-blank line is used). The variable wins over
the file. The LaunchAgent does not set the variable, so use the file for the runner. A `MODEL=`
header in a brief is logged and ignored: the operator chooses the model, not the brief. If no
listed model matches, for example because the pattern is wrong or Codex is not signed in, the
runner fails closed. It does not run the job. It finishes it as `blocked` with the blocker "no
listed model matched (pattern: ...)" and logs it. The `Model for jobs` row is FAIL until this is
fixed.

## qa-submit exit codes

- `2` and "not configured": run `lead/setup-lead.sh --apply`.
- `2` and "transfer failed" / "ssh failed": check the network, Remote Login and the key with
  `ssh -o BatchMode=yes <worker-user>@<worker-host> true`.
- `2` and "NOT SUBMITTED": the worker stayed busy with another queued or running job. Nothing
  was sent. Non-sensitive briefs are kept; ACCESS briefs are purged. One screen, one job.
- `3` and "outcome unknown": the job ran past the deadline. It is still running or finished
  late. Look at `~/qa-worker/done/<job-id>/` on the worker. Do not resubmit blindly.
- `4` and "results were not collected": the job ran and finished, but copying `done/<job-id>/`
  back failed. Copy it with the printed `scp -r` command. Do not resubmit.
- `1`: the job finished but `result.json` is missing or invalid. Read `output.txt` in the
  collected folder and the non-secret blocker in `result.json`. Raw executor stdout/stderr
  are discarded, so there is no new full transcript to inspect.

## Every job finishes "blocked": unsandboxed execution has not been acknowledged

The runner starts no job unless `<base>/unsandboxed-ack` exists (see "Before you set this up" in
the README). The blocker names the fix and the `Unsandboxed run acknowledged` row is FAIL. Read
the explanation, then run `worker/install.sh --apply --accept-unsandboxed` on the worker. The
marker is a one-line text file with the date and runner version; it is not created by anything
else.

## The runner takes no jobs ("paused" in runner.log)

`~/qa-worker/pause` exists. `install.sh --apply` creates it while it upgrades and removes it when
it finishes or aborts. If a crash left it behind, delete it.

A job runs while holding a kernel lock (`flock`) on `~/qa-worker/.active.lock`. macOS releases the
lock as soon as the job process exits or is killed, so a stale lock cannot exist. Do not delete
the file. To see whether a job holds it, run `~/qa-worker/runner.sh --lock-state`. It prints
`free`, or `busy` and the contents of `.active.info`, which is for display only.

## Where things are on the worker

```
~/qa-worker/runner.sh, lockrun.py, jobrun.py  installed runner, lock and private executor
~/qa-worker/runtime-instructions.md      prepended to every job; edit freely
~/qa-worker/model-pattern              optional model pattern (you create it)
~/qa-worker/unsandboxed-ack            acknowledgement written by --accept-unsandboxed
~/qa-worker/jobs/  done/                queue and retained sanitized evidence
~/qa-worker/tmp/active-*                private execution folders; never archive
~/qa-worker/logs/runner.log              runner health/pause lines (no brief text)
~/qa-worker/logs/gui-selfcheck.json      the GUI self-check
~/qa-worker/logs/transcripts/            no raw transcripts are written
~/Library/LaunchAgents/local.qa-worker.runner.plist
```

Restart the runner: `launchctl kickstart -k gui/$(id -u)/local.qa-worker.runner`.

## Credential cleanup and interruption

Only one leading ACCESS JSON header may declare temporary non-production username/password
values. Production declarations accept only a secure reference. Never put credentials in
free prose, headers other than ACCESS, filenames, docs, reports or memory. Declared values
are matched literally in retained JSON text and plaintext screenshot bytes, without guessing
which arbitrary words might be credentials. Screenshot pixels cannot be validated by this
scan: the worker must never capture login forms or visible credentials.

The queue entry is unlinked before validation/execution, and the prompt stays in memory/stdin.
Executor stdout/stderr are discarded. Only sanitized result contract fields, explicitly
referenced local PNG evidence, a fixed output summary and a non-secret receipt survive.
Arbitrary job copies, native log/state files and other outputs stay in the private folder and
are purged before `.done`; invalid and duplicate briefs are never moved into `rejected/`.
Codex must advertise `--ephemeral` or the job is blocked before prompt delivery. The runner
also disables native history and directs native logs/state into the private folder. Official
CLI contracts: [execution flags](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
and [history/log/state configuration](https://learn.chatgpt.com/docs/config-file/config-reference).
These options are exercised only against stub executors here; confirm the installed Codex
runtime's history, log and state persistence on your own worker before sending credentials.

TERM, INT and HUP cancel the job, kill/reap its executor process group, purge private files and
then write a blocked result. SIGKILL and power loss cannot run cleanup: after surviving
executors stop, the next locked queue poll removes only owned `tmp/active-*` folders with the
matching runner marker. New private folders have a mode-600 sibling `active-*.owner.json`
marker recording the owned root inode. The runner binds the opened or retained root
descriptor to that proof and checks the current root identity before root permission changes
or traversal. Its non-inheritable creation descriptor supports same-run mode-`000` root
cleanup using descriptor-based permission changes. Unmarked folders, a root replaced at the
checked binding boundary and symlink targets are preserved.

After a restart, a mode-`000` root cannot be reopened safely without that retained descriptor
on macOS. Cleanup leaves its proof and data intact, emits fixed non-secret failure text and
blocks new jobs until safe owned recovery is possible; it never uses pathname root chmod.
If cleanup remains impossible, exit 75 emits only `Private cleanup pending; worker recovery
required`, keeps the marker and withholds `.done`. The next safe locked recovery can retry
when the proven tree is safely accessible; it never synthesises a completed result. Never
remove a retained marker or archive its tree as a substitute for verified cleanup. No prompt,
transcript, staged transfer or private execution folder is ever archived. Residue from
earlier runs is not deleted automatically; handle it in a worker handover or erase, without
copying credential-bearing files.

Installer `--apply` is tested only against stubs, and the physical installation, GUI, native
history/log/SQLite persistence and screenshot-pixel checks are not covered by the tests. Do not
treat the tests as credential-dispatch readiness.

The lead reads owned input as bytes, detects ACCESS before UTF-8 decoding, and consumes the
exact sensitive brief before config/access/busy/transfer handling. Brief bytes travel on SSH
stdin to a receiver that opens owned non-writable base/queue descriptors without following
symlinks. It checks exact payload size, creates an exclusive mode-600 stage, rechecks directory
identity, publishes with an atomic non-overwriting link and unlinks the stage in `finally`.
The worker recognises only the matching same-inode publication companion and purges both
links; unrelated hardlinks are rejected. No named local upload copy exists. Queue path
substitution and truncated transfers are covered by synthetic fixtures. Native transport
and persistence checks on a real worker are not covered by the tests.

Retained results are validated and projected to the typed contract at both levels: extra
observation fields cannot retain transcripts, and malformed results become a fixed blocked
response. Literal redaction includes raw and standard JSON-escaped declared credential forms.
This is not a claim to detect arbitrary transformed/encoded secrets or text rendered in
screenshots; those remain forbidden by the executor contract.

A transport outage may leave the submitted outcome unknown; never retry or archive a queued
brief/transfer stage blindly. Confirm the specific job once access is restored. A submission
wait timeout does not cancel or replay the worker job. SIGKILL/power loss still cannot run a
cleanup handler; recovery and handover limits above apply.
