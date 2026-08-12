// @vitest-environment node

import { createHash } from 'node:crypto'
import { readFileSync, readdirSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { parseDbc, type DbcParseError } from '../../../src/domain/dbc/index.ts'

interface CorpusSource {
  readonly repository: string
  readonly commit: string
  readonly license: string
  readonly license_file: string
  readonly license_sha256: string
}

interface AcceptedBaseline {
  readonly status: 'accepted'
  readonly messages: number
  readonly signals: number
}

interface RejectedBaseline {
  readonly status: 'rejected'
  readonly error: DbcParseError
}

interface CorpusCase {
  readonly id: string
  readonly file: string
  readonly source: string
  readonly upstream_path: string
  readonly sha256: string
  readonly bytes: number
  readonly declarations: {
    readonly messages: number
    readonly signals: number
  }
  readonly feature_tags: readonly string[]
  readonly markers: readonly string[]
  readonly baseline: AcceptedBaseline | RejectedBaseline
}

interface CorpusManifest {
  readonly schema_version: string
  readonly sources: Readonly<Record<string, CorpusSource>>
  readonly cases: readonly CorpusCase[]
}

const corpusRoot = new URL('../../fixtures/dbc-corpus/', import.meta.url)
const manifest = JSON.parse(
  readFileSync(new URL('manifest.json', corpusRoot), 'utf8'),
) as CorpusManifest

const sha256 = (bytes: Uint8Array): string =>
  createHash('sha256').update(bytes).digest('hex')

const declarationCount = (source: string, expression: RegExp): number =>
  source.split(/\r?\n/).filter((line) => expression.test(line)).length

describe('pinned upstream DBC compatibility corpus', () => {
  it('binds every fixture and license to complete provenance', () => {
    expect(manifest.schema_version).toBe('canlab.dbc-corpus.v1')
    expect(Object.keys(manifest.sources).sort()).toEqual(['cantools', 'opendbc'])
    expect(manifest.cases).toHaveLength(6)

    const fixtureFiles = readdirSync(new URL('files/', corpusRoot)).sort()
    expect(manifest.cases.map(({ file }) => file.replace('files/', '')).sort())
      .toEqual(fixtureFiles)

    for (const [sourceId, source] of Object.entries(manifest.sources)) {
      expect(source.repository).toMatch(/^https:\/\/github\.com\//)
      expect(source.commit).toMatch(/^[0-9a-f]{40}$/)
      expect(source.license).toBe('MIT')
      const licenseBytes = readFileSync(new URL(source.license_file, corpusRoot))
      expect(sha256(licenseBytes), sourceId).toBe(source.license_sha256)
    }

    for (const fixture of manifest.cases) {
      expect(manifest.sources[fixture.source], fixture.id).toBeDefined()
      expect(fixture.upstream_path, fixture.id).not.toBe('')
      expect(fixture.feature_tags.length, fixture.id).toBeGreaterThan(0)
      const bytes = readFileSync(new URL(fixture.file, corpusRoot))
      const source = bytes.toString('utf8')
      expect(bytes.byteLength, fixture.id).toBe(fixture.bytes)
      expect(sha256(bytes), fixture.id).toBe(fixture.sha256)
      expect(
        declarationCount(source, /^BO_\s/),
        `${fixture.id} message declarations`,
      ).toBe(fixture.declarations.messages)
      expect(
        declarationCount(source, /^\s+SG_\s/),
        `${fixture.id} signal declarations`,
      ).toBe(fixture.declarations.signals)
      for (const marker of fixture.markers) {
        expect(source, `${fixture.id} marker ${marker}`).toContain(marker)
      }
    }
  })

  it('makes current parser compatibility changes explicit', () => {
    for (const fixture of manifest.cases) {
      const source = readFileSync(new URL(fixture.file, corpusRoot), 'utf8')
      const result = parseDbc(source)
      const observed: AcceptedBaseline | RejectedBaseline = result.ok
        ? {
            status: 'accepted',
            messages: result.database.messages.length,
            signals: result.database.messages.reduce(
              (count, message) => count + message.signals.length,
              0,
            ),
          }
        : { status: 'rejected', error: result.error }

      expect(observed, fixture.id).toEqual(fixture.baseline)
    }
  })
})
