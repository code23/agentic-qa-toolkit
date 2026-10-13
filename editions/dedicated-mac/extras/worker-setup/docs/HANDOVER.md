# When a worker Mac changes hands

**Erase it, then set it up fresh. Do not just sign out.**

## What the previous owner left on it

- **Their ChatGPT / Codex session.** App tokens live in the Keychain and in `~/.codex/`.
  Signing out of the app does not reliably remove every cached credential, plugin config or
  local history.
- **Browser state.** Cookies, saved passwords, signed-in sessions and history for every site
  they tested, including staging admin sessions.
- **Test credentials.** Keychain items used as secure references for production QA. The
  runner creates no raw transcript and purges private job files.
- **QA evidence.** `~/qa-worker/done/` holds screenshots and results of past jobs. These can show
  unreleased products, client data or personal data. Never archive or copy queued briefs,
  transfer stages or private `tmp/active-*` folders that may contain credentials.
- **Access for their lead Mac.** `~/.ssh/authorized_keys` still lets the previous lead log in
  and submit jobs.
- **System-level traces.** The stored auto-login password, privacy (TCC) grants, Remote Login
  settings, and possibly an Apple Account with Find My and Activation Lock.

Sign-out cleans some of this. It is easy to miss a Keychain item, a browser profile, an
authorised key or an evidence folder, and you cannot easily prove nothing was missed. An erase
removes all of it at once and leaves a Mac that is known clean.

## Previous owner: before handing over

1. Collect any evidence you must keep (`~/qa-worker/done/`) according to your retention rules.
2. Remove the worker from your lead:
   - delete `~/.config/qa-worker/config.json`, or point it at the new worker;
   - `ssh-keygen -R <worker-host>` to remove its host key from known_hosts.
3. Revoke anything that was only for this Mac: test accounts, or Keychain-referenced production
   credentials that should not outlive it. Rotate any credential that ever appeared in a brief.
4. Sign out of the Apple Account (System Settings > your name > Sign Out). This turns off Find
   My and Activation Lock, so the next owner can activate the Mac.

## Erase

System Settings > General > Transfer or Reset > **Erase All Content and Settings**. This needs
an admin password, and the Apple Account password if Find My is on. On Macs that do not offer
it, reinstall macOS from Recovery after erasing the disk.

## New owner

Follow [WORKER-SETUP.md](WORKER-SETUP.md) from the Setup Assistant. Use **your own** ChatGPT
account. Never take over the previous owner's login. Authorise **your** lead key, then run the
probe.
