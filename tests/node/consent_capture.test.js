'use strict';
// consent_capture.js against the demo site. Each scenario runs the script once (in parallel); the tests below only read the results.
const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { NO_CHROME, startSite, closedPort, runScript, makeTmp, rmTmp, readJson, strings } = require('./helpers');

describe('consent_capture.js on the demo site', { skip: NO_CHROME }, () => {
  let site, tmp, dead;
  const runs = {};

  const scenario = async (name, urls, args) => {
    const out = path.join(tmp, `${name}.json`);
    const r = await runScript('consent_capture.js', [Array.isArray(urls) ? urls.join(',') : urls, '--out', out, '--delay', '500', ...args], { cwd: tmp });
    runs[name] = { ...r, json: fs.existsSync(out) ? readJson(out) : null };
    // A run that wrote nothing is otherwise silent: show what the script printed, so a failure on a slow CI machine says why.
    if (!fs.existsSync(out)) console.error(`[consent_capture] scenario "${name}" wrote no output (exit ${r.code})\n--- stdout tail ---\n${r.stdout.slice(-1500)}\n--- stderr tail ---\n${r.stderr.slice(-1500)}`);
  };

  before(async () => {
    site = await startSite(); dead = await closedPort(); tmp = makeTmp();
    const u = p => `${site.origin}/${p}`;
    await Promise.all([
      scenario('home', u('index.html?campaign=SECRETVALUE#top'), ['--width', '375,1366', '--policy', u('privacy.html?x=1')]),
      scenario('pricing', u('pricing.html'), ['--width', '1366']),
      scenario('contact', u('contact.html'), ['--width', '1366']),
      scenario('control', [`http://127.0.0.1:${dead}/gone.html`, u('chain-care-guide.html')], ['--width', '1366']),
      scenario('noreject', u('chain-care-guide.html'), ['--width', '1366', '--no-reject', '--egress', 'GB', '--policy', `http://127.0.0.1:${dead}/privacy.html`]),
    ]);
  });
  after(async () => { await site.close(); rmTmp(tmp); });

  const res = (run, w) => {
    const all = runs[run].json.results.filter(r => r.width === w);
    const ok = all.find(r => !r.error);
    if (!ok) throw new Error(`${run}: no usable ${w}px result; exit ${runs[run].code}; errors: ${JSON.stringify(all.map(r => r.error))}; stderr: ${runs[run].stderr.slice(0, 300)}`);
    return ok;
  };
  const names = list => list.map(c => c.name);
  const sorted = a => [...a].sort();

  describe('home page: banner with Accept / Reject, analytics cookie set before any choice', () => {
    it('exits 0 and covers both widths', () => {
      assert.equal(runs.home.code, 0, runs.home.stderr);
      assert.deepEqual(runs.home.json.results.map(r => r.width), [375, 1366]);
      assert.deepEqual(runs.home.json.failures, []);
      assert.equal(runs.home.json.policyError, null);
    });
    for (const w of [375, 1366]) {
      it(`${w}px: reports the analytics cookie set before any choice as pre-consent tracking`, () => {
        const r = res('home', w);
        assert.ok(names(r.preConsent.cookies).includes('_ga'), JSON.stringify(r.preConsent.cookies));
        assert.deepEqual(r.preConsentTracking, ['google analytics']);
        assert.equal(r.preConsent.cookies.find(c => c.name === '_ga').domain, '127.0.0.1');
      });
      it(`${w}px: clicks Accept once, then reports the cookie that only appears after Accept`, () => {
        const r = res('home', w);
        assert.equal(r.acceptClicked, 'Accept all'); assert.equal(r.acceptContainer, 'named'); assert.equal(r.postConsentBlocked, null);
        assert.deepEqual(names(r.newCookiesAfterConsent), ['_hjid']);
        assert.ok(r.postConsent.storage.local.includes('tidewick-consent'));
        assert.equal(r.acceptError, null);
      });
      it(`${w}px: Reject is honoured on this page`, () => {
        const j = res('home', w).reject;
        assert.equal(j.clicked, 'Reject all'); assert.equal(j.container, 'named');
        assert.equal(j.rejectHonoured, true);
        assert.deepEqual(j.trackersBeforeClick, ['google analytics']);
        assert.deepEqual(j.newTrackersAfterReject, []); assert.deepEqual(j.trackerCookiesAfterReject, []);
        assert.ok(names(j.postReject.cookies).includes('_ga') && !names(j.postReject.cookies).includes('_hjid'));
      });
    }
    it('uses mobile emulation at 375 and none at 1366', () => {
      assert.equal(res('home', 375).emulation.mobile, true); assert.equal(res('home', 1366).emulation.mobile, false);
    });
    it('compares detected vendors with the privacy policy: Google Analytics is named, the Hotjar-style cookie is not', () => {
      const pc = res('home', 1366).policyCheck;
      assert.ok(pc, 'policyCheck missing');
      const ga = pc.find(x => x.vendor === 'google analytics' && x.kind === 'cookie'), hj = pc.find(x => x.vendor === 'hotjar' && x.kind === 'cookie');
      assert.equal(ga.mentionedInPolicy, true); assert.equal(hj.mentionedInPolicy, false);
      assert.equal(hj.category, 'analytics');
    });
    it('leaves IP-address hosts out of policyCheck', () => {
      const pc = res('home', 1366).policyCheck;
      assert.deepEqual(pc.filter(x => x.kind === 'host'), []);
    });
    it('records no Consent Mode signals, no non-GET requests and no mixed content', () => {
      const r = res('home', 1366);
      assert.deepEqual(r.preConsent.consentModeSignals, []); assert.deepEqual(r.nonGetRequests, {}); assert.deepEqual(r.mixedContent, []);
      assert.deepEqual(r.blockedNavigations, []); assert.deepEqual(r.reject.blockedNavigations, []);
    });
  });

  describe('pricing page: Reject is not honoured', () => {
    it('is clean before any choice but sets an analytics cookie after Reject', () => {
      assert.equal(runs.pricing.code, 0, runs.pricing.stderr);
      const r = res('pricing', 1366);
      assert.deepEqual(r.preConsentTracking, []);
      assert.equal(r.acceptClicked, 'Accept all');
      assert.equal(r.reject.clicked, 'Reject all');
      assert.equal(r.reject.rejectHonoured, false);
      assert.deepEqual(r.reject.trackersBeforeClick, []);
      assert.deepEqual(r.reject.newTrackersAfterReject, ['hotjar']);
      assert.deepEqual(r.reject.trackerCookiesAfterReject, [{ name: '_hjid', domain: '127.0.0.1', vendor: 'hotjar', alreadySetBeforeClick: false }]);
    });
  });

  describe('contact page: second banner variant (I agree / Decline), well behaved', () => {
    it('finds "I agree" through the broader label rule, only because the container is consent-named', () => {
      assert.equal(runs.contact.code, 0, runs.contact.stderr);
      const r = res('contact', 1366);
      assert.equal(r.acceptClicked, 'I agree'); assert.equal(r.acceptContainer, 'named');
    });
    it('is clean before a choice, sets its cookie only after Accept, and honours Decline', () => {
      const r = res('contact', 1366);
      assert.deepEqual(r.preConsentTracking, []); assert.deepEqual(r.preConsent.cookies, []);
      assert.deepEqual(names(r.newCookiesAfterConsent), ['_ga']);
      assert.equal(r.reject.clicked, 'Decline'); assert.equal(r.reject.rejectHonoured, true);
      assert.deepEqual(r.reject.trackersAfterReject, []);
    });
    it('never submits the form on the page', () => {
      assert.deepEqual(site.log.filter(l => l.method !== 'GET'), []);
    });
  });

  describe('page without a banner', () => {
    it('marks Accept and Reject as blocked, and is clean', () => {
      const r = res('control', 1366);
      assert.equal(r.acceptClicked, null); assert.match(r.postConsentBlocked, /no accept control found/); assert.equal(r.postConsent, null);
      assert.match(r.reject.blocked, /no reject control found/); assert.equal(r.reject.rejectHonoured, null);
      assert.deepEqual(r.preConsent.cookies, []); assert.deepEqual(r.preConsent.storage, { local: [], session: [] }); assert.deepEqual(r.preConsentTracking, []);
    });
  });

  describe('failures, exit codes and options', () => {
    it('exits 1 when one URL is unreachable, records it, and still reports the other URL', () => {
      const r = runs.control;
      assert.equal(r.code, 1, r.stderr);
      assert.equal(r.json.failures.length, 1);
      assert.match(r.json.failures[0].error, /navigation: .*ERR_CONNECTION_REFUSED/);
      assert.equal(r.json.results.length, 2);
      assert.match(r.json.results[0].error, /ERR_CONNECTION_REFUSED/);
      assert.equal(r.json.results[1].url, `${site.origin}/chain-care-guide.html`);
    });
    it('--no-reject skips the Reject phase; --egress is recorded; an unreachable --policy is a partial failure', () => {
      const r = runs.noreject;
      assert.equal(r.code, 1, r.stderr);
      assert.equal(r.json.labels.reject, null); assert.equal(r.json.egressCountry, 'GB');
      assert.equal(res('noreject', 1366).reject, undefined);
      assert.match(r.json.policyError, /ERR_CONNECTION_REFUSED/);
    });
    it('reports the default egress as unknown', () => {
      assert.equal(runs.home.json.egressCountry, 'unknown');
    });
  });

  describe('evidence hygiene and safety', () => {
    it('writes no query string or fragment anywhere', () => {
      for (const [name, run] of Object.entries(runs)) {
        assert.ok(!/https?:\/\/[^\s"']*[?#]/.test(JSON.stringify(run.json) + run.stdout + run.stderr), name);
      }
      const all = JSON.stringify(runs.home.json) + runs.home.stdout;
      assert.ok(!all.includes('SECRETVALUE') && !all.includes('campaign='));
      assert.equal(runs.home.json.results[0].url, `${site.origin}/index.html`);
    });
    it('redacts token-like cookie names and never writes the raw name', () => {
      const cookie = res('home', 1366).preConsent.cookies.find(c => c.name.startsWith('tw_v'));
      assert.ok(cookie, 'the visitor-id cookie should be listed');
      assert.equal(cookie.name, 'tw_v…<redacted>');
      for (const [name, run] of Object.entries(runs)) {
        const blob = [...strings(run.json)].join('\n') + run.stdout + run.stderr;
        assert.ok(!blob.includes('tw_visitor_k3j9x2m7q1w8e5r4t6y0') && !blob.includes('k3j9x2m7q1w8'), `${name}: raw cookie name leaked`);
      }
    });
    it('keeps cookie values out of the output', () => {
      assert.ok(!JSON.stringify(runs.home.json).includes('"value"'));
    });
    it('is fully offline: every request host the page made (pre-consent, post-consent and post-reject) is the local server', () => {
      const hosts = new Set();
      for (const run of Object.values(runs)) for (const r of run.json.results) {
        if (r.error) continue;
        for (const snap of [r.preConsent, r.postConsent, r.reject && r.reject.preReject, r.reject && r.reject.postReject]) if (snap) snap.hosts.forEach(h => hosts.add(h));
      }
      assert.deepEqual([...hosts], [site.host]);
    });
    it('sends only GET requests to the site: nothing is typed, ticked or submitted', () => {
      assert.deepEqual(site.log.filter(l => l.method !== 'GET'), []);
    });
  });
});
