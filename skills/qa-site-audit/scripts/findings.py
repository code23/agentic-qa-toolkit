#!/usr/bin/env python3
"""findings.json helper: validation, stable fingerprints, coverage-aware suggested scores, and regression diff between runs.

  python3 findings.py template > findings.json          # skeleton to fill in (every dimension starts not-executed)
  python3 findings.py check   RUN/findings.json         # validate; only when valid, (re)compute fingerprints in place
  python3 findings.py score   RUN/findings.json         # suggested 0-10 per dimension, or "not scored" (rubric: references/scoring-rubric.md)
  python3 findings.py diff    RUN/findings.json [--previous OLD/findings.json] [--runs-root ~/qa-runs] [--out RUN/regression.md]

Identity: each finding has an optional 'scope': 'template' (default; one root cause in that template), 'page' (this URL
only) or 'sitewide'. Fingerprint = sha1(normalised rule | normalised template [| url path, only for scope 'page'])[:12];
sitewide findings use the template 'sitewide'. Keep 'rule' stable (axe rule id, script flag such as 'overflow-x:1024',
'nav-missing-item:about') so the same defect matches across runs even if the title, dimension or representative URL changes.
Fingerprints are always recomputed; a changed one is reported. Files without 'scope' are read as scope 'template'.

Scoring needs a 'coverage' entry for every dimension: executed (scored; needs a non-empty 'checks' list), partial (capped
at 8, note required), blocked / not-in-scope / not-executed (not scored). Open, accepted-risk, wont-fix and not-retested
findings all deduct (only 'fixed' is excluded); a not-retested finding also makes its dimension partial.
Regression needs 'checks_run' ([{rule, template, url?}], rule may end in '*' as a prefix wildcard, template may be '*'):
a previous finding missing now is 'fixed' only when its rule and template were re-run and, for scope 'page', a check
names the same URL path; otherwise it is 'not_retested'. Every previous finding that is not 'fixed' is compared: one that is absent now and
was not re-run keeps its disposition (not-retested, wont-fix or accepted-risk); a present one is 'still open', never 'new'.
diff always writes regression.json next to findings.json (also for a baseline run).
Exit: 0 OK, 1 validation errors (file left untouched), 2 usage error.
"""
import argparse, datetime, glob, hashlib, json, os, re, sys
from urllib.parse import urlparse

SEV = {'S1', 'S2', 'S3', 'S4', 'IMP'}   # IMP kept for older files; new runs put improvements in the 'improvements' array
VER = {'independently-reproduced', 'evidence-reviewed', 'provisional'}
LABELS = {'DET', 'JUDG', 'DET+JUDG'}
STATUS = {'open', 'fixed', 'not-retested', 'wont-fix', 'accepted-risk'}
SCOPES = {'template', 'page', 'sitewide'}
DIMS = ['qa-functional', 'ux', 'accessibility', 'performance', 'seo-ai', 'security-privacy', 'content', 'cms-code']
DISPLAY = {'qa-functional': 'Functional QA', 'ux': 'User experience', 'accessibility': 'Accessibility', 'performance': 'Speed and performance',
           'seo-ai': 'Search & AI visibility', 'security-privacy': 'Security & privacy', 'content': 'Content quality', 'cms-code': 'CMS & code'}
COVERAGE = {'executed', 'partial', 'blocked', 'not-in-scope', 'not-executed'}
REQ = ['id', 'title', 'severity', 'verification', 'label', 'dimension', 'template', 'url', 'rule', 'status']
PEN = {'S1': 6, 'S2': 4, 'S3': 2, 'S4': 0.5}
BANDS = [(9, 'Strong. Polish only'), (7, 'Good, with clear fixes'), (5, 'Needs work. Visible to users'), (3, 'Significant problems'), (0, 'Critical. Fix before promoting')]


def norm(s): return re.sub(r'[^a-z0-9:]+', ' ', (s if isinstance(s, str) else '').lower()).strip()


def url_path(u):
    try: return urlparse(u if isinstance(u, str) else '').path or '/'
    except ValueError: return '/'


def scope_of(f): return f.get('scope') or 'template'


def identity(f):
    """(rule, template, path|None) used for the fingerprint and for retest matching."""
    sc = scope_of(f)
    return (norm(f.get('rule') or f.get('title')), 'sitewide' if sc == 'sitewide' else norm(f.get('template')),
            url_path(f.get('url')) if sc == 'page' else None)


def fp(f):
    rule, tpl, path = identity(f)
    return hashlib.sha1('|'.join([rule, tpl] + ([path] if path is not None else [])).encode()).hexdigest()[:12]


def fail(msgs, code=1):
    print('\n'.join(msgs)); print(f'{len(msgs)} error(s); file not modified'); sys.exit(code)


def load(p):
    try:
        with open(p, encoding='utf-8') as fh: return json.load(fh)
    except (OSError, ValueError) as e:
        fail([f'{p}: cannot read JSON ({type(e).__name__}: {str(e)[:160]})'])


def save(p, d):
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh: json.dump(d, fh, indent=1)
    os.replace(tmp, p)


def cmd_template(_):
    print(json.dumps({'run_id': 'example-com-YYYY-MM-DD', 'target': 'https://example.com', 'date': str(datetime.date.today()),
        'verdict': 'PASS | PASS WITH CONDITIONS | FAIL | INCONCLUSIVE', 'scores': {d: None for d in DIMS},
        'coverage': {d: {'status': 'not-executed', 'checks': [], 'note': ''} for d in DIMS},
        'checks_run': [],
        'tooling': {'lighthouse': 'x.y.z', 'lighthouse_runs': 3, 'axe-core': 'x.y.z'},
        'findings': [],
        'improvements': [],
        '_examples': {
            '_note': 'Examples only; ignored by check/score/diff. Copy the shapes into the real keys above, then delete this block if you like.',
            'coverage': {'accessibility': {'status': 'partial', 'checks': ['axe: home, service, contact'], 'note': 'no keyboard walk on mobile'},
                         'ux': {'status': 'executed', 'checks': ['executor walk: home, service, contact']},
                         'cms-code': {'status': 'not-in-scope', 'checks': [], 'note': 'not in the charter'}},
            'checks_run': [{'rule': 'axe:*', 'template': 'author', 'url': 'https://example.com/authors/x/'}, {'rule': 'overflow-x:*', 'template': '*'}],
            'findings': [{'id': 'RUN-01', 'title': 'Symptom, one line', 'severity': 'S3', 'priority': 'P2', 'verification': 'independently-reproduced',
                          'label': 'DET', 'dimension': 'accessibility', 'template': 'author', 'url': 'https://example.com/authors/x/', 'rule': 'color-contrast:header',
                          'scope': 'template', 'status': 'open', 'instances': 1, 'evidence': ['screenshots/lead-x.png'], 'fingerprint': None}],
            'improvements': [{'id': 'IMP-01', 'title': 'Recommendation, one line', 'dimension': 'ux', 'rationale': 'why'}]}}, indent=1))


def _str(x): return isinstance(x, str) and x.strip() != ''


def _http_url(x):
    if not _str(x): return False
    try: p = urlparse(x); return p.scheme in ('http', 'https') and bool(p.hostname)
    except ValueError: return False


def validate(d, strict=True):
    """List of errors. strict = the current run (check/score/diff current); otherwise a compatibility check for older
    previous runs: types are still enforced (no crashes later), but newer required fields may be missing."""
    errs = []
    if not isinstance(d, dict): return ['top level must be an object']
    for k in ('run_id', 'target', 'date'):
        if k in d and not isinstance(d[k], str): errs.append(f'{k} must be a string')
        elif strict and not _str(d.get(k)): errs.append(f'missing run field {k}')
    if strict and _str(d.get('target')) and not _http_url(d['target']): errs.append('target must be an http(s) URL')
    if strict and _str(d.get('date')):
        try: datetime.date.fromisoformat(d['date'])
        except ValueError: errs.append('date must be YYYY-MM-DD')
    if not isinstance(d.get('findings'), list): errs.append('findings must be a list'); return errs
    ids = []
    for i, f in enumerate(d['findings']):
        if not isinstance(f, dict): errs.append(f'finding {i} is not an object'); continue
        n = f.get('id') if _str(f.get('id')) else f'finding {i}'
        for k in REQ:
            if k in f and f[k] is not None and not isinstance(f[k], str): errs.append(f'{n}: {k} must be a string'); continue
            if strict and not _str(f.get(k)): errs.append(f'{n}: missing {k}')
        if not strict and not (_str(f.get('rule')) or _str(f.get('title'))): errs.append(f'{n}: needs rule or title')
        if _str(f.get('id')): ids.append(f['id'])
        for k, allowed in (('severity', SEV), ('verification', VER), ('label', LABELS), ('dimension', DIMS), ('status', STATUS), ('scope', SCOPES)):
            v = f.get(k)
            if v is None and (not strict or k == 'scope'): continue
            if not isinstance(v, str) or v not in allowed: errs.append(f'{n}: {k} must be one of {sorted(allowed)}')
        if f.get('scope') == 'page' and not _http_url(f.get('url')): errs.append(f'{n}: scope "page" needs an http(s) url')
        elif strict and _str(f.get('url')) and not _http_url(f['url']): errs.append(f'{n}: url must be an http(s) URL')
        if 'priority' in f and f['priority'] is not None and not isinstance(f['priority'], str): errs.append(f'{n}: priority must be a string')
        if 'instances' in f and (isinstance(f['instances'], bool) or not isinstance(f['instances'], int) or f['instances'] < 1): errs.append(f'{n}: instances must be a whole number >= 1')
        if 'evidence' in f and (not isinstance(f['evidence'], list) or not all(isinstance(e, str) for e in f['evidence'])): errs.append(f'{n}: evidence must be a list of strings')
        if f.get('fingerprint') is not None and not isinstance(f['fingerprint'], str): errs.append(f'{n}: fingerprint must be a string or null')
    for x in sorted({i for i in ids if ids.count(i) > 1}): errs.append(f'duplicate id {x}')
    cov = d.get('coverage')
    if cov is None:
        if strict: errs.append('missing coverage object (one entry per dimension); score cannot tell tested from untested')
    elif not isinstance(cov, dict): errs.append('coverage must be an object keyed by dimension')
    else:
        for k in cov:
            if k not in DIMS: errs.append(f'coverage: unknown dimension {k}')
        for k in DIMS:
            c = cov.get(k)
            if c is None:
                if strict: errs.append(f'coverage.{k} missing (every dimension needs an entry; use not-executed if it was not tested)')
                continue
            if not isinstance(c, dict) or not isinstance(c.get('status'), str) or c['status'] not in COVERAGE:
                errs.append(f'coverage.{k}.status must be one of {sorted(COVERAGE)}'); continue
            ch = c.get('checks', [])
            if not isinstance(ch, list) or not all(_str(x) for x in ch): errs.append(f'coverage.{k}.checks must be a list of non-empty strings'); continue
            if 'note' in c and c['note'] is not None and not isinstance(c['note'], str): errs.append(f'coverage.{k}.note must be a string')
            if strict and c['status'] in ('executed', 'partial') and not ch: errs.append(f'coverage.{k}: {c["status"]} needs a non-empty checks list (what was actually run)')
            if strict and c['status'] == 'partial' and not _str(c.get('note')): errs.append(f'coverage.{k}: partial needs a note (what was not covered)')
    cr = d.get('checks_run')
    if cr is None:
        if strict: errs.append('missing checks_run list; regression cannot tell fixed from not re-tested')
    elif not isinstance(cr, list): errs.append('checks_run must be a list')
    else:
        for i, c in enumerate(cr):
            if not isinstance(c, dict) or not _str(c.get('rule')) or not _str(c.get('template')): errs.append(f'checks_run[{i}] needs string rule and template'); continue
            if c.get('url') is not None and not _http_url(c['url']): errs.append(f'checks_run[{i}].url must be an http(s) URL')
    for k in ('improvements',):
        if k in d and (not isinstance(d[k], list) or not all(isinstance(x, dict) for x in d[k])): errs.append(f'{k} must be a list of objects')
    if 'scores' in d and not isinstance(d['scores'], dict): errs.append('scores must be an object')
    return errs


def dup_fingerprints(findings):
    seen, dup = {}, {}
    for f in findings:
        k = fp(f)
        if k in seen: dup.setdefault(k, [seen[k]]).append(f.get('id'))
        else: seen[k] = f.get('id')
    return dup


def cmd_check(a):
    d = load(a.file); errs = validate(d)
    if not errs:
        for k, ids in dup_fingerprints(d['findings']).items():
            errs.append(f'duplicate fingerprint {k} for {ids}: same rule + template (+ path for scope "page"). Merge them into one '
                        'finding with an instances count, give distinct rules, or use scope "page" for instance-specific findings')
    if errs: fail(errs)
    changed = []
    for f in d['findings']:
        new = fp(f)
        if f.get('fingerprint') and f['fingerprint'] != new: changed.append(f"{f['id']}: {f['fingerprint']} -> {new}")
        f['fingerprint'] = new
    save(a.file, d)
    for c in changed: print('WARNING fingerprint changed (rule/template/scope/url edited?):', c)
    print(f"OK: {len(d['findings'])} findings, fingerprints set")


def band(s): return next(w for lo, w in BANDS if s >= lo)


def suggested_scores(d):
    """dim -> {'score': float|None, 'status': ..., 'note': ...}. Every non-fixed finding deducts (it is still on the site or
    its state is unknown); not-retested findings also make the dimension partial. Executed/partial with no checks = not scored."""
    cov = d.get('coverage') if isinstance(d.get('coverage'), dict) else {}
    out = {}
    for dim in DIMS:
        c = cov.get(dim) if isinstance(cov.get(dim), dict) else {}
        st, note = c.get('status'), c.get('note') or ''
        if st not in ('executed', 'partial'):
            out[dim] = {'score': None, 'status': st or 'no coverage recorded', 'note': note}
            continue
        if not c.get('checks'):
            out[dim] = {'score': None, 'status': f'{st} but no checks recorded', 'note': note}
            continue
        fs = [f for f in d['findings'] if f.get('dimension') == dim and (f.get('status') or 'open') != 'fixed' and f.get('severity') in PEN]
        s = 10 - sum(PEN[f['severity']] * (0.5 if f.get('verification') == 'provisional' else 1) for f in fs)
        if any(f['severity'] == 'S1' for f in fs): s = min(s, 3)
        elif any(f['severity'] == 'S2' for f in fs): s = min(s, 5)
        elif any(f['severity'] == 'S3' for f in fs): s = min(s, 8)
        notes = []
        if st == 'partial': notes.append('partly covered: ' + note)
        nr = sum((f.get('status') or 'open') == 'not-retested' for f in fs)
        if nr: notes.append(f'{nr} not re-tested'); st = 'partial'
        if st == 'partial': s = min(s, 8)
        out[dim] = {'score': max(0, round(s * 2) / 2), 'status': st, 'note': '; '.join(notes)}
    return out


def cmd_score(a):
    d = load(a.file); errs = validate(d, strict=False)
    if errs: fail(errs)
    cur = d.get('scores') if isinstance(d.get('scores'), dict) else {}
    for k, v in suggested_scores(d).items():
        shown = f"{v['score']:4}  {band(v['score'])}" if v['score'] is not None else f"not scored ({v['status'].replace('-', ' ')})"
        print(f"{DISPLAY[k]:24} {shown}{'  [' + v['note'] + ']' if v['note'] else ''}  (current in file: {cur.get(k)})")


def run_key(run_id, date, mtime):
    run_id = run_id if isinstance(run_id, str) else ''
    m = re.search(r'-(\d+)$', run_id)
    suffix = int(m.group(1)) if m and not re.search(r'\d{4}-\d{2}-\d{2}$', run_id) else 0
    return (date if isinstance(date, str) else '', suffix, mtime)


def host_of(t):
    """host[:port] of a target URL, lower case, with a leading 'www.' label removed (mywww.example.com keeps its name).
    An IPv6 address keeps its brackets, so [2001:db8::1]:8080 and [2001:db8::1:8080] stay different hosts."""
    try:
        p = urlparse(t if isinstance(t, str) else '')
        h = (p.hostname or '').lower()
        port = p.port
    except ValueError:
        return ''
    if h.startswith('www.'): h = h[4:]
    if ':' in h: h = f'[{h}]'
    return h + (f':{port}' if port else '')


def find_previous(cur_path, d, root):
    host = host_of(d['target'])
    me = run_key(d.get('run_id'), d.get('date'), float('inf'))
    best = None
    for p in glob.glob(os.path.join(root, '*', 'findings.json')):
        if os.path.abspath(p) == os.path.abspath(cur_path): continue
        try:
            with open(p, encoding='utf-8') as fh: o = json.load(fh)
        except (OSError, ValueError): continue
        if not isinstance(o, dict) or host_of(o.get('target')) != host or validate(o, strict=False): continue
        k = run_key(o.get('run_id'), o.get('date'), os.path.getmtime(p))
        if k[:2] > me[:2]: continue
        if not best or k > best[0]: best = (k, p, o)
    return best[1:] if best else None


def retested(f, checks):
    """True when this run's checks_run re-ran f's rule on f's template ('*' = all templates) and, for scope 'page', on the
    same URL path (a check without a url does not cover a page-scoped finding). Sitewide findings need template
    'sitewide' or '*'."""
    rule, tpl, path = identity(f)
    for c in checks:
        cr = c.get('rule', '')
        rule_ok = rule.startswith(norm(cr[:-1])) if cr.endswith('*') else rule == norm(cr)
        tpl_ok = c.get('template') == '*' or norm(c.get('template')) == tpl
        path_ok = path is None or (c.get('url') is not None and url_path(c['url']) == path)
        if rule_ok and tpl_ok and path_ok: return True
    return False


def cmd_diff(a):
    cur = load(a.file); errs = validate(cur, strict=False)
    if not errs:
        errs += [f'current run: duplicate fingerprint {k} for {ids} (run check first)' for k, ids in dup_fingerprints(cur['findings']).items()]
    if errs: fail(errs)
    reg_json = os.path.join(os.path.dirname(os.path.abspath(a.file)), 'regression.json')
    empty = {'fixed': [], 'still_open': [], 'new': [], 'not_retested': [], 'wont_fix': [], 'accepted_risk': []}
    for f in cur['findings']: f['fingerprint'] = fp(f)
    if a.previous:
        prev_path, prev = a.previous, load(a.previous)
        perrs = validate(prev, strict=False)
        if not perrs and host_of(prev.get('target')) != host_of(cur.get('target')):
            perrs.append(f"--previous is for {prev.get('target')!r}, current run is for {cur.get('target')!r}")
        if perrs: fail(['previous run: ' + e for e in perrs])
    else:
        b = find_previous(a.file, cur, a.runs_root)
        if not b:
            msg = f"No previous run with findings.json for {cur.get('target')} under {a.runs_root}: baseline run, nothing to compare."
            print(msg)
            if a.out:
                with open(a.out, 'w', encoding='utf-8') as fh: fh.write('# Regression vs previous run\n\n' + msg + '\n')
            save(reg_json, {'status': 'baseline', 'previous': None, **empty})
            return
        prev_path, prev = b
    for f in prev['findings']: f['fingerprint'] = fp(f)
    merged = dup_fingerprints(prev['findings'])   # older runs may hold several findings with one identity under the new model
    checks = cur.get('checks_run') or []
    P = {}
    for f in prev['findings']:
        if (f.get('status') or 'open') != 'fixed': P.setdefault(f['fingerprint'], f)   # every non-fixed finding is carried over
    ALL = {f['fingerprint']: f for f in cur['findings']}
    C = {k: f for k, f in ALL.items() if (f.get('status') or 'open') == 'open'}
    res = {k: [] for k in empty}
    for k, p in P.items():
        c = ALL.get(k)
        cst = (c.get('status') or 'open') if c is not None else None
        if cst == 'open': res['still_open'].append((p, c))
        elif cst in ('wont-fix', 'accepted-risk'): res[cst.replace('-', '_')].append(p)
        elif cst == 'fixed': res['fixed'].append(p)
        elif c is None and retested(p, checks): res['fixed'].append(p)
        elif c is None and (p.get('status') or 'open') in ('wont-fix', 'accepted-risk'): res[p['status'].replace('-', '_')].append(p)   # keeps its disposition
        else: res['not_retested'].append(p)
    res['new'] = [f for k, f in C.items() if k not in P]
    line = lambda f: f"- {f.get('id')} [{f.get('severity')}] {f.get('title')}"
    L = ['# Regression vs previous run', '', f"Previous: {prev.get('run_id')} ({prev_path}) · Current: {cur.get('run_id')}", '',
         f"Fixed: {len(res['fixed'])} · Still open: {len(res['still_open'])} · New: {len(res['new'])} · Not re-tested: {len(res['not_retested'])}"
         f" · Won't fix: {len(res['wont_fix'])} · Accepted risk: {len(res['accepted_risk'])}", '']
    if not checks: L += ['WARNING: this run has no checks_run entries, so nothing missing can be called fixed (all listed as not re-tested).', '']
    if merged: L += [f'NOTE: previous run had findings sharing one identity (compared as one): {list(merged.values())}', '']
    L += ['## Fixed (its check re-ran on the same template, or the same page for page-scoped findings, and the finding is gone; or the lead marked it fixed)'] + [line(f) for f in res['fixed']] + ['']
    L += ['## Still open'] + [f"- {c.get('id')} (was {p.get('id')}) [{p.get('severity')}→{c.get('severity')}] {c.get('title')}" for p, c in res['still_open']] + ['']
    L += ['## New'] + [line(f) for f in res['new']] + ['']
    L += ['## Not re-tested (its check did not run on that template/page this time; status unknown)'] + [line(f) for f in res['not_retested']] + ['']
    L += ["## Won't fix"] + [line(f) for f in res['wont_fix']] + ['', '## Accepted risk'] + [line(f) for f in res['accepted_risk']] + ['']
    txt = '\n'.join(L); print(txt)
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as fh: fh.write(txt)
    fps = lambda xs: [f['fingerprint'] for f in xs]
    save(reg_json, {'status': 'compared', 'previous': prev_path, 'fixed': fps(res['fixed']), 'still_open': [c['fingerprint'] for _, c in res['still_open']],
                    'new': fps(res['new']), 'not_retested': fps(res['not_retested']), 'wont_fix': fps(res['wont_fix']), 'accepted_risk': fps(res['accepted_risk'])})


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sp = ap.add_subparsers(dest='cmd', required=True)
sp.add_parser('template', help='print a skeleton findings.json').set_defaults(fn=cmd_template)
c = sp.add_parser('check', help='validate, then set fingerprints'); c.add_argument('file'); c.set_defaults(fn=cmd_check)
c = sp.add_parser('score', help='suggested scores per dimension'); c.add_argument('file'); c.set_defaults(fn=cmd_score)
c = sp.add_parser('diff', help='regression vs a previous run'); c.add_argument('file'); c.add_argument('--previous')
c.add_argument('--runs-root', default=os.path.expanduser(os.environ.get('QA_RUNS', '~/qa-runs'))); c.add_argument('--out'); c.set_defaults(fn=cmd_diff)
if __name__ == '__main__':
    a = ap.parse_args(); a.fn(a)
