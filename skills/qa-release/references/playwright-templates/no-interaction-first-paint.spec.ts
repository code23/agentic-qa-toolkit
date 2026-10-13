import { expect, test } from '@playwright/test';
import { KEY_TEMPLATES } from './qa.pack';

/**
 * No-interaction first-paint guarantee (default test suite, tier 3).
 *
 * Loads each key template with ZERO user input and asserts the primary content is
 * VISIBLE — not merely present in the DOM. Catches the "invisible until first interaction" class of defect:
 * optimizers or animation frameworks (delayed-JS, rAF hijacking, reveal-on-scroll
 * held at opacity/visibility) leaving content invisible for every no-interaction
 * consumer — Googlebot's renderer, PageSpeed/Lighthouse, link-preview generators,
 * and a mobile user's first paint before they touch anything.
 *
 * Mechanics (each guards a known false-pass/false-fail mode):
 * - Wait for 'load' AND re-assert after a settle: SSR HTML can show the H1 briefly
 *   before client scripts hide it for a reveal animation — asserting too early
 *   false-passes exactly the bug class this spec exists for.
 * - Playwright's toBeVisible() rejects display:none / visibility:hidden / empty box
 *   but treats opacity:0 as visible — so we ALSO assert computed visibility and
 *   opacity on the H1 directly.
 * - The CTA check targets a NAMED control inside main content; "any link visible"
 *   would false-pass on a nav logo while the main column stays blank.
 */

/**
 * Scope note: run in the repo against a PRODUCTION-MODE build where feasible. This
 * spec guards the APP-level failure class (reveal animations, hydration hiding
 * content). Optimizer/CDN-injected failures (NitroPack et al.) only exist on the
 * live site — the tier-4 production canary is the actual guard for optimizer-caused hiding.
 */
for (const { path, heading, cta } of KEY_TEMPLATES) {
  test(`first paint with zero interaction: ${path}`, async ({ page }) => {
    const response = await page.goto(path, { waitUntil: 'load' });
    if (!response) throw new Error(`no response for ${path}`);
    expect(response.status(), `non-2xx for ${path}`).toBeLessThan(400);
    // Deliberately NO input of any kind before or between the assertions.
    const h1 = page.getByRole('heading', { level: 1 });
    await expect(h1).toBeVisible({ timeout: 10_000 });
    await expect(h1).toContainText(heading);

    // Settle, then re-assert: post-hydration optimizer/animation state is the truth.
    await page.waitForTimeout(2_000);
    await expect(h1).toBeVisible();
    await expect
      .poll(async () =>
        h1.evaluate((el) => {
          const cs = getComputedStyle(el);
          return { visibility: cs.visibility, opacity: Number(cs.opacity) };
        }),
      )
      .toEqual(expect.objectContaining({ visibility: 'visible' }));
    const style = await h1.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { visibility: cs.visibility, opacity: Number(cs.opacity) };
    });
    expect(style.opacity).toBeGreaterThan(0.9);

    // Primary CTA reachable without interaction, inside the main content region.
    await expect(
      page
        .getByRole('main')
        .getByRole('link', { name: cta })
        .or(page.getByRole('main').getByRole('button', { name: cta }))
        .first(),
    ).toBeVisible();
  });
}
