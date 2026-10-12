import { useEffect, useState } from 'react'
import { supabase } from './supabase'
import { buildUsageReport, seoulDate, type RetentionMark, type RetentionSummary, type UsageReport } from './usageMetrics'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'missing' }
  | { kind: 'forbidden' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; report: UsageReport; truncated: boolean }

type ProfileRow = {
  id: string
  email: string | null
  name: string | null
  is_admin: boolean | null
  created_at: string
}

type EventRow = {
  actor_id: string
  page: string
  occurred_on: string
}

const MAX_ROWS = 20000

function isMissingSchema(error: { code?: string; message?: string }) {
  const code = error.code ?? ''
  const message = (error.message ?? '').toLowerCase()
  return code === 'PGRST205' || code === '42P01' || code === 'PGRST202' || message.includes('usage_logging') || message.includes('usage_events') || message.includes('schema cache')
}

async function fetchAllRows<T>(load: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: { message: string } | null }>) {
  const pageSize = 1000
  const rows: T[] = []
  for (let from = 0; rows.length < MAX_ROWS; from += pageSize) {
    const { data, error } = await load(from, from + pageSize - 1)
    if (error) throw error
    const batch = data ?? []
    rows.push(...batch)
    if (batch.length < pageSize) return { rows, truncated: false }
  }
  return { rows, truncated: true }
}

function formatKoreanDate(isoDate: string) {
  const [year, month, day] = isoDate.split('-')
  return `${year}.${month}.${day}`
}

function rateText(item: RetentionSummary) {
  if (item.rate === null) return '집계 전'
  return `${Math.round(item.rate * 100)}% · ${item.retained}/${item.eligible}명`
}

function markText(mark: RetentionMark) {
  if (mark === 'yes') return '방문'
  if (mark === 'no') return '없음'
  if (mark === 'pending') return '아직'
  return '기록 전'
}

export function UsageDashboard({ excludeEmails }: { excludeEmails: string[] }) {
  const [snapshot, setSnapshot] = useState<LoadState>({ kind: 'loading' })
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)
  const excludeKey = excludeEmails.map((email) => email.toLowerCase()).join(',')

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setIsRefreshing(true)
      if (!supabase) {
        if (!cancelled) {
          setSnapshot({ kind: 'error', message: 'Supabase 연결값이 없습니다.' })
          setIsRefreshing(false)
        }
        return
      }

      const logging = await supabase.from('usage_logging').select('started_on').eq('id', 1).maybeSingle()
      if (cancelled) return
      if (logging.error) {
        setSnapshot(isMissingSchema(logging.error) ? { kind: 'missing' } : { kind: 'error', message: logging.error.message })
        setIsRefreshing(false)
        return
      }
      const startedOn = logging.data?.started_on
      if (!startedOn) {
        setSnapshot({ kind: 'forbidden' })
        setIsRefreshing(false)
        return
      }
      const client = supabase

      try {
        const [profiles, events] = await Promise.all([
          fetchAllRows<ProfileRow>((from, to) => client
            .from('profiles')
            .select('id, email, name, is_admin, created_at')
            .order('created_at', { ascending: true })
            .range(from, to)),
          fetchAllRows<EventRow>((from, to) => client
            .from('usage_events')
            .select('actor_id, page, occurred_on')
            .order('occurred_on', { ascending: true })
            .range(from, to)),
        ])
        if (cancelled) return
        const report = buildUsageReport({
          users: profiles.rows.map((row) => ({
            id: row.id,
            email: row.email ?? '',
            name: row.name ?? '',
            isAdmin: Boolean(row.is_admin),
            createdAt: row.created_at,
          })),
          events: events.rows.map((row) => ({
            actorId: row.actor_id,
            page: row.page,
            occurredOn: row.occurred_on,
          })),
          today: seoulDate(new Date()),
          loggingStartedOn: String(startedOn).slice(0, 10),
          excludeEmails: excludeKey ? excludeKey.split(',') : [],
        })
        setSnapshot({ kind: 'ready', report, truncated: profiles.truncated || events.truncated })
      } catch (error) {
        if (cancelled) return
        const queryError = error as { code?: string; message?: string }
        setSnapshot(isMissingSchema(queryError)
          ? { kind: 'missing' }
          : { kind: 'error', message: queryError.message || '사용 현황을 불러오지 못했습니다.' })
      } finally {
        if (!cancelled) setIsRefreshing(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [excludeKey, reloadToken])

  const report = snapshot.kind === 'ready' ? snapshot.report : null
  const maxDaily = Math.max(1, ...(report?.daily.map((day) => day.users) ?? [1]))

  return (
    <section className="panel usage-dashboard">
      <div className="usage-dashboard-header">
        <div>
          <h2>사용 현황</h2>
          <p>로그인한 친구 기준입니다. 관리자 계정과 로그인하지 않은 방문은 빠집니다. D+1은 가입 다음 날, D+7은 가입 7일째에 다시 열었는가이고, 7일 내 재방문은 그 사이 하루라도 열었는가입니다.</p>
        </div>
        <button type="button" disabled={isRefreshing} onClick={() => setReloadToken((current) => current + 1)}>
          {isRefreshing ? '불러오는 중' : '다시 불러오기'}
        </button>
      </div>

      {snapshot.kind === 'loading' && <p className="usage-dashboard-status">사용 기록을 불러오는 중입니다.</p>}
      {snapshot.kind === 'missing' && (
        <p className="usage-dashboard-status">
          방문 기록 테이블이 아직 없습니다. Supabase SQL Editor에서 supabase/migrations/017_usage_events.sql 내용을 한 번 실행하면, 그 다음 로그인 방문부터 집계됩니다.
        </p>
      )}
      {snapshot.kind === 'forbidden' && (
        <p className="usage-dashboard-status">
          이 계정은 화면에서는 관리자지만, 데이터베이스 profiles.is_admin 이 꺼져 있어 다른 사용자의 기록을 읽을 수 없습니다.
        </p>
      )}
      {snapshot.kind === 'error' && <p className="usage-dashboard-status">{snapshot.message}</p>}

      {snapshot.kind === 'ready' && report && (
        <>
          <p className="usage-dashboard-meta">기준일 {formatKoreanDate(report.today)} · 기록 시작 {formatKoreanDate(report.loggingStartedOn)}. 시작일보다 앞선 재방문은 분모에서 빼 둡니다.</p>
          {snapshot.truncated && <p className="usage-dashboard-meta">기록이 많아 일부만 반영했습니다.</p>}
          <div className="usage-stat-grid">
            <article>
              <span>가입한 친구</span>
              <strong>{report.friendCount}명</strong>
              <small>한 번도 안 연 친구 {report.neverVisited}명</small>
            </article>
            <article>
              <span>오늘 방문</span>
              <strong>{report.visitedToday}명</strong>
              <small>서로 다른 계정</small>
            </article>
            <article>
              <span>최근 7일 방문</span>
              <strong>{report.visitedLast7Days}명</strong>
              <small>오늘 포함</small>
            </article>
            {report.retention.filter((item) => item.horizon < 30).map((item) => (
              <article key={item.horizon}>
                <span>D+{item.horizon}</span>
                <strong>{rateText(item)}</strong>
                <small>{item.horizon === 1 ? '가입 다음 날' : `가입 ${item.horizon}일째`}</small>
              </article>
            ))}
            <article>
              <span>7일 내 재방문</span>
              <strong>{rateText(report.returnWithin7)}</strong>
              <small>다음 날부터 7일째까지</small>
            </article>
            {report.retention.filter((item) => item.horizon >= 30).map((item) => (
              <article key={item.horizon}>
                <span>D+{item.horizon}</span>
                <strong>{rateText(item)}</strong>
                <small>가입 {item.horizon}일째</small>
              </article>
            ))}
          </div>

          <section className="usage-block">
            <h3>최근 14일 방문</h3>
            <div className="usage-daily" aria-label="최근 14일 방문 인원">
              {report.daily.map((day) => (
                <div className="usage-daily-col" key={day.date} title={`${formatKoreanDate(day.date)} ${day.users}명`}>
                  <span className="usage-daily-count">{day.users}</span>
                  <span className="usage-daily-bar" style={{ height: `${Math.max(day.users === 0 ? 2 : 8, (day.users / maxDaily) * 72)}px` }} />
                  <span className="usage-daily-label">{day.date.slice(5).replace('-', '/')}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="usage-block">
            <h3>화면별 방문</h3>
            <div className="usage-page-list">
              {report.pages.map((page) => (
                <div key={page.page}>
                  <span>{page.label}</span>
                  <strong>{page.userDays}일</strong>
                </div>
              ))}
            </div>
            <p className="usage-dashboard-meta">같은 사람이 같은 화면을 같은 날 여러 번 열어도 1일로 셉니다.</p>
          </section>

          <section className="usage-block">
            <h3>친구별</h3>
            {report.friends.length === 0 ? (
              <p className="usage-dashboard-status">관리자를 뺀 가입 계정이 없습니다.</p>
            ) : (
              <div className="usage-table-wrap">
                <table className="sheet-table usage-table">
                  <thead>
                    <tr>
                      <th>이름</th>
                      <th>가입</th>
                      <th>마지막 방문</th>
                      <th>방문 일수</th>
                      <th>D+1</th>
                      <th>D+7</th>
                      <th>본 화면</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.friends.map((friend) => (
                      <tr key={friend.id}>
                        <td>
                          <strong>{friend.name}</strong>
                          <small>{friend.email}</small>
                        </td>
                        <td>{formatKoreanDate(friend.joinedOn)}</td>
                        <td>{friend.lastVisit ? formatKoreanDate(friend.lastVisit) : '없음'}</td>
                        <td>{friend.activeDays}</td>
                        <td className={`usage-mark usage-mark-${friend.retention[1]}`}>{markText(friend.retention[1])}</td>
                        <td className={`usage-mark usage-mark-${friend.retention[7]}`}>{markText(friend.retention[7])}</td>
                        <td>{friend.pages.length > 0 ? friend.pages.join(', ') : '없음'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </section>
  )
}
