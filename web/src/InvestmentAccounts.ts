export const accountTypes = ['퇴직연금', 'IRP', 'ISA', '일반증권'] as const
export const buyTimings = {
  월초: '거래소 첫 거래일',
  중순: '15일 또는 이후 첫 거래일',
  월말: '거래소 마지막 거래일',
} as const

export type InvestmentAccount = {
  id: string
  nickname: string
  accountNumber: string
  type: typeof accountTypes[number]
  initialCapital?: number
  frequency?: 'weekly' | 'monthly'
  dayOfWeek?: number
  dayOfMonth?: number
  collecting?: { ticker: string; percent: number }[]
  monthlyDeposit: number
  buyTiming: keyof typeof buyTimings
}

export function normalizeInvestmentAccounts(value: unknown): InvestmentAccount[] {
  if (!Array.isArray(value)) return []
  const ids = new Set<string>()
  return value.flatMap((row: Partial<InvestmentAccount> | null) => {
    if (!row || typeof row.id !== 'string' || !row.id || ids.has(row.id)
      || typeof row.nickname !== 'string' || !row.nickname.trim()
      || !row.type || !accountTypes.includes(row.type)
      || !row.buyTiming || !Object.hasOwn(buyTimings, row.buyTiming)
      || typeof row.monthlyDeposit !== 'number' || !Number.isSafeInteger(row.monthlyDeposit)
      || row.monthlyDeposit < 0) return []
    ids.add(row.id)
    return [{
      id: row.id,
      nickname: row.nickname.trim().slice(0, 40),
      accountNumber: typeof row.accountNumber === 'string' && /^[0-9-]{0,32}$/.test(row.accountNumber) ? row.accountNumber : '',
      type: row.type,
      initialCapital: Number.isSafeInteger(row.initialCapital) && row.initialCapital! >= 0 ? row.initialCapital : 0,
      frequency: row.frequency === 'weekly' ? 'weekly' : 'monthly',
      dayOfWeek: Number.isInteger(row.dayOfWeek) && row.dayOfWeek! >= 0 && row.dayOfWeek! <= 6 ? row.dayOfWeek : 1,
      dayOfMonth: Number.isInteger(row.dayOfMonth) && row.dayOfMonth! >= 1 && row.dayOfMonth! <= 31 ? row.dayOfMonth : 1,
      collecting: Array.isArray(row.collecting) ? row.collecting.filter((item) =>
        item && typeof item.ticker === 'string' && /^[A-Z0-9.^=-]+$/.test(item.ticker)
        && Number.isInteger(item.percent) && item.percent > 0 && item.percent <= 100) : [],
      monthlyDeposit: row.monthlyDeposit,
      buyTiming: row.buyTiming,
    }]
  })
}
