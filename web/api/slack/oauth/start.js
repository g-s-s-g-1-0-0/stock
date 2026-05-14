import crypto from 'node:crypto'

function json(res, statusCode, payload) {
  res.statusCode = statusCode
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(payload))
}

function slackConfig() {
  const clientId = String(process.env.SLACK_CLIENT_ID || '').trim()
  const signingSecret = String(process.env.SLACK_SIGNING_SECRET || '').trim()
  if (!clientId || !signingSecret) {
    throw new Error('Slack OAuth 환경변수가 설정되지 않았습니다.')
  }
  return { clientId, signingSecret }
}

function appOrigin(req) {
  const configured = String(process.env.WEB_APP_URL || process.env.APP_URL || process.env.SITE_URL || '').trim().replace(/\/$/, '')
  if (configured) return configured
  const host = req.headers['x-forwarded-host'] || req.headers.host
  const proto = req.headers['x-forwarded-proto'] || 'https'
  return host ? `${proto}://${host}` : ''
}

function base64Url(value) {
  return Buffer.from(value).toString('base64url')
}

function signState(payload, secret) {
  const encodedPayload = base64Url(JSON.stringify(payload))
  const signature = crypto.createHmac('sha256', secret).update(encodedPayload).digest('base64url')
  return `${encodedPayload}.${signature}`
}

async function readSupabaseUser(accessToken) {
  const supabaseUrl = String(process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || '').replace(/\/$/, '')
  const supabaseAnonKey = String(process.env.SUPABASE_ANON_KEY || process.env.VITE_SUPABASE_ANON_KEY || '').trim()
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Supabase 환경변수가 설정되지 않았습니다.')
  }

  const response = await fetch(`${supabaseUrl}/auth/v1/user`, {
    headers: {
      apikey: supabaseAnonKey,
      authorization: `Bearer ${accessToken}`,
    },
  })
  if (!response.ok) {
    throw new Error('로그인이 필요합니다.')
  }
  return response.json()
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('allow', 'POST')
    return json(res, 405, { error: 'Method not allowed.' })
  }

  try {
    const accessToken = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '').trim()
    if (!accessToken) {
      return json(res, 401, { error: '로그인이 필요합니다.' })
    }

    const user = await readSupabaseUser(accessToken)
    const ownerId = String(user.id || '').trim()
    if (!ownerId) {
      return json(res, 401, { error: '로그인이 필요합니다.' })
    }

    const { clientId, signingSecret } = slackConfig()
    const origin = appOrigin(req)
    if (!origin) {
      throw new Error('WEB_APP_URL 설정이 필요합니다.')
    }

    const redirectUri = `${origin}/api/slack/oauth/callback`
    const state = signState({
      ownerId,
      exp: Math.floor(Date.now() / 1000) + 10 * 60,
      nonce: crypto.randomBytes(16).toString('hex'),
    }, signingSecret)
    const params = new URLSearchParams({
      client_id: clientId,
      scope: 'incoming-webhook',
      redirect_uri: redirectUri,
      state,
    })

    return json(res, 200, { url: `https://slack.com/oauth/v2/authorize?${params.toString()}` })
  } catch (error) {
    return json(res, 500, {
      error: error instanceof Error ? error.message : 'Slack 연동을 시작하지 못했습니다.',
    })
  }
}
