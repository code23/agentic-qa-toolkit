"""Shared polite fetcher for qa-site-audit python scripts.

One request at a time, a delay between requests, tagged UA, GET only. No implicit credentials (trust_env=False, so netrc
and environment proxies are never picked up). Every URL gets a structured record instead of an exception: status, final
URL, redirect chain, content type, encoding, error. HTML only, size cap, overall time limit, optional cache of good pages.
Callers parse their arguments before importing this module, so --help works without the dependencies.
"""
import hashlib, ipaddress, json, os, re, sys, time
from urllib.parse import unquote, urldefrag, urljoin, urlsplit, urlunsplit
try:
    import requests
    from bs4 import BeautifulSoup
    import lxml  # noqa: F401  (BeautifulSoup(..., 'lxml') needs it; check now, not on the first page)
except ImportError as _e:
    print(f'needs python packages: requests, beautifulsoup4, lxml (missing: {getattr(_e, "name", None) or "unknown"})', file=sys.stderr)
    sys.exit(2)

UA = 'Mozilla/5.0 (X11; Linux x86_64) Chrome/130 Safari/537.36 agentic-qa-toolkit-audit (read-only)'
MAX_BYTES = 5_000_000
MAX_REDIRECTS = 5
REDIRECT_CODES = (301, 302, 303, 307, 308)
_S = None
_last = [0.0]


class _Session(requests.Session):
    """requests resolves the redirect target itself even with allow_redirects=False (it decodes Location and reads the whole
    redirect body to fill Response.next). Switch that off: fetch_page reads Location defensively and never reads a redirect body."""

    def get_redirect_target(self, resp):
        return None


def _session():
    global _S
    if _S is None:
        _S = _Session()
        _S.trust_env = False
        _S.headers['User-Agent'] = UA
    return _S


_TOKEN = re.compile(r'(?=[A-Za-z_]*\d)[A-Za-z0-9_]{20,}')
_EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
# Credential formats that need no digit to be recognisable: sk-, ghp_/gho_/..., xox*, AKIA, Bearer <token>, JWT-shaped eyJ...
_CRED = re.compile(r'\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|xox[a-z]-[A-Za-z0-9-]{6,}|AKIA[0-9A-Z]{12,}'
                   r'|eyJ[A-Za-z0-9_-]{5,}(?:\.[A-Za-z0-9_-]+){1,2}|Bearer\s+[A-Za-z0-9._~+/=-]{8,})')


def _redact_text(t, keep_email=lambda e: False):
    t = _EMAIL.sub(lambda m: m.group(0) if keep_email(m.group(0).lower()) else '<email>', t)
    t = _CRED.sub(lambda m: m.group(0)[:4] + '…<redacted>', t)
    return _TOKEN.sub(lambda m: m.group(0)[:4] + '…<redacted>', t)


def _scrub_path(path):
    """Redact emails, credentials and token-like strings in a URL path, segment by segment (also when percent-encoded)."""
    out = []
    for seg in path.split('/'):
        dec = unquote(seg)
        red_seg = _redact_text(dec)
        out.append(seg if red_seg == dec else red_seg)
    return '/'.join(out)


def _bracket(host):
    return f'[{host}]' if ':' in host else host


def safe_url(u):
    """URL without query string, fragment or user info, for evidence files (exact URLs stay in memory only). Emails and
    token-like strings in the path are redacted; host and the rest of the path stay readable."""
    try:
        p = urlsplit(u)
        return urlunsplit((p.scheme, _bracket(p.hostname) + (f':{p.port}' if p.port else ''), _scrub_path(p.path), '', ''))
    except Exception:
        return _redact_text(re.split(r'[?#]', str(u))[0][:200])


def host_key(u):
    """Unambiguous host[:port] of a URL: lower case, IPv6 in brackets, default ports dropped. The port counts:
    example.com:8080 is another host, and [2001:db8::1]:8080 differs from [2001:db8::1:8080]."""
    p = urlsplit(u)
    port = p.port
    if port in ((80,) if p.scheme == 'http' else (443,) if p.scheme == 'https' else ()):
        port = None
    return _bracket((p.hostname or '').lower()) + (f':{port}' if port else '')


def with_twin(key):
    """{key, its www/apex twin} for a host_key. Only domain names have twins: IP addresses (v4 or bracketed v6) have none."""
    name, port = key, ''
    if not key.startswith('['):
        name, sep, tail = key.rpartition(':')
        if not sep or not tail.isdigit():
            name, port = key, ''
        else:
            port = ':' + tail
    if name.startswith('['):
        return {key}
    try:
        ipaddress.ip_address(name)
        return {key}
    except ValueError:
        pass
    twin = name[4:] if name.startswith('www.') else 'www.' + name
    return {key, twin + port}


def allowed_hosts_for(urls):
    """Hosts a run may follow redirects to: every input URL's host plus its www/apex twin."""
    out = set()
    for u in urls:
        out |= with_twin(host_key(u))
    return out


def _usage_exit(msg):
    print(msg, file=sys.stderr); sys.exit(2)


def valid_url(u):
    """http(s), a host, no user:pass@, and parseable (malformed IPv6 / ports raise ValueError in urlsplit)."""
    try:
        p = urlsplit(u)
        p.port  # raises ValueError for a bad port
        return p.scheme in ('http', 'https') and bool(p.hostname) and not (p.username or p.password)
    except ValueError:
        return False


def read_urls(arg, error=_usage_exit):
    """URL list from a file or comma-separated string. Invalid input calls error(msg) (pass argparse's ap.error: usage + exit 2)."""
    if os.path.exists(arg):
        with open(arg, encoding='utf-8') as fh:
            raw = fh.read().splitlines()
    else:
        raw = arg.split(',')
    urls, bad = [], []
    for u in (x.strip() for x in raw):
        if not u or u.startswith('#'):
            continue
        (urls if valid_url(u) else bad).append(u)
    if bad:
        error(f'invalid URL(s) (need http/https, no user:pass@): {[safe_url(b) for b in bad[:5]]}')
    if not urls:
        error('the URL list is empty')
    return urls


def red(t, keep_email=lambda e: False):
    """Evidence redaction (same rules as red() in _common.js): emails -> <email> unless keep_email(addr), credential formats
    (sk-, ghp_, xox*, AKIA, Bearer, JWT-shaped) and token-like strings (20+ chars with a digit) -> first 4 chars +
    '…<redacted>', URLs reduced to safe_url. Apply to the WHOLE string, then slice."""
    t = re.sub(r'https?://[^\s"\'<>)]+', lambda m: safe_url(m.group(0)), str(t))
    return _redact_text(t, keep_email)


_META = re.compile(rb'<meta[^>]+charset\s*=\s*["\']?\s*([\w.:-]+)', re.I)
_CT_CHARSET = re.compile(r';\s*charset\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s;]+))', re.I)


def header_charset(content_type):
    """charset parameter of a Content-Type header: quoted or bare, whitespace around '=' allowed (charset="shift_jis")."""
    m = _CT_CHARSET.search(content_type or '')
    if not m:
        return None
    return (m.group(1) or m.group(2) or m.group(3) or '').strip() or None


def _decode(body, content_type):
    """Header charset, then <meta charset>, then UTF-8; cp1252 only as a last resort (never requests' ISO-8859-1 guess)."""
    cands = []
    hc = header_charset(content_type)
    if hc:
        cands.append(hc)
    m = _META.search(body[:4096])
    if m:
        cands.append(m.group(1).decode('ascii', 'ignore'))
    cands.append('utf-8')
    for enc in cands:
        try:
            return body.decode(enc), enc
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode('cp1252', errors='replace'), 'cp1252 (fallback)'


_MEDIA = re.compile(r'[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*')


def media_type(content_type):
    """'text/html' from 'Text/HTML; charset=utf-8'; '' when the header is missing or not a media type."""
    mt = (content_type or '').split(';')[0].strip().lower()
    return mt if _MEDIA.fullmatch(mt) else ''


def _location_text(value):
    """Location header value as text: http.client hands over latin-1 text; re-read it as UTF-8 when it is UTF-8 underneath."""
    try:
        return value.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def fetch_page(url, delay=0.5, cache_dir=None, timeout=30, max_bytes=MAX_BYTES, allowed_hosts=None):
    """Returns a dict; 'html' is '' and 'error' is set when the page can't be used.

    Redirects are followed by hand (GET only, at most MAX_REDIRECTS hops) and only while the target host[:port] is in
    allowed_hosts (default: the requested URL's host and its www/apex twin). A redirect elsewhere is never requested: the
    record gets an error naming the refused host (no path or query), and nothing is cached."""
    rec = {'url': url, 'status': None, 'final_url': None, 'redirects': [], 'content_type': None, 'encoding': None, 'error': None, 'html': ''}
    allowed = set(allowed_hosts) if allowed_hosts is not None else with_twin(host_key(url))
    cf = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cf = os.path.join(cache_dir, hashlib.sha1(url.encode()).hexdigest() + '.json')
        if os.path.exists(cf):
            with open(cf, encoding='utf-8') as fh:
                rec = json.load(fh)
            rec['cached'] = True
            return rec
    t0 = time.time()
    cur = url
    try:
        for hop in range(MAX_REDIRECTS + 1):
            wait = delay - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            try:
                with _session().get(cur, timeout=(10, timeout), stream=True, allow_redirects=False) as r:
                    _last[0] = time.time()
                    rec['status'] = r.status_code
                    rec['final_url'] = safe_url(cur)
                    rec['final_url_exact'] = cur   # operational identity (aliases); never written to evidence
                    loc = r.headers.get('location')
                    if r.status_code in REDIRECT_CODES and loc:
                        # never read a redirect body; Location arrives as latin-1 text, usually UTF-8 underneath
                        rec['redirects'].append(f'{r.status_code} {safe_url(cur)}')
                        try:
                            nxt = urldefrag(urljoin(cur, _location_text(loc)))[0]
                        except ValueError:
                            nxt = ''
                        if not nxt:
                            rec['error'] = 'redirect with an unusable Location header (not followed)'
                        elif not valid_url(nxt):
                            rec['error'] = 'redirect to a non-http(s) URL (not followed)'
                        elif host_key(nxt) not in allowed:
                            rec['error'] = f'redirect to a host outside the input URLs (not followed): {host_key(nxt)}'
                        elif hop == MAX_REDIRECTS:
                            rec['error'] = f'more than {MAX_REDIRECTS} redirects'
                        else:
                            cur = nxt
                            continue
                        break
                    ct = r.headers.get('content-type', '')
                    rec['content_type'] = media_type(ct)   # normalised media type only, never the raw header
                    if r.status_code != 200:
                        rec['error'] = f'HTTP {r.status_code}'
                    elif 'html' not in rec['content_type']:
                        rec['error'] = f"not HTML ({rec['content_type'] or ('invalid content-type' if ct.strip() else 'no content-type')})"
                    else:
                        buf = bytearray()
                        for chunk in r.iter_content(65536):
                            buf += chunk
                            if len(buf) > max_bytes:
                                rec['error'] = f'larger than {max_bytes} bytes'; break
                            if time.time() - t0 > timeout:
                                rec['error'] = f'took longer than {timeout} s'; break
                        if not rec['error']:
                            rec['html'], rec['encoding'] = _decode(bytes(buf), ct)
                    break
            except requests.RequestException as e:
                rec['error'] = red(re.sub(r'\?[^\s)\'"]*', '?…', f'{type(e).__name__}: {e}'))[:200]
                break
    finally:
        _last[0] = time.time()
    if cf and not rec['error']:
        with open(cf, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh)
    return rec


def main_text(html, drop=('script', 'style', 'svg', 'noscript', 'dialog', 'template')):
    """(soup, text, root) from its own parse. root is 'main', or 'body' (header/nav/footer/aside removed) when there is no <main>."""
    s = BeautifulSoup(html, 'lxml')
    root, name = s.find('main') or s.find(attrs={'role': 'main'}), 'main'
    if root is None:
        root, name = (s.body, 'body') if s.body else (s, 'document')
        for t in root.find_all(['header', 'nav', 'footer', 'aside']):
            t.decompose()
    for t in root.find_all(drop):
        t.decompose()
    return s, root.get_text(' ', strip=True), name


def csr_hint(html, words):
    """True when the served HTML looks like an empty client-rendered shell (few words plus an app root or many scripts)."""
    s = BeautifulSoup(html, 'lxml')
    shell = s.select('#root, #__next, #app, #__nuxt, [data-reactroot], app-root, #___gatsby')
    return words < 50 and (bool(shell) or len(s.find_all('script', src=True)) >= 3)


def rendered_words(path):
    """safe_url(URL) -> rendered word count from a viewport_overflow.js JSON file (max over widths). Look up with safe_url(u):
    evidence files hold query-less URLs."""
    if not path:
        return {}
    out = {}
    with open(path, encoding='utf-8') as fh:
        results = json.load(fh).get('results', [])
    for r in results:
        if r.get('renderedWords') is not None:
            k = safe_url(r['url'])
            out[k] = max(out.get(k, 0), r['renderedWords'])
    return out


def coverage(served, rendered, hint):
    """'full', or 'limited (client-rendered)' when served text is under 70% of rendered text or the page looks like a CSR shell."""
    if rendered and served < 0.7 * rendered:
        return 'limited (client-rendered)'
    if rendered is None and hint:
        return 'limited (client-rendered)'
    return 'full'


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)
