# findings.json and regression mode

Save `findings.json` in the run folder every run. `python3 <skill-dir>/scripts/findings.py
template` prints a skeleton: every dimension starts `not-executed` with no checks, `checks_run`
and `findings` start empty, and filled-in examples sit under `_examples` (ignored by
`check`, `score` and `diff`; this page shows the same shapes).

## Schema

```json
{
  "run_id": "<host-slug>-<YYYY-MM-DD>[-<n>]",
  "target": "https://example.com",
  "date": "YYYY-MM-DD",
  "verdict": "PASS | PASS WITH CONDITIONS | FAIL | INCONCLUSIVE",
  "scores": {"ux": 7.0},
  "coverage": {
    "ux": {"status": "executed", "checks": ["executor walk: home, service, contact"], "note": ""},
    "accessibility": {"status": "partial", "checks": ["axe:home,service"], "note": "no keyboard walk on mobile"},
    "cms-code": {"status": "not-in-scope", "checks": [], "note": "not in the charter"}
  },
  "checks_run": [
    {"rule": "axe:*", "template": "home", "url": "https://example.com/"},
    {"rule": "overflow-x:*", "template": "*"},
    {"rule": "stale-quarter", "template": "pricing"}
  ],
  "tooling": {"lighthouse": "12.x", "lighthouse_runs": 3, "axe-core": "4.x"},
  "findings": [{
    "id": "XX-01",
    "title": "Neutral, specific title",
    "severity": "S1|S2|S3|S4",
    "priority": "P1-P4",
    "verification": "independently-reproduced|evidence-reviewed|provisional",
    "label": "DET|JUDG|DET+JUDG",
    "dimension": "qa-functional|ux|accessibility|performance|seo-ai|security-privacy|content|cms-code",
    "template": "service-location",
    "url": "https://example.com/representative/path/",
    "rule": "stable-check-key",
    "scope": "template|page|sitewide",
    "status": "open|fixed|not-retested|wont-fix|accepted-risk",
    "instances": 1,
    "evidence": ["screenshots/lead-01.png"],
    "fingerprint": null
  }],
  "improvements": [{"id": "IMP-01", "title": "Recommendation", "dimension": "ux", "rationale": "why"}]
}
```

- **coverage** (required): one entry for **every** dimension. `status` is `executed`,
  `partial`, `blocked`, `not-in-scope` or `not-executed`. `executed` and `partial` need a
  non-empty `checks` list (what actually ran); `partial` also needs a `note` saying what wasn't
  covered. `score` never scores an executed/partial dimension with no checks. These map onto the
  qa-standards coverage statuses (`not-in-scope` = not applicable / out of charter).
- **checks_run** (required): every check that actually ran this time, as `rule` + `template`
  (+ `url`). `rule` may end in `*` as a prefix wildcard (`axe:*` = every axe rule);
  `template` may be `*` (the check ran on every template). Add `url` when the check ran on
  specific pages (one entry per page): only an entry with the same URL path re-tests a
  page-scoped finding. Record a check here only when it completed; a blocked or failed script
  run is not "run".
- **scope** (optional, default `template`): `template` = one root cause in that template
  (the representative `url` is evidence only); `page` = this URL only (`url` required);
  `sitewide` = every page (use an `instances` count).
- **improvements**: improvement opportunities (no S-rating, qa-standards §2). `IMP` is
  still accepted as a finding severity for older files, but new runs use this array.
- **tooling**: tool versions and run counts that affect comparability (Lighthouse version and
  median-of-N).
- `verification` has no `n/a`: every finding is one of the three standards statuses.

`findings.py check FILE` validates all of this: run fields (`target` an http(s) URL, `date`
YYYY-MM-DD), required finding fields including `rule` as non-empty strings, enums (severity,
verification, label, dimension, status, scope), `instances` a whole number ≥ 1, `evidence` a
list of strings, unique IDs, unique fingerprints, coverage for every dimension, and
checks_run items (string `rule`/`template`, optional http(s) `url`). Only when the file is
valid does it (re)compute every fingerprint and write the file back; an invalid file (or
unreadable JSON) is left untouched, the errors are listed and the command exits 1, never with
a traceback. `score` and `diff` run the same type checks (older files may lack the newer
required fields) and exit 1 the same way.

## Stable IDs and fingerprints

- `fingerprint = sha1(normalised rule | normalised template [| url path])[:12]`. The URL path
  is included **only for `scope: page`**. Template-scoped findings (the default) match across
  runs even when the representative URL changes; `scope: sitewide` uses the template
  `sitewide`. `dimension` is not in the hash, so re-classifying a finding (seo-ai vs content)
  does not break regression.
- Fingerprints are always recomputed; `check` warns when one changes (someone edited
  `rule`, `template`, `scope` or, for page scope, `url`). Two findings with the same
  fingerprint fail `check`: merge them (one root cause per template, with `instances`), give
  them distinct rules, or mark them `scope: page`.
- Older files without `scope` are read as `template`. Their fingerprints change under this
  formula (the path is no longer in it), but `diff` recomputes both sides, so comparisons
  still line up; several old findings that now share one identity are compared as one (noted
  in regression.md).
- `rule` is required and must stay stable between runs. Naming:
  - axe rule ID prefixed `axe:` (`axe:color-contrast`);
  - script flag names (`stale-quarter`, `copyright-year`, `overflow-x:1024`,
    `dev-artefact:debug`, `source-map-exposed`);
  - consent: `consent:pre-tracking:<vendor>`, `consent:reject-ignored:<vendor>`,
    `consent:policy-missing:<vendor>`;
  - nav and content: `nav-missing-item:<label>`, `dead-end`, `offer-parity:<offer>`;
  - otherwise a short kebab-case key you reuse.
  Titles may be reworded freely.
- Sitewide issues (contrast on every page) use `scope: "sitewide"` (or the older
  `template: "sitewide"`) and an `instances` count.
- The display IDs (`XX-01`) may change between runs. The fingerprint is what matches.

## Regression (`findings.py diff`)

- `diff FILE` finds the newest earlier run under `$QA_RUNS/` (by date, then the
  `-<n>` same-day suffix) with a findings.json for the same host. To compare against a
  specific run, use `--previous OLD/findings.json` (it must be for the same host).
- The output is `regression.md` (use `--out`) plus `regression.json` next to findings.json.
  For each finding that was open last time:
  - **Still open**: open in both runs, with the severity change shown.
  - **Fixed**: absent now and this run's `checks_run` has an entry whose `rule` matches
    (wildcards allowed) and whose `template` matches (or is `*`); for a `sitewide` finding the
    template must be `sitewide` or `*`; for a `page` finding the entry must **also** have a
    `url` with the same path (an entry without `url` does not cover page-scoped findings).
    Or the lead set `status: fixed` on it this run.
  - **Not re-tested** (`not_retested`): absent now and no such check ran this time (for
    example the rule ran on another page than the page-scoped finding). Its status is
    unknown; it is not "fixed".
  - **Won't fix** / **Accepted risk**: carried by the current run's `status`.
  - **New**: open now, not in the previous run.
- A run with no `checks_run` list can't call anything fixed: everything missing is "not
  re-tested", with a warning.
- With no previous run it reports "baseline run, nothing to compare" and still writes
  `regression.json` with `"status": "baseline"` and empty lists.
