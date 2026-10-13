# Changelog

All notable changes to this project are recorded here. Versions follow
[Semantic Versioning](https://semver.org/): a change that alters what an installed skill
tells an agent to do is at least a minor version.

## 1.0.0 - unreleased

First public version.

- Three skills: `qa-standards`, `qa-site-audit` and `qa-release`.
- Three editions: dedicated QA Mac, hosted QA bot and local.
- Headless check scripts for viewport overflow, consent capture, leftover dev artefacts,
  duplicate content, copy freshness, and findings scoring and regression.
- Release-QA run helper with a coverage matrix and verdict validation.
- Report scripts: `report_check.py` fails a report whose screenshots are not embedded, and
  `report_export.py` writes a self-contained HTML file or a PDF and verifies the images are
  inside it.
- The dedicated QA Mac edition includes the worker setup and the `qa-submit` command.
- The worker installer needs `--accept-unsandboxed` before it sets anything up, and the
  runner will not start a job without that record.
- `copy_freshness.py --timezone <IANA name>` checks out-of-season timezone labels for any
  zone. The check does not run unless asked for.
- `install.sh`, a demo site with planted faults, and offline tests for every script.
