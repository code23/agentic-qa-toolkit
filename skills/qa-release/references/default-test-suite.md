# Default deterministic test suite (four tiers)

The pack is deterministic regression protection; the qa- skills are human-POV discovery.
They complement each other. Automatable findings from QA runs get promoted into the pack. Stack-specific assertions
(one framework, one payment provider) are adapter examples, not universal rules.

## Tier 1 - Unit/integration (e.g. Vitest), per workspace
Business logic, helpers, API handlers. Invariants that must each have named tests (a high
file count proves nothing):
- **Tenant isolation**: cross-company access denied at the API layer.
- **Role boundaries**: authorization edges between each role (e.g. customer, staff, admin).
- **Financial state machine**: order/refund transitions, idempotency, concurrent checkout/refund.
- **Provider negative paths**: payment webhook signature REJECTION, duplicate delivery,
  event reordering (fixture-based, no live calls); email assertions via captured transport
  (recipient class, template, links; nothing sends).
- **Migration deployability**: apply migrations to an empty DB AND a previous-release schema
  fixture, then run representative reads/writes.
- **Guards**: no live payment key can reach the e2e env; route JS/asset-size budgets gate in
  CI (Lighthouse lab scores are tracked, not gating; lab does not measure real-user INP).
- **Dev-passes-prod-fails source guards**: no inline `<style>` ELEMENTS in components (a
  production nonce CSP drops them while dev allows them); no web-app path aliases on
  worker-reachable modules (worker runtime can't resolve them, boot crash); a config module
  that parses a schema at load has a unit test that imports it. Pattern: when a bug only
  appears in a production build, add the deterministic source guard that would have caught it.
- **Cross-brand global UI guard**: root-level overlays and global chrome use the active
  brand/theme contract, not hard-coded colours, fonts or copied vendor text; a consent
  banner outside the normal theme scope must establish the active brand scope explicitly.

## Tier 2 - E2E critical journeys (e.g. Playwright)
The reasons the site exists, one spec each: signup/auth - browse/search - enquiry or checkout
(payment provider TEST mode only) - admin core journey - webhook/refund paths where money
moves. Drive paths, heading matchers, CTA names and seed slugs from a data-driven pack
config (`playwright-templates/qa.pack.ts`). Rule: don't weaken assertions or drop journeys;
update the pack when the product surface changes. Pre-existing drift may be parked with a
time-boxed `test.fixme` + ticket, never silently skipped.

## Tier 3 - Rendering + accessibility guarantees (Playwright templates in `playwright-templates/`)
Run against a production-mode build, desktop Chromium + one mobile viewport minimum. This
tier guards app-level hiding (reveal animations, hydration); optimizer/CDN failures only
exist live (tier 4).
- **No-interaction first paint** (`no-interaction-first-paint.spec.ts`): load each key
  template with ZERO input, wait for `load`, assert primary content visible, **re-assert
  after a 2s settle**, plus a computed visibility/opacity check (Playwright treats
  `opacity:0` as visible) and a named-CTA-in-main check.
- **Accessibility smoke** (`a11y-smoke.spec.ts`, pinned @axe-core/playwright): fails on NEW
  serious/critical violations; third-party roots excluded and ticketed ids allowlisted in
  `qa.pack.ts` (shrink-only). Evidence, **not WCAG certification**.
- **Global chrome geometry + theme** (`global-chrome.spec.ts`): clean context; a
  content/legal page and the highest-intent page minimum; fixed/sticky headers don't
  intersect breadcrumbs, H1 or first control; capture top-of-page, scrolled-header,
  mobile-menu and footer evidence; first-visit consent banner visible, not obscuring the
  primary action, styles resolve from active brand tokens. A merge gate, not an optional snapshot.

## Tier 4 - Production monitoring (opt-in only, set up only when the site owner explicitly asks)
Anonymous, read-only checks against LIVE sites: first-paint spec, public browse,
HTML-200 + primary-text-non-empty probe, public-page contract (status, title, canonical,
robots/noindex, Open Graph, server-rendered primary content). **No logins, no checkout, no
writes, ever.** Money/auth journey smoke only against staging/preview in test mode.
Pick the interval from the detection time you can accept: a nightly check means up to 24
hours before anyone knows. Ops policy ideas: 2 in-run retries; a confirmed first-paint red is "site down"; dedupe
known-reds and send recovery notices; a dead-man check alerts if the monitor itself stops.
(Scheduling and alert channels are out of scope for this skill; creating one is a separate,
user-approved setup.)

## Rules
- CI gates on tiers 1-3: red suite = no merge. A test command that runs nothing counts as "no suite".
- **Dev is not prod**: visual/rendering sign-off is against a production-mode build. A green
  build is necessary but not sufficient; the build must be viewed or smoke-checked. A
  production build is part of the merge gate for any change touching rendering or
  configuration read at start-up, not only typecheck and unit tests.
- **Conformance is re-verified, not assumed**: branch protection on, workflows actually
  trigger, test discovery non-zero, latest default-branch run green. Check on a schedule.
- Every new template/page type joins the first-paint and a11y lists in the same PR; every
  new global shell, sticky element, breadcrumb wrapper or root overlay joins
  `global-chrome.spec.ts` in that PR.
- Test data: named test accounts and seeded fixtures only; never real customer data;
  payment specs only in provider test mode.
