---
name: qa-release
description: Use for the deepest pre-release QA programme on a web product - "release QA", "test everything", "full app audit", "every route and role", "pre-launch hardening" - inventorying routes, roles, APIs, state machines and providers, running deterministic and real-browser coverage, recording a coverage matrix and defect register, and issuing an evidence-backed release verdict. Audit-only by default. For broad read-only site audits use qa-site-audit instead.
---

> Setup: read `environment.md` in the `qa-standards` skill folder first. It says how the browser is driven on this setup, where run folders live (`$QA_RUNS`) and what this setup cannot do.

# QA release

Run an auditable release-candidate programme, not one large browser walkthrough. Compose the
existing QA, browser and deterministic-test tooling; do not duplicate or weaken their controls.

## Load the operating standards

Read these completely before acting:
1. The `qa-standards` skill (taxonomy, defect format, evidence, verdict rules).
2. The `qa-site-audit` skill (passes and the executor preamble for browser chunks).
3. `references/default-test-suite.md` in this skill folder (deterministic four-tier pack;
   Playwright templates in `references/playwright-templates/`).

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
- Release-QA specific: stateful or money-moving journeys are NOT executed through the live
  UI. Walk them up to the last non-destructive step, then cover the mutation with
  deterministic tests/fixtures or read-only inspection, and mark the live step
  `blocked (safety rule)`.

## Select the mode without widening authority

- **audit-only** (default): discover, reproduce, evidence, report and draft defects. No
  application-code changes and no external mutations.
- **audit-and-repair**: only when the user explicitly asks to fix/harden/repair. Each
  coherent confirmed defect goes through a fix on a branch or worktree, the repo's checks
  and an independent review by a different reviewer than the author. Merging, deploying
  (even to a sandbox), and pushing or opening PRs each need the user's explicit approval.

The skill never authorises production writes, live money, destructive actions, installs,
messages, publishing, secrets access, merges or deploys. Record each boundary in the run manifest.

## Initialise a durable run

Draft a tracking record (charter, environment, verdict rule, scope). If the user keeps a
tracker and approves, file it there; otherwise keep it in the run folder. Then
initialise the local run folder with the helper in this skill folder:

```bash
python3 <skill-folder>/scripts/release_qa_run.py init \
  --project '<project>' --target '<URL>' --environment '<sandbox/staging/preview>' \
  --mode '<audit-only|audit-and-repair>' [--repo '<abs repo path>'] [--tracking-issue '<id>']
```

Default output is `$QA_RUNS/<project>-<date>/` (with briefs/, evidence/, logs/,
receipts/, screenshots/, charter.md, coverage.csv, defects.md, report.md, manifest.json,
checkpoints.jsonl). It refuses to overwrite an existing run. If the script is not present,
create the same layout by hand from the templates in `assets/`.

Complete `charter.md` and the manifest `authority` fields (safe_test_mutations,
sandbox_provider, money_cap, merge, deploy, production_writes=false) and `top_risks` before
any stateful test. Checkpoint after each phase:

```bash
python3 <skill-folder>/scripts/release_qa_run.py checkpoint --run '<run-dir>' \
  --phase '<phase>' --status '<in_progress|completed|blocked>' --next '<exact next action>'
```

## Define coverage precisely

"Every route and possibility" means an explicit, reviewable surface inventory plus risk-based
equivalence classes; never an infinite-input or bug-absence claim.

Populate `coverage.csv` (columns: id, layer, surface, role, state_or_case, risk, oracle,
execution, verification, evidence, defect, notes) before deep execution. Inventory:
- public, authenticated, admin and tenant-specific UI routes;
- API routes, server actions, webhooks, cron jobs, queues and worker entry points;
- roles, organisations/tenants and direct-object boundaries;
- critical journeys and their state machines;
- provider integrations, retries, idempotency keys and reconciliation paths;
- database records, ledgers, audit logs and other durable side effects;
- global chrome, responsive templates, first paint, accessibility and legal surfaces;
- deployment, migration, configuration-at-load and observability paths.

Every item gets one final execution status: `executed`, `blocked`, `not_applicable`,
`not_reachable` or `not_executed` (`planned` only while in progress). Verification:
`independently-reproduced`, `evidence-reviewed`, `provisional` or blank. Never omit an item
because it was inconvenient. Map every top charter risk to at least one coverage row.

## Execute the programme

### Phase 0 - authority and baseline
1. Record repo/branch/dirty-worktree ownership (if a repo is in scope), deployed build,
   environment, test accounts, fixtures, provider mode, cleanup, rollback, money cap (should
   be zero for UI work) and permitted actions.
2. Confirm the environment is not production, that it cannot reach production credentials
   or customer data, and that the test account is not a real customer's or the user's own.
3. Sanity-check the browser (open a known public page, one screenshot) before browser work.
4. Capture the starting state of anything you will later inspect (read-only).

### Phase 1 - surface and risk model
Build the route/role/action/state/provider inventory from repo structure, runtime navigation,
schemas, jobs and product specs. Identify why the product exists and the failure classes that
could cause wrong money, data loss, privilege leakage, stranded state or invisible first
paint. Use the implementation as a discovery source, not the sole oracle. Record missing
product decisions instead of inventing behaviour.

### Phase 2 - deterministic baseline (when a repo is available on the lead machine)
Run the configured lint, type, unit/integration, migration, security, production build,
rendering/accessibility and journey suites in batched commands. Verify non-zero test
discovery and inspect skipped/fixme coverage. Exercise an empty database and a
previous-release schema when migrations are in scope (local/test databases only).
Production-mode rendering checks only; a dev screenshot or green compile is not release
evidence. Propose promoting automatable defect classes into regression tests (see
`references/default-test-suite.md`). No repo: mark this phase `not_reachable`.

### Phase 3 - live happy paths
Use the executor (per `environment.md`) for human-POV journeys with
briefs per qa-standards section 8, one flow or coherent page group per job, the
dedicated test account, every screenshot inspected, severity assigned by the lead.
For each stateful journey:
1. Record the pre-state.
2. Walk to the last non-destructive step (open and cancel; never submit, pay, send,
   invite, delete). Signup/sign-in/verification/onboarding with test data is allowed.
3. Assert the UI outcome.
4. Where read access exists, assert source-of-truth state read-only (DB rows, state
   transitions, ledgers, audit entries, emitted jobs). Otherwise cover via deterministic tests.
5. Record cleanup or the intentionally retained test fixture.

### Phase 4 - negative and hostile paths
Adapt to the product:
- invalid, boundary, empty, loading, back/refresh and abandoned-flow behaviour;
- duplicate submission, retry, timeout, replay and idempotency;
- concurrent actions, row-lock/claim races and cron overlap;
- out-of-order, duplicated, missing and contradictory provider events;
- crash windows between durable state and enqueue/provider calls;
- refund/cancellation/return/dispute and partial-success recovery;
- role, tenant and direct-object isolation at UI and server boundaries;
- stale sessions, revoked permissions and configuration drift;
- mobile/responsive, keyboard/focus, global chrome and no-interaction first paint.
Destructive, expensive or submitting cases are covered with fixtures and deterministic tests
only, never through the live UI.

### Phase 5 - findings and repair loops
Apply the S1-S4 taxonomy and defect format. Independently reproduce S1/S2 where safe. Put
every finding in `defects.md`; draft every confirmed S1-S3 as its own tracker issue linked to
the run record and file only with the user's approval; S4 and improvements stay in the run record.

In audit-and-repair mode (user-requested only), one coherent defect at a time:
```
fix on a branch or worktree -> the repo's deterministic checks -> independent review
(a different reviewer than the author; release repairs count as risky) -> repair if needed
-> green CI -> [user approval] sandbox deploy -> live regression -> evidence/status update
```
Preserve authorship and user-owned uncommitted changes. The author never approves its own
fix; if no independent reviewer is available, hold the change and say so. Keep other audit
lanes going when one defect is blocked; never silently narrow the programme.

### Phase 6 - system regression and release verdict
After the last repair (or at the end of audit-only), rerun: every affected journey and
invariant; the full configured repo gates; global chrome and critical public/account shells
in production mode; the highest-risk cross-feature sequence; reconciliation and background
workers where readable; all previously open S1/S2 reproductions.

Validate the run folder:
```bash
python3 <skill-folder>/scripts/release_qa_run.py validate --run '<run-dir>' --final
```
Verdict rule: any open S1/S2 or any top risk with zero executed coverage means `FAIL`
(allowed verdicts: PASS, PASS WITH CONDITIONS, FAIL, INCONCLUSIVE, each optionally followed
by a scope note in brackets; where `environment.md` caps the verdict, its PREFLIGHT lines
replace PASS and PASS WITH CONDITIONS). State blocked and
unexecuted coverage explicitly. Never say "all bugs are fixed"; say what was inventoried,
executed, blocked and excluded.

## Close the run
1. Show the user the consolidated report and the drafted issue updates; file only with approval.
2. Record environment actions, any money movement, accepted risks, rollback and remaining
   human decisions.
3. If a release blocker remains, say so; the tracking record stays open.
4. Close only browser sessions/tabs created by this run; delete any brief file that held credentials.

Visual findings embed their screenshots directly under the finding (qa-standards section
5). Run the qa-standards `scripts/report_check.py` on the report, and make any PDF or HTML
export with `scripts/report_export.py`, which verifies the images are in it.

The report (`assets/report.md` shape) must contain: charter, verdict, coverage table,
severity-ranked defect register, journey and invariant evidence, environment actions,
regression results, explicit limits and the exact release path.
