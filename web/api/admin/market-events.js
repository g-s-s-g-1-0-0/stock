const DEFAULT_REPO = 'g-s-s-g-1-0-0/stock'
const MARKET_EVENT_PATHS = ['web/public/api/market-events.json', 'data/cache/market-events.json']

function json(res, statusCode, payload) {
  res.statusCode = statusCode
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(payload))
}

function readAdminEmails() {
  return (process.env.ADMIN_EMAILS || process.env.VITE_ADMIN_EMAILS || '')
    .split(',')
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean)
}

function readPayload(req) {
  if (typeof req.body === 'string') {
    return JSON.parse(req.body || '{}')
  }
  return req.body || {}
}

async function readSupabaseUser(accessToken) {
  const supabaseUrl = (process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || '').replace(/\/$/, '')
  const supabaseAnonKey = process.env.SUPABASE_ANON_KEY || process.env.VITE_SUPABASE_ANON_KEY || ''

  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Supabase environment variables are missing.')
  }

  const response = await fetch(`${supabaseUrl}/auth/v1/user`, {
    headers: {
      apikey: supabaseAnonKey,
      authorization: `Bearer ${accessToken}`,
    },
  })

  if (!response.ok) {
    throw new Error('Invalid Supabase session.')
  }

  return response.json()
}

async function requireAdmin(req) {
  const accessToken = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '').trim()
  if (!accessToken) {
    return { status: 401, error: '로그인이 필요합니다.' }
  }

  const user = await readSupabaseUser(accessToken)
  const userEmail = String(user.email || '').toLowerCase()
  if (!readAdminEmails().includes(userEmail)) {
    return { status: 403, error: '관리자만 시장 주요 이벤트를 저장할 수 있습니다.' }
  }

  return null
}

function githubConfig() {
  return {
    token: process.env.GITHUB_ACTIONS_TOKEN,
    repo: process.env.GITHUB_REPO || DEFAULT_REPO,
    ref: process.env.GITHUB_REFRESH_REF || 'main',
  }
}

async function githubRequest(path, options = {}) {
  const { token, repo } = githubConfig()
  if (!token) {
    throw new Error('GITHUB_ACTIONS_TOKEN is missing.')
  }

  const response = await fetch(`https://api.github.com/repos/${repo}${path}`, {
    ...options,
    headers: {
      accept: 'application/vnd.github+json',
      authorization: `Bearer ${token}`,
      'content-type': 'application/json',
      'user-agent': 'gongsuseongga-market-events',
      'x-github-api-version': '2022-11-28',
      ...(options.headers || {}),
    },
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `GitHub request failed with ${response.status}.`)
  }

  return response.status === 204 ? null : response.json()
}

async function commitMarketEvents(payload) {
  const { ref } = githubConfig()
  const refPath = ref.split('/').map(encodeURIComponent).join('/')
  const branchRef = await githubRequest(`/git/ref/heads/${refPath}`)
  const headSha = branchRef.object?.sha
  if (!headSha) {
    throw new Error(`GitHub ref not found: ${ref}`)
  }

  const headCommit = await githubRequest(`/git/commits/${headSha}`)
  const content = JSON.stringify(payload, null, 2) + '\n'
  const entries = await Promise.all(MARKET_EVENT_PATHS.map(async (path) => {
    const blob = await githubRequest('/git/blobs', {
      method: 'POST',
      body: JSON.stringify({
        content: Buffer.from(content, 'utf8').toString('base64'),
        encoding: 'base64',
      }),
    })
    return {
      path,
      mode: '100644',
      type: 'blob',
      sha: blob.sha,
    }
  }))

  const tree = await githubRequest('/git/trees', {
    method: 'POST',
    body: JSON.stringify({
      base_tree: headCommit.tree?.sha,
      tree: entries,
    }),
  })
  const commit = await githubRequest('/git/commits', {
    method: 'POST',
    body: JSON.stringify({
      message: 'Update market events',
      tree: tree.sha,
      parents: [headSha],
    }),
  })

  await githubRequest(`/git/refs/heads/${refPath}`, {
    method: 'PATCH',
    body: JSON.stringify({ sha: commit.sha }),
  })

  return commit.sha
}

export default async function handler(req, res) {
  if (req.method !== 'PUT') {
    res.setHeader('allow', 'PUT')
    return json(res, 405, { error: 'Method not allowed.' })
  }

  try {
    const authError = await requireAdmin(req)
    if (authError) {
      return json(res, authError.status, { error: authError.error })
    }

    let payload
    try {
      payload = readPayload(req)
    } catch {
      return json(res, 400, { error: 'invalid json' })
    }
    if (!payload || !Array.isArray(payload.groups)) {
      return json(res, 400, { error: 'groups must be an array.' })
    }

    const now = new Date().toISOString()
    const saved = {
      ...payload,
      meta: {
        ...(payload.meta && typeof payload.meta === 'object' ? payload.meta : {}),
        kind: 'market-events',
        schedule: 'manual',
        updatedAt: now,
        lastSuccessfulRun: now,
        failedReason: null,
      },
    }
    const commitSha = await commitMarketEvents(saved)
    return json(res, 200, { ...saved, commitSha })
  } catch (error) {
    return json(res, 500, {
      error: error instanceof Error ? error.message : '시장 주요 이벤트 저장에 실패했습니다.',
    })
  }
}
