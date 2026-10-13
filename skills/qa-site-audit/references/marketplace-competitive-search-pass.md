# Marketplace competitive search pass

Mandatory companion to the SEO / schema / AI-search visibility pass in
[`../SKILL.md`](../SKILL.md) when the target is a marketplace, classifieds
platform, multi-vendor catalogue, or category-led inventory site.

This pass does **not** replace the S1 to S4 severity taxonomy, defect format,
evidence rules or verdict rules from the `qa-standards` skill. It adds an
evidence-led competition branch so reports stop comparing only famous
category peers and start from the rivals that actually appear in search.

## When it is mandatory

Run this branch for:

- multi-seller marketplaces
- classifieds / inventory platforms
- catalogue sites that compete in Google for buying intent
- any audit where growth, SEO, category wedges or competitor positioning is in
  the client-facing story

Skip only when the user explicitly scopes the audit as non-competitive (for
example pure accessibility or security hygiene on an internal tool).

## Core rule

**Start from actual Google search-result competitors, not only famous category
peers.**

The famous global platforms in the target's sector may
still matter as scale or brand benchmarks. They are not automatic proof of who
wins the buyer's search for each category.

## Competitor taxonomy (always separate)

Label rivals into at least these buckets:

1. **Broad marketplaces** - horizontal consumer or commercial platforms that
   list everything, including the target's categories.
2. **Local category specialists** - niche sites in the target's own market
   that win individual category searches.
3. **International sector platforms** - cross-border catalogue players in the
   target's sector.
4. **Auctions and immediate-sale alternatives** - auction houses, timed sales,
   and instant-purchase routes.

Do not collapse these into one generic "competitors" table.

## What to collect

Where public tools and budget allow, collect and cache:

| Evidence | Purpose | Client-facing language |
|---|---|---|
| Target visibility estimate (keywords, estimated visits, positions 1 to 10) | Direction of organic return | "Independent public search estimate" / "third-party estimate" |
| Ranked terms and URL mapping | What currently earns attention | Same; never present as Search Console fact |
| Sampled high-intent Google results (category buy/sell queries) | Who actually appears | "Public search sample" / "sampled Google search results" |
| Overlap and gaps vs rivals | Where the target is absent | Label sample limits |
| Linking-site summary (backlinks, websites linking in) | Authority / referral shape | "Websites linking to the platform"; estimate label |
| Trend direction if available | Up / down / new terms | Estimate only |
| AI-source / AI-mention evidence if available | AI search visibility signal | Careful caveats; never claim sitewide AI dominance |
| Public real-user speed data (CrUX / field) where available | Pair with lab Lighthouse | "Real-user speed data"; lab remains lab |
| Stock-depth versus search-opportunity matrix | Commercial prioritisation | Mix verified stock counts with labelled judgement |

### Stock-depth versus search-opportunity matrix

Build a practical matrix with columns such as:

- category
- observed stock depth (sitemap or catalogue evidence)
- sampled search position (including "not seen in sampled top 10 / top 30")
- competitive shape (which bucket wins)
- recommended next move (clearly labelled judgement)

Include positive controls when a focused category already wins. If a large
stock group was not in the search sample, say so and require demand validation
before prioritisation. **Do not invent search volume.**

## Method notes

1. Choose a small set of high-intent, category-specific queries (buyer and, if
   relevant, seller queries). Prefer market-local wording when the client
   sells locally.
2. Record top-ten (and, if cheap, top-thirty) organic domains per query.
3. Count frequency across the sample so the report can show which brands recur
   versus which specialists win once.
4. Capture the target's own best rankings separately from the intentional
   sample so navigational or outlier wins are not mistaken for broad demand.
5. Deduplicate AI-source / AI-overview reference records carefully. Present as
   "N sampled search terms where a page was used as a source in an AI-generated
   Google result", not as a live sitewide guarantee.
6. Pair lab performance with public real-user speed data when available. Lab
   failures still stand; field data changes confidence, not the need for a
   performance budget.
7. Cache raw provider payloads internally under the run's `evidence/` folder.
   Client-facing material must stay provider-neutral.

## Cost gates

Respect budget. Prefer high-signal samples over exhaustive dumps.

**Do by default**

- bounded keyword / rank overview for the target
- 8 to 15 high-intent category queries with top-ten capture
- compact linking-site summary
- AI-source mentions if already in the keyword payload or cheap to retrieve
- one stock-versus-opportunity matrix grounded in current evidence

**Skip or defer unless the user approves extra spend**

- low-value bulk backlink dumps
- repeated generic technology scans already covered by on-page detection
- exhaustive competitor rank tracking across hundreds of keywords
- paid crawl models whose broken-page totals cannot be validated without
  Search Console / server logs

If a cost gate forces a skip, say so in the report and list the follow-up.

## Client-facing language rules

- Keep client-facing material provider-neutral: do not name the SEO data vendor.
- Prefer: "independent public search estimate", "public search sample",
  "third-party estimate".
- Rewrite jargon into plain business English:
  - Google search results (not SERP)
  - main content load time (LCP may appear once in a compact technical note)
  - initial server response (not TTFB as unexplained jargon)
  - websites linking to the platform (not referring domains alone)
  - AI search visibility (not AEO / GEO as unexplained jargon)
  - page information supplied to search engines (schema / structured data in a
    compact technical appendix or finding detail only)
  - real-user speed data (not unexplained CWV)
- Keep confidence labels: Verified, Third-party estimate, Strategic inference.
- State clearly that the audit was public and read-only, not a penetration
  test, and not based on client analytics or Search Console unless those were
  explicitly scoped.

## Access-limited follow-up checks

Mark these blocked until authorised access exists:

- analytics and conversion events
- Search Console queries, pages, experience and indexing reports
- server logs / origin health
- CMS admin (plugins, feeds, imports, users, debug settings)
- backups and proven restore
- WAF / bot / CDN configuration beyond public headers
- authenticated seller journeys, billing and renewal behaviour

Do not invent first-party metrics to fill the gap. Keep third-party estimates
labelled and replace them when access arrives.

## Report expectations

A marketplace audit report should include:

1. Evidence-led competitor section using the four-bucket taxonomy.
2. Visual or tabular frequency of sampled top-ten rivals.
3. Stock-depth versus search-opportunity matrix with caveats.
4. AI search visibility callout only when evidence exists, carefully limited.
5. Provider-neutral wording throughout client-facing surfaces.
6. Internal raw evidence retained for challenge and re-run.

## Re-run checklist (short)

- [ ] High-intent query sample captured and cached
- [ ] Top-ten domains counted and bucketed
- [ ] Target best-rank outliers separated from broad-demand sample
- [ ] Visibility / linking-site estimates labelled third-party
- [ ] Matrix built without invented volumes
- [ ] AI-source mentions deduplicated and caveated
- [ ] Lab + public real-user speed data paired when available
- [ ] Cost-gated skips recorded
- [ ] Access-limited follow-ups listed
- [ ] Client copy has no vendor names or unexplained jargon
