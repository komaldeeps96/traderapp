import { defineConfig, devices } from '@playwright/test';

/**
 * Two suites, one config.
 *
 *  - `tests/mocked` runs the real frontend bundle against a scripted backend
 *    served by Playwright's network interception. Fast, deterministic, and
 *    able to force states the live stack cannot — a dropped socket, a delayed
 *    feed, a symbol with no data. Runs on all three engines.
 *
 *  - `tests/fullstack` runs the real backend, real providers and real
 *    indicator maths, with only Alpaca's HTTP endpoint replaced by a fixture
 *    server. That is what proves the two halves actually agree.
 *
 * Everything starts itself: `npm run test:e2e` needs no running servers, no
 * credentials, and no open market.
 */

// Every e2e server lives on its own port, away from the development stack:
// the dev backend on 8000 and the Vite dev server on 3000 must survive a
// test run untouched. The test frontend is likewise built to `dist-e2e`,
// pointed at the test backend, so the production `dist/` bundle is never
// overwritten with test-only URLs.
const FRONTEND_URL = process.env.E2E_FRONTEND_URL ?? 'http://127.0.0.1:4173';
const BACKEND_URL = process.env.E2E_BACKEND_URL ?? 'http://127.0.0.1:8100';
const FIXTURE_URL = 'http://127.0.0.1:9899';
const isCI = !!process.env.CI;

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  // Two everywhere, not just in CI. Left undefined, Playwright picks half
  // the cores — four on this machine — and each worker is a whole browser
  // holding a chart. On a 16GB laptop that is enough to exhaust memory: a
  // run at the default count took the load average past 250 and ended in a
  // kernel panic with the VM compressor at 100% of its page limit. The
  // suite finishes in about a minute either way; the headroom is worth far
  // more than the seconds.
  workers: 2,
  timeout: 45_000,
  expect: { timeout: 10_000 },

  reporter: isCI
    ? [['github'], ['html', { open: 'never' }], ['list']]
    : [['html', { open: 'never' }], ['list']],

  use: {
    baseURL: FRONTEND_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    timezoneId: 'America/New_York',
    locale: 'en-US',
  },

  projects: [
    {
      name: 'chromium',
      testDir: './tests/mocked',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'firefox',
      testDir: './tests/mocked',
      use: { ...devices['Desktop Firefox'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'webkit',
      testDir: './tests/mocked',
      use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 900 } },
    },
    {
      // A trading terminal is a desktop tool, but the layout should not
      // collapse if it is opened on a tablet.
      name: 'mobile',
      testDir: './tests/responsive',
      use: { ...devices['iPad (gen 7) landscape'] },
    },
    {
      // Pixel baselines are per-engine; keeping them to one avoids three sets
      // of screenshots that all need regenerating.
      name: 'visual',
      testDir: './tests/visual',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      // The README's images. Skipped unless TRADERAPP_CAPTURE is set, because
      // this one writes into docs/ rather than into test-results/ and a plain
      // `playwright test` must not leave the working tree dirty.
      name: 'screenshots',
      testDir: './tests/screenshots',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'fullstack',
      testDir: './tests/fullstack',
      // One backend, one persisted session, one set of connected clients —
      // so these run in order rather than competing over shared state.
      fullyParallel: false,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],

  webServer: [
    {
      name: 'frontend',
      command:
        'npm run build:e2e --workspace frontend && npm run preview:e2e --workspace frontend',
      cwd: '..',
      url: FRONTEND_URL,
      env: {
        // Baked into the e2e bundle so the browser talks to the test
        // backend, not the developer's live one on 8000.
        VITE_API_URL: BACKEND_URL,
        VITE_WS_URL: `${BACKEND_URL.replace('http', 'ws')}/ws`,
      },
      // Never reused. A preview server left running from an earlier run keeps
      // serving the build it started with, so source changes silently do not
      // reach the tests and a green run means nothing. Rebuilding takes about
      // a second; a false pass costs far more.
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      name: 'alpaca-fixture',
      command: 'node fixtures/alpaca-server.mjs',
      url: `${FIXTURE_URL}/health`,
      reuseExistingServer: !isCI,
      timeout: 30_000,
    },
    {
      name: 'backend',
      command: '.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8100',
      cwd: '../backend',
      url: `${BACKEND_URL}/api/health`,
      reuseExistingServer: !isCI,
      timeout: 60_000,
      stdout: 'ignore',
      stderr: 'pipe',
      env: {
        // Real Alpaca provider, pointed at the fixture server.
        TRADERAPP_ALPACA__KEY_ID: 'e2e-key',
        TRADERAPP_ALPACA__SECRET_KEY: 'e2e-secret',
        TRADERAPP_ALPACA__DATA_URL: FIXTURE_URL,
        TRADERAPP_ALPACA__STREAM_URL: 'ws://127.0.0.1:9899',
        // No TWS in CI, and scanning is IBKR-only.
        TRADERAPP_IBKR__ENABLED: 'false',
        TRADERAPP_SCANNER__ENABLED: 'false',
        // The regime poll would dial the real TradingView API from a test.
        TRADERAPP_REGIME__ENABLED: 'false',
        // So would the live news socket, and being a websocket it is not
        // caught by the fixture server the way the REST paths are.
        TRADERAPP_ALPACA__NEWS_STREAM: 'false',
        // So would EDGAR, for the same reason: the dock's fundamentals and
        // filings panels reach data.sec.gov, and nothing in a test run may
        // leave the machine. The mocked suite serves those routes itself.
        TRADERAPP_EDGAR__ENABLED: 'false',
        // And both AI panels, which spawn a `claude` process that reaches
        // Anthropic — the same rule, one process further out. The mocked
        // suite serves their routes itself; a fullstack run gets the
        // "switched off in settings" line, which is a real state of the
        // panels and worth rendering.
        TRADERAPP_NEWS_AI__ENABLED: 'false',
        TRADERAPP_SETUP_AI__ENABLED: 'false',
        TRADERAPP_STATE_FILE: '/tmp/traderapp-e2e-state.yaml',
        TRADERAPP_LOG_LEVEL: 'WARNING',
      },
    },
  ],
});
