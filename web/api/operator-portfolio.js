export function publicPortfolio(settings) {
  const fields = ['id', 'nickname', 'brokerage', 'type', 'initialCapital', 'frequency', 'monthlyDeposit',
    'monthOfYear', 'dayOfWeek', 'dayOfMonth', 'buyTiming']
  const accounts = (Array.isArray(settings.accounts) ? settings.accounts : []).map((account) => ({
    ...Object.fromEntries(fields.filter((key) => ['string', 'number'].includes(typeof account?.[key])).map((key) => [key, account[key]])),
    collecting: (Array.isArray(account?.collecting) ? account.collecting : []).map(({ ticker, percent }) => ({ ticker, percent })),
  }))
  const fieldsSettings = ['initialCapital', 'frequency', 'amount', 'dayOfWeek', 'dayOfMonth', 'monthOfYear', 'collectingSince']
  return {
    ...Object.fromEntries(fieldsSettings.filter((key) => ['string', 'number'].includes(typeof settings[key])).map((key) => [key, settings[key]])),
    accounts,
  }
}

export default async function handler(req, res) {
  res.setHeader('cache-control', 'no-store')
  res.setHeader('content-type', 'application/json; charset=utf-8')
  if (req.method !== 'GET') {
    res.setHeader('allow', 'GET')
    res.statusCode = 405
    return res.end(JSON.stringify({ error: 'Method not allowed.' }))
  }
  const url = (process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || '').replace(/\/$/, '')
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY
  const emails = (process.env.ADMIN_EMAILS || process.env.VITE_ADMIN_EMAILS || '').split(',').map((value) => value.trim().toLowerCase()).filter(Boolean)
  try {
    if (!url || !key || !emails.length) throw new Error('Public portfolio unavailable.')
    const read = async (path) => {
      const response = await fetch(url + path, {
        headers: { apikey: key, authorization: 'Bearer ' + key }, signal: AbortSignal.timeout(8000),
      })
      if (!response.ok) throw new Error('Public portfolio lookup failed.')
      return response.json()
    }
    const profiles = await read('/rest/v1/profiles?select=id,email&email=eq.' + encodeURIComponent(emails[0]))
    if (!profiles[0]?.id) throw new Error('Operator unavailable.')
    const rows = await read('/rest/v1/user_settings?select=contribution_settings&owner_id=eq.' + encodeURIComponent(profiles[0].id))
    if (!rows[0]?.contribution_settings) throw new Error('Operator settings unavailable.')
    res.statusCode = 200
    return res.end(JSON.stringify(publicPortfolio(rows[0].contribution_settings)))
  } catch {
    res.statusCode = 503
    return res.end(JSON.stringify({ error: '공수성가 계좌 설정을 불러오지 못했습니다.' }))
  }
}
