#!/usr/bin/env node
// Pre- vs post-consent capture. Per URL and width, two phases, each in its own fresh profile:
//   accept phase: load with zero interaction, record cookies (all domains, via CDP), storage keys, request hosts and Consent Mode
//                 signals; click ONLY the consent Accept control (a consent choice, not a form submission); reload; record again.
//   reject phase: same, clicking ONLY the Reject control; records which trackers/cookies appear or are re-set after Reject.
// At most one click per phase. Never types, ticks, fills or submits anything. No control found = that phase is blocked.
const { parseArgs, safeUrl, red, freshBrowser, closeBrowser, setViewport, settle, goto, watchRequests, writeJson, sleep,
  CONSENT_NAMED, CONSENT_PRIVACY_NAMED, CONSENT_PRIVACY_TEXT, CONSENT_TEXT, nonDomainHost, needBrowser, scopeHosts, openPage, assertInScope } = require('./_common');
const RX = { named: CONSENT_NAMED, privacyNamed: CONSENT_PRIVACY_NAMED, privacyText: CONSENT_PRIVACY_TEXT, text: CONSENT_TEXT };

// Default labels. The visible label (or aria-label/value) is whitespace-collapsed, trimmed, stripped of trailing . or !,
// and must match the WHOLE pattern (case-insensitive). Keep references/consent-and-privacy.md identical to these.
const ACCEPT = '^(accept|accept all|accept all cookies|accept cookies|allow all|allow all cookies|allow cookies|i accept|got it|ok|ok, got it|agree and close)$';
const AGREE = '^(agree|i agree)$';   // only inside a container whose id/class/aria-label matches CONSENT_NAMED
const REJECT = '^(reject|reject all|reject all cookies|reject cookies|decline|decline all|necessary only|only necessary|only necessary cookies|essential only|deny|deny all)$';

const USAGE = `Usage: node consent_capture.js <urls.txt|url1,url2> [options]

  --accept REGEX   Accept labels (default ${ACCEPT})
                   Bare "Agree"/"I agree" also count, but only inside a cookie/consent/CMP-named container.
  --reject REGEX   Reject labels (default ${REJECT})
  --no-reject      skip the reject phase (not where consent law requires a reject option)
  --width LIST     widths to run (default 375,1366)
  --policy URL     privacy/cookie policy page to check vendor names against (one load)
  --egress CC      the lead machine's egress country/region, recorded in the output (default "unknown")
  --out FILE       JSON output (default evidence/consent.json; written after every URL and width)
  --delay MS       pause between page loads (default 800, min 500)
  --help           this text

Clicks at most one control per phase, only inside a consent container: id/class/aria-label naming cookie/consent/gdpr or a
known consent platform ('privacy' only if the container's text mentions cookies/consent/tracking), or a dialog; either way the
container's text must mention cookies/consent/tracking. Never body/html/main or a page-sized wrapper. Excluded: anything
with a form owner or inside a form, links that navigate away, containers holding text inputs or a CAPTCHA.
Navigation guard: non-GET navigations (for example a form submitted by a banner's click handler) and main-frame navigations to hosts
outside the input URLs (plus www/apex twins) are blocked and recorded in blockedNavigations (kind and host only); an off-scope main
navigation fails that phase. Sub-resource, XHR and beacon requests are untouched, so tracking is measured as a visitor's browser sends it.
Exit: 0 done, 1 some pages or phases failed (partial evidence kept), 2 usage or dependency error (including a missing Chrome binary).`;

// Host / cookie-prefix -> [vendor keyword to look for in the policy, category]. Extend per project.
const VENDORS = [[/google-analytics|googletagmanager|^_ga/i, 'google analytics', 'analytics'], [/doubleclick|googleadservices|googlesyndication|^_gcl/i, 'google ads', 'ads'],
  [/posthog|^ph_/i, 'posthog', 'analytics'], [/openai|^__?oaiq/i, 'openai', 'ads'], [/cloudflareinsights/i, 'cloudflare', 'analytics'], [/facebook|fbcdn|^_fbp/i, 'meta', 'ads'],
  [/hotjar|^_hj/i, 'hotjar', 'analytics'], [/clarity\.ms|^_clck|^_clsk/i, 'clarity', 'analytics'], [/linkedin|licdn/i, 'linkedin', 'ads'], [/hubspot|hs-scripts|^__hs/i, 'hubspot', 'analytics'],
  [/tiktok/i, 'tiktok', 'ads'], [/bing|bat\.bing/i, 'microsoft advertising', 'ads'], [/stripe/i, 'stripe', 'functional'], [/intercom/i, 'intercom', 'functional'],
  [/fonts\.(googleapis|gstatic)/i, 'google fonts', 'functional']];
const vendorOf = s => VENDORS.find(([re]) => re.test(s)) || null;
const tracking = v => !!v && v[2] !== 'functional';
// Vendor name for the policy comparison: the known vendor, else the registrable-ish label of a host. IP addresses (v4/v6, with or
// without a port) and localhost are never a vendor: they are left out.
function policyVendor(it) {
  if (it.kind === 'host' && nonDomainHost(it.id)) return null;
  const v = vendorOf(it.id);
  const name = v ? v[1] : (it.kind === 'host' ? it.id.split('.').slice(-2, -1)[0] : null);
  return name ? { name, category: v ? v[2] : 'unknown' } : null;
}
const trackers = snap => [...new Set([...snap.hosts, ...snap.cookies.map(c => c.name)].map(vendorOf).filter(tracking).map(v => v[1]))].sort();

// Runs in the page: returns [element|null, info|null]. See USAGE and references/consent-and-privacy.md for the rules.
function findControl(labelS, agreeS, rx) {
  const label = new RegExp(labelS, 'i'), agree = agreeS ? new RegExp(agreeS, 'i') : null;
  const NAMED = new RegExp(rx.named, 'i'), PRIV = new RegExp(rx.privacyNamed, 'i'), PRIV_TEXT = new RegExp(rx.privacyText, 'i'), TEXT = new RegExp(rx.text, 'i');
  const de = document.documentElement, pageH = Math.max(de.scrollHeight, document.body ? document.body.scrollHeight : 0);
  const idCls = e => `${e.id || ''} ${typeof e.className === 'string' ? e.className : ''}`;
  const txt = e => e.innerText || e.textContent || '';
  // Walk up from the control; stop before body/html/main; never accept a wrapper taller than 0.8 x the page.
  const container = e => {
    for (let n = e.parentElement; n && !n.matches('body,html,main'); n = n.parentElement) {
      if (n.getBoundingClientRect().height > 0.8 * pageH) continue;
      const t = txt(n);
      if (!TEXT.test(t)) continue;
      if (NAMED.test(`${idCls(n)} ${n.getAttribute('aria-label') || ''}`)) return { el: n, kind: 'named' };
      if (PRIV.test(idCls(n)) && PRIV_TEXT.test(t)) return { el: n, kind: 'privacy-named-with-cookie-text' };
      if (n.matches('[role=dialog],[role=alertdialog],[aria-modal=true],dialog')) return { el: n, kind: 'dialog-with-cookie-text' };
    }
    return null;
  };
  const text = e => (e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().replace(/[.!]+$/, '');
  const visible = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  // '#' and javascript: anchors are allowed (consent platforms use them); any other href navigates away.
  const navigates = e => { if (e.tagName !== 'A' || !e.hasAttribute('href')) return false; const h = e.getAttribute('href').trim(); return !(h === '' || h.startsWith('#') || /^javascript:/i.test(h)); };
  const cands = [...document.querySelectorAll('button, [role=button], a, input[type=button]')]
    .filter(e => visible(e) && !e.disabled && !e.form && !e.closest('form') && !navigates(e));
  for (const e of cands) {
    const l = text(e); if (!l) continue;
    if (!(label.test(l) || (agree && agree.test(l)))) continue;
    const c = container(e); if (!c) continue;
    if (!label.test(l) && c.kind !== 'named') continue;   // bare Agree / I agree: named containers only
    if (c.el.querySelector('input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=button]):not([type=submit]), textarea, iframe[src*=captcha i], iframe[title*=captcha i]'))
      return [null, { blocked: 'consent container holds text inputs or a CAPTCHA; not clicked' }];
    return [e, { label: l, containerKind: c.kind }];
  }
  return [null, null];
}

// Cookie and storage names go through red() (emails, token-like strings). The exact expiry and raw cookie names stay in
// memory only (non-enumerable, never written): the reject phase uses them to see a cookie that was re-set after the click.
async function snapshot(p, client, urls) {
  const raw = (await client.send('Network.getAllCookies')).cookies;
  const cookies = raw.map(c => ({ name: red(c.name), domain: c.domain, expires: c.expires > 0 ? new Date(c.expires * 1000).toISOString().slice(0, 10) : 'session' }));
  const st = await p.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) })).catch(() => ({ local: [], session: [] }));
  const hosts = [...new Set(urls.map(u => { try { return red(new URL(u).host); } catch (e) { return null; } }).filter(Boolean))];   // hosts are redacted like any other written text
  // Google Consent Mode: gcs/gcd parameters on Google tags show cookieless/consent-mode pings (values are not identifiers).
  const cm = {};
  for (const u of urls) { try { const q = new URL(u); const gcs = q.searchParams.get('gcs'), gcd = q.searchParams.get('gcd'); if (gcs || gcd) cm[`${q.host}|${gcs}|${gcd}`] = { host: q.host, gcs: gcs && red(gcs).slice(0, 40), gcd: gcd && red(gcd).slice(0, 80) }; } catch (e) {} }
  const snap = { cookies, storage: { local: st.local.map(red), session: st.session.map(red) }, hosts, requestCount: urls.length, consentModeSignals: Object.values(cm) };
  Object.defineProperty(snap, '_raw', { value: raw.map(c => ({ rawName: c.name, name: red(c.name), domain: c.domain, key: `${red(c.name)}|${c.domain}`, expires: c.expires })), enumerable: false });
  return snap;
}

// One phase in a fresh profile. Throws only when there is no evidence at all (navigation failed); after the pre-consent
// snapshot any failure (click, reload after the click) is returned as res.error with everything collected so far.
async function phase(a, url, vp, kind) {
  let b = null, res = null, w = null, guard = null;
  try {
    b = await freshBrowser(); const p = await openPage(b, a.scope); guard = p.__guard;
    const emulation = await setViewport(p, vp);
    const client = await p.target().createCDPSession(); w = watchRequests(p);
    const nav = await goto(p, url);
    if (nav.error) throw new Error('navigation: ' + nav.error);
    await settle(p); await sleep(1500);
    assertInScope(p);
    const pre = await snapshot(p, client, w.urls);
    res = { emulation, navigation: nav, preConsent: pre, clicked: null, containerKind: null, navigationAfterClick: null, post: null, blocked: null, error: null };
    const h = await p.evaluateHandle(findControl, kind === 'accept' ? a.accept : a.reject, kind === 'accept' ? AGREE : null, RX);
    const el = (await h.getProperty('0')).asElement(); const info = await (await h.getProperty('1')).jsonValue();
    if (el) {
      res.clicked = red(info.label).slice(0, 80); res.containerKind = info.containerKind;
      w.urls.length = 0;
      await el.evaluate(e => e.click());        // the one click of this phase, on exactly the identified element
      await sleep(2500);
      const nav2 = await goto(p, url, { reload: true });
      res.navigationAfterClick = nav2;
      if (nav2.error) throw new Error('reload after click: ' + nav2.error);
      await settle(p); await sleep(2500);
      assertInScope(p);
      res.post = await snapshot(p, client, w.urls);
    } else {
      res.blocked = (info && info.blocked) || `no ${kind} control found inside a cookie/consent container`;
    }
    return res;
  } catch (e) {
    if (!res) throw e;
    res.error = red(String(e.message || e)).slice(0, 200);
    return res;
  } finally {
    if (res && w) { res.nonGetRequests = w.nonGet; res.mixedContent = [...w.mixed].slice(0, 20); res.blockedNavigations = guard.blocked.slice(); }
    await closeBrowser(b);
  }
}

// Reject outcome. trackersBeforeClick are the pre-consent finding (reported separately). rejectHonoured looks only at what
// the Reject choice let through: vendors not there before the click, and analytics/ads cookies that are new or were re-set
// (exact expiry changed) after the click. A re-set session cookie can't be told apart; check those by hand.
function rejectOutcome(rej) {
  const before = trackers(rej.preConsent), after = rej.post ? trackers(rej.post) : null;
  const out = { clicked: rej.clicked, container: rej.containerKind, blocked: rej.blocked, error: rej.error, navigation: rej.navigation,
    navigationAfterClick: rej.navigationAfterClick, preReject: rej.preConsent, postReject: rej.post,
    nonGetRequests: rej.nonGetRequests, mixedContent: rej.mixedContent, blockedNavigations: rej.blockedNavigations,
    trackersBeforeClick: before, trackersAfterReject: after, newTrackersAfterReject: null, trackerCookiesAfterReject: null, rejectHonoured: null };
  if (rej.post) {
    out.newTrackersAfterReject = after.filter(v => !before.includes(v));
    const pre = Object.fromEntries((rej.preConsent._raw || []).map(c => [c.key, c.expires]));
    out.trackerCookiesAfterReject = (rej.post._raw || []).filter(c => tracking(vendorOf(c.rawName)) && (!(c.key in pre) || pre[c.key] !== c.expires))
      .map(c => ({ name: c.name, domain: c.domain, vendor: vendorOf(c.rawName)[1], alreadySetBeforeClick: c.key in pre }));
    out.rejectHonoured = out.newTrackersAfterReject.length === 0 && out.trackerCookiesAfterReject.length === 0;
  }
  return out;
}

async function main() {
  const a = parseArgs({
    accept: { type: 'regex', def: ACCEPT }, reject: { type: 'regex', def: REJECT }, 'no-reject': { type: 'bool' },
    width: { type: 'widths', def: '375,1366' }, policy: { type: 'url', def: null }, egress: { type: 'str', def: 'unknown' },
    out: { type: 'str', def: 'evidence/consent.json' }, delay: { type: 'int', def: '800', min: 500 },
  }, USAGE);
  needBrowser();
  a.scope = scopeHosts(a.policy ? [...a.urls, a.policy] : a.urls);   // navigation guard: input hosts, www/apex twins, the policy page's host
  const out = { generated: new Date().toISOString(), egressCountry: a.egress,
    note: 'At most one click per phase (Accept, then Reject in a separate fresh profile). The consent platform may log each choice server-side; note that in the run log. Policy keyword match is a heuristic; the lead reads the policy before rating. reject.rejectHonoured covers only what the Reject choice let through; trackers present before any click (preConsentTracking, reject.trackersBeforeClick) are a separate pre-consent finding. Severity mapping: references/consent-and-privacy.md.',
    labels: { accept: a.accept, agreeInNamedContainerOnly: AGREE, reject: a['no-reject'] ? null : a.reject }, policyError: null, results: [], failures: [] };
  let failed = 0, policyText = null;
  if (a.policy) {
    let b = null;
    try { b = await freshBrowser(); const p = await openPage(b, a.scope); const nav = await goto(p, a.policy); if (nav.error) throw new Error(nav.error); policyText = (await p.evaluate(() => document.body.innerText)).toLowerCase(); }
    catch (e) { failed++; out.policyError = String(e.message || e).slice(0, 200); }
    finally { await closeBrowser(b); await sleep(a.delay); }
  }
  for (const url of a.urls) for (const vp of a.width) {
    const r = { url: safeUrl(url), width: vp.w };
    try {
      const acc = await phase(a, url, vp, 'accept'); await sleep(a.delay);
      r.emulation = acc.emulation; r.navigation = acc.navigation; r.preConsent = acc.preConsent; r.preConsentTracking = trackers(acc.preConsent);
      r.acceptClicked = acc.clicked; r.acceptContainer = acc.containerKind; r.navigationAfterAccept = acc.navigationAfterClick;
      r.postConsent = acc.post; r.postConsentBlocked = acc.blocked; r.acceptError = acc.error;
      r.newHostsAfterConsent = acc.post ? acc.post.hosts.filter(h => !acc.preConsent.hosts.includes(h)) : [];
      r.newCookiesAfterConsent = acc.post ? acc.post.cookies.filter(c => !acc.preConsent.cookies.some(x => x.name === c.name && x.domain === c.domain)) : [];
      r.nonGetRequests = acc.nonGetRequests; r.mixedContent = acc.mixedContent; r.blockedNavigations = acc.blockedNavigations;
      if (acc.error) { failed++; out.failures.push({ url: r.url, width: vp.w, phase: 'accept', error: acc.error }); }
      if (!a['no-reject']) {
        try {
          const rej = await phase(a, url, vp, 'reject');
          r.reject = rejectOutcome(rej);
          if (rej.error) { failed++; out.failures.push({ url: r.url, width: vp.w, phase: 'reject', error: rej.error }); }
        } catch (e) {
          failed++; r.reject = { error: red(String(e.message || e)).slice(0, 200) }; out.failures.push({ url: r.url, width: vp.w, phase: 'reject', error: r.reject.error });
        } finally { await sleep(a.delay); }
      }
      if (policyText && acc.post) {
        const items = [...new Set([...acc.preConsent.hosts, ...acc.post.hosts])].map(h => ({ kind: 'host', id: h }))
          .concat(acc.post.cookies.map(c => ({ kind: 'cookie', id: c.name + '@' + c.domain })));
        const seen = {};
        r.policyCheck = items.map(it => { const pv = policyVendor(it); if (!pv) return null;
          const name = pv.name, named = policyText.includes(name) || name.split(' ').every(x => policyText.includes(x));
          return { ...it, vendor: name, category: pv.category, mentionedInPolicy: named }; })
          .filter(Boolean).filter(x => (seen[x.vendor + x.kind] ? false : (seen[x.vendor + x.kind] = true)));
      }
      console.log(`${vp.w}px ${r.url}\n  pre: cookies=${r.preConsent.cookies.length} tracking=${r.preConsentTracking.join(', ') || '-'} consentMode=${r.preConsent.consentModeSignals.length}\n  accept=${r.acceptClicked || 'NOT FOUND'} newHosts=${r.newHostsAfterConsent.join(', ') || '-'}` +
        (r.acceptError ? ` ERROR ${r.acceptError}` : '') +
        (r.reject ? `\n  reject=${r.reject.clicked || 'NOT FOUND'} rejectHonoured=${r.reject.rejectHonoured} newTrackersAfterReject=${(r.reject.newTrackersAfterReject || []).join(', ') || '-'}${r.reject.error ? ' ERROR ' + r.reject.error : ''}` : ''));
    } catch (e) {
      failed++; r.error = red(String(e.message || e)).slice(0, 200); out.failures.push({ url: r.url, width: vp.w, error: r.error });
      console.error(`${vp.w}px ${r.url} FAILED: ${r.error}`);
    } finally { out.results.push(r); writeJson(a.out, out); }
  }
  console.log('wrote', a.out, failed ? `(${failed} failed)` : '');
  process.exit(failed ? 1 : 0);
}

if (require.main === module) main().catch(e => { console.error(e); process.exit(1); });
module.exports = { ACCEPT, AGREE, REJECT, RX, findControl, phase, rejectOutcome, trackers, policyVendor };
