# Instructions for AI agents

Read this if a person asked you to install this toolkit, or to work on this repository.

## If you were asked to install the toolkit

Follow these steps in order. Do not skip the dry run.

1. **Edition.** Use the one the person named. If they did not say, ask one question:
   "Which setup: Local (I test on this machine), Hosted QA bot, or Dedicated QA Mac?"
   If they do not know, use `local`. The folder names are `local`, `hosted-bot` and
   `dedicated-mac`.
2. **Skills folder.** The skills go where the QA lead runs:
   - `local` and `dedicated-mac`: your own skills folder, the directory where you load
     folders that contain a `SKILL.md`.
   - `hosted-bot`: the **bot's** skills folder on the bot's machine, not yours. If you are
     not running on that machine, you cannot install it from here: say so, give the person
     the two commands to run there, and treat the bot install as outstanding. On the
     developer's machine the only thing to set up is the `qa-send` command (step 7).

   If you cannot determine the folder with certainty, ask. Do not guess, and do not install
   into a project repository unless the person asks for that.
3. **Dry run.** From the repository root run:
   `./install.sh --edition <edition> --target <skills folder>`
   Show the person the output. It lists what will be installed and anything already there.
4. **Existing skills.** If the output says a `qa-*` skill EXISTS, stop and ask whether to
   replace it. Only with a yes, add `--replace`; it moves the old folder aside to
   `<name>.bak-<timestamp>` and never deletes it.
5. **Apply.** After the person agrees, run the same command with `--apply`.
6. **Verify.** Confirm these exist in the skills folder, and say so:
   `qa-standards/SKILL.md`, `qa-standards/environment.md`, `qa-site-audit/SKILL.md`,
   `qa-release/SKILL.md`. Read `qa-standards/environment.md`: it tells you how this edition
   works and what it may not do.
7. **Remaining setup.** Read `editions/<edition>/README.md` and tell the person what is left
   for them: for `hosted-bot`, the webhook and its key; for `dedicated-mac`, the worker Mac.
   Do not do those steps unless asked.
8. **Offer branding.** Ask once: "Do you want exported reports to carry your own logo,
   colours and fonts?" If no, reports use the neutral look and nothing more is needed. If
   yes, follow `docs/branding.md` with them: copy `skills/qa-standards/brand-example/` to a
   folder of their choice outside the toolkit, help them fill in `brand.json` and replace the
   logo, run `brand_check.py` on it, and tell them the line to add to their shell profile
   (`export QA_BRAND=/path/to/their-brand`). Do not edit their shell profile yourself unless
   they ask.
9. **Finish** by telling the person how to start: "Ask me to use qa-standards to QA a flow
   on a URL."

Do not, as part of installing:

- install system packages, browsers, Node or Python packages without asking first. The check
  scripts are optional; list what they need (see `docs/scripts.md`) and let the person choose;
- run `npm install` inside any `skills/` folder;
- create, read or fill in any key, token or password. The person fills in secrets themselves;
- change SSH, login items or system settings. The worker Mac installer changes nothing
  unless it is run with `--apply`, and that is the person's decision on that Mac;
- pass `--accept-unsandboxed` to the worker Mac installer. That flag is the person's own
  acknowledgement that the worker runs briefs with the agent's approvals and sandbox
  switched off. Show them the explanation the installer prints and let them type it;
- run a QA job. Installing is not a request to test anything.

## If you are using the installed skills

Start with `qa-standards` and its `environment.md`. The safety rules at the top of each
skill win over everything else: read-only by default, test accounts only, stop at payment
forms, phone codes, identity checks and CAPTCHAs, and file or send nothing without approval.
Only test sites the person owns or has permission to test.

## If you are changing this repository

- Read `docs/maintaining.md` first.
- Method text goes in `skills/`. Text that is true for one setup only goes in that edition's
  `environment.md`.
- Every script change needs a test. A new check also plants its fault in `demo-site/` and
  adds a row to the fault table in `demo-site/README.md`.
- Use made-up content only: no real sites, people, customers or run output.
- Run `tools/check.sh` before you say the work is done, and report each line it prints.
  NOT RUN is not a pass.
- Keep the scripts polite and read-only: one page at a time, their own requests GET only,
  no typing into or submitting forms, no crawling, and no navigation or redirect followed to
  a host that was not in the input. A page's own sub-requests are recorded, never blocked.
