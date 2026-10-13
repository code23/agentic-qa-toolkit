#!/usr/bin/env python3
"""Sitewide duplicate-content pass (served HTML). Fetches each URL politely, takes <main> text (or <body> minus header/nav/
footer/aside), masks place/entity names, and compares every pair with 5-word shingle similarity (Jaccard) plus a
SequenceMatcher ratio on candidate pairs. Pairs at or above --threshold (default 0.90) are flagged as near-duplicates.

Pairs where either page has fewer than --min-words words, or looks client-rendered, are 'inconclusive', never flagged.
Each page records the root used, its word count and its coverage ('full' or 'limited (client-rendered)').
Pass --rendered evidence/overflow.json (from viewport_overflow.js) to compare served vs rendered word counts.
SequenceMatcher is quadratic, so it is bounded: when either text is longer than --max-chars (default 6000) it is not run at
all; the pair is marked seq_limited and decided on the full-text Jaccard alone. The whole comparison phase also has a time
budget (--time-budget, default 120 s): pairs not reached are recorded as "skipped (time budget)" and the exit code is 1.
Thresholds are compared on unrounded values.
The output is checkpointed after every URL (pairs: "pending" until all pages are fetched).

Run it per template group (e.g. all location pages), not across the whole site.
Exit: 0 done, 1 some URLs failed (output still written), 2 usage or dependency error.
"""
import argparse, itertools, json, math, re, difflib, sys, os, time

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('urls', help='file with one URL per line, or comma-separated URLs')
ap.add_argument('--mask', default='', help='comma-separated names to mask, e.g. "Reading,Oxford"')
ap.add_argument('--mask-file', help='file with one name to mask per line')
ap.add_argument('--threshold', type=float, default=0.90, help='flag at or above this similarity (0-1, default 0.90)')
ap.add_argument('--min-words', type=int, default=150, help='below this, a pair is inconclusive (default 150)')
ap.add_argument('--rendered', help='viewport_overflow.js JSON, for the served-vs-rendered preflight')
ap.add_argument('--out', default='evidence/similarity.json')
ap.add_argument('--cache', help='cache directory; reruns fetch nothing new')
ap.add_argument('--delay', type=float, default=0.5, help='seconds between requests (min 0.5)')
ap.add_argument('--max-pages', type=int, default=200, help='stop fetching after this many URLs (default 200)')
ap.add_argument('--max-chars', type=int, default=6000, help='longest text SequenceMatcher will compare; longer pairs use Jaccard only (default 6000)')
ap.add_argument('--time-budget', type=float, default=120, help='seconds allowed for the comparison phase; remaining pairs are skipped (default 120)')
a = ap.parse_args()
if not (math.isfinite(a.threshold) and 0 < a.threshold <= 1): ap.error('--threshold must be in (0, 1]')
if not (math.isfinite(a.delay) and a.delay >= 0.5): ap.error('--delay must be a number >= 0.5')
if not (math.isfinite(a.time_budget) and a.time_budget > 0): ap.error('--time-budget must be a number > 0')
if a.min_words < 1 or a.max_pages < 2 or a.max_chars < 1000: ap.error('--min-words >= 1, --max-pages >= 2, --max-chars >= 1000')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fetch import read_urls, fetch_page, main_text, csr_hint, rendered_words, coverage, write_json, safe_url, allowed_hosts_for

urls = read_urls(a.urls, ap.error)
allowed = allowed_hosts_for(urls)   # redirects are only followed between the input URLs' hosts (and their www/apex twins)
names = [n.strip() for n in a.mask.split(',') if n.strip()]
if a.mask_file: names += [l.strip() for l in open(a.mask_file, encoding='utf-8') if l.strip()]
mask_re = re.compile('|'.join(sorted(map(re.escape, names), key=len, reverse=True)), re.I) if names else None
rendered = rendered_words(a.rendered)

# Evidence holds safe_url() forms only; exact URLs (with query) stay in memory for alias detection and lookups.
pages, texts, seen_final, failed = [], {}, {}, 0
info = {}   # exact input URL -> page record


def checkpoint(pairs, complete):
    write_json(a.out, {'masked_names': names, 'threshold': a.threshold, 'min_words': a.min_words, 'complete': complete, 'time_budget': a.time_budget,
                       'method': '5-word shingle Jaccard on served <main> text (or <body> minus header/nav/footer/aside); SequenceMatcher ratio for candidate pairs '
                                 '(not run at all when either text exceeds --max-chars: seq_limited)',
                       'pages': pages, 'pairs': pairs})


for i, u in enumerate(urls):
    if i >= a.max_pages:
        pages.append({'url': safe_url(u), 'status': f'skipped (over --max-pages {a.max_pages})'}); checkpoint('pending', False); continue
    rec = fetch_page(u, a.delay, a.cache, allowed_hosts=allowed)
    page = {k: rec.get(k) for k in ('status', 'final_url', 'redirects', 'content_type', 'encoding', 'error')}
    page = {'url': safe_url(u), **page}
    pages.append(page); info[u] = page
    if rec['error']:
        failed += 1; print('FAILED:', safe_url(u), rec['error'])
    else:
        exact_final = rec.get('final_url_exact') or u   # full final URL including query: /p?id=1 and /p?id=2 are different pages
        if exact_final in seen_final:
            page['alias_of'] = safe_url(seen_final[exact_final]); print('alias (same final URL):', safe_url(u))
        else:
            seen_final[exact_final] = u
            _, t, root = main_text(rec['html'])
            if mask_re: t = mask_re.sub('ENTITY', t)
            t = re.sub(r'\s+', ' ', t.lower()).strip()
            words = len(re.findall(r'\w+', t))
            page.update(root=root, words=words, rendered_words=rendered.get(safe_url(u)), csr_hint=csr_hint(rec['html'], words))
            page['coverage'] = coverage(words, page['rendered_words'], page['csr_hint'])
            texts[u] = t
    checkpoint('pending', False)


def shingles(t, k=5):
    w = re.findall(r'\w+', t)
    if not w: return set()
    return {' '.join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


t_compare = time.monotonic()
S = {u: shingles(t) for u, t in texts.items()}
pairs, over_budget = [], 0
for x, y in itertools.combinations(texts, 2):
    if time.monotonic() - t_compare >= a.time_budget:
        over_budget += 1
        pairs.append({'a': safe_url(x), 'b': safe_url(y), 'status': 'skipped (time budget)', 'flag': False})
        continue
    wx, wy = info[x]['words'], info[y]['words']
    rec = {'a': safe_url(x), 'b': safe_url(y), 'words': [wx, wy], 'roots': [info[x]['root'], info[y]['root']]}
    limited = [safe_url(u) for u in (x, y) if info[u]['coverage'] != 'full']
    if min(wx, wy) < a.min_words or limited:
        rec.update(status='inconclusive', flag=False,
                   reason='client-rendered page(s): ' + ', '.join(limited) if limited else f'fewer than {a.min_words} words')
        pairs.append(rec); continue
    j = len(S[x] & S[y]) / max(1, len(S[x] | S[y]))
    rec['jaccard5'] = round(j, 3)
    score = j
    if j >= a.threshold - 0.2:   # only run the slower ratio on plausible pairs
        if max(len(texts[x]), len(texts[y])) > a.max_chars:
            # SequenceMatcher is quadratic: over the limit it is not run, and the cheap Jaccard score decides
            rec['seq_limited'] = True
        else:
            r = difflib.SequenceMatcher(None, texts[x], texts[y], autojunk=False).ratio()
            rec['seq_ratio'] = round(r, 3)
            score = max(j, r)
    rec['flag'] = score >= a.threshold   # unrounded
    rec['decided_on'] = 'jaccard5 only (seq_limited)' if rec.get('seq_limited') else ('max(jaccard5, seq_ratio)' if 'seq_ratio' in rec else 'jaccard5')
    rec['status'] = 'compared'
    pairs.append(rec)
pairs.sort(key=lambda r: -max(r.get('jaccard5', 0), r.get('seq_ratio', 0)))
for r in pairs[:30]:
    if r['status'].startswith('skipped'): print(f"  {r['status']}  {r['a']}  <->  {r['b']}")
    elif r['status'] == 'inconclusive': print(f"  inconclusive ({r['reason']})  {r['a']}  <->  {r['b']}")
    else: print(f"{'FLAG ' if r['flag'] else '     '}{r['jaccard5']:.2f}/{r.get('seq_ratio', 'limited' if r.get('seq_limited') else '-')}  {r['a']}  <->  {r['b']}")
checkpoint(pairs, True)
print('flagged pairs:', sum(r['flag'] for r in pairs), 'of', len(pairs), '· inconclusive:', sum(r['status'] == 'inconclusive' for r in pairs),
      '· skipped (time budget):', over_budget, '· failed URLs:', failed, '-> wrote', a.out)
sys.exit(1 if failed or over_budget else 0)
