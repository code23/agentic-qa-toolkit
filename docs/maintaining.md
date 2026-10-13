# Maintaining and releasing

## Layout

```
skills/<skill>/              SKILL.md, references/, scripts/, assets/  (same in every edition)
                             qa-standards/scripts: report check and export; qa-site-audit/scripts: site checks
editions/<edition>/          README.md, environment.md, extras/
demo-site/                   made-up site with planted faults; used by tests and examples
tests/python/                tests for the Python scripts
tests/node/                  tests for the headless-browser scripts
tests/worker_setup/          tests for the dedicated-Mac worker setup
tests/install/, tests/build/ tests for install.sh and the package build
tools/build.py               stages skills + one edition, scans it, writes dist/<name>.zip
tools/check_links.py         checks relative links in every Markdown file
tools/check.sh               runs all of the above and prints one line per check
```

## Rules for changing it

- Method text lives in `skills/` only. A sentence that is true for one setup belongs in that
  edition's `environment.md`.
- No material from real runs: no reports, screenshots, numbers or anecdotes from a real
  site. Examples are made up and use the demo site or example.com.
- Every script change comes with a test. A new check also plants its fault in the demo site
  and adds a row to the demo site's fault table.
- The scripts stay polite: one page at a time, a delay between loads, GET only, no crawling.
- Changing what an installed skill tells an agent to do is at least a minor version.

## Checks

```bash
python3 -m venv .venv && .venv/bin/pip install -r skills/qa-site-audit/scripts/requirements.txt -r skills/qa-standards/scripts/requirements.txt
(cd tests/node && npm ci)
tools/check.sh
```

Every check prints PASS, FAIL, NOT RUN or N/A. N/A means the check does not apply on this
operating system (the worker setup tests run on macOS only). NOT RUN means a dependency was missing, and it is
not a pass.

## The package scan

`tools/build.py` refuses to build a package that contains a machine-specific path, a
real-looking email address, a secret pattern, a run artefact or a mis-named skill.

Maintainers who also need to keep private words out (for example the names of their own
customers or internal systems) can list them, one per line, in a file kept **outside this
repository** and point `QA_TOOLKIT_DENYLIST` at it. Matching ignores case and treats
spaces, hyphens, underscores and line breaks alike. A leading `*` refuses the word even
inside a longer word. Run the scan with that variable set before every push; the list
itself must never be committed here.

## Releasing

1. Update `CHANGELOG.md` and `VERSION`.
2. Run `tools/check.sh`; everything must pass.
3. Tag the commit `v<version>` and push the tag.
4. The release workflow re-runs the checks, builds one zip per edition, and publishes a
   release with the zips and a `SHA256SUMS` file. It fails if the tag and `VERSION` differ.
