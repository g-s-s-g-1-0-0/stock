const FILES = {
  stocks: 'stocks.json',
  valuation: 'valuation.json',
  technical: 'technical.json',
  marketEvents: 'market-events.json',
  marketTrends: 'market-trends.json',
  tradeLogs: 'trade-logs.json',
}

let snapshotKey
let snapshotPromise

async function readSource(url, options) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await fetch(url, { ...options, signal: AbortSignal.timeout(8000) })
      if (response.ok || ![408, 429, 500, 502, 503, 504].includes(response.status) || attempt >= 1) return response
    } catch (error) {
      if (attempt >= 1) throw error
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
}

function readSnapshot(repo, sha, headers) {
  const key = `${repo}:${sha}`
  if (snapshotKey === key && snapshotPromise) return snapshotPromise
  snapshotKey = key
  snapshotPromise = Promise.all(Object.entries(FILES).map(async ([key, name]) => {
    const path = `web/public/api/${name}`
    let response
    try {
      response = await fetch(`https://raw.githubusercontent.com/${repo}/${sha}/${path}`, { signal: AbortSignal.timeout(5000) })
      if (response.ok) {
        const payload = await response.json()
        if (payload && typeof payload === 'object') return [key, payload]
      }
    } catch {
      // A disconnected raw host must also reach the authenticated fallback.
    }
    response = await readSource(`https://api.github.com/repos/${repo}/contents/${path}?ref=${sha}`, {
        cache: 'no-store',
        headers: { ...headers, accept: 'application/vnd.github.raw+json' },
    })
    if (!response.ok) throw new Error(`${name}: ${response.status}`)
    const payload = await response.json()
    if (!payload || typeof payload !== 'object') throw new Error(`${name}: Invalid payload.`)
    return [key, payload]
  })).then((entries) => ({ ...Object.fromEntries(entries), sourceRevision: sha })).catch((error) => {
    if (snapshotKey === key) snapshotPromise = undefined
    throw error
  })
  return snapshotPromise
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
  const headers = {
    accept: 'application/vnd.github+json',
    'user-agent': 'gongsuseongga-app-data',
    'cache-control': 'no-cache',
    ...(process.env.GITHUB_ACTIONS_TOKEN ? { authorization: `Bearer ${process.env.GITHUB_ACTIONS_TOKEN}` } : {}),
  }
  // live-data first, then the code branch. A missing branch falls through to main.
  const refs = [...new Set([process.env.GITHUB_DATA_REF || 'live-data', process.env.GITHUB_REFRESH_REF || 'main'])]
  try {
    let sha = ''
    let lastStatus = 0
    for (const ref of refs) {
      const head = await readSource(`https://api.github.com/repos/${repo}/commits/${encodeURIComponent(ref)}`, { cache: 'no-store', headers })
      lastStatus = head.status
      if (!head.ok) continue
      const body = await head.json()
      if (/^[a-f0-9]{40}$/i.test(body.sha || '')) {
        sha = body.sha
        break
      }
    }
    if (!sha) throw new Error(`Head lookup failed: ${lastStatus}`)

    const snapshot = await readSnapshot(repo, sha, headers)
    res.statusCode = 200
    return res.end(JSON.stringify(snapshot))
  } catch (error) {
    console.error('[app-data]', error instanceof Error ? error.message : 'Source unavailable.')
    res.statusCode = 502
    return res.end(JSON.stringify({ error: '최신 데이터를 불러오지 못했습니다. 다시 시도해 주세요.' }))
  }
}
