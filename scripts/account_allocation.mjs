import { calculateAccountPortfolio } from '../web/src/accountAllocation.mjs'
let raw = ''
for await (const chunk of process.stdin) raw += chunk
const input = JSON.parse(raw)
const trades = input.trades || []
const result = new Map()
for (const type of ['swing', 'long_term']) {
  const scoped = trades.filter((t) => (t.investmentType || (t.manualExit ? 'long_term' : 'swing')) === type)
  const summary = calculateAccountPortfolio(scoped, input.stocks, input.trends, input.settings, type, undefined, input.asOf)
  for (let i = 0; i < scoped.length; i++) result.set(scoped[i], summary.trades[i])
}
process.stdout.write(JSON.stringify(trades.map((t) => result.get(t) || t)))
