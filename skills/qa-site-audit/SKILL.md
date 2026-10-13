---
name: qa-site-audit
description: Use when the user asks for a deep, read-only audit of a whole site or web product (multi-pass, possibly long-running) - QA, UI/UX, responsive viewport matrix, accessibility, performance (lab plus field data when granted), SEO/schema/AI-search visibility, content freshness and duplication, passive security/privacy hygiene including pre/post-consent tracking, CMS/code review when scoped, and a synthesized report with a client-ready scored summary, roadmap and regression against previous runs. Not for a single-ticket check (use qa-standards) or a release sign-off programme (use qa-release).
---

> Setup: read `environment.md` in the `qa-standards` skill folder first. It says how the browser is driven on this setup, where run folders live (`$QA_RUNS`) and what this setup cannot do.

# QA site audit

Read the `qa-standards` skill FIRST. It owns the charter, severity matrix (S1-S4 +
improvement opportunities), defect format, verification statuses, evidence rules and verdict
rules. This skill adds only what is audit-specific: the passes, the lead/executor split and
long-run mechanics.

Per-audit working folder: `$QA_RUNS/<host-slug>-<YYYY-MM-DD>[-<n>]/` (host with dots
as dashes, e.g. `example-com-2026-10-10`; add `-2`, `-3` for a same-day re-run; the folder name is
also the `run_id`) with `briefs/`, `screenshots/`, `evidence/`, `report.md`, `summary.md` (client
one-pager) and `findings.json` (machine-readable findings for regression). Never overwrite an
existing run folder.

Reusable checks live in `scripts/` (usage below); long method detail lives in `references/`.

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
  `environment.md` (in `qa-standards`) names that as the credential route. Anonymise
  real-user data if it appears on screen.
- Filing tickets, posting reports or messaging anyone is an external action: draft it and
  get the user's explicit approval first.
- If any step below would break one of these rules, skip it, mark that coverage item
  `blocked (safety rule)` and say so in the report.
- **Typing into forms (part of the test, never a submission).** Type only obvious test data
  ("QA Test", a test inbox address such as qa-test@example.com, "This is a QA test, please
  ignore") to exercise validation, field types, error messages, input masks and length limits.
  - NEVER press submit/send or otherwise trigger submission: no Enter in single-field forms, no
    "Next" that sends data, nothing that auto-submits.
  - Guardrail FIRST: before typing into a live form, check for save-as-you-type behaviour
    (autosave, partial lead capture, HubSpot/Typeform-style partials). Watch the network
    requests while typing a single harmless character into one field and then moving focus
    away. If any request carries field data, stop that form, clear the field, and ask the user
    before continuing. If network requests cannot be observed, do not type into that form;
    mark it `blocked (save-as-you-type check not possible)`.
  - Clear all fields afterwards.
  - Card/payment, phone/SMS code, ID or CAPTCHA fields: never type; stop and ask.
  - Scripts never type into forms.
- **Field data: the one narrow exception to the account rule above.** Analytics, Search
  Console, CrUX/RUM and similar data may be read only through a read-only connector the user
  explicitly grants for this run. Aggregate reports only. Never open session recordings,
  person/user profiles, individual user data or raw event exports, never screenshot them, and
  never save, create or annotate anything (no saved insights, dashboards, notes or annotations).
  No such grant: field data is `blocked`.

## Non-negotiables (audit-specific; qa-standards rules also apply)

- Read-only. Only the safety-rule exceptions (signup/sign-in/verification/onboarding of a
  dedicated test account with obvious test data), plus any named safe test action the user
  explicitly approves for this run, are allowed.
- Never real emails, live enquiries, content changes, plugin updates, settings changes or payments.
- No tool/extension/scanner installs mid-audit without the user's approval.
- Missing credentials: mark that pass `blocked`, continue with public checks.
- Deterministic findings and subjective judgement are labelled as such, never blended.
- Draft the synthesis for the user before any tracker filing.
- Clicking a cookie banner's Accept (or Reject) control in a lead-side headless profile is a
  consent choice, not a form submission, and is allowed for the post-consent pass. Never tick
  or submit anything else on the way. At most one such click per fresh profile.
- Field data only under the field-data exception in the Safety rules. Never ask for, paste or
  store credentials, tokens or API keys.
- Scripts in `scripts/` are polite by design: one page at a time, a delay between loads, a
  tagged UA, and their own fetches are single GETs with a timeout and size cap. (A browser page
  load fetches its own subresources in parallel, as any visitor's browser does.) Do not raise
  their concurrency or turn them into crawlers.

## Execution model (lead + executor)

- **Executor** (whoever drives the visible browser on this setup, per `environment.md`, given
  one chunk brief at a time) does the **human-POV walk only**: one template/page-group per chunk, screenshots at
  assertions / transitions / failures, senior-UX critique per page. The executor's walk uses
  the browser UI only: no scanners, command-line HTTP clients, OS scripting or package
  installs as part of the walk. Where the executor is a separate machine, `environment.md`
  says what may run on it.
- **QA lead** (the assistant running this skill) runs selective complementary deterministic
  checks headless on the lead machine (see Accessibility / Performance), assigns all severity, and
  owns the synthesis after reviewing evidence. Independently reproduce S1/S2 candidates in a
  fresh browser session or with deterministic tooling: verify the evidence, then the finding.
- Lead-side headless runs use a **separately launched** headless Chromium with a fresh,
  throwaway profile per check (the scripts do this). Never drive or attach to the desktop
  browser the executor uses (no CDP to it).
- **Capture discipline (both roles)**: wait for animations and scroll to settle before a
  screenshot (scroll, pause ~1 s, then shoot). The executor rules are in the CAPTURE block of
  the preamble below. **A visual finding needs an independent re-check** (headless DOM,
  computed style and bounding boxes, or a second executor capture after settling) **or an
  explicit lead judgement** that the screenshot is unambiguous and matches none of the
  false-positive patterns; that gives `evidence-reviewed`. Otherwise it stays `provisional`.
  Hover, focus, opened-menu and logged-in states that can't be re-checked headless can still
  reach `evidence-reviewed` this way. False-positive patterns are in
  `references/capture-discipline.md`.

## Long-run mechanics

- One chunk per executor job; collect each chunk's result by its exact job ID before judging
  it, so one chunk's output is never read as another's.
- Sanity-check the browser before kickoff (open a known public page, one screenshot). If the
  browser is unavailable, report the exact error; do not invent workarounds mid-audit.
- Every chunk brief = effort line + the **executor preamble** below + the chunk brief. The chunk
  brief names the clean-context method to use (private/incognito window, guest window, or
  clearing site data via the browser's settings).
- Every brief ends with: if low on budget, stop and write the **page-by-page log and
  candidate findings** for what was seen; the executor does **not** write the verdict.
- **Minimum viable audit** when budget is short, in this order: preflight → global chrome gate
  → pre-consent capture → zero-interaction render → viewport matrix → accessibility →
  performance → SEO → content scripts → conversion path → field data. Anything skipped is
  `not executed (budget)` in the coverage table and its dimension is not scored.

### Executor preamble (prepend to every chunk brief)

```
You are the test EXECUTOR for one chunk of a read-only site audit. Report observations and
impact facts only - no severity ratings, no final verdict; the QA lead assigns those.

HARD RULES
- Drive the browser UI only. No dev-tools protocols, duplicate/hidden browser instances,
  copied profiles, shell browsing (no command-line HTTP clients), OS scripting or installs.
- Clean first visit: opening a new private/incognito or guest window in the same browser, or
  clearing this site's data via the browser's own settings UI, is permitted and is the
  expected way to get a clean first-visit context. Use the method the brief names.
- Bring the target browser window to the front before EVERY screenshot. Screenshot only the
  target page (no agent UI, dev tools or other windows in shot); otherwise retake it.
- Screenshots at assertions, transitions and failures, not a quota. Name files
  <chunk>-<n>-<what>.png.
- Record the CSS viewport the brief requested. Screenshot pixels != CSS viewport. Emulated
  mobile != physical device.
- Read-only: never submit forms, never sign in except with the named test account, never
  trigger payments, never change content or settings, never send or invite anything.
- Forms: typing obvious test data ('QA Test', qa-test@example.com, 'This is a QA test, please
  ignore') to check validation, field types, error messages, input masks and length limits IS
  part of the test. NEVER press submit/send or trigger submission (no Enter in single-field
  forms, no 'Next' that sends data, nothing that auto-submits). FIRST, per live form: type one
  harmless character into one field, move focus away, and watch the browser's network
  activity; if any request carries field data (autosave, partial lead capture), stop that form,
  clear the field and report it for the lead to ask the user. Watching requests through the
  browser's own built-in developer-tools Network panel (opened from the browser UI, closed
  before page screenshots) is allowed for this check only. If you cannot observe network
  requests, do not type into that live form: report it BLOCKED (save-as-you-type check not
  possible). Clear all fields afterwards. Never type into card/payment, phone/SMS code, ID or
  CAPTCHA fields.
- Card/payment form, phone code, ID check or CAPTCHA: STOP that path and report it.
- Never open analytics session recordings or user profiles, even if a link appears.
- Missing credential: report exactly `MISSING CREDENTIAL: <site>`, skip that item, continue.
- Blank/dead page: screenshot it, retry once from a fresh tab, then continue - it may be the
  most important finding. Note whether you had interacted before the blank shot (some
  optimizers hide content until first interaction).
- Harness error (logged out unexpectedly, browser unavailable): report the exact error text
  and stop this chunk.
- Do not invent missing business rules; mark those checks blocked.
- Low on budget: STOP and write the page-by-page log plus candidate findings so far. Never
  declare PASS/FAIL.

CAPTURE
- After a load or scroll, wait ~1 s before shooting; longer if anything is still moving
  (fades, sliders, typing text, count-ups, sticky-header transitions).
- Per shot record: CSS viewport, scroll Y, consent state (banner shown / accepted / rejected /
  not shown).
- Anything that looks blank, see-through or missing an image: take two shots ~2 s apart at
  the same scroll position and report both.
- Widths: desktop (1366 or 1440), tablet (768 AND 1024) and mobile (375), unless the brief narrows it.
- Known false positives, report them as observations, not breaks: mid-fade sections that look
  blank; decorative colour bands that look like missing images; aria-hidden marquee/ticker
  clones that look like duplicated text; a sticky header shot mid-transition that looks
  see-through.

PER PAGE report: expected vs actual (observation only), evidence file, anything odd - layout
breaks, broken interactions, confusing states, slow steps, dead ends, modal or cookie-banner
problems, trust gaps - plus who/what is affected and any workaround seen.

PER TEMPLATE also record: the desktop nav link list; the opened mobile-menu link list; the
onward links at the end of the page (excluding global nav/footer); clicks from this page to
the contact route; what the contact route promises (response time, hours, timezone label).

KEYBOARD (when the brief includes accessibility): tab through header, banner, menus, forms and
modals; report focus order, visible focus, and any focused element hidden behind the sticky
header or cookie banner (WCAG 2.2 2.4.11); note controls that look smaller than 24x24 px
(2.5.8).

GLOBAL CHROME GATE
- Unless the brief says this gate was already completed for this exact build/browser/
  profile/viewport/consent state (reuse coverage IDs), do not assume another screenshot covered it.
- Start from a clean first-visit browser context. If consent is already stored and no clean
  state is available, report that item BLOCKED.
- At desktop and mobile widths, capture the full top edge of a content/legal page and the
  highest-intent public page. Check the fixed/sticky header does not overlap breadcrumbs,
  H1, hero text or the first control, and that breadcrumbs belong to the page/hero, not the nav row.
- Before dismissing consent, check the banner uses this site's colours, typography and
  controls (not another project or brand) and obscures no CTA or navigation. Then dismiss it and re-check.
- After accepting, open the site's cookie settings, withdraw consent, reload, and report whether
  the banner/settings show the withdrawn state (consent withdrawal row).
- Capture the scrolled-header state, mobile-menu state and footer. Report each state as
  EXECUTED or BLOCKED with its evidence file.
```

## Calibration: what great findings look like

Specific, evidence-led, with the user/commercial impact stated, not checklist ticks:

- "The header has two search boxes that route to two different systems and look identical -
  the single biggest first-touch confusion on the site." (not "search could be clearer")
- "The first-visit cookie banner physically overlaps the primary CTA on the highest-intent
  template." (a concrete overlap on a named page, with the stakes)
- "Content is invisible until first user interaction - Googlebot, link previews and mobile
  first-paint all see a blank page." (deterministic + commercial consequence)

Hunt for *classes* of issue: conflicting/duplicated controls, overlays eating CTAs,
placeholder copy, schema mismatches, template-level defects that ship to every page; one
template fix often propagates everywhere. One finding = one root cause per template; a
sitewide root cause is one finding with an instance count (`references/scoring-rubric.md`).

## Inputs to collect first

Target URL + prod/staging - permitted scope (exact domains) - repo path if code review is in
scope - CMS access level if CMS review is in scope - which dedicated test account to use if
login is in scope - form rule (default: "type test data to check validation, never submit",
per the Safety rules) - payment rule (always "stop before payment and ask") - field-data
connectors granted for this run, if any - target market/region (for consent and timezone
checks) - report audience. Missing inputs: proceed public read-only, list blocked areas.

## The passes

1. **Preflight**: run log with date, target, environment, scope, exclusions, the lead machine's egress
   country if known; sitemap, robots.txt, nav + footer links, key templates; initial risk
   notes. **Served vs rendered**: for one page per template, compare the served-HTML word
   count (`similarity.py`/`copy_freshness.py` output) with the rendered count
   (`viewport_overflow.js` `renderedWords`; pass its JSON as `--rendered`). Served under ~70% of
   rendered = client-rendered: the Python content checks for that template are
   `limited (client-rendered)`.
2. **Surface map**: page inventory before judging pages: homepage, core landing,
   services/sector, case studies/insights/careers/contact, key templates and custom post
   types, search/filters/archives/pagination, cookie + privacy surfaces, gated flows if
   approved. Sitemap/nav discovery only; no aggressive crawlers.
3. **Browser QA (executor)**: begin with the qa-standards global chrome gate from a
   clean first-visit state (once per exact build/browser/profile/viewport/consent state;
   reuse coverage IDs). Capture desktop+mobile top edges for home, a content/legal page,
   browse/search and a detail page; add auth/account shells when reachable. Check
   fixed-header clearance above breadcrumbs/H1, breadcrumb placement, brand styling of the
   cookie banner, banner overlap, dismissed state, scrolled header, mobile menu and footer.
   Lead pairs screenshots with bounding-box and computed-style checks when available. Then
   per representative page/flow: desktop + tablet (768 and 1024) + mobile shots; layout breaks,
   broken interactions, confusing states, slow steps, dead ends, modal and banner problems;
   nav, search, form validation (typing obvious test data after the save-as-you-type check,
   never submitting, fields cleared afterwards), error/loading/focus/hover/empty states;
   visible console/resource failures.

   **Lead-side viewport matrix** (alongside the executor walk, not instead of it): headless,
   emulated widths **375, 768, 1024, 1440, plus 320** for overflow, on one representative URL
   per template. Record horizontal overflow (and whether the page really scrolls sideways),
   offending elements, header clearance above H1, breadcrumbs and the first control, CTA
   spacing and mobile-vs-desktop visible text (`viewport_overflow.js`). Tablet/small-laptop
   widths (768-1024) break often and are easy to skip: always run them. **Emulated is not
   physical**: label results "emulated"; real-device checks stay with the human walk or are
   marked not covered. Method: `references/viewport-matrix.md`.

   **Clean first visit**: every lead-side check starts from a fresh headless profile (no
   cookies, storage or cache). Executor states that cannot get a clean profile are `blocked`.
4. **UI/UX review**: proposition clarity, CTA hierarchy, template consistency,
   spacing/typography/crop/responsive polish, touch targets, sticky elements, mobile menu,
   trust signals, readability, form friction. Lead reviews screenshots directly; heuristic
   notes are labelled as judgement.

   **Conversion path pass, per template**: distance to the next CTA (screens of scroll; the
   script measures in-content gaps), dead ends (pages with no onward route), offer/price
   parity between desktop and mobile copy, nav parity (desktop nav vs opened mobile menu), and
   clarity of the contact route (how many steps, what the user is promised, response-time
   claims). **Owners**: the executor records nav lists, onward links and clicks-to-contact
   (PER TEMPLATE line in the preamble); the lead runs the scripts and computes parity and dead
   ends. If product analytics is granted, add funnel drop-off per template (aggregate only).
   Method: `references/conversion-path.md`.
5. **Accessibility** (oracle: **WCAG 2.2 AA**): lead runs **one primary** automated engine
   headless on the lead machine (commonly axe-core, or whatever is already installed; installing one
   needs approval) as a complementary check; add a second engine only when corroboration is
   warranted. Lighthouse a11y may corroborate. **Scan output is evidence, not WCAG
   certification.** Executor: manual keyboard walk (tab order, focus visibility, skip links,
   modals, menus, forms, carousels, banner, search), including 2.4.11 Focus Not Obscured
   (focus hidden behind the sticky header or banner) and 2.5.8 Target Size; 3.3.8 Accessible
   Authentication when sign-in is in scope. Labels, headings, landmarks, alt text, contrast,
   zoom and 1.4.10 reflow (the 320 width), reduced motion.
6. **Performance**: lead lab scores (Lighthouse, default mobile and desktop presets, per
   template) paired with the executor's observed slowness. Take the **median of 3 runs** (5 for
   a page near a threshold), in the pre-consent state, on the same URL set as the previous run;
   record the Lighthouse version and run count in findings.json `tooling`. Image sizing, lazy
   loading, render-blocking assets, third-party scripts, fonts, CLS/LCP, cache headers. **Lab
   performance does not measure real-user INP**. **Field data** only under the Safety-rules
   field-data exception: CrUX through the keyless PageSpeed Insights page/API, Search Console
   and product analytics (aggregate reports only) via connectors granted for this run; show
   field next to lab per template, labelled URL-level or origin-level, never blended. No
   grant or no data: mark field data `blocked (no access)` and keep lab claims labelled lab.
   Method: `references/field-data.md`. **Check the optimizer itself**: delayed-JS /
   animation-frame-hijacking optimizers can hide content from no-interaction renders
   (Googlebot, PageSpeed, previews); test a
   fresh load with zero interaction before any input. If code is in scope, scan for
   unbounded queries, uncached remote calls, global asset loading, expensive builder patterns.
7. **SEO / schema / AI search visibility**: titles, metas, H1s, canonicals,
   robots/noindex, sitemap; OG/social previews; internal linking, orphans, breadcrumbs,
   thin/duplicate content; structured data per template (Organization/LocalBusiness/
   Product/Article/FAQ/BreadcrumbList/Service opportunities), validated against schema.org /
   Rich Results where reachable; llms.txt + AI-crawler stance, answer-friendly structure.
   Internal link status and redirect chains (one GET per unique link, reusing the surface-map
   list), a soft-404 probe (one random non-existent path), hreflang if multilingual. If Search
   Console is granted, cross-check indexing exclusions ("Duplicate without user-selected
   canonical", "Crawled - not indexed") and canonical choice against the duplicate-content
   pass. No unsupported ranking claims. Deep-audit mode only, not an add-on to narrow ticket QA.

   **Sitewide duplicate-content pass**: compare main-content text across same-template pages
   (location, service, sector, product pages) with place and entity names masked; flag pairs
   at or above ~90% similarity (`similarity.py`). Pages under 150 words or client-rendered are
   `inconclusive`, never duplicates. Method: `references/content-checks.md`.

   **Copy and freshness pass** (`copy_freshness.py`, then human review): stale dates,
   quarters and years; timezone labels wrong for the season (pass the site's zone with
   `--timezone`; without it the check does not run and the output says so); lorem or the same filler sentence repeated; names, places, phone/email and
   numbers ("N+ years", founding year) inconsistent across pages; title vs URL slug mismatch;
   mobile vs desktop copy or offer differences (rendered text parity from
   `viewport_overflow.js`; the class-based check is a Tailwind-only heuristic). Method:
   `references/content-checks.md`.

   **Leftover dev artefacts** (`dev_artefacts.js`): debug/test elements and test labels in
   the rendered DOM (visible or hidden, served or script-injected), console and page errors,
   failed requests, exposed source maps (one GET per same-origin asset plus one per in-scope
   map; the `SourceMap` header is read when present). Method: `references/content-checks.md`.

   **Marketplace / classifieds competitive search branch** (mandatory when the target is a
   marketplace, classifieds platform, multi-vendor catalogue or category-led inventory
   site): start from actual Google search-result rivals, not only famous category peers.
   Separate broad marketplaces, local category specialists, international platforms, and
   auctions / immediate-sale alternatives. Collect visibility estimates, ranked terms,
   overlap/gaps, linking-site summaries, trend direction and AI-source evidence where public
   tools and budget allow (paid data needs the user's approval). Build a stock-depth versus
   search-opportunity matrix; never invent search volume. Keep client-facing language
   provider-neutral; label estimates; cache raw evidence under the run's `evidence/`; list
   access-limited follow-ups (analytics, Search Console, server logs, CMS admin, backups,
   WAF). Full method: `references/marketplace-competitive-search-pass.md` in this skill folder.
8. **Security / privacy hygiene (passive only)**: TLS, redirects, security headers, exposed
   paths (.env/.git/backups/debug logs/directory listings) checked by a single plain GET,
   platform+plugin disclosure, safe REST/user-enumeration checks, mixed content (from
   `dev_artefacts.js`/`consent_capture.js` `mixedContent` and the console), consent behaviour
   and tracking before consent, consistency between banner, cookie policy, privacy processor
   list, runtime network destinations and config. Flag stale vendors and cross-brand
   copy/colour contamination. Never brute force, fuzz, exploit or run invasive scanners.

   **Pre/post-consent capture** (`consent_capture.js`, widths 375 and 1366): per width, a fresh
   profile records cookies, local/session storage, network destinations and Consent Mode
   `gcs`/`gcd` signals before any interaction; then clicks only the banner's Accept control,
   loads the page afresh and records again. A second fresh profile does the same with the Reject control and
   records whether Reject is honoured (`rejectHonoured`: no new trackers and no analytics/ads
   cookies set after Reject; trackers already there before any click are the pre-consent
   finding). One click per profile, only inside a positively
   identified consent container. Compare every new vendor with the privacy/cookie policy. Note
   first-party-proxied analytics (identified by cookie names, not hosts). Record the egress
   country. Rate with the **severity mapping** in the reference (pre-consent identifiers to ad
   vendors = S1 privacy exposure; cookieless Consent Mode pings = S4). Token-like values are
   redacted in output; never copy raw IDs into the report. No Accept (or Reject) control found:
   that item is `blocked`. Executor adds the consent-withdrawal check. Method:
   `references/consent-and-privacy.md`.
9. **CMS / code review (when scoped)**: content model fit, editor usability, field
   groups/blocks/components, menus, media; templates, hooks, endpoints, theme/plugin
   structure vs project conventions. Look, don't save: CMS admin is view-only. Editor-side UX
   reported separately from front-end defects. Stack-specific assertions are adapter
   examples for that stack, not universal rules. Findings use dimension `cms-code`.
10. **Synthesis (QA lead)**: report per qa-standards section 7 (verdict by rule,
    coverage table with per-item status, findings in defect format, improvement
    opportunities separate, evidence index, regression vs previous run, next steps), plus
    audit extras: UX narrative, one section per scoring dimension (functional QA / UX /
    accessibility / performance / search & AI / security & privacy / content / CMS & code when
    in scope) and a priority roadmap (quick wins, next sprint, later).

    - **findings.json** every run (`findings.py template` / `check`): stable finding IDs,
      a required `rule` key per finding and a fingerprint, a `coverage` entry per dimension
      (`executed | partial | blocked | not-in-scope | not-executed`) and a `checks_run` list
      (rule + template [+ url]) so later runs can be compared. Schema and fingerprint rules:
      `references/findings-and-regression.md`.
    - **Regression mode**: if an earlier run for the same host exists under
      `$QA_RUNS/`, run `findings.py diff` and report **fixed / still open / new /
      not re-tested / won't fix / accepted risk**. A finding missing this run is "fixed" only
      when its rule + template is in this run's `checks_run` (and, for a `scope: page`
      finding, a check on the same URL path); otherwise it is "not re-tested".
    - **Screenshots are embedded.** Every visual finding in `report.md` shows its
      screenshot directly under it, and each visual issue among the top issues in `summary.md`
      carries one
      (qa-standards section 5). Run qa-standards `scripts/report_check.py` on both files,
      and export any PDF with `scripts/report_export.py`, which verifies the images made it in.
    - **Client-ready one-pager** (`summary.md`, on top of the full report): verdict, a
      0-10 score per dimension using the rubric in `references/scoring-rubric.md`
      (`findings.py score` gives the arithmetic: blocked, not-in-scope, unrecorded or
      no-checks-recorded dimensions print "not scored", partly covered ones and those with
      not-re-tested findings are capped at 8 with a note; accepted-risk and won't-fix findings
      still count; the lead may adjust
      a score by at most 1 point with a stated reason), the top 3-5 issues in plain words
      (verified findings, or marked "(unconfirmed)"), quick wins, and what was not covered.
      No jargon, no hype, no unsupported claims.

## Scripts (lead-side, headless, read-only)

`<skill-dir>` below is the folder holding this SKILL.md. Run the scripts from the run folder,
so output lands in its `evidence/` (the default `--out` paths are `evidence/<name>.json`).
All take a URL list (a file with one URL per line, or a comma-separated list; http(s) only)
and write JSON after every URL, so a crash keeps finished results. Every script has `--help`
(works without dependencies), rejects unknown or invalid options, and exits **0** when every
URL was done, **1** on partial failure (failed URLs are listed in the output) and **2** on a
usage or dependency error (a missing package or no Chrome binary is caught before any URL is
loaded).

**Navigation guard (browser scripts).** A loaded page runs as it would for any visitor: its
own sub-requests, including third-party and POST beacons, are recorded and never blocked,
because the consent pass measures them. Two things are blocked and listed in
`blockedNavigations`: any page navigation that is not a GET (a backstop against a POST form
submission; a page's script can still send data in the background or through a GET form, as
it could for any visitor), and a navigation of the page itself to a host outside the input URL hosts
(www/apex twins of a domain count as the same site; IP addresses have no twin). A blocked
navigation is never sent: the script answers it locally with an empty response, so the page
under test stays in place and is still the thing measured. An off-scope
navigation makes that URL a failure. A page that never goes network-idle is still accepted
only if its main document returned a good status and an HTML type.

Setup: Node 22.12+ and `puppeteer-core` 25. Node scripts need `puppeteer-core` (not full puppeteer) and a
Chrome/Chromium binary (`CHROME_PATH`; the default is Google Chrome's standard path on macOS or Linux). Use an existing
install via `NODE_PATH` (e.g. a scratch tools folder's `node_modules`). **Never run `npm` inside
the skill folder** (its `package.json` is a dependency note only); a new `npm install` in a
scratch tools folder counts as an install and needs the user's approval
mid-audit. Python scripts need Python 3.9+, `requests`, `beautifulsoup4` and `lxml`. A missing
dependency means: mark that check `blocked`, carry on.

Evidence hygiene (built into the scripts; keep it when adding checks): every URL written to
evidence has no query string or fragment (exact URLs are used only in memory); console text,
DOM hits, parity lines, titles, clicked labels, cookie/storage names and snippets are redacted
(emails, long tokens, and recognisable key formats such as `sk-…`, `ghp_…` and JWTs) before
they are cut to length; the same redaction is applied to URL paths, and response headers are
stored only as a normalised media type; the scripts' own GETs never follow a
redirect off the input-URL hosts (www/apex twins included); only role email
addresses (info@, hello@ …) are stored, personal ones are counted; source maps on hosts outside
the input URL hosts (or their www/apex twins) are not fetched (`skipped (off-scope)`); the Python fetcher ignores netrc
and environment credentials. A `--cache` folder is the exception: it holds raw
fetched pages and exact URLs, is working data and not evidence, and is never shared or
attached to a report.

| Script | Pass | Inputs | Usage |
|---|---|---|---|
| `viewport_overflow.js` | 1, 3, 4 | one representative URL per template + home + highest-intent page | `node <skill-dir>/scripts/viewport_overflow.js urls.txt [--viewports 320,375,768,1024,1440] [--shots screenshots/vp] [--cta REGEX] [--delay 800] [--no-mobile] [--reduced-motion] [--no-scroll] [--out evidence/overflow.json]` |
| `consent_capture.js` | 8 | home + highest-intent page (+ one per template if banners differ) | `node <skill-dir>/scripts/consent_capture.js urls.txt [--policy PRIVACY_URL] [--accept REGEX] [--reject REGEX] [--no-reject] [--width 375,1366] [--egress GB] [--delay 800] [--out evidence/consent.json]` |
| `dev_artefacts.js` | 7, 8 | the same representatives as the viewport matrix | `node <skill-dir>/scripts/dev_artefacts.js urls.txt [--width 1366] [--delay 1000] [--timeout 15000] [--max-bytes 5000000] [--cache cache] [--out evidence/artefacts.json]` |
| `similarity.py` | 7 | one run per same-template group (all its sitemap URLs) | `python3 <skill-dir>/scripts/similarity.py urls.txt [--mask "Town A,Town B"] [--mask-file F] [--threshold 0.9] [--min-words 150] [--rendered evidence/overflow.json] [--max-pages 200] [--max-chars 6000] [--time-budget 120] [--cache cache] [--delay 0.5] [--out evidence/similarity.json]` |
| `copy_freshness.py` | 7 | all sitemap URLs (default cap 500; raise with `--max-pages`, use `--cache`) | `python3 <skill-dir>/scripts/copy_freshness.py urls.txt [--today YYYY-MM-DD] [--timezone Europe/London] [--rendered evidence/overflow.json] [--max-pages 500] [--cache cache] [--delay 0.5] [--out evidence/copy.json]` |
| `findings.py` | 10 | the run's findings.json | `python3 <skill-dir>/scripts/findings.py template\|check F\|score F\|diff F [--previous OLD] [--runs-root DIR] [--out regression.md]` |

Large sites: cap each script run at the representatives above (browser scripts) or one
template group / the `--max-pages` cap (Python scripts), and record any cap in the coverage
table.

Script output is evidence for the lead to judge, not a finding list: every hit is reviewed
(see the false-positive list in `references/capture-discipline.md` and the default
severities in `references/scoring-rubric.md`) before it is rated.

## Tracker filing

Draft review outputs first and show the user. Only with their approval: one run-record issue
per audit (charter, verdict, report); every confirmed S1-S3 gets its own linked issue.
Neutral titles; no credentials or customer personal data in the tracker, ever.
