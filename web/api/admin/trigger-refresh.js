const DEFAULT_WORKFLOW_ID = 'web-data-refresh.yml'
const DEFAULT_REPO = 'g-s-s-g-1-0-0/stock'
const ALLOWED_SCOPES = new Set(['all', 'analysis', 'valuation', 'technical', 'market-trends', 'market-events'])

function json(res, statusCode, payload) {
  res.statusCode = statusCode
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(payload))
}

function dispatchError(message, statusCode = 500) {
  const error = new Error(message)
  error.statusCode = statusCode
  return error
}

function readAdminEmails() {
  return (process.env.ADMIN_EMAILS || process.env.VITE_ADMIN_EMAILS || '')
    .split(',')
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean)
}

function normalizeScope(value) {
  const scope = String(value || 'all').trim()
  return ALLOWED_SCOPES.has(scope) ? scope : null
}

function readRequestScope(req) {
  return normalizeScope(req.query?.scope || req.body?.scope || 'all')
}

function readCronSecret(req) {
  return String(
    req.query?.secret ||
    req.headers['x-cron-secret'] ||
    req.headers['x-vercel-cron-signature'] ||
    req.body?.secret ||
    ''
  ).trim()
}

function isValidCronRequest(req) {
  const cronSecret = String(process.env.CRON_SECRET || '').trim()
  return Boolean(cronSecret && readCronSecret(req) === cronSecret)
}

function nextTopOfHourIso() {
  const publishAt = new Date()
  publishAt.setUTCMinutes(0, 0, 0)
  if (publishAt.getTime() <= Date.now()) {
    publishAt.setUTCHours(publishAt.getUTCHours() + 1)
  }
  return publishAt.toISOString().replace(/\.000Z$/, 'Z')
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

async function triggerWorkflow(scope, sendNotifications, scheduledPublishAt = '') {
  const token = process.env.GITHUB_ACTIONS_TOKEN
  const repo = process.env.GITHUB_REPO || DEFAULT_REPO
  const workflowId = process.env.GITHUB_REFRESH_WORKFLOW_ID || DEFAULT_WORKFLOW_ID
  const ref = process.env.GITHUB_REFRESH_REF || 'main'

  if (!token) {
    throw dispatchError('GITHUB_ACTIONS_TOKEN is missing.')
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
    body: JSON.stringify({
      ref,
      inputs: {
        refresh_scope: scope,
        send_notifications: sendNotifications ? 'true' : 'false',
        scheduled_publish_at: scheduledPublishAt,
      },
    }),
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw dispatchError(
      detail || `GitHub workflow dispatch failed with ${response.status}.`,
      502
    )
  }

  return {
    repo,
    workflowId,
    ref,
    scope,
    actionsUrl: `https://github.com/${repo}/actions/workflows/${workflowId}`,
  }
}

export default async function handler(req, res) {
  try {
    const isCronRequest = isValidCronRequest(req)
    const allowsCronGet = req.method === 'GET' && isCronRequest
    if (req.method !== 'POST' && !allowsCronGet) {
      res.setHeader('allow', 'GET, POST')
      return json(res, 405, { error: 'Method not allowed.' })
    }

    const scope = readRequestScope(req)
    if (!scope) {
      return json(res, 400, { error: '지원하지 않는 갱신 범위입니다.' })
    }

    if (!isCronRequest) {
      const accessToken = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '').trim()
      if (!accessToken) {
        return json(res, 401, { error: '로그인이 필요합니다.' })
      }

      const user = await readSupabaseUser(accessToken)
      const userEmail = String(user.email || '').toLowerCase()
      const adminEmails = readAdminEmails()

      if (!adminEmails.includes(userEmail)) {
        return json(res, 403, { error: '관리자만 즉시 갱신을 실행할 수 있습니다.' })
      }
    }

    const scheduledPublishAt = isCronRequest ? nextTopOfHourIso() : ''
    const workflowScheduledPublishAt = scheduledPublishAt || 'immediate'
    const workflow = await triggerWorkflow(scope, true, workflowScheduledPublishAt)
    return json(res, 202, {
      ok: true,
      mode: 'workflow_dispatch',
      message: scheduledPublishAt
        ? 'GitHub Actions 데이터 갱신 워크플로를 실행했습니다. 정각까지 대기 후 메일 발송과 배포를 진행합니다.'
        : 'GitHub Actions 데이터 갱신 워크플로를 실행했습니다.',
      scheduledPublishAt,
      ...workflow,
    })
  } catch (error) {
    const statusCode = Number(error?.statusCode) || 500
    console.error('[trigger-refresh] workflow dispatch failed', {
      statusCode,
      message: error instanceof Error ? error.message : String(error),
    })
    return json(res, statusCode, {
      error: error instanceof Error ? error.message : '즉시 갱신 실행에 실패했습니다.',
    })
  }
}
