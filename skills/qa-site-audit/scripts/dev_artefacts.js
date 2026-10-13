#!/usr/bin/env node
// Leftover dev artefacts in the RENDERED page: debug/test/todo/lorem elements (visible or hidden), console errors, page errors,
// failed requests, mixed content and exposed source maps. Read-only, zero clicks. Its own fetches are polite GETs
// (one at a time, delay, timeout, size cap, scoped redirects): the served HTML once per page, each same-origin JS/CSS asset
// once, each map URL probed once (status only).
const { parseArgs, safeUrl, red, freshBrowser, closeBrowser, setViewport, settle, goto, watchRequests, politeGet, writeJson, needFetch, sleep, needBrowser, scopeHosts, openPage, assertInScope } = require('./_common');

const USAGE = `Usage: node dev_artefacts.js <urls.txt|url1,url2> [options]

  --out FILE        JSON output (default evidence/artefacts.json; written after every page)
  --width N         viewport width, 200-4000 (default 1366)
  --delay MS        pause between the script's own GETs and between pages (default 1000, min 500)
  --timeout MS      per-GET timeout (default 15000)
  --max-bytes N     per-GET body cap (default 5000000)
  --cache DIR       reuse earlier GET responses from DIR (reruns fetch nothing new). The cache holds raw fetched
                    content and exact URLs (query strings included): it is working data, not evidence, and
                    must not be shared or attached to a report
  --help            this text

Source maps are only probed (status only, no body) on the hosts of the input URLs (and their www/apex twins); others are "skipped (off-scope)".
Own GETs follow at most 3 redirects, each on an input-URL host or its www/apex twin; an off-scope hop is "skipped (off-scope redirect)".
Console text, DOM hits and URLs in the output are redacted (no query strings, emails or long tokens).
Navigation guard: non-GET navigations and main-frame navigations to hosts outside the input URLs (plus www/apex twins) are blocked and
recorded in blockedNavigations (kind and host only); an off-scope main navigation fails that URL. Sub-resource requests are untouched.
Exit: 0 done, 1 some pages failed or had own-GET failures (ownFetchErrors; still written), 2 usage or dependency error (including a missing Chrome binary).`;

const PAT = '\\b(debug|lorem ipsum|todo|fixme|xxx+|test(ing)? (label|copy|content|page)|placeholder text|dummy|staging|localhost|console\\.log|asdf)\\b';

const a = parseArgs({
  out: { type: 'str', def: 'evidence/artefacts.json' }, width: { type: 'int', def: '1366', min: 200, max: 4000 }, delay: { type: 'int', def: '1000', min: 500 },
  timeout: { type: 'int', def: '15000', min: 1000 }, 'max-bytes': { type: 'int', def: '5000000', min: 10000 }, cache: { type: 'str', def: null },
}, USAGE);
needFetch(); needBrowser();
// In scope: each input host and its www/apex twin (sites commonly redirect between the two; never a twin for an IP address).
const scopeSet = scopeHosts(a.urls);
// Own GETs: redirects followed by hand, at most 3 hops, every hop on an input-URL host (else 'skipped (off-scope redirect)').
const get = (u, opts = {}) => politeGet(u, { timeoutMs: a.timeout, maxBytes: a['max-bytes'], delayMs: a.delay, cacheDir: a.cache, allowHosts: scopeSet, ...opts });
// A usable own-fetch body: no transport error, not skipped, HTTP 200. Anything else is an own-fetch failure for that page.
const problem = g => g.error || g.skipped || (g.status !== 200 ? `HTTP ${g.status}` : null);

function scanDom(patS) {
  const re = new RegExp(patS, 'i'); const hits = [];
  for (const e of document.querySelectorAll('body *')) {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(e.tagName)) continue;
    const cls = typeof e.className === 'string' ? e.className : (e.className && e.className.baseVal) || '';
    const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
    const attr = `${e.id} ${cls} ${e.getAttribute('data-testid') || ''}`;
    const inText = own && re.exec(own); const m = inText || re.exec(attr);
    if (m) {
      const s = getComputedStyle(e); const r = e.getBoundingClientRect();
      hits.push({ tag: e.tagName, match: m[0], where: inText ? 'text' : 'id/class', text: own.slice(0, 400), id: e.id || '', cls: cls.slice(0, 400),
        visible: s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0 });
    }
    if (hits.length > 40) break;
  }
  return { hits, testIdAttrs: document.querySelectorAll('[data-testid],[data-test],[data-cy]').length };
}

(async () => {
  const assetMap = {};   // asset URL -> { map, via, base } | { map: null } | { error }
  const mapResult = {};  // map URL -> { status } (each map probed once, reused on every page that references it)
  const out = { generated: new Date().toISOString(), pattern: PAT, note: 'inServedHtml is a heuristic (text or attribute found in the served HTML). Hidden hits are hygiene items, not broken UI. ownFetchErrors lists the script\'s own GETs that failed, were truncated or were skipped; such a page counts as a partial failure.', results: [], failures: [] };
  let failed = 0;
  for (const url of a.urls) {
    let b = null; const r = { url: safeUrl(url) }; const ownFetchErrors = [];
    const own = (what, u, msg) => ownFetchErrors.push({ what, url: safeUrl(u), error: red(String(msg)).slice(0, 200) });
    try {
      b = await freshBrowser(); const p = await openPage(b, scopeSet); await setViewport(p, { w: a.width });
      const w = watchRequests(p);
      const consoleMsgs = [], pageErrors = [], failedReqs = [], assets = new Map();
      p.on('console', m => { if (['error', 'warning'].includes(m.type())) consoleMsgs.push(m.type() + ': ' + red(m.text()).slice(0, 240)); });
      p.on('pageerror', e => pageErrors.push(red(String(e)).slice(0, 240)));
      p.on('requestfailed', q => q.__qaBlocked || failedReqs.push(safeUrl(q.url()).slice(0, 160) + ' ' + ((q.failure() || {}).errorText || '')));
      p.on('response', q => {
        if (q.status() >= 400) failedReqs.push(q.status() + ' ' + safeUrl(q.url()).slice(0, 160));
        const t = q.request().resourceType();
        if (t === 'script' || t === 'stylesheet') { const hd = q.headers(); assets.set(q.url(), hd['sourcemap'] || hd['x-sourcemap'] || null); }
      });
      const nav = await goto(p, url);
      if (nav.error) throw new Error('navigation: ' + nav.error);
      await settle(p);
      assertInScope(p);   // a script or meta refresh may have tried to leave the input hosts after the load
      const dom = await p.evaluate(scanDom, PAT);
      const blockedNavigations = p.__guard.blocked.slice();
      await closeBrowser(b); b = null;   // browser done; the remaining GETs are the script's own

      const origin = new URL(url).origin, maps = [];
      for (const [s, header] of assets) {
        if (new URL(s).origin !== origin) continue;
        if (!assetMap[s]) {
          if (header) assetMap[s] = { map: header, via: 'header', base: s };
          else {
            const g = await get(s);
            const bad = problem(g) || (g.truncated ? `truncated at ${a['max-bytes']} bytes (sourceMappingURL comment not checked)` : null);
            if (bad) assetMap[s] = { error: bad };
            else { const m = /[#@]\s*sourceMappingURL=([^\s*]+)/.exec(g.text.slice(-500)); assetMap[s] = { map: m ? m[1] : null, via: 'comment', base: g.finalUrl }; }
          }
        }
        const am = assetMap[s];
        if (am.error) { own('asset', s, am.error); maps.push({ asset: safeUrl(s), status: 'error', error: am.error }); continue; }
        if (!am.map) continue;
        if (am.map.startsWith('data:')) { maps.push({ asset: safeUrl(s), map: 'inline data: URI', status: 'inline' }); continue; }
        let mu; try { mu = new URL(am.map, am.base).href; } catch (e) { maps.push({ asset: safeUrl(s), map: red(am.map).slice(0, 160), status: 'unparseable map URL' }); continue; }
        if (!scopeSet.has(new URL(mu).host)) { maps.push({ asset: safeUrl(s), map: safeUrl(mu), status: 'skipped (off-scope)' }); continue; }
        if (!mapResult[mu]) {   // status-only probe: no body is read, so the status is never a truncated "success"
          const g = await get(mu, { statusOnly: true });
          mapResult[mu] = g.error ? { status: 'error', error: g.error } : g.skipped ? { status: g.skipped, redirects: g.redirects } : { status: g.status, probe: 'status only', redirects: g.redirects.length ? g.redirects : undefined };
        }
        if (mapResult[mu].status === 'error') own('map', mu, mapResult[mu].error);
        maps.push({ asset: safeUrl(s), map: safeUrl(mu), via: am.via, ...mapResult[mu] });
      }

      // Served vs injected (heuristic): text hits searched as text, id/class hits searched as attribute values in the served HTML.
      const served = await get(url);
      const servedBad = problem(served);
      if (servedBad) own('served-html', url, servedBad);
      else if (served.truncated) own('served-html', url, `truncated at ${a['max-bytes']} bytes (inServedHtml may be false negatives)`);
      const html = servedBad ? null : served.text.toLowerCase();
      for (const h of dom.hits) {
        if (html === null) h.inServedHtml = null;
        else if (h.where === 'text') h.inServedHtml = html.includes(h.text.toLowerCase().slice(0, 40));
        else { const v = (h.id || h.cls).toLowerCase(); h.inServedHtml = v ? new RegExp(`(id|class)=["'][^"']*${v.split(/\s+/)[0].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`).test(html) : null; }
        // evidence copies: redacted (emails, tokens) before slicing; the raw strings were only used for the match above
        h.text = red(h.text).slice(0, 80); h.id = red(h.id).slice(0, 100); h.cls = red(h.cls).slice(0, 100);
      }
      Object.assign(r, { navigation: nav, blockedNavigations, domHits: dom.hits, testIdAttrs: dom.testIdAttrs, consoleMsgs, pageErrors, failedRequests: failedReqs,
        mixedContent: [...w.mixed].slice(0, 20), nonGetRequests: w.nonGet, sourceMaps: maps, servedHtmlError: servedBad || null, ownFetchErrors });
      if (ownFetchErrors.length) { failed++; out.failures.push({ url: r.url, error: `${ownFetchErrors.length} own GET(s) failed, truncated or skipped (see ownFetchErrors)` }); }
      console.log(`${r.url}: domHits=${dom.hits.length} (hidden ${dom.hits.filter(h => !h.visible).length}) console=${consoleMsgs.length} pageErrors=${pageErrors.length} failed=${failedReqs.length} mixed=${w.mixed.size} maps=${maps.filter(m => m.status === 200).length} exposed ownFetchErrors=${ownFetchErrors.length}`);
    } catch (e) {
      failed++; r.error = red(String(e.message || e)).slice(0, 200); out.failures.push({ url: r.url, error: r.error });
      if (ownFetchErrors.length) r.ownFetchErrors = ownFetchErrors;
      console.error(`${r.url} FAILED: ${r.error}`);
    } finally {
      await closeBrowser(b); out.results.push(r); writeJson(a.out, out); await sleep(a.delay);
    }
  }
  console.log('wrote', a.out, failed ? `(${failed} failed)` : '');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
