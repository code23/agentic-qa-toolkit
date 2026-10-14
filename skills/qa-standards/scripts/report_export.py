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

Needs the `markdown` package (see requirements.txt). Never overwrites the source report.
Exit: 0 done, 1 refused or verification failed, 2 usage error or missing dependency / Chrome.
"""
import argparse, base64, hashlib, html, os, re, shutil, subprocess, sys, tempfile, time
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_check

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


def build_html(report_text, images):
    """(html_text, renderer). Raw HTML in the source is escaped; only allow-listed elements survive. The renderer reports how many
    figures were inlined (renderer.figures), how many were replaced by unavailable boxes and the distinct inlined images."""
    r = Renderer(images)
    body = r.render(parse_html(report_check.render_markdown(report_text)))
    m = re.search(r'^#\s+(.+?)\s*#*\s*$', report_text, re.M)
    title = esc(re.sub(r'[`*_]', '', m.group(1))) if m else 'QA report'
    page = (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title}</title>\n'
            f'<style>{CSS}</style></head>\n<body>\n{body}\n</body></html>\n')
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


PROBE_SCRIPT = ("<script>window.addEventListener('load',function(){var bad=[];Array.prototype.forEach.call(document.images,function(i,n){"
                "if(!(i.complete&&i.naturalWidth>0&&i.naturalHeight>0))bad.push(n)});document.title='DECODE:'+bad.join(',')+':END'})</script>")


def probe_decode(page):
    """Ask Chrome to load every image of the page (a throwaway copy of it with one inline script; the deliverable has none).
    Returns (ok, bad_figure_indexes, error). Chrome draws a broken-image icon for an image it cannot load, and a PDF then still
    holds an image object, so counting PDF image objects alone cannot prove a screenshot loaded: this probe can."""
    probe = page.replace(CSP, "default-src 'none'; img-src data:; script-src 'unsafe-inline'").replace('</body>', PROBE_SCRIPT + '</body>')
    d = tempfile.mkdtemp(prefix='qa-export-probe-')
    try:
        src, dump = Path(d) / 'probe.html', Path(d) / 'dom.txt'
        src.write_text(probe, encoding='utf-8')
        pat = re.compile(rb'<title>DECODE:([0-9,]*):END</title>')

        def ready():
            return dump.is_file() and bool(pat.search(dump.read_bytes()))

        try:
            run_chrome(['--dump-dom', '--virtual-time-budget=3000'], src.resolve().as_uri(), ready, stdout_to=str(dump), limit=90)
        except OSError as e:
            return False, [], f'Chrome did not run ({type(e).__name__})'
        m = pat.search(dump.read_bytes()) if dump.is_file() else None
        if not m: return False, [], 'the Chrome image-load probe did not report'
        return True, [int(x) for x in m.group(1).split(b',') if x], ''
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('report'); ap.add_argument('--html'); ap.add_argument('--pdf')
    ap.add_argument('--allow-missing', action='store_true', help='export even if an embedded image is missing or invalid')
    a = ap.parse_args(argv)
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
    page, rend = build_html(report.read_text(encoding='utf-8'), images)
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
            parsed = report_check.parsed_images_of_html(page)
            figures = [alt for _, alt in parsed]
            figures_src = [src for src, _ in parsed]
            ok, bad, err = probe_decode(page)
            if not ok:
                print(f'PDF export stopped: {err}', file=sys.stderr); return 1
            if bad:
                names = '; '.join(f'image {k + 1} ("{figures[k] if k < len(figures) else "?"}")' for k in bad)
                print(f'{len(bad)} embedded image(s) cannot be loaded by Chrome: {names}.')
                if not a.allow_missing:
                    print('Not exporting a PDF. Replace the files, or pass --allow-missing to export without them counted.')
                    return 1
                # Count failures per distinct image, as rend.inlined does: the same file embedded twice is one image.
                failed = {figures_src[k] for k in bad if k < len(figures_src)}
                distinct = max(0, distinct - len(failed))
            ok, err = print_pdf(html_path, a.pdf)
            if not ok:
                print(f'PDF export failed: {err}', file=sys.stderr); return 1
            ok, msg, found = verify_pdf(a.pdf, distinct)
            if not ok:
                print(msg); print(f'expected at least {distinct} image objects for {distinct} distinct embedded images, found {found}. The PDF was kept at {a.pdf}.')
                return 1
            pages = count_pdf(Path(a.pdf).read_bytes())[1]
            print(f'PDF written: {a.pdf} ({pages} pages, {found} image objects found, {distinct} images verified)')
    finally:
        if scratch: shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
