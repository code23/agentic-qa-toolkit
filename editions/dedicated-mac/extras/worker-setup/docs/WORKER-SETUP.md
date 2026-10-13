# Worker setup: a fresh Mac, step by step

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
  about, and erase it when it changes hands (see [HANDOVER](HANDOVER.md)).

## What you need

The worker is a Mac that stays on, stays logged in and stays awake, with the screen unlocked.
Computer Use drives that real screen. Plan for the Mac to do nothing else.

You need: the Mac, an admin password for it, your own ChatGPT account (a plan that includes
Codex and Computer Use), and the network name the lead will use to reach it
(for example `qa-worker.local`).

## 1. macOS Setup Assistant

1. Power on and go through the Setup Assistant. The first account you create is the **admin**
   account (for example `qa-admin`). Use it only for admin tasks.
2. You can skip signing in with an Apple Account. If you do sign in, use an account you are happy
   to tie to this Mac. Sign it out before the Mac changes hands (see [HANDOVER](HANDOVER.md)).
3. **FileVault: turn it off** (or skip it). macOS disables automatic login while FileVault is
   on. After a power cut the worker would sit at the unlock screen and no QA would run. Accept
   that trade-off knowingly: keep test data and secrets off this Mac.
4. Finish setup and install macOS updates now: System Settings > General > Software Update.

## 2. Create the dedicated worker user

From the admin account: System Settings > Users & Groups > Add User.

- Type: **Standard** (not Administrator). Name it for the role, for example `qa-worker`.
- Set a password and keep it somewhere safe. You need it for auto-login and SSH key setup.

## 3. Auto-login, no sleep, no lock (admin account)

- System Settings > Users & Groups > **Automatically log in as: the worker user**.
- In Terminal, from the admin account:
  ```bash
  sudo pmset -a sleep 0 displaysleep 0
  ```
  (`install.sh --apply` offers this too, but the worker user is not an admin.)
- System Settings > General > Sharing > **Remote Login: On**, "Allow access for: Only these
  users", then add the worker user.

Log out of the admin account and log in as the worker user. From here on, work as the worker
user, at the screen or over Screen Sharing.

## 4. As the worker user

1. System Settings > Lock Screen:
   - "Start Screen Saver when inactive": **Never**
   - "Turn display off when inactive": **Never**
   - "Require password after screen saver begins or display is turned off": **Never**
     (macOS asks for the user's password to change this).
2. Install the **ChatGPT desktop app** (the one that includes Codex) into `/Applications`.
   Open it.
3. **Sign in with your own account.** Never a shared or borrowed login. Each operator's worker
   uses that operator's account.
4. Install Git if needed: run `xcode-select --install`. This also provides `python3`.
5. Clone this repo:
   ```bash
   git clone <this-repo> ~/qa-worker-setup
   cd ~/qa-worker-setup/editions/dedicated-mac/extras/worker-setup
   ```

## 5. Check, then apply

```bash
worker/install.sh            # read-only: one row per requirement and the exact fix
worker/install.sh --apply --accept-unsandboxed   # install runner + LaunchAgent, plugin, screen saver; then re-check
```

`--apply` needs `--accept-unsandboxed` the first time (see the top of this page); without it nothing is changed. It is safe to re-run. It never stops a runner in the middle of a job. It first creates
`~/qa-worker/pause`, which the runner checks before it takes a job. It then waits, by
default up to 10 minutes (`QA_WORKER_APPLY_WAIT`), until no job is active. If a job is still running
after that, it removes the marker and stops with a message. Otherwise it does the following:

- installs `~/qa-worker/runner.sh`, `runtime-instructions.md` and the LaunchAgent
  `local.qa-worker.runner`, then loads it;
- adds the Computer Use plugin if missing;
- sets the screen saver to never start, and offers `sudo pmset` if sleep is still on;
- removes the pause marker once the new runner is loaded;
- asks the runner for a fresh **GUI self-check** (see below).

It never overwrites a `runtime-instructions.md` you have edited. A newer template is saved
beside it as `runtime-instructions.new.md` for you to merge.

## 6. Manual grants

`--apply` ends with a numbered list. The ones no script can do:

1. System Settings > Privacy & Security > **Accessibility** and **Screen & System Audio
   Recording**: allow **ChatGPT** and its Computer Use helper. The helper appears in the list
   after the first Computer Use run, so you may need to come back after the probe.
2. If macOS asks whether `bash` may record the screen (from the runner's self-check), either
   answer is fine. Computer Use uses ChatGPT's own permission.
3. Authorise the lead's SSH key. On the lead, `lead/setup-lead.sh` prints the exact
   `ssh-copy-id` command. It asks once for the worker user's password.

## 7. The GUI self-check

SSH sessions and the desktop session see different Keychain and privacy (TCC) state. A check
run over SSH can therefore pass while the desktop fails, or the other way round. The runner
runs inside the desktop session. When it starts, every 6 hours, and whenever `--apply` asks, it
writes `~/qa-worker/logs/gui-selfcheck.json`. The file records whether the screen could be
captured, which Codex CLI it found, whether Codex is signed in, whether Computer Use is enabled,
the model jobs will run (and the model pattern in force), and whether the login Keychain is unlocked. It never contains secrets.
`install.sh` reads it for the `GUI:` rows.

## 8. Probe from the lead

From the lead run `lead/qa-submit --probe`. It must print `PROBE OK`. Then open the screenshot
it names and confirm it shows the browser and not another window. Until the probe passes, the
worker is not ready, whatever the table says.
