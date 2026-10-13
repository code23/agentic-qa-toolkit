# How a run works

## Two roles

- **QA lead**: plans the run, reviews every piece of evidence, rates each finding and writes
  the verdict.
- **Executor**: drives the browser and reports what it saw. It never rates a finding and
  never writes the verdict.

Keeping them apart is the point. An observation ("the heading is not visible") is recorded
before anyone decides what it means. Which agent or machine plays each role depends on your
[edition](choosing-an-edition.md).

## The steps

1. **Charter.** Six lines written before anything is tested: goal, what is in scope, what is
   out, the exact environment, the top risks and how wrong behaviour will be recognised.
   No charter, no run.
2. **Readiness.** The lead confirms the build, the test account and the starting data, so
   the executor is not left guessing.
3. **Brief.** One flow per job. It lists the permitted actions; anything not listed is not
   permitted.
4. **The walk.** The executor goes through the flow in a real browser and takes screenshots
   at assertions, transitions and failures.
5. **Headless checks** (site audits). Scripts measure what a walk cannot do reliably:
   overflow at five widths, cookies before and after consent, leftover debug code.
6. **Re-check.** Every finding is verified before it goes in the report. The most serious
   ones are reproduced independently wherever that is safe.
7. **Report.** Verdict, coverage table, findings, improvement ideas, evidence index and
   next steps, always in the same shape. Each finding that rests on a screenshot shows that
   screenshot directly beneath it, and a PDF or HTML export is checked to make sure the
   images are inside it.

## The scales

| Severity | Meaning |
|---|---|
| S1 Blocker | A critical journey is impossible, or there is data loss, a security or privacy exposure, or wrong money movement |
| S2 Critical | A critical journey works only through a workaround most people will not find |
| S3 Major | Real impact on a supporting feature or an edge case; the journey still completes |
| S4 Minor | Cosmetic or low impact |

Priority (P1 to P4) is a separate recommendation about when to fix. The lead recommends it;
the product owner decides.

## The verdict is decided by rule

- **FAIL**: any open S1 or S2, or a top risk that could not be tested at all.
- **PASS WITH CONDITIONS**: no S1 or S2; open S3s or coverage gaps, listed.
- **PASS**: everything planned was executed and nothing S1 to S3 is open.
- **INCONCLUSIVE**: the tooling failed in a way that left the question unanswered.

A coverage gap is always stated. An area that was not tested is never allowed to read as
tested and fine.

## Where the output goes

Each run gets its own folder under `$QA_RUNS` (default `~/qa-runs`), named after the target
and the date, holding briefs, screenshots, evidence, the report and a machine-readable
`findings.json`. A later run of the same site compares itself with the earlier one and
reports what is fixed, still open, new or not re-tested.
