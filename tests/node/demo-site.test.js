'use strict';
// The demo site itself: it must stay offline, fictional and documented; serve.py must serve it on 127.0.0.1 only.
const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const http = require('http');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const { SITE } = require('./helpers');

const walk = dir => fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]);
const files = walk(SITE).filter(f => !f.endsWith('.pyc') && !f.includes('__pycache__'));
const text = f => fs.readFileSync(f, 'utf8');
const pages = files.filter(f => f.endsWith('.html')).map(f => path.relative(SITE, f));

describe('demo site content', () => {
  it('has 6 to 8 pages including the clean control page', () => {
    assert.ok(pages.length >= 6 && pages.length <= 8, pages.join(', '));
    assert.ok(pages.includes('chain-care-guide.html'));
  });
  it('makes no request to any other host: no absolute URLs except mailto: and the plain-text example.com addresses', () => {
    for (const f of files.filter(f => /\.(html|css|js)$/.test(f))) {
      const src = text(f).replace(/mailto:[^"']+/g, '');
      const urls = src.match(/(?:https?:)?\/\/[\w.-]+/g) || [];
      // "//" also appears in JS comments; only count URL-looking values in attributes, url() and fetch/import calls.
      const attrs = [...src.matchAll(/(?:href|src|action|srcset|poster|data)=["']([^"']+)["']|url\(\s*["']?([^)"']+)|fetch\(\s*["']([^"']+)|import\(\s*["']([^"']+)/g)].map(m => m[1] || m[2] || m[3] || m[4]);
      for (const a of attrs) assert.ok(!/^(?:https?:)?\/\//i.test(a), `${path.relative(SITE, f)} references ${a}`);
      assert.ok(!/@import/.test(src), `${f} uses @import`);
      void urls;
    }
  });
  it('uses only example.com email addresses', () => {
    for (const f of files.filter(f => /\.(html|js|md|css)$/.test(f))) {
      for (const m of text(f).matchAll(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g)) assert.match(m[0], /@example\.com$/, `${path.relative(SITE, f)}: ${m[0]}`);
    }
  });
  it('every local link, script, stylesheet and source map target exists', () => {
    for (const p of pages) {
      for (const m of text(path.join(SITE, p)).matchAll(/(?:href|src)="([^"#:]+)(?:#[^"]*)?"/g)) {
        assert.ok(fs.existsSync(path.join(SITE, m[1])), `${p} links to missing ${m[1]}`);
      }
    }
    assert.ok(fs.existsSync(path.join(SITE, 'assets', 'pricing-widget.js.map')));
  });
  it('the control page carries no script, banner, form or hidden markup', () => {
    const c = text(path.join(SITE, 'chain-care-guide.html'));
    assert.ok(!/<script|cookie|<form|\shidden[\s>=]|display:\s*none|lorem|todo/i.test(c));
  });
  it('the two location pages are near-identical and the third is not', () => {
    const body = f => text(path.join(SITE, f)).match(/<main>([\s\S]*)<\/main>/)[1].replace(/<[^>]+>/g, ' ').replace(/Brindlemere|Oakhaven/g, 'X').toLowerCase().match(/\w+/g);
    const sh = w => new Set(Array.from({ length: w.length - 4 }, (_, i) => w.slice(i, i + 5).join(' ')));
    const jac = (a, b) => { const x = sh(a), y = sh(b); let n = 0; for (const s of x) if (y.has(s)) n++; return n / (x.size + y.size - n); };
    assert.ok(jac(body('brindlemere.html'), body('oakhaven.html')) >= 0.9);
    assert.ok(jac(body('brindlemere.html'), body('mobile-service.html')) < 0.3);
    assert.ok(body('brindlemere.html').length >= 150 && body('mobile-service.html').length >= 150);
  });
});

describe('demo site README', () => {
  const readme = text(path.join(SITE, 'README.md'));
  it('says the site is fictional and the faults are deliberate', () => {
    assert.match(readme, /fictional/i); assert.match(readme, /deliberate/i);
  });
  it('mentions every page', () => {
    for (const p of pages) assert.ok(readme.includes(p), `README does not mention ${p}`);
  });
});

const python = spawnSync('python3', ['--version']).status === 0 ? 'python3' : null;
describe('demo-site/serve.py', { skip: python ? false : 'python3 not found' }, () => {
  let child, base;
  before(async () => {
    child = spawn(python, [path.join(SITE, 'serve.py'), '--port', '0']);
    base = await new Promise((resolve, reject) => {
      let buf = '', err = '';
      const started = Date.now();
      const timer = setTimeout(() => reject(new Error(`serve.py did not print its URL within 60 s; stdout: ${JSON.stringify(buf)}; stderr: ${JSON.stringify(err.slice(-500))}`)), 60000);
      child.stdout.on('data', d => { buf += d; const m = /(http:\/\/127\.0\.0\.1:\d+)\//.exec(buf); if (m) { clearTimeout(timer); resolve(m[1]); } });
      child.stderr.on('data', d => { err += d; });
      child.on('exit', c => { clearTimeout(timer); reject(new Error(`serve.py exited ${c} after ${Date.now() - started} ms; stderr: ${JSON.stringify(err.slice(-500))}`)); });
    });
  });
  after(() => child && child.kill());

  const get = (p, opts = {}) => new Promise((resolve, reject) => {
    const u = new URL(base);
    http.get({ host: u.hostname, port: u.port, path: p, ...opts }, res => { let b = ''; res.on('data', d => { b += d; }); res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: b })); }).on('error', reject);
  });

  it('listens on 127.0.0.1 and serves the home page', async () => {
    const r = await get('/');
    assert.equal(r.status, 200); assert.match(r.body, /<title>Tidewick Bike Works/);
  });
  it('serves JS and source maps with usable content types and 404s unknown paths', async () => {
    assert.match((await get('/assets/consent.js')).headers['content-type'], /javascript/);
    const map = await get('/assets/pricing-widget.js.map');
    assert.equal(map.status, 200); assert.match(map.headers['content-type'], /json/);
    assert.equal((await get('/nope.html')).status, 404);
  });
  it('does not serve files from outside the demo folder', async () => {
    const r = await get('/../tests/node/package.json');
    assert.ok(r.status !== 200 || !r.body.includes('agentic-qa-toolkit-node-tests'), `status ${r.status}`);
  });
  it('rejects an out-of-range or non-numeric --port with exit 2, and --help exits 0', () => {
    assert.equal(spawnSync(python, [path.join(SITE, 'serve.py'), '--port', '70000']).status, 2);
    assert.equal(spawnSync(python, [path.join(SITE, 'serve.py'), '--port', 'abc']).status, 2);
    assert.equal(spawnSync(python, [path.join(SITE, 'serve.py'), '--help']).status, 0);
  });
});
