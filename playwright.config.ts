import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'
const localChromium = '/home/kldhsh123/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome'
export default defineConfig({
  testDir: './tests/e2e', fullyParallel: false, timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:1420', viewport: { width: 1200, height: 830 },
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || (existsSync(localChromium) ? localChromium : undefined) } },
  webServer: { command: 'npm run dev -- --port 1420', url: 'http://127.0.0.1:1420', reuseExistingServer: !process.env.CI },
})
