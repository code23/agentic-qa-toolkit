#!/usr/bin/env node
// Device viewport matrix + overflow probe + header clearance + CTA spacing + rendered text parity (lead-side, headless, zero clicks).
// Emulated viewports are NOT physical devices; record that in the report.
const { fs, path, parseArgs, safeUrl, red, freshBrowser, closeBrowser, setViewport, settle, stepScroll, goto, writeJson, sleep, CONSENT_NAMED, needBrowser, scopeHosts, openPage, assertInScope } = require('./_common');

const USAGE = `Usage: node viewport_overflow.js <urls.txt|url1,url2> [options]

  --viewports LIST   widths, or WIDTHxHEIGHT (default 320,375,768,1024,1440; e.g. add 844x390,1280,1920)
  --out FILE         JSON output (default evidence/overflow.json; written after every page)
  --shots DIR        save a top-of-page screenshot per URL and width
  --delay MS         pause between page loads (default 800, min 500)
  --cta REGEX        in-content CTA wording, case-insensitive
                     (default \\b(contact|start a project|get in touch|book(ing)?|enquir\\w*|quote|talk to us)\\b)
  --no-mobile        desktop probe: no mobile or touch emulation at any width (the overflow re-check)
  --reduced-motion   emulate prefers-reduced-motion: reduce (often shows the final animation state)
  --no-scroll        skip the step-scroll that triggers scroll reveals before measuring
  --help             this text

One fresh profile per URL and width; nothing is clicked; consent is never dismissed (pre-consent state).
Navigation guard: non-GET navigations and main-frame navigations to hosts outside the input URLs (plus www/apex twins) are blocked and
recorded in blockedNavigations (kind and host only); an off-scope main navigation fails that URL. Sub-resource requests are untouched.
Exit: 0 all done, 1 some pages failed (still written), 2 usage or dependency error (including a missing Chrome binary).`;

const CTA = '\\b(contact|start a project|get in touch|book(ing)?|enquir\\w*|quote|talk to us)\\b';
const SPEC = {
  viewports: { type: 'widths', def: '320,375,768,1024,1440' }, out: { type: 'str', def: 'evidence/overflow.json' },
  shots: { type: 'str', def: null }, delay: { type: 'int', def: '800', min: 500 }, cta: { type: 'regex', def: CTA },
  'no-mobile': { type: 'bool' }, 'reduced-motion': { type: 'bool' }, 'no-scroll': { type: 'bool' },
};

// Runs in the page. Everything is measured at the top of the page after settling.
function measure(ctaS, namedS) {
  const de = document.documentElement, cw = de.clientWidth, vh = innerHeight;
  const NAMED = new RegExp(namedS, 'i');
  const attrs = e => `${e.id || ''} ${typeof e.className === 'string' ? e.className : ''} ${e.getAttribute('aria-label') || ''}`;
  const inConsent = e => { for (let n = e; n && n !== document.body; n = n.parentElement) if (NAMED.test(attrs(n))) return true; return false; };
  const visible = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const describe = e => e ? (e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '')).slice(0, 80) : null;

  // Overflow. Elements clipped by an overflow:hidden/clip ancestor that itself fits are not offenders (they can't cause sideways scroll).
  const clipped = e => { for (let n = e.parentElement; n && n !== document.body && n !== de; n = n.parentElement) { const ox = getComputedStyle(n).overflowX; if ((ox === 'hidden' || ox === 'clip') && n.getBoundingClientRect().right <= cw + 1) return true; } return false; };
  const wide = [...document.querySelectorAll('body *')].map(e => ({ e, r: e.getBoundingClientRect() }))
    .filter(x => x.r.width > 0 && x.r.right > cw + 1 && getComputedStyle(x.e).position !== 'fixed');
  const unclipped = wide.filter(x => !clipped(x.e));
  const offenders = unclipped.sort((m, n) => n.r.right - m.r.right).slice(0, 8)
    .map(x => ({ el: describe(x.e), right: Math.round(x.r.right), width: Math.round(x.r.width) }));
  scrollTo(10000, 0); const sx = scrollX; scrollTo(0, 0);

  // Header: the outermost fixed/sticky full-width bar at the top that is not a consent banner (any tag, not only <header>).
  const bars = [...document.querySelectorAll('body *')].filter(e => {
    const p = getComputedStyle(e).position; if (p !== 'fixed' && p !== 'sticky') return false;
    const r = e.getBoundingClientRect(); return r.top <= 2 && r.bottom > 0 && r.width >= cw * 0.6 && r.height < vh * 0.5 && !inConsent(e);
  });
  const hdr = bars.filter(e => !bars.some(o => o !== e && o.contains(e))).sort((x, y) => y.getBoundingClientRect().bottom - x.getBoundingClientRect().bottom)[0] || null;
  const hb = hdr ? Math.round(hdr.getBoundingClientRect().bottom) : null;
  const clears = el => (el && hdr && !hdr.contains(el)) ? el.getBoundingClientRect().top >= hb - 1 : null;
  const h1 = [...document.querySelectorAll('h1')].find(visible) || null;
  const crumb = [...document.querySelectorAll('nav[aria-label*=breadcrumb i],[class*=breadcrumb i],[id*=breadcrumb i],[itemtype*=BreadcrumbList]')].find(visible) || null;
  const root = document.querySelector('main') || document.querySelector('[role=main]') || document.body;
  const firstControl = [...root.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea')]
    .find(e => visible(e) && !(hdr && hdr.contains(e)) && !inConsent(e) && !e.closest('nav')) || null;

  // CTAs: in-content only, matched on text/aria-label or link path (word boundaries), last gap measured to the footer top.
  const re = new RegExp(ctaS, 'i');
  const lab = e => `${e.innerText || ''} ${e.getAttribute('aria-label') || ''}`.trim();
  const pathWords = e => { try { return new URL(e.href).pathname.replace(/[-_/]+/g, ' '); } catch (x) { return ''; } };
  const ctas = [...document.querySelectorAll('a,button')].filter(e => visible(e) && (re.test(lab(e)) || (e.tagName === 'A' && re.test(pathWords(e))))
      && !e.closest('header,footer,nav,[role=banner],[role=contentinfo]') && !inConsent(e))
    .map(e => Math.round(e.getBoundingClientRect().top + scrollY)).sort((x, y) => x - y);
  const H = de.scrollHeight;
  // Page footer = the lowest footer/contentinfo that is not nested in content (cards and blockquotes often carry their own <footer>).
  const fts = [...document.querySelectorAll('footer,[role=contentinfo]')].filter(e => !e.closest('main,article,blockquote,figure,section,aside,[role=dialog]') || e.matches('[role=contentinfo]'))
    .map(e => Math.round(e.getBoundingClientRect().top + scrollY)).filter(y => y > 0);
  const end = fts.length ? Math.max(...fts) : H;
  const pts = [0, ...ctas.filter(y => y < end), end]; let maxGap = 0;
  for (let i = 1; i < pts.length; i++) maxGap = Math.max(maxGap, pts[i] - pts[i - 1]);

  const consentBannerVisible = [...document.querySelectorAll('body *')].some(e => NAMED.test(attrs(e)) && visible(e) && e.getBoundingClientRect().height > 40);
  const text = root.innerText || '';
  // Word count on the same root and exclusions as the served count in _fetch.py main_text(): <main>, else <body> minus every
  // header/nav/footer/aside; words = runs of Unicode letters/digits/underscore (Python's \w).
  const countWords = t => (t.match(/[\p{L}\p{N}_]+/gu) || []).length;
  let renderedWords = countWords(text);
  if (root === document.body) {
    const chrome = [...document.body.querySelectorAll('header,nav,footer,aside')].filter(e => !e.parentElement.closest('header,nav,footer,aside'));
    renderedWords = Math.max(0, renderedWords - chrome.reduce((n, e) => n + countWords(e.innerText || ''), 0));
  }
  return {
    scrollWidth: de.scrollWidth, clientWidth: cw, overflowPx: de.scrollWidth - cw, actualScrollX: sx, offenders, clippedWideElements: wide.length - unclipped.length,
    header: describe(hdr), stickyHeaderBottom: hb, h1Top: h1 ? Math.round(h1.getBoundingClientRect().top) : null,
    headerClearsH1: clears(h1), headerClearsBreadcrumb: clears(crumb), breadcrumbInHeader: crumb && hdr ? hdr.contains(crumb) : null,
    headerClearsFirstControl: clears(firstControl), firstControl: describe(firstControl),
    pageHeight: H, inContentCtas: ctas.length, firstCtaScreens: ctas.length ? +(ctas[0] / vh).toFixed(2) : null, maxGapScreensBetweenCtas: +(maxGap / vh).toFixed(2),
    consentBannerVisible, root: root === document.body ? 'body' : 'main', renderedWords, _text: text,
  };
}

// Lines visible at one width but not the other (CSS-agnostic, unlike the Tailwind-class heuristic in copy_freshness.py).
function parity(narrow, wide) {
  // A line counts as breakpoint-only when it does not occur anywhere in the other width's flattened text, so lines that merely
  // wrap or split differently at another width (spans switching to display:block, <br> only on mobile) are not reported.
  const norm = s => s.replace(/\s+/g, ' ').trim().toLowerCase();
  const lines = t => new Set(t.split('\n').map(norm).filter(s => s.length >= 3));
  const flatN = ' ' + norm(narrow.text) + ' ', flatW = ' ' + norm(wide.text) + ' ';
  const N = [...lines(narrow.text)].filter(s => !flatW.includes(s)), W = [...lines(wide.text)].filter(s => !flatN.includes(s));
  const money = s => /[£$€¥]|\d+(\.\d+)?\s?%|\d/.test(s);
  const rank = arr => arr.sort((x, y) => money(y) - money(x)).slice(0, 10).map(s => red(s).slice(0, 160));   // redact, then slice
  const onlyNarrow = N, onlyWide = W;
  return { narrow: narrow.w, wide: wide.w, onlyNarrowCount: onlyNarrow.length, onlyWideCount: onlyWide.length,
    onlyNarrow: rank(onlyNarrow), onlyWide: rank(onlyWide), withNumbersOrPrices: [...onlyNarrow, ...onlyWide].filter(money).length };
}

async function main() {
  const a = parseArgs(SPEC, USAGE);
  needBrowser(); const scope = scopeHosts(a.urls);
  const out = { generated: new Date().toISOString(), note: 'Emulated viewports, not physical devices. Pre-consent state (banner not dismissed). overflowPx>0 with actualScrollX>0 = user can scroll sideways. A null clearance value = not measured (no fixed/sticky header or no such element); check by hand.',
    options: { viewports: a.viewports, noMobile: a['no-mobile'], reducedMotion: a['reduced-motion'], stepScroll: !a['no-scroll'], cta: a.cta }, results: [], parity: [], failures: [] };
  if (a.shots) fs.mkdirSync(a.shots, { recursive: true });
  let failed = 0;
  for (const url of a.urls) {
    const texts = [];
    for (const vp of a.viewports) {
      let b = null;
      try {
        b = await freshBrowser(); const p = await openPage(b, scope);
        const emulation = await setViewport(p, vp, { mobile: a['no-mobile'] ? false : undefined, reducedMotion: a['reduced-motion'] });
        const nav = await goto(p, url);
        if (nav.error) throw new Error('navigation: ' + nav.error);
        await settle(p);
        if (!a['no-scroll']) { await stepScroll(p); await settle(p); }
        assertInScope(p);   // a script or meta refresh may have tried to leave the input hosts after the load
        const r = await p.evaluate(measure, a.cta, CONSENT_NAMED);
        texts.push({ w: vp.w, text: r._text }); delete r._text;
        let shot = null;
        if (a.shots) { shot = path.join(a.shots, `vp-${vp.w}${vp.h ? 'x' + vp.h : ''}-${safeUrl(url).replace(/^https?:\/\//, '').replace(/[^a-z0-9]+/gi, '_').slice(0, 60)}.png`); await p.screenshot({ path: shot }); }
        r.offenders.forEach(o => { o.el = red(o.el); }); r.header = r.header && red(r.header); r.firstControl = r.firstControl && red(r.firstControl);
        out.results.push({ url: safeUrl(url), viewport: vp.w, height: emulation.height, emulated: true, emulation, navigation: nav, blockedNavigations: p.__guard.blocked.slice(), consentState: 'pre-consent (fresh profile, nothing clicked)', scrollY: 0, ...r, shot });
        console.log(`${vp.w}px ${safeUrl(url)} overflow=${r.overflowPx}px scrollX=${r.actualScrollX} clearsH1=${r.headerClearsH1} ctas=${r.inContentCtas} maxGap=${r.maxGapScreensBetweenCtas}scr`);
      } catch (e) {
        failed++; out.failures.push({ url: safeUrl(url), viewport: vp.w, error: red(String(e.message || e)).slice(0, 200) });
        console.error(`${vp.w}px ${safeUrl(url)} FAILED: ${red(String(e.message || e)).slice(0, 160)}`);
      } finally {
        await closeBrowser(b); writeJson(a.out, out); await sleep(a.delay);
      }
    }
    if (texts.length >= 2) {
      const s = texts.slice().sort((x, y) => x.w - y.w);
      const narrow = s.find(t => t.w >= 360) || s[0];
      out.parity.push({ url: safeUrl(url), ...parity(narrow, s[s.length - 1]) }); writeJson(a.out, out);
    }
  }
  console.log('wrote', a.out, failed ? `(${failed} failed)` : '');
  process.exit(failed ? 1 : 0);
}

if (require.main === module) main().catch(e => { console.error(e); process.exit(1); });
module.exports = { measure, parity, CTA };
