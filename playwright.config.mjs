import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:8000'
const target = new URL(baseURL)
const localHosts = new Set(['localhost', '127.0.0.1', '::1'])

if (!localHosts.has(target.hostname) && process.env.E2E_ALLOW_REMOTE !== 'true') {
  throw new Error(
    'E2E_BASE_URL is remote. Set E2E_ALLOW_REMOTE=true only for an isolated QA environment; never run these tests against production.',
  )
}

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: 'list',
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
})
