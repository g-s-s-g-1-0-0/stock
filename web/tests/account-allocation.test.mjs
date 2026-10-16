import test from 'node:test'
import assert from 'node:assert/strict'
import { calculateAccountPortfolio as calculate } from '../src/accountAllocation.mjs'

const trade = (ticker, overrides = {}) => ({ slotId: ticker, ticker, name: ticker, investmentType: 'swing',
  strategy: '3. 정상장 볼린저 워시아웃', buyDate: '2026.10.15', buyPrice: '$100', currentPrice: '$100',
  status: '보유 중', sellDate: '보유 중', sellPrice: '-', riskGroup: ticker, ...overrides })
const settings = (overrides = {}, allocation = {}) => ({ initialCapital: 10000000, amount: 0,
  allocationByInvestmentType: { swing: {slotCount: 2, slotPercents: [10,10], megaTrendOnly: false, ...allocation}}, ...overrides })
const calc = (rows, config = settings(), stocks = [], trends = []) => calculate(rows, stocks, trends, config, 'swing', undefined, '2026-10-17T00:00:00Z')

test('slot overflow becomes deferred everywhere, including QQQ QLD UBER; replay is idempotent', () => {
  const result = calc(['AAA','BBB','QQQ','QLD','UBER'].map((t) => trade(t)))
  assert.equal(result.trades.filter((t) => t.status === '보유 중').length, 2)
  for (const t of result.trades.filter((t) => ['QQQ','QLD','UBER'].includes(t.ticker))) {
    assert.equal(t.status, '매수 보류'); assert.equal(t.investmentAmount, 0); assert.equal(t.sellDate, '-')
    assert.match(t.allocationReason, /2슬롯/)
  }
  assert.equal(result.openInvestmentAmount, 2000000)
  assert.equal(result.totalAsset, 10000000)
  assert.deepEqual(calc(result.trades).trades, result.trades)
})

test('cash, industry cap, duplicate ticker, zero weight and explicit zero have actionable reasons', () => {
  assert.match(calc([trade('A')], settings({initialCapital:0})).trades[0].allocationReason, /현금/)
  assert.match(calc(['A','B','C'].map((t) => trade(t,{riskGroup:'반도체'})),settings({}, {slotCount:3,slotPercents:[10,10,10]})).trades[2].allocationReason, /산업/)
  const duplicate = calc([trade('A'),trade('A',{slotId:'A2'})]).trades[1]
  assert.equal(duplicate.status, '매수 보류'); assert.match(duplicate.allocationReason, /동일 종목/)
  assert.equal(calc([trade('A')],settings({}, {slotPercents:[0,10]})).trades[0].status, '매수 보류')
  const zero = calc([trade('A',{investmentAmount:0})])
  assert.deepEqual(calc(zero.trades).trades, zero.trades)
  assert.equal(zero.trades[0].investmentAmount, 0)
})

test('mega trend filter and leveraged allocation use the same historical week', () => {
  assert.match(calc([trade('QQQ')],settings({}, {megaTrendOnly:true})).trades[0].allocationReason, /메가트렌드/)
  const stocks = [{ticker:'QLD',name:'ProShares Ultra QQQ',industry:'AI 반도체 ETF'}]
  const trends = [{date:'2026.10.12',ranks:['AI 반도체 | 상승']}]
  const result = calc([trade('QLD',{name:'ProShares Ultra QQQ'})],settings({}, {megaTrendOnly:true}),stocks,trends)
  assert.equal(result.trades[0].investmentAmount,500000)
  assert.equal(result.trades[0].recommendedAllocationPercent,5)
})

test('deferred signals consume no cash or slots, and closed trades never reopen on replay', () => {
  const pending = trade('A',{status:'매수 보류',sellDate:'-',allocationReason:'서버 한도'})
  const result = calc([pending,trade('B')])
  assert.equal(result.trades[0].investmentAmount,0)
  assert.equal(result.trades[1].investmentAmount,1000000)
  const closed = {...result.trades[1],status:'익절',sellDate:'2026.10.16',returnPct:10}
  const replay = calc([closed])
  assert.equal(replay.trades[0].status,'익절')
  assert.equal(replay.cash,10100000)
  assert.equal(replay.realizedProfitAmount,100000)
  assert.deepEqual(calc(replay.trades).trades,replay.trades)
})

test('manual requested amount survives save/reload and scheduled cash respects UTC dates', () => {
  const first=calc([trade('A',{manualEntry:true,investmentAmount:200000})])
  assert.equal(first.trades[0].allocationRequestedAmount,200000)
  assert.deepEqual(calc(first.trades).trades,first.trades)
  const result=calc([trade('A',{buyDate:'2026.09.30'})],settings({initialCapital:0,amount:1000000,dayOfMonth:1}))
  assert.equal(result.trades[0].status,'매수 보류')
  assert.equal(result.cash,1000000)
})

test('closing a deferred signal never invents an investment or releases another position', () => {
  const pending = calc([trade('A',{status:'매수 보류',sellDate:'-'})]).trades[0]
  const closed = {...pending,status:'손절',sellDate:'2026.10.16',returnPct:-10}
  const result = calc([trade('A',{slotId:'actual',buyDate:'2026.10.14'}),closed,
    trade('A',{slotId:'later',buyDate:'2026.10.17'})])
  assert.equal(result.trades[1].investmentAmount,0)
  assert.equal(result.trades[2].status,'매수 보류')
  assert.match(result.trades[2].allocationReason,/동일 종목/)
  assert.equal(result.realizedProfitAmount,0)
})
