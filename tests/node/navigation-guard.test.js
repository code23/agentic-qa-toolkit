'use strict';
// The navigation guard (non-GET and off-scope navigations are blocked, everything else is untouched) and the goto timeout path.
const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const http = require('http');
const path = require('path');
const { SCRIPTS, NO_CHROME, runScript, makeTmp, rmTmp, readJson, enablePuppeteer, stopServer, killBrowser } = require('./helpers');

const listen = server => new Promise(r => server.listen(0, '127.0.0.1', () => r(server.address().port)));
const BANNER = (buttons) => `<div id="cookie-banner" role="region" aria-label="Cookie notice" style="position:fixed;bottom:0;left:0;right:0;background:#222;color:#fff;padding:12px"><p>We use cookies.</p>${buttons}</div>`;

describe('navigation guard', { skip: NO_CHROME }, () => {
  let main, other, mainPort, otherPort, mainLog, otherLog, tmp;
  const runs = {};
  const scenario = async (name, script, page, args = []) => {
    const out = path.join(tmp, `${name}.json`);
    const r = await runScript(script, [`http://127.0.0.1:${mainPort}${page}`, '--out', out, '--delay', '500', ...args], { cwd: tmp });
    runs[name] = { ...r, json: fs.existsSync(out) ? readJson(out) : null };
  };

  before(async () => {
    tmp = makeTmp(); mainLog = []; otherLog = [];
    other = http.createServer((req, res) => { otherLog.push(`${req.method} ${req.url}`); res.writeHead(200, { 'content-type': 'text/html' }); res.end('<title>elsewhere</title><body>elsewhere</body>'); });
    otherPort = await listen(other);
    const landing = `http://127.0.0.1:${otherPort}/landed.html`;
    main = http.createServer((req, res) => {
      const u = new URL(req.url, 'http://x');
      mainLog.push(`${req.method} ${u.pathname}`);
      const html = body => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(`<!doctype html><meta charset="utf-8"><link rel="icon" href="data:,"><title>Fixture</title><body><main><h1>Fixture page</h1><p>Some words to measure here.</p></main>${body}</body>`); };
      switch (u.pathname) {
        case '/meta.html': return html(`<meta http-equiv="refresh" content="0;url=${landing}">`);
        case '/redirect.html': res.writeHead(302, { location: landing }); return res.end();
        case '/post-banner.html':   // the banner's Accept and Reject handlers submit a POST form that lives outside the banner
          return html(`<form id="f" method="post" action="/submit"><input type="hidden" name="a" value="1"></form>${BANNER('<button onclick="document.getElementById(\'f\').submit()">Accept all</button> <button onclick="document.getElementById(\'f\').submit()">Reject all</button>')}`);
        case '/click-away.html':    // Accept sends the main document to another host
          return html(BANNER(`<button onclick="location.href='${landing}'">Accept all</button>`));
        case '/beacon.html':        // sub-resource style POSTs on every load: they must go through untouched
          return html(`${BANNER('<button>Accept all</button> <button>Reject all</button>')}<script>
            navigator.sendBeacon('/collect', 'x'); fetch('/collect-fetch', { method: 'POST', body: 'y' }).then(function (r) { return r.text(); });
            var x = new XMLHttpRequest(); x.open('POST', '/collect-xhr'); x.send('z');</script>`);
        case '/iframe-post.html':   // a POST navigation inside a sub-frame
          return html('<iframe srcdoc="<form id=g method=post action=/frame-submit></form><script>g.submit()</script>"></iframe>');
        case '/post-main.html':     // the page submits a POST form to itself shortly after load
          return html('<form id="f" method="post" action="/submit"></form><script>setTimeout(function () { f.submit(); }, 500);</script>');
        case '/keyhost-meta.html': return html('<meta http-equiv="refresh" content="0;url=http://sk-abcdefghijklmnopqrstuvwx.evil.test/landed">');
        case '/keyhost-post.html': return html('<form id="f" method="post" action="http://abcd1234efgh5678ijkl9012.evil.test/x"></form><script>addEventListener("load", function () { setTimeout(function () { f.submit(); }, 1500); });</script>');
        case '/collect': case '/collect-fetch': case '/collect-xhr': case '/submit': case '/frame-submit': res.writeHead(204); return res.end();
        default: res.writeHead(404); return res.end('no');
      }
    });
    mainPort = await listen(main);
    const w = (name, script, page, args) => scenario(name, script, page, args);
    await Promise.all([
      w('vp-meta', 'viewport_overflow.js', '/meta.html', ['--viewports', '375', '--no-scroll']),
      w('vp-redirect', 'viewport_overflow.js', '/redirect.html', ['--viewports', '375', '--no-scroll']),
      w('dev-meta', 'dev_artefacts.js', '/meta.html'),
      w('dev-redirect', 'dev_artefacts.js', '/redirect.html'),
      w('dev-iframe', 'dev_artefacts.js', '/iframe-post.html'),
      w('dev-beacon', 'dev_artefacts.js', '/beacon.html'),
      w('vp-post-main', 'viewport_overflow.js', '/post-main.html', ['--viewports', '1366', '--no-scroll']),
      w('dev-keyhost-meta', 'dev_artefacts.js', '/keyhost-meta.html'),
      w('dev-keyhost-post', 'dev_artefacts.js', '/keyhost-post.html'),
      w('con-redirect', 'consent_capture.js', '/redirect.html', ['--width', '1366', '--no-reject']),
      w('con-post', 'consent_capture.js', '/post-banner.html', ['--width', '1366']),
      w('con-away', 'consent_capture.js', '/click-away.html', ['--width', '1366', '--no-reject']),
      w('con-beacon', 'consent_capture.js', '/beacon.html', ['--width', '1366']),
    ]);
  });
  after(async () => { await Promise.all([stopServer(main), stopServer(other)]); if (tmp) rmTmp(tmp); });

  const hostA = () => `127.0.0.1:${mainPort}`;

  describe('main-frame navigation outside the input hosts', () => {
    for (const [name, what] of [['vp-meta', 'a meta refresh'], ['vp-redirect', 'a 302']]) {
      it(`viewport_overflow.js fails the URL, with a clear reason, for ${what} to another host`, () => {
        const r = runs[name];
        assert.equal(r.code, 1, r.stderr);
        assert.equal(r.json.results.length, 0);
        assert.equal(r.json.failures.length, 1);
        assert.match(r.json.failures[0].error, /main-frame navigation to 127\.0\.0\.1:\d+ is outside the input URLs; blocked$/);
        assert.ok(r.json.failures[0].error.includes(`127.0.0.1:${otherPort}`));
      });
    }
    for (const [name, what] of [['dev-meta', 'a meta refresh'], ['dev-redirect', 'a 302']]) {
      it(`dev_artefacts.js fails the URL for ${what} to another host`, () => {
        const r = runs[name];
        assert.equal(r.code, 1, r.stderr);
        assert.match(r.json.failures[0].error, new RegExp(`outside the input URLs; blocked`));
        assert.ok(r.json.failures[0].error.includes(`127.0.0.1:${otherPort}`));
      });
    }
    it('consent_capture.js fails the URL for a 302 to another host', () => {
      const r = runs['con-redirect'];
      assert.equal(r.code, 1, r.stderr);
      assert.match(r.json.failures[0].error, /outside the input URLs; blocked/);
    });
    it('the other server never receives a request from any of these runs (blocked, not merely ignored)', () => {
      assert.deepEqual(otherLog, []);
    });
    it('a click handler that sends the page to another host fails that phase and the host is not contacted', () => {
      const r = runs['con-away'];
      assert.equal(r.code, 1, r.stderr);
      assert.equal(r.json.results[0].acceptClicked, 'Accept all');
      assert.match(r.json.results[0].acceptError, /outside the input URLs; blocked/);
      assert.deepEqual(r.json.results[0].blockedNavigations, [{ kind: 'off-scope navigation', host: `127.0.0.1:${otherPort}` }]);
    });
  });

  describe('non-GET navigations', () => {
    it('a banner button that submits a POST form is blocked in both phases, recorded, and the server sees no POST', () => {
      const r = runs['con-post'];
      assert.equal(r.code, 0, r.stderr);
      const res = r.json.results[0];
      assert.equal(res.acceptClicked, 'Accept all'); assert.equal(res.reject.clicked, 'Reject all');
      assert.deepEqual(res.blockedNavigations, [{ kind: 'non-GET navigation', host: hostA() }]);
      assert.deepEqual(res.reject.blockedNavigations, [{ kind: 'non-GET navigation', host: hostA() }]);
      assert.ok(!mainLog.includes('POST /submit'), 'the form POST reached the server');
      assert.equal(res.acceptError, null);
    });
    it('a POST navigation inside an iframe is blocked, recorded, and not reported as a failed request', () => {
      const r = runs['dev-iframe'];
      assert.equal(r.code, 0, r.stderr);
      assert.deepEqual(r.json.results[0].blockedNavigations, [{ kind: 'non-GET navigation', host: hostA() }]);
      assert.deepEqual(r.json.results[0].failedRequests, []);
      assert.ok(!mainLog.includes('POST /frame-submit'));
    });
    it('records only the kind and the host of a blocked request, never a path or query', () => {
      for (const r of [runs['con-post'], runs['dev-iframe']]) {
        const blob = JSON.stringify(r.json);
        assert.ok(!blob.includes('/submit') && !blob.includes('/frame-submit'));
      }
    });
  });

  describe('blocked hosts are redacted before they are written', () => {
    it('a refused main-frame destination with a key-shaped host label is masked in the failure message', () => {
      const r = runs['dev-keyhost-meta'];
      assert.equal(r.code, 1, r.stderr);
      assert.match(r.json.failures[0].error, /main-frame navigation to sk-a…<redacted>\.evil\.test is outside the input URLs; blocked/);
      assert.ok(!/sk-abcdefghijklmnopqrstuvwx/.test(JSON.stringify(r.json) + r.stdout + r.stderr), 'key-shaped host label leaked');
    });
    it('a blocked non-GET navigation to a token-shaped host is stored masked', () => {
      const r = runs['dev-keyhost-post'];
      assert.equal(r.code, 0, r.stderr);
      assert.deepEqual(r.json.results[0].blockedNavigations, [{ kind: 'non-GET navigation', host: 'abcd…<redacted>.evil.test' }]);
      assert.ok(!/abcd1234efgh5678ijkl9012/.test(JSON.stringify(r.json) + r.stdout + r.stderr), 'token-shaped host label leaked');
    });
    it('the unresolvable hosts were never contacted (the requests were blocked before any lookup)', () => {
      assert.ok(!mainLog.some(l => /evil\.test/.test(l)));
    });
  });

  describe('a blocked main-frame POST leaves the page in place', () => {
    it('viewport_overflow.js still measures the real page, not a browser error page', () => {
      const r = runs['vp-post-main'];
      assert.equal(r.code, 0, r.stderr);
      const x = r.json.results[0];
      assert.equal(x.root, 'main'); assert.ok(x.renderedWords >= 6, `renderedWords ${x.renderedWords}`); assert.notEqual(x.h1Top, null);
      assert.equal(x.navigation.finalUrl, `http://127.0.0.1:${mainPort}/post-main.html`);
      assert.deepEqual(x.blockedNavigations, [{ kind: 'non-GET navigation', host: hostA() }]);
      assert.ok(!mainLog.includes('POST /submit'));
    });
  });

  describe('sub-resource requests are untouched', () => {
    it('sendBeacon, fetch and XHR POSTs reach the server and are still recorded', () => {
      for (const p of ['/collect', '/collect-fetch', '/collect-xhr']) assert.ok(mainLog.includes(`POST ${p}`), `${p} did not reach the server`);
      const dev = runs['dev-beacon'].json.results[0];
      assert.ok(dev.nonGetRequests[`POST ${hostA()}`] >= 3, JSON.stringify(dev.nonGetRequests));
      assert.deepEqual(dev.blockedNavigations, []); assert.deepEqual(dev.failedRequests, []);
      const con = runs['con-beacon'];
      assert.equal(con.code, 0, con.stderr);
      const res = con.json.results[0];
      assert.ok(res.nonGetRequests[`POST ${hostA()}`] >= 3, JSON.stringify(res.nonGetRequests));
      assert.deepEqual(res.blockedNavigations, []); assert.deepEqual(res.reject.blockedNavigations, []);
      assert.equal(res.acceptClicked, 'Accept all'); assert.equal(res.reject.clicked, 'Reject all');
    });
  });
});

describe('goto: timeout path validates the main document', { skip: NO_CHROME }, () => {
  let common, browser, server, port;
  const open = async fn => { const p = await browser.newPage(); try { return await fn(p); } finally { await p.close(); } };
  before(async () => {
    enablePuppeteer(); common = require(path.join(SCRIPTS, '_common.js'));
    // Pages whose sub-resources never finish, so the network never goes idle.
    const hangers = Array.from({ length: 4 }, (_, i) => `<img src="/hang/${i}">`).join('');
    server = http.createServer((req, res) => {
      const u = new URL(req.url, 'http://x');
      if (u.pathname.startsWith('/hang/')) { res.writeHead(200, { 'content-type': 'image/png' }); res.write('x'); return; }   // never ends
      if (u.pathname === '/ct') { res.writeHead(200, { 'content-type': u.searchParams.get('type') }); return res.end('<!doctype html><title>t</title><body>some text here</body>'); }
      const status = u.pathname === '/busy404' ? 404 : 200, type = u.pathname === '/busytext' ? 'text/plain' : 'text/html';
      res.writeHead(status, { 'content-type': type });
      res.end(`<!doctype html><title>busy</title><body>Plenty of text on this busy page.${hangers}</body>`);
    });
    port = await listen(server);
    browser = await common.freshBrowser();
  });
  after(async () => { await killBrowser(browser); await stopServer(server); });
  const url = p => `http://127.0.0.1:${port}${p}`;

  it('a busy 404 page is a failure, not a partial measurement', () => open(async p => {
    const nav = await common.goto(p, url('/busy404'), { timeoutMs: 2500 });
    assert.equal(nav.status, 404); assert.match(nav.error, /^HTTP 404 \(network never idle within 3 s\)/);
  }));
  it('a busy non-HTML page is a failure', () => open(async p => {
    const nav = await common.goto(p, url('/busytext'), { timeoutMs: 2500 });
    assert.equal(nav.contentType, 'text/plain'); assert.match(nav.error, /^not HTML \(text\/plain\)/);
  }));
  it('a busy good page is still measured, with status, type and a warning', () => open(async p => {
    const nav = await common.goto(p, url('/busy'), { timeoutMs: 2500 });
    assert.equal(nav.error, undefined); assert.equal(nav.status, 200); assert.equal(nav.contentType, 'text/html'); assert.match(nav.warning, /network not idle after 3 s/);
  }));
  it('a blocked main-frame POST leaves the document in place (no browser error page replaces it)', async () => {
    const posts = [];
    const srv = http.createServer((req, res) => {
      if (req.method === 'POST') { posts.push(req.url); res.writeHead(200); return res.end('posted'); }
      res.writeHead(200, { 'content-type': 'text/html' });
      res.end('<!doctype html><body>hello page<form id="f" method="post" action="/x"></form><script>setTimeout(function () { f.submit(); }, 300);</script></body>');
    });
    const sp = await listen(srv);
    try {
      const p = await common.openPage(browser, new Set([`127.0.0.1:${sp}`]));
      try {
        assert.equal((await common.goto(p, `http://127.0.0.1:${sp}/`)).status, 200);
        await new Promise(r => setTimeout(r, 1200));
        assert.equal(p.url(), `http://127.0.0.1:${sp}/`);
        assert.match(await p.evaluate(() => document.body.innerText), /hello page/);
        assert.deepEqual(p.__guard.blocked, [{ kind: 'non-GET navigation', host: `127.0.0.1:${sp}` }]);
        assert.deepEqual(posts, []);
      } finally { await p.close(); }
    } finally { await stopServer(srv); }
  });
  it('accepts a permitted redirect (to another allowed host) followed by a busy page, and records its final safe URL', async () => {
    const hop = http.createServer((req, res) => { res.writeHead(302, { location: `http://127.0.0.1:${port}/busy?token=SECRETVALUE123#frag` }); res.end(); });
    const hopPort = await listen(hop);
    try {
      const p = await common.openPage(browser, new Set([`127.0.0.1:${hopPort}`, `127.0.0.1:${port}`]));
      try {
        const nav = await common.goto(p, `http://127.0.0.1:${hopPort}/start`, { timeoutMs: 2500 });
        assert.equal(nav.error, undefined, JSON.stringify(nav));
        assert.equal(nav.status, 200); assert.equal(nav.contentType, 'text/html'); assert.equal(nav.redirects, 1);
        assert.equal(nav.finalUrl, `http://127.0.0.1:${port}/busy`); assert.match(nav.warning, /network not idle/);
      } finally { await p.close(); }
    } finally { await stopServer(hop); }
  });
  it('still refuses a redirect to a host outside the allowed set, and the destination is never contacted', async () => {
    const hits = [];
    const dest = http.createServer((req, res) => { hits.push(req.url); res.writeHead(200, { 'content-type': 'text/html' }); res.end('<body>x</body>'); });
    const destPort = await listen(dest);
    const hop = http.createServer((req, res) => { res.writeHead(302, { location: `http://127.0.0.1:${destPort}/busy` }); res.end(); });
    const hopPort = await listen(hop);
    try {
      const p = await common.openPage(browser, new Set([`127.0.0.1:${hopPort}`]));
      try {
        const nav = await common.goto(p, `http://127.0.0.1:${hopPort}/start`, { timeoutMs: 2500 });
        assert.match(nav.error, /outside the input URLs/); assert.deepEqual(hits, []);
      } finally { await p.close(); }
    } finally { await Promise.all([stopServer(hop), stopServer(dest)]); }
  });
  it('writes only a normalised media type, and checks the type rather than searching the header for "html"', () => open(async p => {
    const ok = await common.goto(p, url('/ct?type=' + encodeURIComponent('Text/HTML; charset=utf-8; note=jo@example.org')), {});
    assert.equal(ok.contentType, 'text/html'); assert.equal(ok.error, undefined);
    const fake = await common.goto(p, url('/ct?type=' + encodeURIComponent('text/htmlish')), {});
    assert.match(fake.error, /^not HTML \(text\/htmlish\)/);
    const xml = await common.goto(p, url('/ct?type=' + encodeURIComponent('application/xhtml+xml')), {});
    assert.equal(xml.error, undefined);
  }));
});
