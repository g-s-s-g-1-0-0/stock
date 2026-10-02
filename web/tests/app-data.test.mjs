import assert from 'node:assert/strict'
import { afterEach, mock, test } from 'node:test'
import handler from '../api/app-data.js'

afterEach(() => mock.restoreAll())

function response() {
  return {
    headers: {},
    setHeader(key, value) { this.headers[key] = value },
    end(body) { this.body = JSON.parse(body) },
  }
}

test('each reload resolves the current head and reads all six files at that revision', async () => {
  let revision = 'a'.repeat(40)
  const reads = []
  mock.method(globalThis, 'fetch', async (url) => {
    if (url.includes('/commits/')) return Response.json({ sha: revision })
    reads.push(url)
    return Response.json({ rows: [], meta: { updatedAt: revision } })
  })
  for (const sha of ['a'.repeat(40), 'b'.repeat(40)]) {
    revision = sha
    const res = response()
    await handler({ method: 'GET' }, res)
    assert.equal(res.statusCode, 200)
    assert.equal(res.headers['cache-control'], 'no-store')
    assert.equal(res.body.sourceRevision, sha)
    assert.equal(Object.keys(res.body).length, 7)
    for (const payload of Object.values(res.body).filter((value) => typeof value === 'object')) {
      assert.equal(payload.meta.updatedAt, sha)
    }
    assert.ok(reads.slice(-6).every((url) => url.includes(`/${sha}/web/public/api/`)))
  }
})

test('a failed file returns an error instead of a partial or previous snapshot', async () => {
  mock.method(console, 'error', () => {})
  mock.method(globalThis, 'fetch', async (url) => {
    if (url.includes('/commits/')) return Response.json({ sha: 'a'.repeat(40) })
    if (url.includes('technical.json')) return new Response('', { status: 503 })
    return Response.json({ rows: [] })
  })
  const res = response()
  await handler({ method: 'GET' }, res)
  assert.equal(res.statusCode, 502)
  assert.deepEqual(Object.keys(res.body), ['error'])
})

test('the authenticated fallback keeps the same immutable revision', async () => {
  const sha = 'c'.repeat(40)
  const fallbackUrls = []
  mock.method(globalThis, 'fetch', async (url) => {
    if (url.includes('/commits/')) return Response.json({ sha })
    if (url.includes('raw.githubusercontent.com')) return new Response('', { status: 429 })
    fallbackUrls.push(url)
    return Response.json({ rows: [] })
  })
  const res = response()
  await handler({ method: 'GET' }, res)
  assert.equal(res.statusCode, 200)
  assert.equal(fallbackUrls.length, 6)
  assert.ok(fallbackUrls.every((url) => url.endsWith(`?ref=${sha}`)))
})
