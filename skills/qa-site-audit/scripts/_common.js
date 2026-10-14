// Shared helpers for the qa-site-audit node scripts. Read-only headless checks.
// Needs Node 18+ (global fetch), puppeteer-core and a Chrome/Chromium binary (CHROME_PATH, default: Google Chrome's standard path on macOS or Linux).
// puppeteer-core is loaded lazily, so --help and option errors work without it. Never run npm inside the skill folder:
// use an existing install via NODE_PATH, or install in a scratch folder with the user's approval.
// Exit codes for every script: 0 = all URLs done, 1 = partial failure (results still written), 2 = usage/dependency error.
const fs = require('fs'); const os = require('os'); const path = require('path'); const crypto = require('crypto');
const CHROME = process.env.CHROME_PATH || (process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : '/usr/bin/google-chrome');
const UA_TAG = 'agentic-qa-toolkit-audit (read-only)';
const FETCH_UA = 'Mozilla/5.0 (X11; Linux x86_64) Chrome/130 Safari/537.36 ' + UA_TAG;
const sleep = ms => new Promise(r => setTimeout(r, ms));
// Consent container identification (consent_capture.js findControl; viewport_overflow.js consent-bar exclusion).
// Keep references/consent-and-privacy.md identical to these four patterns (all case-insensitive):
//   CONSENT_NAMED          id/class/aria-label that names a consent container (common consent platforms included)
//   CONSENT_PRIVACY_NAMED  'privacy' in id/class only counts when the container's own text matches CONSENT_PRIVACY_TEXT
//   CONSENT_TEXT           every container (named or dialog) must have text matching this
const CONSENT_NAMED = 'cookie|consent|gdpr|onetrust|didomi|usercentrics|trustarc|iubenda|osano|termly|cookiebot|\\bcmp\\b';
const CONSENT_PRIVACY_NAMED = 'privacy';
const CONSENT_PRIVACY_TEXT = 'cookie|consent|tracking';
const CONSENT_TEXT = 'cookie|consent|tracking';

function loadPuppeteer() {
  try { return require('puppeteer-core'); } catch (e) {
    console.error('puppeteer-core not found. Set NODE_PATH to an existing node_modules (never npm-install inside the skill folder) and retry.');
    process.exit(2);
  }
}
// Dependency check before any URL is processed: puppeteer-core and a Chrome/Chromium binary. Exit 2 (dependency error) if either is missing.
function needBrowser() {
  loadPuppeteer();
  let ok = false;
  try { fs.accessSync(CHROME, fs.constants.X_OK); ok = fs.statSync(CHROME).isFile(); } catch (e) { ok = false; }
  if (!ok) { console.error(`Chrome/Chromium binary not found or not executable at ${CHROME}. Install Chrome or set CHROME_PATH to a Chrome/Chromium binary, then retry.`); process.exit(2); }
}
function needFetch() {
  if (typeof fetch !== 'function') { console.error('Node 18+ is required (global fetch).'); process.exit(2); }
}

// Typed CLI options, parsed before any dependency loads.
// spec: { name: { type: 'str'|'int'|'regex'|'bool'|'widths'|'url', def, min, max } }. Unknown flags, missing values and bad values exit 2.
function parseArgs(spec, usage) {
  const v = process.argv.slice(2);
  const fail = msg => { console.error(msg + '\n\n' + usage); process.exit(2); };
  if (v.includes('--help') || v.includes('-h')) { console.log(usage); process.exit(0); }
  const a = { _: [] };
  for (const [k, s] of Object.entries(spec)) a[k] = s.type === 'bool' ? false : s.def;
  for (let i = 0; i < v.length; i++) {
    if (!v[i].startsWith('--')) { a._.push(v[i]); continue; }
    const k = v[i].slice(2), s = spec[k];
    if (!s) fail(`Unknown option --${k}`);
    if (s.type === 'bool') { a[k] = true; continue; }
    const n = v[i + 1];
    if (n === undefined || n.startsWith('--')) fail(`--${k} needs a value`);
    a[k] = n; i++;
  }
  for (const [k, s] of Object.entries(spec)) {
    const x = a[k];
    if (x === undefined || x === null || s.type === 'bool' || s.type === 'str') continue;
    if (s.type === 'int') {
      const n = Number(x);
      if (!Number.isInteger(n) || n < (s.min || 0)) fail(`--${k} must be a whole number >= ${s.min || 0}`);
      if (s.max !== undefined && n > s.max) fail(`--${k} must be a whole number <= ${s.max}`);
      a[k] = n;
    } else if (s.type === 'url') {
      checkUrl(x, fail, `--${k}`);
    } else if (s.type === 'regex') {
      try { new RegExp(x, 'i'); } catch (e) { fail(`--${k} is not a valid regular expression: ${e.message}`); }
    } else if (s.type === 'widths') {
      const list = String(x).split(',').map(t => t.trim()).filter(Boolean).map(t => {
        const m = /^(\d{3,4})(?:x(\d{3,4}))?$/.exec(t);
        if (!m || +m[1] < 200 || +m[1] > 4000 || (m[2] && (+m[2] < 200 || +m[2] > 4000))) fail(`--${k}: "${t}" is not a width (200-4000) or WIDTHxHEIGHT`);
        return { w: +m[1], h: m[2] ? +m[2] : null };
      });
      if (!list.length) fail(`--${k} needs at least one width`);
      a[k] = list;
    }
  }
  if (a._.length !== 1) fail('Give exactly one URL list: a file with one URL per line, or comma-separated URLs.');
  a.urls = readUrls(a._[0], fail);
  return a;
}

// One validator for the URL list and every URL-valued option: http(s), a host, no user:pass@.
function checkUrl(u, fail, what = 'URL') {
  let p; try { p = new URL(u); } catch (e) { fail(`${what}: not a URL: ${safeUrl(u)}`); }
  if (!/^https?:$/.test(p.protocol) || !p.hostname || p.username || p.password) fail(`${what}: only http(s) URLs without user:pass@ are allowed: ${safeUrl(u)}`);
}

function readUrls(arg, fail) {
  const raw = fs.existsSync(arg) ? fs.readFileSync(arg, 'utf8').split('\n') : arg.split(',');
  const urls = raw.map(s => s.trim()).filter(s => s && !s.startsWith('#'));
  for (const u of urls) checkUrl(u, fail);
  if (!urls.length) fail('The URL list is empty.');
  return urls;
}

// Evidence hygiene: drop query strings and fragments from logged URLs, mask emails and long token-like strings.
// Credential formats that contain no digit (and so escape the generic long-token rule) are matched by shape.
const EMAIL_RX = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g;
const CRED_RX = new RegExp([
  '(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}',                       // sk-... API keys
  '(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}',                  // ghp_ / gho_ / ghu_ / ghs_ / ghr_ tokens
  '(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{20,}',
  '(?<![A-Za-z0-9])xox[abeprs]-[A-Za-z0-9-]{10,}',               // Slack tokens
  '(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])',    // AWS access key ids
  '(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{5,}\\.[A-Za-z0-9_-]{5,}(?:\\.[A-Za-z0-9_-]*)?', // JWT-shaped
].join('|'), 'g');
const BEARER_RX = /\bBearer\s+[A-Za-z0-9._~+/=-]{8,}/g;
const redToken = s => String(s)
  .replace(BEARER_RX, 'Bearer …<redacted>')
  .replace(CRED_RX, m => m.slice(0, 4) + '…<redacted>')
  .replace(/(?=[A-Za-z_]*\d)[A-Za-z0-9_]{20,}/g, m => m.slice(0, 4) + '…<redacted>');
const redEmail = s => String(s).replace(EMAIL_RX, '<email>');
// Host and the rest of the path stay readable; emails and token-like strings inside the path are masked.
function redPath(pathname) {
  let dec; try { dec = decodeURIComponent(pathname); } catch (e) { dec = pathname; }
  const out = redToken(redEmail(dec));
  return out === dec ? pathname : out;
}
function safeUrl(u) {
  try { const p = new URL(u); return p.origin + redPath(p.pathname); }
  catch (e) { return redToken(redEmail(String(u).split(/[?#]/)[0].slice(0, 200))); }
}
const red = s => redToken(redEmail(String(s).replace(/https?:\/\/[^\s"'<>)]+/g, u => safeUrl(u))));

// Navigation scope. The allowed hosts are the hosts of every input URL plus their www/apex twin (never for IP addresses or localhost).
const nonDomainHost = h => /^\[.*\](:\d+)?$/.test(h) || /^\d{1,3}(\.\d{1,3}){3}(:\d+)?$/.test(h) || /^localhost(:\d+)?$/i.test(h);
function scopeHosts(urls) {
  const set = new Set();
  for (const u of urls) {
    const h = new URL(u).host; set.add(h);
    if (!nonDomainHost(h)) set.add(h.startsWith('www.') ? h.slice(4) : 'www.' + h);
  }
  return set;
}

// Fresh, throwaway profile per launch = clean first visit (no stored consent, cookies or cache). Profile removed even if launch fails.
async function freshBrowser() {
  const puppeteer = loadPuppeteer();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qa-prof-'));
  try {
    const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', userDataDir: dir,
      args: ['--no-first-run', '--no-default-browser-check', '--disable-extensions'] });
    browser.__dir = dir;
    return browser;
  } catch (e) { fs.rmSync(dir, { recursive: true, force: true }); throw e; }
}
// Bounded: a browser that does not close within 10 s is killed, so a stuck Chrome can never hang a script.
async function closeBrowser(b) {
  if (!b) return;
  const proc = b.process && b.process();
  try { await Promise.race([b.close(), sleep(10000)]); } catch (e) {}
  if (proc && proc.exitCode === null) { try { proc.kill('SIGKILL'); } catch (e) {} }
  try { fs.rmSync(b.__dir, { recursive: true, force: true }); } catch (e) {}
}

// Open a page with the navigation guard installed BEFORE its first navigation. The guard blocks exactly two things and lets every
// other request (sub-resources, XHR, fetch, beacons of any method) through untouched, so tracking is measured as a visitor's
// browser would send it:
//   - any navigation request (any frame) whose method is not GET            -> kind 'non-GET navigation'
//   - a main-frame navigation to a host outside allowHosts (incl. redirects) -> kind 'off-scope navigation'
// Blocked requests are recorded (kind and host only) in page.__guard.blocked. Note: Puppeteer disables the HTTP cache while
// request interception is on, so every request, including after a reload, reaches the network and is recorded.
async function openPage(browser, allowHosts) {
  const page = await browser.newPage();
  const g = { blocked: [], allowHosts };
  page.__guard = g;
  await page.setRequestInterception(true);
  page.on('request', req => {
    if (req.isInterceptResolutionHandled()) return;
    let kind = null, host = '?';
    try {
      if (req.isNavigationRequest()) {
        const u = new URL(req.url()); host = u.host || '?';
        if (req.method() !== 'GET') kind = 'non-GET navigation';
        else if (/^https?:$/.test(u.protocol) && req.frame() === page.mainFrame() && !allowHosts.has(u.host)) kind = 'off-scope navigation';
      }
    } catch (e) { kind = null; }
    if (kind) {
      req.__qaBlocked = true;
      if (g.blocked.length < 20) g.blocked.push({ kind, host: red(host) });   // exact hosts stay in allowHosts for the scope check; only a redacted host is stored
      // Answered with an empty 204, never sent: a 204 navigation leaves the current document in place, whereas an aborted one
      // would replace it with Chrome's own error page (and the scripts would then measure that page).
      req.respond({ status: 204, headers: { 'cache-control': 'no-store' }, body: '' }).catch(() => {});
    } else req.continue().catch(() => {});
  });
  return page;
}
// Message when the page tried to leave the input URLs' hosts (the navigation was blocked), else null.
function scopeViolation(page) {
  const o = page.__guard && page.__guard.blocked.find(b => b.kind === 'off-scope navigation');
  return o ? `main-frame navigation to ${o.host} is outside the input URLs; blocked` : null;
}
function assertInScope(page) { const m = scopeViolation(page); if (m) throw new Error(m); }

// Emulation: mobile below 768 (or a short landscape phone such as 844x390), touch up to and including 1024.
// opts.mobile === false forces a desktop (non-mobile, non-touch) probe at the same width.
async function setViewport(page, vp, opts = {}) {
  const w = vp.w, h = vp.h || (w < 768 ? 844 : 900);
  let mobile = w < 768 || (h < 500 && h < w);
  let touch = mobile || w <= 1024;
  if (opts.mobile === false) { mobile = false; touch = false; }
  await page.setViewport({ width: w, height: h, isMobile: mobile, hasTouch: touch, deviceScaleFactor: 1 });
  let ua = (await page.browser().userAgent()).replace('HeadlessChrome', 'Chrome');
  if (mobile) ua = ua.replace(/\([^)]*\)/, '(Linux; Android 10; K)').replace(/Safari\//, 'Mobile Safari/');
  await page.setUserAgent(ua + ' ' + UA_TAG);
  if (opts.reducedMotion) await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  return { width: w, height: h, mobile, touch, ua: mobile ? 'mobile (Android Chrome)' : 'desktop Chrome', reducedMotion: !!opts.reducedMotion };
}

// Settle: wait for finite CSS/Web-Animations to finish (bounded), then for a DOM quiet period (no mutations for quietMs,
// bounded) which catches JS-driven typewriters, count-ups and reveals that the Animations API can't see, then a short pause.
async function settle(page, maxMs = 6000, quietMs = 1000) {
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    const running = await page.evaluate(() => (document.getAnimations ? document.getAnimations().filter(a => a.playState === 'running' && a.effect && a.effect.getTiming().iterations !== Infinity).length : 0)).catch(() => 0);
    if (!running) break;
    await sleep(300);
  }
  await page.evaluate((quiet, cap) => new Promise(res => {
    let last = Date.now(); const start = last;
    const mo = new MutationObserver(() => { last = Date.now(); });
    mo.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
    const iv = setInterval(() => { const now = Date.now(); if (now - last >= quiet || now - start >= cap) { clearInterval(iv); mo.disconnect(); res(); } }, 100);
  }), quietMs, maxMs).catch(() => {});
  await sleep(500);
}

// Step-scroll in viewport-height steps with a pause, so IntersectionObserver reveals and lazy images fire, then back to top.
async function stepScroll(page, pauseMs = 1000, maxSteps = 12) {
  await page.evaluate(async (pause, steps) => {
    for (let i = 1; i <= steps && scrollY + innerHeight < document.documentElement.scrollHeight; i++) {
      scrollTo(0, i * innerHeight); await new Promise(r => setTimeout(r, pause));
    }
    scrollTo(0, 0);
  }, pauseMs, maxSteps).catch(() => {});
}

// Normalised media type of a Content-Type header ("text/html; charset=utf-8" -> "text/html"); '' if absent or malformed.
// Only this normalised value is ever written to evidence, never the raw header.
function mediaType(header) {
  const m = String(header || '').split(';')[0].trim().toLowerCase();
  return /^[a-z0-9][a-z0-9!#$&^_.+-]*\/[a-z0-9][a-z0-9!#$&^_.+-]*$/.test(m) ? m : '';
}
const HTML_TYPES = new Set(['text/html', 'application/xhtml+xml']);

// Describe a main-document response: { status, finalUrl, contentType, redirects, error? }. error = do not measure this page.
function describeNav(page, r) {
  const ct = mediaType(r.headers()['content-type']);
  const nav = { status: r.status(), finalUrl: safeUrl(page.url()), contentType: ct, redirects: r.request().redirectChain().length };
  if (nav.status >= 400) nav.error = `HTTP ${nav.status}`;
  else if (nav.status >= 300) nav.error = `HTTP ${nav.status} (redirect not completed)`;
  else if (!HTML_TYPES.has(ct)) nav.error = `not HTML (${ct || 'no content-type'})`;
  return nav;
}

// Navigate and check the result. Returns { status, finalUrl, contentType, redirects, error?, warning? }.
// error = do not measure this page (HTTP >= 400, not HTML, no response, network failure, navigation outside the input hosts).
// opts.timeoutMs overrides the 60 s load timeout (tests only). opts.reload loads the URL again from a blank page (see below).
async function goto(page, url, opts = {}) {
  const limit = opts.timeoutMs || 60000, secs = Math.round(limit / 1000);
  let main = null;   // latest main-document response seen, kept so the timeout path can still check status and type
  const onResponse = r => { try { if (!r.request().__qaBlocked && r.request().isNavigationRequest() && r.frame() === page.mainFrame()) main = r; } catch (e) {} };
  page.on('response', onResponse);
  try {
    const wait = { waitUntil: 'networkidle2', timeout: limit };
    // A "reload" starts from about:blank: page.reload() would repeat a pending (blocked) POST navigation, and a goto to the
    // current URL with a #fragment is a same-document navigation. Cookies and storage survive, so the second load is a real one.
    if (opts.reload) await page.goto('about:blank');
    const r = await page.goto(url, wait);
    const scope = scopeViolation(page);
    if (scope) return { error: scope };
    // A page that submitted a form while loading can make page.goto resolve with our own blocked 204; the real document is `main`.
    const resp = r && r.request().__qaBlocked ? main : r;
    if (!resp) return { error: 'no response' };
    return describeNav(page, resp);
  } catch (e) {
    const scope = scopeViolation(page);
    if (scope) return { error: scope };
    if (e && e.name === 'TimeoutError') {
      // Only measure a timed-out load when the target document really is there: its main response was received and is a good
      // HTML response (same status and type rules as a normal load), it came from a host inside the allowed navigation scope
      // (so a permitted redirect, such as to the www/apex twin or from http to https, is fine), the page is still on that
      // document's origin (not about:blank or chrome-error://) and has a <body> with some text. Otherwise it is a failed navigation.
      const cur = page.url();
      if (!main) return { finalUrl: safeUrl(cur), error: `navigation timed out without a main-document response (page at ${safeUrl(cur)})` };
      const nav = describeNav(page, main);
      if (nav.error) return { ...nav, error: `${nav.error} (network never idle within ${secs} s)` };
      let usable = false;
      try {
        const mainUrl = new URL(main.url()), allow = page.__guard && page.__guard.allowHosts;
        if (allow ? !allow.has(mainUrl.host) : mainUrl.origin !== new URL(url).origin) return { ...nav, error: `main document came from ${red(mainUrl.host)}, outside the input URLs (network never idle within ${secs} s)` };
        usable = new URL(cur).origin === mainUrl.origin &&
          await Promise.race([page.evaluate(() => !!document.body && document.body.innerText.trim().length > 0), sleep(5000).then(() => false)]);
      } catch (x) { usable = false; }
      if (usable) return { ...nav, warning: `network not idle after ${secs} s; target document present, measured anyway (partial)` };
      return { ...nav, error: `navigation timed out without a usable target document (page at ${safeUrl(cur)})` };
    }
    return { error: red(String((e && e.message) || e)).slice(0, 200) };
  } finally { page.off('response', onResponse); }
}

// Count requests the page's own JS makes, for information only (nothing is blocked; see N13 in the skill notes).
function watchRequests(page) {
  const w = { urls: [], nonGet: {}, mixed: new Set() };
  page.on('request', r => {
    if (r.__qaBlocked) return;   // blocked by the navigation guard: never sent, so not recorded as traffic
    const u = r.url(); w.urls.push(u);
    const m = r.method();
    let host = '?'; try { host = new URL(u).host; } catch (e) {}
    if (!['GET', 'HEAD', 'OPTIONS'].includes(m)) { const k = `${m} ${red(host)}`; w.nonGet[k] = (w.nonGet[k] || 0) + 1; }
    if (u.startsWith('http:') && page.url().startsWith('https:')) w.mixed.add(safeUrl(u));
  });
  return w;
}

// Polite GET for the scripts' own fetches: delay between calls, timeout, size cap, tagged UA, optional cache of good responses.
// Redirects are followed by hand (at most 3 hops) and only while every hop stays on a host in allowHosts (when given);
// an off-scope hop is not fetched: { skipped: 'skipped (off-scope redirect)' }. statusOnly = probe: read no body, record status.
// Returns { status, finalUrl, redirects, sourceMapHeader, text, truncated } or { error } or { skipped }. finalUrl is exact
// (operational); callers pass it through safeUrl before writing evidence.
let lastFetch = 0;
async function politeGet(url, { timeoutMs = 15000, maxBytes = 5e6, delayMs = 1000, cacheDir = null, allowHosts = null, statusOnly = false } = {}) {
  const key = cacheDir ? path.join(cacheDir, crypto.createHash('sha1').update((statusOnly ? 'status:' : '') + url).digest('hex') + '.json') : null;
  if (key && fs.existsSync(key)) return { ...JSON.parse(fs.readFileSync(key, 'utf8')), cached: true };
  const redirects = []; let cur = url;
  for (let hop = 0; ; hop++) {
    const wait = delayMs - (Date.now() - lastFetch);
    if (wait > 0) await sleep(wait);
    const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const r = await fetch(cur, { method: 'GET', redirect: 'manual', signal: ctl.signal, headers: { 'User-Agent': FETCH_UA } });
      if (r.status >= 300 && r.status < 400 && r.headers.get('location')) {
        if (r.body) await r.body.cancel().catch(() => {});
        let next; try { next = new URL(r.headers.get('location'), cur); } catch (e) { return { error: `bad redirect location after ${safeUrl(cur)}`, redirects }; }
        redirects.push(`${r.status} ${safeUrl(next.href)}`);
        if (!/^https?:$/.test(next.protocol) || next.username || next.password || (allowHosts && !allowHosts.has(next.host)))
          return { skipped: 'skipped (off-scope redirect)', status: r.status, finalUrl: next.href, redirects };
        if (hop >= 3) return { error: 'more than 3 redirects', redirects };
        cur = next.href; continue;
      }
      const out = { status: r.status, finalUrl: cur, redirects, sourceMapHeader: r.headers.get('sourcemap') || r.headers.get('x-sourcemap') || null };
      if (statusOnly) {
        if (r.body) await r.body.cancel().catch(() => {});
        out.probe = 'status only';
      } else {
        const chunks = []; let size = 0, truncated = false;
        if (r.body) for await (const c of r.body) { size += c.length; if (size > maxBytes) { truncated = true; break; } chunks.push(Buffer.from(c)); }
        out.text = Buffer.concat(chunks).toString('utf8'); out.truncated = truncated;
      }
      if (key && r.status === 200 && !out.truncated) { fs.mkdirSync(cacheDir, { recursive: true }); fs.writeFileSync(key, JSON.stringify(out)); }
      return out;
    } catch (e) {
      return { error: ctl.signal.aborted ? `timeout after ${timeoutMs} ms` : red(String((e && e.message) || e)).slice(0, 200), redirects };
    } finally { clearTimeout(timer); lastFetch = Date.now(); }
  }
}

// Incremental, atomic JSON write (called after every URL so a crash never loses finished results).
function writeJson(file, obj) {
  fs.mkdirSync(path.dirname(path.resolve(file)), { recursive: true });
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 1));
  fs.renameSync(tmp, file);
}

module.exports = { fs, path, parseArgs, checkUrl, safeUrl, red, redToken, redEmail, mediaType, nonDomainHost, scopeHosts, openPage, scopeViolation, assertInScope, needBrowser, freshBrowser, closeBrowser, setViewport, settle, stepScroll, goto,
  watchRequests, politeGet, writeJson, needFetch, sleep, CHROME, UA_TAG, CONSENT_NAMED, CONSENT_PRIVACY_NAMED, CONSENT_PRIVACY_TEXT, CONSENT_TEXT };
