# Field data (when available)

Field data shows what real users experience. Lab data (Lighthouse) shows one simulated load.
Show them side by side, per template where possible, and never blend them.

## Rules (the Safety-rules exception in SKILL.md, repeated)

Field data is the one narrow exception to "never use the user's own personal/admin account":

- Only via a **read-only connector the user explicitly grants for this run**. Nothing granted
  earlier carries over to a new run unless the user says so.
- **Aggregate reports only.**
- **Never open** session recordings or replays, person/user profiles, individual user data,
  or raw event streams or exports. **Never screenshot** them.
- **Never save, create or annotate anything**: no saved insights, dashboards, cohorts,
  annotations, notes, URL-inspection requests or exports.
- Never ask for, paste or store logins, API keys or tokens.
- No grant: mark `field data: blocked (no access)`. Grant but no data (e.g. CrUX has no
  record): `not available (insufficient traffic)`. Either way, keep every performance claim
  labelled "lab".

## Sources

| Source | What it gives | Access | Level |
|---|---|---|---|
| CrUX via PageSpeed Insights | p75 LCP, INP, CLS (28-day) | Keyless: the PSI web page, or the PSI v5 API called without a key (no CrUX API key, which would need one) | URL-level for well-trafficked URLs, otherwise origin-level; say which |
| Search Console | Core Web Vitals report, indexing, queries, CTR | A connector granted for this run | URL groups / origin |
| Product analytics (e.g. PostHog) | Web-vitals events, funnels, rage-click counts, device mix | A connector granted for this run; aggregate insights only | per URL pattern |
| Server or CDN analytics | Device and country mix, error rates | A connector granted for this run | origin |

## Where else it is used

- **Pass 7 (SEO)**: if Search Console is granted, cross-check the indexing exclusions
  ("Duplicate without user-selected canonical", "Crawled - not indexed", "Alternate page with
  proper canonical") and the chosen canonicals against the duplicate-content pass.
- **Pass 4 (conversion path)**: if product analytics is granted, funnel drop-off per template
  (aggregate only).

## Presenting it

| Template | Lab mobile perf (median of 3) | Lab LCP | Field p75 LCP | Field p75 INP | Field CLS | Level (url/origin) | Source / period |
|---|---|---|---|---|---|---|---|

Where lab and field disagree, say so plainly. For example, slow on simulated 4G but fine
for real visitors who are mostly on desktop.
