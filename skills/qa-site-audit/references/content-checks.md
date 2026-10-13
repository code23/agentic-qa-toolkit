# Content checks: duplicates, copy/freshness, dev artefacts

All three checks are polite: one page at a time, a delay between requests (0.5 s minimum for
the Python scripts, 1 s default for `dev_artefacts.js`'s own GETs), a tagged user agent, a
timeout and size cap on every fetch, and an optional `--cache DIR` so reruns fetch nothing
new. Each URL gets a status record (HTTP status, final URL, redirects, content type, error);
failed URLs are listed and the script exits 1. The header charset is honoured quoted or bare
(`charset="shift_jis"`), then `<meta charset>`, then UTF-8. Evidence URLs carry no query
string, and snippets and titles are redacted (personal emails, token-like strings) before
they are cut to length.

**Served HTML only (Python scripts).** `similarity.py` and `copy_freshness.py` read the HTML
the server sends, not the rendered page. Run the served-vs-rendered preflight (pass 1): give
them `--rendered evidence/overflow.json` from `viewport_overflow.js`. A page whose served text
is under 70% of its rendered text, or that looks like an empty app shell (few words plus a
`#root`/`#__next`/`#app` mount or many scripts), gets `coverage: limited (client-rendered)`.
Its results are not evidence of "clean" or "duplicate"; say so in the coverage table.

## Duplicate content (`similarity.py`)

- Input: same-template pages. Location, service, sector and product pages are the usual
  suspects. Comparing across templates is noise.
- Main text comes from `<main>` (or `[role=main]`). With no `<main>`, it uses `<body>` with
  `header`, `nav`, `footer` and `aside` removed. Script, style, svg, noscript, dialog and
  template elements are stripped. Each page records `root` (`main`/`body`) and `words`.
- **Mask entity names** (`--mask` or `--mask-file`): town and region names, client names,
  product names. Otherwise "web design in Town A" and "web design in Town B" look different
  when they are the same page.
- Pairs where either page has fewer than `--min-words` (default 150) words, or is
  client-rendered, are `inconclusive` and never flagged.
- Other pairs get 5-word shingle Jaccard. Pairs within 0.2 of the threshold also get a
  SequenceMatcher ratio, and a pair is flagged when either score reaches the threshold
  (default 0.90; compared unrounded). The ratio is slow on long text, so it is bounded: if
  either page's text is longer than `--max-chars` (default 6000) it is not run, the pair is
  marked `seq_limited` and the decision uses the full-text Jaccard only (`decided_on`). The
  comparison phase also has a `--time-budget` (default 120 s); pairs it does not reach are
  `skipped (time budget)` and the exit code is 1. URLs whose exact final URL (query string included) is the same are recorded
  as aliases, not compared; `/product?id=1` and `/product?id=2` are different pages. Evidence
  URLs are written without query strings.
- The JSON is checkpointed after every URL (`"complete": false`, pairs `"pending"`), so an
  interrupted run keeps the pages it fetched.
- Reading it:
  - ≥ 0.90: near-duplicate. This is a thin/doorway content risk for SEO and AI answers.
  - 0.6–0.9: a shared template with some unique copy. Usually fine.
- When most pages in a group are near-duplicates, the lowest-scoring page usually has the
  genuinely local copy. Point to it as the model for the others.

## Copy and freshness (`copy_freshness.py`)

Flags, each reviewed by a human before rating:

| Flag | Meaning |
|---|---|
| `stale-quarter` | "Qn YYYY" earlier than the current quarter; or a bare "Qn" earlier than the current quarter with no forward-looking word nearby |
| `quarter-ambiguous` | A bare "Qn" earlier than the current quarter next to a forward-looking word (booking, from, starting, next, available…). In Q4, "booking Q1" usually means next year |
| `old-year` | "as of / updated / last updated / reviewed / last reviewed" + an optional day/month + a year two or more years old. Plain "in 2019" or "for 2019" is not flagged (too often historical). Ignore it in dated posts and case studies |
| `copyright-year` | "©", "(c)" or "Copyright" + a year, or a range, whose **end** year is before this year ("© 2019–2026" is fine) |
| `timezone-label` | Runs only with `--timezone <IANA name>` (for example `Europe/London`, `America/New_York`, `Australia/Sydney`). Flags the out-of-season abbreviation: GMT shown while London is on BST, EST while New York is on EDT. Without the option the output says `not run`; a zone with no daylight saving reports `not applicable`. Abbreviations that are also English words only count next to a clock time |
| `placeholder` | lorem ipsum, TODO, TBC, FIXME, "placeholder", "[placeholder]", xxx, "coming soon", "insert text/copy here" |
| `repeated-sentence` | The same block (30+ characters) 3 or more times on one page. Each occurrence counts once (`<p><span>…</span></p>` is one), and blocks that are or sit inside `aria-hidden="true"` are excluded. Usually filler pasted into several sections |
| `title-slug-mismatch` | Title vs URL slug word overlap ≤ 0.5. Usually a renamed post that kept its old slug |
| `breakpoint-copy-differs` | **Tailwind-class heuristic only**: inside `<main>`, blocks hidden at one breakpoint via `sm:/md:/lg:hidden` or `hidden md:block` say different things. Finds nothing on other CSS systems; use the `parity` output of `viewport_overflow.js` as the main method |

Cross-page variants are listed for the lead to check:
- phone numbers (national formats with a leading 0, plus any number written with a
  +country code; other national formats: check by hand)
- role email addresses (info@, hello@, sales@ …). Personal addresses are never stored; each
  page records only `personal_emails_seen` (a count), and context snippets show `<email>`
- founding year
- "N+ years / clients / projects" claims

Person names and spellings are checked by hand: scan the about, team, testimonial and
author pages. Typical finds:
- Two different "N+ years" claims on different pages.
- A name that runs into the next label because of missing spacing.
- A pricing page still selling a past quarter's availability.

## Dev artefacts (`dev_artefacts.js`)

- Rendered-DOM text and id/class hits, each recorded as visible or hidden, with `where`
  (`text` or `id/class`) and `inServedHtml` (a heuristic: text hits are searched as text,
  id/class hits as an attribute value in the served HTML; `null` when the served HTML
  couldn't be fetched):
  - debug
  - lorem ipsum
  - todo, fixme, xxx
  - "test" labels (test label/copy/content/page), placeholder text, dummy, asdf
  - staging, localhost, console.log
- `data-testid` / `data-test` / `data-cy` count. This is hygiene only, not a defect by itself.
- Console errors and warnings, page errors and failed requests (redacted: no query strings,
  emails or long tokens). A 404 page logging its own 404 is expected.
- `mixedContent`: http:// subresources on an https page (pass 8).
- Source maps: for same-origin JS and CSS, the `SourceMap` / `X-SourceMap` response header is
  read first (no extra request); otherwise one GET per asset reads the `sourceMappingURL`
  comment (resolved against the asset's final URL). Then **one status-only GET per map URL**
  (no body read; deduplicated across pages; every page that references it still lists it).
  Maps on hosts outside the input URL hosts (and their www/apex twins) are `skipped (off-scope)`. The script's own GETs
  follow at most 3 redirects by hand (the Python fetcher allows 5), each hop on an in-scope host; an off-scope hop is not
  fetched (`skipped (off-scope redirect)`). A public map that returns 200 exposes original
  source. Severity depends on what it contains.
- `ownFetchErrors`: the script's own GETs (asset, map probe, served HTML) that failed, were
  non-200, truncated or skipped. Any entry makes that page a partial failure (exit 1); its
  browser results are still written.
- `nonGetRequests`: POSTs and other non-GET requests the page's own JS made during the load,
  by method and host, for information only.
- Never probe guessed paths beyond the single-GET hygiene list in pass 8.

Conversion-path method: see `conversion-path.md`.
