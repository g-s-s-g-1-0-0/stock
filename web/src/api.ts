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
  yearLabel?: string
  months?: string[]
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
      const response = await fetch(path, { cache: 'no-store' })
      if (response.ok) return await response.json() as T
    } catch {
      // Try the next cache location.
    }
  }
  return null
}

export async function fetchAppData<TStock, TMetric, TGroup, TTrendRow>() {
  const [stocks, valuation, technical, marketEvents, marketTrends] = await Promise.all([
    fetchJson<ApiStocksPayload<TStock>>(['/api/stocks', 'http://127.0.0.1:8787/api/stocks', '/api/stocks.json']),
    fetchJson<ApiValuationPayload<TMetric>>(['/api/valuation', 'http://127.0.0.1:8787/api/valuation', '/api/valuation.json']),
    fetchJson<ApiTechnicalPayload>(['/api/technical', 'http://127.0.0.1:8787/api/technical', '/api/technical.json']),
    fetchJson<ApiMarketEventsPayload<TGroup>>(['/api/market-events', 'http://127.0.0.1:8787/api/market-events', '/api/market-events.json']),
    fetchJson<ApiMarketTrendsPayload<TTrendRow>>(['/api/market-trends', 'http://127.0.0.1:8787/api/market-trends', '/api/market-trends.json']),
  ])

  return { stocks, valuation, technical, marketEvents, marketTrends }
}

export async function saveMarketEvents<TGroup>(
  groups: TGroup[],
  meta?: RuntimeMeta,
  options?: { yearLabel?: string; months?: string[] },
) {
  const payload = {
    meta: {
      ...meta,
      kind: 'market-events',
      schedule: 'manual',
      updatedAt: new Date().toISOString(),
      lastSuccessfulRun: new Date().toISOString(),
      failedReason: null,
    },
    yearLabel: options?.yearLabel,
    months: options?.months,
    groups,
  }

  const endpoints = ['/api/admin/market-events', 'http://127.0.0.1:8787/api/admin/market-events']
  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (response.ok) {
        return await response.json() as { meta: RuntimeMeta; yearLabel?: string; months?: string[]; groups: TGroup[] }
      }
    } catch {
      // Try the local API server fallback.
    }
  }

  throw new Error('시장 주요 이벤트 저장에 실패했습니다.')
}

export async function refreshAppData(tickers: string[]) {
  const endpoints = ['/api/admin/refresh-data', 'http://127.0.0.1:8787/api/admin/refresh-data']
  let lastError = ''

  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tickers }),
      })

      if (response.ok) {
        return await response.json() as { ok: boolean; refreshedTickers: string[] }
      }

      const payload = await response.json().catch(() => null) as { error?: string } | null
      lastError = payload?.error ?? response.statusText
    } catch {
      // Try the local API server fallback.
    }
  }

  throw new Error(lastError || '데이터 즉시 갱신에 실패했습니다.')
}
