import assert from 'node:assert/strict'
import { afterEach, mock, test } from 'node:test'
import handler, { publicPortfolio } from '../api/operator-portfolio.js'

afterEach(() => mock.restoreAll())

test('public portfolio strips account numbers and private nested fields', () => {
  const result = publicPortfolio({
    initialCapital: 100, secret: 'private',
    accounts: [{ id: 'a', nickname: '연금', accountNumber: 'secret-number', owner_id: 'private',
      brokerage: '삼성증권', collecting: [{ ticker: 'VOO', percent: 100, secret: 'private' }] }],
  })
  assert.equal(JSON.stringify(result).includes('private'), false)
  assert.equal(JSON.stringify(result).includes('secret'), false)
  assert.deepEqual(result.accounts[0].collecting, [{ ticker: 'VOO', percent: 100 }])
})

test('public endpoint rejects writes before accessing private data', async () => {
  mock.method(globalThis, 'fetch', () => { throw new Error('must not fetch') })
  const res = { setHeader() {}, end(body) { this.body = JSON.parse(body) } }
  await handler({ method: 'POST' }, res)
  assert.equal(res.statusCode, 405)
})
