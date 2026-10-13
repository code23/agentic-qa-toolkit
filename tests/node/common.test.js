'use strict';
// Unit tests for the pure helpers in _common.js (no browser needed) and for the viewport/consent helpers that are plain functions.
const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const http = require('http');
const { SCRIPTS, REFERENCES, makeTmp, rmTmp } = require('./helpers');

const common = require(path.join(SCRIPTS, '_common.js'));
const { parity } = require(path.join(SCRIPTS, 'viewport_overflow.js'));
const consent = require(path.join(SCRIPTS, 'consent_capture.js'));

describe('safeUrl', () => {
  it('drops query string, fragment and credentials', () => {
    assert.equal(common.safeUrl('https://example.com/a/b?token=abc#frag'), 'https://example.com/a/b');
    assert.equal(common.safeUrl('http://user:secretpw@example.com:8080/x?y=1'), 'http://example.com:8080/x');
  });
  it('cuts unparseable input at the first ? or #', () => {
    assert.equal(common.safeUrl('not a url?secret=1'), 'not a url');
    assert.equal(common.safeUrl('x#y'), 'x');
    assert.ok(common.safeUrl('a'.repeat(500)).length <= 200);
  });
});

describe('safeUrl path redaction', () => {
  it('masks emails and token-like strings in the path and keeps host and the rest readable', () => {
    assert.equal(common.safeUrl('https://shop.example.com/users/jo@example.org/orders?x=1'), 'https://shop.example.com/users/<email>/orders');
    assert.equal(common.safeUrl('https://shop.example.com/users/jo%40example.org/orders'), 'https://shop.example.com/users/<email>/orders');
    assert.equal(common.safeUrl('https://example.com/reset/QX7R2M9KLP4W8ZC3VB6N5A/done#top'), 'https://example.com/reset/QX7R…<redacted>/done');
    assert.equal(common.safeUrl('https://example.com/key/sk-abcdefghijklmnopqrstuvwx'), 'https://example.com/key/sk-a…<redacted>');
  });
  it('leaves ordinary paths, including encoded non-ASCII characters, exactly as they are', () => {
    assert.equal(common.safeUrl('https://example.com/blog/2026-annual-report.html?x=1'), 'https://example.com/blog/2026-annual-report.html');
    assert.equal(common.safeUrl('https://example.com/caf%C3%A9/menu'), 'https://example.com/caf%C3%A9/menu');
    assert.equal(common.safeUrl('http://127.0.0.1:8765/index.html'), 'http://127.0.0.1:8765/index.html');
  });
  it('also masks the unparseable fallback', () => {
    assert.equal(common.safeUrl('see jo@example.org?x=1'), 'see <email>');
  });
});

describe('red: credential formats without a digit', () => {
  const cases = {
    'sk- key': ['key sk-abcdefghijklmnopqrstuvwx', 'key sk-a…<redacted>'],
    'sk-ant style': ['sk-ant-api-abcdefghijklmnopqrstuvwx', 'sk-a…<redacted>'],
    'GitHub token': ['token ghp_abcdefghijklmnopqrstuvwxyzABCD end', 'token ghp_…<redacted> end'],
    'GitHub fine-grained': ['github_pat_abcdefghijklmnopqrstuvwxyz', 'gith…<redacted>'],
    'Slack token': ['xoxb-abcdefghijkl-mnopqrstuvwx', 'xoxb…<redacted>'],
    'AWS key id': ['id AKIAABCDEFGHIJKLMNOP.', 'id AKIA…<redacted>.'],
    'Bearer header': ['Authorization: Bearer abcdefghijkl', 'Authorization: Bearer …<redacted>'],
    'JWT': ['jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhYmMifQ.c2lnbmF0dXJl ok', 'jwt eyJh…<redacted> ok'],
  };
  for (const [name, [input, want]] of Object.entries(cases)) it(`masks a ${name}`, () => assert.equal(common.red(input), want));
  it('does not touch look-alike words', () => {
    for (const t of ['the task-force was formed', 'ask-anything-about-bikes', 'sketch-pad-ideas-for-everyone', 'a bearer of good news']) assert.equal(common.red(t), t);
  });
});

describe('mediaType', () => {
  it('keeps only a normalised media type', () => {
    assert.equal(common.mediaType('text/html; charset=utf-8'), 'text/html');
    assert.equal(common.mediaType('  TEXT/HTML '), 'text/html');
    assert.equal(common.mediaType('application/xhtml+xml;x=jo@example.org'), 'application/xhtml+xml');
  });
  it('returns an empty string for anything malformed or absent', () => {
    for (const bad of [undefined, null, '', 'html', 'text/', '/html', 'text/html, text/plain', 'a b/c', '<script>/x']) assert.equal(common.mediaType(bad), '', String(bad));
  });
});

describe('scopeHosts', () => {
  const list = urls => [...common.scopeHosts(urls)].sort();
  it('adds the www/apex twin of a named host, keeping the port', () => {
    assert.deepEqual(list(['https://example.com/a']), ['example.com', 'www.example.com']);
    assert.deepEqual(list(['http://www.example.com:8080/']), ['example.com:8080', 'www.example.com:8080']);
  });
  it('adds no twin for IP addresses (v4 or v6) or localhost', () => {
    assert.deepEqual(list(['http://127.0.0.1:8765/', 'http://[::1]:9/', 'http://localhost:3000/']), ['127.0.0.1:8765', '[::1]:9', 'localhost:3000']);
  });
  it('unions the hosts of all input URLs', () => {
    assert.deepEqual(list(['https://a.example/x', 'https://b.example/y']), ['a.example', 'b.example', 'www.a.example', 'www.b.example']);
  });
});

describe('red / redToken', () => {
  it('replaces email addresses', () => {
    assert.equal(common.red('write to jo.bloggs+qa@mail.example.co.uk now'), 'write to <email> now');
  });
  it('cuts long token-like strings that contain a digit and keeps four characters', () => {
    assert.equal(common.redToken('key abcd1234efgh5678ijkl9012 end'), 'key abcd…<redacted> end');
    assert.equal(common.redToken('QX7R2M9KLP4W8ZC3VB6N5A'), 'QX7R…<redacted>');
    assert.equal(common.redToken('session_' + '9'.repeat(20)), 'sess…<redacted>');
  });
  it('leaves ordinary long words, short ids and plain numbers alone', () => {
    assert.equal(common.redToken('internationalisationpossibilities'), 'internationalisationpossibilities');
    assert.equal(common.redToken('abcd1234efgh5678ijk'), 'abcd1234efgh5678ijk');   // 19 characters
    assert.equal(common.redToken('call 01632960123 today'), 'call 01632960123 today');
  });
  it('strips query strings and fragments from URLs inside text', () => {
    const out = common.red('failed https://example.com/api?key=SECRET#top (see https://example.com/x?y=1)');
    assert.ok(!out.includes('SECRET') && !out.includes('?') && !out.includes('#'), out);
    assert.match(out, /https:\/\/example\.com\/api /);
  });
  it('accepts non-string input', () => {
    assert.equal(common.red(404), '404');
    assert.equal(common.red(undefined), 'undefined');
  });
});

describe('checkUrl', () => {
  const fail = m => { throw new Error(m); };
  it('accepts http and https URLs', () => {
    common.checkUrl('http://127.0.0.1:8765/index.html', fail);
    common.checkUrl('https://example.com', fail);
  });
  it('rejects other schemes, credentials and non-URLs', () => {
    for (const bad of ['ftp://example.com/', 'file:///etc/passwd', 'javascript:alert(1)', 'example.com', '', 'http://']) {
      assert.throws(() => common.checkUrl(bad, fail), /URL|not a URL|only http/, bad);
    }
    assert.throws(() => common.checkUrl('http://user:secretpw@example.com/', fail), /only http\(s\) URLs without user:pass@/);
  });
  it('does not echo credentials or query strings in its error', () => {
    try { common.checkUrl('http://user:secretpw@example.com/p?token=abc', fail); assert.fail('should throw'); } catch (e) {
      assert.ok(!/secretpw|token=abc/.test(e.message), e.message);
    }
  });
  it('names the option when one is given', () => {
    assert.throws(() => common.checkUrl('ftp://x', fail, '--policy'), /^Error: --policy:/);
  });
});

describe('writeJson', () => {
  let tmp;
  before(() => { tmp = makeTmp(); });
  after(() => rmTmp(tmp));
  it('creates parent folders, writes valid JSON atomically and leaves no temp file', () => {
    const file = path.join(tmp, 'deep', 'er', 'out.json');
    common.writeJson(file, { a: 1, b: ['x'] });
    common.writeJson(file, { a: 2 });
    assert.deepEqual(JSON.parse(fs.readFileSync(file, 'utf8')), { a: 2 });
    assert.deepEqual(fs.readdirSync(path.dirname(file)), ['out.json']);
  });
});

describe('politeGet', () => {
  let server, base, seen;
  before(async () => {
    seen = [];
    server = http.createServer((req, res) => {
      seen.push({ path: req.url, ua: req.headers['user-agent'] });
      const u = new URL(req.url, 'http://x');
      switch (u.pathname) {
        case '/ok': res.writeHead(200, { sourcemap: 'ok.js.map' }); return res.end('hello');
        case '/in': res.writeHead(302, { location: '/ok' }); return res.end();
        case '/off': res.writeHead(302, { location: `http://localhost:${server.address().port}/ok` }); return res.end();
        case '/scheme': res.writeHead(302, { location: 'ftp://example.com/x' }); return res.end();
        case '/creds': res.writeHead(302, { location: `http://u:p@127.0.0.1:${server.address().port}/ok` }); return res.end();
        case '/loop': res.writeHead(302, { location: '/loop' }); return res.end();
        case '/big': res.writeHead(200); return res.end('x'.repeat(50000));
        case '/slow': return setTimeout(() => res.end('late'), 3000);
        case '/missing': res.writeHead(404); return res.end('no');
        default: res.writeHead(200); return res.end('default');
      }
    });
    await new Promise(r => server.listen(0, '127.0.0.1', r));
    base = `http://127.0.0.1:${server.address().port}`;
  });
  after(() => new Promise(r => { server.closeAllConnections(); server.close(r); }));
  const opts = extra => ({ delayMs: 0, ...extra });

  it('returns status, text and the SourceMap header, and sends the tagged user agent', async () => {
    const r = await common.politeGet(base + '/ok', opts());
    assert.equal(r.status, 200); assert.equal(r.text, 'hello'); assert.equal(r.sourceMapHeader, 'ok.js.map'); assert.equal(r.truncated, false);
    assert.ok(seen.at(-1).ua.includes(common.UA_TAG), seen.at(-1).ua);
  });
  it('follows a redirect by hand while it stays on an allowed host', async () => {
    const r = await common.politeGet(base + '/in', opts({ allowHosts: new Set([base.replace('http://', '')]) }));
    assert.equal(r.status, 200); assert.equal(r.text, 'hello'); assert.equal(r.redirects.length, 1); assert.equal(r.finalUrl, base + '/ok');
  });
  it('does not follow a redirect to a host outside allowHosts', async () => {
    const before = seen.length;
    const r = await common.politeGet(base + '/off', opts({ allowHosts: new Set([base.replace('http://', '')]) }));
    assert.equal(r.skipped, 'skipped (off-scope redirect)');
    assert.equal(seen.length - before, 1, 'only the first request may reach the server');
  });
  it('refuses non-http redirect targets and redirect targets with credentials', async () => {
    assert.equal((await common.politeGet(base + '/scheme', opts())).skipped, 'skipped (off-scope redirect)');
    assert.equal((await common.politeGet(base + '/creds', opts())).skipped, 'skipped (off-scope redirect)');
  });
  it('gives up after three redirects', async () => {
    const r = await common.politeGet(base + '/loop', opts());
    assert.match(r.error, /more than 3 redirects/);
  });
  it('caps the body at maxBytes and marks it truncated', async () => {
    const r = await common.politeGet(base + '/big', opts({ maxBytes: 10000 }));
    assert.equal(r.truncated, true); assert.ok(r.text.length < 50000);
  });
  it('times out', async () => {
    const r = await common.politeGet(base + '/slow', opts({ timeoutMs: 300 }));
    assert.match(r.error, /timeout after 300 ms/);
  });
  it('reports a refused connection as an error', async () => {
    const dead = http.createServer(); await new Promise(r => dead.listen(0, '127.0.0.1', r));
    const port = dead.address().port; await new Promise(r => dead.close(r));
    const r = await common.politeGet(`http://127.0.0.1:${port}/`, opts());
    assert.ok(r.error && !r.status, JSON.stringify(r));
  });
  it('statusOnly reads no body', async () => {
    const r = await common.politeGet(base + '/ok', opts({ statusOnly: true }));
    assert.equal(r.status, 200); assert.equal(r.probe, 'status only'); assert.equal(r.text, undefined);
  });
  it('waits between calls (delayMs)', async () => {
    await common.politeGet(base + '/ok', opts());
    const t0 = Date.now();
    await common.politeGet(base + '/ok', { delayMs: 400 });
    assert.ok(Date.now() - t0 >= 350, `elapsed ${Date.now() - t0} ms`);
  });
  it('caches only good (200, untruncated) responses and serves them without a request', async () => {
    const tmp = makeTmp();
    try {
      const n0 = seen.length;
      const a = await common.politeGet(base + '/ok?x=1', opts({ cacheDir: tmp }));
      const b = await common.politeGet(base + '/ok?x=1', opts({ cacheDir: tmp }));
      assert.equal(seen.length - n0, 1); assert.equal(a.cached, undefined); assert.equal(b.cached, true); assert.equal(b.text, 'hello');
      await common.politeGet(base + '/missing', opts({ cacheDir: tmp }));
      await common.politeGet(base + '/missing', opts({ cacheDir: tmp }));
      assert.equal(seen.filter(s => s.path === '/missing').length, 2, 'a 404 must not be cached');
    } finally { rmTmp(tmp); }
  });
});

describe('parity (mobile vs desktop visible text)', () => {
  const t = (w, text) => ({ w, text });
  it('reports nothing for identical text', () => {
    const r = parity(t(375, 'Hello there\nBook now'), t(1440, 'Hello there\nBook now'));
    assert.equal(r.onlyNarrowCount, 0); assert.equal(r.onlyWideCount, 0); assert.equal(r.withNumbersOrPrices, 0);
  });
  it('ignores lines that only wrap or split differently', () => {
    const r = parity(t(375, 'Open Tuesday\nto Saturday'), t(1440, 'Open Tuesday to Saturday'));
    assert.equal(r.onlyNarrowCount, 0); assert.equal(r.onlyWideCount, 0);
  });
  it('reports a changed price on each side and ranks prices first', () => {
    const r = parity(t(375, 'About us\nStandard service from £39\nFree tea'), t(1440, 'About us\nStandard service from £45\nNice tea'));
    assert.deepEqual(r.onlyNarrow[0], 'standard service from £39');
    assert.deepEqual(r.onlyWide[0], 'standard service from £45');
    assert.equal(r.withNumbersOrPrices, 2);
    assert.equal(r.narrow, 375); assert.equal(r.wide, 1440);
  });
  it('redacts emails and token-like strings in the reported lines', () => {
    const r = parity(t(375, 'x'), t(1440, 'Mail jo@example.com ref QX7R2M9KLP4W8ZC3VB6N5A'));
    const line = r.onlyWide.find(l => l.includes('mail'));
    assert.ok(line && line.includes('<email>') && line.includes('<redacted>') && !/example\.com|2m9klp/i.test(line), line);
  });
  it('ignores lines shorter than three characters and caps the lists at ten', () => {
    const many = Array.from({ length: 30 }, (_, i) => `unique line number ${i}`).join('\n');
    const r = parity(t(375, 'ok\nab'), t(1440, many));
    assert.equal(r.onlyNarrowCount, 0); assert.equal(r.onlyWideCount, 30); assert.equal(r.onlyWide.length, 10);
  });
});

describe('consent_capture pure helpers', () => {
  const snap = (hosts, cookies) => {
    const s = { hosts, cookies: cookies.map(c => ({ name: c.name, domain: c.domain || 'example.test' })) };
    Object.defineProperty(s, '_raw', { enumerable: false, value: cookies.map(c => ({ rawName: c.name, name: c.name, domain: c.domain || 'example.test', key: `${c.name}|${c.domain || 'example.test'}`, expires: c.expires ?? -1 })) });
    return s;
  };

  it('trackers: identifies analytics and ad vendors by host or cookie prefix, ignores functional ones, sorted and unique', () => {
    const s = snap(['www.googletagmanager.com', 'fonts.googleapis.com', 'js.stripe.com', 'cdn.example.test'], [{ name: '_ga' }, { name: '_fbp' }, { name: '_hjid' }, { name: 'plain_cookie' }]);
    assert.deepEqual(consent.trackers(s), ['google analytics', 'hotjar', 'meta']);
  });
  it('trackers: nothing for a clean snapshot', () => {
    assert.deepEqual(consent.trackers(snap(['127.0.0.1:1'], [{ name: 'session' }])), []);
  });

  const rej = (pre, post, extra = {}) => ({ clicked: 'Reject all', containerKind: 'named', blocked: null, error: null, navigation: {}, navigationAfterClick: {}, preConsent: pre, post, ...extra });
  it('rejectOutcome: honoured when nothing new appears after Reject, even if trackers were there before the click', () => {
    const pre = snap([], [{ name: '_ga', expires: 1000 }]), post = snap([], [{ name: '_ga', expires: 1000 }]);
    const o = consent.rejectOutcome(rej(pre, post));
    assert.equal(o.rejectHonoured, true); assert.deepEqual(o.trackersBeforeClick, ['google analytics']); assert.deepEqual(o.newTrackersAfterReject, []);
  });
  it('rejectOutcome: not honoured when a new analytics cookie appears', () => {
    const o = consent.rejectOutcome(rej(snap([], []), snap([], [{ name: '_hjid', expires: 5 }])));
    assert.equal(o.rejectHonoured, false); assert.deepEqual(o.newTrackersAfterReject, ['hotjar']);
    assert.deepEqual(o.trackerCookiesAfterReject, [{ name: '_hjid', domain: 'example.test', vendor: 'hotjar', alreadySetBeforeClick: false }]);
  });
  it('rejectOutcome: not honoured when a tracker cookie that was already there is re-set (expiry changed)', () => {
    const o = consent.rejectOutcome(rej(snap([], [{ name: '_ga', expires: 1000 }]), snap([], [{ name: '_ga', expires: 2000 }])));
    assert.equal(o.rejectHonoured, false); assert.deepEqual(o.newTrackersAfterReject, []);
    assert.equal(o.trackerCookiesAfterReject[0].alreadySetBeforeClick, true);
  });
  it('rejectOutcome: not honoured when a new tracker host is contacted', () => {
    const o = consent.rejectOutcome(rej(snap([], []), snap(['www.googletagmanager.com'], [])));
    assert.equal(o.rejectHonoured, false);
  });
  it('rejectOutcome: unknown (null) when there was no click or no reload', () => {
    const o = consent.rejectOutcome(rej(snap([], []), null, { clicked: null, blocked: 'no reject control found inside a cookie/consent container' }));
    assert.equal(o.rejectHonoured, null); assert.equal(o.trackersAfterReject, null); assert.match(o.blocked, /no reject control/);
  });
});

describe('consent_capture policyVendor', () => {
  it('never derives a vendor from an IP address (v4 or v6, with or without a port) or localhost', () => {
    for (const id of ['127.0.0.1', '127.0.0.1:8765', '10.1.2.3:80', '[::1]', '[::1]:8765', '[2001:db8::1]:443', 'localhost', 'localhost:3000', 'LOCALHOST']) {
      assert.equal(consent.policyVendor({ kind: 'host', id }), null, id);
    }
  });
  it('still names a vendor from a named host, as before', () => {
    assert.deepEqual(consent.policyVendor({ kind: 'host', id: 'cdn.widgets-example.invalid' }), { name: 'widgets-example', category: 'unknown' });
    assert.deepEqual(consent.policyVendor({ kind: 'host', id: 'www.googletagmanager.com' }), { name: 'google analytics', category: 'analytics' });
    assert.deepEqual(consent.policyVendor({ kind: 'cookie', id: '_hjid@example.test' }), { name: 'hotjar', category: 'analytics' });
    assert.equal(consent.policyVendor({ kind: 'cookie', id: 'plain@example.test' }), null);
  });
});

describe('reference docs stay identical to the script patterns', () => {
  const doc = fs.readFileSync(path.join(REFERENCES, 'consent-and-privacy.md'), 'utf8');
  it('documents the default Accept, Agree and Reject label patterns character for character', () => {
    for (const [name, rx] of [['ACCEPT', consent.ACCEPT], ['AGREE', consent.AGREE], ['REJECT', consent.REJECT]]) {
      assert.ok(doc.includes('`' + rx + '`'), `consent-and-privacy.md no longer contains the ${name} pattern ${rx}`);
    }
  });
  it('documents the consent container pattern', () => {
    assert.ok(doc.includes('`' + common.CONSENT_NAMED + '`'), 'CONSENT_NAMED differs from the documented pattern');
    assert.ok(doc.includes('`' + common.CONSENT_TEXT + '`'), 'CONSENT_TEXT differs from the documented pattern');
  });
});
