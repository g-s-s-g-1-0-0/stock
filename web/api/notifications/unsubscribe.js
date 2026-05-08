import crypto from 'node:crypto'

const DEFAULT_NOTIFICATION_PREFERENCES = {
  opinionChangeEmail: true,
  nasdaqPeakEmail: true,
  weeklyTrendReport: true,
  earningsDayBefore: true,
  adminAutoUpdateFailureEmail: true,
  recipientEmail: '',
}
const ALLOWED_NOTIFICATION_KEYS = new Set(Object.keys(DEFAULT_NOTIFICATION_PREFERENCES).filter((key) => key !== 'recipientEmail'))

function json(res, statusCode, payload) {
  res.statusCode = statusCode
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(payload))
}

function base64UrlDecode(value) {
  return Buffer.from(String(value || ''), 'base64url')
}

function signingSecret() {
  return String(process.env.NOTIFICATION_UNSUBSCRIBE_SECRET || process.env.SUPABASE_SERVICE_ROLE_KEY || '').trim()
}

function verifyToken(rawToken) {
  const [encodedPayload, encodedSignature] = String(rawToken || '').split('.')
  const secret = signingSecret()
  if (!encodedPayload || !encodedSignature || !secret) {
    throw new Error('Invalid unsubscribe token.')
  }

  const expectedSignature = crypto
    .createHmac('sha256', secret)
    .update(encodedPayload)
    .digest()
  const actualSignature = base64UrlDecode(encodedSignature)
  if (actualSignature.length !== expectedSignature.length || !crypto.timingSafeEqual(actualSignature, expectedSignature)) {
    throw new Error('Invalid unsubscribe token.')
  }

  const payload = JSON.parse(base64UrlDecode(encodedPayload).toString('utf8'))
  if (!payload || typeof payload !== 'object') {
    throw new Error('Invalid unsubscribe token.')
  }
  if (!ALLOWED_NOTIFICATION_KEYS.has(payload.key)) {
    throw new Error('Unsupported notification preference.')
  }
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(payload.ownerId || ''))) {
    throw new Error('Invalid unsubscribe token.')
  }
  if (Number(payload.exp || 0) < Math.floor(Date.now() / 1000)) {
    throw new Error('This unsubscribe link has expired.')
  }

  return {
    ownerId: String(payload.ownerId),
    key: String(payload.key),
  }
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

async function disableNotification(ownerId, key) {
  const rows = await supabaseRequest(
    `/rest/v1/user_settings?owner_id=eq.${encodeURIComponent(ownerId)}&select=notification_preferences&limit=1`,
  )
  const currentPreferences = rows?.[0]?.notification_preferences && typeof rows[0].notification_preferences === 'object'
    ? rows[0].notification_preferences
    : {}
  const notificationPreferences = {
    ...DEFAULT_NOTIFICATION_PREFERENCES,
    ...currentPreferences,
    [key]: false,
  }

  const updatePath = `/rest/v1/user_settings?owner_id=eq.${encodeURIComponent(ownerId)}`
  const updatedRows = await supabaseRequest(updatePath, {
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

function appOrigin(req) {
  const configured = String(process.env.WEB_APP_URL || process.env.APP_URL || process.env.SITE_URL || '').trim().replace(/\/$/, '')
  if (configured) return configured
  const host = req.headers['x-forwarded-host'] || req.headers.host
  const proto = req.headers['x-forwarded-proto'] || 'https'
  return host ? `${proto}://${host}` : ''
}

function redirectToSettings(req, res, status) {
  const origin = appOrigin(req)
  if (!origin) {
    return json(res, 200, { ok: status === 'unsubscribed', status })
  }
  const params = new URLSearchParams({ settings: 'notifications', notification: status })
  res.statusCode = 302
  res.setHeader('location', `${origin}/#home?${params.toString()}`)
  res.end()
}

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    res.setHeader('allow', 'GET')
    return json(res, 405, { error: 'Method not allowed.' })
  }

  try {
    const { ownerId, key } = verifyToken(req.query?.token)
    await disableNotification(ownerId, key)
    return redirectToSettings(req, res, 'unsubscribed')
  } catch (error) {
    return json(res, 400, {
      error: error instanceof Error ? error.message : '알림 수신 해제에 실패했습니다.',
    })
  }
}
