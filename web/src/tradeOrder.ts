type SignalDates = { buyDate: string; sellDate: string; sellTimestamp?: string }

function timestamp(value: string) {
  const parsed = Date.parse(value.replaceAll('.', '-'))
  return Number.isFinite(parsed) ? parsed : 0
}

export function compareTradeSignals(a: SignalDates, b: SignalDates, direction: 'asc' | 'desc' = 'asc') {
  const lastDay = (trade: SignalDates) => {
    const value = timestamp(trade.sellDate) ? trade.sellDate : trade.buyDate
    return timestamp(value.replaceAll('.', '-').slice(0, 10))
  }
  const difference = lastDay(a) - lastDay(b)
  return (direction === 'asc' ? difference : -difference) || timestamp(a.buyDate) - timestamp(b.buyDate)
}
