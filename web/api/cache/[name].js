// Server-side reader for the JSON caches the refresh workflow commits.
//
// The browser used to read raw.githubusercontent.com directly. That host rate
// limits per client IP and the app appends a cache-buster to every request, so
// every page load was a fresh unauthenticated hit; once raw answers 429 or 503
// the app silently falls back to the copy baked into the last Vite build, which
// is stale because cache-only commits skip the rebuild on purpose. The result is
// a page that shows an old timestamp while the workflow reports success.
//
// Reading through this function instead puts one server between the users and
// GitHub: responses are cached at the edge, so GitHub sees roughly one request
// per minute instead of one per page load, and a raw outage falls back to the
// authenticated contents API rather than to stale build output.

const ALLOWED = new Set([
  'stocks.json',
  'valuation.json',
  'technical.json',
  'market-events.json',
  'market-trends.json',
  'trade-logs.json',
  'stock-search.json',
])

const DEFAULT_REPO = 'g-s-s-g-1-0-0/stock'
const CACHE_DIR = 'web/public/api'

function repoRef() {
  return {
    repo: process.env.GITHUB_REPO || DEFAULT_REPO,
    ref: process.env.GITHUB_REFRESH_REF || 'main',
  }
}

async function fromRaw(name) {
  const { repo, ref } = repoRef()
  const response = await fetch(
    `https://raw.githubusercontent.com/${repo}/${ref}/${CACHE_DIR}/${name}`,
    { headers: { accept: 'application/json' } },
  )
  if (!response.ok) throw new Error(`raw responded ${response.status}`)
  return response.json()
}

async function fromContentsApi(name) {
  const { repo, ref } = repoRef()
  const token = process.env.GITHUB_ACTIONS_TOKEN
  const headers = {
    accept: 'application/vnd.github.raw+json',
    'user-agent': 'gongsuseongga-cache-reader',
    'x-github-api-version': '2022-11-28',
  }
  if (token) headers.authorization = `Bearer ${token}`

  const response = await fetch(
    `https://api.github.com/repos/${repo}/contents/${CACHE_DIR}/${name}?ref=${ref}`,
    { headers },
  )
  if (!response.ok) throw new Error(`contents API responded ${response.status}`)
  return response.json()
}

export default async function handler(req, res) {
  const name = String(req.query?.name || '')
  if (!ALLOWED.has(name)) {
    res.statusCode = 404
    res.setHeader('content-type', 'application/json; charset=utf-8')
    return res.end(JSON.stringify({ error: 'Unknown cache file.' }))
  }

  let payload = null
  const failures = []
  for (const read of [fromRaw, fromContentsApi]) {
    try {
      payload = await read(name)
      break
    } catch (error) {
      failures.push(error instanceof Error ? error.message : String(error))
    }
  }

  if (!payload) {
    // Let the client fall through to its own fallbacks rather than caching a miss.
    console.error('[cache-reader] every source failed', { name, failures })
    res.statusCode = 502
    res.setHeader('cache-control', 'no-store')
    res.setHeader('content-type', 'application/json; charset=utf-8')
    return res.end(JSON.stringify({ error: 'Cache source unavailable.', failures }))
  }

  // Refreshes land every two hours at most, so a minute of edge cache costs no
  // freshness while absorbing every page load in that window.
  res.statusCode = 200
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.setHeader('cache-control', 'public, max-age=0, s-maxage=60, stale-while-revalidate=600')
  return res.end(JSON.stringify(payload))
}
