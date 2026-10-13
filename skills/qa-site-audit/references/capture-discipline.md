# Capture discipline and false-positive patterns

## Before any screenshot

1. Load, then let the page settle. What the scripts actually do (`settle()` in `_common.js`):
   - wait up to 6 s for running **finite CSS / Web-Animations** to finish;
   - then wait for a **DOM quiet period** (no mutations for 1 s, capped at 6 s), which also
     catches JS-driven typewriters, count-ups and reveals that the Animations API can't see;
   - then 500 ms.
   `viewport_overflow.js` also **step-scrolls** the page in viewport-height steps with a 1 s
   pause (so IntersectionObserver reveals and lazy images fire), returns to the top and
   settles again before measuring. `--reduced-motion` emulates `prefers-reduced-motion:
   reduce`, which often shows the final state; use it as a second capture when animation is
   in doubt.
   Limits: an infinite animation (marquee, looping video) never "finishes"; requestAnimationFrame
   loops that only change canvas or transforms without DOM mutations are not detected. Treat
   anything moving in a shot as unsettled.
2. After scrolling, pause about 1 s so lazy images, fade-ins and sticky-header transitions
   can complete (longer if anything is still moving).
3. Note the CSS viewport, scroll Y and consent state (banner shown / accepted / rejected /
   not shown). The scripts record these per result.
4. For anything that looks blank, see-through or missing an image: two shots ~2 s apart.
5. Shoot only the target page.

The executor gets these rules in the CAPTURE block of the preamble in SKILL.md.

## When a visual finding is verified

A visual finding becomes `evidence-reviewed` (qa-standards §3) when either:

- an **independent re-check** agrees: headless (DOM presence, computed style such as
  opacity/visibility/colour, bounding boxes at the same width and scroll position, the served
  HTML) or a second executor capture after settling; or
- the **lead judges** the screenshot unambiguous and it matches none of the patterns below.
  This is the route for states that can't be re-checked headless: hover, focus, an opened
  executor-only menu, physical-device results, logged-in shells.

Otherwise it stays `provisional`. Two shots from the same mid-transition moment are not an
independent check. If a re-check can't reproduce the finding, keep it provisional or drop it,
and say which. `independently-reproduced` still needs a reproduction (fresh session or
deterministic tooling).

## False-positive patterns

| Looks like | Actually | How to tell |
|---|---|---|
| A blank or black section | Content mid-fade (scroll-triggered reveal) | Re-shoot after settle. Check that the elements exist with opacity going to 1 |
| A missing cover or hero image | A deliberate decorative colour band | No `<img>` or background-image is expected there. Check the template and sibling pages |
| Duplicated or repeated text | An `aria-hidden` marquee or ticker (cloned for looping) | `aria-hidden="true"` on the clone. Screen readers hear it once |
| A see-through sticky header in one shot | A scroll transition captured mid-way | Scroll, settle, re-shoot, and read the computed background |
| A "Debug" label in the DOM | A hidden debug element injected by script | Visible? In the served HTML or injected? A hidden one is a low-severity hygiene item, not a broken UI |
| A "staging" or "test" word hit | Product mock-up copy (e.g. a screenshot of a UI that shows "Staging") | Read the context before raising it |
| A console error on a 404 page | The 404 page's own 404 status | Expected. Ignore it |
| Sideways scroll at 320 | Mobile emulation clips (`scrollX 0`) while `overflowPx > 0` | Re-run with `--no-mobile` and look at the edge |
| A wide element in `offenders` | Clipped by an `overflow:hidden/clip` ancestor | The script already excludes these (`clippedWideElements` counts them) |
| Analytics vendor missing from network hosts | First-party proxied analytics | Look for vendor cookie prefixes (e.g. `ph_`, `_ga`) as well as hosts |
| Google Analytics hits before consent | Consent Mode cookieless pings | `gcs`/`gcd` parameters and no `_ga` cookie: see the severity mapping in `consent-and-privacy.md` |
| Two near-identical pages | Empty or client-rendered `<main>` in the served HTML | `similarity.py` marks these `inconclusive`; check `words` and `coverage` |
| An image with empty alt flagged as missing alt | `alt=""` on a decorative image | Correct practice. Only flag informative images |
