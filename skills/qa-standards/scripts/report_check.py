#!/usr/bin/env python3
"""Check that a QA report carries its screenshots: every image a report relies on must be embedded in report.md.

  python3 report_check.py RUN/report.md [--findings RUN/findings.json] [--strict]

Convention: a run folder holds report.md, optional summary.md and findings.json, and images under screenshots/ (or evidence/).
A finding that rests on a screenshot embeds it directly under the finding as a captioned Markdown image,
`![what it shows](screenshots/file.png)`. Naming a file in an "Evidence:" line or an evidence index is not enough.

Errors (exit 1): an embedded image whose file does not exist, is empty, or is not a real PNG/JPEG/WebP/GIF; a target that is
absolute, a URL (http, https, data, file ...) or resolves outside the run folder (`..` and symlinks are followed); an embedded
image with empty alt text; an image path mentioned in the text (inline code, evidence lines, tables, links) but never
embedded; with --findings, a finding whose "evidence" list names an image that is not embedded.
Notes (errors only with --strict): image files in screenshots/ or evidence/ that nothing references; findings but no embedded image.
Embedded images are read from the PARSED document (python-markdown, the same parser report_export.py uses), so image syntax
inside inline code, fenced or indented code blocks, or with an escaped `!` is text, not an image.

How far an image file is validated (the limit, stated plainly):
  PNG            decoded in full with the standard library: chunk checksums, then the pixel stream is decompressed (with a size
                 cap) and its length and row filter bytes are checked against the header. Interlaced (Adam7) PNGs are supported.
  JPEG, GIF, WebP  structural checks only (JPEG: frame header with a size, scan data, end marker; GIF: image block with data,
                 trailer; WebP: RIFF size, an image chunk with a valid frame header). This does NOT prove the image decodes.
                 report_export.py --pdf goes further: it asks Chrome to load every image before printing (Chrome's own decoder must
                 accept the file and report its size; damage deep inside the pixel data of a JPEG/GIF/WebP can still get through).
Paths inside fenced code blocks are ignored.
Needs the `markdown` package (requirements.txt); without it the check exits 2.

Output: one line per problem with the report line number, then `N images embedded, N problems`.
Exit: 0 clean, 1 problems, 2 usage error (unreadable report or findings file, or `markdown` not installed).
"""
import argparse, json, os, re, struct, sys, zlib
from html.parser import HTMLParser
from pathlib import Path

IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
EMBED = re.compile(r'!\[((?:[^\]\\]|\\.)*)\]\(\s*(<[^>]*>|[^)\s]*)(?:\s+(?:"[^"]*"|\'[^\']*\'))?\s*\)')
MENTION = re.compile(r'[^\s`"\'()<>\[\]|,;=]+\.(?:png|jpe?g|webp|gif)(?![\w-])(?!\.\w)', re.I)
SCHEME = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*:')
FENCE = re.compile(r'^\s{0,3}(`{3,}|~{3,})')
# error kinds that make an export refuse: the image cannot be inlined
BLOCKING = ('missing', 'unsafe', 'invalid')


def sniff(head):
    """Image type from the first bytes, or None (first-bytes check only; validate_image checks the whole file)."""
    if head.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if head.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if head[:6] in (b'GIF87a', b'GIF89a'): return 'image/gif'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP': return 'image/webp'
    return None


# Limits that keep a hostile PNG from exhausting memory: decompression stops at the size IHDR implies, which itself is capped.
MAX_PNG_SIDE = 65535
MAX_PNG_PIXEL_BYTES = 256 * 1024 * 1024
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def _png_passes(width, height, bpp, interlaced):
    """[(rows, bytes per row including the filter byte)] for each stored pass: one for a plain PNG, up to seven for Adam7."""
    if not interlaced:
        return [(height, 1 + (width * bpp + 7) // 8)]
    out = []
    for x0, y0, dx, dy in _ADAM7:
        w, h = (width - x0 + dx - 1) // dx if width > x0 else 0, (height - y0 + dy - 1) // dy if height > y0 else 0
        if w and h: out.append((h, 1 + (w * bpp + 7) // 8))
    return out


def _png_error(d):
    """Decodes a PNG as far as the standard library allows: chunk walk with checksums, then the pixel stream is decompressed
    (with a size cap) and its length and per-row filter bytes are checked against what IHDR implies."""
    if len(d) < 33 or d[12:16] != b'IHDR' or struct.unpack('>I', d[8:12])[0] != 13:
        return 'PNG header chunk (IHDR) is missing or damaged'
    w, h, depth, ctype, comp, filt, inter = struct.unpack('>IIBBBBB', d[16:29])
    if not w or not h: return 'PNG has zero width or height'
    if w > MAX_PNG_SIDE or h > MAX_PNG_SIDE: return f'PNG declares {w}x{h} pixels, over the {MAX_PNG_SIDE} per side limit'
    if ctype not in _DEPTHS or depth not in _DEPTHS[ctype] or comp != 0 or filt != 0 or inter not in (0, 1):
        return 'PNG header (IHDR) holds an invalid colour type, bit depth or method'
    passes = _png_passes(w, h, _CHANNELS[ctype] * depth, inter == 1)
    expected = sum(rows * rowlen for rows, rowlen in passes)
    if expected > MAX_PNG_PIXEL_BYTES: return f'PNG declares {expected // (1024 * 1024)} MB of pixel data, over the {MAX_PNG_PIXEL_BYTES // (1024 * 1024)} MB limit'
    pos, idat, iend, plte = 8, [], False, False
    while pos + 12 <= len(d):
        ln, kind = struct.unpack('>I', d[pos:pos + 4])[0], d[pos + 4:pos + 8]
        end = pos + 12 + ln
        if end > len(d): return 'PNG is truncated (a chunk runs past the end of the file)'
        if zlib.crc32(d[pos + 4:pos + 8 + ln]) & 0xffffffff != struct.unpack('>I', d[end - 4:end])[0]:
            return f'PNG is damaged (bad checksum in the {kind.decode("latin-1")} chunk)'
        if kind == b'IDAT': idat.append(d[pos + 8:pos + 8 + ln])
        plte = plte or kind == b'PLTE'
        pos = end
        if kind == b'IEND': iend = True; break
    if not iend: return 'PNG is truncated (no IEND chunk)'
    if not idat: return 'PNG has no image data (no IDAT chunk)'
    if ctype == 3 and not plte: return 'PNG uses a palette but has no PLTE chunk'
    dec, out = zlib.decompressobj(), bytearray()
    try:
        for part in idat:
            data = part
            while data and len(out) <= expected:
                out += dec.decompress(data, expected + 1 - len(out))
                data = dec.unconsumed_tail
            if len(out) > expected: break
        if len(out) <= expected: out += dec.flush(expected + 1 - len(out))
    except zlib.error:
        return 'PNG pixel data does not decompress (damaged image data)'
    if len(out) > expected: return f'PNG pixel data is longer than its header implies ({expected} bytes expected)'
    if len(out) < expected or not dec.eof: return f'PNG pixel data is incomplete ({len(out)} of {expected} bytes decompress)'
    off = 0
    for rows, rowlen in passes:
        if any(out[off + r * rowlen] > 4 for r in range(rows)): return 'PNG pixel data has an invalid row filter'
        off += rows * rowlen
    return None


_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_error(d):
    """Structure only: SOI, a frame header with a size, a start-of-scan followed by entropy data, EOI. Does not decode."""
    pos, frame, scan = 2, False, None
    while pos + 4 <= len(d):
        if d[pos] != 0xFF: break
        marker = d[pos + 1]
        if marker == 0xFF: pos += 1; continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7: pos += 2; continue
        ln = struct.unpack('>H', d[pos + 2:pos + 4])[0]
        if marker in _SOF:
            if pos + 9 > len(d): return 'JPEG is truncated inside its frame header'
            h, w = struct.unpack('>HH', d[pos + 5:pos + 9])
            if not w or not h: return 'JPEG has zero width or height'
            frame = True
        if marker == 0xDA:
            scan = pos + 2 + ln
            break
        pos += 2 + ln
    if not frame: return 'JPEG has no frame header with a size'
    if scan is None: return 'JPEG has no start-of-scan segment (no image data)'
    body = d.rstrip(b'\x00')
    if not body.endswith(b'\xff\xd9'): return 'JPEG is truncated (no end marker)'
    if scan >= len(body) - 2: return 'JPEG has no image data between its scan header and end marker'
    return None


def _gif_error(d):
    """Structure only: header, logical screen, at least one non-empty image block with data, trailer. Does not decode."""
    if len(d) < 14: return 'GIF is truncated (shorter than its header)'
    w, h = struct.unpack('<HH', d[6:10])
    if not w or not h: return 'GIF has zero width or height'
    flags, pos = d[10], 13
    if flags & 0x80: pos += 3 * (2 << (flags & 7))
    images = 0
    while pos < len(d):
        b = d[pos]
        if b == 0x3B: return None if images else 'GIF has no image block (no pixels)'
        if b == 0x21:   # extension: label, then sub-blocks
            pos += 2
        elif b == 0x2C:
            if pos + 10 > len(d): return 'GIF is truncated inside an image descriptor'
            iw, ih, f = struct.unpack('<HH', d[pos + 5:pos + 9])[0:2] + (d[pos + 9],)
            if not iw or not ih: return 'GIF image block has zero width or height'
            pos += 10
            if f & 0x80: pos += 3 * (2 << (f & 7))
            pos += 1   # LZW minimum code size
            if pos >= len(d) or d[pos] == 0: return 'GIF image block has no pixel data'
            images += 1
        else:
            return 'GIF is damaged (unknown block type)'
        while pos < len(d) and d[pos] != 0:   # sub-blocks
            pos += 1 + d[pos]
        pos += 1
    return 'GIF is truncated (no trailer)'


def _webp_error(d):
    """Structure only: RIFF size, WEBP, then an image chunk with a payload and a frame header with a size. Does not decode."""
    if len(d) < 20: return 'WebP is truncated (shorter than its header)'
    riff = struct.unpack('<I', d[4:8])[0]
    if riff + 8 > len(d): return f'WebP is truncated (its header says {riff + 8} bytes, the file has {len(d)})'
    pos, end, found = 12, riff + 8, False
    while pos + 8 <= end:
        kind, ln = d[pos:pos + 4], struct.unpack('<I', d[pos + 4:pos + 8])[0]
        body = d[pos + 8:pos + 8 + ln]
        if pos + 8 + ln > end: return 'WebP is truncated (a chunk runs past the end)'
        if kind == b'VP8 ':
            if len(body) < 10 or body[3:6] != b'\x9d\x01\x2a': return 'WebP image chunk (VP8) has no valid frame header'
            if not (struct.unpack('<H', body[6:8])[0] & 0x3fff and struct.unpack('<H', body[8:10])[0] & 0x3fff): return 'WebP frame has zero width or height'
            found = True
        elif kind == b'VP8L':
            if len(body) < 6 or body[0] != 0x2f: return 'WebP image chunk (VP8L) has no valid frame header'
            found = True
        elif kind == b'VP8X':
            if len(body) < 10: return 'WebP extended header (VP8X) is too short'
        elif kind == b'ANMF':
            if len(body) < 24: return 'WebP animation frame is too short'
            found = True
        pos += 8 + ln + (ln & 1)
    return None if found else 'WebP has no image chunk with data (VP8, VP8L or animation frame)'


STRUCTURAL_ONLY = ('PNG files are decoded in full. JPEG, GIF and WebP are checked structurally only: that does not prove the image '
                   'decodes (report_export.py --pdf asks Chrome to load every image before printing).')


def validate_image(data):
    """(mime, None) for a sound image, else (None, message). PNG is decoded; JPEG, GIF and WebP are structural checks only."""
    mime = sniff(data[:16])
    if not mime: return None, 'file is not a real PNG/JPEG/WebP/GIF image'
    err = {'image/png': _png_error, 'image/jpeg': _jpeg_error, 'image/gif': _gif_error, 'image/webp': _webp_error}[mime](data)
    return (None, err) if err else (mime, None)


def escape_html_extension():
    """python-markdown extension: raw HTML is escaped into text instead of passed through."""
    from markdown.extensions import Extension

    class EscapeHtml(Extension):
        def extendMarkdown(self, md):
            md.preprocessors.deregister('html_block')
            md.inlinePatterns.deregister('html')
    return EscapeHtml()


def render_markdown(text):
    """The one Markdown pipeline shared by the checker and the exporter."""
    import markdown
    return markdown.markdown(text, extensions=['tables', 'fenced_code', escape_html_extension()])


class _ImgCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            a = dict(attrs)
            self.images.append((a.get('src') or '', a.get('alt') or ''))

    handle_startendtag = handle_starttag


def parsed_images_of_html(html_text):
    """[(src, alt)] of the <img> elements of an HTML string, in order."""
    c = _ImgCollector(); c.feed(html_text); c.close()
    return c.images


def parsed_images(text):
    """[(src, alt)] of every image in the parsed document, in order. Code spans, code blocks and escaped `!` are not images."""
    c = _ImgCollector(); c.feed(render_markdown(text)); c.close()
    return c.images


def _unquote(t):
    from urllib.parse import unquote
    t = t.strip()
    if t.startswith('<') and t.endswith('>'): t = t[1:-1]
    return unquote(t).replace('\\', '/')


def _is_absolute(t):
    return t.startswith('/') or t.startswith('~') or bool(re.match(r'^[a-zA-Z]:/', t))


class Result:
    def __init__(self):
        self.problems = []    # (line, kind, message)
        self.notes = []       # (line, message)
        self.embedded = []    # dicts: line, alt, target, path (Path|None when unusable), mime
        self.mentions = []    # (line, text)
        self.limits = []      # statements about what the checks did not prove

    def problem(self, line, kind, msg): self.problems.append((line, kind, msg))


def _text_lines(text):
    """(line_number, text) for every line outside fenced code blocks."""
    out, fence = [], None
    for n, line in enumerate(text.splitlines(), start=1):
        m = FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and line.strip().strip(fence[0]) == '':
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        out.append((n, line))
    return out


def _rel(run_dir, target):
    """Normalised relative path of a mentioned file (no leading ./)."""
    return os.path.normpath(_unquote(target)).replace('\\', '/')


def check(report, findings=None, strict=False):
    report = Path(report)
    run_dir = report.resolve().parent
    run_real = Path(os.path.realpath(run_dir))
    res = Result()
    text = report.read_text(encoding='utf-8')
    lines = _text_lines(text)
    embedded_keys = set()    # resolved relative paths of embedded images (for matching mentions)
    embedded_names = set()

    # Which images exist comes from the parsed document. Candidates found by regex only supply line numbers, and the spans of the
    # ones that matched are hidden from the "mentioned in text" scan. Candidates inside code spans or after a backslash are skipped.
    cands = []
    for n, line in lines:
        code = [(m.start(), m.end()) for m in re.finditer(r'(`+).+?\1', line)]
        for m in EMBED.finditer(line):
            if any(a <= m.start() < b for a, b in code) or (m.start() and line[m.start() - 1] == '\\'): continue
            cands.append((n, m.span(), _unquote(m.group(2))))
    hidden = {}    # line -> [(start, end)] of embeds confirmed by the parser
    ci = 0
    for src, alt in parsed_images(text):
        target = _unquote(src)
        n = 0
        for k in range(ci, len(cands)):
            if cands[k][2] == target:
                n = cands[k][0]; hidden.setdefault(n, []).append(cands[k][1]); ci = k + 1; break
        alt = alt.strip()
        item = {'line': n, 'alt': alt, 'target': src, 'src': src, 'path': None, 'mime': None}
        res.embedded.append(item)
        if not alt: res.problem(n, 'alt', f'image has empty alt text (caption): {src}')
        if SCHEME.match(target) and not re.match(r'^[a-zA-Z]:/', target):
            res.problem(n, 'unsafe', f'image target is a URL, not a file in the run folder: {target.split(":", 1)[0]}:...'); continue
        if _is_absolute(target):
            res.problem(n, 'unsafe', f'image target is an absolute path: {target}'); continue
        real = Path(os.path.realpath(run_dir / target))
        try:
            real.relative_to(run_real)
        except ValueError:
            res.problem(n, 'unsafe', f'image resolves outside the run folder: {target}'); continue
        if not target.lower().endswith(IMG_EXT):
            res.problem(n, 'invalid', f'embedded target is not an image file (.png .jpg .jpeg .webp .gif): {target}'); continue
        embedded_keys.add(os.path.normpath(target).replace('\\', '/'))
        embedded_names.add(os.path.basename(target).lower())
        embedded_keys.add(str(real.relative_to(run_real)).replace('\\', '/'))
        if not real.is_file():
            res.problem(n, 'missing', f'image file does not exist: {target}'); continue
        try:
            data = real.read_bytes()
        except OSError as e:
            res.problem(n, 'invalid', f'image file cannot be read: {target} ({type(e).__name__})'); continue
        if not data:
            res.problem(n, 'invalid', f'image file is empty: {target}'); continue
        mime, err = validate_image(data)
        if err:
            res.problem(n, 'invalid', f'{err}: {target}'); continue
        item['path'], item['mime'] = real, mime

    def is_embedded(path_text):
        key = os.path.normpath(_unquote(path_text)).replace('\\', '/')
        if key in embedded_keys: return True
        return '/' not in key and key.lower() in embedded_names

    mentioned = set()
    for n, line in lines:
        rest = line
        for a0, b0 in sorted(hidden.get(n, []), reverse=True): rest = rest[:a0] + ' ' * (b0 - a0) + rest[b0:]
        for m in MENTION.finditer(rest):
            tok = m.group(0)
            if SCHEME.match(tok) or tok.startswith('//'): continue
            res.mentions.append((n, tok))
            mentioned.add(os.path.normpath(_unquote(tok)).replace('\\', '/'))
            if not is_embedded(tok):
                res.problem(n, 'unembedded', f'image referenced but not embedded: {tok} (embed it as ![caption]({tok}))')

    n_findings = 0
    if findings is not None:
        data = json.loads(Path(findings).read_text(encoding='utf-8'))
        items = data.get('findings') if isinstance(data, dict) else None
        for f in items if isinstance(items, list) else []:
            if not isinstance(f, dict): continue
            n_findings += 1
            ev = f.get('evidence')
            for entry in ev if isinstance(ev, list) else []:
                for m in MENTION.finditer(entry if isinstance(entry, str) else ''):
                    mentioned.add(os.path.normpath(_unquote(m.group(0))).replace('\\', '/'))
                    if not SCHEME.match(m.group(0)) and not is_embedded(m.group(0)):
                        res.problem(0, 'finding', f'finding {f.get("id", "?")}: evidence image not embedded in the report: {m.group(0)}')

    for sub in ('screenshots', 'evidence'):
        d = run_dir / sub
        if d.is_dir():
            for p in sorted(d.rglob('*')):
                if p.is_file() and p.suffix.lower() in IMG_EXT:
                    rel = str(p.relative_to(run_dir)).replace(os.sep, '/')
                    if rel not in mentioned and rel not in embedded_keys and p.name.lower() not in embedded_names:
                        res.notes.append((0, f'image file never referenced: {rel}'))
    if any(e['mime'] and e['mime'] != 'image/png' for e in res.embedded): res.limits.append(STRUCTURAL_ONLY)
    if n_findings and not res.embedded:
        res.notes.append((0, f'{n_findings} findings but no embedded images'))
    if strict:
        for _, msg in res.notes: res.problems.append((0, 'note', msg))
        res.notes = []
    res.problems.sort(key=lambda p: p[0])
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('report', help='RUN/report.md')
    ap.add_argument('--findings', help='RUN/findings.json: cross-check each finding\'s evidence images')
    ap.add_argument('--strict', action='store_true', help='treat notes as errors')
    a = ap.parse_args(argv)
    try:
        import markdown  # noqa: F401
    except ImportError:
        print('report_check: needs the python package "markdown" (pip install -r requirements.txt, in the scripts folder)', file=sys.stderr); return 2
    try:
        res = check(a.report, a.findings, a.strict)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        print(f'report_check: cannot read input ({type(e).__name__}: {str(e)[:160]})', file=sys.stderr); return 2
    name = os.path.basename(a.report)
    for line, kind, msg in res.problems: print(f'{name}:{line}: {msg}' if line else f'{name}: {msg}')
    for _, msg in res.notes: print(f'note: {msg}')
    for msg in res.limits: print(f'note: {msg}')
    print(f'{len(res.embedded)} images embedded, {len(res.problems)} problems')
    return 1 if res.problems else 0


if __name__ == '__main__':
    sys.exit(main())
