type Summary<T> = {
  trades: T[]
  cash: number; projectedCash: number; totalCapital: number; investedAmount: number
  openInvestmentAmount: number; cumulativeInvestmentAmount: number; positionValue: number
  totalAsset: number; profitAmount: number; realizedProfitAmount: number
  unrealizedProfitAmount: number; profitRate: number; amountByTradeKey: Map<string, number>
}
export function calculateAccountPortfolio<T>(trades: T[], stocks: unknown[], trends: unknown[], settings: unknown, investmentType: string, initialCashOverride?: number, asOf?: string): Summary<T>
export function normalizeAccountSettings(settings?: unknown): unknown

export function accountTradeKey(trade: unknown): string

export function swingRiskGroupOverride(ticker: string): string | null
