export type RuntimeMeta = {
  kind?: string
  schedule?: string
  updatedAt?: string
  lastSuccessfulRun?: string | null
  failedReason?: string | null
}

export type ApiTechnicalPayload = {
  meta?: RuntimeMeta
  marketSnapshot?: string[][]
  rows?: Record<string, Record<string, string>>
}

export type ApiStocksPayload<TStock> = {
  meta?: RuntimeMeta
  rows?: TStock[]
}

export type ApiValuationPayload<TMetric> = {
  meta?: RuntimeMeta
  rows?: Record<string, TMetric>
}

export type ApiMarketEventsPayload<TGroup> = {
  meta?: RuntimeMeta
  groups?: TGroup[]
}

export type ApiMarketTrendsPayload<TRow> = {
  meta?: RuntimeMeta
  rows?: TRow[]
}

export type AppData<TStock, TMetric, TGroup, TTrendRow> = {
  stocks: ApiStocksPayload<TStock> | null
  valuation: ApiValuationPayload<TMetric> | null
  technical: ApiTechnicalPayload | null
  marketEvents: ApiMarketEventsPayload<TGroup> | null
  marketTrends: ApiMarketTrendsPayload<TTrendRow> | null
}

async function fetchJson<T>(paths: string[]): Promise<T | null> {
  for (const path of paths) {
    try {
      const response = await fetch(path)
      if (response.ok) return await response.json() as T
    } catch {
      // Try the next cache location.
    }
  }
  return null
}

export async function fetchAppData<TStock, TMetric, TGroup, TTrendRow>() {
  const [stocks, valuation, technical, marketEvents, marketTrends] = await Promise.all([
    fetchJson<ApiStocksPayload<TStock>>(['/api/stocks', '/api/stocks.json']),
    fetchJson<ApiValuationPayload<TMetric>>(['/api/valuation', '/api/valuation.json']),
    fetchJson<ApiTechnicalPayload>(['/api/technical', '/api/technical.json']),
    fetchJson<ApiMarketEventsPayload<TGroup>>(['/api/market-events', '/api/market-events.json']),
    fetchJson<ApiMarketTrendsPayload<TTrendRow>>(['/api/market-trends', '/api/market-trends.json']),
  ])

  return { stocks, valuation, technical, marketEvents, marketTrends }
}

export async function saveMarketEvents<TGroup>(groups: TGroup[], meta?: RuntimeMeta) {
  const payload = {
    meta: {
      ...meta,
      kind: 'market-events',
      schedule: 'manual',
      updatedAt: new Date().toISOString(),
      lastSuccessfulRun: new Date().toISOString(),
      failedReason: null,
    },
    groups,
  }

  const response = await fetch('/api/admin/market-events', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error('시장 주요 이벤트 저장에 실패했습니다.')
  }
  return await response.json() as { meta: RuntimeMeta; groups: TGroup[] }
}
