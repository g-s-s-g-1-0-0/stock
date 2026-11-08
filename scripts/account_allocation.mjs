import { calculateAccountPortfolio } from '../web/src/accountAllocation.mjs'
let raw = ''
for await (const chunk of process.stdin) raw += chunk
const input = JSON.parse(raw)
const trades = input.trades || []
const result = new Map()
for (const type of ['swing', 'long_term']) {
  const scoped = trades.filter((t) => (t.investmentType || (t.manualExit ? 'long_term' : 'swing')) === type)
  const accountIds = new Set(scoped.map((trade) => trade.investmentAccountId || 'default'))
  for (const accountId of accountIds) {
    const accountTrades = scoped.filter((trade) => (trade.investmentAccountId || 'default') === accountId)
    const account = input.settings?.accounts?.find((item) => item.id === accountId)
    const settings = accountId !== 'default' && account ? {
      ...input.settings,
      initialCapital: account.initialCapital ?? 0,
      amount: account.monthlyDeposit ?? 0,
      frequency: account.frequency ?? 'monthly',
      monthOfYear: account.monthOfYear ?? 1,
      dayOfWeek: account.dayOfWeek ?? 1,
      dayOfMonth: account.dayOfMonth ?? 1,
    } : input.settings
    const summary = calculateAccountPortfolio(accountTrades, input.stocks, input.trends, settings, type, undefined, input.asOf)
    for (let i = 0; i < accountTrades.length; i++) result.set(accountTrades[i], summary.trades[i])
  }
}
process.stdout.write(JSON.stringify(trades.map((t) => result.get(t) || t)))
