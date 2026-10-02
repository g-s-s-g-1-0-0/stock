const FILES = {
  stocks: 'stocks.json',
  valuation: 'valuation.json',
  technical: 'technical.json',
  marketEvents: 'market-events.json',
  marketTrends: 'market-trends.json',
  tradeLogs: 'trade-logs.json',
}

export default async function handler(req, res) {
  res.setHeader('cache-control', 'no-store')
  res.setHeader('content-type', 'application/json; charset=utf-8')
  if (req.method !== 'GET') {
    res.setHeader('allow', 'GET')
    res.statusCode = 405
    return res.end(JSON.stringify({ error: 'Method not allowed.' }))
  }

  const repo = process.env.GITHUB_REPO || 'g-s-s-g-1-0-0/stock'
  const ref = process.env.GITHUB_REFRESH_REF || 'main'
  const headers = {
    accept: 'application/vnd.github+json',
    'user-agent': 'gongsuseongga-app-data',
    'cache-control': 'no-cache',
    ...(process.env.GITHUB_ACTIONS_TOKEN ? { authorization: `Bearer ${process.env.GITHUB_ACTIONS_TOKEN}` } : {}),
  }
  try {
    const head = await fetch(`https://api.github.com/repos/${repo}/commits/${encodeURIComponent(ref)}`, { cache: 'no-store', headers })
    if (!head.ok) throw new Error(`Head lookup failed: ${head.status}`)
    const { sha } = await head.json()
    if (!/^[a-f0-9]{40}$/i.test(sha || '')) throw new Error('Invalid source revision.')

    const entries = await Promise.all(Object.entries(FILES).map(async ([key, name]) => {
      const path = `web/public/api/${name}`
      let response = await fetch(`https://raw.githubusercontent.com/${repo}/${sha}/${path}`)
      if (!response.ok) {
        response = await fetch(`https://api.github.com/repos/${repo}/contents/${path}?ref=${sha}`, {
          cache: 'no-store',
          headers: { ...headers, accept: 'application/vnd.github.raw+json' },
        })
      }
      if (!response.ok) throw new Error(`${name}: ${response.status}`)
      const payload = await response.json()
      if (!payload || typeof payload !== 'object') throw new Error(`${name}: Invalid payload.`)
      return [key, payload]
    }))
    res.statusCode = 200
    return res.end(JSON.stringify({ ...Object.fromEntries(entries), sourceRevision: sha }))
  } catch (error) {
    console.error('[app-data]', error instanceof Error ? error.message : 'Source unavailable.')
    res.statusCode = 502
    return res.end(JSON.stringify({ error: '최신 데이터를 불러오지 못했습니다. 다시 시도해 주세요.' }))
  }
}
