#!/usr/bin/env python3
"""Export a QA report as ONE self-contained HTML file and, optionally, a PDF that carries every screenshot.

  python3 report_export.py RUN/report.md [--html OUT.html] [--pdf OUT.pdf] [--allow-missing]

First runs report_check.py's checks and refuses to export when an embedded image is missing, unsafe or not a real image
(--allow-missing exports anyway and shows a visible "image unavailable" box in its place). It also refuses when an image the
checker validated does not end up inlined in the page (the checker and the exporter parse the Markdown identically, so this
should never happen), unless --allow-missing. Every local image is inlined as a
data: URI inside <figure> with its alt text as <figcaption>. Raw HTML in the Markdown is escaped, not passed through; the page
carries a Content-Security-Policy meta tag and references no remote resource. Links stay as text links.

--pdf prints that HTML with headless Chrome (CHROME_PATH, default: Google Chrome's standard path on macOS or Linux) using a
throwaway profile folder, then VERIFIES the PDF: it exists, starts with %PDF, and holds at least as many image objects
(/Subtype /Image, not counting soft masks that belong to a transparent image) as there are distinct images actually inlined. A failed verification keeps the file and exits 1.
With only --pdf, the HTML is built in a temporary folder that is removed afterwards.

Image validation (the limit): for a PNG the checker verifies chunk checksums and decompresses the pixel stream, checking its
length and row filter bytes against the header; it does not interpret pixels or palette colours. JPEG, GIF and WebP get structural checks only, which do
not prove the image decodes; an HTML-only export says so. --pdf is the stronger check: before printing, Chrome is asked to load
every image of a throwaway copy of the page (its own decoder must accept the file and report a size; damage deep inside the pixel
data can still get through). A PDF image count alone is not proof, because Chrome draws a broken-image icon, itself an image
object, for a file it cannot load. An image Chrome cannot load stops the PDF unless --allow-missing.

Brand pack (optional): --brand DIR, else the QA_BRAND environment variable; --no-brand ignores both. See brand_check.py for the folder
layout and brand.json schema, which is validated first (a bad pack refuses the export). A brand adds a cover page (logo, the
report's first H1, brand name, date, cover fields, or cover.md), colours and fonts from the pack, and a footer on every
PDF page. Brand files are inlined as data: URIs; the logo is an <img>, so an SVG logo cannot run script or load anything. Without a
brand the output is exactly what it is without this feature. --date YYYY-MM-DD sets the cover date (default: today).

Needs the `markdown` package (see requirements.txt). Never overwrites the source report.
Exit: 0 done, 1 refused or verification failed, 2 usage error or missing dependency / Chrome.
"""
import argparse, base64, datetime, hashlib, html, os, re, shutil, subprocess, sys, tempfile, time
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_check
import brand_check

CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
CHROME = os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform == 'darwin' else '/usr/bin/google-chrome')
VOID = {'img', 'br', 'hr'}
ALLOWED = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'pre', 'code',
           'em', 'strong', 'blockquote', 'hr', 'br', 'a', 'img', 'del', 'sup', 'sub'}
CSS = """
body { font: 14px/1.5 -apple-system, Helvetica, Arial, sans-serif; color: #1b1f24; max-width: 920px; margin: 24px auto; padding: 0 16px; }
h1, h2, h3, h4 { line-height: 1.25; break-after: avoid; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #c8ccd0; padding: 4px 8px; text-align: left; vertical-align: top; }
pre { background: #f4f5f6; padding: 10px; overflow-wrap: anywhere; white-space: pre-wrap; }
code { background: #f4f5f6; padding: 0 3px; }
blockquote { border-left: 3px solid #c8ccd0; margin-left: 0; padding-left: 12px; color: #4a5056; }
figure { margin: 1em 0; break-inside: avoid; page-break-inside: avoid; }
figure img, img { display: block; max-width: 100%; height: auto; border: 1px solid #d0d7de; }
figcaption { font-size: 12px; color: #4a5056; margin-top: 4px; }
figure.unavailable { border: 1px dashed #b00020; padding: 10px; color: #b00020; }
@page { margin: 15mm; }
/* In print a tall phone screenshot is held to about half a page, so it sits with its finding. */
@media print { body { max-width: none; margin: 0; } a { color: inherit; } figure img, img { max-height: 125mm; width: auto; } }
"""


class Node:
    def __init__(self, tag, attrs=None):
        self.tag, self.attrs, self.children = tag, dict(attrs or []), []


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root'); self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs); self.stack[-1].children.append(n)
        if tag not in VOID: self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]; break

    def handle_data(self, data): self.stack[-1].children.append(data)


def parse_html(src):
    t = _Tree(); t.feed(src); t.close(); return t.root


def esc(s): return html.escape(s, quote=True)


def safe_href(h):
    h = (h or '').strip()
    return h if re.match(r'^(https?:|mailto:|#)', h, re.I) else None


def media_of(path):
    with open(path, 'rb') as fh: return report_check.sniff(fh.read(16))


class Renderer:
    def __init__(self, images):
        self.images = images    # image src as the Markdown parser renders it -> {'path': Path, 'mime': str}
        self.inlined = {}       # sha1 of bytes -> True (distinct images that made it into the page)
        self.figures = 0        # image figures inlined (an image used twice counts twice)
        self.unavailable = 0    # image figures replaced by an "unavailable" box

    def figure(self, img):
        alt = img.attrs.get('alt', '').strip()
        src = img.attrs.get('src', '')
        info = self.images.get(src)
        if not info:
            self.unavailable += 1
            note = f'image unavailable: {esc(alt)}' if alt else 'image unavailable'
            return f'<figure class="unavailable"><figcaption>{note}</figcaption></figure>'
        data = Path(info['path']).read_bytes()
        self.inlined[hashlib.sha1(data).hexdigest()] = True
        self.figures += 1
        uri = f"data:{info['mime']};base64,{base64.b64encode(data).decode('ascii')}"
        cap = f'<figcaption>{esc(alt)}</figcaption>' if alt else ''
        return f'<figure><img src="{uri}" alt="{esc(alt)}">{cap}</figure>'

    def render(self, node):
        if isinstance(node, str): return esc(node)
        tag = node.tag
        if tag == 'root': return ''.join(self.render(c) for c in node.children)
        if tag == 'img': return self.figure(node)
        if tag not in ALLOWED: return ''.join(self.render(c) for c in node.children)   # unknown element: keep only its text
        if tag == 'p':
            kids = [c for c in node.children if not (isinstance(c, str) and not c.strip())]
            if kids and all(isinstance(c, Node) and c.tag in ('img', 'br') for c in kids) and any(c.tag == 'img' for c in kids):
                return ''.join(self.figure(c) for c in kids if c.tag == 'img')
        if tag in VOID: return f'<{tag}>'
        inner = ''.join(self.render(c) for c in node.children)
        if tag == 'a':
            href = safe_href(node.attrs.get('href'))
            return f'<a href="{esc(href)}" rel="noreferrer">{inner}</a>' if href else inner
        if tag in ('th', 'td') and node.attrs.get('style', '').replace(' ', '').startswith('text-align:'):
            al = node.attrs['style'].replace(' ', '').split(':', 1)[1].rstrip(';')
            if al in ('left', 'right', 'center'): return f'<{tag} style="text-align:{al}">{inner}</{tag}>'
        return f'<{tag}>{inner}</{tag}>'


def md_escape(text):
    """Markdown-escape a value so it renders as literal text."""
    return re.sub(r'([\\`*_{}\[\]()>#+\-.!])', r'\\\1', re.sub(r'\s+', ' ', text))


def css_string(text):
    """text as the inside of a CSS string literal: everything but letters, digits, space and basic punctuation is hex-escaped."""
    return ''.join(c if (c.isalnum() and c.isascii()) or c in ' .,-_:/()&' else f'\\{ord(c):x} ' for c in text)


BRAND_CSS = """
:root { --accent: %(accent)s; --ink: %(ink)s; --muted: %(muted)s; --paper: %(paper)s; }
html { background: var(--paper); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { color: var(--ink); background: var(--paper); }
h1, h2, h3, h4 { color: var(--ink); }
h2 { border-bottom: 2px solid var(--accent); padding-bottom: 4px; }
a { color: var(--accent); }
th { border-color: var(--muted); }
td { border-color: var(--muted); }
figcaption, blockquote { color: var(--muted); }
.cover { break-after: page; page-break-after: always; min-height: 240mm; display: flex; flex-direction: column; justify-content: center; }
.cover .brand-logo { max-height: 28mm; max-width: 70mm; width: auto; height: auto; border: 0; margin-bottom: 24mm; }
.cover .cover-title { font-size: 30px; line-height: 1.2; font-weight: 700; color: var(--ink); margin: 0 0 8px; }
.cover .cover-brand { border-top: 2px solid var(--accent); padding-top: 12px; }
.cover .cover-brand { font-size: 16px; margin: 0; }
.cover .cover-date { color: var(--muted); margin: 4px 0 24px; }
.cover dl { margin: 0; } .cover dt { color: var(--muted); font-size: 12px; margin-top: 10px; } .cover dd { margin: 0; }
.brand-footer { font-size: 10px; color: var(--muted); text-align: center; margin-top: 24px; }
@media print { .brand-footer { display: none; } }
"""
FONT_STACK = '-apple-system, Helvetica, Arial, sans-serif'   # the report's own font stack (see CSS body rule)
BRAND_DEFAULTS = {'accent': '#1b1f24', 'ink': '#1b1f24', 'muted': '#4a5056', 'paper': '#ffffff'}


def brand_stylesheet(brand):
    """(css, needs_font_src) for a validated brand: colour variables, font-face rules and cover/footer styling, all generated from validated
    brand.json values. The only stylesheet in an export is ours plus this."""
    colours = {**BRAND_DEFAULTS, **brand['colours']}
    css = BRAND_CSS % colours
    # The page box, margins included, takes the paper colour; the root background alone stops at the margins in print.
    css += f'@page {{ background: {colours["paper"]}; }}\n'
    seen = {}
    for f in brand['fonts']:
        key = (f['family'], f['ext'], hashlib.sha1(f['data']).hexdigest())
        if key in seen: continue
        seen[key] = True
        uri = f"data:{brand_check.FONT_MIME[f['ext']]};base64,{base64.b64encode(f['data']).decode('ascii')}"
        css += f'@font-face {{ font-family: "{css_string(f["family"])}"; src: url({uri}) format("{brand_check.FONT_FORMAT[f["ext"]]}"); font-display: block; }}\n'
    fams = {f['role']: f['family'] for f in brand['fonts']}
    if brand['footer']:   # printed in the page margin: the margin box does not inherit the body font, so it is set here
        stack = (f'"{css_string(fams["body"])}", ' if 'body' in fams else '') + FONT_STACK
        css += f'@page {{ @bottom-center {{ content: "{css_string(brand["footer"])}"; font-family: {stack}; font-size: 9px; color: {colours["muted"]}; }} }}\n'
    if 'body' in fams: css += f'body {{ font-family: "{css_string(fams["body"])}", {FONT_STACK}; }}\n'
    if 'heading' in fams: css += f'h1, h2, h3, h4, .cover .cover-title {{ font-family: "{css_string(fams["heading"])}", {FONT_STACK}; }}\n'
    return css, bool(brand['fonts'])


def cover_html(brand, title, date):
    """The cover page: logo, then either cover.md (placeholders substituted as escaped text, rendered through the safe pipeline)
    or the default layout. Report screenshots are <figure><img>; nothing here is, so the load probe and PDF image target ignore it."""
    out = ['<section class="cover">']
    if brand['logo']:
        uri = f"data:{brand['logo']['mime']};base64,{base64.b64encode(brand['logo']['data']).decode('ascii')}"
        out.append(f'<img class="brand-logo" src="{uri}" alt="{esc(brand["name"])} logo">')
    values = {'title': title, 'date': date, 'brand': brand['name'], **{k: brand['cover'].get(k, '') for k in brand_check.COVER_KEYS}}
    if brand['cover_md'] is not None:
        text = re.sub(r'\{(' + '|'.join(brand_check.PLACEHOLDERS) + r')\}', lambda m: md_escape(values[m.group(1)]), brand['cover_md'])
        out.append(Renderer({}).render(parse_html(report_check.render_markdown(text))))
    else:
        out.append(f'<p class="cover-title">{esc(title)}</p>\n<p class="cover-brand">{esc(brand["name"])}</p>\n<p class="cover-date">{esc(date)}</p>')
        rows = [(label, brand['cover'][k]) for k, label in (('prepared_by', 'Prepared by'), ('contact', 'Contact'), ('confidentiality', 'Confidentiality')) if brand['cover'].get(k)]
        if rows: out.append('<dl class="cover-fields">' + ''.join(f'<dt>{label}</dt><dd>{esc(v)}</dd>' for label, v in rows) + '</dl>')
    out.append('</section>')
    return '\n'.join(out)


def first_h1(report_text):
    m = re.search(r'^#\s+(.+?)\s*#*\s*$', report_text, re.M)
    return re.sub(r'[`*_]', '', m.group(1)) if m else 'QA report'


def build_html(report_text, images, brand=None, date=None):
    """(html_text, renderer). Raw HTML in the source is escaped; only allow-listed elements survive. The renderer reports how many
    figures were inlined (renderer.figures), how many were replaced by unavailable boxes and the distinct inlined images.
    With a validated brand (brand_check.check_brand(...).brand) the page gets a cover, the brand's colours and fonts,
    and a footer; without one the output is unchanged."""
    r = Renderer(images)
    body = r.render(parse_html(report_check.render_markdown(report_text)))
    title = esc(first_h1(report_text))
    csp, css = CSP, CSS
    if brand:
        extra, fonts = brand_stylesheet(brand)
        css += extra
        if fonts: csp = CSP.replace("img-src data:;", "img-src data:; font-src data:;")
        body = cover_html(brand, first_h1(report_text), date or str(datetime.date.today())) + '\n' + body
        if brand['footer']: body += f'\n<footer class="brand-footer">{esc(brand["footer"])}</footer>'
    page = (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title}</title>\n'
            f'<style>{css}</style></head>\n<body>\n{body}\n</body></html>\n')
    return page, r


def count_pdf(data):
    """(image objects, pages). Soft masks (an image object another object names as /SMask or /Mask) are not screenshots and do not
    count: a transparent screenshot is one image plus its mask."""
    objs = [(m.start(), int(m.group(1))) for m in re.finditer(rb'(?m)^(\d+)\s+\d+\s+obj\b', data)]
    images, masks = set(), set()
    for k, (start, num) in enumerate(objs):
        end = objs[k + 1][0] if k + 1 < len(objs) else len(data)
        head = data[start:end].split(b'stream', 1)[0]
        masks.update(int(x) for x in re.findall(rb'/(?:SMask|Mask)\s+(\d+)\s+\d+\s+R', head))
        if re.search(rb'/Subtype\s*/Image\b', head): images.add(num)
    pages = len(re.findall(rb'/Type\s*/Page\b(?!s)', data))
    return len(images - masks), pages


def verify_pdf(path, expected_images):
    """(ok, message, images_found). The PDF must exist, start with %PDF and hold at least expected_images image objects."""
    p = Path(path)
    if not p.is_file(): return False, f'PDF verification failed: {p} was not written', 0
    data = p.read_bytes()
    if not data.startswith(b'%PDF'): return False, f'PDF verification failed: {p} does not start with %PDF (starts with {data[:8]!r})', 0
    found, _ = count_pdf(data)
    if found < expected_images:
        return False, f'PDF verification failed: expected at least {expected_images} image objects, found {found}', found
    return True, f'{found} image objects found, {expected_images} expected', found


FOOTER_MIN_CHROME = 131   # CSS page margin boxes (@page { @bottom-center }) need Chrome 131 or later
_chrome_major = []


def parse_chrome_major(text):
    """Major version from `chrome --version` output ('Google Chrome 155.0.8059.40', 'Chromium 120.0.6099.109 built on Debian'), or None."""
    m = re.search(r'(\d+)\.\d+\.\d+\.\d+', text or '')
    return int(m.group(1)) if m else None


def chrome_major_version():
    """Chrome's major version, asked once per run; None when it cannot be determined."""
    if not _chrome_major:
        try:
            out = subprocess.run([CHROME, '--version'], capture_output=True, text=True, timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            out = ''
        _chrome_major.append(parse_chrome_major(out))
    return _chrome_major[0]


def run_chrome(args, url, ready, stdout_to=None, limit=180):
    """Run headless Chrome on url with a throwaway profile; poll ready() and stop Chrome as soon as it is true or it exits.
    Chrome can hang or exit non-zero in its teardown after it has done the work, so the caller judges by the result, not the exit code.
    Returns the exit status (None if Chrome was stopped by us) or raises OSError when it cannot start."""
    profile = tempfile.mkdtemp(prefix='qa-export-profile-')
    try:
        cmd = [CHROME, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-extensions',
               '--disable-background-networking', '--disable-component-update', '--disable-sync', f'--user-data-dir={profile}', *args, url]
        out = open(stdout_to, 'wb') if stdout_to else subprocess.DEVNULL
        try:
            proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.DEVNULL)
            deadline = time.time() + limit
            try:
                while time.time() < deadline and proc.poll() is None and not ready():
                    time.sleep(0.4)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(10)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        finally:
            if stdout_to: out.close()
        return proc.returncode
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def print_pdf(html_path, pdf_path):
    """Headless Chrome print; returns (ok, error message)."""
    started, out = time.time() - 1, Path(pdf_path)
    state = {'last': -1}

    def fresh():
        return out.is_file() and out.stat().st_size > 0 and out.stat().st_mtime >= started

    def ready():   # the file exists and has stopped growing
        size = out.stat().st_size if fresh() else -1
        done = size > 0 and size == state['last']
        state['last'] = size
        return done

    try:
        rc = run_chrome(['--no-pdf-header-footer', f'--print-to-pdf={pdf_path}'], Path(html_path).resolve().as_uri(), ready)
    except OSError as e:
        return False, f'Chrome did not run ({type(e).__name__})'
    return (True, '') if fresh() else (False, f'Chrome exited with status {rc} and wrote no PDF')


PROBE_JS = r"""
function shown(i){
  if(!i.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return false;
  var r=i.getBoundingClientRect(), minW=Math.min(40,i.naturalWidth), minH=Math.min(40,i.naturalHeight);
  if(r.width<minW||r.height<minH) return false;
  if(r.right<=0||r.bottom+window.scrollY<=0||r.left>=document.documentElement.scrollWidth) return false;
  for(var e=i;e&&e!==document.documentElement;e=e.parentElement){
    var c=window.getComputedStyle(e);
    if(c.clipPath!=='none'||c.filter!=='none'||c.transform!=='none'||(c.maskImage&&c.maskImage!=='none')||c.contentVisibility==='hidden') return false;
    if(e!==i&&(c.overflowX!=='visible'||c.overflowY!=='visible')){
      var q=e.getBoundingClientRect();
      if(Math.min(r.right,q.right)-Math.max(r.left,q.left)<minW||Math.min(r.bottom,q.bottom)-Math.max(r.top,q.top)<minH) return false;
    }
  }
  return true;
}
window.addEventListener('load',function(){var load=[],hid=[];
  Array.prototype.forEach.call(document.querySelectorAll('figure img'),function(i,n){
    if(!(i.complete&&i.naturalWidth>0&&i.naturalHeight>0)) load.push(n); else if(!shown(i)) hid.push(n);});
  document.title='DECODE:'+load.join(',')+':SHOWN:'+hid.join(',')+':END';});
"""
PROBE_SCRIPT = '<script>' + PROBE_JS + '</script>'
CSP_META = re.compile(r'(<meta http-equiv="Content-Security-Policy" content=")[^"]*(")')


def report_figures(page):
    """[(src, alt)] of each report screenshot (<figure><img>), in order. Brand images (the cover logo) are not figures and are not listed."""
    out = []

    def walk(n, in_fig=False):
        if isinstance(n, str): return
        if n.tag == 'img' and in_fig: out.append((n.attrs.get('src', ''), n.attrs.get('alt', '')))
        for c in n.children: walk(c, in_fig or n.tag == 'figure')
    walk(parse_html(page))
    return out


def measure_logo_images(brand, title, date):
    """How many image objects the brand's logo adds to a PDF, measured: the cover alone (same brand stylesheet, no report body, no
    screenshots) is printed to a temporary PDF and its image objects are counted with the same counter (soft masks excluded). A PNG
    logo adds one, a pure-vector SVG none, an SVG that embeds a bitmap one or more. The temporary files are removed.
    Returns None if the cover cannot be printed: the caller must then stop, because guessing 0 would let the logo stand in for a
    missing screenshot."""
    page, _ = build_html(f'# {title}\n', {}, brand, date)
    d = tempfile.mkdtemp(prefix='qa-export-logo-')
    try:
        src, pdf = Path(d) / 'cover.html', Path(d) / 'cover.pdf'
        src.write_text(page, encoding='utf-8')
        ok, _ = print_pdf(src, pdf)
        if not (ok and pdf.is_file()): return None
        data = pdf.read_bytes()
        images, pages = count_pdf(data)
        # Only a complete PDF is a measurement: a header, at least one page and an end-of-file marker. A truncated file would
        # read as "the logo adds nothing", which is the unsafe direction.
        if not data.startswith(b'%PDF-') or pages < 1 or b'%%EOF' not in data[-1024:]: return None
        return images
    finally:
        shutil.rmtree(d, ignore_errors=True)


def probe_details(page):
    """Ask Chrome about every report screenshot, on the real page with all its styling (a throwaway copy with one inline script;
    the deliverable has none). Returns (ok, not_loaded, not_shown, error): figure indexes Chrome could not load, and figures that
    loaded but are hidden, clipped away or too small to see (a size of at least 40 x 40 CSS px, or the image's own size if smaller).
    Chrome draws a broken-image icon for an image it cannot load, and a PDF then still holds an image object, so counting PDF image
    objects alone cannot prove a screenshot loaded or is visible: this probe can."""
    probe = CSP_META.sub(r"\g<1>default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'\g<2>", page).replace('</body>', PROBE_SCRIPT + '</body>')
    d = tempfile.mkdtemp(prefix='qa-export-probe-')
    try:
        src, dump = Path(d) / 'probe.html', Path(d) / 'dom.txt'
        src.write_text(probe, encoding='utf-8')
        pat = re.compile(rb'<title>DECODE:([0-9,]*):SHOWN:([0-9,]*):END</title>')

        def ready():
            return dump.is_file() and bool(pat.search(dump.read_bytes()))

        try:
            run_chrome(['--dump-dom', '--window-size=1000,800', '--virtual-time-budget=3000'], src.resolve().as_uri(), ready, stdout_to=str(dump), limit=90)
        except OSError as e:
            return False, [], [], f'Chrome did not run ({type(e).__name__})'
        m = pat.search(dump.read_bytes()) if dump.is_file() else None
        if not m: return False, [], [], 'the Chrome image-load probe did not report'
        ints = lambda g: [int(x) for x in g.split(b',') if x]
        return True, ints(m.group(1)), ints(m.group(2)), ''
    finally:
        shutil.rmtree(d, ignore_errors=True)


def probe_decode(page):
    """(ok, bad_figure_indexes, error): every figure that did not load or is not visibly shown, see probe_details."""
    ok, load, hidden, err = probe_details(page)
    return ok, sorted(set(load) | set(hidden)), err


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('report'); ap.add_argument('--html'); ap.add_argument('--pdf')
    ap.add_argument('--allow-missing', action='store_true', help='export even if an embedded image is missing or invalid')
    ap.add_argument('--brand', metavar='DIR', help='brand pack folder (default: $QA_BRAND if set); see brand_check.py')
    ap.add_argument('--no-brand', action='store_true', help='ignore --brand and $QA_BRAND')
    ap.add_argument('--date', metavar='YYYY-MM-DD', help='date shown on the cover (default: today)')
    a = ap.parse_args(argv)
    if a.brand and a.no_brand: ap.error('--brand and --no-brand together make no sense')
    if a.date:
        try: datetime.date.fromisoformat(a.date)
        except ValueError: ap.error('--date must be YYYY-MM-DD')
    try:
        import markdown  # noqa: F401
    except ImportError:
        print('report_export: needs the python package "markdown" (pip install -r requirements.txt, in the scripts folder)', file=sys.stderr); return 2
    if not a.html and not a.pdf:
        ap.error('give --html and/or --pdf')
    report = Path(a.report)
    if not report.is_file():
        print(f'report_export: cannot read {report}', file=sys.stderr); return 2
    outs = [Path(x).resolve() for x in (a.html, a.pdf) if x]
    if report.resolve() in outs or len(set(outs)) != len(outs):
        print('report_export: an output path would overwrite the report or the other output', file=sys.stderr); return 2
    if a.pdf and not (os.path.isfile(CHROME) and os.access(CHROME, os.X_OK)):
        print(f'report_export: Chrome/Chromium not found or not executable at {CHROME}. Install Chrome or set CHROME_PATH.', file=sys.stderr); return 2
    brand_dir = None if a.no_brand else (a.brand or os.environ.get('QA_BRAND') or None)
    brand = None
    if not brand_dir and not a.no_brand:
        print('note: no brand set, so the report uses the neutral look. To add your logo, colours and fonts, see brand-example/README.md '
              'in the qa-standards skill, then set QA_BRAND (or pass --no-brand to silence this).')
    if brand_dir:
        try:
            bres = brand_check.check_brand(brand_dir)
        except NotADirectoryError:
            print(f'report_export: brand folder {brand_dir} is not a folder', file=sys.stderr); return 2
        for p in bres.problems: print(f'brand: {p}')
        if bres.problems:
            print(f'refusing to export: the brand pack has {len(bres.problems)} problem(s). Run brand_check.py on it, or use --no-brand.')
            return 1
        brand = bres.brand
    try:
        res = report_check.check(report)
    except (OSError, UnicodeDecodeError) as e:
        print(f'report_export: cannot read the report ({type(e).__name__})', file=sys.stderr); return 2
    for line, kind, msg in res.problems:
        print(f'{report.name}:{line}: {msg}')
    blocking = [p for p in res.problems if p[1] in report_check.BLOCKING]
    if blocking and not a.allow_missing:
        print(f'refusing to export: {len(blocking)} embedded image problem(s). Fix them, or pass --allow-missing to export with "image unavailable" boxes.')
        return 1
    images = {e['src']: {'path': e['path'], 'mime': e['mime']} for e in res.embedded if e['path']}
    page, rend = build_html(report.read_text(encoding='utf-8'), images, brand, a.date)
    validated = sum(1 for e in res.embedded if e['path'])
    non_png = sum(1 for e in res.embedded if e['path'] and e['mime'] != 'image/png')
    distinct = len(rend.inlined)
    if rend.figures + rend.unavailable != len(res.embedded):
        print(f'refusing to export: the checker found {len(res.embedded)} embedded images but the page has {rend.figures + rend.unavailable} figures. '
              'This is a bug: the checker and the exporter must read the report identically.')
        return 1
    if rend.figures != validated and not a.allow_missing:
        print(f'refusing to export: the checker validated {validated} embedded images but only {rend.figures} were inlined in the page '
              f'({rend.unavailable} became "image unavailable" boxes). Pass --allow-missing to export anyway.')
        return 1
    scratch = None
    try:
        html_path = Path(a.html) if a.html else None
        if not html_path:
            scratch = tempfile.mkdtemp(prefix='qa-export-html-'); html_path = Path(scratch) / 'report.html'
        html_path.write_text(page, encoding='utf-8')
        if a.html: print(f'HTML written: {html_path} ({distinct} distinct images inlined)')
        if non_png and not a.pdf:
            print(f'note: {non_png} JPEG/GIF/WebP image(s) were checked structurally only, not decoded; a --pdf export has Chrome load them.')
        if a.pdf:
            if brand and brand['footer']:
                major = chrome_major_version()
                if major is not None and major < FOOTER_MIN_CHROME:
                    print(f'note: Chrome {major} is older than {FOOTER_MIN_CHROME}: the brand footer will be missing from the PDF (page margin boxes need Chrome {FOOTER_MIN_CHROME} or later).')
            parsed = report_figures(page)   # report screenshots only: the cover logo is not a figure
            figures = [alt for _, alt in parsed]
            figures_src = [src for src, _ in parsed]
            ok, bad_load, bad_hidden, err = probe_details(page)
            if not ok:
                print(f'PDF export stopped: {err}', file=sys.stderr); return 1
            bad = sorted(set(bad_load) | set(bad_hidden))
            if bad:
                name = lambda k: f'image {k + 1} ("{figures[k] if k < len(figures) else "?"}")'
                if bad_load: print(f'{len(bad_load)} embedded image(s) cannot be loaded by Chrome: {"; ".join(map(name, bad_load))}.')
                if bad_hidden: print(f'{len(bad_hidden)} embedded image(s) loaded but are not visibly shown in the page (hidden, clipped, transparent or too small): {"; ".join(map(name, bad_hidden))}.')
                if not a.allow_missing:
                    print('Not exporting a PDF. Replace the files or fix the styling, or pass --allow-missing to export without them counted.')
                    return 1
                # Count failures per distinct image, as rend.inlined does: the same file embedded twice is one image.
                failed = {figures_src[k] for k in bad if k < len(figures_src)}
                distinct = max(0, distinct - len(failed))
            ok, err = print_pdf(html_path, a.pdf)
            if not ok:
                print(f'PDF export failed: {err}', file=sys.stderr); return 1
            logo_images = measure_logo_images(brand, first_h1(report.read_text(encoding="utf-8")), a.date) if brand and brand['logo'] and hashlib.sha1(brand['logo']['data']).hexdigest() not in rend.inlined else 0
            if logo_images is None:
                print('PDF export stopped: could not print the brand cover on its own to measure what the logo adds, so the screenshot '
                      f'count cannot be verified. The PDF was kept at {a.pdf}.', file=sys.stderr)
                return 1
            ok, msg, found = verify_pdf(a.pdf, distinct + logo_images)   # screenshots plus what the logo itself adds to a PDF (measured, not guessed)
            if not ok:
                print(msg); print(f'expected at least {distinct + logo_images} image objects ({distinct} distinct embedded screenshots + {logo_images} from the brand logo), found {found}. The PDF was kept at {a.pdf}.')
                return 1
            pages = count_pdf(Path(a.pdf).read_bytes())[1]
            print(f'PDF written: {a.pdf} ({pages} pages, {found} image objects found, {distinct} images verified)')
    finally:
        if scratch: shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
