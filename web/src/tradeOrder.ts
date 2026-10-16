type SignalDates = { buyDate: string; sellDate: string; sellTimestamp?: string; lastSignalEmailSentAt?: string; lastSignalEmailDate?: string }

function timestamp(value: string) {
  const parsed = Date.parse(value.replace(/^(\d{4})\.(\d{2})\.(\d{2})/, '$1-$2-$3'))
  return Number.isFinite(parsed) ? parsed : 0
}

export function compareTradeSignals(a: SignalDates, b: SignalDates, direction: 'asc' | 'desc' = 'desc', aOrder = 0, bOrder = 0) {
  const lastDay = (trade: SignalDates) => {
    const value = timestamp(trade.sellDate) ? trade.sellDate : trade.buyDate
    return timestamp(value.replaceAll('.', '-').slice(0, 10))
  }
  const mailTime = (trade: SignalDates) => trade.lastSignalEmailDate && timestamp(trade.lastSignalEmailDate) === lastDay(trade)
    ? timestamp(trade.lastSignalEmailSentAt || '') : 0
  const difference = lastDay(a) - lastDay(b) || mailTime(a) - mailTime(b) || timestamp(a.buyDate) - timestamp(b.buyDate) || aOrder - bOrder
  return difference === 0 ? 0 : direction === 'asc' ? difference : -difference
}
