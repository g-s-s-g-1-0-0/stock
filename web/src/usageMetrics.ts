export const USAGE_PAGES = ['home', 'value-analysis', 'technical-analysis', 'market-events', 'market-trends'] as const

export type UsagePage = typeof USAGE_PAGES[number]

export const USAGE_PAGE_LABELS: Record<UsagePage, string> = {
  home: 'HOME',
  'value-analysis': '가치 분석',
  'technical-analysis': '기술 분석',
  'market-events': '시장 주요 이벤트',
  'market-trends': '시장 트렌드',
}

export const RETENTION_HORIZONS = [1, 7, 30] as const

export type RetentionHorizon = typeof RETENTION_HORIZONS[number]

export type RetentionMark = 'yes' | 'no' | 'pending' | 'unobserved'

export type UsageUserInput = {
  id: string
  email: string
  name: string
  isAdmin: boolean
  createdAt: string
}

export type UsageEventInput = {
  actorId: string
  page: string
  occurredOn: string
}

export type RetentionSummary = {
  horizon: number
  retained: number
  eligible: number
  rate: number | null
}

export type UsageFriend = {
  id: string
  name: string
  email: string
  joinedOn: string
  lastVisit: string | null
  activeDays: number
  pages: string[]
  retention: Record<RetentionHorizon, RetentionMark>
  returnWithin7: RetentionMark
}

export type UsageReport = {
  today: string
  loggingStartedOn: string
  friendCount: number
  visitedToday: number
  visitedLast7Days: number
  neverVisited: number
  retention: RetentionSummary[]
  returnWithin7: RetentionSummary
  daily: Array<{ date: string; users: number }>
  pages: Array<{ page: UsagePage; label: string; userDays: number }>
  friends: UsageFriend[]
}

export function isUsagePage(page: string): page is UsagePage {
  return (USAGE_PAGES as readonly string[]).includes(page)
}

export function seoulDate(instant: Date | string) {
  const date = typeof instant === 'string' ? new Date(instant) : instant
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

export function addDays(isoDate: string, days: number) {
  const [year, month, day] = isoDate.slice(0, 10).split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function calendarDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}/.test(value) && !value.includes('T')
    ? value.slice(0, 10)
    : seoulDate(value)
}

function exactMark(joinedOn: string, activeDates: Set<string>, today: string, loggingStartedOn: string, horizon: number): RetentionMark {
  const target = addDays(joinedOn, horizon)
  if (target < loggingStartedOn) return 'unobserved'
  if (target > today) return 'pending'
  return activeDates.has(target) ? 'yes' : 'no'
}

function windowMark(joinedOn: string, activeDates: Set<string>, today: string, loggingStartedOn: string, horizon: number): RetentionMark {
  const windowStart = addDays(joinedOn, 1)
  const windowEnd = addDays(joinedOn, horizon)
  if (windowEnd < loggingStartedOn) return 'unobserved'
  if (today < windowStart) return 'pending'
  const observedStart = windowStart > loggingStartedOn ? windowStart : loggingStartedOn
  const observedEnd = today < windowEnd ? today : windowEnd
  for (const date of activeDates) {
    if (date >= observedStart && date <= observedEnd) return 'yes'
  }
  if (today < windowEnd) return 'pending'
  return 'no'
}

function summary(horizon: number, marks: RetentionMark[]): RetentionSummary {
  const eligibleMarks = marks.filter((mark) => mark === 'yes' || mark === 'no')
  const retained = eligibleMarks.filter((mark) => mark === 'yes').length
  return {
    horizon,
    retained,
    eligible: eligibleMarks.length,
    rate: eligibleMarks.length === 0 ? null : retained / eligibleMarks.length,
  }
}

export function buildUsageReport(input: {
  users: UsageUserInput[]
  events: UsageEventInput[]
  today: string
  loggingStartedOn: string
  excludeEmails?: string[]
}): UsageReport {
  const today = input.today.slice(0, 10)
  const loggingStartedOn = input.loggingStartedOn.slice(0, 10)
  const excluded = new Set((input.excludeEmails ?? []).map((email) => email.trim().toLowerCase()).filter(Boolean))
  const friends = input.users.filter((user) => !user.isAdmin && !excluded.has(user.email.trim().toLowerCase()))
  const friendIds = new Set(friends.map((user) => user.id))
  const datesByUser = new Map<string, Set<string>>()
  const pagesByUser = new Map<string, Set<UsagePage>>()
  const pageUserDays = new Map<UsagePage, Set<string>>(USAGE_PAGES.map((page) => [page, new Set()]))

  for (const event of input.events) {
    if (!friendIds.has(event.actorId) || !isUsagePage(event.page)) continue
    const occurredOn = calendarDate(event.occurredOn)
    const dates = datesByUser.get(event.actorId) ?? new Set<string>()
    dates.add(occurredOn)
    datesByUser.set(event.actorId, dates)
    const pages = pagesByUser.get(event.actorId) ?? new Set<UsagePage>()
    pages.add(event.page)
    pagesByUser.set(event.actorId, pages)
    pageUserDays.get(event.page)?.add(`${event.actorId}:${occurredOn}`)
  }

  const rows: UsageFriend[] = friends.map((user) => {
    const joinedOn = seoulDate(user.createdAt)
    const activeDates = datesByUser.get(user.id) ?? new Set<string>()
    const retention = {
      1: exactMark(joinedOn, activeDates, today, loggingStartedOn, 1),
      7: exactMark(joinedOn, activeDates, today, loggingStartedOn, 7),
      30: exactMark(joinedOn, activeDates, today, loggingStartedOn, 30),
    } satisfies Record<RetentionHorizon, RetentionMark>
    const lastVisit = [...activeDates].sort().at(-1) ?? null
    return {
      id: user.id,
      name: user.name.trim() || user.email.split('@')[0] || '사용자',
      email: user.email,
      joinedOn,
      lastVisit,
      activeDays: activeDates.size,
      pages: USAGE_PAGES.filter((page) => pagesByUser.get(user.id)?.has(page)).map((page) => USAGE_PAGE_LABELS[page]),
      retention,
      returnWithin7: windowMark(joinedOn, activeDates, today, loggingStartedOn, 7),
    }
  })

  rows.sort((left, right) => {
    if (left.lastVisit !== right.lastVisit) {
      if (!left.lastVisit) return 1
      if (!right.lastVisit) return -1
      return left.lastVisit < right.lastVisit ? 1 : -1
    }
    return left.joinedOn < right.joinedOn ? 1 : -1
  })

  const activeOn = (date: string) => rows.filter((row) => datesByUser.get(row.id)?.has(date)).length
  const weekStart = addDays(today, -6)
  const daily = Array.from({ length: 14 }, (_, index) => {
    const date = addDays(today, index - 13)
    return { date, users: activeOn(date) }
  })

  return {
    today,
    loggingStartedOn,
    friendCount: rows.length,
    visitedToday: activeOn(today),
    visitedLast7Days: rows.filter((row) => [...(datesByUser.get(row.id) ?? [])].some((date) => date >= weekStart && date <= today)).length,
    neverVisited: rows.filter((row) => row.activeDays === 0).length,
    retention: RETENTION_HORIZONS.map((horizon) => summary(horizon, rows.map((row) => row.retention[horizon]))),
    returnWithin7: summary(7, rows.map((row) => row.returnWithin7)),
    daily,
    pages: USAGE_PAGES.map((page) => ({
      page,
      label: USAGE_PAGE_LABELS[page],
      userDays: pageUserDays.get(page)?.size ?? 0,
    })),
    friends: rows,
  }
}
