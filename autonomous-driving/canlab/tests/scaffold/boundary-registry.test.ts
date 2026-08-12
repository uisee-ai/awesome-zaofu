// @vitest-environment node

import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

interface PackageManifest {
  scripts?: Record<string, string>
}

const packageManifest = JSON.parse(
  readFileSync(new URL('../../package.json', import.meta.url), 'utf8'),
) as PackageManifest

describe('root command registry', () => {
  it('publishes the candidate commands from the repository root', () => {
    expect(packageManifest.scripts).toMatchObject({
      build: 'tsc --noEmit && vite build',
      lint: 'eslint .',
      test:
        'vitest run --reporter=default --reporter=json --outputFile.json=artifacts/verification/p0/static/tests.json',
      'test:e2e': 'playwright test',
    })
  })

  it('registers exactly one passive-boundary runner for the assembly scanner', () => {
    expect(packageManifest.scripts?.['boundary:check']).toBe(
      'node tools/check-passive-boundary.mjs',
    )
    expect(
      Object.keys(packageManifest.scripts ?? {}).filter((scriptName) =>
        scriptName.startsWith('boundary:'),
      ),
    ).toEqual(['boundary:check'])
  })
})
