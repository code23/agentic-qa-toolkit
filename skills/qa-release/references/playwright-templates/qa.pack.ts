/**
 * Per-project QA pack config (default test suite).
 *
 * ONE source of truth for which templates/pages the tier-3 specs cover — the
 * first-paint, a11y and global-chrome specs import from here, so the lists cannot drift.
 * Forks customise THIS file (paths, heading matchers, CTA names, seed slugs) instead
 * of editing the specs: "don't weaken assertions or drop journeys — update the pack
 * when the product surface changes."
 *
 * Prefer stable public routes; add seeded detail pages only when the slug comes from
 * config/fixtures (a commented-out example rots forever).
 */

export interface KeyTemplate {
  /** Route to load. */
  path: string;
  /** Must match the visible H1. */
  heading: RegExp;
  /** Accessible name of the primary CTA that must be visible with zero interaction. */
  cta: RegExp;
}

export const KEY_TEMPLATES: KeyTemplate[] = [
  { path: '/', heading: /your product name/i, cta: /start|browse|sign up|get started/i },
  // { path: '/search', heading: /results|browse/i, cta: /view|filter/i },
];

/** Selectors of third-party roots excluded from the a11y scan (cookie banners,
 * chat widgets, embeds) — reviewed, not a dumping ground. */
export const A11Y_EXCLUDE: string[] = [
  // '#cookie-banner',
];

/** Known, ticketed axe violation ids tolerated while being fixed. New ids fail CI. */
export const A11Y_ALLOWLIST: string[] = [];

export interface GlobalChromePage {
  path: string;
  kind: 'content' | 'intent';
  /** Whether this page is expected to render a breadcrumb landmark. */
  hasBreadcrumb: boolean;
  /** Primary action checked for visibility and cookie-banner overlap. */
  primaryAction?: RegExp;
}

/**
 * Keep at least one content/legal page and one highest-intent public page. The
 * global-chrome spec fails its own configuration if either class is missing.
 */
export const GLOBAL_CHROME_PAGES: GlobalChromePage[] = [
  { path: '/privacy', kind: 'content', hasBreadcrumb: true },
  {
    path: '/',
    kind: 'intent',
    hasBreadcrumb: false,
    primaryAction: /start|browse|sign up|get started/i,
  },
];

/** Adapt selectors and tokens here; do not weaken assertions in the spec. */
export const GLOBAL_CHROME = {
  header: 'header',
  mainHeading: 'h1',
  breadcrumb: 'nav[aria-label="Breadcrumb"]',
  footer: 'footer',
  cookieBanner: '[data-testid="cookie-consent-banner"]',
  brandScope: '[data-brand]',
  cookieSurfaceToken: '--brand-surface',
  cookieActionToken: '--brand-primary',
  acceptButton: /accept all/i,
  dismissButton: /reject all|only necessary|decline/i,
  mobileMenuButton: /menu/i,
} as const;
