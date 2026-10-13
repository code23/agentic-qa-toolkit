# Client summary scoring rubric (0–10 per dimension)

## Dimensions

| Key (findings.json) | Name in the client summary | Report section |
|---|---|---|
| `qa-functional` | Functional QA | Functional QA |
| `ux` | User experience | UX (incl. conversion path) |
| `accessibility` | Accessibility | Accessibility |
| `performance` | Speed and performance | Performance |
| `seo-ai` | Search & AI visibility | SEO / schema / AI search |
| `security-privacy` | Security & privacy | Security & privacy |
| `content` | Content quality | Content (duplication, freshness, artefacts) |
| `cms-code` | CMS & code | CMS / code (only when in scope) |

These match the `dimension` values in findings.json and the report's per-dimension sections.
Use the plain-English names in `summary.md`, never the keys.

## Coverage comes first

Every dimension has a `coverage` entry in findings.json. `findings.py score` uses it:

| Coverage | Score shown |
|---|---|
| `executed` with a non-empty `checks` list | the arithmetic below |
| `partial` with a non-empty `checks` list | the arithmetic below, **capped at 8**, with "partly covered: <note>" |
| `executed` / `partial` with no `checks` | "not scored (executed but no checks recorded)"; `check` rejects it |
| `blocked` | "not scored (blocked)" |
| `not-in-scope` | "not scored (not in scope)" |
| `not-executed` or no entry | "not scored" |

`findings.py template` starts every dimension at `not-executed` with no checks, so nothing
scores until the lead records what actually ran. "Mostly blocked" means fewer than half of the
dimension's planned checks ran: record it as `blocked`, not `partial`. A dimension with no
findings is only "Strong" if it was actually tested.

## Arithmetic (what `findings.py score` computes)

- Every finding that is **still on the site or of unknown state** counts: `open`,
  `accepted-risk`, `wont-fix` and `not-retested`. Only `fixed` is excluded. Accepting a risk
  or deciding not to fix it is a workflow decision; the defect is still there, so the score
  does not go up.
- A `not-retested` finding also makes its dimension count as **partial** (capped at 8, note
  "N not re-tested"): the dimension's state is partly unknown.
- Start at 10 and subtract per counted finding in that dimension:

  | Severity | Deduction |
  |---|---|
  | S1 | 6 |
  | S2 | 4 |
  | S3 | 2 |
  | S4 | 0.5 |
  | Improvement | 0 |

- `provisional` findings count at half weight.
- Caps:
  - with any S1, the score is at most 3
  - with any S2, at most 5
  - with any S3, at most 8
  - partial coverage (including any not-retested finding), at most 8
- Floor 0. Round to the nearest 0.5.

## Counting unit

One finding = **one root cause per template**. A root cause shared by every page is one
`sitewide` finding with an `instances` count, not one finding per page. Six axe violations
with six different fixes are six findings; one header component causing five symptoms is one.
Splitting or merging differently from the previous run moves the score with no change to the
site, so keep the unit stable.

## Default severities for script flags

Starting points; the lead raises or lowers them with the qa-standards matrix and a stated
reason (journey criticality, affected population, workaround).

| Script flag / evidence | Default | Dimension | Raise when / lower when |
|---|---|---|---|
| Sideways scroll (`actualScrollX > 0`, or `--no-mobile` scroll) at any width | S4 | ux | S3 if it hides content or a CTA; S2 on a critical journey on all mobile |
| `overflowPx > 0` with no actual scroll | not a defect | — | note only |
| Header overlaps H1 / breadcrumb / first control | S3 | ux | S2 if it hides the primary CTA |
| Hidden debug/test element | S4 | content | S3 if visible to users |
| Visible "lorem", placeholder or test copy | S3 | content | S4 in a low-traffic corner |
| Exposed source map (200) | S4 | security-privacy | S1/S2 if it exposes secrets or private code |
| `stale-quarter`, `old-year`, `copyright-year` | S4 | content | S3 if it drives pricing or booking |
| `quarter-ambiguous` | judge in context | content | — |
| Near-duplicate pair (≥ 0.90) | S3 | seo-ai | S4 for two pages; S2 for a doorway-page pattern at scale |
| Title–slug mismatch | S4 | seo-ai | — |
| Offer or price shown at one breakpoint only | S3 | ux | S2 if the offer drives the main conversion |
| Pre-consent tracking | per the mapping in `consent-and-privacy.md` | security-privacy | — |
| Reject not honoured (`rejectHonoured: false`) | per the same mapping | security-privacy | — |
| Vendor missing from policy | S3 | security-privacy | S4 for a functional vendor |
| Mixed content | S3 | security-privacy | S4 for passive images only |
| Console page error with no visible effect | S4 | qa-functional | S2/S3 if a feature breaks |

## Lead adjustment

The lead may move a score by at most ±1, with a one-line reason written in the summary.
For example, many S4s that all come from one template fix. Never adjust a "not scored"
dimension into a number.

## Bands (wording for the client)

| Score | Wording |
|---|---|
| 9–10 | Strong. Polish only |
| 7–8.5 | Good, with clear fixes |
| 5–6.5 | Needs work. Visible to users |
| 3–4.5 | Significant problems |
| 0–2.5 | Critical. Fix before promoting |

## One-page summary layout (`summary.md`)

1. Site, date, scope, verdict (from qa-standards rules). One sentence on what that
   means.
2. A score table: dimension (plain-English name), score or "not scored", band, and a
   one-line reason (for partial coverage, what wasn't covered; name accepted-risk / won't-fix
   items that still pull the score down).
3. The top 3–5 issues in plain words: what, where, who it affects, and the fix. Verified
   findings only (`independently-reproduced` or `evidence-reviewed`); a provisional one may
   appear only labelled "(unconfirmed)".
4. Quick wins: under a day each.
5. Not covered or blocked, such as physical devices, field data, logged-in areas, and
   anything excluded from scope.
6. A pointer to the full report and the regression summary, if any (including the number of
   earlier findings "not re-tested").

No jargon without a gloss, no hype, no ranking or revenue promises.
