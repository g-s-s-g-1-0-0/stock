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

export type ApiStockSearchPayload<TStock> = {
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

export type ApiTradeLogsPayload<TTradeLog> = {
  meta?: RuntimeMeta
  rows?: TTradeLog[]
}

export type AppData<TStock, TMetric, TGroup, TTrendRow, TTradeLog = unknown> = {
  stocks: ApiStocksPayload<TStock> | null
  valuation: ApiValuationPayload<TMetric> | null
  technical: ApiTechnicalPayload | null
  marketEvents: ApiMarketEventsPayload<TGroup> | null
  marketTrends: ApiMarketTrendsPayload<TTrendRow> | null
  tradeLogs: ApiTradeLogsPayload<TTradeLog> | null
}

async function fetchJson<T>(paths: string[]): Promise<T | null> {
  for (const path of paths) {
    try {
      const separator = path.includes('?') ? '&' : '?'
      const response = await fetch(`${path}${separator}v=${Date.now()}`, { cache: 'no-store' })
      if (response.ok) return await response.json() as T
    } catch {
      // Try the next cache location.
    }
  }
  return null
}

const dataPaths = {
  stocks: import.meta.env.DEV ? ['/api/stocks.json', '/api/stocks', 'http://127.0.0.1:8787/api/stocks'] : ['/api/stocks.json'],
  valuation: import.meta.env.DEV ? ['/api/valuation.json', '/api/valuation', 'http://127.0.0.1:8787/api/valuation'] : ['/api/valuation.json'],
  technical: import.meta.env.DEV ? ['/api/technical.json', '/api/technical', 'http://127.0.0.1:8787/api/technical'] : ['/api/technical.json'],
  marketEvents: import.meta.env.DEV ? ['/api/market-events.json', '/api/market-events', 'http://127.0.0.1:8787/api/market-events'] : ['/api/market-events.json'],
  marketTrends: import.meta.env.DEV ? ['/api/market-trends.json', '/api/market-trends', 'http://127.0.0.1:8787/api/market-trends'] : ['/api/market-trends.json'],
  tradeLogs: import.meta.env.DEV ? ['/api/trade-logs.json', '/api/trade-logs', 'http://127.0.0.1:8787/api/trade-logs'] : ['/api/trade-logs.json'],
  stockSearch: import.meta.env.DEV ? ['/api/stock-search.json', '/api/stock-search', 'http://127.0.0.1:8787/api/stock-search'] : ['/api/stock-search.json'],
}

export async function fetchAppData<TStock, TMetric, TGroup, TTrendRow, TTradeLog = unknown>() {
  const [stocks, valuation, technical, marketEvents, marketTrends, tradeLogs] = await Promise.all([
    fetchJson<ApiStocksPayload<TStock>>(dataPaths.stocks),
    fetchJson<ApiValuationPayload<TMetric>>(dataPaths.valuation),
    fetchJson<ApiTechnicalPayload>(dataPaths.technical),
    fetchJson<ApiMarketEventsPayload<TGroup>>(dataPaths.marketEvents),
    fetchJson<ApiMarketTrendsPayload<TTrendRow>>(dataPaths.marketTrends),
    fetchJson<ApiTradeLogsPayload<TTradeLog>>(dataPaths.tradeLogs),
  ])

  return { stocks, valuation, technical, marketEvents, marketTrends, tradeLogs }
}

export async function fetchStockSearchData<TStock>() {
  return fetchJson<ApiStockSearchPayload<TStock>>(dataPaths.stockSearch)
}

export async function saveMarketEvents<TGroup>(
  groups: TGroup[],
  meta?: RuntimeMeta,
  options?: { yearLabel?: string; months?: string[]; accessToken?: string },
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
        headers: {
          'content-type': 'application/json',
          ...(options?.accessToken ? { authorization: `Bearer ${options.accessToken}` } : {}),
        },
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

export async function saveMarketTrends<TRow>(
  rows: TRow[],
  meta?: RuntimeMeta,
  options?: { accessToken?: string },
) {
  const payload = {
    meta: {
      ...meta,
      kind: 'market-trends',
      schedule: 'manual',
      updatedAt: new Date().toISOString(),
      lastSuccessfulRun: new Date().toISOString(),
      failedReason: null,
    },
    rows,
  }

  const endpoints = ['/api/admin/market-trends', 'http://127.0.0.1:8787/api/admin/market-trends']
  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint, {
        method: 'PUT',
        headers: {
          'content-type': 'application/json',
          ...(options?.accessToken ? { authorization: `Bearer ${options.accessToken}` } : {}),
        },
        body: JSON.stringify(payload),
      })
      if (response.ok) {
        return await response.json() as { meta: RuntimeMeta; rows: TRow[] }
      }
    } catch {
      // Try the local API server fallback.
    }
  }

  throw new Error('시장 트렌드 저장에 실패했습니다.')
}

export async function refreshAppData(tickers: string[], accessToken?: string, scope = 'analysis') {
  const endpoints = import.meta.env.DEV
    ? ['/api/admin/trigger-refresh', '/api/admin/refresh-data', 'http://127.0.0.1:8787/api/admin/refresh-data']
    : ['/api/admin/trigger-refresh']
  let lastError = ''

  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({ tickers, scope }),
      })

      if (response.ok) {
        const payload = await response.json() as {
          ok: boolean
          refreshedTickers?: string[]
          mode?: 'workflow_dispatch'
          message?: string
          actionsUrl?: string
        }
        return {
          ...payload,
          refreshedTickers: payload.refreshedTickers ?? tickers,
        }
      }

      const payload = await response.json().catch(() => null) as { error?: string } | null
      lastError = payload?.error ?? response.statusText
    } catch {
      // Try the next refresh endpoint fallback.
    }
  }

  throw new Error(lastError || '데이터 즉시 갱신에 실패했습니다.')
}
