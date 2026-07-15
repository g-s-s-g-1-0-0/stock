import crypto from 'node:crypto'

const DEFAULT_NOTIFICATION_PREFERENCES = {
  opinionChangeEmail: true,
  nasdaqPeakEmail: true,
  weeklyTrendReport: true,
  earningsDayBefore: true,
  adminAutoUpdateFailureEmail: true,
  recipientEmail: '',
  notificationChannel: 'email',
  kakaoTalkConnected: false,
  slackConnected: false,
  kakaoTalkConnectedAt: '',
  slackConnectedAt: '',
}

function json(res, statusCode, payload) {
  res.statusCode = statusCode
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(payload))
}

function appOrigin(req) {
  const configured = String(process.env.WEB_APP_URL || process.env.APP_URL || process.env.SITE_URL || '').trim().replace(/\/$/, '')
  if (configured) return configured
  const host = req.headers['x-forwarded-host'] || req.headers.host
  const proto = req.headers['x-forwarded-proto'] || 'https'
  return host ? `${proto}://${host}` : ''
}

function redirectToSettings(req, res, status, detail = '') {
  const origin = appOrigin(req)
  if (!origin) {
    return json(res, status === 'connected' ? 200 : 400, { ok: status === 'connected', status, detail })
  }
  const params = new URLSearchParams({ settings: 'notifications', slack: status })
  if (detail) params.set('detail', detail)
  res.statusCode = 302
  res.setHeader('location', `${origin}/#home?${params.toString()}`)
  res.end()
}

function slackConfig() {
  const clientId = String(process.env.SLACK_CLIENT_ID || '').trim()
  const clientSecret = String(process.env.SLACK_CLIENT_SECRET || '').trim()
  const signingSecret = String(process.env.SLACK_SIGNING_SECRET || '').trim()
  if (!clientId || !clientSecret || !signingSecret) {
    throw new Error('Slack OAuth 환경변수가 설정되지 않았습니다.')
  }
  return { clientId, clientSecret, signingSecret }
}

function base64UrlDecode(value) {
  return Buffer.from(String(value || ''), 'base64url')
}

function verifyState(rawState, secret) {
  const [encodedPayload, encodedSignature] = String(rawState || '').split('.')
  if (!encodedPayload || !encodedSignature) {
    throw new Error('Invalid Slack OAuth state.')
  }
  const expected = crypto.createHmac('sha256', secret).update(encodedPayload).digest()
  const actual = base64UrlDecode(encodedSignature)
  if (actual.length !== expected.length || !crypto.timingSafeEqual(actual, expected)) {
    throw new Error('Invalid Slack OAuth state.')
  }
  const payload = JSON.parse(base64UrlDecode(encodedPayload).toString('utf8'))
  if (!payload || typeof payload !== 'object' || !payload.ownerId) {
    throw new Error('Invalid Slack OAuth state.')
  }
  if (Number(payload.exp || 0) < Math.floor(Date.now() / 1000)) {
    throw new Error('Slack OAuth state has expired.')
  }
  return { ownerId: String(payload.ownerId) }
}

function supabaseConfig() {
  const supabaseUrl = String(process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || '').replace(/\/$/, '')
  const serviceKey = String(process.env.SUPABASE_SERVICE_ROLE_KEY || '').trim()
  if (!supabaseUrl || !serviceKey) {
    throw new Error('Supabase service credentials are missing.')
  }
  return { supabaseUrl, serviceKey }
}

async function supabaseRequest(path, options = {}) {
  const { supabaseUrl, serviceKey } = supabaseConfig()
  const response = await fetch(`${supabaseUrl}${path}`, {
    ...options,
    headers: {
      apikey: serviceKey,
      authorization: `Bearer ${serviceKey}`,
      accept: 'application/json',
      'content-type': 'application/json',
      ...(options.headers || {}),
    },
  })
  const text = await response.text()
  const payload = text ? JSON.parse(text) : null
  if (!response.ok) {
    throw new Error(payload?.message || text || `Supabase request failed with ${response.status}.`)
  }
  return payload
}

async function exchangeSlackCode(req, code) {
  const { clientId, clientSecret } = slackConfig()
  const origin = appOrigin(req)
  if (!origin) {
    throw new Error('WEB_APP_URL 설정이 필요합니다.')
  }

  const response = await fetch('https://slack.com/api/oauth.v2.access', {
    method: 'POST',
    headers: {
      'content-type': 'application/x-www-form-urlencoded',
    },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      code,
      redirect_uri: `${origin}/api/slack/oauth/callback`,
    }),
  })
  const payload = await response.json()
  if (!response.ok || payload?.ok !== true) {
    throw new Error(payload?.error || `Slack OAuth failed with ${response.status}.`)
  }
  return payload
}

async function saveSlackIntegration(ownerId, slackPayload) {
  const webhook = slackPayload?.incoming_webhook || {}
  const webhookUrl = String(webhook.url || '').trim()
  if (!webhookUrl) {
    throw new Error('Slack incoming webhook URL이 응답에 없습니다.')
  }

  await supabaseRequest('/rest/v1/notification_integrations?on_conflict=owner_id,provider', {
    method: 'POST',
    headers: {
      prefer: 'resolution=merge-duplicates,return=minimal',
    },
    body: JSON.stringify({
      owner_id: ownerId,
      provider: 'slack',
      team_id: slackPayload.team?.id || null,
      team_name: slackPayload.team?.name || null,
      channel_id: webhook.channel_id || null,
      channel_name: webhook.channel || null,
      webhook_url: webhookUrl,
      configuration_url: webhook.configuration_url || null,
    }),
  })
}

async function markSlackConnected(ownerId) {
  const rows = await supabaseRequest(
    `/rest/v1/user_settings?owner_id=eq.${encodeURIComponent(ownerId)}&select=notification_preferences&limit=1`,
  )
  const currentPreferences = rows?.[0]?.notification_preferences && typeof rows[0].notification_preferences === 'object'
    ? rows[0].notification_preferences
    : {}
  const notificationPreferences = {
    ...DEFAULT_NOTIFICATION_PREFERENCES,
    ...currentPreferences,
    notificationChannel: 'slack',
    slackConnected: true,
    slackConnectedAt: new Date().toISOString(),
  }

  const updatedRows = await supabaseRequest(`/rest/v1/user_settings?owner_id=eq.${encodeURIComponent(ownerId)}`, {
    method: 'PATCH',
    headers: {
      prefer: 'return=representation',
    },
    body: JSON.stringify({ notification_preferences: notificationPreferences }),
  })
  if (Array.isArray(updatedRows) && updatedRows.length > 0) return

  await supabaseRequest('/rest/v1/user_settings', {
    method: 'POST',
    headers: {
      prefer: 'return=minimal',
    },
    body: JSON.stringify({ owner_id: ownerId, notification_preferences: notificationPreferences }),
  })
}

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    res.setHeader('allow', 'GET')
    return json(res, 405, { error: 'Method not allowed.' })
  }

  try {
    if (req.query?.error) {
      return redirectToSettings(req, res, 'error', String(req.query.error))
    }
    const code = String(req.query?.code || '').trim()
    if (!code) {
      return redirectToSettings(req, res, 'error', 'missing_code')
    }
    const { signingSecret } = slackConfig()
    const { ownerId } = verifyState(req.query?.state, signingSecret)
    const slackPayload = await exchangeSlackCode(req, code)
    await saveSlackIntegration(ownerId, slackPayload)
    await markSlackConnected(ownerId)
    return redirectToSettings(req, res, 'connected')
  } catch (error) {
    return redirectToSettings(req, res, 'error', error instanceof Error ? error.message : 'Slack 연동에 실패했습니다.')
  }
}
