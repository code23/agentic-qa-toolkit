# Tidewick Bike Works: demo site with deliberate faults

Tidewick Bike Works is a **fictional** bicycle workshop. The names, towns, prices and email addresses (all at `example.com`) are invented. The site exists to give the `qa-site-audit` scripts something to find, and to give the test suite in `tests/node/` a known target.

**Every fault listed below is deliberate.** Nothing on this site is a real business, person or offer, and the contact form goes nowhere. Do not copy its markup as an example of good practice, apart from `chain-care-guide.html`, which is the clean control page.

The site is plain HTML, CSS and a little JavaScript. There is no build step and it makes no request to any other host: no CDN, no web fonts, no analytics, no remote images.

## Run it

```
python3 demo-site/serve.py            # http://127.0.0.1:8765/   (--port N to change it, --port 0 for any free port)
```

The server uses only the Python standard library and listens on `127.0.0.1` only. Then point a script at it, from a scratch folder so the default `evidence/` output lands there:

```
printf '%s\n' http://127.0.0.1:8765/index.html http://127.0.0.1:8765/pricing.html > urls.txt
NODE_PATH=<a node_modules with puppeteer-core> node skills/qa-site-audit/scripts/viewport_overflow.js urls.txt
```

The browser scripts need `puppeteer-core` and Chrome (see the skill's `SKILL.md`, "Scripts"). The Python scripts need `requests`, `beautifulsoup4` and `lxml`.

## Pages

| Page | Purpose |
|---|---|
| `index.html` | Home. Cookie banner variant A. |
| `brindlemere.html`, `oakhaven.html` | Two near-identical location pages. |
| `mobile-service.html` | A genuinely different location-style page (the repair van). |
| `pricing.html` | Prices, banner variant A, stale copy, hidden markup. |
| `contact.html` | Contact form that posts nowhere, banner variant B. |
| `privacy.html` | Privacy and cookie policy (names Google Analytics only). |
| `chain-care-guide.html` | **Clean control page.** No script, banner, form or hidden markup. |

## Planted faults and what detects them

Script names are in `skills/qa-site-audit/scripts/`. Field names are keys in the script's JSON output. The Python scripts are run with `--mask "Brindlemere,Oakhaven"` (similarity) and `--today 2026-07-15 --timezone Europe/London` (copy_freshness, so that London is on summer time).

| # | Fault | Page | Detected by | Output field |
|---|---|---|---|---|
| 1 | Horizontal overflow at 768 px wide only; clean at 320, 375, 1024 and 1440 | `index.html` | `viewport_overflow.js` | `results[]` for viewport 768: `overflowPx` > 0, `actualScrollX` > 0, `offenders[0].el` (`div#hours.hours-strip`) |
| 2 | Fixed header sits on top of the H1 (sticky headers elsewhere clear it) | `mobile-service.html` | `viewport_overflow.js` | `headerClearsH1: false` at every width |
| 3 | Mobile-only price: £39 on phones, £45 on desktop | `pricing.html` | `viewport_overflow.js` | `parity[].onlyNarrow`, `onlyWide`, `withNumbersOrPrices` |
| 4 | Analytics-style cookie `_ga` set before any consent choice | `index.html` | `consent_capture.js` | `results[].preConsentTracking` (`google analytics`), `preConsent.cookies` |
| 5 | Another analytics-style cookie set only after Accept (`_hjid` on the home page, `_ga` on the contact page) | `index.html`, `contact.html` | `consent_capture.js` | `results[].newCookiesAfterConsent` |
| 6 | Reject honoured on the home and contact pages, **not** honoured on pricing (`_hjid` is set after Reject) | `index.html`, `contact.html`, `pricing.html` | `consent_capture.js` | `results[].reject.rejectHonoured`, `newTrackersAfterReject`, `trackerCookiesAfterReject` |
| 7 | Second banner variant: labels "I agree" and "Decline", matched by the bare-"Agree" rule in a consent-named container | `contact.html` | `consent_capture.js` | `results[].acceptClicked` (`I agree`), `acceptContainer` (`named`), `reject.clicked` (`Decline`) |
| 8 | A vendor that loads after Accept (Hotjar-style `_hjid`) is missing from the privacy policy | `index.html` vs `privacy.html` | `consent_capture.js --policy <privacy.html URL>` | `results[].policyCheck[]` with `mentionedInPolicy: false` |
| 9 | Leftover debug and test markup hidden in the DOM: a TODO note, a "test label" and a `debug-grid` class (all served), plus a `debug-overlay` element injected by script | `pricing.html`; `contact.html` | `dev_artefacts.js` | `results[].domHits[]` (`visible: false`, `inServedHtml` true, or false for the injected one) |
| 10 | Console error | `contact.html` | `dev_artefacts.js` | `results[].consoleMsgs` |
| 11 | Failed same-origin request (404 for `/api/availability.json`) | `contact.html` | `dev_artefacts.js` | `results[].failedRequests` |
| 12 | Uncaught script error (`bookingWidget` is never defined) | `mobile-service.html` | `dev_artefacts.js` | `results[].pageErrors` |
| 13 | Source map left public next to its script | `pricing.html` | `dev_artefacts.js` | `results[].sourceMaps[]` with `status: 200` |
| 14 | Stale quarter ("Q1 2024"), old "last updated" year (2022) and old copyright year (2021) | `pricing.html` | `copy_freshness.py` | `pages[].flags[].type`: `stale-quarter`, `old-year`, `copyright-year` |
| 15 | Out-of-season timezone label: "GMT" in summer | `contact.html` | `copy_freshness.py --today 2026-07-15 --timezone Europe/London` | `pages[].flags[].type`: `timezone-label` |
| 16 | Lorem ipsum in visible copy | `contact.html` | `dev_artefacts.js`; `copy_freshness.py` | `domHits[]` (`visible: true`); `flags[].type`: `placeholder` |
| 17 | Two near-identical location pages (about 95% similar once the town names are masked) next to one genuinely different page | `brindlemere.html`, `oakhaven.html` (and `mobile-service.html` as the contrast) | `similarity.py` | `pairs[]` with `flag: true` for the Brindlemere and Oakhaven pair only |
| 18 | The repair van page carries an unrelated title ("Workshop opening hours") under a different slug | `mobile-service.html` | `copy_freshness.py` | `pages[].flags[].type`: `title-slug-mismatch` |

### Clean control page

`chain-care-guide.html` plants nothing. The scripts should report no overflow, a header that clears the H1, no banner and no cookies, no breakpoint-only text, no DOM hits, no console or page errors, no failed requests and no source maps. It does contain one decorative SVG that is wider than the page but clipped by an `overflow: hidden` wrapper; `viewport_overflow.js` must count it in `clippedWideElements` and not as an offender.

### Fixtures for the evidence-hygiene checks

These are fake values, there only so the tests can prove redaction works:

- `pricing.html` contains an email address and a token-like reference in text (and in the hidden TODO note). The scripts should print `<email>` and a shortened `…<redacted>` form, never the originals.
- `index.html` sets a cookie with a long token-like name. `consent_capture.js` should list it in shortened form only.
- `contact.html` requests `/api/availability.json?session=…`. The query string must not appear in any output.

### Not a fault

The contact form's `action` is `#`, so a submit goes nowhere. The scripts never type into or submit forms, and the test suite asserts the server never sees a POST.
