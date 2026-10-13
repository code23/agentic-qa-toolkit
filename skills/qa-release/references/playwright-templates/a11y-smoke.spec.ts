import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { A11Y_ALLOWLIST, A11Y_EXCLUDE, KEY_TEMPLATES } from './qa.pack';

/**
 * Accessibility smoke (default test suite, tier 3).
 *
 * Fails on NEW serious/critical axe-core violations on key templates. Deterministic
 * evidence, not a WCAG audit — the qa-site-audit skill owns the full pass.
 *
 * - Known third-party roots (cookie banner, chat widget) are excluded via qa.pack —
 *   their violations are not app regressions and would only train people to ignore red.
 * - Pre-existing, ticketed violations sit in A11Y_ALLOWLIST so retrofit repos can
 *   adopt the gate immediately; a NEW violation id still fails. Shrink the allowlist,
 *   never grow it silently.
 * - Moderate/minor counts are logged (annotations) but non-blocking.
 * - Pin @axe-core/playwright — impact taxonomy changes between majors.
 */

for (const { path } of KEY_TEMPLATES) {
  test(`a11y smoke: ${path}`, async ({ page }) => {
    await page.goto(path, { waitUntil: 'load' });
    await page.waitForTimeout(1_000); // post-hydration DOM is what users get

    // wcag22aa does NOT subsume the 2.1 tags — list them explicitly.
    let builder = new AxeBuilder({ page }).withTags([
      'wcag2a',
      'wcag2aa',
      'wcag21a',
      'wcag21aa',
      'wcag22aa',
    ]);
    for (const sel of A11Y_EXCLUDE) builder = builder.exclude(sel);
    const results = await builder.analyze();

    const serious = results.violations.filter((v) =>
      ['serious', 'critical'].includes(v.impact ?? ''),
    );
    const newViolations = serious.filter((v) => !A11Y_ALLOWLIST.includes(v.id));
    const lesser = results.violations.length - serious.length;
    test.info().annotations.push({
      type: 'a11y-summary',
      description: `${serious.length} serious/critical (${newViolations.length} new), ${lesser} lesser`,
    });

    expect(
      newViolations,
      newViolations
        .map((v) => `${v.id} (${v.impact}): ${v.nodes.length} node(s) — ${v.helpUrl}`)
        .join('\n'),
    ).toEqual([]);
  });
}
