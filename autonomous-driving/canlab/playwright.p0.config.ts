import { defineConfig } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'

interface QualificationReceipt {
  readonly executable_path?: string
}

const qualificationPath = process.env.P0_QUALIFICATION_RECEIPT
const qualification = qualificationPath !== undefined && existsSync(qualificationPath)
  ? JSON.parse(readFileSync(qualificationPath, 'utf8')) as QualificationReceipt
  : undefined

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: 'p0-closeout.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: process.env.P0_TEST_OUTPUT_DIR ?? '/tmp/canlab-p0-test-results',
  reporter: [['list']],
  timeout: 120_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: 'http://127.0.0.1:4197',
    viewport: { width: 1440, height: 1000 },
    trace: 'off',
    screenshot: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
        launchOptions: {
          ...(qualification?.executable_path === undefined
            ? {}
            : { executablePath: qualification.executable_path }),
          args: ['--no-sandbox', '--disable-dev-shm-usage'],
        },
      },
    },
  ],
  webServer: {
    command:
      'node tools/serve-p0-preview.mjs --host 127.0.0.1 --port 4197 --strictPort',
    url: 'http://127.0.0.1:4197',
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
