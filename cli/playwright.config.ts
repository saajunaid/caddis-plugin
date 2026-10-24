import { defineConfig } from '@playwright/test';

// R31: Chromium only, headless, one worker. Each test starts its own hub server on port 0 (see e2e/fixtures.ts).
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  reporter: [['list']],
  outputDir: 'test-results',
  use: {
    browserName: 'chromium',
    headless: true,
    viewport: { width: 1360, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'off',
  },
});
