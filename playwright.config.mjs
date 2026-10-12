import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/frontend', testMatch: '**/*.spec.mjs',
  fullyParallel: true, retries: 0, reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:8765', browserName: 'chromium',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {} },
  webServer: { command: 'python3 -m http.server 8765 --bind 127.0.0.1',
    url: 'http://127.0.0.1:8765/tests/frontend/control-harness.html', timeout: 20000 },
});
