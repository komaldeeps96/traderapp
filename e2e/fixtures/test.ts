/**
 * Test fixtures.
 *
 * `test` gives every spec a terminal page object plus a scripted backend,
 * already installed and navigated. `liveTest` skips the mocking and drives the
 * real stack instead.
 */

import { test as base, expect } from '@playwright/test';

import type { Page } from '@playwright/test';

import { TerminalPage } from '../pages/TerminalPage';

import { installMockBackend, type MockBackend, type MockBackendOptions } from './mockBackend';

interface Fixtures {
  terminal: TerminalPage;
  backend: MockBackend;
  /** Per-spec overrides, set with `test.use({ backendOptions: {...} })`. */
  backendOptions: MockBackendOptions;
}

export const test = base.extend<Fixtures>({
  backendOptions: [{}, { option: true }],

  backend: async ({ page, backendOptions }, use) => {
    const backend = await installMockBackend(page, backendOptions);
    await use(backend);
  },

  terminal: async ({ page, backend }, use) => {
    // Depending on `backend` guarantees interception is installed before the
    // first navigation; otherwise the app would race it and hit the network.
    void backend;
    await reduceMotion(page);
    const terminal = new TerminalPage(page);
    await terminal.goto();
    await use(terminal);
  },
});

/** Drives the real backend, with no interception. */
export const liveTest = base.extend<{ terminal: TerminalPage }>({
  terminal: async ({ page }, use) => {
    await reduceMotion(page);
    const terminal = new TerminalPage(page);
    await terminal.goto();
    await use(terminal);
  },
});

export { expect };

/**
 * Collapse every CSS transition, which the app already does under
 * `prefers-reduced-motion`.
 *
 * The accessibility scan needs it: axe reads computed colours, so a scan that
 * lands mid-theme-switch sees blended values and reports contrast failures
 * against colours no user ever sees. Set here rather than in the config's
 * `use` block, where it is silently dropped — verified by reading
 * `matchMedia` from the page.
 */
async function reduceMotion(page: Page): Promise<void> {
  await page.emulateMedia({ reducedMotion: 'reduce' });
}
