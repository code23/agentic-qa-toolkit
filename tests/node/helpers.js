'use strict';
// Shared test helpers: locate the repo pieces, serve the demo site in-process, run the scripts as subprocesses.
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const { spawn } = require('child_process');

const REPO = path.resolve(__dirname, '..', '..');
const SCRIPTS = path.join(REPO, 'skills', 'qa-site-audit', 'scripts');
const REFERENCES = path.join(REPO, 'skills', 'qa-site-audit', 'references');
const SITE = path.join(REPO, 'demo-site');
const NODE_MODULES = path.join(__dirname, 'node_modules');

// Same default the scripts use, so a missing browser is reported the way the scripts would hit it.
const CHROME = process.env.CHROME_PATH || (process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : '/usr/bin/google-chrome');
const NO_CHROME = fs.existsSync(CHROME) ? false : `Chrome not found at ${CHROME}; set CHROME_PATH to run the browser tests`;

// Hang insurance. `npm test` runs the suite through run-tests.js (per-test and overall bounds). This watchdog covers a test file
// run directly: if the file is still running after FILE_LIMIT_MS it reports what keeps the process alive and exits 1, so a stuck
// run can never sit silently.
const FILE_LIMIT_MS = Number(process.env.QA_TEST_FILE_LIMIT_MS) || 270000;
function armWatchdog(limitMs) {
  setTimeout(() => {
    console.error(`[watchdog] ${path.basename(require.main ? require.main.filename : process.argv[1] || 'test file')} still running after ${limitMs} ms; active resources: ${JSON.stringify(process.getActiveResourcesInfo ? process.getActiveResourcesInfo() : 'n/a')}`);
    process.exit(1);
  }, limitMs).unref();
}
armWatchdog(FILE_LIMIT_MS);

// Resolve when a promise settles or after ms, whichever is first (teardown must never wait forever).
const within = (promise, ms) => Promise.race([Promise.resolve(promise).catch(() => {}), new Promise(r => setTimeout(r, ms).unref())]);
// Force-close a node http server: drop every connection (including never-ending responses), then close it. Tolerates undefined.
function stopServer(server) {
  if (!server) return Promise.resolve();
  try { server.closeAllConnections(); } catch (e) { /* already closed */ }
  return within(new Promise(r => server.close(() => r())), 3000);
}
// Close a puppeteer browser, then kill its process if it is still alive. Tolerates undefined.
async function killBrowser(browser) {
  if (!browser) return;
  const proc = browser.process && browser.process();
  await within(browser.close(), 8000);
  if (proc && proc.exitCode === null && !proc.killed) { try { proc.kill('SIGKILL'); } catch (e) { /* gone */ } }
  if (browser.__dir) fs.rmSync(browser.__dir, { recursive: true, force: true });
}

const MIME = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.map': 'application/json', '.json': 'application/json', '.svg': 'image/svg+xml' };

// Serve a folder on 127.0.0.1 and a random free port. Every request is logged (time, path, user agent).
// headers(pathname) may add response headers (for example SourceMap).
function startSite(root = SITE, { headers = () => ({}) } = {}) {
  const log = [];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    log.push({ t: Date.now(), method: req.method, path: url.pathname, ua: req.headers['user-agent'] || '' });
    let rel = decodeURIComponent(url.pathname);
    if (rel.endsWith('/')) rel += 'index.html';
    const file = path.join(root, path.normalize(rel));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404, { 'content-type': 'text/plain' }); res.end('not found'); return;
    }
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store', ...headers(url.pathname) });
    res.end(fs.readFileSync(file));
  });
  return new Promise(resolve => server.listen(0, '127.0.0.1', () => {
    const { port } = server.address();
    resolve({ port, origin: `http://127.0.0.1:${port}`, host: `127.0.0.1:${port}`, log, close: () => stopServer(server) });
  }));
}

// A port nothing listens on: bind, note the port, release it.
async function closedPort() {
  const s = http.createServer();
  await new Promise(r => s.listen(0, '127.0.0.1', r));
  const { port } = s.address();
  await new Promise(r => s.close(r));
  return port;
}

// Run one of the scripts under test as a subprocess. Resolves { code, stdout, stderr } (never rejects on a non-zero exit).
function runScript(script, args, { env = {}, cwd = os.tmpdir(), timeoutMs = 200000 } = {}) {
  return new Promise(resolve => {
    const child = spawn(process.execPath, [path.join(SCRIPTS, script), ...args],
      { cwd, env: { ...process.env, NODE_PATH: NODE_MODULES, ...env } });
    let stdout = '', stderr = '';
    child.stdout.on('data', d => { stdout += d; });
    child.stderr.on('data', d => { stderr += d; });
    const timer = setTimeout(() => { stderr += `\n[test harness] ${script} killed after ${timeoutMs} ms`; child.kill('SIGKILL'); }, timeoutMs);
    // Settle on 'exit' (plus a short grace for buffered output) rather than 'close', which also waits for every inherited pipe.
    child.on('exit', code => setTimeout(() => { clearTimeout(timer); resolve({ code, stdout, stderr }); }, 300));
  });
}

const makeTmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'qa-node-tests-'));
const rmTmp = dir => fs.rmSync(dir, { recursive: true, force: true });
const readJson = file => JSON.parse(fs.readFileSync(file, 'utf8'));

// Every string value in a JSON-like structure.
function* strings(x) {
  if (typeof x === 'string') yield x;
  else if (Array.isArray(x)) for (const v of x) yield* strings(v);
  else if (x && typeof x === 'object') for (const [k, v] of Object.entries(x)) { yield k; yield* strings(v); }
}

// Make puppeteer-core resolvable for the scripts' modules when they are required in this process.
function enablePuppeteer() {
  const existing = (process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean);
  if (!existing.includes(NODE_MODULES)) process.env.NODE_PATH = [NODE_MODULES, ...existing].join(path.delimiter);
  require('module').Module._initPaths();
}

module.exports = { armWatchdog, within, stopServer, killBrowser, REPO, SCRIPTS, REFERENCES, SITE, NODE_MODULES, CHROME, NO_CHROME, startSite, closedPort, runScript, makeTmp, rmTmp, readJson, strings, enablePuppeteer };
