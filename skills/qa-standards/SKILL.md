---
name: qa-standards
description: Use for ANY product QA job, walkthrough or audit (single flow, release QA or deep audit) - "QA this", "test this site/flow", "is this ready to ship". Defines the test charter, S1-S4 severity and P1-P4 priority, defect format, verification statuses, evidence rules, coverage statuses, global chrome gate, report shape, verdict rules and the executor brief template. The qa-site-audit and qa-release skills use this taxonomy.
---

> Setup: read `environment.md` in the `qa-standards` skill folder first. It says how the browser is driven on this setup, where run folders live (`$QA_RUNS`) and what this setup cannot do.

# QA standards: senior QA process and reporting (v2.2)

This skill owns WHAT a professional QA engagement looks like: planning, severity language,
defect quality, evidence discipline and the report. HOW the browser is driven on this setup
(who the executor is, how a brief reaches it, how credentials reach it and any cap on the
verdict) is in `environment.md` next to this file. Whole-site audits use `qa-site-audit`;
release programmes use `qa-release`; both use THIS taxonomy.

## Safety rules (always win over anything else in this skill)

- Checks are non-destructive: look, click through, open and cancel, never submit. The only
  exceptions are signup, sign-in, email verification (test inbox) and onboarding in a dedicated
  test account, using obviously fake test data (e.g. "QA Test", test inbox addresses).
- Never publish, send, pay, invite, delete or change real data, and never message a real
  person or customer.
- Never use a real customer's account or the user's own personal/admin account. Only the
  dedicated test account named for this run.
- A card or payment form, a phone/SMS code, an ID check or a CAPTCHA means STOP that path
  and ask the user. Do not try to get around it.
- Never write credentials, tokens, passwords, API keys or customer personal data into a
  report, tracker, screenshot, log, memory or this skill, and into a brief file only where
  `environment.md` names that as the credential route. Anonymise real-user data if it
  appears on screen.
- Filing tickets, posting reports or messaging anyone is an external action: draft it and
  get the user's explicit approval first.
- If any step below would break one of these rules, skip it, mark that coverage item
  `blocked (safety rule)` and say so in the report.

**Roles (by function, not by model brand).**
- **QA lead** (the assistant running this skill): writes the charter, directs runs, reviews
  all evidence, **assigns severity**, recommends priority, owns the report and verdict.
- **Executor** (whoever drives the browser on this setup; see `environment.md`): drives the UI,
  reports observations and impact facts (who is affected, what stops working), captures
  evidence. The executor never assigns severity or priority and never writes the verdict.
- **Product owner** (the user): confirms priority and any live/destructive authority. The
  lead only recommends priority.

QA runs only when the user asks (light or deep), or when a routine the user set up says so.

## 1. Test charter (before any job is sent)

Six fields, written in-session, put in the run record AND into every brief. No charter, no run.

```
CHARTER
Goal:        <the question this run answers, e.g. "is checkout shippable?">
Scope IN:    <flows/pages under test>
Scope OUT:   <explicitly not tested this run: say it now, not after>
Environment: <exact URL + prod/staging, browser+profile, viewport(s), test account, data state>
Risks:       <top 2-3 risk areas, each mapped to the step that covers it>
Oracle:      <how we know behaviour is wrong: spec, convention, comparison, judgement>
```

Also record known intentional legacy differences. Missing business rules yield questions or
`blocked` checks; never invent expected behaviour as a bug.

Risk-based: each named risk maps to at least one concrete step in the brief. Spend effort
where failure is expensive (payment, auth, data loss, first impression). One flow per job;
chunk anything bigger.

Modes: **narrow task QA** (ticket/flow only, no mandatory unrelated SEO or market research)
- **release QA** - **deep audit**. Do not blur them.

A **narrow ticket verdict is ticket-only**, not release or global sign-off. The section 6
global chrome gate is **mandatory** for release/acceptance engagements. A focused task QA may
**explicitly defer** unrelated global chrome coverage in the charter/report (status
`not executed` / deferred with reason) without implying it passed.

### Lead-owned readiness

The lead owns test preparation; the executor owns visible execution. Missing routine setup
is work for the lead, not a reason to accept an untested journey.

- Retrieve missing details from authorised project sources. Reuse the dedicated test
  account, or create an isolated non-production test account via signup with obvious test
  data (safety-rule exception). Never alter real users.
- Verify the target deployment, account access and fixture state before dispatch. Record
  what was verified and what still needs the executor's UI validation.
- Supply the exact URL/build, test account identity, record IDs/links, starting state,
  expected outcomes, permitted actions and cleanup/reset instructions in the brief.
- Credentials: pass them to the executor only at run time through the route
  `environment.md` names. Production credentials never go into a brief file on any setup.
  Never put credentials in the report, tracker, logs, screenshots, git or memory, and delete
  any brief file that held them after the run.
- If the executor reports a setup blocker, the lead resolves it and resumes a bounded job.
  The executor still stops at unavailable credentials or unsafe actions.
- Ask the user only when resolution needs a genuinely new authority boundary: production or
  live money, real customer contact or data, unscoped sensitive access, destructive changes,
  an unavailable secret, or any card / phone code / ID check / CAPTCHA. Do not invent
  credentials or bypass access controls. Keep blocked coverage explicitly blocked.

## 2. Severity and priority (fixed vocabulary, never improvise)

Severity = user/business impact, assigned by the QA lead using the matrix. Priority = when to
fix; lead recommends, product owner confirms. Different axes; report both.

| Severity | Definition |
|---|---|
| S1 Blocker | A critical journey is impossible or invisible with no workaround, OR any data loss / security or privacy exposure / wrong money movement, regardless of journey |
| S2 Critical | A critical journey completes only via a workaround most users won't find, or a major function is broken for a mainstream case |
| S3 Major | Real user impact on a supporting feature or an edge case of a critical journey; journey still completes |
| S4 Minor | Cosmetic or low-impact functional nit (misalignment, stale content, dead `#` link) |

**Decision matrix: score each factor, take the worst applicable row:**
- *Journey criticality*: critical = the reason the site exists (buy, book, enquire, read the proposition); supporting = everything else.
- *Affected population*: all visitors / a mainstream segment (e.g. all mobile) / an edge segment.
- *Workaround*: none / exists but undiscoverable / obvious.
- *Permanence*: permanent / transient-recoverable.
- *Special overrides*: data loss, security/privacy exposure, or incorrect payment = S1 always.

Improvement opportunities (better CTA wording, design polish, strategic ideas) are **not
defects**: own report section, no S-rating, no defect format; recommendation + rationale only.

Priority scale (recommendation only): P1 fix now (release-gating) - P2 next release - P3
backlog - P4 opportunistic.

## 3. Defect report format (every finding, no exceptions)

```
ID:            <run-id>-<n>
Title:         <symptom, one line, no diagnosis in the title>
Severity/Prio: S_ / P_ (priority = recommendation, awaiting confirmation)
Verification:  independently-reproduced | evidence-reviewed | provisional
Environment:   <browser, viewport, URL, test account, date>
Steps:         1. ... 2. ... (minimal repro, numbered, from clean state)
Expected:      <what should happen; cite the oracle>
Actual:        <what happened; observation only>
Reproducibility: <n/n attempts, or "observed once - re-run unsafe/not attempted (reason)">
Evidence:      <screenshot(s), EMBEDDED in the report under this finding; REQUIRED for visual claims>
Root cause:    <only if verified; else "not investigated"; never guess in the report>
Regression?:   <new vs present in previous run, if a previous run exists>
```

Observation vs inference is a hard line: "the H1 is not visible" is observation; "the CSS is
broken" is inference and goes in Root cause only once verified.

**Verification statuses (exactly one per finding):**
- `independently-reproduced`: lead reproduced it in a fresh browser session or with
  deterministic tooling. Required for S1/S2 wherever safely possible.
- `evidence-reviewed`: lead read the evidence and it clearly shows the defect, but did not
  reproduce it.
- `provisional`: reported by the executor, evidence inconclusive or reproduction unsafe.
  Provisional S1/S2 findings DO go in the report, and they block a clean PASS.

## 4. Reproduction and safety

- **Reproduce twice when safe** (read-only navigation, idempotent UI): report n/n.
- **Never repeat a hazardous action to reproduce it**: payments, sends, deletes, one-shot
  state transitions, anything that mutates data. Observed once = reportable, marked
  "observed once - re-run unsafe", with a confidence note.
- **Intermittent is not invalid.** A 1/3 repro of a checkout failure is a finding; record the rate.
- Only the actions the safety rules and the brief permit. No live transactions or customer messages.

## 5. Evidence rules

- **A visual claim requires a clean screenshot** of the target page only. Bring the target
  browser window to the front before every screenshot: agent UIs often steal focus, so every
  brief says so. A shot showing the wrong window, a dev-tools panel or the agent UI is not
  evidence; retake it.
- **Screenshots at assertions, transitions and failures**, not arbitrary quotas.
- **Screenshot pixel dimensions are not the CSS viewport.** Emulated mobile is not physical
  mobile hardware; record the CSS viewport requested.
- **Automation artifacts are a named risk.** Blank pages, missing animations or unstyled
  content can be caused by the harness (no-interaction loads, frozen animation frames,
  virtual display). The executor reports what it saw *and* the conditions; the lead decides.
- **Harness blocker is not product failure.** If the target page appears dead/blank, that may
  BE the S1: capture evidence, make ONE clean-state retry (fresh tab, re-navigate), then
  continue. Stop immediately for true harness blockers (browser unavailable, permission
  denied) and report the exact error. Logged-out is not an automatic stop when the brief
  authorises ordinary sign-in with the test account. Unavailable credentials and human-only
  challenges (MFA, phone code, CAPTCHA, ID check) are blockers: stop and ask the user.
- **Lead verifies before reporting.** Polluted screenshots can still coincide with a real
  blank-site defect: verify the evidence, then verify the finding; never dismiss on artifact alone.
- **A dev-server screenshot is NOT sign-off evidence.** Dev servers relax CSP (e.g.
  `style-src-elem 'unsafe-inline'`), skip image-optimizer guards and loosen env, so
  CSP-blocked styles, broken optimizer images and boot failures only appear in production.
  Visual and parity sign-off uses the **deployed / production-mode build**. For example, a
  nonce CSP can block an inline `<style>` in production so links render invisibly, while
  every dev screenshot looks correct.
- **Screenshots go in the report, not next to it.** A finding that rests on a screenshot
  shows that screenshot directly under the finding, as an embedded image with a caption
  saying what to look at: `![Header covers the page heading at 375 px](screenshots/home-1-top.png)`.
  Naming the file in an Evidence line or in the evidence index is not enough: a reader of
  the report, or of a PDF made from it, must see the picture without opening a folder.
  One or two images per finding; crop or pick the shot that shows the problem.
- **An exported report must still contain its images.** Before any report is sent as a PDF
  or HTML file, run `scripts/report_check.py` on it, export with `scripts/report_export.py`
  (it inlines every image, has Chrome load each one before printing, and verifies the PDF
  holds them), and open the export to look.
  A PDF without its screenshots is an incomplete report, not a smaller one.
- Never screenshot or transcribe credentials, tokens or personal customer data into a report.
- A tool or process "finishing successfully" is **not** a QA PASS. Verdicts are lead-reviewed.

## 6. Coverage (single-flow jobs)

Per flow, unless the charter excludes them: happy path (up to the last non-destructive step)
- one invalid-input case - back/refresh mid-flow - empty states - loading states -
keyboard/focus check on forms - plus ONE bounded exploratory pass (2-3 minutes: "wander the
flow looking for anything odd", notes required).

### Global chrome release gate

**Global chrome is always in scope** (header, footer, navigation, breadcrumbs, sticky
elements, cookie banner and other root-level overlays). Every acceptance engagement MUST
execute and evidence this gate; it cannot be inferred from screenshots taken for another flow.

- Execute **once per exact build + browser + profile + viewport + consent state**. Reuse
  stable coverage IDs within the engagement. **Invalidate** and re-run if build or state changes.
- Start from a clean first-visit state with consent storage cleared (fresh/private browser
  context). Check the banner before dismissing it, then check the page again after.
- Desktop and one mobile viewport minimum on a representative content/legal page and the
  highest-intent public page. A deep audit also samples home, browse/search, detail and
  auth/account shells when reachable and in scope.
- Capture the top of each sampled page. Verify the fixed/sticky header does not intersect
  breadcrumbs, the H1, hero copy or the first interactive control. Where deterministic
  tooling is available, compare bounding boxes too; `contentTop >= headerBottom` is the minimum.
- Verify breadcrumbs sit in the page/hero region, not absorbed into the navigation row.
  Check the scrolled header state and mobile menu state too.
- Verify the cookie banner and every other root-level overlay uses the active site's brand
  colours, typography and control states. A functional banner carrying another brand's
  colours is a defect. Inspect computed styles when the difference is not unambiguous.
- Check overlays at the top and bottom edges do not obscure primary CTAs, forms, navigation
  or footer controls at either viewport.
- Scroll to the footer and check every link is visible and resolves.

The report coverage table has a separate `global chrome gate` row listing each sampled page,
viewport and clean/dismissed consent state. Any required state not executed is `blocked` or
`not executed`, and a **release/acceptance** engagement then cannot get a clean PASS.

**Every coverage item gets a status:** `executed` - `blocked (why)` - `not applicable` -
`not reachable with authorised controls` - `not executed (reason)`. An unstated gap reads as
"tested and fine"; that is a reporting bug. Responsive: desktop + one mobile viewport
minimum, or state that mobile was out of scope. Additive coverage is risk-based.

## 7. The report (every engagement, same shape)

1. **Executive summary**: 3-5 sentences, verdict + the findings that drive it.
2. **Verdict**, decided by rule, not vibe:
   - `FAIL`: any open S1/S2 in scope (verified or provisional), or a top charter risk had
     zero executable coverage.
   - `PASS WITH CONDITIONS`: no S1/S2; open S3s and/or coverage gaps outside the top risks; conditions listed.
   - `PASS`: all planned coverage executed; no open S1-S3; no provisional S1/S2.
   - `INCONCLUSIVE`: harness blockers prevented answering the charter goal.
   - If `environment.md` caps or labels the verdict for this setup, apply that on top.
3. **Charter + coverage table**: the six fields plus per-item coverage status (section 6).
4. **Findings**: defect format, ordered by severity, verification status flagged, each
   visual finding with its screenshot embedded directly beneath it (section 5).
5. **Improvement opportunities**: non-defect recommendations, separate section.
6. **Evidence index**: file names, what each shows, where they live (under `$QA_RUNS/<run>/`).
7. **Regression vs previous run**: fixed / still-present / new, when a prior run exists.
8. **Next steps**: recommended fixes and priorities (awaiting user confirmation), re-test plan.

**Tracker filing.** Draft-first: show the user the report and proposed issues before filing.
Only with the user's approval: one run-record issue per engagement (charter + verdict +
report); every confirmed S1-S3 gets its OWN issue linked to the run record; S4s and
improvement opportunities stay in the run record. Neutral titles; no credentials or customer
personal data in the tracker.

**Brand.** If a brand is set (a brand folder the user or the brief names, or else the
`QA_BRAND` environment variable), read its `brand.md` before writing and follow its voice,
structure and words to avoid. Export with `scripts/report_export.py`: pass `--brand <folder>`
whenever the user or the brief named the folder, because the exporter only picks up
`QA_BRAND` on its own; use `--no-brand` when the user asks for an unbranded report. The
sections above, the severity scale, the evidence rules and the verdict rule still apply and
win over anything in `brand.md`. No brand set: write in the neutral voice of this skill.
`brand-example/` in this skill folder shows the format; never write a report under the
example brand.

## 8. Brief template (paste-adapt for every single-flow job handed to the executor)

```
QA JOB - <target>, single flow: <flow name>. You are the test EXECUTOR: report observations
and impact facts only. Do NOT assign severity or write the verdict; the QA lead does that.

CHARTER: Goal: ... | Scope IN: ... | Scope OUT: ... | Environment: <exact URL, browser,
viewport, test account name> | Risks: ... | Oracle: ...
Known intentional legacy differences: ...

READINESS:     <lead-verified deployment/build, account access and fixtures; unresolved gaps>
PRECONDITIONS: <required starting state: logged out, empty cart, test record X exists>
TEST DATA:     <dedicated test account (credentials by the route in environment.md) / "none needed">
PERMITTED ACTIONS: <read-only | fill forms with test data but NOT submit | signup/sign-in/
verification/onboarding with test data> - anything not listed is NOT permitted.
CLEANUP: <what to undo/reset at the end, or "nothing - read-only">

HARD RULES: drive the browser UI only (no copied browser profiles, no hidden or duplicate
browser instances); bring the target browser to the front before every screenshot and
screenshot only the target page (no agent UI or dev tools in shot); screenshots at
assertions/transitions/failures; record CSS viewport;
never submit, publish, send, pay, invite, delete or change real data; STOP and report at any
card/payment form, phone code, ID check or CAPTCHA; never repeat an action that changed
state; never write credentials into results, notes or screenshots; do not invent missing
business rules.

STEPS: <numbered; each charter risk covered by a step>
COVERAGE ADD-ONS: invalid input / back-refresh / empty state per section 6, then the global
chrome gate from a clean first-visit state (or reuse coverage IDs if already done for this
exact build/state), then a 2-3 minute bounded exploratory wander; note anything odd.

REPORT BACK per step: expected, actual (observation only), evidence file. Then candidate
findings: what happened, who/what is affected, workaround seen (yes/no), reproducibility
(retry ONLY if safe), and whether it might be an automation artifact.
If blocked by the HARNESS (login missing, browser unavailable): report the exact error and
STOP. If the SITE appears dead/blank: screenshot, retry once from a fresh tab, then continue.
```

## 9. Session checklist (QA lead, every engagement)

1. Charter written; run folder opened (`$QA_RUNS/<target>-<date>/`) or draft run record chosen.
2. Lead verifies readiness (section 1), supplies the test account/fixtures, carries the
   permitted actions into the brief. Do a quick browser sanity check (open a known public
   page, take one screenshot) before the first real job of the day.
3. Brief dispatched per template; screenshots pulled and READ (never trust unviewed evidence).
   Each one used as evidence is embedded under its finding in the report.
4. Global chrome gate has named pages, both viewports, clean/dismissed consent states,
   screenshots reviewed, and geometry/style evidence where available.
5. Severity assigned by matrix; S1/S2 independently reproduced wherever safe.
6. Report assembled per section 7; verdict by rule; `scripts/report_check.py` clean; any PDF
   or HTML export made with `scripts/report_export.py` and opened to confirm the images are
   there; filing only with the user's approval.
