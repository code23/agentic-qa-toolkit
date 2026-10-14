'use strict';
// viewport_overflow.js against the demo site. Each scenario runs the script once (in parallel); the tests below only read the results.
const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { NO_CHROME, startSite, closedPort, runScript, makeTmp, rmTmp, readJson, strings } = require('./helpers');

const FAST = ['--delay', '500', '--no-scroll'];

describe('viewport_overflow.js on the demo site', { skip: NO_CHROME }, () => {
  let site, tmp, dead;
  const runs = {};   // name -> { code, stdout, stderr, json }

  const scenario = async (name, urls, args) => {
    const out = path.join(tmp, `${name}.json`);
    const list = Array.isArray(urls) ? urls.join(',') : urls;
    const r = await runScript('viewport_overflow.js', [list, '--out', out, ...args], { cwd: tmp });
    runs[name] = { ...r, json: fs.existsSync(out) ? readJson(out) : null, out };
    // A run that wrote nothing is otherwise silent: show what the script printed, so a failure on a slow CI machine says why.
    if (!fs.existsSync(out)) console.error(`[viewport_overflow] scenario "${name}" wrote no output (exit ${r.code})\n--- stdout tail ---\n${r.stdout.slice(-1500)}\n--- stderr tail ---\n${r.stderr.slice(-1500)}`);
  };

  before(async () => {
    site = await startSite(); dead = await closedPort(); tmp = makeTmp();
    const u = p => `${site.origin}/${p}`;
    const listFile = path.join(tmp, 'urls.txt');
    fs.writeFileSync(listFile, `# a comment\n\n${`http://127.0.0.1:${dead}/gone.html`}\n  ${u('missing.html')}  \n${u('brindlemere.html')}\n`);
    await Promise.all([
      scenario('home', u('index.html'), ['--viewports', '375,768,1024,1440', ...FAST]),
      scenario('pricing', u('pricing.html?token=SECRETVALUE123#frag'), ['--viewports', '375,1440', ...FAST]),
      scenario('overlap', u('mobile-service.html'), ['--viewports', '375,1440', ...FAST]),
      scenario('control', u('chain-care-guide.html'), ['--delay', '500']),
      scenario('partial', listFile, ['--viewports', '375', ...FAST]),
      scenario('options', u('index.html'), ['--viewports', '375', '--no-mobile', '--reduced-motion', '--cta', 'zzzz-never', '--shots', path.join(tmp, 'shots'), ...FAST]),
    ]);
  });
  after(async () => { await site.close(); rmTmp(tmp); });

  const at = (run, w) => runs[run].json.results.find(r => r.viewport === w);

  describe('planted fault: overflow at one tablet width only', () => {
    it('exits 0 and writes one result per width', () => {
      assert.equal(runs.home.code, 0, runs.home.stderr);
      assert.deepEqual(runs.home.json.results.map(r => r.viewport), [375, 768, 1024, 1440]);
      assert.deepEqual(runs.home.json.failures, []);
    });
    it('reports sideways overflow at 768 that the user can really scroll, naming the offending element', () => {
      const r = at('home', 768);
      assert.ok(r.overflowPx > 100, `overflowPx ${r.overflowPx}`);
      assert.ok(r.actualScrollX > 0);
      assert.match(r.offenders[0].el, /hours-strip/);
      assert.ok(r.scrollWidth > r.clientWidth);
    });
    it('is clean at phone, small-laptop and desktop widths', () => {
      for (const w of [375, 1024, 1440]) {
        const r = at('home', w);
        assert.equal(r.overflowPx, 0, `${w}px overflowPx`); assert.equal(r.actualScrollX, 0); assert.deepEqual(r.offenders, []);
      }
    });
    it('sees the cookie banner and in-content CTAs, and finds the header clear of the H1', () => {
      for (const r of runs.home.json.results) {
        assert.equal(r.consentBannerVisible, true, `${r.viewport}px`);
        assert.ok(r.inContentCtas >= 2, `${r.viewport}px ctas ${r.inContentCtas}`);
        assert.equal(r.headerClearsH1, true);
        assert.match(r.header, /^header\.site-header/);
        assert.equal(r.root, 'main'); assert.ok(r.renderedWords > 80);
      }
    });
    it('records the emulation, final URL and pre-consent state for each result', () => {
      const r = at('home', 375);
      assert.equal(r.emulated, true); assert.equal(r.emulation.mobile, true); assert.equal(r.emulation.touch, true);
      assert.equal(at('home', 768).emulation.mobile, false); assert.equal(at('home', 768).emulation.touch, true);
      assert.equal(at('home', 1440).emulation.touch, false);
      assert.equal(r.navigation.status, 200); assert.equal(r.navigation.finalUrl, `${site.origin}/index.html`);
      assert.match(r.consentState, /^pre-consent/); assert.equal(r.scrollY, 0);
      for (const x of runs.home.json.results) assert.deepEqual(x.blockedNavigations, [], 'the guard must not block anything on a well-behaved page');
      assert.equal(r.navigation.contentType, 'text/html');
    });
    it('shows no breakpoint-only text on a page without mobile-only copy', () => {
      const p = runs.home.json.parity[0];
      assert.equal(p.onlyNarrowCount, 0); assert.equal(p.onlyWideCount, 0);
    });
  });

  describe('planted fault: fixed header on top of the H1', () => {
    it('reports headerClearsH1 false at every width, and no overflow', () => {
      assert.equal(runs.overlap.code, 0, runs.overlap.stderr);
      for (const r of runs.overlap.json.results) {
        assert.equal(r.headerClearsH1, false, `${r.viewport}px`);
        assert.ok(r.stickyHeaderBottom > r.h1Top, `header bottom ${r.stickyHeaderBottom} vs h1 top ${r.h1Top}`);
        assert.equal(r.overflowPx, 0);
        assert.equal(r.consentBannerVisible, false);
      }
    });
  });

  describe('planted fault: mobile price differs from the desktop price', () => {
    it('reports the changed line on each side, with prices ranked first', () => {
      assert.equal(runs.pricing.code, 0, runs.pricing.stderr);
      const p = runs.pricing.json.parity[0];
      assert.equal(p.narrow, 375); assert.equal(p.wide, 1440);
      assert.ok(p.onlyNarrow.includes('standard service from £39'), JSON.stringify(p.onlyNarrow));
      assert.ok(p.onlyWide.includes('standard service from £45'), JSON.stringify(p.onlyWide));
      assert.ok(p.withNumbersOrPrices >= 2);
    });
    it('reports the desktop-only contact line, redacted', () => {
      const line = runs.pricing.json.parity[0].onlyWide.find(l => l.startsWith('questions about your quote'));
      assert.ok(line, 'desktop-only line missing');
      assert.match(line, /<email>/); assert.match(line, /<redacted>/);
    });
  });

  describe('clean control page', () => {
    it('exits 0 with the default five widths including 320', () => {
      assert.equal(runs.control.code, 0, runs.control.stderr);
      assert.deepEqual(runs.control.json.results.map(r => r.viewport), [320, 375, 768, 1024, 1440]);
      assert.equal(runs.control.json.options.stepScroll, true);
    });
    it('reports no overflow, a clear header, no banner and no breakpoint-only text', () => {
      for (const r of runs.control.json.results) {
        assert.equal(r.overflowPx, 0, `${r.viewport}px`); assert.equal(r.actualScrollX, 0);
        assert.equal(r.headerClearsH1, true); assert.equal(r.consentBannerVisible, false);
        assert.ok(r.inContentCtas >= 2);
      }
      const p = runs.control.json.parity[0];
      assert.equal(p.onlyNarrowCount, 0); assert.equal(p.onlyWideCount, 0); assert.equal(p.withNumbersOrPrices, 0);
    });
    it('does not blame an element that an overflow:hidden wrapper clips', () => {
      assert.ok(at('control', 375).clippedWideElements >= 1);
    });
    it('applies mobile emulation at 320 and 375 only', () => {
      assert.deepEqual(runs.control.json.results.map(r => r.emulation.mobile), [true, true, false, false, false]);
    });
  });

  describe('failures and exit codes', () => {
    it('exits 1 when some URLs fail, lists them, and still writes the URL that worked', () => {
      const r = runs.partial;
      assert.equal(r.code, 1, r.stderr);
      assert.equal(r.json.failures.length, 2);
      assert.match(r.json.failures[0].error, /^navigation: .*ERR_CONNECTION_REFUSED/);
      assert.equal(r.json.failures[0].url, `http://127.0.0.1:${dead}/gone.html`);
      assert.match(r.json.failures[1].error, /^navigation: HTTP 404/);
      assert.equal(r.json.results.length, 1); assert.equal(r.json.results[0].url, `${site.origin}/brindlemere.html`);
      assert.match(r.stdout, /\(2 failed\)/);
    });
    it('reads a URL list file, skipping comments and blank lines and trimming spaces', () => {
      assert.equal(runs.partial.json.failures.length + runs.partial.json.results.length, 3);
    });
  });

  describe('options', () => {
    it('--no-mobile, --reduced-motion, --cta and --shots are honoured', () => {
      const r = runs.options;
      assert.equal(r.code, 0, r.stderr);
      const res = r.json.results[0];
      assert.equal(res.emulation.mobile, false); assert.equal(res.emulation.touch, false); assert.equal(res.emulation.reducedMotion, true);
      assert.equal(r.json.options.noMobile, true); assert.equal(r.json.options.stepScroll, false);
      assert.equal(res.inContentCtas, 0, 'a CTA pattern that matches nothing must find nothing');
      assert.ok(res.shot && fs.statSync(res.shot).size > 1000, 'screenshot missing');
      assert.match(path.basename(res.shot), /^vp-375-127_0_0_1_\d+_index_html\.png$/);
    });
  });

  describe('evidence hygiene', () => {
    it('writes no query string or fragment anywhere in any output', () => {
      for (const [name, run] of Object.entries(runs)) {
        const blob = JSON.stringify(run.json) + run.stdout + run.stderr;
        assert.ok(!/https?:\/\/[^\s"']*[?#]/.test(blob), `${name}: a URL with a query or fragment was written`);
      }
      assert.ok(!JSON.stringify(runs.pricing.json).includes('SECRETVALUE123') && !runs.pricing.stdout.includes('SECRETVALUE123'));
      assert.equal(runs.pricing.json.results[0].url, `${site.origin}/pricing.html`);
    });
    it('redacts emails and token-like strings in text it reports', () => {
      const all = [...strings(runs.pricing.json)].join('\n') + runs.pricing.stdout + runs.pricing.stderr;
      assert.ok(!/workshop\.lead@example\.com/i.test(all), 'email leaked');
      assert.ok(!/QX7R2M9KLP4W8ZC3VB6N5A/i.test(all), 'token leaked');
    });
  });
});
