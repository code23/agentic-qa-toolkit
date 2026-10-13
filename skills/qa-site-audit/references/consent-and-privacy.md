# Consent and privacy capture

## Why clicking Accept or Reject is allowed

Choosing a cookie preference is a consent choice, not a form submission. It sends no
personal data, and it happens in a throwaway headless profile that is deleted afterwards.
Click only the Accept (or Reject) control **inside the cookie/consent container**. Never
click anything inside a `<form>`, never tick other boxes, never type, never log in.
The consent platform may record the choice server-side (a consent log entry for an
anonymous visitor). That is accepted; note it in the run log.

## How the script identifies the control (`consent_capture.js`)

At most **one click per phase**, on exactly the element identified, and only if all of these hold:

- **Container.** The control sits inside an ancestor (the nearest one that qualifies) which is
  one of:
  - a **named container**: id, class or aria-label matches
    `cookie|consent|gdpr|onetrust|didomi|usercentrics|trustarc|iubenda|osano|termly|cookiebot|\bcmp\b`
    (case-insensitive; `CONSENT_NAMED` in `_common.js`);
  - a **privacy-named container**: id or class matches `privacy`, **and** the container's own
    text matches `cookie|consent|tracking`. "privacy" alone (a privacy-policy or account notice)
    never qualifies;
  - a **dialog**: `[role=dialog]`, `[role=alertdialog]`, `[aria-modal=true]` or `<dialog>`.

  In every case the container's text must also match `cookie|consent|tracking`. The
  walk up from the control stops before `body`, `html` and `main`; those are never accepted,
  and neither is any wrapper taller than 0.8 × the page's scroll height (an app or page shell).
  A bare dialog (newsletter, age gate, terms) never counts.
- **Element.** A visible, enabled `button`, `[role=button]`, `a` or `input[type=button]`. Excluded:
  anything with a form owner (`e.form`, including `form="…"`-associated buttons) or inside a
  `<form>`, and links that navigate away (an `href` other than empty, `#…` or `javascript:`;
  those three stay allowed because consent platforms use them for their buttons).
- **Container contents.** If the container holds a text/email/other input, a textarea or a
  CAPTCHA frame, nothing is clicked and the phase is `blocked`. Category checkboxes are fine
  (they are never ticked).
- **Label.** The visible label (or aria-label/value) is whitespace-collapsed, trimmed and
  stripped of a trailing `.` or `!`, then must match the **whole** pattern, case-insensitive.

Default labels (these are the script's regexes, character for character):

- **Accept** (`--accept`):
  `^(accept|accept all|accept all cookies|accept cookies|allow all|allow all cookies|allow cookies|i accept|got it|ok|ok, got it|agree and close)$`
  matches Accept · Accept all · Accept all cookies · Accept cookies · Allow all · Allow all
  cookies · Allow cookies · I accept · Got it · OK · OK, got it · Agree and close.
- **Accept, named container only**: `^(agree|i agree)$`
  matches Agree · I agree, only in a named container (not privacy-named, not a dialog).
- **Reject** (`--reject`):
  `^(reject|reject all|reject all cookies|reject cookies|decline|decline all|necessary only|only necessary|only necessary cookies|essential only|deny|deny all)$`
  matches Reject · Reject all · Reject all cookies · Reject cookies · Decline · Decline all ·
  Necessary only · Only necessary · Only necessary cookies · Essential only · Deny · Deny all.

Not matched on purpose: bare "Allow" (permission prompts), "Accept terms", "Subscribe",
"Cookie settings" / "Manage preferences" (second layer, not a choice). A site with other
wording: pass `--accept` / `--reject` with the exact labels, anchored the same way.

## Steps

Default widths are **375 and 1366** (`--width`); mobile banners are often a different component.
Each URL and width runs two phases, each in its own fresh profile:

1. **Pre-consent**: load and wait, with no interaction. Record:
   - all cookies (CDP `Network.getAllCookies`)
   - localStorage and sessionStorage keys
   - request hostnames
   - Google Consent Mode signals: any `gcs` / `gcd` parameter on requests (host + value)
   - tracking vendors present (analytics/ads categories), as `preConsentTracking`
2. **Accept phase**: click the Accept control, load the page afresh (not a browser reload,
   which could repeat a blocked request), record again. Diff to get new hosts,
   cookies and storage keys. No control found: `postConsentBlocked (no accept control found…)`.
3. **Reject phase** (on by default; `--no-reject` skips it, never for sites serving visitors where consent law requires a reject option, such as the UK and EU):
   fresh profile, click the Reject control, load the page afresh, record. The `reject` object holds its own
   `navigation`, `preReject` and `postReject` snapshots, `nonGetRequests` and `mixedContent`,
   and:
   - `trackersBeforeClick`: analytics/ads vendors already present before any click. These are
     the **pre-consent finding** and are reported separately; Reject can't be blamed for them.
   - `trackersAfterReject`: analytics/ads vendors seen after the reload.
   - `newTrackersAfterReject`: vendors after Reject that were not there before the click.
   - `trackerCookiesAfterReject`: analytics/ads cookies (by name prefix) that are new after
     Reject or were re-set (exact expiry changed), with `alreadySetBeforeClick`. A re-set
     session cookie can't be detected this way; check it by hand.
   - `rejectHonoured`: true only if `newTrackersAfterReject` is empty **and** no analytics/ads
     cookie was set after Reject. `null` when there was no Reject click or no reload.
   No Reject on the first layer = `reject: blocked`, and that is itself a reading point (below).
   If the reload after a click fails, the phase keeps what it collected (`error` plus the
   pre-click snapshot) and the script exits 1.
4. **Policy comparison** (`--policy URL`): load the privacy/cookie page once. For every vendor
   detected (via a host or cookie-prefix map), check whether the policy names it. Report
   `mentioned` / `NOT mentioned`.
5. **Egress region**: pass `--egress CC` with the lead machine's egress country if known (from the run
   environment or the user); otherwise it records `unknown`. The scripts never call a geo-IP
   service. Consent platforms geo-target, so record it in the run log and, when it differs from
   the client's market, list "consent behaviour from a non-<market> region" as a coverage limit.
6. **Executor check (human walk)**: withdraw consent via the site's "Cookie settings" link after
   accepting, reload, and confirm trackers stop (check the banner/settings state and, where the
   browser UI shows it, the site's cookies). Coverage row: `consent withdrawal`.

`nonGetRequests` and `mixedContent` are logged for information (the page's own JS beacons;
nothing is blocked, since blocking would break the measurement).

## Severity mapping (feeds qa-standards §2)

The standards make any "security or privacy exposure" S1. For consent evidence this skill
defines what counts as an exposure, so two leads rate the same evidence the same way:

| Evidence before consent (or after Reject) | Severity | Label |
|---|---|---|
| Personal data or a persistent identifier sent to an advertising vendor (ads pixel with a click/user ID cookie, `_fbp`, `_gcl_*`, LinkedIn/TikTok tags) | S1 privacy exposure | DET+JUDG |
| Non-essential analytics cookies/identifiers set (`_ga`, `ph_*`, `_hj*`, `_clck`) or analytics loaded with identifiers | S2 (raise to S1 if special-category or account data is involved) | DET+JUDG |
| Reject not honoured (`rejectHonoured: false`: new trackers or analytics/ads cookies set after Reject) | as the two rows above | DET+JUDG |
| Trackers already running before any click (`preConsentTracking`, `reject.trackersBeforeClick`) | the pre-consent rows above; one finding, not repeated as a Reject finding | DET+JUDG |
| Consent Mode cookieless pings (`gcs=G100`/`G1--` style, no `_ga`/ads cookie set) | S4 transparency item: name it in the policy | DET |
| No Reject on the first layer, or Reject much less prominent than Accept (UK/EU-facing) | S3 | JUDG |
| Vendor loads after Accept but is missing from the policy; or policy lists vendors that never load | S3 / S4 policy mismatch | DET+JUDG |
| Geo-targeted site seen from another region | not rated; coverage limitation | — |

Jurisdiction can lower a row only with a stated reason (e.g. a US-only site with no EU
audience), and the reason goes in the finding.

## Reading the result

- Proxied first-party analytics shows up only as cookies or storage keys, not as a
  third-party host. Identify it by cookie prefix.
- Advertising pixels (search ads, AI-platform ads, social) after Accept need to be named in
  the policy and banner text.
- Reject must be reachable on the first layer with equal prominence (UK/EU).

## Privacy of the evidence

Cookie and storage names and clicked labels are redacted (email addresses become `<email>`;
token-like values of 20+ characters containing digits, such as project keys and session IDs,
are cut). Page URLs are stored without query string or fragment; for requests only hosts are
stored, never full request URLs.
Consent Mode values (`gcs`, `gcd`) are consent-state codes, not identifiers. Never copy raw
cookie values, IDs or keys into the report. Name the cookie or vendor only.
