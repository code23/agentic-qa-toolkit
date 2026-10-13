# After any update

App and OS updates are the most common reason a working worker stops working. After **any**
macOS update or ChatGPT app update on the worker:

1. Make sure the worker is logged in at its screen. A macOS update restarts the Mac, and without
   auto-login it waits at the login window.
2. On the worker, in Terminal in the GUI session:
   ```bash
   cd ~/qa-worker-setup && git pull
   cd editions/dedicated-mac/extras/worker-setup
   worker/install.sh            # read the table
   worker/install.sh --apply    # if anything is FAIL
   ```
   A worker installed before the acknowledgement existed needs the flag once:
   `worker/install.sh --apply --accept-unsandboxed` (read "Before you set this up" in the README
   first). Until it is recorded, the `Unsandboxed run acknowledged` row is FAIL and the runner
   blocks every job.
   Watch these rows in particular:
   - `Computer Use plugin`: updates have dropped it. `--apply` re-adds it. Reopen ChatGPT
     afterwards.
   - `Bundled Codex CLI`: updates have moved it. The runner finds it again by bundle id. This row
     confirms it.
   - `Model for jobs`: shows which model the next job will run and the model pattern in force.
   - `GUI: Codex + Computer Use` and `GUI: Keychain unlocked`: the desktop session's view after
     the update.
   - macOS updates can reset privacy grants. If the probe fails, recheck Accessibility and
     Screen Recording for ChatGPT.
3. From the lead: `lead/qa-submit --probe`, and look at the screenshot.

Do not send real QA jobs until the probe passes.

After pulling a new version of this repo, `install.sh --apply` upgrades the installed runner.
The `Runner installed` row compares versions. It reloads the LaunchAgent only when something
changed, and never while a job is running.
