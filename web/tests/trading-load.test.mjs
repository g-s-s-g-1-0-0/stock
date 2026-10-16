import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { afterEach, mock, test } from 'node:test'
import ts from 'typescript'

async function sourceModule(file) {
  const source = readFileSync(new URL(file, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2023 } })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

const { readRequest } = await sourceModule('../src/readRequest.ts')
const { compareTradeSignals } = await sourceModule('../src/tradeOrder.ts')
afterEach(() => mock.restoreAll())

test('overlapping app loads share one request and the next refresh reads again', async () => {
  const source = readFileSync(new URL('../src/api.ts', import.meta.url), 'utf8')
    .replace("import { readRequest } from './readRequest'", 'const readRequest = (...args) => fetch(...args)')
    .replaceAll('import.meta.env', '({ PROD: true, DEV: false })')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
  const { fetchAppData } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
  let calls = 0
  mock.method(globalThis, 'fetch', async () => {
    calls += 1
    return Response.json(Object.fromEntries(['stocks', 'valuation', 'technical', 'marketEvents', 'marketTrends', 'tradeLogs'].map((key) => [key, { rows: [] }])))
  })
  await Promise.all([fetchAppData(), fetchAppData(), fetchAppData()])
  assert.equal(calls, 1)
  await fetchAppData()
  assert.equal(calls, 2)
})

test('last signal day ignores sell time and uses earliest first signal for ties', () => {
  const trades = [
    { buyDate: '2026.09.02', sellDate: '2026.10.02T01:00:00Z' },
    { buyDate: '2026.09.01', sellDate: '2026.10.02T22:00:00Z' },
    { buyDate: '2026.09.30', sellDate: '보유 중' },
  ]
  assert.deepEqual(trades.slice().sort(compareTradeSignals).map((t) => t.buyDate), ['2026.09.01', '2026.09.02', '2026.09.30'])
  assert.equal(compareTradeSignals(trades[0], { ...trades[0] }), 0)
  assert.ok(compareTradeSignals(trades[1], trades[0], 'desc') < 0)
})

test('healthy reads have no additional request and temporary failures recover', async () => {
  let calls = 0
  mock.method(globalThis, 'fetch', async () => {
    calls += 1
    if (calls === 2) throw new TypeError('Failed to fetch')
    return Response.json({ ok: true })
  })
  assert.equal((await readRequest('/api/app-data')).status, 200)
  assert.equal(calls, 1)
  assert.equal((await readRequest('/api/app-data')).status, 200)
  assert.equal(calls, 3)
})

test('permanent errors and writes are never retried; transient retries are bounded', async () => {
  let calls = 0
  let status = 401
  mock.method(globalThis, 'fetch', async () => { calls += 1; return new Response('', { status }) })
  await readRequest('/api/account')
  assert.equal(calls, 1)
  status = 503
  await readRequest('/api/account', { method: 'POST' })
  assert.equal(calls, 2)
  await readRequest('/api/account')
  assert.equal(calls, 5)
})
