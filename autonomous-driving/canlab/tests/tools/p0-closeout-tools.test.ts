// @vitest-environment node

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'
import { mergeP0EvidenceArtifacts } from '../../tools/merge-p0-evidence'

const readProjectFile = (path: string) =>
  readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8')

const PROMOTION_BASE = '2583d6e47ec4c890fa63b9f81b80f07e5c2586ef'
const RELEASE_HISTORY_ARTIFACTS = [
  'artifacts/verification/p0/manifest.json',
  'artifacts/verification/p0/release-candidate.json',
  'artifacts/verification/p0/release/cas-receipt.json',
]

const hasReleaseHistory = (() => {
  if (!RELEASE_HISTORY_ARTIFACTS.every((path) => existsSync(resolve(process.cwd(), path)))) {
    return false
  }
  try {
    execFileSync('git', ['cat-file', '-e', `${PROMOTION_BASE}^{commit}`], {
      cwd: process.cwd(),
      stdio: 'ignore',
    })
    return true
  } catch {
    return false
  }
})()

const releaseHistoryIt = hasReleaseHistory ? it : it.skip

const createIsolatedPromotionRepository = (root: string, prefix: string) => {
  const directory = mkdtempSync(join(tmpdir(), prefix))
  rmSync(directory, { recursive: true, force: true })
  const gitCommonDir = execFileSync('git', ['rev-parse', '--git-common-dir'], {
    cwd: root,
    encoding: 'utf8',
  }).trim()
  const source = resolve(root, gitCommonDir)
  const head = execFileSync('git', ['rev-parse', 'HEAD'], {
    cwd: root,
    encoding: 'utf8',
  }).trim()

  execFileSync('git', ['clone', '--no-hardlinks', '--no-checkout', source, directory], {
    stdio: 'pipe',
  })
  execFileSync('git', ['checkout', '--detach', head], { cwd: directory, stdio: 'pipe' })
  execFileSync('git', ['update-ref', 'refs/heads/main', PROMOTION_BASE], { cwd: directory })
  execFileSync('git', ['config', 'user.name', 'CAN Lab verifier test'], { cwd: directory })
  execFileSync('git', ['config', 'user.email', 'canlab@example.invalid'], { cwd: directory })

  const isolatedMain = execFileSync('git', ['rev-parse', 'refs/heads/main'], {
    cwd: directory,
    encoding: 'utf8',
  }).trim()
  if (isolatedMain !== PROMOTION_BASE) {
    throw new Error(`failed to pin isolated main: ${isolatedMain}`)
  }

  return directory
}

describe('P0 closeout tools', () => {
  it('preserves durable release artifacts when a later browser gate regenerates evidence', () => {
    const merged = mergeP0EvidenceArtifacts(
      [
        { path: 'artifacts/verification/p0/static/tests.json', sha256: 'old-tests', byte_count: 1 },
        { path: 'artifacts/verification/p0/release/final-verification.json', sha256: 'final', byte_count: 2 },
      ],
      [{ path: 'artifacts/verification/p0/static/tests.json', sha256: 'new-tests', byte_count: 3 }],
    )
    expect(merged).toEqual([
      { path: 'artifacts/verification/p0/static/tests.json', sha256: 'new-tests', byte_count: 3 },
      { path: 'artifacts/verification/p0/release/final-verification.json', sha256: 'final', byte_count: 2 },
    ])
  })

  it('uses an exact eight-fixture deny matrix and enumerates six persistence surfaces', () => {
    const manifest = JSON.parse(
      readProjectFile('tests/fixtures/passive-boundary/manifest.json'),
    ) as unknown
    expect(manifest).toEqual({
      schema_version: 'canlab.passive-boundary-fixtures.v1',
      fixtures: [
        { file: 'webhid.js', expected_rule: 'webhid' },
        { file: 'webbluetooth.js', expected_rule: 'webbluetooth' },
        { file: 'websocket.js', expected_rule: 'websocket' },
        { file: 'eventsource.js', expected_rule: 'eventsource' },
        { file: 'webrtc.js', expected_rule: 'webrtc' },
        { file: 'serviceworker.js', expected_rule: 'serviceworker' },
        { file: 'hardware-access.js', expected_rule: 'hardware_access' },
        { file: 'can-send.js', expected_rule: 'can_transmit' },
      ],
    })
    const policy = JSON.parse(
      readProjectFile('config/passive-boundary-policy.json'),
    ) as { persistence_surfaces: string[] }
    expect(policy.persistence_surfaces).toEqual([
      'cookies',
      'service-worker-registrations',
      'localStorage',
      'sessionStorage',
      'IndexedDB',
      'CacheStorage',
    ])

    const directory = mkdtempSync(join(tmpdir(), 'canlab-boundary-test-'))
    try {
      const output = join(directory, 'boundary.json')
      execFileSync(
        process.execPath,
        [
          'tools/check-passive-boundary.mjs',
          '--policy',
          'config/passive-boundary-policy.json',
          '--fixtures',
          'tests/fixtures/passive-boundary',
          '--output',
          output,
        ],
        { cwd: process.cwd(), stdio: 'pipe' },
      )
      const evidence = JSON.parse(readFileSync(output, 'utf8')) as {
        status: string
        production_violations: unknown[]
        negative_fixtures: Array<{ expected_rule: string; rejected: boolean }>
      }
      expect(evidence.status).toBe('passed')
      expect(evidence.production_violations).toEqual([])
      expect(evidence.negative_fixtures).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ expected_rule: 'webhid', rejected: true }),
          expect.objectContaining({ expected_rule: 'webbluetooth', rejected: true }),
          expect.objectContaining({ expected_rule: 'websocket', rejected: true }),
          expect.objectContaining({ expected_rule: 'eventsource', rejected: true }),
          expect.objectContaining({ expected_rule: 'webrtc', rejected: true }),
          expect.objectContaining({ expected_rule: 'serviceworker', rejected: true }),
          expect.objectContaining({ expected_rule: 'hardware_access', rejected: true }),
          expect.objectContaining({ expected_rule: 'can_transmit', rejected: true }),
        ]),
      )
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  })

  it('qualifies from the official dynamic Stable snapshot without a fixed Chrome version', () => {
    const qualification = readProjectFile('tools/qualify-stable-chromium.mjs')
    expect(qualification).toContain(
      'https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json',
    )
    expect(qualification).toContain("snapshot.channels?.Stable")
    expect(qualification).toContain("candidate.platform === options.platform")
    expect(qualification).not.toMatch(/stableVersion\s*=\s*['"][0-9]/)
  })

  it('keeps browser routes observational and the release verifier ref-read-only', () => {
    const browserTest = readProjectFile('tests/e2e/p0-closeout.spec.ts')
    expect(browserTest).toContain('route.continue()')
    expect(browserTest).not.toContain('route.abort(')
    expect(browserTest).toContain("'securitypolicyviolation'")
    expect(browserTest).toContain('sentinel_arrivals')
    expect(browserTest).toContain('path: `artifacts/verification/p0/${path}`')
    expect(browserTest).not.toContain('relative(projectRoot, absolutePath)')

    const releaseVerifier = readProjectFile('tools/verify-p0-release.mjs')
    for (const mutation of [
      "'update-ref'",
      "'symbolic-ref'",
      "'checkout'",
      "'merge'",
      "'push'",
      "'reset'",
    ]) expect(releaseVerifier).not.toContain(mutation)
    expect(releaseVerifier).toContain("'for-each-ref'")
    expect(releaseVerifier).toContain("'archive'")
    expect(releaseVerifier).toContain('resolveEvidenceArtifactPath(artifact.path)')
    expect(releaseVerifier).toContain("path.split(/[\\\\/]/).includes('..')")
    expect(releaseVerifier).toContain(
      "const projectRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))",
    )
    expect(releaseVerifier).toContain("CANLAB_NESTED_RELEASE_VERIFY: '1'")
  })

  releaseHistoryIt('rebinds an unissued release intent to the integrated candidate without dirtying evidence', () => {
    if (process.env.CANLAB_NESTED_RELEASE_VERIFY === '1') return

    const manifestPath = 'artifacts/verification/p0/manifest.json'
    const candidatePath = 'artifacts/verification/p0/release-candidate.json'
    const casReceiptPath = 'artifacts/verification/p0/release/cas-receipt.json'
    const originalManifest = readFileSync(manifestPath)
    const originalCandidate = readFileSync(candidatePath)
    const originalCasReceipt = readFileSync(casReceiptPath)
    const git = (...args: string[]) => execFileSync('git', args, {
      cwd: process.cwd(),
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
    }).trim()
    const currentCommit = git('rev-parse', 'HEAD')
    const currentTree = git('rev-parse', 'HEAD^{tree}')
    const refsBefore = git('for-each-ref', '--format=%(refname) %(objectname)')
    const releaseCandidate = JSON.parse(originalCandidate.toString('utf8')) as {
      base_commit: string
      candidate_commit: string
      candidate_tree: string
    }
    const rewrittenCandidateCommit = execFileSync(
      'git',
      [
        'commit-tree',
        releaseCandidate.candidate_tree,
        '-p',
        git('rev-parse', `${releaseCandidate.candidate_commit}^`),
      ],
      {
        cwd: process.cwd(),
        encoding: 'utf8',
        input: 'Equivalent pending candidate with rewritten history\n',
        env: {
          ...process.env,
          GIT_AUTHOR_NAME: 'CAN Lab verifier test',
          GIT_AUTHOR_EMAIL: 'canlab@example.invalid',
          GIT_COMMITTER_NAME: 'CAN Lab verifier test',
          GIT_COMMITTER_EMAIL: 'canlab@example.invalid',
        },
      },
    ).trim()
    expect(rewrittenCandidateCommit).not.toBe(releaseCandidate.candidate_commit)
    const rewrittenCandidate = {
      ...releaseCandidate,
      candidate_commit: rewrittenCandidateCommit,
    }
    const rewrittenCandidateBody = Buffer.from(
      `${JSON.stringify(rewrittenCandidate, null, 2)}\n`,
    )
    const rewrittenCasReceipt = {
      ...(JSON.parse(originalCasReceipt.toString('utf8')) as Record<string, unknown>),
      candidate_commit: rewrittenCandidateCommit,
      candidate_tree: releaseCandidate.candidate_tree,
      candidate_manifest_sha256: createHash('sha256')
        .update(rewrittenCandidateBody)
        .digest('hex'),
    }
    const rewrittenCasReceiptBody = Buffer.from(
      `${JSON.stringify(rewrittenCasReceipt, null, 2)}\n`,
    )
    const manifest = JSON.parse(originalManifest.toString('utf8')) as {
      subject: { target_commit: string; target_tree: string }
      artifacts: Array<{ path: string; sha256: string; byte_count: number }>
    }
    manifest.subject = {
      target_commit: currentCommit,
      target_tree: currentTree,
    }
    manifest.artifacts = manifest.artifacts.map((artifact) => {
      const body = artifact.path === candidatePath
        ? rewrittenCandidateBody
        : artifact.path === casReceiptPath
          ? rewrittenCasReceiptBody
          : undefined
      return body === undefined
        ? artifact
        : {
            ...artifact,
            sha256: createHash('sha256').update(body).digest('hex'),
            byte_count: body.byteLength,
          }
    })
    writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
    writeFileSync(candidatePath, rewrittenCandidateBody)
    writeFileSync(casReceiptPath, rewrittenCasReceiptBody)

    expect(() => {
      try {
        execFileSync(
        './tools/verify-p0-release.sh',
        [
          '--mode',
          'read-only',
          '--expected-old-main',
          releaseCandidate.base_commit,
          '--candidate-manifest',
          'artifacts/verification/p0/release-candidate.json',
          '--cas-receipt',
          'artifacts/verification/p0/release/cas-receipt.json',
          '--output',
          'artifacts/verification/p0/release',
        ],
        {
          cwd: process.cwd(),
          encoding: 'utf8',
          env: { ...process.env, CANLAB_NESTED_RELEASE_VERIFY: '1' },
          maxBuffer: 64 * 1024 * 1024,
          timeout: 55_000,
        },
        )
      } finally {
        writeFileSync(manifestPath, originalManifest)
        writeFileSync(candidatePath, originalCandidate)
        writeFileSync(casReceiptPath, originalCasReceipt)
      }
    }).toThrow()
    expect(git('for-each-ref', '--format=%(refname) %(objectname)')).toBe(refsBefore)
    expect(
      git(
        'status',
        '--porcelain',
        '--untracked-files=all',
        '--',
        'artifacts/verification/p0',
      ),
    ).toBe('')
  }, 60_000)

  releaseHistoryIt('validates real product P and evidence carrier E histories', () => {
    if (process.env.CANLAB_NESTED_RELEASE_VERIFY === '1') return
    const root = process.cwd()
    const directory = createIsolatedPromotionRepository(root, 'canlab-p-e-')
    try {
      const integrationBase = execFileSync('git', ['rev-parse', 'refs/heads/main'], {
        cwd: directory,
        encoding: 'utf8',
      }).trim()
      writeFileSync(join(directory, 'src/App.tsx'), `${readFileSync(join(directory, 'src/App.tsx'), 'utf8')}\n// integration rewrite fixture\n`)
      execFileSync('git', ['add', 'src/App.tsx'], { cwd: directory })
      const sourceTree = execFileSync('git', ['write-tree'], { cwd: directory, encoding: 'utf8' }).trim()
      const source = execFileSync('git', ['commit-tree', sourceTree, '-p', integrationBase], { cwd: directory, encoding: 'utf8', input: 'worker source P\n' }).trim()
      execFileSync('git', ['commit', '-m', 'fixture integrated product P prime'], { cwd: directory })
      const product = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: directory, encoding: 'utf8' }).trim()
      const productTree = execFileSync('git', ['rev-parse', 'HEAD^{tree}'], { cwd: directory, encoding: 'utf8' }).trim()
      const candidatePath = 'artifacts/verification/p0/release-candidate.json'
      const casPath = 'artifacts/verification/p0/release/cas-receipt.json'
      const manifestPath = 'artifacts/verification/p0/manifest.json'
      const candidate = JSON.parse(readFileSync(join(directory, candidatePath), 'utf8'))
      candidate.candidate_commit = source
      candidate.candidate_tree = sourceTree
      candidate.source_commit = product
      candidate.source_tree = productTree
      writeFileSync(join(directory, candidatePath), `${JSON.stringify(candidate, null, 2)}\n`)
      const cas = JSON.parse(readFileSync(join(directory, casPath), 'utf8'))
      cas.candidate_commit = source
      cas.candidate_tree = sourceTree
      cas.candidate_manifest_sha256 = createHash('sha256').update(readFileSync(join(directory, candidatePath))).digest('hex')
      writeFileSync(join(directory, casPath), `${JSON.stringify(cas, null, 2)}\n`)
      const manifest = JSON.parse(readFileSync(join(directory, manifestPath), 'utf8'))
      manifest.subject = { target_commit: source, target_tree: sourceTree }
      manifest.browser_qualification.image_digest = JSON.parse(
        readFileSync(join(directory, 'artifacts/verification/p0/browser/qualification.json'), 'utf8'),
      ).image_digest
      for (const path of [
        'artifacts/verification/p0/static/assets.json',
        'artifacts/verification/p0/browser/qualification.json',
        'artifacts/verification/p0/release/clean-checkout.json',
        'artifacts/verification/p0/release/final-verification.json',
      ]) {
        const value = JSON.parse(readFileSync(join(directory, path), 'utf8'))
        if (path.endsWith('static/assets.json')) {
          value.observed_git = { commit: source, tree: sourceTree }
        }
        value.target_commit = source
        value.target_tree = sourceTree
        value.candidate_commit = source
        value.candidate_tree = sourceTree
        if (path.endsWith('final-verification.json')) {
          value.evidence_artifact_count = manifest.artifacts.length
        }
        writeFileSync(join(directory, path), `${JSON.stringify(value, null, 2)}\n`)
      }
      for (const artifact of manifest.artifacts) {
        const body = readFileSync(join(directory, artifact.path))
        artifact.sha256 = createHash('sha256').update(body).digest('hex')
        artifact.byte_count = body.byteLength
      }
      writeFileSync(join(directory, manifestPath), `${JSON.stringify(manifest, null, 2)}\n`)
      execFileSync('git', ['add', 'artifacts/verification/p0'], { cwd: directory })
      execFileSync('git', ['commit', '-m', 'fixture evidence carrier E'], { cwd: directory })
      const evidence = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: directory, encoding: 'utf8' }).trim()
      const assetsProbe = 'artifacts/verification/p0/static/assets-fixture.json'
      const noIdentityEnv = { ...process.env }
      delete noIdentityEnv.P0_VERIFICATION_COMMIT
      delete noIdentityEnv.P0_VERIFICATION_TREE
      execFileSync(process.execPath, ['tools/verify-assets.mjs', '--output', assetsProbe], { cwd: directory, env: noIdentityEnv })
      const observed = JSON.parse(readFileSync(join(directory, assetsProbe), 'utf8'))
      const effectiveCandidate = JSON.parse(readFileSync(join(directory, candidatePath), 'utf8'))
      expect(effectiveCandidate.candidate_commit).toBe(source)
      expect(observed.observed_git).toEqual({ commit: source, tree: sourceTree })
      const incompleteEnv = { ...noIdentityEnv, P0_VERIFICATION_COMMIT: source }
      expect(() => execFileSync(process.execPath, ['tools/verify-assets.mjs', '--output', assetsProbe], { cwd: directory, env: incompleteEnv })).toThrow()
      rmSync(join(directory, assetsProbe), { force: true })
      expect(execFileSync('git', ['merge-base', '--is-ancestor', product, evidence], { cwd: directory })).toBeDefined()
      expect(() => execFileSync('git', ['merge-base', '--is-ancestor', source, evidence], { cwd: directory })).toThrow()
      expect(execFileSync('git', ['diff', '--name-only', product, evidence], { cwd: directory, encoding: 'utf8' }).trim().split('\n').every((path) => path.startsWith('artifacts/verification/p0/'))).toBe(true)
      const sourcePatch = createHash('sha256').update(execFileSync('git', ['diff', '--binary', integrationBase, source, '--', '.', ':(exclude)artifacts/verification/p0'], { cwd: directory })).digest('hex')
      const matches = execFileSync('git', ['rev-list', '--first-parent', `${integrationBase}..${evidence}`], { cwd: directory, encoding: 'utf8' }).trim().split('\n').filter(Boolean).filter((commit) => execFileSync('git', ['rev-parse', `${commit}^{tree}`], { cwd: directory, encoding: 'utf8' }).trim() === sourceTree && createHash('sha256').update(execFileSync('git', ['diff', '--binary', integrationBase, commit, '--', '.', ':(exclude)artifacts/verification/p0'], { cwd: directory })).digest('hex') === sourcePatch)
      expect(matches).toEqual([product])
      const output = execFileSync('./tools/verify-p0-release.sh', [
        '--mode', 'read-only', '--expected-old-main', PROMOTION_BASE,
        '--candidate-manifest', candidatePath, '--cas-receipt', casPath, '--output', 'artifacts/verification/p0/release',
      ], { cwd: directory, encoding: 'utf8', env: { ...process.env, CANLAB_NESTED_RELEASE_VERIFY: '1' } })
      expect(output).toContain('lineage proof=evidence-only')
      expect(output).toContain(`${source} -> ${product}`)

      for (const path of [
        'artifacts/verification/p0/static/assets.json',
        'artifacts/verification/p0/browser/qualification.json',
        'artifacts/verification/p0/release/final-verification.json',
      ]) {
        const original = readFileSync(join(directory, path))
        const stale = JSON.parse(original.toString('utf8'))
        if (path.endsWith('static/assets.json')) {
          stale.observed_git = { commit: product, tree: productTree }
        }
        stale.target_commit = product
        stale.candidate_commit = product
        writeFileSync(join(directory, path), `${JSON.stringify(stale, null, 2)}\n`)
        expect(() => execFileSync('./tools/verify-p0-release.sh', [
          '--mode', 'read-only', '--expected-old-main', PROMOTION_BASE,
          '--candidate-manifest', candidatePath, '--cas-receipt', casPath, '--output', 'artifacts/verification/p0/release',
        ], { cwd: directory, env: { ...process.env, CANLAB_NESTED_RELEASE_VERIFY: '1' } })).toThrow()
        writeFileSync(join(directory, path), original)
      }

      const wrongSubject = JSON.parse(readFileSync(join(directory, manifestPath), 'utf8'))
      wrongSubject.subject.target_commit = product
      writeFileSync(join(directory, manifestPath), `${JSON.stringify(wrongSubject, null, 2)}\n`)
      execFileSync('git', ['add', manifestPath], { cwd: directory })
      execFileSync('git', ['commit', '-m', 'fixture wrong subject'], { cwd: directory })
      expect(() => execFileSync('./tools/verify-p0-release.sh', [
        '--mode', 'read-only', '--expected-old-main', PROMOTION_BASE,
        '--candidate-manifest', candidatePath, '--cas-receipt', casPath, '--output', 'artifacts/verification/p0/release',
      ], { cwd: directory, env: { ...process.env, CANLAB_NESTED_RELEASE_VERIFY: '1' } })).toThrow()
      wrongSubject.subject.target_commit = source
      writeFileSync(join(directory, manifestPath), `${JSON.stringify(wrongSubject, null, 2)}\n`)
      execFileSync('git', ['add', manifestPath], { cwd: directory })
      execFileSync('git', ['commit', '-m', 'fixture restore subject'], { cwd: directory })
      writeFileSync(join(directory, 'src/App.tsx'), `${readFileSync(join(directory, 'src/App.tsx'), 'utf8')}\n// product drift\n`)
      execFileSync('git', ['add', 'src/App.tsx'], { cwd: directory })
      execFileSync('git', ['commit', '-m', 'fixture product drift'], { cwd: directory })
      expect(() => execFileSync('./tools/verify-p0-release.sh', [
        '--mode', 'read-only', '--expected-old-main', PROMOTION_BASE,
        '--candidate-manifest', candidatePath, '--cas-receipt', casPath, '--output', 'artifacts/verification/p0/release',
      ], { cwd: directory, env: { ...process.env, CANLAB_NESTED_RELEASE_VERIFY: '1' } })).toThrow()
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  }, 180_000)

  releaseHistoryIt('rejects zero and multiple integrated lineage matches before evidence checks', () => {
    if (process.env.CANLAB_NESTED_RELEASE_VERIFY === '1') return
    const root = process.cwd()
    const directory = createIsolatedPromotionRepository(root, 'canlab-lineage-')
    try {
      const git = (...args: string[]) => execFileSync('git', args, { cwd: directory, encoding: 'utf8' }).trim()
      const base = PROMOTION_BASE
      const integrationHead = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
      const candidatePath = join(directory, 'artifacts/verification/p0/release-candidate.json')
      const casPath = join(directory, 'artifacts/verification/p0/release/cas-receipt.json')
      const manifestPath = join(directory, 'artifacts/verification/p0/manifest.json')
      const bind = (commit: string) => {
        const tree = git('rev-parse', `${commit}^{tree}`)
        const candidate = JSON.parse(readFileSync(candidatePath, 'utf8'))
        Object.assign(candidate, { base_commit: base, candidate_commit: commit, candidate_tree: tree, source_commit: commit, source_tree: tree })
        writeFileSync(candidatePath, `${JSON.stringify(candidate, null, 2)}\n`)
        const cas = JSON.parse(readFileSync(casPath, 'utf8'))
        Object.assign(cas, { expected_old_main: base, candidate_commit: commit, candidate_tree: tree, candidate_manifest_sha256: createHash('sha256').update(readFileSync(candidatePath)).digest('hex') })
        writeFileSync(casPath, `${JSON.stringify(cas, null, 2)}\n`)
        const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
        manifest.subject = { target_commit: commit, target_tree: tree }
        for (const artifact of manifest.artifacts) {
          const body = readFileSync(join(directory, artifact.path))
          artifact.sha256 = createHash('sha256').update(body).digest('hex')
          artifact.byte_count = body.byteLength
        }
        writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
      }
      const invoke = () => execFileSync('./tools/verify-p0-release.sh', ['--mode', 'read-only', '--expected-old-main', base, '--candidate-manifest', 'artifacts/verification/p0/release-candidate.json', '--cas-receipt', 'artifacts/verification/p0/release/cas-receipt.json', '--output', 'artifacts/verification/p0/release'], { cwd: directory, env: { ...process.env, CANLAB_NESTED_RELEASE_VERIFY: '1' } })
      writeFileSync(join(directory, 'src/App.tsx'), `${readFileSync(join(directory, 'src/App.tsx'), 'utf8')}\n// zero mapping\n`)
      git('add', 'src/App.tsx')
      const zeroTree = git('write-tree')
      const zero = execFileSync('git', ['commit-tree', zeroTree, '-p', 'HEAD'], { cwd: directory, input: 'zero\n', encoding: 'utf8' }).trim()
      bind(zero)
      expect(invoke).toThrow(/integrated product mapping is not unique: 0 matches/)
      git('restore', '--source=HEAD', '--staged', '--worktree', '--', 'src/App.tsx')
      git('checkout', '--detach', integrationHead)
      writeFileSync(join(directory, 'src/App.tsx'), `${readFileSync(join(directory, 'src/App.tsx'), 'utf8')}\n// duplicate mapping\n`)
      git('add', 'src/App.tsx')
      git('commit', '-m', 'lineage P prime')
      const first = git('rev-parse', 'HEAD')
      git('commit', '--allow-empty', '-m', 'lineage duplicate P prime')
      bind(first)
      expect(invoke).toThrow(/integrated product mapping is not unique: 2 matches/)
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  }, 120_000)

  releaseHistoryIt('fails qualification identity before invoking curl', () => {
    if (process.env.CANLAB_NESTED_RELEASE_VERIFY === '1') return
    const root = process.cwd()
    const directory = mkdtempSync(join(tmpdir(), 'canlab-qualifier-'))
    rmSync(directory, { recursive: true, force: true })
    try {
      execFileSync('git', ['worktree', 'add', '--detach', directory, 'HEAD'], { cwd: root })
      const candidatePath = join(directory, 'artifacts/verification/p0/release-candidate.json')
      const candidate = JSON.parse(readFileSync(candidatePath, 'utf8'))
      writeFileSync(join(directory, 'src/App.tsx'), `${readFileSync(join(directory, 'src/App.tsx'), 'utf8')}\n// stale candidate\n`)
      execFileSync('git', ['add', 'src/App.tsx'], { cwd: directory })
      const staleTree = execFileSync('git', ['write-tree'], { cwd: directory, encoding: 'utf8' }).trim()
      const stale = execFileSync('git', ['commit-tree', staleTree, '-p', 'HEAD'], { cwd: directory, input: 'stale candidate\n', encoding: 'utf8' }).trim()
      candidate.candidate_commit = stale
      candidate.candidate_tree = execFileSync('git', ['rev-parse', `${stale}^{tree}`], { cwd: directory, encoding: 'utf8' }).trim()
      candidate.source_commit = stale
      candidate.source_tree = candidate.candidate_tree
      writeFileSync(candidatePath, `${JSON.stringify(candidate, null, 2)}\n`)
      const bin = join(directory, 'bin')
      const marker = join(directory, 'curl-called')
      mkdirSync(bin)
      const curl = join(bin, 'curl')
      writeFileSync(curl, `#!/bin/sh\necho called > ${marker}\nexit 99\n`)
      chmodSync(curl, 0o755)
      expect(() => execFileSync(process.execPath, ['tools/qualify-stable-chromium.mjs', '--channel', 'stable', '--platform', 'linux64', '--output', 'artifacts/verification/p0/browser/qualification.json'], { cwd: directory, env: { ...process.env, PATH: `${bin}:${process.env.PATH}` }, stdio: 'pipe' })).toThrow()
      expect(() => readFileSync(marker)).toThrow()
    } finally {
      execFileSync('git', ['worktree', 'remove', '--force', directory], { cwd: root })
      rmSync(directory, { recursive: true, force: true })
    }
  }, 60_000)

  it('fails closed for incomplete or mismatched verification identity env', () => {
    if (process.env.CANLAB_NESTED_RELEASE_VERIFY === '1') return
    const commit = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
    const tree = execFileSync('git', ['rev-parse', 'HEAD^{tree}'], { encoding: 'utf8' }).trim()
    const run = (env: NodeJS.ProcessEnv) => execFileSync(process.execPath, ['tools/verify-assets.mjs', '--output', 'artifacts/verification/p0/static/env-probe.json'], { cwd: process.cwd(), env, stdio: 'pipe' })
    expect(() => run({ ...process.env, P0_VERIFICATION_COMMIT: commit })).toThrow()
    expect(() => run({ ...process.env, P0_VERIFICATION_COMMIT: commit, P0_VERIFICATION_TREE: '0'.repeat(40) })).toThrow()
    expect(() => run({ ...process.env, P0_VERIFICATION_COMMIT: '0'.repeat(40), P0_VERIFICATION_TREE: tree })).toThrow()
  }, 60_000)

  releaseHistoryIt('rejects cross-artifact semantic contradictions after recomputing manifest digests', () => {
    if (process.env.CANLAB_NESTED_RELEASE_VERIFY === '1') return
    const root = process.cwd()
    const directory = createIsolatedPromotionRepository(root, 'canlab-semantic-')
    try {
      const manifestPath = join(directory, 'artifacts/verification/p0/manifest.json')
      const qualificationPath = join(directory, 'artifacts/verification/p0/browser/qualification.json')
      const finalPath = join(directory, 'artifacts/verification/p0/release/final-verification.json')
      const candidatePath = 'artifacts/verification/p0/release-candidate.json'
      const casPath = 'artifacts/verification/p0/release/cas-receipt.json'
      const invoke = () => execFileSync('./tools/verify-p0-release.sh', [
        '--mode', 'read-only', '--expected-old-main', PROMOTION_BASE,
        '--candidate-manifest', candidatePath, '--cas-receipt', casPath, '--output', 'artifacts/verification/p0/release',
      ], { cwd: directory, env: { ...process.env, CANLAB_NESTED_RELEASE_VERIFY: '1' }, maxBuffer: 64 * 1024 * 1024 })
      const originalManifest = readFileSync(manifestPath)
      const originalQualification = readFileSync(qualificationPath)
      const originalFinal = readFileSync(finalPath)
      const manifest = JSON.parse(originalManifest.toString('utf8')) as {
        browser_qualification?: Record<string, unknown>
        artifacts: Array<{ path: string; sha256: string; byte_count: number }>
      }
      const updateDigest = (path: string, body: Buffer) => {
        const artifact = manifest.artifacts.find((entry) => entry.path === path)
        if (!artifact) throw new Error(`missing manifest artifact ${path}`)
        artifact.sha256 = createHash('sha256').update(body).digest('hex')
        artifact.byte_count = body.byteLength
      }

      const qualification = JSON.parse(originalQualification.toString('utf8'))
      qualification.image_digest = 'sha256:' + '0'.repeat(64)
      const qualificationBody = Buffer.from(`${JSON.stringify(qualification, null, 2)}\n`)
      writeFileSync(qualificationPath, qualificationBody)
      updateDigest('artifacts/verification/p0/browser/qualification.json', qualificationBody)
      writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
      expect(invoke).toThrow(/browser qualification image digest does not match evidence manifest/)

      writeFileSync(qualificationPath, originalQualification)
      updateDigest('artifacts/verification/p0/browser/qualification.json', originalQualification)
      manifest.browser_qualification = {
        ...(manifest.browser_qualification ?? {}),
        image_digest: JSON.parse(originalQualification.toString('utf8')).image_digest,
      }
      const finalVerification = JSON.parse(originalFinal.toString('utf8'))
      finalVerification.evidence_artifact_count = 0
      const finalBody = Buffer.from(`${JSON.stringify(finalVerification, null, 2)}\n`)
      writeFileSync(finalPath, finalBody)
      updateDigest('artifacts/verification/p0/release/final-verification.json', finalBody)
      writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
      expect(invoke).toThrow(/final verification evidence artifact count does not match evidence manifest/)
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  }, 120_000)

})
