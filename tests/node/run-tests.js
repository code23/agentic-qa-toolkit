'use strict';
// `npm test` entry point: node --test with a per-test timeout (hooks and suites included) and an overall bound, so a stuck
// browser, server or script fails with the name of what was running instead of sitting silently.
//   QA_TEST_TIMEOUT_MS     per test / hook / suite (default 240000)
//   QA_TEST_TOTAL_MS       whole run (default 900000)
//   QA_TEST_KILL_GRACE_MS  grace between SIGTERM and SIGKILL for the process group on timeout (default 5000)
// On timeout the whole process group is cleaned up (SIGTERM, grace, SIGKILL) before the wrapper exits non-zero, even if the
// test runner itself has already gone: a hung browser that ignores SIGTERM must not outlive the run.
const { spawn } = require('child_process');
const perTest = Number(process.env.QA_TEST_TIMEOUT_MS) || 240000;
const total = Number(process.env.QA_TEST_TOTAL_MS) || 900000;
const grace = Number(process.env.QA_TEST_KILL_GRACE_MS) || 5000;
const child = spawn(process.execPath, ['--test', `--test-timeout=${perTest}`, ...process.argv.slice(2)], { stdio: 'inherit', detached: true });
const stop = sig => { try { process.kill(-child.pid, sig); } catch (e) { /* group already gone */ } };
let stopping = false;

// Shared by the overall timeout and by SIGINT/SIGTERM: SIGTERM the group, give it a grace period, SIGKILL whatever is left,
// then exit non-zero. Exits early once the group is empty.
function shutdown(why) {
  if (stopping) return;
  stopping = true;
  console.error(`\n[run-tests] ${why}; stopping the process group (SIGTERM, then SIGKILL after ${grace} ms)`);
  stop('SIGTERM');
  const groupAlive = () => { try { process.kill(-child.pid, 0); return true; } catch (e) { return e.code === 'EPERM'; } };
  const deadline = Date.now() + grace;
  const poll = setInterval(() => {
    if (!groupAlive()) { clearInterval(poll); process.exit(1); }
    if (Date.now() >= deadline) { clearInterval(poll); stop('SIGKILL'); process.exit(1); }
  }, 100);
}

const timer = setTimeout(() => shutdown(`overall limit of ${total} ms reached`), total);

child.on('exit', (code, signal) => {
  clearTimeout(timer);
  if (stopping) return;   // shutdown() owns the exit: it still has to SIGKILL any survivors in the group
  stop('SIGTERM');        // normal finish: sweep any stragglers the runner left behind
  process.exit(code || (signal ? 1 : 0));
});
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => shutdown(`received ${sig}`));
