const DEFAULT_WORKFLOW_ID = 'web-data-refresh.yml'
const DEFAULT_REPO = 'g-s-s-g-1-0-0/stock'

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

async function triggerWorkflow() {
  const token = process.env.GITHUB_ACTIONS_TOKEN
  const repo = process.env.GITHUB_REPO || DEFAULT_REPO
  const workflowId = process.env.GITHUB_REFRESH_WORKFLOW_ID || DEFAULT_WORKFLOW_ID
  const ref = process.env.GITHUB_REFRESH_REF || 'main'

  if (!token) {
    throw new Error('GITHUB_ACTIONS_TOKEN is missing.')
  }

  const response = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${workflowId}/dispatches`, {
    method: 'POST',
    headers: {
      accept: 'application/vnd.github+json',
      authorization: `Bearer ${token}`,
      'content-type': 'application/json',
      'user-agent': 'gongsuseongga-admin-refresh',
      'x-github-api-version': '2022-11-28',
    },
    body: JSON.stringify({ ref }),
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `GitHub workflow dispatch failed with ${response.status}.`)
  }

  return {
    repo,
    workflowId,
    ref,
    actionsUrl: `https://github.com/${repo}/actions/workflows/${workflowId}`,
  }
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('allow', 'POST')
    return json(res, 405, { error: 'Method not allowed.' })
  }

  const accessToken = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '').trim()
  if (!accessToken) {
    return json(res, 401, { error: '로그인이 필요합니다.' })
  }

  try {
    const user = await readSupabaseUser(accessToken)
    const userEmail = String(user.email || '').toLowerCase()
    const adminEmails = readAdminEmails()

    if (!adminEmails.includes(userEmail)) {
      return json(res, 403, { error: '관리자만 즉시 갱신을 실행할 수 있습니다.' })
    }

    const workflow = await triggerWorkflow()
    return json(res, 202, {
      ok: true,
      mode: 'workflow_dispatch',
      message: 'GitHub Actions 데이터 갱신 워크플로를 실행했습니다.',
      ...workflow,
    })
  } catch (error) {
    return json(res, 500, {
      error: error instanceof Error ? error.message : '즉시 갱신 실행에 실패했습니다.',
    })
  }
}
