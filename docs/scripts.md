# The scripts

There are two sets: check scripts for the site audit, and report scripts that every QA job
can use.

## Report scripts

In `skills/qa-standards/scripts/`. They exist because a report is only useful if its
screenshots travel with it.

| Script | What it does |
|---|---|
| `report_check.py` | Fails a report that mentions a screenshot without embedding it, embeds a file that is missing, sits outside the report's folder or is not a sound image file (a PNG's checksums, palette and decompressed pixel stream are checked against its header; JPEG, GIF and WebP are checked structurally only; neither proves the picture looks right), or has a finding whose evidence image is not shown in the report |
| `report_export.py` | Writes one self-contained HTML file with every image inside it, prints it to PDF with Chrome, and verifies the PDF contains the images. Before printing, Chrome loads every image and the export stops if one will not load. Raw HTML in the report is neutralised and the export loads nothing from the network |

```bash
python3 -m venv .venv
.venv/bin/pip install -r skills/qa-standards/scripts/requirements.txt
.venv/bin/python skills/qa-standards/scripts/report_check.py  RUN/report.md --findings RUN/findings.json
.venv/bin/python skills/qa-standards/scripts/report_export.py RUN/report.md --html RUN/report.html --pdf RUN/report.pdf
```

Both need the `markdown` package (the first two lines install it), and `report_export.py`
needs Chrome for `--pdf`.

## Check scripts

The site audit includes six scripts in `skills/qa-site-audit/scripts/`. An agent using the
skill runs them for you, but each one also works on its own from a terminal. All are
read-only: they load pages and write JSON.

| Script | What it finds |
|---|---|
| `viewport_overflow.js` | Sideways scrolling at 320, 375, 768, 1024 and 1440 px and the elements that cause it; a fixed header covering the heading; text that differs between mobile and desktop |
| `consent_capture.js` | Cookies, storage and network destinations before any consent choice, after Accept and after Reject; whether Reject is honoured |
| `dev_artefacts.js` | Debug and test markup left in the page, console errors, failed requests, exposed source maps |
| `similarity.py` | Pages in the same group that are near-duplicates of each other |
| `copy_freshness.py` | Stale years and quarters, placeholder text, repeated filler, inconsistent names and numbers across pages |
| `findings.py` | Not a check: validates a run's `findings.json`, suggests scores per area and compares a run with the previous one |

## Setup

```bash
# Python scripts
python3 -m venv .venv
.venv/bin/pip install -r skills/qa-site-audit/scripts/requirements.txt -r skills/qa-standards/scripts/requirements.txt

# Browser scripts: puppeteer-core in a folder of your choice, outside the skill folder
mkdir -p ~/qa-tools && (cd ~/qa-tools && npm install puppeteer-core)
export NODE_PATH=~/qa-tools/node_modules
export CHROME_PATH="/path/to/chrome"     # only if Chrome is not in its standard place
```

Do not run `npm install` inside the skill folder. Its `package.json` only records the
dependency.

## Try them on the demo site

The [demo site](../demo-site/README.md) is a made-up business site with faults planted on
purpose. Its README lists each fault and which script finds it.

```bash
python3 demo-site/serve.py --port 8765 &
mkdir -p /tmp/qa-demo && cd /tmp/qa-demo
S=/path/to/qa-toolkit/skills/qa-site-audit/scripts

node $S/viewport_overflow.js http://127.0.0.1:8765/ --out evidence/overflow.json
node $S/consent_capture.js   http://127.0.0.1:8765/ --out evidence/consent.json
node $S/dev_artefacts.js     http://127.0.0.1:8765/ --out evidence/artefacts.json
```

Every script has `--help`, which lists its options and works before any dependency is
installed.

## Conventions they all share

- **Input**: a file with one URL per line, or a comma-separated list. http and https only.
- **Output**: JSON, written after every URL, so an interrupted run keeps what it finished.
  The default location is `evidence/` in the current folder.
- **Exit codes**: `0` every URL done, `1` some URLs failed (they are listed in the output),
  `2` a usage or dependency error.
- **Politeness**: one page at a time, a delay between loads, a tagged user agent. The
  scripts' own requests are GET only. A page loaded in the browser still makes its own
  requests, as it would for any visitor.
- **Staying on the site**: a page that redirects or navigates to a host you did not list is
  blocked and reported as a failed URL. The Python scripts refuse such redirects too.
- **Privacy**: URLs are stored without query strings; personal email addresses and
  token-like strings are redacted; cookie values are never stored, only names.
- **Caches are raw**: a `--cache` folder holds fetched pages and exact URLs. It is working
  data, not evidence; do not share it.
- **Emulated is not physical**: mobile widths are emulated in a desktop browser. Results
  say so.

## Reading the output

Script output is evidence, not a list of defects. A person or the QA lead agent reviews each
hit before it becomes a finding: some are false positives by nature, such as a decorative
band that looks like a missing image. The skill's `references/` folder explains how to read
each script's output and how to rate what it finds.
