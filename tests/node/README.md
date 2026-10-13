# Node tests for the headless-browser scripts

Offline tests for `skills/qa-site-audit/scripts/` (`_common.js`, `viewport_overflow.js`, `consent_capture.js`, `dev_artefacts.js`). They run the scripts against the fictional site in `demo-site/`, which the tests serve in-process on `127.0.0.1` and a random free port. Nothing leaves the machine.

```
cd tests/node
npm install        # puppeteer-core only, pinned; run it here, never inside skills/
npm test           # run-tests.js: node --test with a per-test timeout (QA_TEST_TIMEOUT_MS, default 240000) and an overall bound (QA_TEST_TOTAL_MS, default 900000)
```

- Needs Node 20.11 or newer (the runner uses `--test-timeout`) and Chrome. Set `CHROME_PATH` if Chrome is not at the platform default the scripts use. Without Chrome the browser tests are skipped with a message; the command-line and unit tests still run.
- The tests set `NODE_PATH` to this folder's `node_modules` when they spawn a script, which is how the scripts find `puppeteer-core`.
- Everything is written to temporary folders and removed afterwards.
- The suite takes about two minutes: each script is run once per scenario, scenarios run in parallel, and the assertions read the saved JSON.
- `demo-site/README.md` lists every planted fault and which script and field should report it.
