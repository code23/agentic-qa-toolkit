# Conversion path pass (per template)

For each template, take one representative page at desktop and mobile. **Owners**: the
executor collects what needs interactive browsing (the PER TEMPLATE line in the preamble);
the lead runs the scripts and computes distances, parity and dead ends.

1. **Distance to next CTA** (lead): use `viewport_overflow.js` (`firstCtaScreens`,
   `maxGapScreensBetweenCtas`; in-content CTAs only, matched on whole words in the label or
   link path; the last gap runs to the top of the footer). Pass `--cta REGEX` for the site's
   own CTA wording. Long gaps on long pages are a UX judgement, not a defect.
2. **Dead ends** (executor records the onward links at the end of each page; lead judges):
   pages where the only onward route is the global nav or footer. Common culprits are case
   studies, blog posts, legal pages, thank-you or 404 pages, and filtered lists with no results.
3. **Offer parity** (lead): compare desktop and mobile copy for price, offer, guarantee and
   availability. Main method: the `parity` block of `viewport_overflow.js` (visible text lines
   seen at the narrow width but not the wide one and vice versa, with lines holding prices,
   percentages or numbers listed first). `copy_freshness.py` → `breakpoint-copy-differs` is a
   **Tailwind-class heuristic only** (`sm:/md:/lg:hidden`, `hidden md:block`); it finds nothing
   on Bootstrap, custom media queries or CSS-in-JS. An offer shown on only one breakpoint is a
   real finding when the offer drives the conversion.
4. **Contact-route clarity** (executor records clicks-to-contact and the promises; lead
   judges): how many steps from any page to contact, and whether the form, email, phone and
   booking options agree with each other. Check what the user is promised (response time,
   office hours, timezone label). Form checks follow the Safety rules in SKILL.md:
   - Typing into the form IS part of the test. Type only obvious test data ("QA Test",
     qa-test@example.com, "This is a QA test, please ignore") to exercise validation, field
     types, error messages, input masks and length limits.
   - NEVER press submit/send or otherwise trigger submission: no Enter in single-field forms,
     no "Next" that sends data, nothing that auto-submits.
   - Guardrail FIRST: before typing into a live form, watch the network requests while typing
     a single harmless character into one field and then moving focus away. If any request
     carries field data (autosave, partial lead capture, HubSpot/Typeform-style partials), stop
     that form, clear the field, and ask the user before continuing. Mark it
     `blocked (safety rule: save-as-you-type)` until they answer. The executor may watch requests
     in the browser's own developer-tools Network panel (opened from the UI, closed before
     screenshots). If requests cannot be observed, do not type into that form: mark it
     `blocked (save-as-you-type check not possible)`.
   - Clear all fields afterwards.
   - Card/payment, phone/SMS code, ID or CAPTCHA fields: never type; stop and ask.
   - Scripts never type into forms.
5. **Nav parity** (executor records the desktop nav link list and the opened mobile-menu link
   list; lead diffs them): does the mobile menu contain the same key destinations as desktop?
   Typical miss: a key page reachable on desktop but absent from the mobile menu.
6. **Funnel data** (only if product analytics is granted under the field-data exception):
   funnel drop-off per template, aggregate only. Never open individual sessions or users.

Report these in the UX section, labelled JUDG unless they are deterministic (missing link,
differing offer text).
