const ALLOWED_CODES = new Set(['supabase_client_missing'])
const MIN_INTERVAL_MS = 6 * 60 * 60 * 1000
const recentAlerts = new Map()

function json(res, statusCode, payload) {
  res.statusCode = statusCode
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.setHeader('cache-control', 'no-store')
  res.end(JSON.stringify(payload))
}

function readAdminEmails() {
  return (process.env.ADMIN_EMAILS || process.env.VITE_ADMIN_EMAILS || '')
    .split(',')
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean)
}

function readBody(req) {
  if (req.body && typeof req.body === 'object') return req.body
  return {}
}

function shouldThrottle(code, hostname) {
  const key = `${code}:${hostname || '-'}`
  const last = recentAlerts.get(key) || 0
  const now = Date.now()
  if (now - last < MIN_INTERVAL_MS) return true
  recentAlerts.set(key, now)
  return false
}

async function sendBrevoEmail({ to, subject, html }) {
  const apiKey = String(process.env.BREVO_API_KEY || '').trim()
  if (!apiKey) throw new Error('BREVO_API_KEY is missing.')
  const fromEmail = String(process.env.SMTP_FROM || '').trim()
  const fromName = String(process.env.SMTP_FROM_NAME || '공수성가').trim() || '공수성가'
  if (!fromEmail) throw new Error('SMTP_FROM is missing.')

  const response = await fetch('https://api.brevo.com/v3/smtp/email', {
    method: 'POST',
    headers: {
      accept: 'application/json',
      'content-type': 'application/json',
      'api-key': apiKey,
    },
    body: JSON.stringify({
      sender: { email: fromEmail, name: fromName },
      to: [{ email: to }],
      subject,
      htmlContent: html,
    }),
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Brevo failed with ${response.status}`)
  }
}

function alertCopy(code, hostname, href) {
  if (code === 'supabase_client_missing') {
    return {
      subject: '[경고] 웹 로그인 설정 누락 (Supabase 클라이언트)',
      html: [
        '<p>프로덕션 웹에서 Supabase 로그인 클라이언트가 비활성 상태입니다.</p>',
        '<p>일반 사용자는 로그인할 수 없습니다. Vercel 환경변수의 <code>VITE_SUPABASE_URL</code> / <code>VITE_SUPABASE_ANON_KEY</code>가 빌드에 반영됐는지 확인하고 Redeploy 해 주세요.</p>',
        `<p>hostname: <strong>${hostname || '-'}</strong><br/>href: ${href || '-'}</p>`,
      ].join(''),
    }
  }
  return {
    subject: '[경고] 웹 런타임 알림',
    html: `<p>code=${code}</p><p>hostname=${hostname || '-'}</p>`,
  }
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return json(res, 405, { ok: false, error: 'Method not allowed' })
  }

  const body = readBody(req)
  const code = String(body.code || '').trim()
  const hostname = String(body.hostname || '').trim().slice(0, 200)
  const href = String(body.href || '').trim().slice(0, 500)

  if (!ALLOWED_CODES.has(code)) {
    return json(res, 400, { ok: false, error: 'Unsupported alert code' })
  }

  if (shouldThrottle(code, hostname)) {
    return json(res, 200, { ok: true, skipped: 'throttled' })
  }

  const recipients = readAdminEmails()
  if (!recipients.length) {
    return json(res, 500, { ok: false, error: 'ADMIN_EMAILS is missing' })
  }

  try {
    const { subject, html } = alertCopy(code, hostname, href)
    for (const to of recipients) {
      await sendBrevoEmail({ to, subject, html })
    }
    return json(res, 200, { ok: true, sent: recipients.length })
  } catch (error) {
    return json(res, 500, { ok: false, error: error instanceof Error ? error.message : String(error) })
  }
}
