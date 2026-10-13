'use strict';
// Command-line behaviour that must work with no browser and no puppeteer-core: --help, option validation, exit codes.
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { runScript, makeTmp, rmTmp } = require('./helpers');

const SCRIPT_NAMES = ['viewport_overflow.js', 'consent_capture.js', 'dev_artefacts.js'];
const NO_PUPPETEER = { NODE_PATH: '' };
const URL1 = 'http://127.0.0.1:9/index.html';

// Each row: [description, args]. All must exit 2 with a usage message and must not touch the network or a browser.
const COMMON_BAD = [
  ['an unknown option', [URL1, '--nonsense']],
  ['an option with no value', [URL1, '--delay']],
  ['an option whose value is another option', [URL1, '--delay', '--out']],
  ['a delay below the 500 ms minimum', [URL1, '--delay', '100']],
  ['a non-numeric delay', [URL1, '--delay', 'soon']],
  ['no URL at all', []],
  ['two URL arguments', [URL1, URL1]],
  ['a non-http URL', ['ftp://example.com/']],
  ['a URL with credentials', ['http://user:secretpw@example.com/']],
  ['text that is not a URL', ['example.com']],
  ['one bad URL among good ones', [`${URL1},file:///etc/passwd`]],
];
const PER_SCRIPT_BAD = {
  'viewport_overflow.js': [
    ['a width below 200', [URL1, '--viewports', '100']],
    ['a width above 4000', [URL1, '--viewports', '5000']],
    ['a malformed WIDTHxHEIGHT', [URL1, '--viewports', '375x']],
    ['an empty width list', [URL1, '--viewports', ',']],
    ['an invalid CTA regular expression', [URL1, '--cta', '(']],
  ],
  'consent_capture.js': [
    ['an invalid accept regular expression', [URL1, '--accept', '(']],
    ['an invalid reject regular expression', [URL1, '--reject', '[']],
    ['a bad --width value', [URL1, '--width', 'wide']],
    ['a non-http policy URL', [URL1, '--policy', 'ftp://example.com/privacy']],
  ],
  'dev_artefacts.js': [
    ['a width below 200', [URL1, '--width', '100']],
    ['a width above 4000', [URL1, '--width', '5000']],
    ['a timeout below 1000 ms', [URL1, '--timeout', '10']],
    ['a max-bytes cap below 10000', [URL1, '--max-bytes', '5']],
  ],
};

for (const script of SCRIPT_NAMES) {
  describe(`${script} command line`, () => {
    it('--help prints usage and exits 0 without puppeteer-core', async () => {
      const r = await runScript(script, ['--help'], { env: NO_PUPPETEER });
      assert.equal(r.code, 0, r.stderr);
      assert.match(r.stdout, new RegExp(`Usage: node ${script}`));
      assert.match(r.stdout, /Exit: 0/);
    });
    it('-h works too, and --help wins over other bad arguments', async () => {
      assert.equal((await runScript(script, ['-h'], { env: NO_PUPPETEER })).code, 0);
      assert.equal((await runScript(script, ['--bogus', '--help'], { env: NO_PUPPETEER })).code, 0);
    });
    for (const [what, args] of [...COMMON_BAD, ...PER_SCRIPT_BAD[script]]) {
      it(`exits 2 for ${what}`, async () => {
        const r = await runScript(script, args, { env: NO_PUPPETEER });
        assert.equal(r.code, 2, `stdout: ${r.stdout}\nstderr: ${r.stderr}`);
        assert.match(r.stderr, /Usage: node /, 'the error should be followed by the usage text');
        assert.ok(!/secretpw/.test(r.stderr), 'credentials must not be echoed');
      });
    }
    it('exits 2 for an empty URL list file', async () => {
      const tmp = makeTmp();
      try {
        const f = path.join(tmp, 'urls.txt'); fs.writeFileSync(f, '\n# only a comment\n\n');
        const r = await runScript(script, [f], { env: NO_PUPPETEER });
        assert.equal(r.code, 2); assert.match(r.stderr, /URL list is empty/);
      } finally { rmTmp(tmp); }
    });
    it('exits 2 for a URL list file that holds one invalid entry', async () => {
      const tmp = makeTmp();
      try {
        const f = path.join(tmp, 'urls.txt'); fs.writeFileSync(f, `${URL1}\nftp://example.com/x\n`);
        assert.equal((await runScript(script, [f], { env: NO_PUPPETEER })).code, 2);
      } finally { rmTmp(tmp); }
    });
    it('--help mentions the navigation guard where the script has one, and works without Chrome', async () => {
      const r = await runScript(script, ['--help'], { env: { ...NO_PUPPETEER, CHROME_PATH: '/nonexistent/chrome' } });
      assert.equal(r.code, 0, r.stderr);
      assert.match(r.stdout, /Chrome binary|exit 2|dependency error/i);
      assert.match(r.stdout, /Navigation guard/);
    });
    it('exits 2 before processing any URL when the Chrome binary is missing, and writes nothing', async () => {
      const tmp = makeTmp();
      try {
        const out = path.join(tmp, 'out.json');
        for (const chrome of ['/nonexistent/chrome', tmp, path.join(tmp, 'not-executable')]) {
          fs.writeFileSync(path.join(tmp, 'not-executable'), 'x', { mode: 0o644 });
          const r = await runScript(script, [`${URL1},http://127.0.0.1:9/two.html`, '--out', out], { env: { CHROME_PATH: chrome } });
          assert.equal(r.code, 2, `${chrome}: stdout ${r.stdout}\nstderr ${r.stderr}`);
          assert.match(r.stderr, /Chrome\/Chromium binary not found or not executable/);
          assert.match(r.stderr, /CHROME_PATH/);
          assert.equal(fs.existsSync(out), false, 'no result file should be written for a dependency error');
        }
      } finally { rmTmp(tmp); }
    });
    it('exits 2 with a clear message when puppeteer-core is missing and valid arguments are given', async () => {
      const tmp = makeTmp();
      try {
        const r = await runScript(script, [URL1, '--out', path.join(tmp, 'out.json')], { env: NO_PUPPETEER });
        assert.equal(r.code, 2, `stdout: ${r.stdout}\nstderr: ${r.stderr}`);
        assert.match(r.stderr, /puppeteer-core not found/);
        assert.match(r.stderr, /NODE_PATH/);
      } finally { rmTmp(tmp); }
    });
  });
}

describe('dev_artefacts.js --cache help text', () => {
  it('says the cache is raw working data, not evidence, and not to be shared', async () => {
    const r = await runScript('dev_artefacts.js', ['--help'], { env: NO_PUPPETEER });
    assert.match(r.stdout, /raw fetched\s+content and exact URLs/);
    assert.match(r.stdout, /working data, not evidence/);
    assert.match(r.stdout, /must not be shared/);
  });
});
