#!/usr/bin/env python3
"""Copy and freshness scan (served HTML, polite fetch). Heuristic flags for the lead to judge, not defects by themselves:
  stale-quarter       'Qn YYYY' earlier than the current quarter; a bare 'Qn' earlier than the current quarter with no
                      forward-looking word nearby (booking, from, starting, next, ...)
  quarter-ambiguous   a bare 'Qn' earlier than the current quarter WITH a forward-looking word (may mean next year)
  old-year            'as of / updated / last updated / reviewed / last reviewed <optional day/month> YYYY' older than last year
  copyright-year      '© / (c) / Copyright YYYY' or a range 'YYYY-YYYY' whose END year is before this year
  timezone-label      only with --timezone <IANA name> (e.g. Europe/London, America/New_York): an abbreviation of that zone that
                      is out of season on --today, such as 'GMT' while London is on BST. Needs a zone with two named seasons;
                      without --timezone, or for a zone without them, the check is reported as not run / not applicable
  placeholder         lorem ipsum, TODO, TBC, FIXME, 'placeholder', [placeholder], xxx, 'coming soon', 'insert text/copy here'
  repeated-sentence   the same block (30+ chars) 3+ times on one page; each occurrence counted once, aria-hidden excluded
  title-slug-mismatch title vs URL slug word overlap <= 0.5 (file extension and trailing index dropped; slug needs 2+ words)
  breakpoint-copy-differs  Tailwind-class heuristic only (sm:/md:/lg:hidden, hidden md:block); use viewport_overflow.js
                      parity output for a CSS-agnostic check
Cross-page variants: phone numbers (national numbers with a leading 0, plus any +country-code number), role email addresses (info@, hello@ ...;
personal addresses are counted, never stored), 'established/founded/since YYYY', 'N+ <noun>' claims.

Evidence: URLs without query strings; every snippet and title is redacted (personal emails, token-like strings) before it
is cut to length. The output is checkpointed after every URL ("complete": false until the end).
Exit: 0 done, 1 some URLs failed (output still written), 2 usage or dependency error.
"""
import argparse, collections, datetime, json, math, re, sys, os

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('urls', help='file with one URL per line, or comma-separated URLs')
ap.add_argument('--out', default='evidence/copy.json')
ap.add_argument('--cache', help='cache directory; reruns fetch nothing new')
ap.add_argument('--delay', type=float, default=0.5, help='seconds between requests (min 0.5)')
ap.add_argument('--today', help='YYYY-MM-DD (default: today)')
ap.add_argument('--timezone', help='IANA zone name (Europe/London, America/New_York, Australia/Sydney ...) for the out-of-season abbreviation check; without it that check does not run')
ap.add_argument('--rendered', help='viewport_overflow.js JSON, for the served-vs-rendered preflight')
ap.add_argument('--max-pages', type=int, default=500, help='stop fetching after this many URLs (default 500)')
a = ap.parse_args()
if not (math.isfinite(a.delay) and a.delay >= 0.5): ap.error('--delay must be a number >= 0.5')
if a.max_pages < 1: ap.error('--max-pages must be at least 1')
try:
    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()
except ValueError:
    ap.error('--today must be YYYY-MM-DD')

def zone_season(name, day):
    """(status, in_force, out_of_season) for an IANA zone on day. status is 'run' or 'not applicable (...)'. The two names come from
    the zone's own tzname() values across day's year; numeric abbreviations ('+03') and single-name zones have no seasonal pair."""
    from zoneinfo import ZoneInfo
    z = ZoneInfo(name)
    names = {datetime.datetime(day.year, m, 15, 12, tzinfo=z).tzname() for m in range(1, 13)}
    names = {n for n in names if n and re.fullmatch(r'[A-Za-z]{2,6}', n)}
    here = datetime.datetime(day.year, day.month, day.day, 12, tzinfo=z).tzname()
    if len(names) < 2 or here not in names:
        return f'not applicable ({name} has no seasonal pair of named abbreviations)', here, []
    return 'run', here, sorted(names - {here})


tz_name, tz_status, tz_in_force, tz_out = a.timezone, 'not run (no --timezone given)', None, []
if tz_name is not None:
    try:
        tz_status, tz_in_force, tz_out = zone_season(tz_name, today)
    except ImportError:
        print('copy_freshness: --timezone needs Python 3.9+ (zoneinfo)', file=sys.stderr); sys.exit(2)
    except (KeyError, ValueError, OSError):
        print(f'copy_freshness: unknown time zone {tz_name!r}, or no time zone data on this machine (try: pip install tzdata)', file=sys.stderr); sys.exit(2)
    if tz_status == 'run':
        tz_status = f'run: {tz_in_force} in force on {today}; flags out-of-season {"/".join(tz_out)}'
TZ_RE = re.compile(r'(?<![A-Za-z0-9])(' + '|'.join(map(re.escape, tz_out)) + r')(?![A-Za-z0-9])') if tz_out else None
# abbreviations that are also English words only count next to a clock time ("10:00 CAT"); "EST. 1994" (established) never counts
WORDLIKE = {'WET', 'EAT', 'CAT', 'MET', 'PET', 'WAT', 'SAT'}
TIME_BEFORE = re.compile(r'\d\s*(?:[ap]\.?m\.?)?\s*$', re.I)


def tz_label_hit(full, m):
    before, after = full[max(0, m.start() - 14):m.start()], full[m.end():m.end() + 14]
    after_time = bool(re.match(r'\s*\d{1,2}(?:[:.]\d{2})?\b', after))
    near_time = bool(TIME_BEFORE.search(before)) or after_time
    if re.match(r'\.?\s*(?:19|20)\d\d\b', after) and not TIME_BEFORE.search(before): return False
    return near_time or m.group(1) not in WORDLIKE


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.parse import urlsplit
from _fetch import read_urls, fetch_page, main_text, csr_hint, rendered_words, coverage, write_json, safe_url, allowed_hosts_for, red
from bs4 import BeautifulSoup

cur_q = (today.month - 1) // 3 + 1


STOP = set('a an the and or of to for in on with your you our we is are how what why which do does vs'.split())
FORWARD = re.compile(r'\b(book(ing|ings)?|from|starting|start|next|upcoming|available|open(ing)?|launch(ing)?|coming|reserve|by)\b', re.I)
ROLE = set('info hello contact enquiries enquiry sales support help admin office team press media careers jobs hr privacy dpo accounts '
           'billing bookings booking reception marketing studio mail general service customerservice noreply no-reply webmaster security legal'.split())
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[a-z]{2,})+', re.I)
PHONE = re.compile(r'\b0\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}|\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}')
BLOCKS = ['p', 'li', 'h2', 'h3', 'h4', 'dd', 'figcaption', 'blockquote', 'span']


def is_role(e): return e.split('@')[0] in ROLE


def scrub(t):  # personal email addresses and token-like strings never land in evidence; role addresses are kept
    return red(EMAIL.sub(lambda m: m.group(0) if is_role(m.group(0).lower()) else '<email>', t), keep_email=is_role)


def ctx(text, m, before=60, after=40): return text[max(0, m.start() - before):m.end() + after]


def hidden(e):
    return e.get('aria-hidden') == 'true' or e.find_parent(attrs={'aria-hidden': 'true'}) is not None


def slug_words(path):
    """Words of the last URL segment: a trailing file extension (.html, .php ...) and a trailing 'index' segment are dropped,
    dots inside the slug (v2.1-release-notes) stay, then it is split on - _ . and stop words are removed."""
    parts = [p for p in path.lower().split('/') if p]
    if parts:
        parts[-1] = re.sub(r'\.[a-z][a-z0-9]{1,4}$', '', parts[-1])
    if parts and parts[-1] == 'index':
        parts.pop()
    return [w for w in re.split(r'[-_.]', parts[-1] if parts else '') if w and w not in STOP]


def flags_for(full, soup):
    full = scrub(full)   # before slicing context, so a cut-off address can't slip through
    f = []
    for m in re.finditer(r'\bQ([1-4])(?:[\s-]*(?:cohort\s+)?(20\d\d))?\b', full):
        q, y = int(m.group(1)), m.group(2)
        if y:
            if (int(y), q) < (today.year, cur_q): f.append({'type': 'stale-quarter', 'text': ctx(full, m)})
        elif q < cur_q:
            near = full[max(0, m.start() - 40):m.end() + 20]
            f.append({'type': 'quarter-ambiguous' if FORWARD.search(near) else 'stale-quarter', 'text': ctx(full, m), 'note': 'no year given'})
    for m in re.finditer(r'\b(as of|last updated|updated|last reviewed|reviewed)\s*:?\s+(?:on\s+)?(?:\d{1,2}(?:st|nd|rd|th)?\s+)?'
                         r'(?:[A-Z][a-z]+\.?\s+)?(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(20\d\d)\b', full, re.I):
        if int(m.group(2)) < today.year - 1: f.append({'type': 'old-year', 'text': ctx(full, m, 40, 40)})
    for m in re.finditer(r'(?:©|\(c\)|\bcopyright\b)\s*(?:(?:19|20)\d\d\s*[-–—]\s*)?((?:19|20)\d\d)\b', full, re.I):
        if int(m.group(1)) < today.year: f.append({'type': 'copyright-year', 'text': ctx(full, m, 20, 40)})
    if TZ_RE:
        for m in TZ_RE.finditer(full):
            if tz_label_hit(full, m):
                f.append({'type': 'timezone-label', 'text': ctx(full, m, 60, 10),
                          'note': f'{tz_name} is currently on {tz_in_force}; a label with no abbreviation ("local time") is always right'})
    for m in re.finditer(r'lorem ipsum|\bTODO\b|\bTBC\b|\bFIXME\b|\[placeholder\]|\bplaceholder\b|\bx{3,}\b|coming soon|insert (text|copy) here', full, re.I):
        f.append({'type': 'placeholder', 'text': ctx(full, m, 40, 40)})

    # repeated blocks: count each occurrence once (skip a block whose nearest block ancestor has the same text)
    main = soup.find('main') or soup.body or soup
    blocks = []
    for e in main.find_all(BLOCKS):
        if hidden(e) or e.find(['p', 'li', 'div']): continue
        t = re.sub(r'\s+', ' ', e.get_text(' ', strip=True))
        if len(t) < 30: continue
        parent = e.find_parent(BLOCKS)
        if parent is not None and re.sub(r'\s+', ' ', parent.get_text(' ', strip=True)) == t: continue
        blocks.append(t)
    for sent, c in collections.Counter(blocks).items():
        if c >= 3: f.append({'type': 'repeated-sentence', 'count': c, 'text': scrub(sent)[:140]})

    # breakpoint-only copy: Tailwind-class heuristic only
    mob, desk = [], []
    for e in main.find_all(class_=True):
        cl = ' '.join(e.get('class'))
        t = e.get_text(' ', strip=True)
        if len(t) < 25 or hidden(e): continue
        if re.search(r'(^|\s)(sm|md|lg):hidden(\s|$)', cl): mob.append(scrub(t)[:160])
        elif re.search(r'(^|\s)hidden(\s|$)', cl) and re.search(r'(sm|md|lg):(block|flex|grid|inline)', cl): desk.append(scrub(t)[:160])
    mob_only = [t for t in mob if t not in desk]; desk_only = [t for t in desk if t not in mob]
    if mob_only or desk_only:
        f.append({'type': 'breakpoint-copy-differs', 'method': 'tailwind-class heuristic', 'mobile_only': mob_only[:5], 'desktop_only': desk_only[:5]})
    return f


rendered = rendered_words(a.rendered)
urls = read_urls(a.urls, ap.error)
allowed = allowed_hosts_for(urls)   # redirects are only followed between the input URLs' hosts (and their www/apex twins)
pages, failed = [], 0
facts = collections.defaultdict(lambda: collections.defaultdict(set))   # values hold safe_url() forms only


def variants():
    return {k: {val: sorted(us)[:5] for val, us in v.items()} for k, v in facts.items() if len(v) > 1}


def checkpoint(complete):
    write_json(a.out, {'today': str(today), 'timezone': tz_name, 'timezone_check': tz_status, 'timezone_in_force': tz_in_force,
                       'timezone_out_of_season': tz_out, 'complete': complete,
                       'pages': pages, 'cross_page_variants': variants(),
                       'note': 'Heuristics on served HTML. The lead confirms each flag in context before rating it. Timezone-label check: ' + tz_status + '. Pages with coverage "limited (client-rendered)" were not really checked.'})


for i, u in enumerate(urls):
    su = safe_url(u)
    if i >= a.max_pages:
        pages.append({'url': su, 'status': f'skipped (over --max-pages {a.max_pages})', 'flags': []}); checkpoint(False); continue
    rec = fetch_page(u, a.delay, a.cache, allowed_hosts=allowed)
    if rec['error']:
        failed += 1; pages.append({'url': su, 'status': rec['status'], 'error': rec['error'], 'flags': []}); print('FAILED:', su, rec['error'])
        checkpoint(False); continue
    soup = BeautifulSoup(rec['html'], 'lxml')
    for t in soup.find_all(['script', 'style', 'noscript', 'template']): t.decompose()
    full = (soup.body or soup).get_text(' ', strip=True)
    _, main_t, root = main_text(rec['html'])
    words = len(re.findall(r'\w+', main_t))
    f = flags_for(full, soup)
    title = (soup.title.get_text(strip=True) if soup.title else '').split(' — ')[0].split(' | ')[0]
    slug = slug_words(urlsplit(u).path)
    tw = {w for w in re.findall(r'[a-z0-9]+', title.lower()) if w not in STOP}
    if len(slug) >= 2 and tw:
        ov = len(set(slug) & tw) / len(set(slug) | tw)
        if ov <= 0.5: f.append({'type': 'title-slug-mismatch', 'slug': scrub('-'.join(slug))[:120], 'title': scrub(title)[:160], 'jaccard': round(ov, 2)})
    personal = 0
    for m in PHONE.finditer(full): facts['phone'][re.sub(r'\D', '', m.group(0))[-10:]].add(su)
    for m in EMAIL.finditer(full):
        e = m.group(0).lower().rstrip('.')
        if re.search(r'\.(css|js|png|webp|jpg|svg)$', e): continue
        if is_role(e): facts['email'][e].add(su)
        else: personal += 1
    for m in re.finditer(r'\b(?:established|founded|since|est\.?)\s+(?:in\s+)?((?:19|20)\d\d)\b', full, re.I): facts['established'][m.group(1)].add(su)
    for m in re.finditer(r'\b(\d{1,4})\+\s+([a-z-]+(?:\s[a-z-]+)?)', full, re.I): facts['stat:' + m.group(2).lower().split()[0]][m.group(1)].add(su)
    hint = csr_hint(rec['html'], words)
    pages.append({'url': su, 'status': rec['status'], 'final_url': rec['final_url'], 'title': scrub(title)[:160], 'root': root, 'words': words,
                  'rendered_words': rendered.get(su), 'coverage': coverage(words, rendered.get(su), hint), 'personal_emails_seen': personal, 'flags': f})
    print(f"{len(f):3} flags  {su}  " + ', '.join(sorted({x['type'] for x in f})))
    checkpoint(False)
print('cross-page variants:', json.dumps(variants(), indent=0)[:1500])
checkpoint(True)
print('failed URLs:', failed, '-> wrote', a.out)
sys.exit(1 if failed else 0)
