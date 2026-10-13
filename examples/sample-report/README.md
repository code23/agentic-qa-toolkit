# Sample report

A worked example of what the site audit produces, so you can see the shape before you
install anything.

- **The site is made up.** It is the [demo site](../../demo-site/README.md) in this
  repository, which has faults planted on purpose.
- **The evidence is real script output.** The files in `evidence/` were written by the five
  check scripts run against the demo site on a local server. `findings.json` passes
  `findings.py check`, and the scores in the summary are what `findings.py score` printed.
- **It shows the headless half of an audit only.** No browser walk, accessibility scan or
  performance run was done, and the report says so in its coverage table.
- **Screenshots sit under the findings they support**, which is the rule for every report.
  Here they are the captures the viewport script saves; a full audit adds the walk's own.

| File | What it is |
|---|---|
| [summary.md](summary.md) | The one-page, plain-language version |
| [report.md](report.md) | The full report |
| `findings.json` | The same findings in machine-readable form, used to compare runs |
| `evidence/` | Raw output from each script |
| `screenshots/` | The images embedded in the report |

To reproduce the evidence, follow "Try them on the demo site" in
[docs/scripts.md](../../docs/scripts.md) and pass `--today 2026-07-15 --timezone Europe/London` to
`copy_freshness.py` and `--mask "Brindlemere,Oakhaven"` to `similarity.py`.
