# Viewport matrix (lead-side, headless)

Runs alongside the executor's human walk. It does not replace it.

## Widths

| Width | Represents | Emulation (script default) |
|---|---|---|
| 320 | Smallest phones and zoomed views. Overflow + WCAG 1.4.10 reflow proxy | mobile + touch |
| 375 | Typical phone | mobile + touch |
| 768 | Portrait tablet | touch |
| 1024 | Landscape tablet or small laptop | touch |
| 1440 | Desktop | none |
| Optional: `844x390` | Landscape phone (sticky headers and banners can fill the screen) | mobile + touch |
| Optional: 1280, 1920 | Common laptop, large desktop | none |

Rules in the script: mobile below 768 or for a short landscape size (height < 500 and less
than the width); touch up to and including 1024. Mobile widths use an Android Chrome user
agent, others desktop Chrome. Pass `--viewports 320,375,844x390,768,1024,1280,1440,1920` for
the full set. `--no-mobile` turns off mobile and touch emulation at every width (the desktop
probe used to re-check overflow).

Use one representative URL per template, plus the home page and the highest-intent page
(pricing, contact or booking). Run `viewport_overflow.js`, which uses a fresh profile per URL
and width and never clicks anything. Each result records its `emulation`, `navigation`
(status, final URL), `consentState` (always pre-consent: banner not dismissed) and whether a
consent banner was visible. The dismissed-banner state is covered by the executor's global
chrome gate, not by this script.

## What to record

- `overflowPx` is document width minus viewport width. `actualScrollX` is how far the page
  really scrolls sideways after `scrollTo(10000, 0)`. **Mobile emulation can report
  `scrollX 0` while `overflowPx > 0`**, because the viewport clips. Treat this as "content
  wider than the screen". Report it, but rate it on what a user actually sees: re-check
  with `--no-mobile` at the same width and look at the screenshot.
- `offenders` are the widest elements that pass the right edge, excluding elements clipped by
  an `overflow:hidden/clip` ancestor (counted in `clippedWideElements` instead). Common causes:
  100vw children inside a padded container, marquees and tickers, wide tables and code blocks,
  and negative margins on decorative shapes.
- Header clearance. The header is the outermost fixed or sticky full-width bar at the top of
  the page (any element, not only `<header>`; consent banners are excluded):
  - `headerClearsH1`, `headerClearsBreadcrumb`, `headerClearsFirstControl`: whether each
    element's top sits at or below the header bottom.
  - `breadcrumbInHeader`: breadcrumbs absorbed into the nav row (qa-standards §6).
  - **`null` means "not measured"** (no fixed/sticky header, or no such element). Check by hand.
- CTA spacing (in-content only; header, nav, footer and consent CTAs are excluded; matched on
  whole words in the label or link path):
  - `firstCtaScreens`: how many screens down the first CTA sits.
  - `maxGapScreensBetweenCtas`: the longest stretch without one, the last gap measured to the
    top of the footer. More than about 4 screens on a long landing page is worth a UX note.
    This is a judgement call, not a defect.
- `renderedWords` and `root`: rendered main-content word count, for the served-vs-rendered
  preflight (`--rendered` in the Python content scripts). Counted on the same root and
  exclusions as the served count: `<main>`, else `<body>` minus every header/nav/footer/aside.
- A navigation that times out (network never idle) is measured only when the target origin's
  document is there with some body text (`navigation.warning`); otherwise it is a failure.
- `parity` (per URL): visible text lines at the narrowest width ≥ 360 vs the widest width;
  lines with prices, percentages or numbers come first. Feeds offer parity in the conversion
  pass. Line breaks can differ with layout, so read the lines before rating.

## Why these widths

- A site can be clean at 375 and 1440 and still scroll sideways at 1024. A walk that covers
  only desktop and phone misses it. Always include the 768–1024 band.
- At 320, mobile emulation can report overflow with no actual scroll while the `--no-mobile`
  probe does scroll. Report both numbers.

## Limits

These widths are emulated, not physical devices. Safari/iOS rendering, real touch, the
on-screen keyboard, notches and dynamic toolbars are not covered. Mark them "not covered
(physical device)" unless the human walk used a real device.
