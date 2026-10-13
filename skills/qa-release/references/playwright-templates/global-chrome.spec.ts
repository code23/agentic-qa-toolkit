import { expect, type Locator, type Page, test } from '@playwright/test';
import { GLOBAL_CHROME, GLOBAL_CHROME_PAGES } from './qa.pack';

/**
 * Global chrome geometry + active-brand guarantee (default suite, tier 3).
 *
 * Run against a production-mode build. Each test gets a clean browser context, so the
 * consent banner is observed before any preference is stored. Screenshots supplement
 * deterministic geometry/token assertions; they do not replace them.
 */

const VIEWPORTS = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'desktop', width: 1440, height: 1000 },
] as const;

test('global chrome pack covers content and intent pages', () => {
  expect(GLOBAL_CHROME_PAGES.some((page) => page.kind === 'content')).toBe(true);
  expect(GLOBAL_CHROME_PAGES.some((page) => page.kind === 'intent')).toBe(true);
});

for (const viewport of VIEWPORTS) {
  test(`global chrome: ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);

    const firstPage = GLOBAL_CHROME_PAGES[0];
    if (!firstPage) throw new Error('GLOBAL_CHROME_PAGES must not be empty');
    await gotoChecked(page, firstPage.path);

    const banner = page.locator(GLOBAL_CHROME.cookieBanner);
    await expect(banner, 'first-visit consent banner').toBeVisible();
    await assertActiveBrandTokens(page, banner);
    await assertNoPrimaryActionOverlap(page, banner, firstPage.primaryAction);
    await page.screenshot({ path: testInfo.outputPath(`cookie-${viewport.name}.png`) });

    await page.getByRole('button', { name: GLOBAL_CHROME.dismissButton }).click();
    await expect(banner).toBeHidden();

    for (const target of GLOBAL_CHROME_PAGES) {
      await gotoChecked(page, target.path);
      const responseHeading = page.locator(GLOBAL_CHROME.mainHeading).first();
      const header = page.locator(GLOBAL_CHROME.header).first();
      await expect(header, `${target.path} header`).toBeVisible();
      await expect(responseHeading, `${target.path} H1`).toBeVisible();
      await assertBelowHeader(header, responseHeading, `${target.path} H1`);

      if (target.hasBreadcrumb) {
        const breadcrumb = page.locator(GLOBAL_CHROME.breadcrumb).first();
        await expect(breadcrumb, `${target.path} breadcrumb`).toBeVisible();
        await assertBelowHeader(header, breadcrumb, `${target.path} breadcrumb`);
      }

      if (target.primaryAction) {
        await expect(primaryAction(page, target.primaryAction)).toBeVisible();
      }

      await page.screenshot({
        path: testInfo.outputPath(`${target.kind}-${viewport.name}-top.png`),
      });
    }

    const intentPage = GLOBAL_CHROME_PAGES.find((target) => target.kind === 'intent');
    if (!intentPage) throw new Error('GLOBAL_CHROME_PAGES must include an intent page');
    await gotoChecked(page, intentPage.path);
    await page.evaluate(() => window.scrollTo(0, Math.min(700, document.body.scrollHeight)));
    await page.screenshot({ path: testInfo.outputPath(`header-${viewport.name}-scrolled.png`) });

    if (viewport.name === 'mobile') {
      const menuButton = page.getByRole('button', { name: GLOBAL_CHROME.mobileMenuButton });
      await expect(menuButton, 'mobile menu button').toBeVisible();
      await menuButton.click();
      await page.screenshot({ path: testInfo.outputPath('mobile-menu-open.png') });
    }

    const footer = page.locator(GLOBAL_CHROME.footer).first();
    await footer.scrollIntoViewIfNeeded();
    await expect(footer).toBeVisible();
    const footerLinks = footer.getByRole('link');
    expect(await footerLinks.count(), 'footer has no links').toBeGreaterThan(0);
    for (const link of await footerLinks.all()) {
      await expect(link).toBeVisible();
      const href = await link.getAttribute('href');
      expect(href, 'footer link has no destination').toBeTruthy();
      expect(href).not.toBe('#');
    }
    await page.screenshot({ path: testInfo.outputPath(`footer-${viewport.name}.png`) });
  });
}

async function assertBelowHeader(header: Locator, target: Locator, label: string): Promise<void> {
  const headerBox = await header.boundingBox();
  const targetBox = await target.boundingBox();
  if (!headerBox) throw new Error(`${label}: missing header geometry`);
  if (!targetBox) throw new Error(`${label}: missing target geometry`);
  expect(targetBox.y, `${label} intersects fixed/sticky header`).toBeGreaterThanOrEqual(
    headerBox.y + headerBox.height,
  );
}

async function assertActiveBrandTokens(page: Page, banner: Locator): Promise<void> {
  const action = page.getByRole('button', { name: GLOBAL_CHROME.acceptButton });
  await expect(action).toBeVisible();

  const expectedStyles = await banner.evaluate(
    (element, config) => {
      const scope = element.closest(config.brandScope) ?? document.querySelector(config.brandScope);
      if (!(scope instanceof HTMLElement)) return null;

      const probe = document.createElement('span');
      scope.append(probe);
      probe.style.backgroundColor = `var(${config.surfaceToken})`;
      const expectedSurface = getComputedStyle(probe).backgroundColor;
      probe.style.backgroundColor = `var(${config.actionToken})`;
      const expectedAction = getComputedStyle(probe).backgroundColor;
      probe.remove();

      return {
        actualSurface: getComputedStyle(element).backgroundColor,
        expectedSurface,
        expectedAction,
      };
    },
    {
      brandScope: GLOBAL_CHROME.brandScope,
      surfaceToken: GLOBAL_CHROME.cookieSurfaceToken,
      actionToken: GLOBAL_CHROME.cookieActionToken,
    },
  );

  if (!expectedStyles) {
    throw new Error('cookie banner is outside the configured active brand scope');
  }
  const actualAction = await action.evaluate(
    (element) => getComputedStyle(element).backgroundColor,
  );
  expect(expectedStyles.expectedSurface, 'cookie surface token did not resolve').not.toBe('');
  expect(expectedStyles.expectedAction, 'cookie action token did not resolve').not.toBe('');
  expect(expectedStyles.actualSurface).toBe(expectedStyles.expectedSurface);
  expect(actualAction).toBe(expectedStyles.expectedAction);
}

async function assertNoPrimaryActionOverlap(
  page: Page,
  banner: Locator,
  actionName: RegExp | undefined,
): Promise<void> {
  if (!actionName) return;
  const action = primaryAction(page, actionName);
  await expect(action).toBeVisible();
  const bannerBox = await banner.boundingBox();
  const actionBox = await action.boundingBox();
  if (!bannerBox) throw new Error('cookie banner has no measurable geometry');
  if (!actionBox) throw new Error('primary action has no measurable geometry');
  expect(boxesOverlap(bannerBox, actionBox), 'cookie banner obscures primary action').toBe(false);
}

async function gotoChecked(page: Page, path: string): Promise<void> {
  const response = await page.goto(path, { waitUntil: 'load' });
  if (!response) throw new Error(`${path} did not return an HTTP response`);
  expect(response.status(), `${path} returned an error response`).toBeLessThan(400);
}

function primaryAction(page: Page, name: RegExp): Locator {
  const main = page.getByRole('main');
  return main.getByRole('link', { name }).or(main.getByRole('button', { name })).first();
}

function boxesOverlap(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number },
): boolean {
  return !(
    a.x + a.width <= b.x ||
    b.x + b.width <= a.x ||
    a.y + a.height <= b.y ||
    b.y + b.height <= a.y
  );
}
