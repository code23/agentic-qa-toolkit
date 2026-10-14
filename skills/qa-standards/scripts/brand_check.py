#!/usr/bin/env python3
"""Validate a brand pack folder for report_export.py --brand.

  python3 brand_check.py DIR

A brand pack is a folder holding:
  brand.json   required (schema below; unknown keys are errors so typos surface)
  logo.svg | logo.png | logo.webp | logo.jpg   optional, named in brand.json
  fonts/*.woff2 | .woff | .ttf | .otf          optional, named in brand.json
  cover.md     optional cover page template: {title} {date} {brand} {prepared_by} {contact} {confidentiality}
  report.css   optional extra styling (no @import, no url() that is not a data: URI)
  brand.md     optional, for the agent only (voice and structure); ignored here and by the exporter

brand.json:
  { "name": "Example Agency",                         required, plain text
    "colours": {"accent": "#0a5", "ink": "#112233", "muted": "#667", "paper": "#fff"},   each optional, #rgb or #rrggbb only
    "logo": "logo.svg",
    "fonts": {"heading": {"family": "X", "file": "fonts/x.woff2"}, "body": {"family": "Y", "file": "fonts/y.woff2"}},
    "cover": {"prepared_by": "...", "contact": "...", "confidentiality": "..."},        each optional, plain text
    "footer": "..." }                                                                     optional, plain text, every PDF page

Every file must be a regular file inside the brand folder (no symlinks, no `..`, no absolute paths). Image files must pass
report_check.py's structural image check (an SVG logo is only checked for being an <svg> document: it is embedded as an image,
so a script or external reference inside it cannot run or load). Fonts need a known font signature.

Exit: 0 clean, 1 problems, 2 usage error (not a folder, or the `markdown` package is missing).
"""
import argparse, base64, json, os, re, sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_check

TOP_KEYS = {'name', 'colours', 'logo', 'fonts', 'cover', 'footer'}
COLOUR_KEYS = ('accent', 'ink', 'muted', 'paper')
FONT_ROLES = ('heading', 'body')
COVER_KEYS = ('prepared_by', 'contact', 'confidentiality')
COLOUR_RE = re.compile(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})')
FAMILY_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9 _.,-]{0,59}')
LOGO_EXT = ('.svg', '.png', '.webp', '.jpg', '.jpeg')
FONT_SIGNATURES = {'.woff2': (b'wOF2',), '.woff': (b'wOFF',), '.ttf': (b'\x00\x01\x00\x00', b'true'), '.otf': (b'OTTO',)}
FONT_MIME = {'.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf'}
FONT_FORMAT = {'.woff2': 'woff2', '.woff': 'woff', '.ttf': 'truetype', '.otf': 'opentype'}
MAX_LOGO, MAX_FONT, MAX_TEXT_FILE = 2 * 1024 * 1024, 5 * 1024 * 1024, 200 * 1024
PLACEHOLDERS = ('title', 'date', 'brand', 'prepared_by', 'contact', 'confidentiality')


class Result:
    def __init__(self):
        self.problems, self.notes, self.brand = [], [], None

    def problem(self, where, msg): self.problems.append(f'{where}: {msg}')


def plain_text(value, limit):
    """None when value is acceptable plain text, else the reason."""
    if not isinstance(value, str) or not value.strip(): return 'must be non-empty text'
    if len(value) > limit: return f'is longer than {limit} characters'
    if re.search(r'[\x00-\x1f\x7f]', value): return 'must not contain control characters or line breaks'
    if '<' in value or '>' in value: return 'must be plain text (no < or >)'
    return None


def safe_file(root, rel, where, res):
    """Path of a regular file inside root named by rel, else None with a problem recorded. No symlinks, no .., no absolute paths."""
    if not isinstance(rel, str) or not rel.strip(): res.problem(where, 'must be a file name'); return None
    if '\\' in rel or rel.startswith('/') or re.match(r'^[A-Za-z]:', rel) or '\x00' in rel:
        res.problem(where, f'must be a relative path inside the brand folder: {rel!r}'); return None
    parts = PurePosixPath(rel).parts
    if not parts or any(p in ('..', '.') for p in parts):
        res.problem(where, f'must not contain . or .. segments: {rel!r}'); return None
    cur = root
    for part in parts:
        cur = cur / part
        if cur.is_symlink(): res.problem(where, f'{rel} is (or passes through) a symlink; copy the real file into the brand folder'); return None
    if not cur.exists(): res.problem(where, f'file does not exist: {rel}'); return None
    if not cur.is_file(): res.problem(where, f'not a regular file: {rel}'); return None
    return cur


def normalise_css(css):
    """Comments removed and CSS escapes decoded, so `u\\72l(` or `@\\69mport` cannot hide from the network rule."""
    css = re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)
    css = re.sub(r'\\([0-9a-fA-F]{1,6})\s?', lambda m: chr(min(int(m.group(1), 16), 0x10ffff)) if int(m.group(1), 16) else '', css)
    return re.sub(r'\\(.)', r'\1', css, flags=re.S)


def css_problems(css):
    out = []
    n = normalise_css(css)
    if '</' in css or '</' in n or '<!--' in css: out.append('contains markup (</style> would end the stylesheet)')
    if re.search(r'@import', n, re.I): out.append('uses @import')
    for m in re.finditer(r'url\s*\(\s*([\'"]?)(.*?)\1\s*\)', n, re.I | re.S):
        if not re.match(r'\s*data:', m.group(2), re.I): out.append(f'url() that is not a data: URI ({m.group(2)[:40]!r})')
    if re.search(r'url\s*\((?![^)]*\))', n, re.I): out.append('has an unterminated url(')
    if re.search(r'(?<![\w-])(?:-webkit-)?image-set\s*\(|(?<![\w-])src\s*\(|@namespace|expression\s*\(|javascript\s*:|behavior\s*:|-moz-binding', n, re.I):
        out.append('uses image-set(), src(), @namespace, expression() or another construct that can load or run something')
    return out


def check_brand(directory):
    res = Result()
    root = Path(directory)
    if not root.is_dir(): raise NotADirectoryError(str(directory))
    bj = safe_file(root, 'brand.json', 'brand.json', res)
    if not bj: return res
    try:
        raw = json.loads(bj.read_text(encoding='utf-8'))
    except (ValueError, OSError) as e:
        res.problem('brand.json', f'cannot be read as JSON ({type(e).__name__}: {str(e)[:120]})'); return res
    if not isinstance(raw, dict): res.problem('brand.json', 'must hold a JSON object'); return res
    for k in sorted(set(raw) - TOP_KEYS): res.problem('brand.json', f'unknown key {k!r} (allowed: {", ".join(sorted(TOP_KEYS))})')
    brand = {'name': None, 'colours': {}, 'logo': None, 'fonts': [], 'cover': {}, 'footer': None, 'cover_md': None, 'css': None}

    if 'name' not in raw: res.problem('name', 'is required')
    else:
        why = plain_text(raw['name'], 100)
        if why: res.problem('name', why)
        else: brand['name'] = raw['name'].strip()

    c = raw.get('colours')
    if c is not None:
        if not isinstance(c, dict): res.problem('colours', 'must be an object')
        else:
            for k in sorted(set(c) - set(COLOUR_KEYS)): res.problem('colours', f'unknown key {k!r} (allowed: {", ".join(COLOUR_KEYS)})')
            for k in COLOUR_KEYS:
                if k in c:
                    if isinstance(c[k], str) and COLOUR_RE.fullmatch(c[k]): brand['colours'][k] = c[k]
                    else: res.problem(f'colours.{k}', f'must be #rgb or #rrggbb, got {c[k]!r}')

    if raw.get('logo') is not None:
        p = safe_file(root, raw['logo'], 'logo', res)
        if p:
            ext = p.suffix.lower()
            data = p.read_bytes()
            if ext not in LOGO_EXT: res.problem('logo', f'must be one of {", ".join(LOGO_EXT)}')
            elif len(data) > MAX_LOGO: res.problem('logo', f'is larger than {MAX_LOGO // 1024} KB')
            elif ext == '.svg':
                text = data.decode('utf-8', 'replace')
                if '<svg' not in text.lower(): res.problem('logo', 'is not an SVG document (no <svg element)')
                elif re.search(r'<!ENTITY', text, re.I): res.problem('logo', 'SVG declares entities, which are not allowed')
                else:
                    brand['logo'] = {'mime': 'image/svg+xml', 'data': data}
                    if re.search(r'<script|\bon\w+\s*=|(?:href|src)\s*=\s*["\']?\s*(?:https?:|//)', text, re.I):
                        res.notes.append('logo SVG contains script, event handlers or external references; they are inert because the logo is embedded as an image, but remove them')
            else:
                mime, err = report_check.validate_image(data)
                if err: res.problem('logo', f'{err}')
                else: brand['logo'] = {'mime': mime, 'data': data}

    f = raw.get('fonts')
    if f is not None:
        if not isinstance(f, dict): res.problem('fonts', 'must be an object')
        else:
            for k in sorted(set(f) - set(FONT_ROLES)): res.problem('fonts', f'unknown key {k!r} (allowed: heading, body)')
            for role in FONT_ROLES:
                if role not in f: continue
                e, where = f[role], f'fonts.{role}'
                if not isinstance(e, dict): res.problem(where, 'must be an object with "family" and "file"'); continue
                for k in sorted(set(e) - {'family', 'file'}): res.problem(where, f'unknown key {k!r}')
                if not (isinstance(e.get('family'), str) and FAMILY_RE.fullmatch(e['family'])):
                    res.problem(where + '.family', 'must be a font name of letters, digits, spaces and - _ . , (max 60)'); continue
                p = safe_file(root, e.get('file'), where + '.file', res)
                if not p: continue
                ext = p.suffix.lower()
                if ext not in FONT_SIGNATURES: res.problem(where + '.file', 'must be .woff2, .woff, .ttf or .otf'); continue
                data = p.read_bytes()
                if len(data) > MAX_FONT: res.problem(where + '.file', f'is larger than {MAX_FONT // 1024 // 1024} MB'); continue
                if not data.startswith(FONT_SIGNATURES[ext]): res.problem(where + '.file', f'does not have a {ext[1:]} font signature'); continue
                brand['fonts'].append({'role': role, 'family': e['family'], 'ext': ext, 'data': data})

    cv = raw.get('cover')
    if cv is not None:
        if not isinstance(cv, dict): res.problem('cover', 'must be an object')
        else:
            for k in sorted(set(cv) - set(COVER_KEYS)): res.problem('cover', f'unknown key {k!r} (allowed: {", ".join(COVER_KEYS)})')
            for k in COVER_KEYS:
                if k in cv:
                    why = plain_text(cv[k], 300)
                    if why: res.problem(f'cover.{k}', why)
                    else: brand['cover'][k] = cv[k].strip()

    if raw.get('footer') is not None:
        why = plain_text(raw['footer'], 300)
        if why: res.problem('footer', why)
        else: brand['footer'] = raw['footer'].strip()

    for name, key in (('cover.md', 'cover_md'), ('report.css', 'css')):
        if not (root / name).exists() and not (root / name).is_symlink(): continue
        p = safe_file(root, name, name, res)
        if not p: continue
        if p.stat().st_size > MAX_TEXT_FILE: res.problem(name, f'is larger than {MAX_TEXT_FILE // 1024} KB'); continue
        try:
            text = p.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            res.problem(name, 'is not UTF-8 text'); continue
        if name == 'report.css':
            bad = css_problems(text)
            for b in bad: res.problem(name, b)
            if not bad: brand[key] = text
        else:
            if report_check.parsed_images(text): res.problem(name, 'must not contain images (the logo is placed on the cover for you)'); continue
            brand[key] = text
    if not res.problems: res.brand = brand
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir', help='the brand pack folder')
    a = ap.parse_args(argv)
    try:
        import markdown  # noqa: F401
    except ImportError:
        print('brand_check: needs the python package "markdown" (pip install -r requirements.txt, in the scripts folder)', file=sys.stderr); return 2
    try:
        res = check_brand(a.dir)
    except NotADirectoryError:
        print(f'brand_check: {a.dir} is not a folder', file=sys.stderr); return 2
    for p in res.problems: print(p)
    for n in res.notes: print(f'note: {n}')
    print(f'brand pack {(res.brand or {}).get("name") or os.path.basename(os.path.abspath(a.dir))}: {len(res.problems)} problems')
    return 1 if res.problems else 0


if __name__ == '__main__':
    sys.exit(main())
