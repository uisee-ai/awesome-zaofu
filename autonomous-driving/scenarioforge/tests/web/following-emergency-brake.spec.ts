import { expect, test } from '@playwright/test'

test('following emergency brake browser evidence proves the replay and comparison story', async ({ page }) => {
  test.skip(!process.env.SCENARIOFORGE_FOLLOWING_BRAKE_E2E_URL, 'release runner starts the real API')
  const endpoint = process.env.SCENARIOFORGE_FOLLOWING_BRAKE_E2E_URL!
  await page.goto(endpoint)
  await page.getByLabel('API endpoint').fill(endpoint)
  await page.getByLabel('Capability token').fill('following-browser-capability')
  await page.getByLabel('CSRF token').fill('following-browser-csrf')

  await expect(page.getByTestId('job-status')).toBeVisible()
  const bundle = page.getByRole('textbox', { name: 'Bundle ID', exact: true })
  await bundle.fill('baseline')
  await page.getByRole('button', { name: 'Load sealed replay' }).click()
  await expect(page.getByTestId('replay-status')).toHaveText('Sealed replay ready')
  await expect(page.getByTestId('metrics')).toContainText('ego:')
  await expect(page.getByTestId('metrics')).toContainText('lead:')
  await expect(page.getByTestId('events')).toContainText('lead-emergency-brake')
  await expect(page.getByTestId('minimum-ttc')).toContainText('s')
  await expect(page.getByTestId('metrics')).toContainText('Safety verdict:')

  await page.getByLabel('New bundle ID').fill('candidate')
  await page.getByRole('button', { name: 'Compare immutable bundles' }).click()
  await expect(page.getByTestId('comparison-result')).toContainText('differences')

  await bundle.fill('candidate')
  await page.getByRole('button', { name: 'Load sealed replay' }).click()
  await expect(page.getByTestId('replay-status')).toHaveText('Sealed replay ready')
  await expect(page.getByTestId('metrics')).toContainText('ego:')
  await expect(page.getByTestId('metrics')).toContainText('lead:')
})
