import { defineConfig, devices } from '@playwright/test'
import { homedir } from 'node:os'
import { join } from 'node:path'

const browserLibraryPath = join(
  homedir(),
  '.cache',
  'ms-playwright',
  'canlab-browser-libs',
)

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: 'golden-journey.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: './tests/e2e/.artifacts/test-results',
  reporter: [
    ['list'],
    [
      'html',
      { open: 'never', outputFolder: './tests/e2e/.artifacts/report' },
    ],
  ],
  use: {
    baseURL: 'http://127.0.0.1:4197',
    trace: 'on',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          env: {
            ...(process.env as Record<string, string>),
            LD_LIBRARY_PATH: [browserLibraryPath, process.env.LD_LIBRARY_PATH]
              .filter(Boolean)
              .join(':'),
          },
        },
      },
    },
  ],
  webServer: {
    command:
      'npm run build && npm run preview -- --host 127.0.0.1 --port 4197 --strictPort',
    url: 'http://127.0.0.1:4197',
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
