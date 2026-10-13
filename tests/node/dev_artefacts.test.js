'use strict';
// dev_artefacts.js against the demo site and a few purpose-built folders. Scenarios run once, in parallel; the tests read the results.
const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { NO_CHROME, startSite, closedPort, runScript, makeTmp, rmTmp, readJson, strings } = require('./helpers');

// The script's own GETs carry this UA (a fixed Linux Chrome/130 string plus the tag); the browser's UA differs.
const isOwnGet = l => /Linux x86_64\) Chrome\/130 Safari/.test(l.ua);

describe('dev_artefacts.js on the demo site', { skip: NO_CHROME }, () => {
  let site, tmp, dead, edge, edgeRoot, cacheSite;
  const runs = {};

  const scenario = async (name, urls, args = [], cwd) => {
    const out = path.join(tmp, `${name}.json`);
    const r = await runScript('dev_artefacts.js', [Array.isArray(urls) ? urls.join(',') : urls, '--out', out, '--delay', '500', ...args], { cwd: cwd || tmp });
    runs[name] = { ...r, json: fs.existsSync(out) ? readJson(out) : null };
  };

  before(async () => {
    site = await startSite(); dead = await closedPort(); tmp = makeTmp();
    const u = p => `${site.origin}/${p}`;

    // A purpose-built folder for edge cases: a SourceMap header, an oversized asset and an off-scope map comment.
    edgeRoot = path.join(tmp, 'edge'); fs.mkdirSync(edgeRoot);
    fs.writeFileSync(path.join(edgeRoot, 'index.html'), '<!doctype html><meta charset="utf-8"><link rel="icon" href="data:,"><title>Edge</title><body><main><h1>Edge cases</h1></main><script src="app.js"></script><script src="big.js"></script><script src="offscope.js"></script></body>');
    fs.writeFileSync(path.join(edgeRoot, 'app.js'), 'console.log("app");\n');
    fs.writeFileSync(path.join(edgeRoot, 'app.js.map'), '{"version":3,"sources":[],"mappings":""}');
    fs.writeFileSync(path.join(edgeRoot, 'big.js'), '// ' + 'x'.repeat(30000) + '\n');
    fs.writeFileSync(path.join(edgeRoot, 'offscope.js'), 'var a = 1;\n//# sourceMappingURL=http://example.invalid/never-fetched.js.map\n');
    edge = await startSite(edgeRoot, { headers: p => (p === '/app.js' ? { SourceMap: 'app.js.map' } : {}) });

    const listFile = path.join(tmp, 'urls.txt');
    fs.writeFileSync(listFile, `${`http://127.0.0.1:${dead}/gone.html`}\n${u('missing.html')}\n${u('privacy.html')}\n`);

    cacheSite = await startSite();
    // Two sequential runs sharing one cache folder, against their own server so its request log is unambiguous.
    const cached = async () => {
      const url = `${cacheSite.origin}/pricing.html`;
      await scenario('cacheA', url, ['--cache', path.join(tmp, 'cache')]);
      runs.cacheA.ownGets = cacheSite.log.filter(isOwnGet).length;
      await scenario('cacheB', url, ['--cache', path.join(tmp, 'cache')]);
      runs.cacheB.ownGets = cacheSite.log.filter(isOwnGet).length;
    };

    await Promise.all([
      cached(),
      scenario('pricing', u('pricing.html?token=SECRETVALUE123#frag')),
      scenario('contact', u('contact.html')),
      scenario('overlap', u('mobile-service.html')),
      scenario('home', u('index.html'), ['--width', '375']),
      scenario('control', u('chain-care-guide.html')),
      scenario('partial', listFile),
      scenario('edge', edge.origin + '/index.html', ['--max-bytes', '10000']),
    ]);
  });
  after(async () => { await site.close(); await edge.close(); await cacheSite.close(); rmTmp(tmp); });

  const first = name => runs[name].json.results[0];
  const hit = (name, pred) => first(name).domHits.find(pred);

  describe('clean control page', () => {
    it('exits 0 and reports nothing', () => {
      const r = runs.control;
      assert.equal(r.code, 0, r.stderr);
      const x = first('control');
      for (const k of ['domHits', 'consoleMsgs', 'pageErrors', 'failedRequests', 'sourceMaps', 'ownFetchErrors', 'mixedContent']) assert.deepEqual(x[k], [], k);
      assert.deepEqual(x.nonGetRequests, {}); assert.deepEqual(x.blockedNavigations, []); assert.equal(x.navigation.contentType, 'text/html'); assert.equal(x.testIdAttrs, 0); assert.equal(x.servedHtmlError, null);
      assert.equal(x.navigation.status, 200);
    });
    it('the home page is also free of artefacts (at a 375 width)', () => {
      assert.equal(runs.home.code, 0, runs.home.stderr);
      const x = first('home');
      for (const k of ['domHits', 'consoleMsgs', 'pageErrors', 'failedRequests', 'sourceMaps']) assert.deepEqual(x[k], [], k);
    });
  });

  describe('planted fault: leftover debug and test markup hidden in the DOM', () => {
    it('finds a hidden TODO note, a hidden test label and a debug class, all present in the served HTML', () => {
      assert.equal(runs.pricing.code, 0, runs.pricing.stderr);
      const todo = hit('pricing', h => h.match.toLowerCase() === 'todo');
      assert.ok(todo, JSON.stringify(first('pricing').domHits));
      assert.equal(todo.where, 'text'); assert.equal(todo.visible, false); assert.equal(todo.inServedHtml, true); assert.equal(todo.id, 'price-notes');
      const label = hit('pricing', h => /test label/i.test(h.match));
      assert.ok(label && label.visible === false && label.inServedHtml === true);
      const dbg = hit('pricing', h => h.match.toLowerCase() === 'debug');
      assert.ok(dbg); assert.equal(dbg.where, 'id/class'); assert.equal(dbg.visible, false); assert.equal(dbg.inServedHtml, true); assert.match(dbg.cls, /debug-grid/);
      assert.equal(first('pricing').domHits.length, 3);
    });
    it('finds a debug element that only script puts into the DOM, and says it is not in the served HTML', () => {
      const d = hit('contact', h => /debug-overlay/.test(h.cls));
      assert.ok(d, JSON.stringify(first('contact').domHits));
      assert.equal(d.visible, false); assert.equal(d.inServedHtml, false); assert.equal(d.where, 'id/class');
    });
  });

  describe('planted fault: lorem ipsum', () => {
    it('is reported as visible text that is also in the served HTML', () => {
      const l = hit('contact', h => /lorem ipsum/i.test(h.match));
      assert.ok(l); assert.equal(l.visible, true); assert.equal(l.inServedHtml, true); assert.equal(l.where, 'text');
    });
  });

  describe('planted faults: console error and failed same-origin request', () => {
    it('reports the console error with the email redacted', () => {
      const msgs = first('contact').consoleMsgs;
      assert.ok(msgs.includes('error: Map widget failed to initialise for <email>'), JSON.stringify(msgs));
    });
    it('reports the 404 for the availability request without its query string', () => {
      assert.deepEqual(first('contact').failedRequests, [`404 ${site.origin}/api/availability.json`]);
    });
    it('reports an uncaught script error as a page error', () => {
      assert.ok(first('overlap').pageErrors.some(e => /ReferenceError: bookingWidget is not defined/.test(e)), JSON.stringify(first('overlap').pageErrors));
    });
  });

  describe('planted fault: exposed source map', () => {
    it('reports the map as publicly readable (status 200, status-only probe)', () => {
      const maps = first('pricing').sourceMaps;
      assert.equal(maps.length, 1, JSON.stringify(maps));
      assert.deepEqual({ ...maps[0], redirects: undefined }, { asset: `${site.origin}/assets/pricing-widget.js`, map: `${site.origin}/assets/pricing-widget.js.map`, via: 'comment', status: 200, probe: 'status only', redirects: undefined });
    });
    it('does not report maps for pages that ship none', () => {
      assert.deepEqual(first('contact').sourceMaps, []);
    });
  });

  describe('edge cases on a purpose-built folder', () => {
    it('uses the SourceMap response header without fetching the asset itself', () => {
      const m = first('edge').sourceMaps.find(x => x.asset.endsWith('/app.js'));
      assert.ok(m, JSON.stringify(first('edge').sourceMaps));
      assert.equal(m.via, 'header'); assert.equal(m.status, 200);
      assert.equal(edge.log.filter(l => isOwnGet(l) && l.path === '/app.js').length, 0, 'the asset must not be fetched when the header names the map');
      assert.equal(edge.log.filter(l => isOwnGet(l) && l.path === '/app.js.map').length, 1);
    });
    it('does not fetch a source map on a host outside the input URLs', () => {
      const m = first('edge').sourceMaps.find(x => x.asset.endsWith('/offscope.js'));
      assert.equal(m.status, 'skipped (off-scope)'); assert.equal(m.map, 'http://example.invalid/never-fetched.js.map');
    });
    it('a body longer than --max-bytes is reported as truncated and makes the run a partial failure', () => {
      assert.equal(runs.edge.code, 1, runs.edge.stderr);
      const errs = first('edge').ownFetchErrors;
      assert.equal(errs.length, 1, JSON.stringify(errs));
      assert.equal(errs[0].what, 'asset'); assert.match(errs[0].error, /truncated at 10000 bytes/);
      assert.equal(runs.edge.json.failures.length, 1);
      assert.equal(first('edge').sourceMaps.find(x => x.asset.endsWith('/big.js')).status, 'error');
    });
  });

  describe('failures and exit codes', () => {
    it('exits 1 for unreachable and 404 URLs, lists them, and still writes the page that worked', () => {
      const r = runs.partial;
      assert.equal(r.code, 1, r.stderr);
      assert.equal(r.json.failures.length, 2);
      assert.match(r.json.failures[0].error, /navigation: .*ERR_CONNECTION_REFUSED/);
      assert.match(r.json.failures[1].error, /navigation: HTTP 404/);
      const ok = r.json.results.find(x => x.url.endsWith('/privacy.html'));
      assert.ok(ok && !ok.error && ok.navigation.status === 200);
      assert.equal(r.json.results.length, 3);
    });
  });

  describe('evidence hygiene and offline behaviour', () => {
    it('writes no query string or fragment anywhere, and redacts emails and tokens', () => {
      for (const [name, run] of Object.entries(runs)) {
        const blob = [...strings(run.json)].join('\n') + run.stdout + run.stderr;
        assert.ok(!/https?:\/\/[^\s"']*[?#]/.test(blob), `${name}: URL with query or fragment`);
        assert.ok(!/SECRETVALUE123|a1b2c3d4e5f6|workshop\.lead@example\.com|QX7R2M9KLP4W8ZC3VB6N5A/i.test(blob), `${name}: unredacted value`);
      }
      assert.equal(first('pricing').url, `${site.origin}/pricing.html`);
      const todo = hit('pricing', h => h.match.toLowerCase() === 'todo');
      assert.match(todo.text, /<email>/); assert.match(todo.text, /<redacted>/);
    });
    it('is fully offline: the only host in any non-GET record is the local server, and nothing was POSTed', () => {
      for (const run of Object.values(runs)) for (const r of run.json.results) for (const k of Object.keys(r.nonGetRequests || {})) assert.ok(k.endsWith(site.host) || k.endsWith(edge.host), k);
      assert.deepEqual(site.log.filter(l => l.method !== 'GET'), []);
    });
    it('makes only the documented own GETs for a page: the page, each same-origin asset once, each map once', () => {
      const own = site.log.filter(l => isOwnGet(l));
      assert.ok(own.length > 0, 'own GETs should be identifiable by their user agent');
      for (const p of ['/pricing.html', '/assets/pricing-widget.js', '/assets/pricing-widget.js.map']) assert.equal(own.filter(l => l.path === p).length, 1, p);
    });
    it('spaces its own GETs at least the --delay apart', () => {
      // Several scenarios hit the demo server in parallel, so measure on the edge server, which only one process uses.
      const e = edge.log.filter(isOwnGet).map(l => l.t);
      assert.ok(e.length >= 4, `expected several own GETs, saw ${e.length}`);
      for (let i = 1; i < e.length; i++) assert.ok(e[i] - e[i - 1] >= 430, `gap ${e[i] - e[i - 1]} ms between own GETs`);
    });
  });

  describe('--cache', () => {
    it('a second run with the same cache folder makes no new GETs of its own and reports the same findings', () => {
      assert.equal(runs.cacheA.code, 0, runs.cacheA.stderr); assert.equal(runs.cacheB.code, 0, runs.cacheB.stderr);
      assert.ok(runs.cacheA.ownGets >= 4, `first run own GETs: ${runs.cacheA.ownGets}`);
      assert.equal(runs.cacheB.ownGets, runs.cacheA.ownGets, 'a cached run must not repeat its own GETs');
      assert.deepEqual(first('cacheB').sourceMaps, first('cacheA').sourceMaps);
      assert.deepEqual(first('cacheB').domHits, first('cacheA').domHits);
    });
  });
});
