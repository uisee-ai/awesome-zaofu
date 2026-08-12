#!/usr/bin/env node

import { createReadStream } from 'node:fs'
import { readFile, stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const loopbackHosts = new Set(['127.0.0.1', 'localhost', '::1'])
const mimeTypes = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.dbc', 'text/plain; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.ndjson', 'application/x-ndjson; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.txt', 'text/plain; charset=utf-8'],
  ['.zip', 'application/zip'],
])

const parseArguments = (values) => {
  const options = { host: '127.0.0.1', port: 4173, strictPort: false }
  for (let index = 0; index < values.length; index += 1) {
    const name = values[index]
    if (name === '--strictPort') {
      options.strictPort = true
      continue
    }
    if (name !== '--host' && name !== '--port') {
      throw new Error(`Unknown argument ${name}`)
    }
    const value = values[index + 1]
    if (value === undefined || value.startsWith('--')) {
      throw new Error(`${name} requires a value`)
    }
    if (name === '--host') options.host = value
    else options.port = Number(value)
    index += 1
  }
  if (!loopbackHosts.has(options.host)) {
    throw new Error(`Preview host must be loopback, received ${options.host}`)
  }
  if (!Number.isInteger(options.port) || options.port < 0 || options.port > 65535) {
    throw new Error(`Preview port is invalid: ${String(options.port)}`)
  }
  return options
}

const serializeCsp = (directives) => Object.entries(directives)
  .map(([name, values]) => `${name} ${values.join(' ')}`)
  .join('; ')

const options = parseArguments(process.argv.slice(2))
const policyPath = resolve(
  projectRoot,
  process.env.P0_CSP_POLICY ?? 'config/csp-policy.json',
)
const policy = JSON.parse(await readFile(policyPath, 'utf8'))
if (
  policy.schema_version !== 'canlab.csp-policy.v1' ||
  policy.header_name !== 'Content-Security-Policy' ||
  typeof policy.policy_version !== 'string' ||
  typeof policy.directives !== 'object' ||
  policy.directives === null
) {
  throw new Error('CSP policy does not match schema v1')
}

const distRoot = resolve(projectRoot, 'dist')
const indexPath = resolve(distRoot, 'index.html')
await stat(indexPath)
const csp = serializeCsp(policy.directives)

const resolveRequestPath = async (requestUrl) => {
  const pathname = decodeURIComponent(new URL(requestUrl, 'http://127.0.0.1').pathname)
  const normalized = pathname === '/' ? '/index.html' : pathname
  const candidate = resolve(distRoot, `.${normalized}`)
  if (candidate !== distRoot && !candidate.startsWith(`${distRoot}${sep}`)) {
    return undefined
  }
  try {
    const details = await stat(candidate)
    if (details.isFile()) return candidate
  } catch {
    if (extname(candidate) === '') return indexPath
  }
  return undefined
}

const server = createServer(async (request, response) => {
  response.setHeader(policy.header_name, csp)
  response.setHeader('Cache-Control', 'no-store')
  response.setHeader('Referrer-Policy', 'no-referrer')
  response.setHeader('X-Content-Type-Options', 'nosniff')
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    response.writeHead(405, { Allow: 'GET, HEAD' })
    response.end('Method not allowed')
    return
  }
  try {
    const path = await resolveRequestPath(request.url ?? '/')
    if (path === undefined) {
      response.writeHead(404)
      response.end('Not found')
      return
    }
    response.setHeader(
      'Content-Type',
      mimeTypes.get(extname(path)) ?? 'application/octet-stream',
    )
    response.writeHead(200)
    if (request.method === 'HEAD') response.end()
    else createReadStream(path).pipe(response)
  } catch (error) {
    response.writeHead(500)
    response.end(error instanceof Error ? error.message : String(error))
  }
})

server.on('error', (error) => {
  console.error(error)
  process.exitCode = 1
})

server.listen(options.port, options.host, () => {
  const address = server.address()
  if (address === null || typeof address === 'string') {
    throw new Error('Preview server did not expose a TCP address')
  }
  const displayHost = address.address === '::1' ? '[::1]' : address.address
  console.log(
    `CANLAB_PREVIEW_READY ${JSON.stringify({
      origin: `http://${displayHost}:${address.port}`,
      policy_version: policy.policy_version,
    })}`,
  )
})

const close = () => server.close(() => process.exit())
process.on('SIGINT', close)
process.on('SIGTERM', close)
