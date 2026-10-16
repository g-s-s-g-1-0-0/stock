type SignalDates = { buyDate: string }

function timestamp(value: string) {
  const parsed = Date.parse(value.replace(/^(\d{4})\.(\d{2})\.(\d{2})/, '$1-$2-$3'))
  return Number.isFinite(parsed) ? parsed : 0
}

// Buy date and original append order are stable when a position exits or gets email.
export function compareTradeSignals(a: SignalDates, b: SignalDates, direction: 'asc' | 'desc' = 'desc', aOrder = 0, bOrder = 0) {
  const difference = timestamp(a.buyDate) - timestamp(b.buyDate) || aOrder - bOrder
  return difference === 0 ? 0 : direction === 'asc' ? difference : -difference
}
