'use strict';
// Used by run-tests.test.js: launch a browser, then hang so that the per-file watchdog in helpers.js has to fire.
const fs = require('fs');
const path = require('path');
const { enablePuppeteer, armWatchdog, SCRIPTS } = require('../helpers');
enablePuppeteer();
const common = require(path.join(SCRIPTS, '_common.js'));
common.freshBrowser().then(browser => {
  fs.writeFileSync(process.env.QA_FIXTURE_PIDFILE, String(browser.process().pid));
  armWatchdog(1500);             // armed only now that the browser is up and its pid is on disk, so the test cannot race it
  setInterval(() => {}, 1000);   // keep the process alive until the watchdog fires
});
