'use strict';
// run-tests.js (the npm test wrapper) and the per-file watchdog in helpers.js must leave nothing running when they time out.
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { NO_CHROME, makeTmp, rmTmp, NODE_MODULES } = require('./helpers');

const alive = pid => { try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; } };
const run = (args, env) => new Promise(resolve => {
  const base = { ...process.env, NODE_PATH: NODE_MODULES, ...env };
  delete base.NODE_TEST_CONTEXT;   // the outer test runner sets this; inherited, it would stop a nested `node --test` acting as a runner
  const child = spawn(process.execPath, args, { cwd: __dirname, env: base });
  let stderr = ''; child.stderr.on('data', d => { stderr += d; }); child.stdout.on('data', () => {});
  child.on('exit', (code, signal) => setTimeout(() => resolve({ code, signal, stderr }), 200));
});
const waitDead = async pid => { for (let i = 0; i < 20 && alive(pid); i++) await new Promise(r => setTimeout(r, 100)); return !alive(pid); };

const readPid = async (file, withinMs) => {
  for (const t0 = Date.now(); Date.now() - t0 < withinMs; ) { if (fs.existsSync(file) && fs.readFileSync(file, 'utf8')) return Number(fs.readFileSync(file, 'utf8')); await new Promise(r => setTimeout(r, 100)); }
  return null;
};
const cleanup = (pid, tmp) => { if (pid && alive(pid)) { try { process.kill(pid, 'SIGKILL'); } catch (e) { /* gone */ } } rmTmp(tmp); };

describe('run-tests.js cleans up its process group', () => {
  it('on the overall timeout: kills a descendant that ignores SIGTERM and exits non-zero', async () => {
    // Nothing here depends on how fast the fixture starts: if the wrapper's limit expired before the fixture had written its
    // pid, the attempt is repeated with twice the limit. Once a pid exists, the assertions are about the state after the wrapper.
    let pid = null, tmp, r, total = 4000;
    for (let attempt = 0; attempt < 5 && !pid; attempt++, total *= 2) {
      tmp = makeTmp();
      const pidFile = path.join(tmp, 'pid');
      r = await run(['run-tests.js', 'fixtures/hang-fixture.js'], { QA_FIXTURE_PIDFILE: pidFile, QA_TEST_TOTAL_MS: String(total), QA_TEST_KILL_GRACE_MS: '1000' });
      pid = fs.existsSync(pidFile) && fs.readFileSync(pidFile, 'utf8') ? Number(fs.readFileSync(pidFile, 'utf8')) : null;
      if (!pid) rmTmp(tmp);
    }
    try {
      assert.ok(pid, 'the fixture never wrote its pid, even with a 64 s limit');
      assert.notEqual(r.code, 0, 'the wrapper must exit non-zero on timeout');
      assert.match(r.stderr, /overall limit of \d+ ms reached/);
      assert.equal(await waitDead(pid), true, `grandchild ${pid} survived the wrapper`);
    } finally { cleanup(pid, tmp); }
  });

  it('on SIGTERM to the wrapper: same clean-up, no timing involved', async () => {
    const tmp = makeTmp(); const pidFile = path.join(tmp, 'pid');
    let pid = null;
    try {
      const env = { ...process.env, NODE_PATH: NODE_MODULES, QA_FIXTURE_PIDFILE: pidFile, QA_TEST_TOTAL_MS: '600000', QA_TEST_KILL_GRACE_MS: '1000' };
      delete env.NODE_TEST_CONTEXT;
      const child = spawn(process.execPath, ['run-tests.js', 'fixtures/hang-fixture.js'], { cwd: __dirname, env, stdio: 'ignore' });
      const exited = new Promise(res => child.on('exit', (code, signal) => res({ code, signal })));
      pid = await readPid(pidFile, 120000);
      assert.ok(pid, 'the fixture never wrote its pid');
      child.kill('SIGTERM');
      const { code } = await exited;
      assert.notEqual(code, 0);
      assert.equal(await waitDead(pid), true, `grandchild ${pid} survived the wrapper`);
    } finally { cleanup(pid, tmp); }
  });
});

describe('per-file watchdog', { skip: NO_CHROME }, () => {
  it('kills its own browser before exiting 1', async () => {
    // The fixture arms the watchdog only after the browser is running and its pid is on disk, so a slow start cannot race it.
    const tmp = makeTmp(); const pidFile = path.join(tmp, 'pid');
    let pid = null;
    try {
      const r = await run(['fixtures/watchdog-fixture.js'], { QA_FIXTURE_PIDFILE: pidFile });
      pid = await readPid(pidFile, 1000);
      assert.ok(pid, `the fixture never wrote the browser pid; stderr: ${r.stderr.slice(0, 300)}`);
      assert.equal(r.code, 1);
      assert.match(r.stderr, /\[watchdog\] watchdog-fixture\.js still running after 1500 ms/);
      assert.equal(await waitDead(pid), true, `browser ${pid} survived the watchdog`);
    } finally { cleanup(pid, tmp); }
  });
});
