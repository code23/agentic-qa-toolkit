'use strict';
// Not a test for npm test discovery (name and folder do not match the runner's patterns). Used by run-tests.test.js:
// a test that never finishes, next to a grandchild process that ignores SIGTERM. The pid file is written only once the
// grandchild has installed its SIGTERM handler, so a test that reads the pid can rely on the grandchild really ignoring it.
const { test } = require('node:test');
const { spawn } = require('child_process');
const fs = require('fs');
test('hangs forever, next to a SIGTERM-proof grandchild', async () => {
  const g = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); process.stdout.write("ready\\n"); setInterval(() => {}, 1000);'], { stdio: ['ignore', 'pipe', 'ignore'] });
  await new Promise(resolve => g.stdout.once('data', resolve));
  fs.writeFileSync(process.env.QA_FIXTURE_PIDFILE, String(g.pid));
  await new Promise(() => {});
});
