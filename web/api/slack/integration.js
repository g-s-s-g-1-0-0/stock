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

async function requireUser(req) {
  const accessToken = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '').trim()
  if (!accessToken) {
    return { error: { status: 401, message: '로그인이 필요합니다.' } }
  }
  const user = await readSupabaseUser(accessToken)
  return { ownerId: String(user.id || '').trim() }
}

async function markSlackDisconnected(ownerId) {
  const rows = await supabaseRequest(
    `/rest/v1/user_settings?owner_id=eq.${encodeURIComponent(ownerId)}&select=notification_preferences&limit=1`,
  )
  const currentPreferences = rows?.[0]?.notification_preferences && typeof rows[0].notification_preferences === 'object'
    ? rows[0].notification_preferences
    : {}
  const notificationPreferences = {
    ...DEFAULT_NOTIFICATION_PREFERENCES,
    ...currentPreferences,
    notificationChannel: currentPreferences.notificationChannel === 'slack' ? 'email' : currentPreferences.notificationChannel || 'email',
    slackConnected: false,
    slackConnectedAt: '',
  }

  await supabaseRequest(`/rest/v1/user_settings?owner_id=eq.${encodeURIComponent(ownerId)}`, {
    method: 'PATCH',
    headers: {
      prefer: 'return=minimal',
    },
    body: JSON.stringify({ notification_preferences: notificationPreferences }),
  })
}

export default async function handler(req, res) {
  if (req.method !== 'DELETE') {
    res.setHeader('allow', 'DELETE')
    return json(res, 405, { error: 'Method not allowed.' })
  }

  try {
    const { ownerId, error } = await requireUser(req)
    if (error) {
      return json(res, error.status, { error: error.message })
    }
    if (!ownerId) {
      return json(res, 401, { error: '로그인이 필요합니다.' })
    }

    await supabaseRequest(
      `/rest/v1/notification_integrations?owner_id=eq.${encodeURIComponent(ownerId)}&provider=eq.slack`,
      { method: 'DELETE' },
    )
    await markSlackDisconnected(ownerId)
    return json(res, 200, { ok: true })
  } catch (error) {
    return json(res, 500, {
      error: error instanceof Error ? error.message : 'Slack 연동 해제에 실패했습니다.',
    })
  }
}
