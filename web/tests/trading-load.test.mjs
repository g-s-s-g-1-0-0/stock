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

test('buy date alone orders trades even when older positions exit later', () => {
  const trades = [
    { buyDate: '2026.09.02', sellDate: '2026.10.02T01:00:00Z' },
    { buyDate: '2026.09.01', sellDate: '2026.10.02T22:00:00Z' },
    { buyDate: '2026.09.30', sellDate: '보유 중' },
  ]
  assert.deepEqual(trades.slice().sort(compareTradeSignals).map((t) => t.buyDate), ['2026.09.30', '2026.09.02', '2026.09.01'])
  assert.equal(compareTradeSignals(trades[0], { ...trades[0] }), 0)
  assert.ok(compareTradeSignals(trades[1], trades[0], 'desc') > 0)
})

test('date-only signals use newest appended record first, including the reported three stocks', () => {
  const trades = ['VST', 'NBIS', '039030'].map((ticker, index) => ({ ticker, index, buyDate: '2026.10.16', sellDate: '-' }))
  const sort = (direction) => trades.slice().sort((a, b) => compareTradeSignals(a, b, direction, a.index, b.index)).map((trade) => trade.ticker)
  assert.deepEqual(sort('desc'), ['039030', 'NBIS', 'VST'])
  assert.deepEqual(sort('asc'), ['VST', 'NBIS', '039030'])
})

test('NBIS stays below the later EO Technics buy after a stop loss or any email', () => {
  const nebius = { ticker: 'NBIS', buyDate: '2026.10.16', sellDate: '보유 중' }
  const eo = { ticker: '039030', buyDate: '2026.10.16', sellDate: '보유 중' }
  const sort = (nbis, direction) => [nbis, eo].sort((a, b) => compareTradeSignals(
    a, b, direction, a.ticker === 'NBIS' ? 1 : 2, b.ticker === 'NBIS' ? 1 : 2,
  )).map((t) => t.ticker)
  const exited = { ...nebius, sellDate: '2026.10.17', sellTimestamp: '2026-10-17T10:00:00Z',
    lastSignalEmailSentAt: '2026-10-17T10:01:00Z', lastSignalEmailDate: '2026.10.17' }
  assert.deepEqual(sort(nebius, 'desc'), ['039030', 'NBIS'])
  assert.deepEqual(sort(exited, 'desc'), sort(nebius, 'desc'))
  assert.deepEqual(sort(exited, 'asc'), ['NBIS', '039030'])
  // Even a same-day sale email cannot alter the original buy order.
  assert.deepEqual(sort({ ...exited, sellDate: '2026.10.16', lastSignalEmailDate: '2026.10.16' }, 'desc'), sort(nebius, 'desc'))
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
