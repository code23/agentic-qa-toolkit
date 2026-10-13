'use strict';
// In-process tests of the browser helpers in _common.js and of the in-page functions (findControl, measure), using inline fixtures.
const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const http = require('http');
const path = require('path');
const { SCRIPTS, NO_CHROME, startSite, closedPort, enablePuppeteer, stopServer, killBrowser } = require('./helpers');

describe('browser helpers', { skip: NO_CHROME }, () => {
  let common, consent, overflow, browser, site, closed, side;

  before(async () => {
    enablePuppeteer();
    common = require(path.join(SCRIPTS, '_common.js'));
    consent = require(path.join(SCRIPTS, 'consent_capture.js'));
    overflow = require(path.join(SCRIPTS, 'viewport_overflow.js'));
    site = await startSite();
    closed = await closedPort();
    // A second tiny server for redirect, non-HTML and POST cases.
    side = http.createServer((req, res) => {
      if (req.url.startsWith('/redir')) { res.writeHead(302, { location: '/page' }); return res.end(); }
      if (req.url.startsWith('/json')) { res.writeHead(200, { 'content-type': 'application/json' }); return res.end('{}'); }
      if (req.url.startsWith('/long')) { res.writeHead(200, { 'content-type': 'text/html' }); return res.end('<body style="margin:0"><div style="height:3000px">tall</div></body>'); }
      res.writeHead(200, { 'content-type': 'text/html' }); res.end('<meta name="viewport" content="width=device-width"><body>page text</body>');
    });
    await new Promise(r => side.listen(0, '127.0.0.1', r));
    side.base = `http://127.0.0.1:${side.address().port}`;
    browser = await common.freshBrowser();
  });
  after(async () => {
    const dir = browser && browser.__dir;
    await common.closeBrowser(browser);
    if (dir) assert.equal(fs.existsSync(dir), false, 'closeBrowser must remove the throwaway profile');
    await killBrowser(browser);
    await site.close(); await stopServer(side);
  });

  describe('freshBrowser / closeBrowser', () => {
    it('uses a throwaway profile folder and closeBrowser tolerates null', async () => {
      assert.ok(browser.__dir && fs.existsSync(browser.__dir));
      assert.match(path.basename(browser.__dir), /^qa-prof-/);
      await common.closeBrowser(null);
    });
    it('starts with no cookies (clean first visit)', async () => {
      const p = await browser.newPage();
      await p.goto(site.origin + '/chain-care-guide.html');
      assert.equal(await p.evaluate(() => document.cookie), '');
      await p.close();
    });
  });

  describe('setViewport emulation rules', () => {
    const cases = [
      [{ w: 320 }, { mobile: true, touch: true }],
      [{ w: 375 }, { mobile: true, touch: true }],
      [{ w: 767 }, { mobile: true, touch: true }],
      [{ w: 768 }, { mobile: false, touch: true }],
      [{ w: 1024 }, { mobile: false, touch: true }],
      [{ w: 1025 }, { mobile: false, touch: false }],
      [{ w: 1440 }, { mobile: false, touch: false }],
      [{ w: 844, h: 390 }, { mobile: true, touch: true }],
    ];
    for (const [vp, want] of cases) {
      it(`${vp.w}${vp.h ? 'x' + vp.h : ''}: mobile=${want.mobile} touch=${want.touch}`, async () => {
        const p = await browser.newPage();
        const em = await common.setViewport(p, vp);
        assert.equal(em.mobile, want.mobile); assert.equal(em.touch, want.touch); assert.equal(em.width, vp.w);
        await p.goto(side.base + '/page');
        const seen = await p.evaluate(() => ({ w: innerWidth, ua: navigator.userAgent, touch: navigator.maxTouchPoints > 0 }));
        assert.equal(seen.w, vp.w);
        assert.equal(/Android/.test(seen.ua), want.mobile, seen.ua);
        assert.ok(seen.ua.includes(common.UA_TAG), 'user agent must carry the tag');
        assert.ok(!/HeadlessChrome/.test(seen.ua));
        assert.equal(seen.touch, want.touch);
        await p.close();
      });
    }
    it('mobile:false forces a desktop probe at a phone width', async () => {
      const p = await browser.newPage();
      const em = await common.setViewport(p, { w: 375 }, { mobile: false });
      assert.equal(em.mobile, false); assert.equal(em.touch, false);
      await p.close();
    });
    it('reducedMotion is applied and reported', async () => {
      const p = await browser.newPage();
      const em = await common.setViewport(p, { w: 1440 }, { reducedMotion: true });
      assert.equal(em.reducedMotion, true);
      await p.goto(side.base + '/page');
      assert.equal(await p.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true);
      await p.close();
    });
  });

  describe('goto', () => {
    const open = async fn => { const p = await browser.newPage(); try { return await fn(p); } finally { await p.close(); } };
    it('returns status, content type and a final URL without query or fragment', () => open(async p => {
      const nav = await common.goto(p, site.origin + '/index.html?token=abc#frag');
      assert.equal(nav.status, 200); assert.equal(nav.contentType, 'text/html'); assert.equal(nav.finalUrl, site.origin + '/index.html'); assert.equal(nav.redirects, 0); assert.equal(nav.error, undefined);
    }));
    it('reload:true re-requests a page whose URL has a #fragment (a plain goto to the same URL is a same-document navigation)', () => open(async p => {
      const url = site.origin + '/index.html?x=1#top';
      assert.equal((await common.goto(p, url)).status, 200);
      const n0 = site.log.length;
      const again = await common.goto(p, url, { reload: true });
      assert.equal(again.status, 200, JSON.stringify(again)); assert.equal(again.finalUrl, site.origin + '/index.html');
      assert.ok(site.log.slice(n0).some(l => l.path === '/index.html'), 'the reload must reach the server');
    }));
    it('counts redirects', () => open(async p => {
      const nav = await common.goto(p, side.base + '/redir');
      assert.equal(nav.redirects, 1); assert.equal(nav.finalUrl, side.base + '/page');
    }));
    it('treats HTTP 404 as an error', () => open(async p => {
      assert.equal((await common.goto(p, site.origin + '/missing.html')).error, 'HTTP 404');
    }));
    it('treats a non-HTML response as an error', () => open(async p => {
      assert.match((await common.goto(p, side.base + '/json')).error, /^not HTML \(application\/json\)/);
    }));
    it('reports a refused connection as an error, not an exception', () => open(async p => {
      const nav = await common.goto(p, `http://127.0.0.1:${closed}/`);
      assert.match(nav.error, /ERR_CONNECTION_REFUSED/);
    }));
  });

  describe('stepScroll, settle, watchRequests', () => {
    it('stepScroll returns to the top of a tall page', async () => {
      const p = await browser.newPage(); await common.setViewport(p, { w: 1440 });
      await p.goto(side.base + '/long');
      await common.stepScroll(p, 50, 3);
      assert.equal(await p.evaluate(() => scrollY), 0);
      await p.close();
    });
    it('settle returns once the DOM is quiet', async () => {
      const p = await browser.newPage(); await p.goto(side.base + '/page');
      const t0 = Date.now(); await common.settle(p, 3000, 300);
      assert.ok(Date.now() - t0 < 3500, `took ${Date.now() - t0} ms`);
      await p.close();
    });
    it('watchRequests lists URLs, counts non-GET requests by host and flags nothing as mixed on http', async () => {
      const p = await browser.newPage(); const w = common.watchRequests(p);
      await p.goto(side.base + '/page');
      await p.evaluate(base => fetch(base + '/json', { method: 'POST', body: 'x' }), side.base);
      assert.ok(w.urls.some(u => u.endsWith('/page')));
      assert.equal(w.nonGet[`POST ${side.base.replace('http://', '')}`], 1);
      assert.equal(w.mixed.size, 0);
      await p.close();
    });
  });

  describe('consent findControl (in-page)', () => {
    const find = async (html, kind = 'accept', labels = {}) => {
      const p = await browser.newPage();
      try {
        await p.setContent(`<!doctype html><body>${html}</body>`);
        const label = labels.label || (kind === 'accept' ? consent.ACCEPT : consent.REJECT);
        const h = await p.evaluateHandle(consent.findControl, label, kind === 'accept' ? consent.AGREE : null, consent.RX);
        const el = (await h.getProperty('0')).asElement();
        const info = await (await h.getProperty('1')).jsonValue();
        return { found: !!el, info };
      } finally { await p.close(); }
    };
    const banner = (inner, attrs = 'id="cookie-banner"') => `<p>Long page text.</p><div ${attrs}><p>We use cookies on this site.</p>${inner}</div>`;

    it('finds Accept inside a cookie-named container', async () => {
      const r = await find(banner('<button>Accept all</button>'));
      assert.equal(r.found, true); assert.deepEqual(r.info, { label: 'Accept all', containerKind: 'named' });
    });
    it('matches labels case-insensitively, ignoring a trailing full stop or exclamation mark', async () => {
      assert.equal((await find(banner('<button>ACCEPT ALL.</button>'))).found, true);
      assert.equal((await find(banner('<button>Got it!</button>'))).found, true);
    });
    it('does not match near-miss labels', async () => {
      for (const l of ['Allow', 'Accept terms', 'Accept and subscribe', 'Cookie settings', 'Manage preferences']) {
        assert.equal((await find(banner(`<button>${l}</button>`))).found, false, l);
      }
    });
    it('finds Reject labels', async () => {
      assert.equal((await find(banner('<button>Decline</button>'), 'reject')).found, true);
      assert.equal((await find(banner('<button>Necessary only</button>'), 'reject')).found, true);
    });
    it('accepts bare "I agree" only inside a named container', async () => {
      assert.equal((await find(banner('<button>I agree</button>'))).found, true);
      const dlg = '<div role="dialog"><p>We use cookies here.</p><button>I agree</button></div>';
      assert.equal((await find(dlg)).found, false);
      assert.equal((await find(dlg.replace('I agree', 'Accept all'))).info.containerKind, 'dialog-with-cookie-text');
    });
    it('accepts a privacy-named container only when its text mentions cookies, consent or tracking', async () => {
      const mk = t => `<div id="privacy-notice"><p>${t}</p><button>Accept</button></div>`;
      assert.equal((await find(mk('We use cookies to improve things.'))).info.containerKind, 'privacy-named-with-cookie-text');
      assert.equal((await find(mk('Our privacy policy has changed.'))).found, false);
    });
    it('ignores a dialog whose text is not about cookies (newsletter, age gate)', async () => {
      assert.equal((await find('<div role="dialog"><p>Join our newsletter</p><button>Accept</button></div>')).found, false);
    });
    it('never clicks inside a form or a button owned by a form', async () => {
      assert.equal((await find(banner('<form><button type="button">Accept all</button></form>'))).found, false);
      assert.equal((await find('<form id="f"></form>' + banner('<button form="f" type="button">Accept all</button>'))).found, false);
    });
    it('skips links that navigate away but allows # and javascript: anchors', async () => {
      assert.equal((await find(banner('<a href="/privacy">Accept all</a>'))).found, false);
      assert.equal((await find(banner('<a href="#">Accept all</a>'))).found, true);
      assert.equal((await find(banner('<a href="javascript:void(0)">Accept all</a>'))).found, true);
    });
    it('skips hidden and disabled controls', async () => {
      assert.equal((await find(banner('<button style="display:none">Accept all</button>'))).found, false);
      assert.equal((await find(banner('<button disabled>Accept all</button>'))).found, false);
    });
    it('reports blocked, and clicks nothing, when the container holds a text input or a CAPTCHA', async () => {
      const a = await find(banner('<input type="text" name="q"><button>Accept all</button>'));
      assert.equal(a.found, false); assert.match(a.info.blocked, /text inputs or a CAPTCHA/);
      const b = await find(banner('<iframe title="Captcha challenge"></iframe><button>Accept all</button>'));
      assert.equal(b.found, false); assert.match(b.info.blocked, /CAPTCHA/);
      assert.equal((await find(banner('<input type="checkbox"><button>Accept all</button>'))).found, true, 'category checkboxes are fine');
    });
    it('does not accept a control that sits directly in body or main, or in a page-sized wrapper', async () => {
      assert.equal((await find('<p>We use cookies.</p><button>Accept all</button>')).found, false);
      assert.equal((await find('<main class="cookie-main"><p>cookies</p><button>Accept all</button></main>')).found, false);
      assert.equal((await find('<div class="cookie-shell" style="height:3000px"><p>cookies</p><button>Accept all</button></div>')).found, false);
    });
    it('honours a custom --accept pattern', async () => {
      assert.equal((await find(banner('<button>Sounds good</button>'))).found, false);
      assert.equal((await find(banner('<button>Sounds good</button>'), 'accept', { label: '^sounds good$' })).found, true);
    });
  });

  describe('viewport_overflow measure (in-page)', () => {
    const measure = async (html, w = 800) => {
      const p = await browser.newPage();
      try {
        await p.setViewport({ width: w, height: 600 });
        await p.setContent(`<!doctype html><html><body style="margin:0">${html}</body></html>`);
        return await p.evaluate(overflow.measure, overflow.CTA, common.CONSENT_NAMED);
      } finally { await p.close(); }
    };
    it('flags a fixed header that sits on top of the H1', async () => {
      const r = await measure('<header style="position:fixed;top:0;left:0;right:0;height:80px">Nav</header><main><h1 style="margin:10px 0">Title</h1></main>');
      assert.equal(r.headerClearsH1, false); assert.equal(r.stickyHeaderBottom, 80);
    });
    it('reports a clear header as clearing the H1', async () => {
      const r = await measure('<header style="position:sticky;top:0;height:80px">Nav</header><main><h1>Title</h1></main>');
      assert.equal(r.headerClearsH1, true);
    });
    it('does not mistake a fixed consent banner at the top for the header, and reports null clearance', async () => {
      const r = await measure('<div class="cookie-banner" style="position:fixed;top:0;left:0;right:0;height:60px">cookies</div><main><h1 style="margin:0">Title</h1></main>');
      assert.equal(r.header, null); assert.equal(r.headerClearsH1, null);
    });
    it('measures overflow and lists the offending element', async () => {
      const r = await measure('<main><div class="wide" style="width:1000px;height:20px">x</div></main>', 600);
      assert.equal(r.overflowPx, 400); assert.equal(r.actualScrollX, 400); assert.match(r.offenders[0].el, /^div\.wide/);
    });
    it('does not count elements clipped by a fitting overflow:hidden ancestor', async () => {
      const r = await measure('<main><div style="overflow:hidden;width:300px"><div style="width:1000px;height:20px">x</div></div></main>', 600);
      assert.equal(r.overflowPx, 0); assert.deepEqual(r.offenders, []); assert.ok(r.clippedWideElements >= 1);
    });
    it('counts only in-content CTAs (not header, footer, nav or consent) and the gap to the footer', async () => {
      const r = await measure('<header><a href="/contact">Contact</a></header><main><div style="height:1200px">x</div><a href="/contact">Contact us</a><div style="height:600px">y</div></main><footer><a href="/c">Get in touch</a></footer><div class="cookie-bar"><a href="/c">Book now</a></div>');
      assert.equal(r.inContentCtas, 1); assert.ok(r.firstCtaScreens > 2 && r.firstCtaScreens < 2.2, `firstCtaScreens ${r.firstCtaScreens}`);
    });
    it('counts rendered words in <main> only', async () => {
      const r = await measure('<header>one two three</header><main>alpha beta gamma delta</main><footer>x y z</footer>');
      assert.equal(r.root, 'main'); assert.equal(r.renderedWords, 4);
    });
  });
});
