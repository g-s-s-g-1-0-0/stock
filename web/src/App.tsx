import './App.css'
import { Fragment, type CSSProperties, type FormEvent, type ReactNode, type RefObject, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { User } from '@supabase/supabase-js'
import { fetchAppData, fetchStockSearchData, refreshAppData, saveMarketEvents, saveMarketTrends, saveTradeLogs, type AppData, type RuntimeMeta } from './api'
import { isSupabaseConfigured, supabase, userDisplayName } from './supabase'

type Market = 'KR' | 'US'
type Valuation = '저평가' | '보통' | '고평가' | '판단 불가'
type Opinion = '매수' | '관망' | '매도' | '-'
type TradeStatus = '익절' | '손절' | '실패 익절' | '보유 중'
type WatchlistSortKey = 'registered' | 'market_kr_first' | 'market_us_first' | 'holding_first' | 'not_holding_first' | 'valuation_low_first' | 'valuation_high_first' | 'opinion_buy_first' | 'opinion_sell_first' | 'name_asc' | 'name_desc'
type NotificationDeliveryChannel = 'email' | 'kakaoTalk' | 'slack'
type NotificationIntegrationChannel = Exclude<NotificationDeliveryChannel, 'email'>

type WatchlistSortSettings = {
  primary: WatchlistSortKey
  secondary: WatchlistSortKey
}

type NotificationPreferences = {
  opinionChangeEmail: boolean
  nasdaqPeakEmail: boolean
  regimeShiftEmail: boolean
  bbPullbackEmail: boolean
  weeklyTrendReport: boolean
  earningsDayBefore: boolean
  adminAutoUpdateFailureEmail: boolean
  recipientEmail: string
  notificationChannel: NotificationDeliveryChannel
  kakaoTalkConnected: boolean
  slackConnected: boolean
  kakaoTalkConnectedAt: string
  slackConnectedAt: string
}

type InvestmentType = 'swing' | 'long_term'

type StoredUserSettings = {
  watchlistSort: WatchlistSortSettings
  notificationPreferences: NotificationPreferences
  investmentType: InvestmentType | null
}

type StoredPortfolioState = {
  personalTradeLogs: TradeLog[]
  contributionSettings: ContributionSettings
  initialized: boolean
}

type LoadedWatchlist = {
  tickers: string[] | null
  watchlistSort: WatchlistSortSettings | null
  updatedAt: number | null
  tickersByType?: Partial<Record<InvestmentType, string[]>> | null
}

type PendingWatchlistEntry = {
  tickers: string[]
  updatedAt: number
}

type ResolvedWatchlistState = {
  tickers: string[]
  pendingToSync: string[] | null
  clearPending: boolean
}

type WatchlistPersistResult =
  | { ok: true }
  | { ok: false; reason?: 'auth'; error?: unknown }

type NotificationPreferenceKey = 'opinionChangeEmail' | 'nasdaqPeakEmail' | 'regimeShiftEmail' | 'bbPullbackEmail' | 'weeklyTrendReport' | 'earningsDayBefore' | 'adminAutoUpdateFailureEmail'

type Stock = {
  ticker: string
  name: string
  market: Market
  fairPrice: string
  currentPrice: string
  valuation: Valuation
  opinion: Opinion
  strategies: string[]
  category?: string
  industry?: string
  fairPriceReason?: 'loss_making' | 'etf'
  updatedAt: string
}

type TradeLog = {
  slotId?: string
  investmentType?: InvestmentType
  investmentAmount?: number
  ticker: string
  name?: string
  market?: Market
  currentPrice?: string
  strategy: string
  buyDate: string
  buyPrice: string
  sellDate: string
  sellPrice: string
  returnPct: number
  holdingDays: number | '-'
  status: TradeStatus
  // 가치투자에서 개인이 직접 청산한 거래임을 표시. 자동 매도 신호와 구분해 로그/현금 계산에 포함한다.
  manualExit?: boolean
}

type TooltipState = {
  text: string
  x: number
  y: number
  className?: string
}

type ActivePage = 'home' | 'value-analysis' | 'technical-analysis' | 'market-events' | 'market-trends' | 'board' | 'admin-logs'

type AuthMode = 'login' | 'signup' | 'recover' | 'reset'
type BoardCategory = '칭찬' | '버그' | '건의' | '기타'
type BoardFilter = '전체' | BoardCategory
type BoardSortDirection = 'desc' | 'asc'

type UserSession = {
  id: string
  email: string
  name: string
  loggedInAt: string
}

type HoldingLiquidationDraft = {
  key: string
  ticker: string
  name: string
  buyDate: string
  buyPrice: string
  sellDate: string
  sellPrice: string
}

type ContributionFrequency = 'weekly' | 'monthly'
type ContributionSettingsMode = 'cash' | 'investment'

type AllocationSettings = {
  slotCount: number
  slotPercents: number[]
}

type ContributionSettings = {
  initialCapital: number
  frequency: ContributionFrequency
  amount: number
  dayOfWeek: number
  dayOfMonth: number
  allocationByInvestmentType: Record<InvestmentType, AllocationSettings>
}

type ContributionSettingsDraft = {
  initialCapital: string
  frequency: ContributionFrequency
  amount: string
  dayOfWeek: string
  dayOfMonth: string
  allocationByInvestmentType: Record<InvestmentType, {
    slotCount: string
    slotPercents: string[]
  }>
}

type PortfolioSummary = {
  cash: number
  projectedCash: number
  totalCapital: number
  investedAmount: number
  openInvestmentAmount: number
  cumulativeInvestmentAmount: number
  positionValue: number
  totalAsset: number
  profitAmount: number
  realizedProfitAmount: number
  unrealizedProfitAmount: number
  profitRate: number
  amountByTradeKey: Map<string, number>
}

type TradeBuyPriority = {
  megaRank: number
  trendRank: number
}

type TechnicalColumn = {
  key?: string
  label: string
  tooltip: string
  value: (stock: Stock, index: number) => string
}

type MarketEventEntry = {
  month: string
  date: string
  dday: string
  time: string
  highlighted?: boolean
  status?: 'past' | 'today' | 'future'
}

type MarketEventGroup = {
  title: string
  tooltip: string
  entries: MarketEventEntry[]
}

type MarketTrendRow = {
  date: string
  ranks: string[]
  summary: string
}

type BoardPost = {
  id: string
  category: BoardCategory
  content: string
  createdAt: string
  authorId: string
  authorName: string
  comments: BoardComment[]
  hidden?: boolean
}

type BoardComment = {
  id: string
  postId: string
  content: string
  createdAt: string
  authorId: string
  authorName: string
}

type ApiLog = {
  id: string
  triggerName: string
  status: 'success' | 'failure'
  message: string
  createdAt: string
  actorEmail?: string
  metadata?: Record<string, unknown>
}

type ApiLogTrigger = 'value-analysis' | 'technical-analysis' | 'market-trends'
type ApiLogDetailColumn = { key: string; label: string; width?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' }
type ApiLogDetailRow = Record<string, unknown>

type ValuationMetric = {
  marketCap: string
  sales: string
  salesQoq: string
  salesYoyTtm: string
  salesPastYears: string
  currentRatio: string
  priceToFreeCashFlow: string
  priceToSales: string
  per: string
  pbr: string
  roe: string
  peg: string
  sharesOutstanding: string
  grossMargin: string
  operatingMargin: string
  epsTtm: string
  epsNextYear: string
  epsQoq: string
  ruleOf40: string
  earningsDate: string
}

const MAX_WATCHLIST_ITEMS = 50
const LEGACY_AUTH_SESSION_STORAGE_KEY = 'gongsu-user-session'
const LOCAL_TEST_SESSION_STORAGE_KEY = 'gongsu-local-test-session'
const WATCHLIST_STORAGE_KEY = 'gongsu-watchlist'
const PERSONAL_WATCHLIST_PENDING_STORAGE_KEY = 'gongsu-watchlist-pending-v1'
// 가치투자(long_term)/스윙투자(swing)의 관심종목을 로컬에서 분리 보관한다.
// 로컬 우선 프리뷰 단계라 원격 스키마는 그대로 두고, 분리 데이터는 이 키로만 관리한다.
const PERSONAL_WATCHLIST_BY_TYPE_STORAGE_KEY = 'gongsu-watchlist-by-type-v1'
const OPERATOR_WATCHLIST_STORAGE_KEY = 'gongsu-operator-watchlist'
const OPERATOR_WATCHLIST_REMOTE_CACHE_STORAGE_KEY = 'gongsu-operator-watchlist-remote-cache-v1'
const OPERATOR_WATCHLIST_PENDING_STORAGE_KEY = 'gongsu-operator-watchlist-pending-v1'
// 운영자(어드민) 관심종목도 가치투자/스윙투자 유형별로 분리 보관한다. (로컬 우선 프리뷰, 세션 비종속 단일 키)
const OPERATOR_WATCHLIST_BY_TYPE_STORAGE_KEY = 'gongsu-operator-watchlist-by-type-v1'
const PERSONAL_TRADES_STORAGE_KEY = 'gongsu-personal-trades'
const VIEW_MODE_STORAGE_KEY = 'gongsu-view-mode'
const VIEW_MODE_HINT_STORAGE_KEY = 'gongsu-view-mode-hint-seen'
const USER_SETTINGS_STORAGE_KEY = 'gongsu-user-settings'
const USER_SETTINGS_REMOTE_CACHE_STORAGE_KEY = 'gongsu-user-settings-remote-cache-v1'
const OPERATOR_WATCHLIST_SORT_STORAGE_KEY = 'gongsu-operator-watchlist-sort'
const CONTRIBUTION_SETTINGS_STORAGE_KEY = 'gongsu-contribution-settings'
const API_LOGS_STORAGE_KEY = 'gongsu-api-logs'
const ACTIVE_PAGE_STORAGE_KEY = 'gongsu-active-page'
const DEFAULT_ADMIN_EMAILS = ['admin@gongsu.local']
const FAIR_PRICE_UNAVAILABLE_LABEL = '적자 상태라 판단 불가'
const ETF_FAIR_PRICE_UNAVAILABLE_LABEL = 'ETF라 판단 불가'
const FAIR_PRICE_RANGE_TOOLTIP = 'EPS(TTM) × 적용 PER 배수로 계산합니다. 가치주는 10~15배, 혼합주는 15~25배를 적용하고, 성장주는 매출 성장률에 따라 15~20배부터 최대 50~70배까지 적용합니다. EPS가 0 이하이면 판단 불가로 표시합니다.'
const ADMIN_LOGS_PAGE_SIZE = 50
const BOARD_POST_PAGE_SIZE = 50
const MAX_BOARD_COMMENTS_PER_POST = 50
const MAX_BOARD_COMMENT_LENGTH = 500
const DEFAULT_WATCHLIST_SORT: WatchlistSortSettings = { primary: 'registered', secondary: 'registered' }
const activePages: ActivePage[] = ['home', 'value-analysis', 'technical-analysis', 'market-events', 'market-trends', 'board', 'admin-logs']
const DEFAULT_NOTIFICATION_PREFERENCES: NotificationPreferences = {
  opinionChangeEmail: true,
  nasdaqPeakEmail: true,
  regimeShiftEmail: true,
  bbPullbackEmail: true,
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
const DEFAULT_USER_SETTINGS: StoredUserSettings = {
  watchlistSort: DEFAULT_WATCHLIST_SORT,
  notificationPreferences: DEFAULT_NOTIFICATION_PREFERENCES,
  investmentType: null,
}
const DEFAULT_INVESTMENT_TYPE: InvestmentType = 'long_term'
const DEFAULT_PORTFOLIO_CASH = 10_000_000
const DEFAULT_ALLOCATION_SETTINGS: Record<InvestmentType, AllocationSettings> = {
  swing: { slotCount: 3, slotPercents: [50, 25, 25] },
  long_term: { slotCount: 10, slotPercents: Array.from({ length: 10 }, () => 10) },
}
const DEFAULT_CONTRIBUTION_SETTINGS: ContributionSettings = {
  initialCapital: DEFAULT_PORTFOLIO_CASH,
  frequency: 'monthly',
  amount: 1_000_000,
  dayOfWeek: 1,
  dayOfMonth: 1,
  allocationByInvestmentType: DEFAULT_ALLOCATION_SETTINGS,
}
const weekdayOptions = [
  { value: 0, label: '일요일' },
  { value: 1, label: '월요일' },
  { value: 2, label: '화요일' },
  { value: 3, label: '수요일' },
  { value: 4, label: '목요일' },
  { value: 5, label: '금요일' },
  { value: 6, label: '토요일' },
]
const TEST_USER_SESSION: UserSession = {
  id: 'local-test-user',
  email: 'test@gongsu.local',
  name: '테스트',
  loggedInAt: '',
}
const investmentProfileOptions: Array<{
  value: InvestmentType
  title: string
  description: string
  bullets: string[]
}> = [
  {
    value: 'long_term',
    title: '천천히 모아가는 투자자 (가치 투자)',
    description: '좋은 매수 시점과 보유 흐름을 중심으로 보고 싶어요.',
    bullets: ['매수/관망 신호만 보기', '매도 관련 정보는 숨김', '보유 종목 수익률 중심'],
  },
  {
    value: 'swing',
    title: '빠르게 사고파는 투자자 (스윙 투자)',
    description: '타이밍을 보며 수익 기회를 빠르게 잡고 싶어요.',
    bullets: ['매수/관망/매도 신호 모두 보기', '수익 실현과 손절 기준 확인', '거래 기록으로 성과 확인'],
  },
]
const notificationIntegrationOptions: Array<{
  channel: NotificationIntegrationChannel
  shortTitle: string
  logoSrc: string
  disabled?: boolean
}> = [
  {
    channel: 'slack',
    shortTitle: '슬랙',
    logoSrc: '',
  },
  {
    channel: 'kakaoTalk',
    shortTitle: '카카오톡',
    logoSrc: 'https://cdn.simpleicons.org/kakaotalk/000000',
    disabled: true,
  },
]

function configuredAdminEmails() {
  const configuredEmails = (import.meta.env.VITE_ADMIN_EMAILS ?? '')
    .split(',')
    .map((email: string) => email.trim().toLowerCase())
    .filter(Boolean)
  return configuredEmails.length > 0 ? configuredEmails : DEFAULT_ADMIN_EMAILS
}

function isConfiguredAdminEmail(email: string | null | undefined) {
  return Boolean(email && configuredAdminEmails().includes(email.toLowerCase()))
}

function personalWatchlistStorageKey(session: UserSession | null) {
  return `${WATCHLIST_STORAGE_KEY}:${session?.email.toLowerCase() ?? 'guest'}`
}

function personalWatchlistPendingStorageKey(session: UserSession | null) {
  return `${PERSONAL_WATCHLIST_PENDING_STORAGE_KEY}:${session?.email.toLowerCase() ?? 'guest'}`
}

function readLegacyWatchlist(session: UserSession | null) {
  const scopedKey = personalWatchlistStorageKey(session)
  const storedWatchlist = localStorage.getItem(scopedKey) ?? localStorage.getItem(WATCHLIST_STORAGE_KEY)
  if (!storedWatchlist) return null

  try {
    const parsed = JSON.parse(storedWatchlist)
    return Array.isArray(parsed) ? parsed.filter((ticker): ticker is string => typeof ticker === 'string') : null
  } catch {
    localStorage.removeItem(scopedKey)
    return null
  }
}

function readStoredWatchlist(session: UserSession | null = null) {
  return readLegacyWatchlist(session) ?? initialWatchlist
}

function readStoredOperatorWatchlist() {
  const storedWatchlist = localStorage.getItem(OPERATOR_WATCHLIST_STORAGE_KEY)
  if (!storedWatchlist) return operatorTickers

  try {
    const parsed = JSON.parse(storedWatchlist)
    return Array.isArray(parsed) ? parsed.filter((ticker): ticker is string => typeof ticker === 'string') : operatorTickers
  } catch {
    localStorage.removeItem(OPERATOR_WATCHLIST_STORAGE_KEY)
    return operatorTickers
  }
}

function readCachedRemoteOperatorWatchlist() {
  const storedWatchlist = localStorage.getItem(OPERATOR_WATCHLIST_REMOTE_CACHE_STORAGE_KEY)
  if (!storedWatchlist) return []

  try {
    const parsed = JSON.parse(storedWatchlist)
    return Array.isArray(parsed) ? parsed.filter((ticker): ticker is string => typeof ticker === 'string') : []
  } catch {
    localStorage.removeItem(OPERATOR_WATCHLIST_REMOTE_CACHE_STORAGE_KEY)
    return []
  }
}

function sameWatchlistTickers(a: string[] | null | undefined, b: string[] | null | undefined) {
  return JSON.stringify(a ?? []) === JSON.stringify(b ?? [])
}

function storeRemoteOperatorWatchlist(tickers: string[]) {
  localStorage.setItem(OPERATOR_WATCHLIST_STORAGE_KEY, JSON.stringify(tickers))
  localStorage.setItem(OPERATOR_WATCHLIST_REMOTE_CACHE_STORAGE_KEY, JSON.stringify(tickers))
}

function parseRemoteUpdatedAt(value: unknown) {
  if (typeof value !== 'string' || !value) return null
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : null
}

function readPendingWatchlistEntry(storageKey: string): PendingWatchlistEntry | null {
  const storedWatchlist = localStorage.getItem(storageKey)
  if (!storedWatchlist) return null

  try {
    const parsed = JSON.parse(storedWatchlist) as { tickers?: unknown; updatedAt?: unknown }
    const updatedAt = typeof parsed.updatedAt === 'number' ? parsed.updatedAt : 0
    if (!updatedAt || Date.now() - updatedAt > PENDING_WATCHLIST_MAX_AGE_MS) {
      localStorage.removeItem(storageKey)
      return null
    }
    return {
      tickers: normalizeWatchlistTickers(parsed.tickers) ?? [],
      updatedAt,
    }
  } catch {
    localStorage.removeItem(storageKey)
    return null
  }
}

function resolveWatchlistWithPending(
  remote: { tickers: string[] | null; updatedAt: number | null },
  pending: PendingWatchlistEntry | null,
): ResolvedWatchlistState {
  const remoteTickers = remote.tickers ?? []
  if (!pending) {
    return { tickers: remoteTickers, pendingToSync: null, clearPending: false }
  }
  if (sameWatchlistTickers(remote.tickers, pending.tickers)) {
    return { tickers: remoteTickers, pendingToSync: null, clearPending: true }
  }
  const remoteUpdatedAt = remote.updatedAt ?? 0
  if (pending.updatedAt > remoteUpdatedAt) {
    return { tickers: pending.tickers, pendingToSync: pending.tickers, clearPending: false }
  }
  return { tickers: remoteTickers, pendingToSync: null, clearPending: true }
}

function readPendingPersonalWatchlist(session: UserSession | null) {
  return session ? readPendingWatchlistEntry(personalWatchlistPendingStorageKey(session)) : null
}

function readPendingOperatorWatchlist() {
  return readPendingWatchlistEntry(OPERATOR_WATCHLIST_PENDING_STORAGE_KEY)
}

function storePendingPersonalWatchlist(session: UserSession | null, tickers: string[]) {
  if (!session) return
  localStorage.setItem(personalWatchlistStorageKey(session), JSON.stringify(tickers))
  localStorage.setItem(personalWatchlistPendingStorageKey(session), JSON.stringify({ tickers, updatedAt: Date.now() }))
}

function storePendingOperatorWatchlist(tickers: string[]) {
  storeRemoteOperatorWatchlist(tickers)
  localStorage.setItem(OPERATOR_WATCHLIST_PENDING_STORAGE_KEY, JSON.stringify({ tickers, updatedAt: Date.now() }))
}

function clearPendingPersonalWatchlist(session: UserSession | null) {
  if (!session) return
  localStorage.removeItem(personalWatchlistPendingStorageKey(session))
}

function clearPendingOperatorWatchlist() {
  localStorage.removeItem(OPERATOR_WATCHLIST_PENDING_STORAGE_KEY)
}

function personalWatchlistByTypeStorageKey(session: UserSession | null) {
  return `${PERSONAL_WATCHLIST_BY_TYPE_STORAGE_KEY}:${session?.email.toLowerCase() ?? 'guest'}`
}

function readPersonalWatchlistByType(session: UserSession | null): Partial<Record<InvestmentType, string[]>> | null {
  const stored = localStorage.getItem(personalWatchlistByTypeStorageKey(session))
  if (!stored) return null
  try {
    const parsed = JSON.parse(stored) as Partial<Record<InvestmentType, unknown>> | null
    const result: Partial<Record<InvestmentType, string[]>> = {}
    const longTerm = normalizeWatchlistTickers(parsed?.long_term)
    const swing = normalizeWatchlistTickers(parsed?.swing)
    if (longTerm) result.long_term = longTerm
    if (swing) result.swing = swing
    return result
  } catch {
    localStorage.removeItem(personalWatchlistByTypeStorageKey(session))
    return null
  }
}

function storePersonalWatchlistByType(session: UserSession | null, store: Record<InvestmentType, string[]>) {
  localStorage.setItem(personalWatchlistByTypeStorageKey(session), JSON.stringify(store))
}

function readOperatorWatchlistByType(): Partial<Record<InvestmentType, string[]>> | null {
  const stored = localStorage.getItem(OPERATOR_WATCHLIST_BY_TYPE_STORAGE_KEY)
  if (!stored) return null
  try {
    const parsed = JSON.parse(stored) as Partial<Record<InvestmentType, unknown>> | null
    const result: Partial<Record<InvestmentType, string[]>> = {}
    const longTerm = normalizeWatchlistTickers(parsed?.long_term)
    const swing = normalizeWatchlistTickers(parsed?.swing)
    if (longTerm) result.long_term = longTerm
    if (swing) result.swing = swing
    return result
  } catch {
    localStorage.removeItem(OPERATOR_WATCHLIST_BY_TYPE_STORAGE_KEY)
    return null
  }
}

function storeOperatorWatchlistByType(store: Record<InvestmentType, string[]>) {
  localStorage.setItem(OPERATOR_WATCHLIST_BY_TYPE_STORAGE_KEY, JSON.stringify(store))
}

// DB(jsonb) 등 외부에서 받은 유형별 관심종목 값을 안전하게 정규화한다.
function normalizeWatchlistByType(value: unknown): Partial<Record<InvestmentType, string[]>> | null {
  if (!value || typeof value !== 'object') return null
  const parsed = value as Partial<Record<InvestmentType, unknown>>
  const result: Partial<Record<InvestmentType, string[]>> = {}
  const longTerm = normalizeWatchlistTickers(parsed.long_term)
  const swing = normalizeWatchlistTickers(parsed.swing)
  if (longTerm) result.long_term = longTerm
  if (swing) result.swing = swing
  return result
}

const APP_DATA_CACHE_STORAGE_KEY = 'gssg-app-data-cache-v1'
const APP_DATA_AUTO_REFRESH_INTERVAL_MS = 3 * 60 * 1000
const PENDING_WATCHLIST_MAX_AGE_MS = 24 * 60 * 60 * 1000

type GssgAppData = AppData<Stock, ValuationMetric, MarketEventGroup, MarketTrendRow, TradeLog>
type AppDataMetas = {
  stocks?: RuntimeMeta
  valuation?: RuntimeMeta
  technical?: RuntimeMeta
  marketEvents?: RuntimeMeta
  marketTrends?: RuntimeMeta
  tradeLogs?: RuntimeMeta
}

function readCachedAppData() {
  try {
    const cached = JSON.parse(localStorage.getItem(APP_DATA_CACHE_STORAGE_KEY) ?? 'null') as GssgAppData | null
    if (!cached || typeof cached !== 'object') return null
    return cached
  } catch {
    return null
  }
}

function storeCachedAppData(data: GssgAppData) {
  try {
    localStorage.setItem(APP_DATA_CACHE_STORAGE_KEY, JSON.stringify(data))
  } catch {
    // Cache is an optimization only; keep rendering with in-memory data.
  }
}

function wait(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms))
}

function runtimeMetaChanged(current: RuntimeMeta | undefined, previous: RuntimeMeta | undefined) {
  return Boolean(current?.updatedAt && current.updatedAt !== previous?.updatedAt)
}

function appDataMetaChanged(data: GssgAppData, previousMetas: AppDataMetas) {
  return (
    runtimeMetaChanged(data.stocks?.meta, previousMetas.stocks)
    || runtimeMetaChanged(data.valuation?.meta, previousMetas.valuation)
    || runtimeMetaChanged(data.technical?.meta, previousMetas.technical)
    || runtimeMetaChanged(data.marketEvents?.meta, previousMetas.marketEvents)
    || runtimeMetaChanged(data.marketTrends?.meta, previousMetas.marketTrends)
    || runtimeMetaChanged(data.tradeLogs?.meta, previousMetas.tradeLogs)
  )
}

function readStoredViewMode() {
  return localStorage.getItem(VIEW_MODE_STORAGE_KEY) === 'operator' ? 'operator' : 'personal'
}

function readStoredActivePage(): ActivePage {
  const stored = localStorage.getItem(ACTIVE_PAGE_STORAGE_KEY)
  return activePages.includes(stored as ActivePage) ? stored as ActivePage : 'home'
}

function activePageFromHash() {
  const page = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  return activePages.includes(page as ActivePage) ? page as ActivePage : null
}

function readInitialActivePage(): ActivePage {
  return activePageFromHash() ?? readStoredActivePage()
}

function activePageHash(page: ActivePage) {
  return `#${page}`
}

function activePageHashParams() {
  const [, rawQuery = ''] = window.location.hash.split('?')
  return new URLSearchParams(rawQuery)
}

function notificationSettingsDeepLinkMessage() {
  const params = activePageHashParams()
  if (params.get('notification') === 'unsubscribed') {
    return '알림 수신 설정이 해제되었습니다.'
  }
  return ''
}

function hasNotificationSettingsDeepLink() {
  const params = activePageHashParams()
  return params.get('settings') === 'notifications' || params.get('notification') === 'unsubscribed'
}

function authCallbackParams() {
  const params = new URLSearchParams(window.location.search)
  const hash = window.location.hash.replace(/^#/, '')
  if (hash.includes('=')) {
    const [, rawHashQuery = hash] = hash.split('?')
    const hashParams = new URLSearchParams(rawHashQuery)
    hashParams.forEach((value, key) => params.set(key, value))
  }
  return params
}

function authCallbackMessage() {
  const params = authCallbackParams()
  const errorCode = params.get('error_code')
  const errorDescription = params.get('error_description') ?? params.get('error')
  if (errorCode === 'otp_expired') {
    return '가입 확인 링크가 만료되었거나 이미 사용되었습니다.\n회원가입 탭에서 같은 이메일로 다시 요청해 주세요.'
  }
  if (errorDescription) {
    return `인증 링크를 처리하지 못했습니다.\n${errorDescription.replace(/\+/g, ' ')}`
  }
  return ''
}

function hasAuthCallbackError() {
  const params = authCallbackParams()
  return Boolean(params.get('error') || params.get('error_code') || params.get('error_description'))
}

function hasAuthCallbackPayload() {
  const params = authCallbackParams()
  return Boolean(
    params.get('access_token')
    || params.get('refresh_token')
    || params.get('code')
    || params.get('type') === 'signup'
    || params.get('type') === 'recovery',
  )
}

function authCallbackSuccessMessage() {
  const type = authCallbackParams().get('type')
  if (type === 'signup') {
    return '이메일 인증이 완료되었습니다.\n계정으로 로그인되었습니다.'
  }
  if (type === 'recovery') {
    return '비밀번호 재설정 링크가 확인되었습니다.\n새 비밀번호를 입력해 주세요.'
  }
  if (hasAuthCallbackPayload()) {
    return '인증이 완료되었습니다.\n계정 정보를 불러왔습니다.'
  }
  return ''
}

function clearAuthCallbackFromUrl() {
  if (!hasAuthCallbackError() && !hasAuthCallbackPayload()) return
  const searchParams = new URLSearchParams(window.location.search)
  ;['code', 'error', 'error_code', 'error_description'].forEach((key) => searchParams.delete(key))
  const nextSearch = searchParams.toString()
  const nextHash = activePageHash(readStoredActivePage())
  window.history.replaceState(null, '', `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ''}${nextHash}`)
}

function clearAuthCallbackErrorFromUrl() {
  if (!hasAuthCallbackError()) return
  clearAuthCallbackFromUrl()
}

function userSettingsStorageKey(session: UserSession | null = null) {
  return `${USER_SETTINGS_STORAGE_KEY}:${session?.email.toLowerCase() ?? 'guest'}`
}

function contributionSettingsStorageKey(session: UserSession | null = null) {
  return `${CONTRIBUTION_SETTINGS_STORAGE_KEY}:${session?.email.toLowerCase() ?? 'guest'}`
}

function personalTradeLogsStorageKey(session: UserSession | null = null) {
  return `${PERSONAL_TRADES_STORAGE_KEY}:${session?.email.toLowerCase() ?? 'guest'}`
}

function hasStoredContributionSettings(session: UserSession | null = null) {
  return Boolean(localStorage.getItem(contributionSettingsStorageKey(session)) ?? localStorage.getItem(CONTRIBUTION_SETTINGS_STORAGE_KEY))
}

function hasStoredPersonalTradeLogs(session: UserSession | null = null) {
  return Boolean(localStorage.getItem(personalTradeLogsStorageKey(session)))
}

function hasStoredWatchlist(session: UserSession | null = null) {
  if (!session) return false
  return Boolean(
    localStorage.getItem(personalWatchlistStorageKey(session))
    ?? localStorage.getItem(WATCHLIST_STORAGE_KEY),
  )
}

function resolveLocalTestWatchlist(session: UserSession) {
  if (isConfiguredAdminEmail(session.email)) return readStoredWatchlist(session)
  if (!hasStoredWatchlist(session)) return localTestWatchlist
  return readLegacyWatchlist(session) ?? initialWatchlist
}

function resolveLocalTestPersonalTrades(session: UserSession) {
  if (isConfiguredAdminEmail(session.email)) return readStoredPersonalTradeLogs(session)
  if (!hasStoredPersonalTradeLogs(session)) return localTestPersonalTrades
  return readStoredPersonalTradeLogs(session)
}

function isLocalTestSession(session: UserSession | null) {
  return Boolean(session?.id.startsWith('local-test-'))
}

function normalizeWatchlistSortSettings(value: unknown): WatchlistSortSettings {
  const allowed: WatchlistSortKey[] = [
    'registered',
    'market_kr_first',
    'market_us_first',
    'holding_first',
    'not_holding_first',
    'valuation_low_first',
    'valuation_high_first',
    'opinion_buy_first',
    'opinion_sell_first',
    'name_asc',
    'name_desc',
  ]
  const candidate = value as Partial<WatchlistSortSettings> | null
  const primary = candidate && allowed.includes(candidate.primary as WatchlistSortKey) ? candidate.primary as WatchlistSortKey : DEFAULT_WATCHLIST_SORT.primary
  const secondary = candidate && allowed.includes(candidate.secondary as WatchlistSortKey) ? candidate.secondary as WatchlistSortKey : DEFAULT_WATCHLIST_SORT.secondary
  return { primary, secondary }
}

function readOperatorWatchlistSortSettings() {
  const stored = localStorage.getItem(OPERATOR_WATCHLIST_SORT_STORAGE_KEY)
  if (!stored) return null

  try {
    return normalizeWatchlistSortSettings(JSON.parse(stored))
  } catch {
    localStorage.removeItem(OPERATOR_WATCHLIST_SORT_STORAGE_KEY)
    return null
  }
}

function storeOperatorWatchlistSortSettings(watchlistSort: WatchlistSortSettings) {
  localStorage.setItem(OPERATOR_WATCHLIST_SORT_STORAGE_KEY, JSON.stringify(watchlistSort))
}

function normalizeWatchlistTickers(value: unknown) {
  return Array.isArray(value) ? value.filter((ticker): ticker is string => typeof ticker === 'string') : null
}

function normalizeNotificationChannel(value: unknown): NotificationDeliveryChannel {
  return value === 'kakaoTalk' || value === 'slack' ? value : 'email'
}

function normalizeNotificationPreferences(value: unknown): NotificationPreferences {
  const candidate = value as Partial<NotificationPreferences> | null
  const kakaoTalkConnected = typeof candidate?.kakaoTalkConnected === 'boolean' ? candidate.kakaoTalkConnected : DEFAULT_NOTIFICATION_PREFERENCES.kakaoTalkConnected
  const slackConnected = typeof candidate?.slackConnected === 'boolean' ? candidate.slackConnected : DEFAULT_NOTIFICATION_PREFERENCES.slackConnected
  const requestedChannel = normalizeNotificationChannel(candidate?.notificationChannel)
  const notificationChannel = requestedChannel === 'kakaoTalk' && !kakaoTalkConnected
    ? 'email'
    : requestedChannel === 'slack' && !slackConnected
      ? 'email'
      : requestedChannel

  return {
    opinionChangeEmail: typeof candidate?.opinionChangeEmail === 'boolean' ? candidate.opinionChangeEmail : DEFAULT_NOTIFICATION_PREFERENCES.opinionChangeEmail,
    nasdaqPeakEmail: typeof candidate?.nasdaqPeakEmail === 'boolean' ? candidate.nasdaqPeakEmail : DEFAULT_NOTIFICATION_PREFERENCES.nasdaqPeakEmail,
    regimeShiftEmail: typeof candidate?.regimeShiftEmail === 'boolean' ? candidate.regimeShiftEmail : DEFAULT_NOTIFICATION_PREFERENCES.regimeShiftEmail,
    bbPullbackEmail: typeof candidate?.bbPullbackEmail === 'boolean' ? candidate.bbPullbackEmail : DEFAULT_NOTIFICATION_PREFERENCES.bbPullbackEmail,
    weeklyTrendReport: typeof candidate?.weeklyTrendReport === 'boolean' ? candidate.weeklyTrendReport : DEFAULT_NOTIFICATION_PREFERENCES.weeklyTrendReport,
    earningsDayBefore: typeof candidate?.earningsDayBefore === 'boolean' ? candidate.earningsDayBefore : DEFAULT_NOTIFICATION_PREFERENCES.earningsDayBefore,
    adminAutoUpdateFailureEmail: typeof candidate?.adminAutoUpdateFailureEmail === 'boolean' ? candidate.adminAutoUpdateFailureEmail : DEFAULT_NOTIFICATION_PREFERENCES.adminAutoUpdateFailureEmail,
    recipientEmail: typeof candidate?.recipientEmail === 'string' ? candidate.recipientEmail.trim() : DEFAULT_NOTIFICATION_PREFERENCES.recipientEmail,
    notificationChannel,
    kakaoTalkConnected,
    slackConnected,
    kakaoTalkConnectedAt: typeof candidate?.kakaoTalkConnectedAt === 'string' ? candidate.kakaoTalkConnectedAt : DEFAULT_NOTIFICATION_PREFERENCES.kakaoTalkConnectedAt,
    slackConnectedAt: typeof candidate?.slackConnectedAt === 'string' ? candidate.slackConnectedAt : DEFAULT_NOTIFICATION_PREFERENCES.slackConnectedAt,
  }
}

function normalizeInvestmentType(value: unknown): InvestmentType | null {
  return value === 'swing' || value === 'long_term' ? value : null
}

function normalizeTradeLog(value: unknown): TradeLog | null {
  const candidate = value as Partial<TradeLog> | null
  if (!candidate || typeof candidate.ticker !== 'string' || typeof candidate.buyDate !== 'string') return null
  const normalizedStatus = String(candidate.status).replace(/[()]/g, ' ').replace(/\s+/g, ' ').trim()

  return {
    slotId: typeof candidate.slotId === 'string' ? candidate.slotId : undefined,
    investmentType: normalizeInvestmentType(candidate.investmentType) ?? undefined,
    investmentAmount: typeof candidate.investmentAmount === 'number' && Number.isFinite(candidate.investmentAmount) ? candidate.investmentAmount : undefined,
    ticker: candidate.ticker,
    name: typeof candidate.name === 'string' ? candidate.name : undefined,
    market: candidate.market === 'KR' || candidate.market === 'US' ? candidate.market : undefined,
    currentPrice: typeof candidate.currentPrice === 'string' ? candidate.currentPrice : undefined,
    strategy: typeof candidate.strategy === 'string' ? candidate.strategy : '-',
    buyDate: candidate.buyDate,
    buyPrice: typeof candidate.buyPrice === 'string' ? candidate.buyPrice : '-',
    sellDate: typeof candidate.sellDate === 'string' ? candidate.sellDate : '-',
    sellPrice: typeof candidate.sellPrice === 'string' ? candidate.sellPrice : '-',
    returnPct: typeof candidate.returnPct === 'number' && Number.isFinite(candidate.returnPct) ? candidate.returnPct : 0,
    holdingDays: typeof candidate.holdingDays === 'number' || candidate.holdingDays === '-' ? candidate.holdingDays : '-',
    status: ['익절', '손절', '실패 익절', '보유 중'].includes(normalizedStatus) ? normalizedStatus as TradeStatus : '보유 중',
    manualExit: candidate.manualExit === true ? true : undefined,
  }
}

function readStoredPersonalTradeLogs(session: UserSession | null = null) {
  if (!session) return []
  const stored = localStorage.getItem(personalTradeLogsStorageKey(session))
  if (!stored) return personalTrades

  try {
    const parsed = JSON.parse(stored)
    if (!Array.isArray(parsed)) return personalTrades
    const normalized = parsed.map(normalizeTradeLog).filter((trade): trade is TradeLog => Boolean(trade))
    if (import.meta.env.DEV && normalized.length > 0 && normalized.every((trade) => !trade.investmentType)) {
      return personalTrades
    }
    return normalized
  } catch {
    localStorage.removeItem(personalTradeLogsStorageKey(session))
    return personalTrades
  }
}

function storePersonalTradeLogs(session: UserSession | null, trades: TradeLog[]) {
  localStorage.setItem(personalTradeLogsStorageKey(session), JSON.stringify(trades))
}

function readStoredUserSettings(session: UserSession | null = null): StoredUserSettings {
  const stored = localStorage.getItem(userSettingsStorageKey(session)) ?? (session ? localStorage.getItem(USER_SETTINGS_STORAGE_KEY) : null)
  if (!stored) {
    return {
      ...DEFAULT_USER_SETTINGS,
      watchlistSort: session ? DEFAULT_USER_SETTINGS.watchlistSort : readOperatorWatchlistSortSettings() ?? DEFAULT_USER_SETTINGS.watchlistSort,
    }
  }

  try {
    const parsed = JSON.parse(stored)
    return {
      watchlistSort: normalizeWatchlistSortSettings(parsed.watchlistSort),
      notificationPreferences: normalizeNotificationPreferences(parsed.notificationPreferences),
      investmentType: normalizeInvestmentType(parsed.investmentType),
    }
  } catch {
    localStorage.removeItem(userSettingsStorageKey(session))
    return {
      ...DEFAULT_USER_SETTINGS,
      watchlistSort: session ? DEFAULT_USER_SETTINGS.watchlistSort : readOperatorWatchlistSortSettings() ?? DEFAULT_USER_SETTINGS.watchlistSort,
    }
  }
}

function storeUserSettings(
  session: UserSession | null,
  watchlistSort: WatchlistSortSettings,
  notificationPreferences: NotificationPreferences,
  investmentType: InvestmentType | null,
) {
  localStorage.setItem(userSettingsStorageKey(session), JSON.stringify({ watchlistSort, notificationPreferences, investmentType }))
}

function readCachedRemoteUserSettings() {
  const stored = localStorage.getItem(USER_SETTINGS_REMOTE_CACHE_STORAGE_KEY)
  if (!stored) return null

  try {
    const parsed = JSON.parse(stored)
    return {
      watchlistSort: normalizeWatchlistSortSettings(parsed.watchlistSort),
      notificationPreferences: normalizeNotificationPreferences(parsed.notificationPreferences),
      investmentType: normalizeInvestmentType(parsed.investmentType),
    }
  } catch {
    localStorage.removeItem(USER_SETTINGS_REMOTE_CACHE_STORAGE_KEY)
    return null
  }
}

function storeCachedRemoteUserSettings(settings: StoredUserSettings) {
  localStorage.setItem(USER_SETTINGS_REMOTE_CACHE_STORAGE_KEY, JSON.stringify(settings))
}

function normalizeAllocationSettings(value: unknown, investmentType: InvestmentType): AllocationSettings {
  const fallback = DEFAULT_ALLOCATION_SETTINGS[investmentType]
  const candidate = value as Partial<AllocationSettings> | null
  const slotCount = typeof candidate?.slotCount === 'number' && Number.isFinite(candidate.slotCount)
    ? Math.min(20, Math.max(1, Math.round(candidate.slotCount)))
    : fallback.slotCount
  const candidatePercents = Array.isArray(candidate?.slotPercents) ? candidate.slotPercents : []
  const slotPercents = Array.from({ length: slotCount }, (_, index) => {
    const value = candidatePercents[index]
    if (typeof value === 'number' && Number.isFinite(value)) {
      return Math.min(100, Math.max(0, Math.round(value)))
    }
    return fallback.slotPercents[index] ?? 0
  })

  return { slotCount, slotPercents }
}

function normalizeContributionSettings(value: unknown): ContributionSettings {
  const candidate = value as Partial<ContributionSettings> | null
  if (!candidate) return DEFAULT_CONTRIBUTION_SETTINGS
  const frequency = candidate.frequency === 'weekly' || candidate.frequency === 'monthly' ? candidate.frequency : DEFAULT_CONTRIBUTION_SETTINGS.frequency
  const initialCapital = typeof candidate.initialCapital === 'number' && Number.isFinite(candidate.initialCapital)
    ? Math.max(0, Math.round(candidate.initialCapital))
    : DEFAULT_CONTRIBUTION_SETTINGS.initialCapital
  const amount = typeof candidate.amount === 'number' && Number.isFinite(candidate.amount)
    ? Math.max(0, Math.round(candidate.amount))
    : DEFAULT_CONTRIBUTION_SETTINGS.amount

  return {
    initialCapital,
    frequency,
    amount,
    dayOfWeek: Math.min(6, Math.max(0, Number(candidate.dayOfWeek) || DEFAULT_CONTRIBUTION_SETTINGS.dayOfWeek)),
    dayOfMonth: Math.min(31, Math.max(1, Number(candidate.dayOfMonth) || DEFAULT_CONTRIBUTION_SETTINGS.dayOfMonth)),
    allocationByInvestmentType: {
      swing: normalizeAllocationSettings(candidate.allocationByInvestmentType?.swing, 'swing'),
      long_term: normalizeAllocationSettings(candidate.allocationByInvestmentType?.long_term, 'long_term'),
    },
  }
}

function readStoredContributionSettings(session: UserSession | null = null): ContributionSettings {
  const stored = localStorage.getItem(contributionSettingsStorageKey(session)) ?? localStorage.getItem(CONTRIBUTION_SETTINGS_STORAGE_KEY)
  if (!stored) return DEFAULT_CONTRIBUTION_SETTINGS
  try {
    return normalizeContributionSettings(JSON.parse(stored))
  } catch {
    localStorage.removeItem(contributionSettingsStorageKey(session))
    return DEFAULT_CONTRIBUTION_SETTINGS
  }
}

function storeContributionSettings(session: UserSession | null, settings: ContributionSettings) {
  localStorage.setItem(contributionSettingsStorageKey(session), JSON.stringify(settings))
}

function readStoredLocalTestSession({ allowProduction = false } = {}): UserSession | null {
  if (!import.meta.env.DEV && !allowProduction) return null
  const stored = localStorage.getItem(LOCAL_TEST_SESSION_STORAGE_KEY)
  if (!stored) return null

  try {
    const parsed = JSON.parse(stored) as Partial<UserSession>
    if (typeof parsed.email !== 'string' || typeof parsed.id !== 'string' || typeof parsed.name !== 'string') return null
    return {
      id: parsed.id,
      email: parsed.email,
      name: parsed.name,
      loggedInAt: typeof parsed.loggedInAt === 'string' ? parsed.loggedInAt : new Date().toISOString(),
    }
  } catch {
    localStorage.removeItem(LOCAL_TEST_SESSION_STORAGE_KEY)
    return null
  }
}

function storeLocalTestSession(session: UserSession | null, { allowProduction = false } = {}) {
  if (!import.meta.env.DEV && !allowProduction) return
  if (!session) {
    localStorage.removeItem(LOCAL_TEST_SESSION_STORAGE_KEY)
    return
  }
  localStorage.setItem(LOCAL_TEST_SESSION_STORAGE_KEY, JSON.stringify(session))
}

function readStoredApiLogs() {
  const stored = localStorage.getItem(API_LOGS_STORAGE_KEY)
  if (!stored) return []
  try {
    const parsed = JSON.parse(stored)
    return Array.isArray(parsed) ? parsed.filter((row): row is ApiLog => typeof row?.id === 'string') : []
  } catch {
    localStorage.removeItem(API_LOGS_STORAGE_KEY)
    return []
  }
}

function storeApiLogs(logs: ApiLog[]) {
  const cutoff = Date.now() - 21 * 24 * 60 * 60 * 1000
  localStorage.setItem(API_LOGS_STORAGE_KEY, JSON.stringify(
    logs.filter((log) => new Date(log.createdAt).getTime() >= cutoff).slice(0, 200),
  ))
}

function mapApiLog(row: {
  id: string
  trigger_name: string
  status: string
  message: string | null
  created_at: string
  metadata: Record<string, unknown> | null
  profiles?: { email?: string | null } | null
}): ApiLog {
  return {
    id: row.id,
    triggerName: row.trigger_name,
    status: row.status === 'failure' ? 'failure' : 'success',
    message: row.message ?? '',
    createdAt: row.created_at,
    actorEmail: row.profiles?.email ?? undefined,
    metadata: row.metadata ?? {},
  }
}

function sessionFromSupabaseUser(user: User): UserSession {
  return {
    id: user.id,
    email: user.email ?? '',
    name: userDisplayName(user),
    loggedInAt: user.last_sign_in_at ?? new Date().toISOString(),
  }
}

function mapBoardPost(row: {
  id: string
  category: string
  content: string
  created_at: string
  author_id: string
  author_name: string
  hidden: boolean | null
  board_comments?: Array<{
    id: string
    post_id: string
    content: string
    created_at: string
    author_id: string
    author_name: string
  }> | null
}): BoardPost {
  return {
    id: row.id,
    category: boardCategories.includes(row.category as BoardCategory) ? row.category as BoardCategory : '기타',
    content: row.content,
    createdAt: row.created_at,
    authorId: row.author_id,
    authorName: row.author_name,
    comments: (row.board_comments ?? [])
      .map(mapBoardComment)
      .sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()),
    hidden: row.hidden ?? false,
  }
}

function mapBoardComment(row: {
  id: string
  post_id: string
  content: string
  created_at: string
  author_id: string
  author_name: string
}): BoardComment {
  return {
    id: row.id,
    postId: row.post_id,
    content: row.content,
    createdAt: row.created_at,
    authorId: row.author_id,
    authorName: row.author_name,
  }
}

const searchUniverse: Stock[] = [
  {
    ticker: '005930',
    name: '삼성전자',
    market: 'KR',
    fairPrice: '₩82,000',
    currentPrice: '₩84,200',
    valuation: '보통',
    opinion: '관망',
    strategies: ['D. 200일선 상방 & 상승 흐름 강화'],
    updatedAt: '2시간 전',
  },
  {
    ticker: 'NVDA',
    name: 'NVIDIA',
    market: 'US',
    fairPrice: '$98.00',
    currentPrice: '$109.88',
    valuation: '고평가',
    opinion: '관망',
    strategies: ['A. 200일선 상방 & 모멘텀 재가속'],
    updatedAt: '2시간 전',
  },
  {
    ticker: 'AAPL',
    name: 'Apple',
    market: 'US',
    fairPrice: '$203.00',
    currentPrice: '$195.42',
    valuation: '보통',
    opinion: '매수',
    strategies: ['C. 200일선 상방 & 스퀴즈 거래량 돌파', 'D. 200일선 상방 & 상승 흐름 강화'],
    updatedAt: '2시간 전',
  },
  {
    ticker: 'TSLA',
    name: 'Tesla',
    market: 'US',
    fairPrice: '$230.00',
    currentPrice: '$265.30',
    valuation: '고평가',
    opinion: '매도',
    strategies: ['F. 200일선 상방 & BB 극단 저점'],
    updatedAt: '2시간 전',
  },
  {
    ticker: '035420',
    name: 'NAVER',
    market: 'KR',
    fairPrice: '₩245,000',
    currentPrice: '₩209,500',
    valuation: '저평가',
    opinion: '매수',
    strategies: ['E. 200일선 상방 & 스퀴즈 저점'],
    updatedAt: '2시간 전',
  },
  {
    ticker: '042700',
    name: '한미반도체',
    market: 'KR',
    fairPrice: '₩178,000',
    currentPrice: '₩169,400',
    valuation: '보통',
    opinion: '관망',
    strategies: ['D. 200일선 상방 & 상승 흐름 강화'],
    updatedAt: '2시간 전',
  },
  {
    ticker: '247540',
    name: '에코프로비엠',
    market: 'KR',
    fairPrice: '₩132,000',
    currentPrice: '₩151,800',
    valuation: '고평가',
    opinion: '매도',
    strategies: ['E. 200일선 상방 & 스퀴즈 저점'],
    updatedAt: '2시간 전',
  },
  {
    ticker: 'ONON',
    name: 'On Holding',
    market: 'US',
    fairPrice: '$46.00',
    currentPrice: '$38.30',
    valuation: '보통',
    opinion: '매수',
    strategies: ['B. 200일선 하방 & 공황 저점'],
    updatedAt: '2시간 전',
  },
  {
    ticker: 'BE',
    name: 'Bloom Energy',
    market: 'US',
    fairPrice: '$27.00',
    currentPrice: '$20.70',
    valuation: '저평가',
    opinion: '관망',
    strategies: ['F. 200일선 상방 & BB 극단 저점'],
    updatedAt: '2시간 전',
  },
  {
    ticker: 'LRCX',
    name: 'Lam Research',
    market: 'US',
    fairPrice: '$104.00',
    currentPrice: '$95.20',
    valuation: '보통',
    opinion: '매수',
    strategies: ['D. 200일선 상방 & 상승 흐름 강화'],
    updatedAt: '2시간 전',
  },
  {
    ticker: 'SNDK',
    name: 'Sandisk',
    market: 'US',
    fairPrice: '$68.00',
    currentPrice: '$57.40',
    valuation: '저평가',
    opinion: '관망',
    strategies: ['A. 200일선 상방 & 모멘텀 재가속'],
    updatedAt: '2시간 전',
  },
  {
    ticker: 'MSFT',
    name: 'Microsoft',
    market: 'US',
    fairPrice: '$520.00',
    currentPrice: '$485.90',
    valuation: '보통',
    opinion: '매수',
    strategies: ['C. 200일선 상방 & 스퀴즈 거래량 돌파'],
    updatedAt: '2시간 전',
  },
]

function stockSearchShell(stock: Stock): Stock {
  return {
    ...withDisplayStockName(stock),
    fairPrice: '-',
    currentPrice: '-',
    valuation: '보통',
    opinion: '관망',
    strategies: [],
    category: stock.category,
    industry: stock.industry ?? '-',
    updatedAt: '-',
  }
}

function mergeStocks(primary: Stock[], secondary: Stock[]) {
  const rowsByTicker = new Map<string, Stock>()
  for (const stock of secondary) rowsByTicker.set(stock.ticker, stockSearchShell(stock))
  for (const stock of primary) rowsByTicker.set(stock.ticker, withDisplayStockName(stock))
  return [...rowsByTicker.values()]
}

function watchlistStockShell(ticker: string): Stock {
  const normalized = ticker.trim().toUpperCase()
  return stockSearchShell({
    ticker: normalized,
    name: stockName(normalized),
    market: stockMarket(normalized),
    fairPrice: '-',
    currentPrice: '-',
    valuation: '보통',
    opinion: '관망',
    strategies: [],
    updatedAt: '-',
  })
}

function resolveStockForTicker(ticker: string, primaryStocks: Stock[], fallbackStocks: Stock[] = []) {
  const normalized = ticker.trim().toUpperCase()
  const matchesTicker = (stock: Stock) => stock.ticker.trim().toUpperCase() === normalized
  const fromPrimary = primaryStocks.find(matchesTicker)
  if (fromPrimary) return withDisplayStockName(fromPrimary)
  const fromFallback = fallbackStocks.find(matchesTicker)
  if (fromFallback) return withDisplayStockName(fromFallback)
  return watchlistStockShell(normalized)
}

const initialWatchlist: string[] = []

const operatorTickers: string[] = []
const strategyFilters = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
const personalTrades: TradeLog[] = []
const localTestWatchlist = ['AVGO', 'NVDA', 'MSFT', '005930']
const localTestPersonalTrades: TradeLog[] = [
  {
    investmentType: 'long_term',
    ticker: 'AVGO',
    name: 'Broadcom',
    market: 'US',
    currentPrice: '$425.19',
    strategy: 'E. 200일선 상방 & 스퀴즈 저점',
    buyDate: '2026.04.18',
    buyPrice: '$389.40',
    sellDate: '-',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    investmentType: 'long_term',
    ticker: 'MSFT',
    name: 'Microsoft',
    market: 'US',
    currentPrice: '$485.90',
    strategy: 'C. 200일선 상방 & 스퀴즈 거래량 돌파',
    buyDate: '2026.04.22',
    buyPrice: '$461.30',
    sellDate: '-',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    investmentType: 'swing',
    ticker: 'AVGO',
    name: 'Broadcom',
    market: 'US',
    currentPrice: '$425.19',
    strategy: 'E. 200일선 상방 & 스퀴즈 저점',
    buyDate: '2026.04.18',
    buyPrice: '$389.40',
    sellDate: '2026.05.15',
    sellPrice: '$425.19',
    returnPct: 9.19,
    holdingDays: 27,
    status: '실패 익절',
  },
  {
    investmentType: 'swing',
    ticker: 'NVDA',
    name: 'NVIDIA',
    market: 'US',
    currentPrice: '$118.40',
    strategy: 'D. 200일선 상방 & 상승 흐름 강화',
    buyDate: '2026.04.15',
    buyPrice: '$104.20',
    sellDate: '2026.05.08',
    sellPrice: '$118.40',
    returnPct: 13.63,
    holdingDays: 23,
    status: '익절',
  },
  {
    investmentType: 'swing',
    ticker: '005930',
    name: '삼성전자',
    market: 'KR',
    currentPrice: '₩78,300',
    strategy: 'A. 200일선 상방 & 모멘텀 재가속',
    buyDate: '2026.05.02',
    buyPrice: '₩75,100',
    sellDate: '-',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
]
const operatorTrades: TradeLog[] = []
const valuationMetrics: Record<string, ValuationMetric> = {
  '005930': {
    marketCap: '106조 7,264억',
    sales: '186조 2,545억',
    salesQoq: '+3.2%',
    salesYoyTtm: '+11.8%',
    salesPastYears: '+4.9% / +6.2%',
    currentRatio: '2.61',
    priceToFreeCashFlow: '18.4',
    priceToSales: '1.02',
    per: '15.03',
    pbr: '1.21',
    roe: '8.41%',
    peg: '1.8',
    sharesOutstanding: '59억 6,978만',
    grossMargin: '38.7%',
    operatingMargin: '14.2%',
    epsTtm: '₩3,240',
    epsNextYear: '₩4,110',
    epsQoq: '+18.2%',
    ruleOf40: '26.0%',
    earningsDate: '2026.07.30',
  },
  NVDA: {
    marketCap: '1,292조 1,040억',
    sales: '333조 6,059억',
    salesQoq: '+12.1%',
    salesYoyTtm: '+68.4%',
    salesPastYears: '+37.4% / +52.8%',
    currentRatio: '4.77',
    priceToFreeCashFlow: '59.2',
    priceToSales: '30.46',
    per: '38.57',
    pbr: '20.18',
    roe: '52.3%',
    peg: '1.2',
    sharesOutstanding: '244억',
    grossMargin: '74.6%',
    operatingMargin: '61.9%',
    epsTtm: '$2.84',
    epsNextYear: '$4.12',
    epsQoq: '+64.1%',
    ruleOf40: '130.3%',
    earningsDate: '2026.05.27',
  },
  AAPL: {
    marketCap: '973조 1,467억',
    sales: '341억',
    salesQoq: '+0.4%',
    salesYoyTtm: '+2.1%',
    salesPastYears: '+1.1% / +5.4%',
    currentRatio: '0.87',
    priceToFreeCashFlow: '28.6',
    priceToSales: '9.43',
    per: '21.81',
    pbr: '7.37',
    roe: '44.0%',
    peg: '2.7',
    sharesOutstanding: '151억',
    grossMargin: '46.2%',
    operatingMargin: '31.5%',
    epsTtm: '$6.43',
    epsNextYear: '$7.12',
    epsQoq: '+3.7%',
    ruleOf40: '33.6%',
    earningsDate: '2026.07.23',
  },
  TSLA: {
    marketCap: '108조 7,264억',
    sales: '186조 2,545억',
    salesQoq: '-8.7%',
    salesYoyTtm: '-3.4%',
    salesPastYears: '+16.2% / +24.1%',
    currentRatio: '2.03',
    priceToFreeCashFlow: '96.3',
    priceToSales: '8.29',
    per: '148.2',
    pbr: '10.46',
    roe: '5.0%',
    peg: '5.8',
    sharesOutstanding: '32억 1,000만',
    grossMargin: '17.8%',
    operatingMargin: '6.3%',
    epsTtm: '$1.79',
    epsNextYear: '$2.18',
    epsQoq: '-20.4%',
    ruleOf40: '2.9%',
    earningsDate: '2026.07.16',
  },
  '035420': {
    marketCap: '27조 9,575억',
    sales: '97조 4,293억',
    salesQoq: '+4.8%',
    salesYoyTtm: '+10.9%',
    salesPastYears: '+9.1% / +13.3%',
    currentRatio: '1.55',
    priceToFreeCashFlow: '15.8',
    priceToSales: '0.29',
    per: '3.27',
    pbr: '0.58',
    roe: '19.0%',
    peg: '0.6',
    sharesOutstanding: '1억 6,400만',
    grossMargin: '39.4%',
    operatingMargin: '15.1%',
    epsTtm: '₩64,120',
    epsNextYear: '₩69,800',
    epsQoq: '+9.8%',
    ruleOf40: '26.0%',
    earningsDate: '2026.08.06',
  },
  '042700': {
    marketCap: '35조 7,499억',
    sales: '5,766억',
    salesQoq: '+16.7%',
    salesYoyTtm: '+44.6%',
    salesPastYears: '+28.2% / +35.1%',
    currentRatio: '3.21',
    priceToFreeCashFlow: '42.6',
    priceToSales: '60.83',
    per: '164.8',
    pbr: '50.56',
    roe: '34.8%',
    peg: '3.9',
    sharesOutstanding: '9,771만',
    grossMargin: '57.1%',
    operatingMargin: '36.8%',
    epsTtm: '₩1,028',
    epsNextYear: '₩1,790',
    epsQoq: '+52.6%',
    ruleOf40: '81.4%',
    earningsDate: '2026.08.12',
  },
  '247540': {
    marketCap: '20조 1,531억',
    sales: '2조 5,316억',
    salesQoq: '-4.9%',
    salesYoyTtm: '-21.6%',
    salesPastYears: '+18.4% / +41.7%',
    currentRatio: '1.12',
    priceToFreeCashFlow: '-',
    priceToSales: '7.96',
    per: '511.17',
    pbr: '11.65',
    roe: '2.29%',
    peg: '-',
    sharesOutstanding: '9,782만',
    grossMargin: '12.8%',
    operatingMargin: '-1.6%',
    epsTtm: '₩297',
    epsNextYear: '₩1,240',
    epsQoq: '-36.5%',
    ruleOf40: '-23.2%',
    earningsDate: '2026.08.07',
  },
  ONON: {
    marketCap: '62조 1,452억',
    sales: '11조 3,143억',
    salesQoq: '+28.9%',
    salesYoyTtm: '+32.2%',
    salesPastYears: '+43.6% / +49.8%',
    currentRatio: '2.77',
    priceToFreeCashFlow: '48.5',
    priceToSales: '5.49',
    per: '91.44',
    pbr: '6.59',
    roe: '7.70%',
    peg: '2.1',
    sharesOutstanding: '6억 3,000만',
    grossMargin: '59.8%',
    operatingMargin: '12.6%',
    epsTtm: '$0.42',
    epsNextYear: '$0.75',
    epsQoq: '+41.0%',
    ruleOf40: '44.8%',
    earningsDate: '2026.05.12',
  },
  BE: {
    marketCap: '5조 7,499억',
    sales: '1조 2,202억',
    salesQoq: '-3.6%',
    salesYoyTtm: '+8.1%',
    salesPastYears: '+17.7% / +19.4%',
    currentRatio: '2.01',
    priceToFreeCashFlow: '-',
    priceToSales: '0.68',
    per: '37.21',
    pbr: '50.56',
    roe: '4.67%',
    peg: '1.4',
    sharesOutstanding: '2억 2,800만',
    grossMargin: '23.8%',
    operatingMargin: '-4.7%',
    epsTtm: '$0.56',
    epsNextYear: '$0.92',
    epsQoq: '+12.3%',
    ruleOf40: '3.4%',
    earningsDate: '2026.05.08',
  },
  LRCX: {
    marketCap: '53조 5,742억',
    sales: '13조 6,549억',
    salesQoq: '+7.5%',
    salesYoyTtm: '+18.0%',
    salesPastYears: '+8.8% / +15.7%',
    currentRatio: '2.44',
    priceToFreeCashFlow: '24.2',
    priceToSales: '4.81',
    per: '81.71',
    pbr: '14.37',
    roe: '19.20%',
    peg: '1.9',
    sharesOutstanding: '12억 8,000만',
    grossMargin: '47.5%',
    operatingMargin: '29.6%',
    epsTtm: '$1.16',
    epsNextYear: '$1.42',
    epsQoq: '+20.6%',
    ruleOf40: '47.6%',
    earningsDate: '2026.07.29',
  },
  SNDK: {
    marketCap: '15조 8,925억',
    sales: '15조 2,726억',
    salesQoq: '+5.2%',
    salesYoyTtm: '+14.6%',
    salesPastYears: '+2.3% / +7.2%',
    currentRatio: '1.62',
    priceToFreeCashFlow: '31.4',
    priceToSales: '1.04',
    per: '55.1',
    pbr: '35.64',
    roe: '75.30%',
    peg: '2.4',
    sharesOutstanding: '3억 4,200만',
    grossMargin: '38.1%',
    operatingMargin: '18.3%',
    epsTtm: '$1.04',
    epsNextYear: '$1.68',
    epsQoq: '+39.1%',
    ruleOf40: '32.9%',
    earningsDate: '2026.08.14',
  },
  MSFT: {
    marketCap: '3,840조 1,000억',
    sales: '328조 8,000억',
    salesQoq: '+6.4%',
    salesYoyTtm: '+15.2%',
    salesPastYears: '+14.0% / +16.8%',
    currentRatio: '1.35',
    priceToFreeCashFlow: '45.2',
    priceToSales: '11.68',
    per: '36.4',
    pbr: '11.90',
    roe: '33.1%',
    peg: '2.3',
    sharesOutstanding: '74억 3,000만',
    grossMargin: '69.8%',
    operatingMargin: '44.7%',
    epsTtm: '$13.32',
    epsNextYear: '$15.10',
    epsQoq: '+11.2%',
    ruleOf40: '59.9%',
    earningsDate: '2026.07.28',
  },
}

function normalizeQuery(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, '')
}

function displayStockName(name: string) {
  let value = name.trim()
  if (!value) return '-'

  for (const marker of [' American Depositary', ' Depositary Shares', ' ADS']) {
    if (value.includes(marker)) {
      value = value.split(marker, 1)[0].trim()
    }
  }

  for (const suffix of [', Ltd.', ' Ltd.', ', Inc.', ' Inc.', ', Corp.', ' Corp.', ', Co.', ' Co.']) {
    const index = value.indexOf(suffix)
    if (index !== -1) {
      value = value.slice(0, index + suffix.length).trim()
      break
    }
  }

  return value
}

function withDisplayStockName(stock: Stock): Stock {
  return {
    ...stock,
    name: displayStockName(stock.name),
  }
}

function stockSearchRank(stock: Stock, normalizedQuery: string) {
  const ticker = normalizeQuery(stock.ticker)
  const name = normalizeQuery(stock.name)

  if (ticker === normalizedQuery) return 0
  if (ticker.startsWith(normalizedQuery)) return 1
  if (ticker.includes(normalizedQuery)) return 2
  if (name.startsWith(normalizedQuery)) return 3
  if (name.includes(normalizedQuery)) return 4
  return 99
}

const SCROLL_GESTURE_GAP_MS = 80
let lastWheelTimestamp = 0
let lastWheelAbsDeltaY = 0
let releaseScrollToPage = false

function releaseVerticalScrollAtEdge(event: globalThis.WheelEvent) {
  const container = event.currentTarget as HTMLElement | null
  if (!container) return
  if (Math.abs(event.deltaY) < Math.abs(event.deltaX) || container.scrollHeight <= container.clientHeight) return

  const now = event.timeStamp
  const absDeltaY = Math.abs(event.deltaY)
  const gap = now - lastWheelTimestamp
  lastWheelTimestamp = now

  const isAtTop = container.scrollTop <= 0
  const isAtBottom = Math.ceil(container.scrollTop + container.clientHeight) >= container.scrollHeight
  const atEdgeInScrollDirection = (event.deltaY < 0 && isAtTop) || (event.deltaY > 0 && isAtBottom)

  if (!atEdgeInScrollDirection) {
    // The table still has room: let it scroll, and require a fresh push to move the page later.
    releaseScrollToPage = false
    lastWheelAbsDeltaY = absDeltaY
    return
  }

  // Pinned at the edge. Inertia from the gesture that scrolled the table here keeps firing with a
  // steadily decaying deltaY, so we swallow it (the rows stay readable). The page only takes over
  // on a clearly intentional new push, detected either by a brief pause or by deltaY jumping back
  // up above the decaying momentum tail. This makes "scroll to the end, then scroll again" reliable
  // without waiting for inertia to fully die out.
  const isFreshPush = gap > SCROLL_GESTURE_GAP_MS || absDeltaY > lastWheelAbsDeltaY * 1.5 + 4
  lastWheelAbsDeltaY = absDeltaY
  if (isFreshPush) releaseScrollToPage = true

  event.preventDefault()
  if (!releaseScrollToPage) return

  const activeElement = document.activeElement
  if (activeElement instanceof HTMLElement && container.contains(activeElement)) {
    activeElement.blur()
  }
  window.scrollBy({ top: event.deltaY, behavior: 'auto' })
}

// React의 onWheel은 루트에 passive로 등록돼 내부 preventDefault가 무시되고 경고를 쏟는다.
// 비-passive 네이티브 wheel 리스너를 직접 붙여 가장자리 스크롤 제어를 정상 동작시킨다.
function useEdgeScrollWheelRef(externalRef?: RefObject<HTMLDivElement | null>) {
  const cleanupRef = useRef<(() => void) | null>(null)
  return useCallback((node: HTMLDivElement | null) => {
    cleanupRef.current?.()
    cleanupRef.current = null
    if (externalRef) externalRef.current = node
    if (node) {
      node.addEventListener('wheel', releaseVerticalScrollAtEdge, { passive: false })
      cleanupRef.current = () => node.removeEventListener('wheel', releaseVerticalScrollAtEdge)
    }
  }, [externalRef])
}

function statusClass(value: Valuation | Opinion | TradeStatus) {
  if (value === '저평가' || value === '매수' || value === '익절') return 'positive'
  if (value === '고평가' || value === '매도' || value === '손절' || value === '실패 익절') return 'negative'
  return 'neutral'
}

function valuationBadgeClass(value: Valuation) {
  if (value === '저평가') return 'valuation-low'
  if (value === '고평가') return 'valuation-high'
  if (value === '판단 불가') return 'valuation-unavailable'
  return 'valuation-normal'
}

function returnClass(value: number) {
  if (value > 0) return 'return-positive'
  if (value < 0) return 'return-negative'
  return ''
}

function tradeReturnClass(trade: TradeLog, value: number) {
  if (trade.status === '손절' || trade.status === '실패 익절') return 'return-negative'
  return returnClass(value)
}

function strategyCode(strategy: string) {
  return strategy.slice(0, 1)
}

function strategyInfo(strategy: string) {
  const descriptions: Record<string, string> = {
    A: '상승 흐름 중 잠깐 쉬었다가 다시 힘이 붙는 구간입니다. 강한 종목이 다시 오르려는 신호를 봅니다.',
    B: '장기 평균선 아래에서 많이 빠진 구간입니다. 반등 가능성은 보지만, 실패하면 손절 기준이 중요합니다.',
    C: '한동안 조용하던 가격이 거래량과 함께 움직이기 시작한 구간입니다. 돌파 후 계속 이어지는지 봅니다.',
    D: '장기 평균선 위에서 상승 힘이 더 강해지는 구간입니다. 이미 강한 종목을 따라가는 전략입니다.',
    E: '상승 흐름은 유지되지만 가격이 잠시 눌린 구간입니다. 다시 들어갈 만한 저점 후보로 봅니다.',
    F: '상승 흐름 안에서 가격이 아래쪽까지 과하게 밀린 구간입니다. 반등을 노리지만 흔들림이 클 수 있습니다.',
    G: '급락 후 회복장에서 20일선까지 눌렸다가 다시 회복하는 구간입니다. 회복장 눌림목만 선별합니다.',
  }
  return descriptions[strategyCode(strategy)] ?? '전략 요약 정보가 준비 중입니다. 세부 수식보다 신호의 성격만 제공합니다.'
}

function tradeResultLabel(status: TradeStatus) {
  if (status === '익절') return '성공(익절)'
  if (status === '손절') return '실패(손절)'
  if (status === '실패 익절') return '실패(익절)'
  return '보유중'
}

function tradeCriteriaInfo(strategy: string) {
  const code = strategyCode(strategy)

  if (['A', 'B', 'C'].includes(code)) {
    return `${code} 전략 기준: 성공은 매수가 대비 +20% 도달 시 즉시 익절입니다. -30%에 닿으면 손절 실패이고, 매수 후 15거래일 종가 수익률이 +8% 미만이면 반등 미달로 청산합니다. 60거래일 경과 후 수익 중이거나 120거래일 최대 보유 기간에 걸려 청산되면 수익이어도 목표 미달 실패(익절)로 볼 수 있습니다.`
  }

  if (code === 'D') {
    return 'D 전략 기준: 성공은 매수가 대비 +12% 도달 시 즉시 익절입니다. -25%에 닿으면 손절 실패이고, 매수 후 15거래일 종가 수익률이 +8% 미만이면 반등 미달로 청산합니다. 30거래일 최대 보유 기간 안에 목표를 채우지 못해 청산되면 수익이어도 목표 미달 실패(익절)로 볼 수 있습니다.'
  }

  if (code === 'G') {
    return 'G 전략 기준: 성공은 매수가 대비 +12% 도달 시 즉시 익절입니다. -10%에 닿으면 손절 실패이고, 매수 후 15거래일 종가 수익률이 +8% 미만이면 반등 미달로 청산합니다. 40거래일 최대 보유 기간 안에 목표를 채우지 못해 청산되면 수익이어도 목표 미달 실패(익절)로 볼 수 있습니다.'
  }

  if (['E', 'F'].includes(code)) {
    return `${code} 전략 기준: 성공은 +20% 도달 후 MACD 둔화 신호가 나오거나 목표 도달 후 5거래일 대기 만료 시 청산입니다. -30%에 닿으면 손절 실패이고, 매수 후 15거래일 종가 수익률이 +8% 미만이면 반등 미달로 청산합니다. 60거래일 수익 중 청산이나 120거래일 최대 보유 기간 청산은 조건 충족 여부에 따라 수익이어도 실패(익절)로 볼 수 있습니다.`
  }

  return '전략별 성공/실패 기준 정보가 준비 중입니다.'
}

function tradeResultInfo(trade: TradeLog) {
  if (trade.status !== '보유 중') return tradeCriteriaInfo(trade.strategy)
  return '아직 매도 신호가 없어 성공/실패를 확정하지 않은 보유 중 거래입니다. 보유 여부는 투자금 산정과 별개로 구분해서 봅니다.'
}

function isSystemHolding(ticker: string, targetTrades: TradeLog[]) {
  return targetTrades.some((trade) => trade.ticker === ticker && trade.status === '보유 중')
}

function isEtfStock(stock: Stock) {
  const normalizedText = `${stock.name} ${stock.category ?? ''} ${stock.industry ?? ''}`.toUpperCase()
  return stock.fairPriceReason === 'etf' || /\bETF\b/.test(normalizedText)
}

function isFairPriceUnavailable(stock: Stock) {
  return isEtfStock(stock) || stock.fairPriceReason === 'loss_making' || stock.fairPrice === FAIR_PRICE_UNAVAILABLE_LABEL
}

function displayFairPriceText(stock: Stock) {
  if (isEtfStock(stock)) return ETF_FAIR_PRICE_UNAVAILABLE_LABEL
  return isFairPriceUnavailable(stock) ? FAIR_PRICE_UNAVAILABLE_LABEL : stock.fairPrice
}

function displayCurrentPriceText(stock: Stock) {
  return stock.currentPrice
}

function displayStockOpinion(stock: Stock): Opinion {
  return stock.opinion
}

function displayValueAnalysisOpinion(stock: Stock): Opinion {
  return isFairPriceUnavailable(stock) ? '-' : stock.opinion
}

function displayStockValuation(stock: Stock): Valuation {
  if (isFairPriceUnavailable(stock)) return '판단 불가'
  return valuationFromPriceRange(stock.currentPrice, stock.fairPrice) ?? stock.valuation
}

function compareValues(a: number | string, b: number | string) {
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), ['ko', 'en'])
}

function valuationRank(stock: Stock) {
  const value = displayStockValuation(stock)
  if (value === '저평가') return 0
  if (value === '보통') return 1
  if (value === '고평가') return 2
  return 3
}

function opinionRank(stock: Stock) {
  const value = displayStockOpinion(stock)
  if (value === '매수') return 0
  if (value === '관망') return 1
  if (value === '매도') return 2
  return 3
}

function valuationHighRank(stock: Stock) {
  const value = displayStockValuation(stock)
  if (value === '고평가') return 0
  if (value === '보통') return 1
  if (value === '저평가') return 2
  return 3
}

function opinionSellRank(stock: Stock) {
  const value = displayStockOpinion(stock)
  if (value === '매도') return 0
  if (value === '관망') return 1
  if (value === '매수') return 2
  return 3
}

function compareByWatchlistSortKey(key: WatchlistSortKey, a: Stock, b: Stock, trades: TradeLog[]) {
  if (key === 'registered') return 0
  if (key === 'market_kr_first') return compareValues(a.market === 'KR' ? 0 : 1, b.market === 'KR' ? 0 : 1)
  if (key === 'market_us_first') return compareValues(a.market === 'US' ? 0 : 1, b.market === 'US' ? 0 : 1)
  if (key === 'holding_first') return compareValues(isSystemHolding(a.ticker, trades) ? 0 : 1, isSystemHolding(b.ticker, trades) ? 0 : 1)
  if (key === 'not_holding_first') return compareValues(isSystemHolding(a.ticker, trades) ? 1 : 0, isSystemHolding(b.ticker, trades) ? 1 : 0)
  if (key === 'valuation_low_first') return compareValues(valuationRank(a), valuationRank(b))
  if (key === 'valuation_high_first') return compareValues(valuationHighRank(a), valuationHighRank(b))
  if (key === 'opinion_buy_first') return compareValues(opinionRank(a), opinionRank(b))
  if (key === 'opinion_sell_first') return compareValues(opinionSellRank(a), opinionSellRank(b))
  if (key === 'name_asc') return compareValues(a.name, b.name)
  if (key === 'name_desc') return compareValues(b.name, a.name)
  return 0
}

function sortWatchlistStocks(stocks: Stock[], settings: WatchlistSortSettings, tickers: string[], trades: TradeLog[]) {
  const registeredOrder = new Map(tickers.map((ticker, index) => [ticker, index]))
  return stocks.slice().sort((a, b) => {
    const primary = compareByWatchlistSortKey(settings.primary, a, b, trades)
    if (primary !== 0) return primary
    const secondary = compareByWatchlistSortKey(settings.secondary, a, b, trades)
    if (secondary !== 0) return secondary
    return (registeredOrder.get(a.ticker) ?? 0) - (registeredOrder.get(b.ticker) ?? 0)
  })
}

function stockName(ticker: string) {
  return searchUniverse.find((stock) => stock.ticker === ticker)?.name ?? ticker
}

function stockMarket(ticker: string) {
  return searchUniverse.find((stock) => stock.ticker === ticker)?.market ?? 'US'
}

function tradeName(trade: TradeLog) {
  return trade.name || stockName(trade.ticker)
}

function tradeMarket(trade: TradeLog) {
  return trade.market || stockMarket(trade.ticker)
}

function formatTradePrice(trade: TradeLog, value: number | null, fallback: string) {
  if (value === null) return fallback
  return tradeMarket(trade) === 'KR'
    ? `₩${Math.round(value).toLocaleString('ko-KR')}`
    : `$${value.toFixed(2)}`
}

function marketFlag(market: Market) {
  return market === 'KR' ? '🇰🇷' : '🇺🇸'
}

// 종목 불러오기 목록 정렬용: 한국 종목 먼저, 그 다음 미국 종목.
function marketSortRank(market: Market) {
  return market === 'KR' ? 0 : 1
}

function StockNameCell({
  name,
  market,
  onTooltipOpen,
  onTooltipClose,
}: {
  name: string
  market: Market
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  const textRef = useRef<HTMLSpanElement>(null)
  const [isTruncated, setIsTruncated] = useState(false)

  useLayoutEffect(() => {
    const textElement = textRef.current
    if (!textElement) return undefined

    let frameId = 0
    const updateTruncation = () => {
      window.cancelAnimationFrame(frameId)
      frameId = window.requestAnimationFrame(() => {
        setIsTruncated(textElement.scrollWidth > textElement.clientWidth + 1)
      })
    }

    updateTruncation()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updateTruncation)
    observer?.observe(textElement)
    if (textElement.parentElement) observer?.observe(textElement.parentElement)
    window.addEventListener('resize', updateTruncation)

    return () => {
      window.cancelAnimationFrame(frameId)
      observer?.disconnect()
      window.removeEventListener('resize', updateTruncation)
    }
  }, [name])

  const openTooltip = (element: HTMLElement) => {
    const textElement = textRef.current
    if (!textElement || textElement.scrollWidth <= textElement.clientWidth + 1) return

    const rect = element.getBoundingClientRect()
    const edgePadding = window.innerWidth <= 760 ? 20 : 32
    const maxTooltipWidth = window.innerWidth - edgePadding * 2
    const tooltipWidth = Math.min(textElement.scrollWidth + 26, maxTooltipWidth)
    const tooltipHalfWidth = tooltipWidth / 2
    const minX = tooltipHalfWidth + edgePadding
    const maxX = window.innerWidth - tooltipHalfWidth - edgePadding
    const centeredX = rect.left + rect.width / 2

    onTooltipOpen({
      text: name,
      x: Math.min(Math.max(centeredX, minX), maxX),
      y: rect.top - 8,
      className: 'stock-name-floating-tooltip',
    })
  }

  return (
    <div className="name-cell analysis-stock-name-cell">
      <span className="market-flag" aria-hidden="true">{marketFlag(market)}</span>
      {isTruncated ? (
        <span
          aria-label={`${name} 전체 종목명 보기`}
          className="stock-name-tooltip-trigger is-truncated"
          role="button"
          tabIndex={0}
          title={name}
          onBlur={onTooltipClose}
          onClick={(event) => {
            event.stopPropagation()
            openTooltip(event.currentTarget)
          }}
          onFocus={(event) => openTooltip(event.currentTarget)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return
            event.preventDefault()
            event.stopPropagation()
            openTooltip(event.currentTarget)
          }}
          onMouseEnter={(event) => openTooltip(event.currentTarget)}
          onMouseLeave={onTooltipClose}
        >
          <span className="stock-name-text" ref={textRef}>{name}</span>
        </span>
      ) : (
        <span className="stock-name-tooltip-trigger">
          <span className="stock-name-text" ref={textRef}>{name}</span>
        </span>
      )}
    </div>
  )
}

function AnalysisStockName({
  stock,
  onTooltipOpen,
  onTooltipClose,
}: {
  stock: Stock
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  return (
    <StockNameCell
      market={stock.market}
      name={stock.name}
      onTooltipClose={onTooltipClose}
      onTooltipOpen={onTooltipOpen}
    />
  )
}

function StrategyTag({
  strategy,
  onTooltipOpen,
  onTooltipClose,
}: {
  strategy: string
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  const openTooltip = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect()
    const minX = 280
    const maxX = window.innerWidth - 280
    const centeredX = rect.left + rect.width / 2

    onTooltipOpen({
      text: strategyInfo(strategy),
      x: Math.min(Math.max(centeredX, minX), maxX),
      y: rect.top - 8,
    })
  }

  return (
    <span
      className="strategy-item"
      onBlur={onTooltipClose}
      onClick={(event) => {
        event.stopPropagation()
        openTooltip(event.currentTarget)
      }}
      onFocus={(event) => openTooltip(event.currentTarget)}
      onMouseEnter={(event) => openTooltip(event.currentTarget)}
      onMouseLeave={onTooltipClose}
      tabIndex={0}
    >
      <span className={`strategy-pill strategy-${strategyCode(strategy).toLowerCase()}`}>
        {strategy}
      </span>
    </span>
  )
}

function ResultBadge({
  trade,
  onTooltipOpen,
  onTooltipClose,
}: {
  trade: TradeLog
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  const openTooltip = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect()
    const minX = 280
    const maxX = window.innerWidth - 280
    const centeredX = rect.left + rect.width / 2

    onTooltipOpen({
      text: tradeResultInfo(trade),
      x: Math.min(Math.max(centeredX, minX), maxX),
      y: rect.top - 8,
    })
  }

  return (
    <span
      className={`status-badge result-badge ${statusClass(trade.status)}`}
      onBlur={onTooltipClose}
      onClick={(event) => {
        event.stopPropagation()
        openTooltip(event.currentTarget)
      }}
      onFocus={(event) => openTooltip(event.currentTarget)}
      onMouseEnter={(event) => openTooltip(event.currentTarget)}
      onMouseLeave={onTooltipClose}
      tabIndex={0}
    >
      {tradeResultLabel(trade.status)}
    </span>
  )
}

function formatWinRate(label: string, targetTrades: TradeLog[]) {
  const finished = targetTrades.filter((trade) => trade.status !== '보유 중')
  if (finished.length === 0) return `${label} -`
  const wins = finished.filter((trade) => trade.status === '익절').length
  return `${label} ${Math.round((wins / finished.length) * 100)}%`
}

function daysFromFirstTrade(targetTrades: TradeLog[]) {
  if (targetTrades.length === 0) return 0
  const timestamps = targetTrades.map((trade) => new Date(trade.buyDate.replaceAll('.', '-')).getTime())
  const first = Math.min(...timestamps)
  const latest = Math.max(...timestamps)
  return Math.max(1, Math.ceil((latest - first) / 86_400_000) + 1)
}

function parseTradeDate(value: string) {
  return new Date(value.replaceAll('.', '-')).getTime()
}

function todayTradeDateString() {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}.${month}.${day}`
}

function tradeDateInputValue(value: string) {
  return value.replaceAll('.', '-')
}

function normalizeTradeDateInput(value: string) {
  return value.trim().replaceAll('-', '.')
}

function holdingPeriodDays(trade: TradeLog) {
  const endTime = trade.status === '보유 중' ? Date.now() : parseTradeDate(trade.sellDate)
  return Math.max(0, Math.ceil((endTime - parseTradeDate(trade.buyDate)) / 86_400_000))
}

function parsePriceValue(value: string) {
  // 원격 JSON 행은 타입상 string이지만 실제로는 값이 비어 올 수 있어 방어한다.
  if (typeof value !== 'string') return null
  const parsed = Number(value.replace(/[^0-9.-]/g, ''))
  return Number.isFinite(parsed) ? parsed : null
}

function parseAmountValue(value: string) {
  const parsed = Number(value.replace(/[^0-9.-]/g, ''))
  return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : null
}

function amountInputValue(value: string) {
  const digits = value.replace(/[^0-9]/g, '')
  if (!digits) return ''
  return `₩${Number(digits).toLocaleString('ko-KR')}`
}

function amountInputDigits(value: string) {
  return value.replace(/[^0-9]/g, '')
}

function amountDraftValue(value: string) {
  return amountInputDigits(value) || '0'
}

function currentReturnPct(trade: TradeLog, stocks: Stock[] = searchUniverse) {
  const buyPrice = parsePriceValue(trade.buyPrice)
  const currentPrice = parsePriceValue(trade.currentPrice || stocks.find((stock) => stock.ticker === trade.ticker)?.currentPrice || '')

  if (!buyPrice || currentPrice === null) return null
  return ((currentPrice - buyPrice) / buyPrice) * 100
}

function tradeCurrentPriceText(trade: TradeLog, stocks: Stock[] = searchUniverse) {
  return trade.currentPrice || stocks.find((stock) => stock.ticker === trade.ticker)?.currentPrice || '-'
}

function displayedTradeReturnPct(trade: TradeLog, stocks: Stock[] = searchUniverse) {
  return trade.status === '보유 중' ? currentReturnPct(trade, stocks) : trade.returnPct
}

function tradeInvestmentAmount(trade: TradeLog, amountByTradeKey?: Map<string, number>) {
  return amountByTradeKey?.get(tradeKey(trade)) ?? 0
}

function tradeProfitAmount(trade: TradeLog, stocks: Stock[] = searchUniverse, amountByTradeKey?: Map<string, number>) {
  const returnPct = displayedTradeReturnPct(trade, stocks)
  if (returnPct === null) return null
  return Math.round(tradeInvestmentAmount(trade, amountByTradeKey) * returnPct / 100)
}

function formatKrwAmount(value: number) {
  const sign = value < 0 ? '-' : ''
  return `${sign}₩${Math.abs(Math.round(value)).toLocaleString('ko-KR')}`
}

function tradeProfitClass(value: number | null) {
  if (value === null) return ''
  if (value > 0) return 'return-positive'
  if (value < 0) return 'return-negative'
  return ''
}

function tradeReturnPriceText(trade: TradeLog, stocks: Stock[] = searchUniverse) {
  return trade.status === '보유 중' ? tradeCurrentPriceText(trade, stocks) : trade.sellPrice || '-'
}

function formatPriceWithReturn(price: string, returnPct: number | null) {
  if (returnPct === null) return `${price} (-)`
  return `${price} (${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(1)}%)`
}

function valuationFromPriceRange(currentPrice: string, fairPrice: string): Valuation | null {
  const current = parsePriceValue(currentPrice)
  if (typeof fairPrice !== 'string') return null
  const [lowText, highText] = fairPrice.split('~').map((value) => value.trim())
  const low = parsePriceValue(lowText ?? '')
  const high = parsePriceValue(highText ?? '')

  if (current === null || low === null || high === null) return null
  if (current < low) return '저평가'
  if (current > high) return '고평가'
  return '보통'
}

function tradeKey(trade: TradeLog) {
  return trade.slotId || `${trade.investmentType ?? 'shared'}-${trade.ticker}-${trade.buyDate}-${strategyCode(trade.strategy)}-${trade.buyPrice}`
}

function tradeDateObject(value: string) {
  return new Date(value.replaceAll('.', '-'))
}

function sameOrBeforeDate(a: Date, b: Date) {
  return a.getTime() <= b.getTime()
}

function nextDay(date: Date) {
  const next = new Date(date)
  next.setDate(next.getDate() + 1)
  return next
}

function scheduledContributionBetween(startExclusive: Date, endInclusive: Date, settings: ContributionSettings) {
  let total = 0
  for (let day = nextDay(startExclusive); sameOrBeforeDate(day, endInclusive); day = nextDay(day)) {
    if (settings.frequency === 'weekly' && day.getDay() === settings.dayOfWeek) {
      total += settings.amount
    }
    if (settings.frequency === 'monthly' && day.getDate() === settings.dayOfMonth) {
      total += settings.amount
    }
  }
  return total
}

function contributionDayMessage(value: string) {
  if (value.trim() === '') return '입금일을 입력해 주세요.'
  const day = Number(value)
  if (!Number.isInteger(day) || day < 1 || day > 31) {
    return '입금일은 1일부터 31일 사이의 숫자로 입력해 주세요.'
  }
  if (day === 29) return '2월 29일은 윤년에만 입금됩니다.'
  if (day === 30) return '30일이 없는 달에는 해당 월 입금이 건너뜁니다.'
  if (day === 31) return '31일이 없는 달에는 해당 월 입금이 건너뜁니다.'
  return ''
}

function allocationWeightsForProfile(investmentType: InvestmentType, settings: ContributionSettings) {
  const allocation = settings.allocationByInvestmentType[investmentType]
  return allocation.slotPercents.slice(0, allocation.slotCount).map((percent) => percent / 100)
}

function contributionSettingsDraftFrom(settings: ContributionSettings): ContributionSettingsDraft {
  return {
    initialCapital: String(settings.initialCapital),
    frequency: settings.frequency,
    amount: String(settings.amount),
    dayOfWeek: String(settings.dayOfWeek),
    dayOfMonth: String(settings.dayOfMonth),
    allocationByInvestmentType: {
      swing: {
        slotCount: String(settings.allocationByInvestmentType.swing.slotCount),
        slotPercents: settings.allocationByInvestmentType.swing.slotPercents.map(String),
      },
      long_term: {
        slotCount: String(settings.allocationByInvestmentType.long_term.slotCount),
        slotPercents: settings.allocationByInvestmentType.long_term.slotPercents.map(String),
      },
    },
  }
}

function allocationSummaryText(settings: AllocationSettings) {
  const percents = settings.slotPercents.slice(0, settings.slotCount)
  const firstPercent = percents[0] ?? 0
  const isSamePercent = percents.every((percent) => percent === firstPercent)

  if (isSamePercent) {
    return `제한 슬롯 ${settings.slotCount}개 · 각 슬롯당 ${firstPercent}%가 기본값`
  }

  return `제한 슬롯 ${settings.slotCount}개 · 슬롯 비중 ${percents.join('% / ')}%`
}

function buildPortfolioSummary(
  trades: TradeLog[],
  stocks: Stock[],
  buyPriorityForTrade: (trade: TradeLog) => TradeBuyPriority,
  settings: ContributionSettings,
  investmentType: InvestmentType,
  initialCash = settings.initialCapital,
): PortfolioSummary {
  let runningCash = initialCash
  const slotWeights = allocationWeightsForProfile(investmentType, settings)
  const occupiedSlots = new Map<string, number>()
  const amountByTradeKey = new Map<string, number>()
  let openInvestmentAmount = 0
  let cumulativeInvestmentAmount = 0
  let positionValue = 0
  let profitAmount = 0
  let realizedProfitAmount = 0
  let unrealizedProfitAmount = 0
  const eventsByDate = new Map<string, { buys: TradeLog[]; sells: TradeLog[] }>()
  const addEvent = (date: string, field: 'buys' | 'sells', trade: TradeLog) => {
    const bucket = eventsByDate.get(date) ?? { buys: [], sells: [] }
    bucket[field].push(trade)
    eventsByDate.set(date, bucket)
  }

  for (const trade of trades) {
    addEvent(trade.buyDate, 'buys', trade)
    if (trade.status !== '보유 중' && trade.sellDate !== '-') {
      addEvent(trade.sellDate, 'sells', trade)
    }
  }

  const orderedDates = [...eventsByDate.keys()].sort((a, b) => parseTradeDate(a) - parseTradeDate(b))
  let contributionCursor = orderedDates[0] ? tradeDateObject(orderedDates[0]) : new Date()

  for (const date of orderedDates) {
    const tradeDate = tradeDateObject(date)
    runningCash += scheduledContributionBetween(contributionCursor, tradeDate, settings)
    contributionCursor = tradeDate
    const events = eventsByDate.get(date)
    if (!events) continue

    for (const trade of events.sells) {
      const key = tradeKey(trade)
      const amount = amountByTradeKey.get(key) ?? 0
      const tradeProfit = Math.round(amount * (displayedTradeReturnPct(trade, stocks) ?? 0) / 100)
      runningCash += amount + tradeProfit
      occupiedSlots.delete(key)
    }

    const cashBeforeBuys = runningCash
    const orderedBuys = [...events.buys].sort((a, b) => {
      const aPriority = buyPriorityForTrade(a)
      const bPriority = buyPriorityForTrade(b)
      return aPriority.megaRank - bPriority.megaRank
        || aPriority.trendRank - bPriority.trendRank
        || a.ticker.localeCompare(b.ticker)
    })

    for (const trade of orderedBuys) {
      const key = tradeKey(trade)
      const fixedAmount = typeof trade.investmentAmount === 'number' && Number.isFinite(trade.investmentAmount)
        ? Math.max(0, Math.round(trade.investmentAmount))
        : null
      const slotIndex = fixedAmount === 0 ? -1 : slotWeights.findIndex((_, index) => ![...occupiedSlots.values()].includes(index))
      const amount = fixedAmount !== null
        ? fixedAmount
        : slotIndex >= 0 ? Math.min(runningCash, Math.max(0, Math.floor(cashBeforeBuys * slotWeights[slotIndex]))) : 0
      amountByTradeKey.set(key, amount)
      if (slotIndex >= 0 && amount > 0) occupiedSlots.set(key, slotIndex)
      cumulativeInvestmentAmount += amount
      runningCash -= amount
    }
  }

  for (const trade of trades) {
    const amount = amountByTradeKey.get(tradeKey(trade)) ?? 0
    const tradeProfit = Math.round(amount * (displayedTradeReturnPct(trade, stocks) ?? 0) / 100)
    profitAmount += tradeProfit
    if (trade.status === '보유 중') {
      unrealizedProfitAmount += tradeProfit
      openInvestmentAmount += amount
      positionValue += amount + tradeProfit
    } else {
      realizedProfitAmount += tradeProfit
    }
  }

  runningCash += scheduledContributionBetween(contributionCursor, new Date(), settings)
  const projectedCash = Math.round(runningCash)
  const cash = projectedCash
  const investedAmount = openInvestmentAmount
  const totalCapital = openInvestmentAmount
  const totalAsset = cash + positionValue
  const profitRate = cumulativeInvestmentAmount > 0 ? profitAmount / cumulativeInvestmentAmount * 100 : 0

  return {
    cash,
    projectedCash,
    totalCapital,
    investedAmount,
    openInvestmentAmount,
    cumulativeInvestmentAmount,
    positionValue,
    totalAsset,
    profitAmount,
    realizedProfitAmount,
    unrealizedProfitAmount,
    profitRate,
    amountByTradeKey,
  }
}

function displayIndustryLabel(industry?: string) {
  const value = industry?.trim()
  if (!value || value === '-') return '-'

  const items = value
    .replaceAll('，', ',')
    .split(',')
    .map((item) => item.trim()
      .replaceAll(' 등 제조 및 판매', '')
      .replaceAll(' 등 제조/판매', '')
      .replaceAll(' 제조 및 판매', '')
      .replaceAll(' 제조/판매', '')
      .replaceAll(' 개발/운영 서비스 등', '')
      .replaceAll(' 개발·운영 서비스 등', '')
      .replaceAll(' 서비스 등', '')
      .replaceAll(' 사업 등', '')
      .replace(/ 등$/, '')
      .trim())
    .filter(Boolean)

  return Array.from(new Set(items)).slice(0, 5).join(', ') || value
}

function primaryIndustryLabel(industry?: string) {
  return displayIndustryLabel(industry).split(/[,|/]/)[0]?.trim() || '-'
}

function industryTrendKeywords(industry?: string) {
  return (industry ?? '')
    .split(/[,·|/()\s]+/)
    .map(normalizeTrendText)
    .filter((keyword) => keyword.length > 1)
}

function normalizeTrendText(value: string) {
  return value
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/[·,|/()]/g, '')
}

function isSameTrendWeek(tradeDate: string, trendDate: string) {
  const tradeTime = parseTradeDate(tradeDate)
  const trendTime = parseTradeDate(trendDate)
  const diffDays = (tradeTime - trendTime) / 86_400_000

  return diffDays >= 0 && diffDays < 7
}

const gnbMenus = ['HOME', '가치 분석', '기술 분석', '시장 주요 이벤트', '시장 트렌드']
const adminGnbMenus = [...gnbMenus, '운영 로그', '게시판']
const boardCategories: BoardCategory[] = ['칭찬', '버그', '건의', '기타']
const boardFilters: BoardFilter[] = ['전체', ...boardCategories]
const watchlistSortOptions: Array<{ value: WatchlistSortKey; label: string; description: string }> = [
  { value: 'registered', label: '등록순', description: '내가 추가한 순서를 그대로 유지' },
  { value: 'market_kr_first', label: '한국 종목 먼저', description: '국내 종목을 위로 모아서 보기' },
  { value: 'market_us_first', label: '미국 종목 먼저', description: '미국 종목을 위로 모아서 보기' },
  { value: 'holding_first', label: '보유 중 먼저', description: '현재 시스템이 보유 중인 종목 우선' },
  { value: 'not_holding_first', label: '미보유 먼저', description: '새로 볼 후보 종목부터 확인' },
  { value: 'valuation_low_first', label: '저평가 먼저', description: '가치분석 매력이 큰 종목 우선' },
  { value: 'valuation_high_first', label: '고평가 먼저', description: '비싼 종목이나 리스크 먼저 확인' },
  { value: 'opinion_buy_first', label: '매수 의견 먼저', description: '기술분석 매수 신호 우선' },
  { value: 'opinion_sell_first', label: '매도 의견 먼저', description: '위험 신호가 있는 종목 우선' },
  { value: 'name_asc', label: '종목명 가나다/A-Z', description: '종목명 기준 오름차순' },
  { value: 'name_desc', label: '종목명 역순', description: '종목명 기준 내림차순' },
]
const notificationOptions: Array<{ key: NotificationPreferenceKey; title: string; description: string }> = [
  { key: 'opinionChangeEmail', title: '투자의견 변경', description: '관심종목의 매수/관망/매도 신호가 바뀔 때' },
  { key: 'nasdaqPeakEmail', title: '나스닥 고점 과열', description: 'QQQ 과열과 RSI 둔화가 동시에 감지될 때' },
  { key: 'regimeShiftEmail', title: '시장 국면 전환', description: '회복장↔비회복장이 바뀌어 매수 차단선·예외 전략이 달라질 때' },
  { key: 'bbPullbackEmail', title: 'BB 눌림 반등 후보', description: '관심종목이 BB 상단 돌파 후 얕은 눌림 반등 후보로 잡힐 때' },
  { key: 'weeklyTrendReport', title: '주간 트렌드 리포트', description: '시장 트렌드와 관심종목 흐름을 주 1회 정리' },
  { key: 'earningsDayBefore', title: '실적발표 전날', description: '관심종목 실적발표 전 리스크 점검' },
]
const adminNotificationOptions: Array<{ key: NotificationPreferenceKey; title: string; description: string }> = [
  { key: 'adminAutoUpdateFailureEmail', title: '자동 업데이트 실패', description: '관리자 전용: 같은 작업이 연속 3회 이상 실패할 때' },
]
const apiLogTabs: Array<{ key: ApiLogTrigger; label: string; description: string }> = [
  { key: 'value-analysis', label: '가치분석', description: '적정 주가 범위, 밸류에이션 캐시 생성' },
  { key: 'technical-analysis', label: '기술분석', description: '매수/관망/매도 신호와 전략 계산' },
  { key: 'market-trends', label: '시장 트렌드', description: '섹터·메가트렌드 랭킹 업데이트' },
]

const initialBoardPosts: BoardPost[] = []

const marketTrendRows: MarketTrendRow[] = [
  {
    date: '2026.03.25',
    ranks: [
      'AI 인프라 | 공장, 데이터센터, 데이터센터냉각',
      '반도체 | 메모리, Arm, SK Hynix',
      '인공지능 | OpenAI, Meta, Anthropic',
      '사이버 보안 | Databricks, Lake 보안 기술',
      '로봇 기술 | Zoox, Fauna Robotics, Agile Robots',
      '에너지 | 원자력, 전력 인프라',
      '금융 기술 | 결제 시스템, 스테이블코인, 파이낸스',
      '자동차 기술 | 자율 주행, 로보택시, 전기차',
      '소프트웨어 | 인공지능 소프트웨어, Gemini',
      '통신 기술 | 5G, 네트워크 인프라, 광통신',
    ],
    summary: '이번 주 전체 시장 분위기는 인공지능과 기술 인프라 주가 상승세를 보이며, 에너지와 금융 분야에서도 주요 뉴스가 발생했습니다.',
  },
  {
    date: '2026.03.29',
    ranks: [
      '에너지 | 원유, 가스, 석유',
      '기술 | AI, 반도체, 데이터센터',
      '국방 | 방위산업, 무기, 군사',
      '자동차 | 전기차, 자율주행, 수소차',
      '통신 | 5G, 네트워크, 위성통신',
      '의료 | 헬스케어, 바이오, 제약',
      '소비재 | 식품, 유통, 소비심리',
      '금융 | 디지털 결제, 모바일 뱅킹',
      '사이버 보안 | 네트워크 보안, 데이터 보호',
      '교육 기술 | 온라인 교육, 에듀테크',
    ],
    summary: '이번 주 전체 시장 분위기는 글로벌 경제 불안정과 정책 위험으로 인해 에너지 가격 상승과 기술 및 국방 산업의 부상이 두드러졌습니다.',
  },
  {
    date: '2026.04.05',
    ranks: [
      'AI 인프라 | 반도체, 트랙서버, 데이터센터냉각',
      '기술 | 핀테크, 마이크로소프트, 오픈AI',
      '반도체 산업 | 중국 반도체, 일본 반도체',
      '금융 기술 | 스테이블코인, 디지털 결제',
      '재생 에너지 | 태양광, 풍력, 에너지 저장',
      '로봇 | 산업용 로봇, 휴머노이드',
      '바이오 | 유전자 치료, 신약 개발',
      '전자 상거래 | 아마존, 쇼피파이',
      '산업 제조 | 스마트팩토리, 자동화',
      '소비재 | 소비 심리, 브랜드',
    ],
    summary: '이번 주 전체 시장 분위기는 기술과 금융 분야에서 새로운 플랫폼과 발전이 나타나며, 일부 투자자들의 관심이 집중되는 가운데 전반적인 변동성이 커지고 있습니다.',
  },
  {
    date: '2026.04.12',
    ranks: [
      'AI 인프라 | 광통신, 트랜시버, 데이터센터냉각',
      'AI 애플리케이션 | ChatGPT, Claude, AI 보안',
      '전기차 | EV 배터리, 충전 인프라, 자율 주행',
      '생명공학 | 제약, 의약품, 바이오',
      '클라우드 컴퓨팅 | AWS, Azure, Google Cloud',
      'AI 반도체 | GPU, 하이퍼스케일',
      '소프트웨어 | SaaS, 클라우드 소프트웨어',
      '금융 기술 | 디지털 결제, 모바일 뱅킹',
      '사이버 보안 | 데이터 보안, 네트워크 보안',
      '기술 | 온라인 교육, 에듀테크',
    ],
    summary: '이번 주 전체 시장 분위기는 지속적인 불확실성과 호조를 특징지었지만, 투자자들은 다양한 섹터의 테마에 관심을 두고 있습니다.',
  },
  {
    date: '2026.04.19',
    ranks: [
      'AI 인프라 | 광통신, 트랜시버, 데이터센터냉각',
      '반도체 | AI칩, Nvidia, AMD',
      '클라우드 컴퓨팅 | Microsoft, Oracle, GCP',
      '기술 주식 | 테슬라, 애플, 구글',
      '금융 기술 | 디지털 결제, 모바일 뱅킹',
      '기업 | 헬스케어, 바이오테크, 의료 기기',
      '전기차 | 배터리, 충전 인프라',
      '재생 에너지 | 태양광, 풍력, 에너지 저장',
      '방산 | 무인기, 국방 소프트웨어',
      '소프트웨어 | 데이터 플랫폼, AI 서비스',
    ],
    summary: '이번 주 전체 시장 분위기는 기술 주식과 금융 기술이 상승세가 두드러졌으며, 시장 플라우드 컴퓨팅이 주목받는 테마로 부상했습니다.',
  },
  {
    date: '2026.04.26',
    ranks: [
      'AI 인프라 | 데이터센터, 클라우드 컴퓨팅, 서버 반도체',
      'AI 기술주 | 애플, 마이크로소프트, 인텔',
      '전기차 | 테슬라, EV 배터리, 자율 주행',
      '친환경 에너지 | 태양광, 풍력, 그리드',
      '금융 보안 | 사이버 보안, 데이터 보호',
      '바이오 | 신약 개발, 유전자 치료',
      '교육 기술 | 온라인 교육, 에듀테크',
      '로봇 | 제조, 산업 자동화',
      '네트워크 | 5G, 네트워크 보안',
      '부동산 | 부동산 투자, 부동산 기술',
    ],
    summary: '이번 주 전체 시장 분위기는 기술과 인공지능 관련 주가가 상승하며 활황을 보이고 있습니다.',
  },
  {
    date: '2026.05.03',
    ranks: [
      'AI 인프라 | 데이터센터, 클라우드 컴퓨팅, AI 칩',
      'AI칩 | 오픈AI, 마이크로소프트, 인텔',
      '에너지 | 원유, 가스, 전력인프라',
      '자동차 | 전기자동차, 자율주행, 로봇택시',
      '헬스케어 | 의료 기술, 제약, 의료 서비스',
      '금융 | 은행, 결제, 자산 관리',
      '소비재 | 소매, 전자상거래, 소비자 기술',
      '통신 | 5G, 네트워크, 통신 장비',
      '산업 | 제조, 로봇, 산업 자동화',
      '기술 | 반도체, 클라우드, AI 서비스',
    ],
    summary: '이번 주 전체 시장 분위기는 기술 주와 에너지 섹터의 상승세가 두드러졌으며, 금융과 헬스케어 섹터도 안정적인 모습을 보였습니다.',
  },
]
void marketTrendRows

const eventMonths = ['1월', '2월', '3월', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월']

const marketEventGroups: MarketEventGroup[] = [
  {
    title: '금리 발표',
    tooltip: '미국 기준금리 방향을 확인하는 발표입니다. 금리 예상이 바뀌면 성장주, 달러, 지수가 함께 크게 움직일 수 있습니다.',
    entries: [
      { month: '1월', date: '2026. 1. 29', dday: '101', time: '4:00' },
      { month: '2월', date: '-', dday: '-', time: '-' },
      { month: '3월', date: '2026. 3. 19', dday: '45', time: '3:00' },
      { month: '4월', date: '2026. 4. 30', dday: '3', time: '3:00' },
      { month: '5월', date: '-', dday: '-', time: '-' },
      { month: '6월', date: '2026. 6. 18', dday: '-46', time: '3:00', highlighted: true },
      { month: '7월', date: '2026. 7. 30', dday: '-88', time: '3:00', highlighted: true },
      { month: '8월', date: '-', dday: '-', time: '-' },
      { month: '9월', date: '2026. 9. 17', dday: '-137', time: '3:00', highlighted: true },
      { month: '10월', date: '2026. 10. 29', dday: '-179', time: '3:00', highlighted: true },
      { month: '11월', date: '-', dday: '-', time: '-' },
      { month: '12월', date: '2026. 12. 10', dday: '-221', time: '4:00', highlighted: true },
    ],
  },
  {
    title: '고용보고서 발표',
    tooltip: '미국 일자리 상황을 보여주는 발표입니다. 예상보다 좋거나 나쁘면 금리와 경기 전망이 바뀌어 지수가 흔들릴 수 있습니다.',
    entries: [
      { month: '1월', date: '2026. 1. 9', dday: '114', time: '22:30' },
      { month: '2월', date: '2026. 2. 11', dday: '88', time: '22:30' },
      { month: '3월', date: '2026. 3. 6', dday: '58', time: '22:30' },
      { month: '4월', date: '2026. 4. 3', dday: '30', time: '22:30' },
      { month: '5월', date: '2026. 5. 8', dday: '0', time: '22:30', status: 'today' },
      { month: '6월', date: '2026. 6. 5', dday: '-33', time: '22:30', highlighted: true },
      { month: '7월', date: '2026. 7. 2', dday: '-60', time: '22:30', highlighted: true },
      { month: '8월', date: '2026. 8. 7', dday: '-96', time: '22:30', highlighted: true },
      { month: '9월', date: '2026. 9. 4', dday: '-124', time: '22:30', highlighted: true },
      { month: '10월', date: '2026. 10. 2', dday: '-152', time: '22:30', highlighted: true },
      { month: '11월', date: '2026. 11. 6', dday: '-187', time: '22:30', highlighted: true },
      { month: '12월', date: '2026. 12. 4', dday: '-215', time: '22:30', highlighted: true },
    ],
  },
  {
    title: 'CPI 발표',
    tooltip: '소비자 물가가 얼마나 올랐는지 보는 지표입니다. 예상과 다르면 금리 전망이 바뀌어 주식과 달러가 크게 움직일 수 있습니다.',
    entries: [
      { month: '1월', date: '2026. 1. 13', dday: '110', time: '22:30' },
      { month: '2월', date: '2026. 2. 13', dday: '86', time: '22:30' },
      { month: '3월', date: '2026. 3. 11', dday: '53', time: '21:30' },
      { month: '4월', date: '2026. 4. 10', dday: '23', time: '21:30' },
      { month: '5월', date: '2026. 5. 12', dday: '0', time: '21:30', status: 'today' },
      { month: '6월', date: '2026. 6. 10', dday: '-38', time: '21:30', highlighted: true },
      { month: '7월', date: '2026. 7. 14', dday: '-72', time: '21:30', highlighted: true },
      { month: '8월', date: '2026. 8. 12', dday: '-101', time: '21:30', highlighted: true },
      { month: '9월', date: '2026. 9. 11', dday: '-131', time: '21:30', highlighted: true },
      { month: '10월', date: '2026. 10. 14', dday: '-164', time: '21:30', highlighted: true },
      { month: '11월', date: '2026. 11. 10', dday: '-191', time: '22:30', highlighted: true },
      { month: '12월', date: '2026. 12. 10', dday: '-221', time: '22:30', highlighted: true },
    ],
  },
  {
    title: 'PPI 발표',
    tooltip: '기업이 물건을 만들 때 드는 비용 변화를 봅니다. 비용 부담이 커지면 물가 걱정이 커져 시장 변동성이 커질 수 있습니다.',
    entries: [
      { month: '1월', date: '2026. 1. 30', dday: '100', time: '22:30' },
      { month: '2월', date: '2026. 2. 27', dday: '65', time: '22:30' },
      { month: '3월', date: '2026. 3. 18', dday: '46', time: '21:30' },
      { month: '4월', date: '2026. 4. 14', dday: '19', time: '21:30' },
      { month: '5월', date: '2026. 5. 13', dday: '0', time: '21:30', status: 'today' },
      { month: '6월', date: '2026. 6. 11', dday: '-39', time: '21:30', highlighted: true },
      { month: '7월', date: '2026. 7. 15', dday: '-73', time: '21:30', highlighted: true },
      { month: '8월', date: '2026. 8. 13', dday: '-102', time: '21:30', highlighted: true },
      { month: '9월', date: '2026. 9. 10', dday: '-130', time: '21:30', highlighted: true },
      { month: '10월', date: '2026. 10. 15', dday: '-', time: '21:30', highlighted: true },
      { month: '11월', date: '2026. 11. 13', dday: '-194', time: '22:30', highlighted: true },
      { month: '12월', date: '2026. 12. 15', dday: '-226', time: '22:30', highlighted: true },
    ],
  },
  {
    title: 'PCE 발표',
    tooltip: '미국 중앙은행이 중요하게 보는 물가 지표입니다. 예상과 다르면 금리 전망이 바뀌어 시장이 흔들릴 수 있습니다.',
    entries: [
      { month: '1월', date: '2026. 1. 29', dday: '94', time: '22:30' },
      { month: '2월', date: '2026. 2. 26', dday: '66', time: '22:30' },
      { month: '3월', date: '2026. 3. 26', dday: '24', time: '21:30' },
      { month: '4월', date: '2026. 4. 30', dday: '3', time: '21:30' },
      { month: '5월', date: '2026. 5. 28', dday: '-25', time: '21:30', highlighted: true },
      { month: '6월', date: '2026. 6. 25', dday: '-53', time: '21:30', highlighted: true },
      { month: '7월', date: '2026. 7. 30', dday: '-88', time: '21:30', highlighted: true },
      { month: '8월', date: '2026. 8. 26', dday: '-115', time: '21:30', highlighted: true },
      { month: '9월', date: '2026. 9. 30', dday: '-150', time: '21:30', highlighted: true },
      { month: '10월', date: '2026. 10. 29', dday: '-179', time: '21:30', highlighted: true },
      { month: '11월', date: '2026. 11. 25', dday: '-206', time: '22:30', highlighted: true },
      { month: '12월', date: '2026. 12. 23', dday: '-234', time: '22:30', highlighted: true },
    ],
  },
  {
    title: '네마녀의 날',
    tooltip: '여러 파생상품 만기가 한꺼번에 겹치는 날입니다. 큰 자금 이동이 생겨 거래량과 가격 변동이 커질 수 있습니다.',
    entries: [
      { month: '1월', date: '-', dday: '-', time: '-' },
      { month: '2월', date: '-', dday: '-', time: '-' },
      { month: '3월', date: '2026. 3. 21', dday: '50', time: '5:00' },
      { month: '4월', date: '-', dday: '-', time: '-' },
      { month: '5월', date: '-', dday: '-', time: '-' },
      { month: '6월', date: '2026. 6. 19', dday: '-40', time: '5:00', highlighted: true },
      { month: '7월', date: '-', dday: '-', time: '-' },
      { month: '8월', date: '-', dday: '-', time: '-' },
      { month: '9월', date: '2026. 9. 19', dday: '-139', time: '5:00', highlighted: true },
      { month: '10월', date: '-', dday: '-', time: '-' },
      { month: '11월', date: '-', dday: '-', time: '-' },
      { month: '12월', date: '2026. 12. 19', dday: '-230', time: '6:00', highlighted: true },
    ],
  },
  {
    title: '나스닥 100 리밸런싱',
    tooltip: '나스닥100 안의 종목과 비중이 바뀌는 일정입니다. 펀드들이 비중을 맞추며 관련 종목 가격이 크게 움직일 수 있습니다.',
    entries: [
      { month: '1월', date: '-', dday: '-', time: '-' },
      { month: '2월', date: '-', dday: '-', time: '-' },
      { month: '3월', date: '2026. 3. 23', dday: '48', time: '22:30' },
      { month: '4월', date: '-', dday: '-', time: '-' },
      { month: '5월', date: '-', dday: '-', time: '-' },
      { month: '6월', date: '2026. 6. 22', dday: '-43', time: '22:30', highlighted: true },
      { month: '7월', date: '-', dday: '-', time: '-' },
      { month: '8월', date: '-', dday: '-', time: '-' },
      { month: '9월', date: '2026. 9. 21', dday: '-134', time: '22:30', highlighted: true },
      { month: '10월', date: '-', dday: '-', time: '-' },
      { month: '11월', date: '-', dday: '-', time: '-' },
      { month: '12월', date: '2026. 12. 21', dday: '-225', time: '23:30', highlighted: true },
    ],
  },
]

const valueMetricColumns: Array<{ label: string; value: (metric: ValuationMetric) => string; tooltip?: string }> = [
  { label: 'Market Cap', value: (metric) => metric.marketCap, tooltip: '회사의 전체 몸값입니다. 큰 회사일수록 안정적일 수 있지만, 같은 업종 대비 너무 비싼지는 함께 봅니다.' },
  { label: 'Sales', value: (metric) => metric.sales, tooltip: '최근에 벌어들인 매출 규모입니다. 매출이 크더라도 성장률이 낮으면 투자 매력은 줄 수 있습니다.' },
  { label: 'Sales Q/Q', value: (metric) => metric.salesQoq, tooltip: '직전 분기보다 매출이 얼마나 늘었는지 봅니다. 높으면 최근 흐름이 좋고, 계속 마이너스면 수요 둔화를 의심합니다.' },
  { label: 'Sales Y/Y (TTM)', value: (metric) => metric.salesYoyTtm, tooltip: '최근 12개월 매출이 1년 전보다 얼마나 늘었는지 봅니다. 성장률이 둔화되면 비싼 가격을 조심해서 봅니다.' },
  { label: 'Sales past 3/5Y', value: (metric) => metric.salesPastYears, tooltip: '최근 3년/5년 동안 매출이 꾸준히 늘었는지 봅니다. 들쭉날쭉하면 경기 영향을 많이 받는지 확인합니다.' },
  { label: 'Current Ratio', value: (metric) => metric.currentRatio, tooltip: '1년 안에 갚을 돈을 감당할 여력이 있는지 봅니다. 보통 1 이상이면 단기 자금 사정이 무난하다고 봅니다.' },
  { label: 'P/FCF', value: (metric) => metric.priceToFreeCashFlow, tooltip: '회사가 실제로 남기는 현금 대비 가격입니다. 낮으면 현금창출력 대비 싸고, 높으면 기대가 많이 반영된 상태일 수 있습니다.' },
  { label: 'P/S', value: (metric) => metric.priceToSales, tooltip: '매출 대비 회사 가격이 얼마나 비싼지 봅니다. 낮을수록 부담이 작고, 성장주는 업종 평균과 같이 비교합니다.' },
  { label: 'PER', value: (metric) => metric.per, tooltip: '이익 대비 주가가 얼마나 비싼지 보는 지표입니다. 낮으면 싸 보일 수 있고, 성장률이 낮은데 높으면 부담입니다.' },
  { label: 'PBR', value: (metric) => metric.pbr, tooltip: '회사가 가진 순자산 대비 주가가 비싼지 봅니다. 수익성이 낮은데 이 값이 높으면 주의가 필요합니다.' },
  { label: 'ROE', value: (metric) => metric.roe, tooltip: '회사가 가진 돈으로 얼마나 이익을 잘 내는지 봅니다. 높고 꾸준하면 좋지만, 빚 때문에 높아진 건 아닌지 확인합니다.' },
  { label: 'PEG', value: (metric) => metric.peg, tooltip: '이익 성장 속도 대비 주가가 비싼지 봅니다. 1 안팎이면 무난하고, 높을수록 성장 대비 비싸다는 뜻입니다.' },
  { label: 'Shares Outstanding', value: (metric) => metric.sharesOutstanding, tooltip: '시장에 풀린 전체 주식 수입니다. 늘어나면 기존 주주의 몫이 줄 수 있고, 줄어들면 주당 가치에 유리합니다.' },
  { label: 'Gross Margin', value: (metric) => metric.grossMargin, tooltip: '제품을 팔고 원가를 뺀 뒤 얼마나 남는지 봅니다. 높을수록 가격 경쟁력이 좋고, 하락하면 원가 부담을 의심합니다.' },
  { label: 'Oper. Margin', value: (metric) => metric.operatingMargin, tooltip: '본업에서 매출 대비 얼마나 이익을 남기는지 봅니다. 높고 안정적이면 좋고, 마이너스면 비용 구조를 먼저 봅니다.' },
  { label: 'EPS (TTM)', value: (metric) => metric.epsTtm, tooltip: '최근 12개월 동안 주식 1주당 벌어들인 이익입니다. 높고 증가하면 이익 체력이 좋다고 봅니다.' },
  { label: 'EPS Next Y', value: (metric) => metric.epsNextYear, tooltip: '다음 해에 예상되는 1주당 이익입니다. 현재보다 높으면 성장 기대가 있고, 자주 낮아지면 보수적으로 봅니다.' },
  { label: 'EPS Q/Q (%)', value: (metric) => metric.epsQoq, tooltip: '직전 분기보다 1주당 이익이 얼마나 늘었는지 봅니다. 높으면 최근 실적 흐름이 좋다는 뜻입니다.' },
  { label: 'Rule of 40%', value: (metric) => metric.ruleOf40, tooltip: '성장률과 이익률을 같이 보는 지표입니다. 40% 이상이면 성장과 수익의 균형이 좋다고 봅니다.' },
  { label: '실적발표일 (한국 시간 기준)', value: (metric) => metric.earningsDate },
]

const technicalMarketSnapshot: string[][] = [
  ['시장 주요 이벤트', '당분간 없음'],
  ['VIX (변동성지수) 당일·전날', '16.99 / 16.89'],
  ['미국 10년물 금리', '4.378'],
  ['달러 인덱스', '98.21'],
  ['QQQ 주봉 RSI (14)', '64.16'],
  ['QQQ 일봉 RSI (14, 당일)', '82.79'],
  ['QQQ 일봉 RSI (14, 전날)', '82.78'],
  ['QQQ MACD Histogram (D/D-1/D-2)', '+12.34 / +13.21 / +14.02'],
  ['QQQ 60거래일 최저 이격도', '-5.20%'],
  ['QQQ 매수 차단 기준', '>+18.00%'],
  ['나스닥 (QQQ, 당일)', '674.18'],
  ['나스닥 (QQQ, 20일 이동평균선)', '638.20'],
  ['나스닥 (QQQ, 60일 이동평균선)', '611.53'],
  ['나스닥 (QQQ, 144일 이동평균선)', '614.24'],
  ['나스닥 (QQQ, 200일 이동평균선)', '604.08'],
  ['나스닥 (QQQ, 200일선 이격도)', '+11.60%'],
]

const technicalSummaryTooltips: Record<string, string> = {
  '시장 주요 이벤트': '금리, 물가, 고용처럼 시장 전체 변동성을 키울 수 있는 일정을 먼저 확인합니다.',
  'VIX (변동성지수) 당일·전날': '시장 공포심과 변동성 수준을 봅니다. 높거나 급등하면 보수적으로 판단합니다.',
  'CNN 공포·탐욕지수 당일·전날': '투자 심리가 과열인지 공포인지 확인합니다. 극단 구간에서는 반대 움직임을 주의합니다.',
  '미국 10년물 금리': '성장주와 할인율에 영향을 주는 핵심 금리입니다. 급등하면 기술주 부담이 커질 수 있습니다.',
  '달러 인덱스': '달러 강세 여부를 봅니다. 달러가 강하면 위험자산과 해외 매출 기업에 부담이 될 수 있습니다.',
  'QQQ 주봉 RSI (14)': '나스닥 중기 과열·침체를 봅니다. 주봉 기준이라 큰 추세 판단에 씁니다.',
  'QQQ 일봉 RSI (14, 당일)': '나스닥 단기 과열 여부를 확인합니다. 높으면 신규 진입을 조심합니다.',
  'QQQ 일봉 RSI (14, 전날)': '전날 RSI와 비교해 단기 매수세가 강해졌는지 약해졌는지 봅니다.',
  'QQQ MACD Histogram (D/D-1/D-2)': 'QQQ의 MACD 히스토그램 3일 흐름입니다. D < D-1 < D-2이면 상승 힘이 2일 연속 둔화된 것으로 봅니다.',
  'QQQ 60거래일 최저 이격도': '최근 60거래일 동안 QQQ가 200일선 대비 가장 낮았던 위치입니다. -5% 이하 이력이 있으면 급락 후 회복장 후보로 봅니다.',
  'QQQ 매수 차단 기준': '현재 QQQ 이격도와 비교하는 신규·재진입 차단선입니다. 급락 후 회복장은 +18%, 비회복장은 +9%를 씁니다.',
  '나스닥 (QQQ, 당일)': '기술주 대표 지수의 현재 위치를 봅니다. 개별 종목 신호의 시장 배경입니다.',
  '나스닥 (QQQ, 20일 이동평균선)': '단기 평균선입니다. QQQ가 이 선 위면 단기 흐름이 비교적 양호합니다.',
  '나스닥 (QQQ, 60일 이동평균선)': '중기 평균선입니다. 시장의 중기 추세가 꺾이는지 확인합니다.',
  '나스닥 (QQQ, 144일 이동평균선)': '200일선보다 빠른 장기 흐름 기준입니다. 추세 변화 조기 확인에 씁니다.',
  '나스닥 (QQQ, 200일 이동평균선)': '장기 추세의 기준선입니다. 이탈하면 시장 리스크를 더 크게 봅니다.',
  '나스닥 (QQQ, 200일선 이격도)': 'QQQ가 200일선 대비 얼마나 위/아래에 있는지 보여줍니다. 매수 차단과 고점 청산의 기본 위치값입니다.',
}

function isMeaningfulMarketSnapshot(snapshot: string[][]) {
  return snapshot.length > 2 || !snapshot.some(([label, value]) => (
    (label === '시장 주요 이벤트' && value === '캐시 기준')
    || label === '기술분석 갱신 주기'
  ))
}

function mergeMarketSnapshot(snapshot: string[][]): string[][] {
  if (!isMeaningfulMarketSnapshot(snapshot)) return technicalMarketSnapshot

  const incomingValues = new Map<string, string>(
    snapshot.map(([label, value]) => [label, label === '시장 주요 이벤트' && value === '캐시 기준' ? '당분간 없음' : value]),
  )
  const normalizedRows = snapshot
    .filter(([label]) => label !== '기술분석 갱신 주기')
    .map(([label, value]) => [label, incomingValues.get(label) ?? value])
  const [eventRow = technicalMarketSnapshot[0], ...restRows] = normalizedRows
  const vixRows = restRows.filter(([label]) => label.startsWith('VIX'))
  const otherRows = restRows.filter(([label]) => !label.startsWith('VIX'))

  return [
    eventRow,
    ...vixRows,
    ...otherRows,
  ]
}

function technicalSummaryDisplayLabel(label: string) {
  return label === 'QQQ MACD Histogram (D/D-1/D-2)' ? 'QQQ MACD Histogram' : label
}

function shouldShowTechnicalSummaryCard(label: string) {
  return label !== 'QQQ 매수 차단 기준'
}

function technicalSeed(stock: Stock, index: number, salt = 0) {
  const base = [...stock.ticker].reduce((sum, char) => sum + char.charCodeAt(0), 0)
  return (base * 17 + index * 31 + salt * 13) % 997
}

function technicalNumber(stock: Stock, index: number, salt: number, min: number, span: number, decimals = 2) {
  const value = min + (technicalSeed(stock, index, salt) / 996) * span
  return Number(value.toFixed(decimals))
}

function formatTechnicalNumber(value: number, decimals = 2) {
  return value.toLocaleString('en-US', { maximumFractionDigits: decimals, minimumFractionDigits: decimals })
}

function formatSignedTechnical(value: number, decimals = 2) {
  return `${value >= 0 ? '+' : ''}${formatTechnicalNumber(value, decimals)}`
}

function stockPriceNumber(stock: Stock) {
  return parsePriceValue(stock.currentPrice) ?? 100
}

function formatUpdateTime(date: Date) {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function nextTwoHourUpdateLabel(date = new Date()) {
  const nextUpdate = new Date(date)
  nextUpdate.setMinutes(0, 0, 0)
  nextUpdate.setHours(nextUpdate.getHours() + (nextUpdate.getHours() % 2 === 0 ? 2 : 1))
  return `${formatUpdateTime(nextUpdate)} 에 업데이트 예정`
}

function nextMidnightUpdateLabel(date = new Date()) {
  const nextUpdate = new Date(date)
  nextUpdate.setDate(nextUpdate.getDate() + 1)
  nextUpdate.setHours(0, 0, 0, 0)
  return `${formatUpdateTime(nextUpdate)} 에 업데이트 예정`
}

function isPendingValue(value: string) {
  // 원격 JSON 행은 타입상 string이지만 값이 비어 올 수 있어 방어한다.
  if (typeof value !== 'string') return true
  return value.trim() === '-'
}

function formatTechnicalPrice(stock: Stock, value: number) {
  if (stock.market === 'KR') return `₩${Math.round(value).toLocaleString('ko-KR')}`
  return `$${formatTechnicalNumber(value, 2)}`
}

function formatTechnicalVolume(stock: Stock, index: number, salt: number) {
  const value = Math.round(technicalNumber(stock, index, salt, stock.market === 'KR' ? 85_000 : 450_000, stock.market === 'KR' ? 1_420_000 : 9_800_000, 0))
  return value.toLocaleString('ko-KR')
}

function technicalEarningsDate(stock: Stock) {
  return valuationMetrics[stock.ticker]?.earningsDate ?? '-'
}

function openTradesForStock(stock: Stock, targetTrades: TradeLog[]) {
  return targetTrades.filter((trade) => trade.ticker === stock.ticker && trade.status === '보유 중')
}

function openTradeStrategiesForStock(stock: Stock, targetTrades: TradeLog[]) {
  const strategies = openTradesForStock(stock, targetTrades).map((trade) => trade.strategy).filter(Boolean)
  return Array.from(new Set(strategies))
}

function displayStrategiesForStock(stock: Stock, targetTrades: TradeLog[] = []) {
  const openTradeStrategies = openTradeStrategiesForStock(stock, targetTrades)
  return openTradeStrategies.length > 0 ? openTradeStrategies : stock.strategies
}

function technicalEntryStrategiesForStock(stock: Stock, targetTrades: TradeLog[] = []) {
  const strategies = openTradesForStock(stock, targetTrades).map((trade) => trade.strategy).filter(Boolean)
  return strategies.length > 0 ? strategies : stock.strategies
}

function joinTradeValues(targetTrades: TradeLog[], value: (trade: TradeLog) => string) {
  const values = targetTrades.map(value).filter(Boolean)
  return values.length > 0 ? values.join(', ') : '-'
}

function technicalEntryPrice(stock: Stock, targetTrades: TradeLog[] = []) {
  return joinTradeValues(openTradesForStock(stock, targetTrades), (trade) => trade.buyPrice)
}

function technicalEntryDate(stock: Stock, targetTrades: TradeLog[] = []) {
  return joinTradeValues(openTradesForStock(stock, targetTrades), (trade) => trade.buyDate.replaceAll('.', '-'))
}

function technicalEntryStrategy(stock: Stock, targetTrades: TradeLog[] = []) {
  const strategies = technicalEntryStrategiesForStock(stock, targetTrades)
  return strategies.length > 0 ? strategies.join(', ') : '-'
}

const technicalMetricColumns: TechnicalColumn[] = [
  { label: 'RSI (D)', tooltip: '최근 14일 기준으로 주가가 얼마나 강하게 올랐는지 봅니다. 70 이상은 과열, 30 이하는 과매도에 가깝습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 1, 29, 58), 2) },
  { label: 'RSI (D-1)', tooltip: '어제 기준 RSI입니다. 오늘 값과 비교해 매수세가 더 강해졌는지 약해졌는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 2, 28, 57), 2) },
  { key: 'RSI Signal', label: 'RSI EMA(9)', tooltip: 'RSI 값들을 9일 EMA로 부드럽게 만든 비교선입니다. RSI가 이 선 위면 단기 힘이 유지되는 쪽으로 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 3, 32, 48), 2) },
  { key: 'RSI 기울기', label: 'RSI 변화(D-D-1)', tooltip: '오늘 RSI에서 어제 RSI를 뺀 값입니다. 플러스면 매수세가 강해지고, 마이너스면 힘이 약해지는 흐름입니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 4, -9, 16), 2) },
  { label: 'CCI (D)', tooltip: '최근 14일 고가·저가·종가의 typical price 기준 CCI입니다. +100 이상은 강세, -100 이하는 약세나 과매도에 가깝습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 5, -130, 280), 2) },
  { label: 'CCI (D-1)', tooltip: '어제 기준 14일 CCI입니다. 오늘 값과 비교해 강세나 약세가 이어지는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 6, -125, 270), 2) },
  { key: 'CCI Signal', label: 'CCI EMA(9)', tooltip: '14일 CCI 값들을 9일 EMA로 부드럽게 만든 비교선입니다. CCI가 이 선 위로 올라서면 단기 반등 힘이 붙었다고 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 7, -90, 240), 2) },
  { key: 'CCI 기울기', label: 'CCI 변화(D-D-1)', tooltip: '오늘 CCI에서 어제 CCI를 뺀 값입니다. 크게 오르면 반등 시도, 크게 내리면 힘이 약해진 흐름입니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 8, -58, 136), 2) },
  { label: 'MACD (12, 26, D)', tooltip: '짧은 평균가격과 긴 평균가격의 차이입니다. 0보다 높으면 상승 흐름, 낮으면 하락 흐름이 우세합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 9, -900, 12000), 2) },
  { label: 'MACD (12, 26, D-1)', tooltip: '어제 기준 MACD입니다. 오늘 값과 비교해 추세가 강해졌는지 약해졌는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 10, -850, 11200), 2) },
  { key: 'MACD Signal', label: 'MACD Signal EMA(9)', tooltip: 'MACD 값들을 9일 EMA로 부드럽게 만든 비교선입니다. MACD가 이 선 위면 상승 힘이 있고, 아래면 힘이 약해질 수 있습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 11, -700, 9800), 2) },
  { key: 'MACD Histogram (D)', label: 'MACD Hist(D)', tooltip: 'MACD에서 Signal을 뺀 값입니다. 값이 커지면 추세가 강해지고, 작아지면 힘이 약해질 수 있습니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 12, -4200, 7600), 2) },
  { key: 'M - H (D-1)', label: 'MACD Hist(D-1)', tooltip: '어제 기준 MACD Histogram입니다. 오늘 값과 비교해 모멘텀이 이어지는지 봅니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 13, -2400, 5000), 2) },
  { key: 'M - H (D-2)', label: 'MACD Hist(D-2)', tooltip: '2거래일 전 MACD Histogram입니다. 최근 3일 흐름을 같이 봐서 일시적인 신호를 줄입니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 14, -2100, 4600), 2) },
  { key: 'MACD 기울기', label: 'MACD 기울기', tooltip: '오늘 MACD 값에서 어제 MACD 값을 뺀 값입니다. 플러스면 MACD 추세가 개선되고, 마이너스면 상승 힘이 약해질 수 있습니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 15, -620, 1360), 2) },
  { label: '+DI (DMI, 14)', tooltip: '상승 힘을 보여주는 지표입니다. +DI가 -DI보다 높으면 매수세가 더 강하다고 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 16, 12, 52), 2) },
  { label: '-DI (DMI, 14)', tooltip: '하락 힘을 보여주는 지표입니다. -DI가 +DI보다 높으면 매도 압력이 더 강하다고 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 17, 9, 48), 2) },
  { label: 'ADX (14, D)', tooltip: '상승이든 하락이든 추세가 얼마나 강한지 봅니다. 20 이상이면 추세가 생겼고, 40 이상이면 강한 편입니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 18, 14, 58), 2) },
  { label: 'ADX (14, D-1)', tooltip: '어제 기준 ADX입니다. 오늘 값과 비교해 추세의 힘이 커졌는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 19, 13, 57), 2) },
  { label: 'ADX (14, D-2)', tooltip: '2거래일 전 ADX입니다. 최근 3일 동안 추세의 힘이 강해지는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 20, 13, 55), 2) },
  { key: 'ADX 기울기', label: 'ADX 변화(D-D-1)', tooltip: '오늘 ADX에서 어제 ADX를 뺀 값입니다. 오르면 추세가 강해지고, 내리면 횡보 가능성이 커집니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 21, -6, 12), 2) },
  { key: 'Candle Open', label: '시가(D)', tooltip: '오늘 장이 시작된 가격입니다. 종가와 비교해 장중에 매수세가 강했는지 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 22, 0.965, 0.07, 4)) },
  { key: 'C - High', label: '고가(D)', tooltip: '오늘 가장 높게 거래된 가격입니다. 종가가 고가에 가까우면 매수세가 끝까지 강했다고 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 23, 1.005, 0.06, 4)) },
  { key: 'C - Low', label: '저가(D)', tooltip: '오늘 가장 낮게 거래된 가격입니다. 저가에서 얼마나 회복했는지로 반등 힘을 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 24, 0.925, 0.065, 4)) },
  { key: 'C - Close', label: '종가(D)', tooltip: '오늘 마감 가격입니다. 대부분의 기술 지표가 이 가격을 기준으로 계산됩니다.', value: (stock) => stock.currentPrice },
  { key: 'C - Volume', label: '캔들 거래량(D)', tooltip: '오늘 캔들 데이터의 실제 거래량입니다. 가격 움직임에 거래량이 같이 붙으면 신뢰도가 높아집니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 25) },
  { label: '아래꼬리 길이', tooltip: '시가와 종가 중 낮은 값에서 저가를 뺀 폭입니다. 길수록 저점 매수세가 들어왔다고 볼 수 있습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 26, 0, 18), 2) },
  { label: '위꼬리 길이', tooltip: '고가에서 시가와 종가 중 높은 값을 뺀 폭입니다. 길수록 위에서 매물이 많이 나왔다고 볼 수 있습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 27, 0, 16), 2) },
  { label: '몸통 길이', tooltip: '시가와 종가의 차이입니다. 클수록 그날 방향성이 뚜렷합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 28, 0.2, 22), 2) },
  { key: '거래량 (D)', label: '5일 평균 대비 거래량(D)', tooltip: '오늘 실제 거래량을 최근 5일 평균 거래량으로 나눈 비율입니다. 100% 이상이면 최근 5일 평균보다 거래가 많습니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 29) },
  { key: '거래량 (D-1)', label: '전일 5일 평균 대비 거래량(D-1)', tooltip: '어제 실제 거래량을 어제 기준 직전 5일 평균 거래량으로 나눈 비율입니다. 오늘 비율과 비교해 관심이 늘었는지 확인합니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 30) },
  { label: '20일 평균 대비 거래량 (D)', tooltip: '최근 20일 평균보다 오늘 거래가 얼마나 많은지 봅니다. 100% 이상이면 평소보다 활발합니다.', value: (stock, index) => `${formatTechnicalNumber(technicalNumber(stock, index, 31, 45, 165), 0)}%` },
  { key: '절대 거래량 (D)', label: '실제 거래량(D)', tooltip: '오늘 실제 거래된 주식 수입니다. 거래가 너무 적으면 신호가 좋아도 매매가 어려울 수 있습니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 32) },
  { label: '볼린저밴드 %B (종가)', tooltip: '종가가 가격 범위 안에서 위쪽인지 아래쪽인지 봅니다. 80 이상은 상단, 20 이하는 하단에 가깝습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 33, 5, 112), 2) },
  { label: '볼린저밴드 %B (저가)', tooltip: '오늘 저가가 가격 범위 안에서 어디였는지 봅니다. 장중에 아래쪽을 찍고 회복했는지 확인합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 34, 0, 105), 2) },
  { key: '볼린저밴드 Peak (D)', label: '볼린저밴드 %B (고가)', tooltip: '오늘 고가가 볼린저밴드 안에서 어디까지 올라갔는지 보는 값입니다. 과열 후 힘이 약해지는지 볼 때 씁니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 35, 20, 95), 2) },
  { key: '볼린저밴드 Peak (D-1)', label: '전일 볼린저밴드 %B (고가)', tooltip: '어제 고가 기준 볼린저밴드 %B입니다. 오늘 고가 위치와 비교해 과열이 이어지는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 36, 18, 92), 2) },
  { label: '볼린저밴드 폭 (D)', tooltip: '가격이 움직이는 범위의 넓이입니다. 좁으면 조용한 구간, 넓으면 크게 움직이는 구간입니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 37, 8, 48), 2) },
  { label: '볼린저밴드 폭 (D-1)', tooltip: '어제 기준 가격 범위의 넓이입니다. 오늘과 비교해 움직임이 커졌는지 작아졌는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 38, 8, 46), 2) },
  { key: '지난 60일 볼린저밴드 폭 평균', label: '볼린저밴드 폭 60일 평균', tooltip: '최근 60거래일 동안의 볼린저밴드 폭 평균입니다. 현재 폭이 평소보다 좁은지 넓은지 비교합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 39, 12, 42), 2) },
  { label: '현재가', tooltip: '가장 최근 가격입니다. 평균선, 가격 범위, 진입가와 비교해 현재 위치를 봅니다.', value: (stock) => stock.currentPrice },
  { label: '5일 이동평균선', tooltip: '최근 5일 평균 가격입니다. 현재가가 이 선 위면 단기 흐름이 강한 편입니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 40, 0.965, 0.07, 4)) },
  { label: '20일 이동평균선', tooltip: '최근 20일 평균 가격입니다. 이 선 위에 있으면 단기 상승 흐름이 유지된다고 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 41, 0.92, 0.13, 4)) },
  { label: '60일 이동평균선', tooltip: '최근 60일 평균 가격입니다. 이 선 위면 중기 흐름이 좋고, 아래면 약세를 의심합니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 42, 0.84, 0.2, 4)) },
  { label: '144일 이동평균선', tooltip: '최근 144일 평균 가격입니다. 장기 흐름이 바뀌는지 200일선보다 조금 빠르게 볼 때 씁니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 43, 0.78, 0.24, 4)) },
  { label: '200일 이동평균선', tooltip: '최근 200일 평균 가격입니다. 현재가가 이 선 위면 장기 흐름이 좋다고 보는 경우가 많습니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 44, 0.72, 0.28, 4)) },
  { label: '120일 저가 회귀 추세선', tooltip: '최근 120일의 낮은 가격 흐름을 따라 그은 선입니다. 현재가가 위에 있으면 저점이 높아지는 흐름입니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 45, 0.68, 0.34, 4)) },
  { label: '실적발표일 (한국 시간 기준)', tooltip: '한국 시간 기준 실적 발표일입니다. 실적 전후에는 가격이 크게 움직일 수 있어 주의합니다.', value: (stock) => technicalEarningsDate(stock) },
  { label: '진입가', tooltip: '현재 보유 중인 종목을 산 가격입니다. 보유 전이면 빈 값으로 표시합니다.', value: (stock) => technicalEntryPrice(stock) },
  { label: '진입일', tooltip: '현재 보유 중인 종목을 산 날짜입니다. 보유 전이면 빈 값으로 표시합니다.', value: (stock) => technicalEntryDate(stock) },
  { label: '진입 전략', tooltip: '매수할 때 사용된 전략명입니다. A~F 전략 설명은 Home의 전략 툴팁과 같은 기준입니다.', value: (stock) => technicalEntryStrategy(stock) },
]

function MetricValue({
  children,
  tooltip,
  onTooltipOpen,
  onTooltipClose,
}: {
  children: string
  tooltip?: string
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  if (!tooltip) return <>{children}</>

  const openTooltip = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect()
    const tooltipHalfWidth = Math.min(130, (window.innerWidth - 32) / 2)
    const minX = tooltipHalfWidth + 16
    const maxX = window.innerWidth - tooltipHalfWidth - 16
    const centeredX = rect.left + rect.width / 2

    onTooltipOpen({
      text: tooltip,
      x: Math.min(Math.max(centeredX, minX), maxX),
      y: rect.top - 8,
    })
  }

  return (
    <button
      className="metric-tooltip-trigger"
      type="button"
      onBlur={onTooltipClose}
      onClick={(event) => {
        event.stopPropagation()
        openTooltip(event.currentTarget)
      }}
      onFocus={(event) => openTooltip(event.currentTarget)}
      onMouseEnter={(event) => openTooltip(event.currentTarget)}
      onMouseLeave={onTooltipClose}
    >
      {children}
    </button>
  )
}

function ValueAnalysisPage({
  stocks,
  viewMode,
  valuationRows,
  updateLabel,
  addStockControl,
  onAddStock,
  onTooltipOpen,
  onTooltipClose,
}: {
  stocks: Stock[]
  viewMode: 'personal' | 'operator'
  valuationRows: Record<string, ValuationMetric>
  updateLabel: string
  addStockControl?: ReactNode
  onAddStock: () => void
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  const visibleStocks = stocks.slice(0, MAX_WATCHLIST_ITEMS)
  const blankRowCount = Math.max(MAX_WATCHLIST_ITEMS - visibleStocks.length, 0)
  const isEmpty = stocks.length === 0
  const sheetWheelRef = useEdgeScrollWheelRef()

  return (
    <section className="panel value-analysis-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>가치 분석</h2>
          <p>Home 관심 종목 기준으로 핵심 재무 지표를 확인해 적정 주가 범위를 계산하고, 현재가를 기준으로 저평가/고평가 여부를 판단합니다.</p>
          <p className="page-update-note">각 지표는 매일 자정에 1회 업데이트됩니다.</p>
        </div>
        <span className="section-heading-meta">총 {visibleStocks.length}개 <b>|</b> {updateLabel}</span>
      </div>

      {addStockControl}

      {isEmpty ? (
        <div className="watchlist-empty-panel analysis-empty-panel">
          <div className="empty-watchlist">
            <strong>관심 종목이 없습니다.</strong>
            <span>종목을 추가하면 가치 분석 표에 표시됩니다.</span>
            {viewMode === 'personal' && (
              <button className="analysis-overlay-add-button" type="button" onClick={onAddStock}>
                관심종목 추가
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="sheet-wrap value-analysis-sheet" ref={sheetWheelRef}>
          <table className="sheet-table value-analysis-table">
          <thead>
            <tr>
              <th>종목명</th>
              <th>티커</th>
              <th>
                <MetricValue
                  tooltip="가치주는 이익 대비 가격 부담이 낮은 종목입니다. 성장주는 매출·이익 성장 기대가 큰 종목, 혼합주는 두 성격이 함께 있는 종목입니다."
                  onTooltipClose={onTooltipClose}
                  onTooltipOpen={onTooltipOpen}
                >
                  구분
                </MetricValue>
              </th>
              <th>산업</th>
              <th>
                <MetricValue
                  tooltip={FAIR_PRICE_RANGE_TOOLTIP}
                  onTooltipClose={onTooltipClose}
                  onTooltipOpen={onTooltipOpen}
                >
                  적정 주가 범위
                </MetricValue>
              </th>
              <th>현재가</th>
              <th>가치 평가</th>
              {valueMetricColumns.map((column) => (
                <th className={column.label.startsWith('실적발표일') ? 'earnings-date-cell' : undefined} key={column.label}>
                  <MetricValue
                    tooltip={column.tooltip}
                    onTooltipClose={onTooltipClose}
                    onTooltipOpen={onTooltipOpen}
                  >
                    {column.label}
                  </MetricValue>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleStocks.map((stock) => {
              const metric = valuationRows[stock.ticker]
              const displayValuation = displayStockValuation(stock)

              return (
                <tr key={stock.ticker}>
                  <td className="name-data-cell">
                    <AnalysisStockName stock={stock} onTooltipClose={onTooltipClose} onTooltipOpen={onTooltipOpen} />
                  </td>
                  <td className="ticker-cell">{stock.ticker}</td>
                  <td>{stock.category ?? (stock.market === 'KR' ? '성장주' : '혼합주')}</td>
                  <td className="industry-cell">{displayIndustryLabel(stock.industry)}</td>
                  <td className="number-cell">{isFairPriceUnavailable(stock) ? <span className="unavailable-value-label">{displayFairPriceText(stock)}</span> : displayFairPriceText(stock)}</td>
                  <td className="number-cell">{displayCurrentPriceText(stock)}</td>
                  <td><span className={`status-badge ${valuationBadgeClass(displayValuation)}`}>{displayValuation}</span></td>
                  {valueMetricColumns.map((column) => (
                    <td className={`number-cell ${column.label.startsWith('실적발표일') ? 'earnings-date-cell' : ''}`.trim()} key={column.label}>
                      {metric ? column.value(metric) : '-'}
                    </td>
                  ))}
                </tr>
              )
            })}
            {Array.from({ length: blankRowCount }).map((_, index) => (
              <tr className="blank-row" key={`value-analysis-blank-${index}`}>
                {Array.from({ length: 7 + valueMetricColumns.length }).map((__, cellIndex) => (
                  <td key={`value-analysis-blank-${index}-${cellIndex}`}>&nbsp;</td>
                ))}
              </tr>
            ))}
          </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function TechnicalAnalysisPage({
  stocks,
  viewMode,
  technicalRows,
  tradeLogs,
  hideSellSignals,
  marketSnapshot,
  updateLabel,
  addStockControl,
  onAddStock,
  onTooltipOpen,
  onTooltipClose,
}: {
  stocks: Stock[]
  viewMode: 'personal' | 'operator'
  technicalRows: Record<string, Record<string, string>>
  tradeLogs: TradeLog[]
  hideSellSignals: boolean
  marketSnapshot: string[][]
  updateLabel: string
  addStockControl?: ReactNode
  onAddStock: () => void
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  const [isSummaryOpen, setIsSummaryOpen] = useState(false)
  const visibleStocks = stocks.slice(0, MAX_WATCHLIST_ITEMS)
  const blankRowCount = Math.max(MAX_WATCHLIST_ITEMS - visibleStocks.length, 0)
  const isEmpty = stocks.length === 0
  const sheetWheelRef = useEdgeScrollWheelRef()
  const vixSnapshot = marketSnapshot.find(([label]) => label === 'VIX (변동성지수) 당일·전날')?.[1] ?? '16.99 / 16.89'
  const fearGreedSnapshot = marketSnapshot.find(([label]) => label === 'CNN 공포·탐욕지수 당일·전날')?.[1]
  const tnxSnapshot = marketSnapshot.find(([label]) => label === '미국 10년물 금리')?.[1] ?? '4.378'
  const dollarSnapshot = marketSnapshot.find(([label]) => label === '달러 인덱스')?.[1] ?? '98.21'
  const qqqDailyRsi = marketSnapshot.find(([label]) => label === 'QQQ 일봉 RSI (14, 당일)')?.[1] ?? '82.79'
  const qqqDailyRsiPrev = marketSnapshot.find(([label]) => label === 'QQQ 일봉 RSI (14, 전날)')?.[1] ?? '82.78'
  const qqqPrice = marketSnapshot.find(([label]) => label === '나스닥 (QQQ, 당일)')?.[1] ?? '674.18'
  const qqqMa200 = marketSnapshot.find(([label]) => label === '나스닥 (QQQ, 200일 이동평균선)')?.[1] ?? '604.08'
  const qqqPriceValue = parsePriceValue(qqqPrice)
  const qqqMa200Value = parsePriceValue(qqqMa200)
  const qqqMa200Distance = qqqPriceValue !== null && qqqMa200Value !== null && qqqMa200Value > 0
    ? ((qqqPriceValue / qqqMa200Value - 1) * 100).toFixed(1)
    : null
  const qqqSummary = qqqMa200Distance === null
    ? `나스닥(QQQ) ${qqqPrice} / 200일선 ${qqqMa200}`
    : `나스닥(QQQ) ${qqqPrice} / 200일선 ${qqqMa200} (200일선 대비 ${Number(qqqMa200Distance) >= 0 ? '+' : ''}${qqqMa200Distance}%)`

  return (
    <section className="panel value-analysis-panel technical-analysis-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>기술 분석</h2>
          <p>Home 관심 종목 기준으로 RSI, CCI, MACD, DMI, 캔들, 거래량, 볼린저밴드, 이동평균 데이터 등의 기술 지표들을 활용해 매매 타이밍을 판단합니다.</p>
          <p className="page-update-note">각 지표는 2시간마다 업데이트되며, 삼성증권 앱과 동일한 계산 방식을 적용하기 때문에 본인이 바라보는 지표와 일부 다를 수 있습니다.</p>
        </div>
        <span className="section-heading-meta">총 {visibleStocks.length}개 <b>|</b> {updateLabel}</span>
      </div>

      <details
        className="technical-summary-disclosure"
        open={isSummaryOpen}
        onToggle={(event) => setIsSummaryOpen(event.currentTarget.open)}
      >
        <summary>
          <span>공통 지표</span>
          <strong>VIX (변동성지수) {vixSnapshot}</strong>
          {fearGreedSnapshot && <strong>CNN 공포·탐욕지수 {fearGreedSnapshot}</strong>}
          <strong>{qqqSummary}</strong>
          <strong>미국 10년물 금리 {tnxSnapshot}</strong>
          <strong>달러 인덱스 {dollarSnapshot}</strong>
          <strong>QQQ 일봉 RSI 당일 {qqqDailyRsi} / 전날 {qqqDailyRsiPrev}</strong>
          <em>펼쳐보기</em>
        </summary>
        <div className="technical-summary-strip" aria-label="기술 분석 시장 요약">
          {marketSnapshot.filter(([label]) => shouldShowTechnicalSummaryCard(label)).map(([label, value]) => (
            <div className="technical-summary-item" key={label}>
              <span>
                <MetricValue
                  tooltip={technicalSummaryTooltips[label]}
                  onTooltipClose={onTooltipClose}
                  onTooltipOpen={onTooltipOpen}
                >
                  {technicalSummaryDisplayLabel(label)}
                </MetricValue>
              </span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        <button className="technical-summary-collapse-button" type="button" onClick={() => setIsSummaryOpen(false)}>
          공통 지표 접기
        </button>
      </details>

      {addStockControl}

      {isEmpty ? (
        <div className="watchlist-empty-panel analysis-empty-panel">
          <div className="empty-watchlist">
            <strong>관심 종목이 없습니다.</strong>
            <span>종목을 추가하면 기술 분석 표에 표시됩니다.</span>
            {viewMode === 'personal' && (
              <button className="analysis-overlay-add-button" type="button" onClick={onAddStock}>
                관심종목 추가
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="sheet-wrap value-analysis-sheet technical-analysis-sheet" ref={sheetWheelRef}>
          <table className="sheet-table value-analysis-table technical-analysis-table">
            <thead>
              <tr>
                <th>종목명</th>
                <th>티커</th>
                <th>투자의견</th>
                {technicalMetricColumns.map((column) => (
                  <th className={column.label.startsWith('실적발표일') ? 'earnings-date-cell' : undefined} key={column.label}>
                    <MetricValue
                      tooltip={column.tooltip}
                      onTooltipClose={onTooltipClose}
                      onTooltipOpen={onTooltipOpen}
                    >
                      {column.label}
                    </MetricValue>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleStocks.map((stock) => {
                const apiRow = technicalRows[stock.ticker]
                const displayedOpinion = hideSellSignals && stock.opinion === '매도' ? '관망' : displayStockOpinion(stock)

                return (
                <tr key={stock.ticker}>
                  <td className="name-data-cell">
                    <AnalysisStockName stock={stock} onTooltipClose={onTooltipClose} onTooltipOpen={onTooltipOpen} />
                  </td>
                  <td className="ticker-cell">{stock.ticker}</td>
                  <td><span className={`status-badge ${statusClass(displayedOpinion)}`}>{displayedOpinion}</span></td>
                  {technicalMetricColumns.map((column) => {
                    const apiKey = column.key ?? column.label
                    const entryStrategies = apiKey === '진입 전략' ? technicalEntryStrategiesForStock(stock, tradeLogs) : []
                    const value = apiKey === '진입가'
                      ? technicalEntryPrice(stock, tradeLogs)
                      : apiKey === '진입일'
                        ? technicalEntryDate(stock, tradeLogs)
                        : apiKey === '진입 전략'
                          ? (entryStrategies.length > 0 ? entryStrategies.join(', ') : '-')
                          : apiRow?.[apiKey] ?? '-'
                    const isEntryStrategy = apiKey === '진입 전략'
                    const isEarningsDate = apiKey.startsWith('실적발표일')
                    const cellClassName = value === '-'
                      ? 'dash-cell'
                      : isEntryStrategy
                        ? 'strategy-data-cell technical-strategy-cell'
                        : `number-cell ${isEarningsDate ? 'earnings-date-cell' : ''}`.trim()

                    return (
                      <td className={cellClassName} key={column.label}>
                        {isEntryStrategy && entryStrategies.length > 0 ? entryStrategies.map((strategy, strategyIndex) => (
                          <StrategyTag
                            key={`${strategy}-${strategyIndex}`}
                            onTooltipClose={onTooltipClose}
                            onTooltipOpen={onTooltipOpen}
                            strategy={strategy}
                          />
                        )) : value}
                      </td>
                    )
                  })}
                </tr>
                )
              })}
              {Array.from({ length: blankRowCount }).map((_, index) => (
                <tr className="blank-row" key={`technical-analysis-blank-${index}`}>
                  {Array.from({ length: 3 + technicalMetricColumns.length }).map((__, cellIndex) => (
                    <td key={`technical-analysis-blank-${index}-${cellIndex}`}>&nbsp;</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function parseMarketEventDate(date: string) {
  const match = date.match(/^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})$/)
  if (!match) return null

  const [, year, month, day] = match
  return new Date(Number(year), Number(month) - 1, Number(day))
}

function marketEventStatus(entry: MarketEventEntry) {
  const eventDate = parseMarketEventDate(entry.date)
  if (!eventDate) return 'none'

  const today = new Date()
  const todayDate = new Date(today.getFullYear(), today.getMonth(), today.getDate())

  if (eventDate.getTime() === todayDate.getTime()) return 'today'
  if (eventDate.getTime() < todayDate.getTime()) return 'past'
  return 'future'
}

function marketEventDday(entry: MarketEventEntry) {
  const eventDate = parseMarketEventDate(entry.date)
  if (!eventDate) return '-'

  const today = new Date()
  const todayDate = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const msPerDay = 24 * 60 * 60 * 1000
  const daysFromEvent = Math.round((todayDate.getTime() - eventDate.getTime()) / msPerDay)
  return daysFromEvent > 0 ? `+${daysFromEvent}` : String(daysFromEvent)
}

function normalizeMarketEventDdays(groups: MarketEventGroup[]) {
  return groups.map((group) => ({
    ...group,
    entries: group.entries.map((entry) => ({
      ...entry,
      dday: marketEventDday(entry),
      status: undefined,
    })),
  }))
}

function marketEventDateClass(entry: MarketEventEntry, isGroupStart: boolean) {
  const status = marketEventStatus(entry)
  const classes = ['event-date-cell']

  if (isGroupStart) classes.push('event-group-start')
  if (status === 'past') classes.push('event-past-cell')
  if (status === 'future' || status === 'today') classes.push('event-future-cell')

  return classes.join(' ')
}

function marketEventDdayClass(entry: MarketEventEntry) {
  return marketEventStatus(entry) === 'today' ? 'number-cell event-today-dday-cell' : 'number-cell'
}

function marketEventTimeClass(entry: MarketEventEntry) {
  return marketEventStatus(entry) === 'today' ? 'event-today-time-cell' : ''
}

function formatCurrentDateLabel(date = new Date()) {
  const parts = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    weekday: 'short',
  }).formatToParts(date)
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? ''

  return `현재 날짜: ${part('year')}년 ${part('month')}월 ${part('day')}일 (${part('weekday')}) (한국시간 기준)`
}

function marketEventDateToInputValue(date: string) {
  const match = date.match(/^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})$/)
  if (!match) return ''

  const [, year, month, day] = match
  return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`
}

function formatMarketEventDateFromInput(value: string) {
  if (!value) return '-'
  const [year, month, day] = value.split('-')
  return `${year}. ${Number(month)}. ${Number(day)}`
}

function marketTrendRowKey(row: MarketTrendRow) {
  return `${row.date}||${row.summary}`
}

function MarketEventsPage({
  groups,
  yearLabel,
  months,
  isAdmin,
  isSaving,
  isDirty,
  onTooltipOpen,
  onTooltipClose,
  onYearLabelChange,
  onMonthChange,
  onEventChange,
  onSave,
}: {
  groups: MarketEventGroup[]
  yearLabel: string
  months: string[]
  isAdmin: boolean
  isSaving: boolean
  isDirty: boolean
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
  onYearLabelChange: (value: string) => void
  onMonthChange: (monthIndex: number, value: string) => void
  onEventChange: (groupIndex: number, entryIndex: number, field: keyof MarketEventEntry, value: string) => void
  onSave: () => void
}) {
  return (
    <section className="panel value-analysis-panel market-events-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>시장 주요 이벤트</h2>
          <p>금리, 고용, 물가, 리밸런싱 등 시장 변동성을 키울 수 있는 주요 이벤트 일정을 확인합니다. 모든 날짜 및 시간은 한국 기준입니다.</p>
          <p className="page-warning">※ 이벤트 일정은 미국 정부 상황에 따라 유동적으로 달라져 간혹 맞지 않을 수 있습니다.</p>
        </div>
        <span className="section-heading-meta">{formatCurrentDateLabel()} <b>|</b> D-day 자동 계산 <b>|</b> 일정은 수동 확인</span>
      </div>
      {isAdmin && (
        <div className="admin-event-toolbar">
          <span>어드민 모드: 연도, 월, 발표일, 발표 시간을 직접 수정할 수 있습니다. D-day는 현재 날짜 기준으로 자동 계산됩니다.</span>
          {isDirty && (
            <button disabled={isSaving} type="button" onClick={onSave}>
              {isSaving ? '저장 중...' : '저장'}
            </button>
          )}
        </div>
      )}

      <div className="sheet-wrap market-events-sheet">
        <table className="sheet-table market-events-table">
          <thead>
            <tr>
              <th className="event-period-head" rowSpan={2}>시기</th>
              <th className="event-month-head" rowSpan={2}>월</th>
              {groups.map((group) => (
                <th className="event-group-header" colSpan={3} key={group.title}>
                  <MetricValue
                    tooltip={group.tooltip}
                    onTooltipClose={onTooltipClose}
                    onTooltipOpen={onTooltipOpen}
                  >
                    {group.title}
                  </MetricValue>
                </th>
              ))}
            </tr>
            <tr>
              {groups.map((group, groupIndex) => (
                <Fragment key={group.title}>
                  <th className={groupIndex > 0 ? 'event-date-head event-group-start' : 'event-date-head'}>발표일</th>
                  <th>D-day</th>
                  <th>발표 시간</th>
                </Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {months.map((month, index) => (
              <tr key={`market-event-month-${index}`}>
                {index === 0 && (
                  <td className="event-year-cell" rowSpan={months.length}>
                    {isAdmin ? (
                      <input
                        aria-label="시장 이벤트 연도"
                        className="event-edit-input event-edit-input-label"
                        value={yearLabel}
                        onChange={(event) => onYearLabelChange(event.target.value)}
                      />
                    ) : yearLabel}
                  </td>
                )}
                <td className="event-month-cell">
                  {isAdmin ? (
                    <input
                      aria-label={`${month} 표시`}
                      className="event-edit-input event-edit-input-label event-edit-input-short"
                      value={month}
                      onChange={(event) => onMonthChange(index, event.target.value)}
                    />
                  ) : month}
                </td>
                {groups.map((group, groupIndex) => {
                  const entry = group.entries[index] ?? { month, date: '-', dday: '-', time: '-' }
                  const isGroupStart = groupIndex > 0

                  return (
                    <Fragment key={`${group.title}-${index}`}>
                      <td className={marketEventDateClass(entry, isGroupStart)}>
                        {isAdmin ? (
                          <input
                            aria-label={`${group.title} ${month} 발표일`}
                            className="event-edit-input"
                            type="date"
                            value={marketEventDateToInputValue(entry.date)}
                            onChange={(event) => onEventChange(groupIndex, index, 'date', formatMarketEventDateFromInput(event.target.value))}
                          />
                        ) : entry.date}
                      </td>
                      <td className={marketEventDdayClass(entry)}>
                        {marketEventDday(entry)}
                      </td>
                      <td className={marketEventTimeClass(entry)}>
                        {isAdmin ? (
                          <input
                            aria-label={`${group.title} ${month} 발표 시간`}
                            className="event-edit-input"
                            value={entry.time}
                            onChange={(event) => onEventChange(groupIndex, index, 'time', event.target.value)}
                          />
                        ) : entry.time}
                      </td>
                    </Fragment>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function MarketTrendsPage({
  rows,
  updateLabel,
  isAdmin,
  selectedRowKeys,
  isSaving,
  onToggleRow,
  onDeleteSelected,
}: {
  rows: MarketTrendRow[]
  updateLabel: string
  isAdmin: boolean
  selectedRowKeys: string[]
  isSaving: boolean
  onToggleRow: (rowKey: string) => void
  onDeleteSelected: () => void
}) {
  const [page, setPage] = useState(1)
  const sortedMarketTrendRows = [...rows].sort((a, b) => new Date(b.date.replaceAll('.', '-')).getTime() - new Date(a.date.replaceAll('.', '-')).getTime())
  const pageSize = 50
  const totalPages = Math.max(1, Math.ceil(sortedMarketTrendRows.length / pageSize))
  const safePage = Math.min(page, totalPages)
  const pageStart = (safePage - 1) * pageSize
  const visibleMarketTrendRows = sortedMarketTrendRows.slice(pageStart, pageStart + pageSize)
  const blankRowCount = Math.max(MAX_WATCHLIST_ITEMS - visibleMarketTrendRows.length, 0)
  const selectedRowCount = selectedRowKeys.length

  return (
    <section className="panel value-analysis-panel market-trends-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>시장 트렌드</h2>
          <p>주간 시장에서 자주 언급된 핵심 테마와 섹터를 순위별로 확인합니다.</p>
        </div>
        <span className="section-heading-meta">총 {rows.length}개 <b>|</b> {updateLabel}</span>
      </div>
      {isAdmin && selectedRowCount > 0 && (
        <div className="market-trends-table-actions">
          <button
            className="remove-selected-button"
            disabled={isSaving}
            type="button"
            onClick={onDeleteSelected}
          >
            {isSaving ? '삭제 중...' : `삭제${selectedRowCount > 0 ? ` (${selectedRowCount})` : ''}`}
          </button>
        </div>
      )}

      <div className="sheet-wrap market-trends-sheet">
        <table className={`sheet-table market-trends-table ${isAdmin ? 'admin-market-trends-table' : ''}`}>
          <colgroup>
            {isAdmin && <col className="trend-select-col" />}
            <col className="trend-date-col" />
            {Array.from({ length: 10 }).map((_, index) => (
              <col className="trend-rank-col" key={`trend-rank-col-${index + 1}`} />
            ))}
            <col className="trend-summary-col" />
          </colgroup>
          <thead>
            <tr>
              {isAdmin && <th>선택</th>}
              <th className="trend-date-head">날짜</th>
              {Array.from({ length: 10 }).map((_, index) => (
                <th key={`trend-rank-${index + 1}`}>{index + 1}위</th>
              ))}
              <th>시장요약</th>
            </tr>
          </thead>
          <tbody>
            {visibleMarketTrendRows.map((row) => {
              const rowKey = marketTrendRowKey(row)
              const isSelected = selectedRowKeys.includes(rowKey)

              return (
                <tr className={isSelected ? 'selected-market-trend-row' : undefined} key={rowKey}>
                  {isAdmin && (
                    <td className="checkbox-cell">
                      <input
                        aria-label={`${row.date} 시장 트렌드 선택`}
                        checked={isSelected}
                        onChange={() => onToggleRow(rowKey)}
                        type="checkbox"
                      />
                    </td>
                  )}
                  <td className="number-cell trend-date-cell">{row.date}</td>
                  {Array.from({ length: 10 }).map((_, index) => (
                    <td className="trend-rank-cell" key={`${row.date}-${index + 1}`}>{row.ranks[index] ?? '-'}</td>
                  ))}
                  <td className="trend-summary-cell">{row.summary}</td>
                </tr>
              )
            })}
            {Array.from({ length: blankRowCount }).map((_, rowIndex) => (
              <tr className="blank-row" key={`market-trend-blank-${rowIndex}`}>
                {Array.from({ length: isAdmin ? 13 : 12 }).map((__, cellIndex) => (
                  <td key={`market-trend-blank-${rowIndex}-${cellIndex}`}>&nbsp;</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="market-trends-pagination" aria-label="시장 트렌드 페이지">
          <button disabled={safePage === 1} type="button" onClick={() => setPage((current) => Math.max(1, current - 1))}>
            이전
          </button>
          {Array.from({ length: totalPages }).map((_, index) => {
            const pageNumber = index + 1

            return (
              <button
                className={safePage === pageNumber ? 'active' : ''}
                key={`market-trends-page-${pageNumber}`}
                type="button"
                onClick={() => setPage(pageNumber)}
              >
                {pageNumber}
              </button>
            )
          })}
          <button disabled={safePage === totalPages} type="button" onClick={() => setPage((current) => Math.min(totalPages, current + 1))}>
            다음
          </button>
        </div>
      )}
    </section>
  )
}

function formatKstDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const parts = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? ''

  return `${part('year')}.${part('month')}.${part('day')} ${part('hour')}:${part('minute')}`
}

function formatBoardPostDate(value: string) {
  return formatKstDateTime(value)
}

function formatUpdateLabel(meta?: RuntimeMeta) {
  return `최근 업데이트: ${formatKstDateTime(meta?.lastSuccessfulRun ?? meta?.updatedAt)} (한국시간)`
}

function boardCurrentUserId(userSession: UserSession | null) {
  return userSession?.email ?? 'local-guest'
}

function boardCurrentUserName(userSession: UserSession | null) {
  return userSession?.name ?? '나'
}

function maskBoardAuthorName(value: string) {
  if (!value) return '**'
  return `${value.slice(0, 2)}******`
}

function normalizeApiLogTrigger(triggerName: string): ApiLogTrigger | null {
  const normalized = triggerName.toLowerCase()
  if (normalized.includes('value') || normalized.includes('valuation') || normalized.includes('fair-price')) return 'value-analysis'
  if (normalized.includes('technical') || normalized.includes('opinion') || normalized.includes('strategy')) return 'technical-analysis'
  if (normalized.includes('trend') || normalized.includes('sector') || normalized.includes('mega')) return 'market-trends'
  return null
}

function isRefreshDataLog(triggerName: string) {
  return triggerName.toLowerCase().includes('refresh-data')
}

function normalizeApiLogTask(metadata?: Record<string, unknown>): ApiLogTrigger | null {
  const task = typeof metadata?.task === 'string' ? metadata.task : ''
  if (!task) return null
  return normalizeApiLogTrigger(task)
}

function apiLogMatchesTab(log: ApiLog, tab: ApiLogTrigger) {
  if (log.metadata?.source === 'refresh-data') return false
  return normalizeApiLogTrigger(log.triggerName) === tab || normalizeApiLogTask(log.metadata) === tab
}

function apiLogTriggerLabel(log: ApiLog) {
  const task = normalizeApiLogTask(log.metadata)
  if (task) return apiLogTabs.find((tab) => tab.key === task)?.label ?? log.triggerName
  if (isRefreshDataLog(log.triggerName)) return '전체 갱신'
  const { triggerName } = log
  const normalized = normalizeApiLogTrigger(triggerName)
  return apiLogTabs.find((tab) => tab.key === normalized)?.label ?? triggerName
}

function apiLogDuration(metadata?: Record<string, unknown>) {
  const value = metadata?.durationMs ?? metadata?.duration_ms ?? metadata?.duration ?? metadata?.elapsedMs
  if (typeof value === 'number') return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}초`
  if (typeof value === 'string' && value.trim()) return value
  return '-'
}

function apiLogDetailRows(metadata?: Record<string, unknown>): ApiLogDetailRow[] {
  return Array.isArray(metadata?.rows) ? metadata.rows.filter((row): row is ApiLogDetailRow => row !== null && typeof row === 'object' && !Array.isArray(row)) : []
}

function apiLogDetailColumns(metadata?: Record<string, unknown>, rows: ApiLogDetailRow[] = apiLogDetailRows(metadata)): ApiLogDetailColumn[] {
  if (Array.isArray(metadata?.columns)) {
    const columns = metadata.columns
      .filter((column): column is ApiLogDetailColumn => column !== null && typeof column === 'object' && typeof column.key === 'string' && typeof column.label === 'string')
      .slice(0, 14)
    if (columns.length > 0) return columns
  }
  const firstRow = rows[0]
  if (!firstRow) return []
  return Object.keys(firstRow).slice(0, 10).map((key) => ({ key, label: key }))
}

function formatApiLogValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (Array.isArray(value)) return value.length > 0 ? value.join(', ') : '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function apiLogPlainText(metadata?: Record<string, unknown>) {
  if (typeof metadata?.copyText === 'string' && metadata.copyText.trim()) return metadata.copyText.trim()
  const rows = apiLogDetailRows(metadata)
  const rowTexts = rows
    .map((row) => {
      if (typeof row.logText === 'string' && row.logText.trim()) return row.logText.trim()
      if (typeof row.decision !== 'string' || !row.decision.trim()) return ''

      const title = [row.ticker, row.name, row.market, row.industry].map(formatApiLogValue).filter((value) => value !== '-').join(' | ')
      const lines = [
        `====== ${title || '기술분석 로그'} ======`,
        '[요약]',
        `  변경: ${formatApiLogValue(row.change)}`,
        `  투자의견: ${formatApiLogValue(row.opinion)}`,
        `  진입 전략: ${formatApiLogValue(row.strategy)}`,
        '[판단]',
        ...row.decision.split('\n').map((line) => `  ${line}`),
      ]

      const metrics = [
        ['현재가', row.currentPrice],
        ['RSI', row.rsi],
        ['종가%B', row.pctB],
        ['MA200', row.ma200],
        ['갱신', row.updatedAt],
      ].filter(([, value]) => formatApiLogValue(value) !== '-')

      if (metrics.length > 0) {
        lines.push('[핵심 지표]')
        metrics.forEach(([label, value]) => lines.push(`  ${label}: ${formatApiLogValue(value)}`))
      }

      return lines.join('\n')
    })
    .filter(Boolean)
  return rowTexts.length > 0 ? rowTexts.join('\n\n') : ''
}

function apiLogColumnClass(column: ApiLogDetailColumn) {
  const width = column.width ?? (
    column.key === 'decision' || column.key === 'summary' ? 'xl'
      : column.key === 'name' || column.key === 'strategy' || column.key === 'industry' || column.key === 'keywords' ? 'md'
        : column.key === 'ticker' || column.key === 'rank' || column.key === 'change' || column.key === 'rsi' || column.key === 'pctB' || column.key === 'ma200' ? 'xs'
          : 'sm'
  )
  return `admin-log-col-${width} admin-log-col-${column.key}`
}

function apiLogCopyText(log: ApiLog) {
  const plainText = apiLogPlainText(log.metadata)
  if (plainText) return plainText

  return JSON.stringify({
    createdAt: log.createdAt,
    triggerName: log.triggerName,
    status: log.status,
    message: log.message,
    actorEmail: log.actorEmail,
    metadata: log.metadata ?? {},
  }, null, 2)
}

function ApiLogMetadataDetail({
  log,
  copied,
  onCopy,
}: {
  log: ApiLog
  copied: boolean
  onCopy: () => void
}) {
  const metadata = log.metadata
  if (!metadata || Object.keys(metadata).length === 0) {
    return (
      <div className="admin-log-detail-empty">
        기록된 세부 정보가 없습니다.
        <button className="admin-log-copy-button" type="button" onClick={onCopy}>{copied ? '복사됨' : '로그 전체 복사'}</button>
      </div>
    )
  }

  const rows = apiLogDetailRows(metadata)
  const columns = apiLogDetailColumns(metadata, rows)
  const plainText = apiLogPlainText(metadata)
  const summary = typeof metadata.summary === 'string' ? metadata.summary : ''
  const actionUrl = typeof metadata.actionsUrl === 'string' ? metadata.actionsUrl : ''

  return (
    <div className="admin-log-detail-panel">
      <div className="admin-log-detail-meta">
        {summary && <span>{summary}</span>}
        {typeof metadata.total === 'number' && <span>총 {metadata.total}개</span>}
        {actionUrl && <a href={actionUrl} rel="noreferrer" target="_blank">GitHub Actions 보기</a>}
        <button className="admin-log-copy-button" type="button" onClick={onCopy}>{copied ? '복사됨' : '로그 전체 복사'}</button>
      </div>

      {plainText ? (
        <pre className="admin-log-pretty-text">{plainText}</pre>
      ) : rows.length > 0 && columns.length > 0 ? (
        <div className="admin-log-detail-table-wrap">
          <table className="admin-log-detail-table">
            <thead>
              <tr>
                {columns.map((column) => <th className={apiLogColumnClass(column)} key={column.key}>{column.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`api-log-detail-${rowIndex}`}>
                  {columns.map((column) => <td className={apiLogColumnClass(column)} key={column.key}>{formatApiLogValue(row[column.key])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <pre>{JSON.stringify(metadata, null, 2)}</pre>
      )}
    </div>
  )
}

function AdminLogsPage({
  logs,
  isLoading,
  onRefresh,
}: {
  logs: ApiLog[]
  isLoading: boolean
  onRefresh: () => void
}) {
  const [activeLogTab, setActiveLogTab] = useState<ApiLogTrigger>('value-analysis')
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null)
  const [adminLogPage, setAdminLogPage] = useState(1)
  const [copiedLogId, setCopiedLogId] = useState<string | null>(null)
  const activeTab = apiLogTabs.find((tab) => tab.key === activeLogTab) ?? apiLogTabs[0]
  const filteredLogs = logs.filter((log) => apiLogMatchesTab(log, activeLogTab))
  const totalLogPages = Math.max(1, Math.ceil(filteredLogs.length / ADMIN_LOGS_PAGE_SIZE))
  const currentLogPage = Math.min(adminLogPage, totalLogPages)
  const pagedLogs = filteredLogs.slice((currentLogPage - 1) * ADMIN_LOGS_PAGE_SIZE, currentLogPage * ADMIN_LOGS_PAGE_SIZE)

  const copyLog = async (log: ApiLog) => {
    await navigator.clipboard.writeText(apiLogCopyText(log))
    setCopiedLogId(log.id)
    window.setTimeout(() => setCopiedLogId((current) => current === log.id ? null : current), 1600)
  }

  return (
    <section className="panel board-panel admin-logs-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>운영 로그</h2>
          <p>자동 업데이트 작업을 구분해서 보고, 실패한 실행은 행을 눌러 세부 로그를 확인합니다.</p>
        </div>
        <button className="refresh-data-button" disabled={isLoading} type="button" onClick={onRefresh}>
          {isLoading ? '불러오는 중' : '새로고침'}
        </button>
      </div>

      <div className="admin-log-tabs" aria-label="운영 로그 종류">
        {apiLogTabs.map((tab) => {
          const tabLogs = logs.filter((log) => apiLogMatchesTab(log, tab.key))
          const hasFailure = tabLogs.some((log) => log.status === 'failure')
          return (
            <button
              className={`${activeLogTab === tab.key ? 'active' : ''} ${hasFailure ? 'has-failure' : ''}`}
              key={tab.key}
              type="button"
              onClick={() => {
                setActiveLogTab(tab.key)
                setExpandedLogId(null)
                setCopiedLogId(null)
                setAdminLogPage(1)
              }}
            >
              <span>{tab.label}</span>
              <small>{tabLogs.length}회</small>
            </button>
          )
        })}
      </div>

      <div className="admin-log-context">
        <strong>{activeTab.label}</strong>
        <span>{activeTab.description}</span>
      </div>

      <div className={`sheet-wrap admin-logs-sheet ${filteredLogs.length === 0 ? 'admin-logs-sheet-empty' : ''}`}>
        {filteredLogs.length === 0 ? (
          <div className="board-empty-state admin-log-empty-state">
            <strong>아직 이 작업의 실행 로그가 없습니다.</strong>
            <span>자동 업데이트 스크립트에서 <code>{activeLogTab}</code> 이름으로 기록되면 시간순으로 쌓입니다.</span>
          </div>
        ) : (
          <table className="sheet-table admin-logs-table">
            <thead>
              <tr>
                <th>시작 시간</th>
                <th>작업</th>
                <th>기간</th>
                <th>상태</th>
                <th>요약</th>
              </tr>
            </thead>
            <tbody>
              {pagedLogs.map((log) => {
                const isExpanded = expandedLogId === log.id
                return (
                  <Fragment key={log.id}>
                    <tr className="admin-log-row" onClick={() => setExpandedLogId(isExpanded ? null : log.id)}>
                      <td>{formatBoardPostDate(log.createdAt)}</td>
                      <td>{apiLogTriggerLabel(log)}</td>
                      <td>{apiLogDuration(log.metadata)}</td>
                      <td><span className={`status-badge ${log.status === 'success' ? 'positive' : 'negative'}`}>{log.status === 'success' ? '완료' : '실패'}</span></td>
                      <td className="admin-log-message-cell">
                        <button type="button" onClick={(event) => { event.stopPropagation(); setExpandedLogId(isExpanded ? null : log.id) }}>
                          {log.message || '세부 로그 보기'}
                        </button>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="admin-log-detail-row">
                        <td colSpan={5}>
                          <ApiLogMetadataDetail
                            copied={copiedLogId === log.id}
                            log={log}
                            onCopy={() => void copyLog(log)}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      {filteredLogs.length > ADMIN_LOGS_PAGE_SIZE && (
        <div className="admin-log-pagination">
          <span>{filteredLogs.length}개 중 {(currentLogPage - 1) * ADMIN_LOGS_PAGE_SIZE + 1}-{Math.min(currentLogPage * ADMIN_LOGS_PAGE_SIZE, filteredLogs.length)}개 표시</span>
          <div>
            <button disabled={currentLogPage <= 1} type="button" onClick={() => setAdminLogPage((page) => Math.max(1, page - 1))}>이전</button>
            <strong>{currentLogPage} / {totalLogPages}</strong>
            <button disabled={currentLogPage >= totalLogPages} type="button" onClick={() => setAdminLogPage((page) => Math.min(totalLogPages, page + 1))}>다음</button>
          </div>
        </div>
      )}
    </section>
  )
}

function BoardPage({
  posts,
  category,
  content,
  commentDrafts,
  filter,
  currentUserId,
  page,
  showMineOnly,
  sortDirection,
  onCategoryChange,
  onCommentChange,
  onContentChange,
  onDeletePost,
  onFilterChange,
  onHideSelectedPosts,
  onPageChange,
  onRemoveSelectedPosts,
  onSelectedPostIdsChange,
  onShowMineOnlyChange,
  onSortDirectionChange,
  onSubmit,
  onSubmitComment,
  selectedPostIds,
}: {
  posts: BoardPost[]
  category: BoardCategory
  content: string
  commentDrafts: Record<string, string>
  filter: BoardFilter
  currentUserId: string
  page: number
  showMineOnly: boolean
  sortDirection: BoardSortDirection
  selectedPostIds: string[]
  onCategoryChange: (category: BoardCategory) => void
  onCommentChange: (postId: string, content: string) => void
  onContentChange: (content: string) => void
  onDeletePost: (postId: string) => void
  onFilterChange: (filter: BoardFilter) => void
  onHideSelectedPosts: () => void
  onPageChange: (page: number) => void
  onRemoveSelectedPosts: () => void
  onSelectedPostIdsChange: (postIds: string[]) => void
  onShowMineOnlyChange: (showMineOnly: boolean) => void
  onSortDirectionChange: (direction: BoardSortDirection) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onSubmitComment: (event: FormEvent<HTMLFormElement>, post: BoardPost) => void
}) {
  const postsPerPage = 10
  const filteredPosts = posts
    .filter((post) => !post.hidden)
    .filter((post) => filter === '전체' || post.category === filter)
    .filter((post) => !showMineOnly || post.authorId === currentUserId)
    .sort((a, b) => {
      const diff = new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      return sortDirection === 'asc' ? diff : -diff
    })
  const totalPages = Math.max(1, Math.ceil(filteredPosts.length / postsPerPage))
  const safePage = Math.min(page, totalPages)
  const pageStart = (safePage - 1) * postsPerPage
  const paginatedPosts = filteredPosts.slice(pageStart, pageStart + postsPerPage)
  const selectedPostCount = selectedPostIds.length

  const toggleSelectedPost = (postId: string) => {
    onSelectedPostIdsChange(
      selectedPostIds.includes(postId)
        ? selectedPostIds.filter((selectedPostId) => selectedPostId !== postId)
        : [...selectedPostIds, postId],
    )
  }

  return (
    <section className="panel board-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>게시판</h2>
          <p>서비스에 대한 칭찬, 버그, 건의, 기타 의견을 간편하게 남길 수 있습니다.</p>
        </div>
        <span>총 {filteredPosts.length}개</span>
      </div>

      <div className="board-layout">
        <section className="board-feed" aria-label="올라온 게시글 목록">
          <div className="board-feed-header">
            <div>
              <h3>올라온 게시글 목록</h3>
              <span>총 {filteredPosts.length}개</span>
            </div>
            <div className="board-feed-actions">
              <button
                className="sort-button board-sort-button"
                type="button"
                onClick={() => {
                  onSortDirectionChange(sortDirection === 'desc' ? 'asc' : 'desc')
                  onPageChange(1)
                }}
              >
                날짜 정렬
                <span aria-hidden="true">{sortDirection === 'desc' ? '↓' : '↑'}</span>
              </button>
            </div>
          </div>

          <div className="board-filter-group" aria-label="게시글 카테고리 필터">
            {boardFilters.map((option) => (
              <button
                className={filter === option ? 'active' : ''}
                key={option}
                type="button"
                onClick={() => {
                  onFilterChange(option)
                  onSelectedPostIdsChange([])
                  onPageChange(1)
                }}
              >
                {option}
              </button>
            ))}
            <button
              className={`board-filter-mine ${showMineOnly ? 'active' : ''}`}
              type="button"
              onClick={() => {
                onShowMineOnlyChange(!showMineOnly)
                onSelectedPostIdsChange([])
                onPageChange(1)
              }}
            >
              내 글만 보기
            </button>
            {selectedPostCount > 0 && (
              <div className="board-admin-actions">
                <span>{selectedPostCount}개 선택</span>
                <button type="button" onClick={onHideSelectedPosts}>숨김</button>
                <button className="danger" type="button" onClick={onRemoveSelectedPosts}>제거</button>
              </div>
            )}
          </div>

          <div className="board-post-list">
            {paginatedPosts.length > 0 ? paginatedPosts.map((post) => (
              <article className={`board-post-card ${post.authorId === currentUserId ? 'my-board-post' : ''} ${selectedPostIds.includes(post.id) ? 'selected-board-post' : ''}`} key={post.id}>
                <div className="board-post-meta">
                  <div className="board-post-meta-left">
                    <label className="board-post-select">
                      <input
                        aria-label={`${post.category} 게시글 선택`}
                        checked={selectedPostIds.includes(post.id)}
                        type="checkbox"
                        onChange={() => toggleSelectedPost(post.id)}
                      />
                    </label>
                    <span className={`board-category-pill category-${post.category}`}>{post.category}</span>
                    {post.authorId === currentUserId && <span className="my-post-badge">내 글</span>}
                    <span>{maskBoardAuthorName(post.authorName)}</span>
                    <span className="board-comment-count">댓글 {post.comments.length}</span>
                  </div>
                  <div className="board-post-meta-right">
                    <time dateTime={post.createdAt}>{formatBoardPostDate(post.createdAt)}</time>
                    {post.authorId === currentUserId && (
                      <button type="button" onClick={() => onDeletePost(post.id)}>삭제</button>
                    )}
                  </div>
                </div>
                <p>{post.content}</p>
                <div className="board-comment-panel">
                  {post.comments.length > 0 ? (
                    <div className="board-comment-list">
                      {post.comments.map((comment) => (
                        <div className={`board-comment ${comment.authorId === currentUserId ? 'my-board-comment' : ''}`} key={comment.id}>
                          <div className="board-comment-meta">
                            <strong>{maskBoardAuthorName(comment.authorName)}</strong>
                            <time dateTime={comment.createdAt}>{formatBoardPostDate(comment.createdAt)}</time>
                          </div>
                          <span>{comment.content}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="board-comment-empty">첫 댓글을 남겨 대화를 이어가 보세요.</div>
                  )}
                  <form className="board-comment-form" onSubmit={(event) => onSubmitComment(event, post)}>
                    <textarea
                      maxLength={MAX_BOARD_COMMENT_LENGTH}
                      placeholder={post.comments.length >= MAX_BOARD_COMMENTS_PER_POST ? '댓글 한도에 도달했습니다.' : '댓글을 입력하세요.'}
                      rows={2}
                      value={commentDrafts[post.id] ?? ''}
                      onChange={(event) => onCommentChange(post.id, event.target.value)}
                    />
                    <div className="board-comment-form-actions">
                      <span>{(commentDrafts[post.id] ?? '').length}/{MAX_BOARD_COMMENT_LENGTH}</span>
                      <button
                        disabled={(commentDrafts[post.id] ?? '').trim().length === 0 || post.comments.length >= MAX_BOARD_COMMENTS_PER_POST}
                        type="submit"
                      >
                        댓글
                      </button>
                    </div>
                  </form>
                </div>
              </article>
            )) : (
              <div className="board-empty-state">
                <strong>게시글이 없습니다.</strong>
                <span>선택한 카테고리의 첫 의견을 남겨 주세요.</span>
              </div>
            )}
          </div>

          {filteredPosts.length > postsPerPage && (
            <nav className="board-pagination" aria-label="게시판 페이지네이션">
              <button disabled={safePage === 1} type="button" onClick={() => onPageChange(safePage - 1)}>이전</button>
              {Array.from({ length: totalPages }).map((_, index) => {
                const pageNumber = index + 1

                return (
                  <button
                    className={safePage === pageNumber ? 'active' : ''}
                    key={pageNumber}
                    type="button"
                    onClick={() => onPageChange(pageNumber)}
                  >
                    {pageNumber}
                  </button>
                )
              })}
              <button disabled={safePage === totalPages} type="button" onClick={() => onPageChange(safePage + 1)}>다음</button>
            </nav>
          )}
        </section>

        <aside className="board-aside" aria-label="게시글 작성">
          <form className="board-composer" onSubmit={onSubmit}>
            <div className="board-composer-header">
              <h3>게시글 올리기</h3>
            </div>

            <div className="board-category-selector" aria-label="게시글 카테고리 선택">
              {boardCategories.map((option) => (
                <button
                  className={category === option ? `active category-${option}` : ''}
                  key={option}
                  type="button"
                  onClick={() => onCategoryChange(option)}
                >
                  {option}
                </button>
              ))}
            </div>

            <div className="board-chat-input">
              <textarea
                value={content}
                onChange={(event) => onContentChange(event.target.value)}
                placeholder="채팅하듯이 의견을 남겨 주세요."
                rows={6}
              />
              <button disabled={content.trim().length === 0} type="submit">올리기</button>
            </div>
          </form>
        </aside>
      </div>
    </section>
  )
}

function App() {
  const cachedAppData = useMemo(() => readCachedAppData(), [])
  const initialLocalTestSession = useMemo(() => readStoredLocalTestSession(), [])
  const initialUserSettings = useMemo(() => (
    initialLocalTestSession
      ? readStoredUserSettings(initialLocalTestSession)
      : isSupabaseConfigured
        ? readCachedRemoteUserSettings() ?? readStoredUserSettings(null)
        : readStoredUserSettings(null)
  ), [initialLocalTestSession])
  const [query, setQuery] = useState('')
  const [watchlist, setWatchlist] = useState<string[]>(() => (
    initialLocalTestSession ? resolveLocalTestWatchlist(initialLocalTestSession) : readStoredWatchlist()
  ))
  // 가치투자/스윙투자 관심종목을 유형별로 보관한다. 활성 유형의 리스트는 watchlist와 동기화되며,
  // 비활성 유형 리스트는 '상대 유형 불러오기'의 원본으로 쓰인다. (로컬 우선 프리뷰)
  const [personalWatchlistByType, setPersonalWatchlistByType] = useState<Record<InvestmentType, string[]>>(() => {
    const stored = readPersonalWatchlistByType(initialLocalTestSession)
    return {
      long_term: stored?.long_term ?? [],
      swing: stored?.swing ?? [],
    }
  })
  const [operatorWatchlist, setOperatorWatchlist] = useState<string[]>(() => isSupabaseConfigured ? readCachedRemoteOperatorWatchlist() : readStoredOperatorWatchlist())
  // 운영자 관심종목의 유형별 보관소. 활성 유형은 operatorWatchlist와 동기화되고, 비활성 유형은 불러오기 원본이 된다.
  const [operatorWatchlistByType, setOperatorWatchlistByType] = useState<Record<InvestmentType, string[]>>(() => {
    const stored = readOperatorWatchlistByType()
    return {
      long_term: stored?.long_term ?? [],
      swing: stored?.swing ?? [],
    }
  })
  // DB에서 유형별 운영자 관심종목을 한 번 복원한 뒤에만 어드민 변경분을 다시 저장하도록 게이트한다.
  const operatorWatchlistByTypeLoadedRef = useRef(false)
  const [personalTradeLogs, setPersonalTradeLogs] = useState<TradeLog[]>(() => (
    initialLocalTestSession ? resolveLocalTestPersonalTrades(initialLocalTestSession) : readStoredPersonalTradeLogs()
  ))
  const [systemTradeLogs, setSystemTradeLogs] = useState<TradeLog[]>(() => cachedAppData?.tradeLogs?.rows ?? operatorTrades)
  const [isAddingStock, setIsAddingStock] = useState(false)
  const [viewMode, setViewMode] = useState<'personal' | 'operator'>(() => readStoredViewMode())
  const [showViewModeHint, setShowViewModeHint] = useState(() => localStorage.getItem(VIEW_MODE_HINT_STORAGE_KEY) !== 'true')
  const [selectedStrategy, setSelectedStrategy] = useState('전체')
  const [sortDirection, setSortDirection] = useState<'desc' | 'asc'>('desc')
  const [activeTooltip, setActiveTooltip] = useState<TooltipState | null>(null)
  const [selectedTickers, setSelectedTickers] = useState<string[]>([])
  const [selectedHoldingTradeKeys, setSelectedHoldingTradeKeys] = useState<string[]>([])
  const [isResetConfirmOpen, setIsResetConfirmOpen] = useState(false)
  const [isHoldingDeleteConfirmOpen, setIsHoldingDeleteConfirmOpen] = useState(false)
  const [isHoldingLiquidationOpen, setIsHoldingLiquidationOpen] = useState(false)
  const [holdingLiquidationDrafts, setHoldingLiquidationDrafts] = useState<HoldingLiquidationDraft[]>([])
  const [contributionSettings, setContributionSettings] = useState<ContributionSettings>(() => readStoredContributionSettings(initialLocalTestSession))
  const [contributionDraft, setContributionDraft] = useState<ContributionSettingsDraft | null>(null)
  const [contributionSettingsMode, setContributionSettingsMode] = useState<ContributionSettingsMode>('cash')
  const [isLoginOpen, setIsLoginOpen] = useState(() => Boolean(authCallbackMessage() || hasNotificationSettingsDeepLink()))
  const [isAccountDeleteConfirmOpen, setIsAccountDeleteConfirmOpen] = useState(false)
  const [isDeletingAccount, setIsDeletingAccount] = useState(false)
  const [accountDeleteError, setAccountDeleteError] = useState('')
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginPasswordConfirm, setLoginPasswordConfirm] = useState('')
  const [loginError, setLoginError] = useState('')
  const [signupConfirmationEmail, setSignupConfirmationEmail] = useState('')
  const [isRecoverySent, setIsRecoverySent] = useState(false)
  const [boardPosts, setBoardPosts] = useState<BoardPost[]>(initialBoardPosts)
  const [boardCategory, setBoardCategory] = useState<BoardCategory>('건의')
  const [boardContent, setBoardContent] = useState('')
  const [boardCommentDrafts, setBoardCommentDrafts] = useState<Record<string, string>>({})
  const [boardFilter, setBoardFilter] = useState<BoardFilter>('전체')
  const [boardPage, setBoardPage] = useState(1)
  const [showMineOnly, setShowMineOnly] = useState(false)
  const [boardSortDirection, setBoardSortDirection] = useState<BoardSortDirection>('desc')
  const [selectedBoardPostIds, setSelectedBoardPostIds] = useState<string[]>([])
  const [pendingBoardDeleteIds, setPendingBoardDeleteIds] = useState<string[]>([])
  const [userSession, setUserSession] = useState<UserSession | null>(initialLocalTestSession)
  const [canUseAccountSwitch, setCanUseAccountSwitch] = useState(Boolean(initialLocalTestSession))
  const [authInfoMessage, setAuthInfoMessage] = useState(() => authCallbackMessage() || notificationSettingsDeepLinkMessage())
  const [isRemoteDataReady, setIsRemoteDataReady] = useState(!isSupabaseConfigured)
  const [apiStocks, setApiStocks] = useState<Stock[]>(() => cachedAppData?.stocks?.rows?.length ? cachedAppData.stocks.rows.map(withDisplayStockName) : searchUniverse.map(stockSearchShell))
  const [apiSearchStocks, setApiSearchStocks] = useState<Stock[]>(() => cachedAppData?.stocks?.rows?.length ? mergeStocks(cachedAppData.stocks.rows, searchUniverse) : searchUniverse.map(stockSearchShell))
  const [isStockSearchLoaded, setIsStockSearchLoaded] = useState(false)
  const [apiValuationMetrics, setApiValuationMetrics] = useState<Record<string, ValuationMetric>>(() => cachedAppData?.valuation?.rows ?? {})
  const [apiTechnicalRows, setApiTechnicalRows] = useState<Record<string, Record<string, string>>>(() => cachedAppData?.technical?.rows ?? {})
  const [apiMarketSnapshot, setApiMarketSnapshot] = useState<string[][]>(() => cachedAppData?.technical?.marketSnapshot && isMeaningfulMarketSnapshot(cachedAppData.technical.marketSnapshot) ? mergeMarketSnapshot(cachedAppData.technical.marketSnapshot) : technicalMarketSnapshot)
  const [apiMarketEventGroups, setApiMarketEventGroups] = useState<MarketEventGroup[]>(() => cachedAppData?.marketEvents?.groups?.length ? cachedAppData.marketEvents.groups : marketEventGroups)
  const [marketEventYearLabel, setMarketEventYearLabel] = useState(() => cachedAppData?.marketEvents?.yearLabel ?? '2026년')
  const [marketEventMonths, setMarketEventMonths] = useState(() => cachedAppData?.marketEvents?.months?.length ? cachedAppData.marketEvents.months : eventMonths)
  const [apiMarketTrendRows, setApiMarketTrendRows] = useState<MarketTrendRow[]>(() => cachedAppData?.marketTrends?.rows ?? [])
  const [apiMetas, setApiMetas] = useState(() => ({
    stocks: cachedAppData?.stocks?.meta,
    valuation: cachedAppData?.valuation?.meta,
    technical: cachedAppData?.technical?.meta,
    marketEvents: cachedAppData?.marketEvents?.meta,
    marketTrends: cachedAppData?.marketTrends?.meta,
    tradeLogs: cachedAppData?.tradeLogs?.meta,
  }))
  const [marketEventsMeta, setMarketEventsMeta] = useState<RuntimeMeta | undefined>()
  const [isSavingMarketEvents, setIsSavingMarketEvents] = useState(false)
  const [isMarketEventsDirty, setIsMarketEventsDirty] = useState(false)
  const [selectedMarketTrendRowKeys, setSelectedMarketTrendRowKeys] = useState<string[]>([])
  const [pendingMarketTrendDeleteKeys, setPendingMarketTrendDeleteKeys] = useState<string[]>([])
  const [isSavingMarketTrends, setIsSavingMarketTrends] = useState(false)
  const [isSavingTradeLogs, setIsSavingTradeLogs] = useState(false)
  const [isRefreshingData, setIsRefreshingData] = useState(false)
  const [refreshDataMessage, setRefreshDataMessage] = useState('')
  const [watchlistSortSettings, setWatchlistSortSettings] = useState<WatchlistSortSettings>(() => initialUserSettings.watchlistSort)
  const [notificationPreferences, setNotificationPreferences] = useState<NotificationPreferences>(() => initialUserSettings.notificationPreferences)
  const [connectingNotificationChannel, setConnectingNotificationChannel] = useState<NotificationIntegrationChannel | null>(null)
  const [investmentType, setInvestmentType] = useState<InvestmentType | null>(() => initialUserSettings.investmentType)
  const [onboardingInvestmentType, setOnboardingInvestmentType] = useState<InvestmentType>(DEFAULT_INVESTMENT_TYPE)
  const [isWatchlistSortOpen, setIsWatchlistSortOpen] = useState(false)
  const [isOperatorImportOpen, setIsOperatorImportOpen] = useState(false)
  const [operatorImportTickers, setOperatorImportTickers] = useState<string[]>([])
  const [isWatchlistTypeImportOpen, setIsWatchlistTypeImportOpen] = useState(false)
  const [watchlistTypeImportTickers, setWatchlistTypeImportTickers] = useState<string[]>([])
  const [apiLogs, setApiLogs] = useState<ApiLog[]>(() => readStoredApiLogs())
  const [isLoadingApiLogs, setIsLoadingApiLogs] = useState(false)
  const [activePage, setActivePage] = useState<ActivePage>(() => readInitialActivePage())
  const [isTradingPinned, setIsTradingPinned] = useState(false)
  const [isWatchlistPinned, setIsWatchlistPinned] = useState(false)
  const [isHoldingPinned, setIsHoldingPinned] = useState(false)
  const [homePinnedStyles, setHomePinnedStyles] = useState<{ trading?: CSSProperties; watchlist?: CSSProperties; holding?: CSSProperties }>({})
  const addStockButtonRef = useRef<HTMLButtonElement | null>(null)
  const inlineAddRef = useRef<HTMLDivElement | null>(null)
  const watchlistSortMenuRef = useRef<HTMLDivElement | null>(null)
  const tradingLogScrollRef = useRef<HTMLDivElement | null>(null)
  const watchlistSheetRef = useRef<HTMLDivElement | null>(null)
  const holdingSheetRef = useRef<HTMLDivElement | null>(null)
  // 기존 스크롤 ref를 유지하면서 비-passive wheel 리스너를 함께 붙인다.
  const tradingLogWheelRef = useEdgeScrollWheelRef(tradingLogScrollRef)
  const watchlistSheetWheelRef = useEdgeScrollWheelRef(watchlistSheetRef)
  const holdingSheetWheelRef = useEdgeScrollWheelRef(holdingSheetRef)
  const apiMetasRef = useRef<AppDataMetas>(apiMetas)
  const resetSyncGenerationRef = useRef(0)

  const resetHomeSheetScroll = () => {
    const reset = () => {
      for (const sheet of [tradingLogScrollRef.current, watchlistSheetRef.current, holdingSheetRef.current]) {
        if (sheet) sheet.scrollLeft = 0
      }
    }

    reset()
    window.requestAnimationFrame(reset)
    window.setTimeout(reset, 80)
  }

  const homeSheetFor = (type: 'trading' | 'watchlist' | 'holding') => (
    type === 'trading'
      ? tradingLogScrollRef.current
      : type === 'watchlist'
        ? watchlistSheetRef.current
        : holdingSheetRef.current
  )

  const homePinnedStyleFor = (sheet: HTMLDivElement | null, type: 'trading' | 'watchlist' | 'holding') => {
    if (typeof window !== 'undefined' && window.innerWidth <= 760) {
      return {} as CSSProperties
    }

    const table = sheet?.querySelector<HTMLTableElement>('table')
    const headers = Array.from(table?.querySelectorAll<HTMLTableCellElement>('thead th') ?? [])
    const width = (index: number, fallback: number) => Math.ceil(headers[index]?.getBoundingClientRect().width || fallback)
    const isEditable = table?.classList.contains('editable-home-table') ?? true
    const noIndex = type === 'trading' ? 0 : isEditable ? 1 : 0
    const nameIndex = type === 'trading' ? 1 : type === 'watchlist' || type === 'holding' ? (isEditable ? 2 : 1) : (isEditable ? 3 : 2)
    const selectWidth = type === 'trading' ? 0 : isEditable ? width(0, 40) : 0
    const noWidth = width(noIndex, 48)
    const nameWidth = width(nameIndex, 220)
    const vars: Record<string, string> = {
      '--home-select-width': `${selectWidth}px`,
      '--home-no-left': `${selectWidth}px`,
      '--home-no-width': `${noWidth}px`,
      '--home-name-left': `${selectWidth + noWidth}px`,
      '--home-name-width': `${nameWidth}px`,
    }

    return vars as CSSProperties
  }

  const refreshHomePinnedStyle = (type: 'trading' | 'watchlist' | 'holding') => {
    if (typeof window !== 'undefined' && window.innerWidth <= 760) return

    const style = homePinnedStyleFor(homeSheetFor(type), type)
    setHomePinnedStyles((current) => ({ ...current, [type]: style }))
  }

  const toggleTradingPinned = () => {
    if (!isTradingPinned && window.innerWidth > 760) refreshHomePinnedStyle('trading')
    setIsTradingPinned((current) => !current)
  }

  const toggleWatchlistPinned = () => {
    if (!isWatchlistPinned && window.innerWidth > 760) refreshHomePinnedStyle('watchlist')
    setIsWatchlistPinned((current) => !current)
  }

  const toggleHoldingPinned = () => {
    if (!isHoldingPinned && window.innerWidth > 760) refreshHomePinnedStyle('holding')
    setIsHoldingPinned((current) => !current)
  }

  const applyLoadedData = (data: GssgAppData) => {
    storeCachedAppData(data)
    setApiMetas({
      stocks: data.stocks?.meta,
      valuation: data.valuation?.meta,
      technical: data.technical?.meta,
      marketEvents: data.marketEvents?.meta,
      marketTrends: data.marketTrends?.meta,
      tradeLogs: data.tradeLogs?.meta,
    })
    if (data.stocks?.rows && data.stocks.rows.length > 0) {
      const stocks = data.stocks.rows.map(withDisplayStockName)
      setApiStocks(stocks)
      setApiSearchStocks((currentStocks) => mergeStocks(stocks, currentStocks))
    }
    if (data.valuation?.rows) {
      setApiValuationMetrics(data.valuation.rows)
    }
    if (data.technical?.rows) {
      setApiTechnicalRows(data.technical.rows)
    }
    if (data.technical?.marketSnapshot && isMeaningfulMarketSnapshot(data.technical.marketSnapshot)) {
      setApiMarketSnapshot(mergeMarketSnapshot(data.technical.marketSnapshot))
    }
    if (data.marketEvents?.groups && data.marketEvents.groups.length > 0) {
      setApiMarketEventGroups(data.marketEvents.groups)
    }
    if (data.marketEvents?.yearLabel) {
      setMarketEventYearLabel(data.marketEvents.yearLabel)
    }
    if (data.marketEvents?.months && data.marketEvents.months.length > 0) {
      setMarketEventMonths(data.marketEvents.months)
    }
    if (data.marketEvents?.meta) {
      setMarketEventsMeta(data.marketEvents.meta)
    }
    if (data.marketTrends?.rows) {
      setApiMarketTrendRows(data.marketTrends.rows)
    }
    if (data.tradeLogs?.rows) {
      setSystemTradeLogs(data.tradeLogs.rows)
    }
  }

  useEffect(() => {
    apiMetasRef.current = apiMetas
  }, [apiMetas])

  async function ensureProfile(session: UserSession) {
    if (!supabase) return

    await supabase
      .from('profiles')
      .upsert({
        id: session.id,
        email: session.email,
        name: session.name,
      })

    try {
      await supabase
        .from('user_settings')
        .upsert({ owner_id: session.id })
    } catch {
      // The follow-up migration may not be applied in older live environments yet.
    }
  }

  async function loadUserSettings(session: UserSession | null) {
    if (!session || !supabase) return readStoredUserSettings(session)

    const storedSettings = readStoredUserSettings(session)
    const { data, error } = await supabase
      .from('user_settings')
      .select('watchlist_sort, notification_preferences, investment_type')
      .eq('owner_id', session.id)
      .maybeSingle()

    if (error) {
      const fallback = await supabase
        .from('user_settings')
        .select('watchlist_sort, notification_preferences')
        .eq('owner_id', session.id)
        .maybeSingle()

      if (fallback.error) return storedSettings
      const nextSettings = {
        watchlistSort: normalizeWatchlistSortSettings(fallback.data?.watchlist_sort),
        notificationPreferences: normalizeNotificationPreferences(fallback.data?.notification_preferences),
        investmentType: storedSettings.investmentType,
      }
      storeUserSettings(session, nextSettings.watchlistSort, nextSettings.notificationPreferences, nextSettings.investmentType)
      storeCachedRemoteUserSettings(nextSettings)
      return nextSettings
    }

    const nextSettings = {
      watchlistSort: normalizeWatchlistSortSettings(data?.watchlist_sort),
      notificationPreferences: normalizeNotificationPreferences(data?.notification_preferences),
      investmentType: normalizeInvestmentType(data?.investment_type),
    }
    storeUserSettings(session, nextSettings.watchlistSort, nextSettings.notificationPreferences, nextSettings.investmentType)
    storeCachedRemoteUserSettings(nextSettings)
    return nextSettings
  }

  async function persistUserSettings(
    watchlistSort: WatchlistSortSettings,
    notificationPreferences: NotificationPreferences,
    nextInvestmentType = investmentType,
    session = userSession,
  ) {
    const nextSettings = { watchlistSort, notificationPreferences, investmentType: nextInvestmentType }
    storeUserSettings(session, watchlistSort, notificationPreferences, nextInvestmentType)
    if (!supabase || !session) return

    try {
      const { error } = await supabase
        .from('user_settings')
        .upsert({
          owner_id: session.id,
          watchlist_sort: watchlistSort,
          notification_preferences: notificationPreferences,
          investment_type: nextInvestmentType,
        })
      if (!error) {
        storeCachedRemoteUserSettings(nextSettings)
        setAuthInfoMessage('')
        return
      }

      const fallback = await supabase
        .from('user_settings')
        .upsert({
          owner_id: session.id,
          watchlist_sort: watchlistSort,
          notification_preferences: notificationPreferences,
        })
      if (fallback.error) throw fallback.error
      storeCachedRemoteUserSettings(nextSettings)
      setAuthInfoMessage('')
    } catch {
      setAuthInfoMessage('알림 설정을 서버에 저장하지 못했습니다.\n화면의 선택값과 실제 자동 알림 설정이 다를 수 있으니 잠시 후 다시 저장해 주세요.')
    }
  }

  async function loadPortfolioState(session: UserSession | null): Promise<StoredPortfolioState> {
    const localTrades = readStoredPersonalTradeLogs(session)
    const localContributionSettings = readStoredContributionSettings(session)
    const localState: StoredPortfolioState = {
      personalTradeLogs: localTrades,
      contributionSettings: localContributionSettings,
      initialized: hasStoredPersonalTradeLogs(session) || hasStoredContributionSettings(session),
    }

    if (!session || !supabase) return localState

    try {
      const { data, error } = await supabase
        .from('user_settings')
        .select('personal_trade_logs, contribution_settings, portfolio_state_initialized')
        .eq('owner_id', session.id)
        .maybeSingle()

      if (error) return localState

      const remoteInitialized = Boolean(data?.portfolio_state_initialized)
      const remoteTrades = Array.isArray(data?.personal_trade_logs)
        ? data.personal_trade_logs.map(normalizeTradeLog).filter((trade): trade is TradeLog => Boolean(trade))
        : []
      const remoteContributionSettings = data?.contribution_settings && typeof data.contribution_settings === 'object'
        ? normalizeContributionSettings(data.contribution_settings)
        : DEFAULT_CONTRIBUTION_SETTINGS

      if (!remoteInitialized && localState.initialized) {
        await persistPortfolioState(localState.personalTradeLogs, localState.contributionSettings, session)
        return { ...localState, initialized: true }
      }

      const remoteState = {
        personalTradeLogs: remoteInitialized ? remoteTrades : localTrades,
        contributionSettings: remoteInitialized ? remoteContributionSettings : localContributionSettings,
        initialized: remoteInitialized,
      }
      storePersonalTradeLogs(session, remoteState.personalTradeLogs)
      storeContributionSettings(session, remoteState.contributionSettings)
      return remoteState
    } catch {
      return localState
    }
  }

  async function persistPortfolioState(
    trades = personalTradeLogs,
    settings = contributionSettings,
    session = userSession,
  ) {
    storePersonalTradeLogs(session, trades)
    storeContributionSettings(session, settings)
    if (!supabase || !session) return

    try {
      await supabase
        .from('user_settings')
        .upsert({
          owner_id: session.id,
          personal_trade_logs: trades,
          contribution_settings: settings,
          portfolio_state_initialized: true,
        })
    } catch {
      // Local storage remains the offline fallback if the remote schema is not applied yet.
    }
  }

  async function loadApiLogs() {
    if (!userSession || !isConfiguredAdminEmail(userSession.email)) return
    setIsLoadingApiLogs(true)
    const cutoff = new Date(Date.now() - 21 * 24 * 60 * 60 * 1000).toISOString()
    try {
      if (!supabase) {
        const logs = readStoredApiLogs().filter((log) => log.createdAt >= cutoff)
        setApiLogs(logs)
        storeApiLogs(logs)
        return
      }

      await supabase.from('api_logs').delete().lt('created_at', cutoff)
      const { data, error } = await supabase
        .from('api_logs')
        .select('id, trigger_name, status, message, metadata, created_at')
        .gte('created_at', cutoff)
        .order('created_at', { ascending: false })
        .limit(200)
      if (error) throw error
      setApiLogs((data ?? []).map(mapApiLog))
    } catch {
      const logs = readStoredApiLogs().filter((log) => log.createdAt >= cutoff)
      setApiLogs(logs)
    } finally {
      setIsLoadingApiLogs(false)
    }
  }

  async function recordApiLog(triggerName: string, status: 'success' | 'failure', message: string, metadata: Record<string, unknown> = {}) {
    const nextLog: ApiLog = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      triggerName,
      status,
      message,
      metadata,
      createdAt: new Date().toISOString(),
      actorEmail: userSession?.email,
    }
    setApiLogs((current) => {
      const next = [nextLog, ...current].slice(0, 200)
      if (!supabase) storeApiLogs(next)
      return next
    })

    if (!supabase || !userSession) return
    try {
      await supabase
        .from('api_logs')
        .insert({
          actor_id: userSession.id,
          trigger_name: triggerName,
          status,
          message,
          metadata,
        })
    } catch {
      // The in-memory log is still shown to the admin for this session.
    }
  }

  const applyLocalTestSessionData = (session: UserSession) => {
    const isLocalAdmin = isConfiguredAdminEmail(session.email)
    const nextWatchlist = resolveLocalTestWatchlist(session)
    setWatchlist(nextWatchlist)
    if (!isLocalAdmin && !hasStoredWatchlist(session)) {
      localStorage.setItem(personalWatchlistStorageKey(session), JSON.stringify(nextWatchlist))
    }

    const nextPersonalTrades = resolveLocalTestPersonalTrades(session)
    setPersonalTradeLogs(nextPersonalTrades)
    if (!isLocalAdmin && !hasStoredPersonalTradeLogs(session)) {
      storePersonalTradeLogs(session, nextPersonalTrades)
    }

    const nextSettings = readStoredUserSettings(session)
    setWatchlistSortSettings(nextSettings.watchlistSort)
    if (isLocalAdmin) {
      storeOperatorWatchlistSortSettings(nextSettings.watchlistSort)
    }
    setNotificationPreferences(nextSettings.notificationPreferences)
    const nextInvestmentType = !isLocalAdmin ? nextSettings.investmentType ?? 'long_term' : nextSettings.investmentType
    setInvestmentType(nextInvestmentType)
    setContributionSettings(readStoredContributionSettings(session))
    if (!isLocalAdmin && !nextSettings.investmentType) {
      storeUserSettings(session, nextSettings.watchlistSort, nextSettings.notificationPreferences, nextInvestmentType)
    }
  }

  function logStocksForTickers(tickers: unknown) {
    const tickerSet = new Set(
      (Array.isArray(tickers) ? tickers : apiStocks.map((stock) => stock.ticker))
        .map((ticker) => String(ticker).trim().toUpperCase())
        .filter(Boolean),
    )
    return apiStocks.filter((stock) => tickerSet.has(stock.ticker.toUpperCase())).slice(0, 80)
  }

  function technicalValue(row: Record<string, string> | undefined, candidates: string[]) {
    if (!row) return '-'
    const entries = Object.entries(row)
    for (const candidate of candidates) {
      const exact = row[candidate]
      if (exact !== undefined && String(exact).trim()) return exact
      const found = entries.find(([key]) => key.toLowerCase().includes(candidate.toLowerCase()))
      if (found && String(found[1]).trim()) return found[1]
    }
    return '-'
  }

  function buildValueAnalysisLogMetadata(metadata: Record<string, unknown>) {
    const rows = logStocksForTickers(metadata.tickers).map((stock) => {
      const metric = apiValuationMetrics[stock.ticker]
      return {
        ticker: stock.ticker,
        name: stock.name,
        market: stock.market,
        industry: displayIndustryLabel(stock.industry),
        currentPrice: displayCurrentPriceText(stock),
        fairPrice: stock.fairPrice || '-',
        valuation: displayStockValuation(stock),
        opinion: displayValueAnalysisOpinion(stock),
        per: metric?.per || '-',
        epsTtm: metric?.epsTtm || '-',
        roe: metric?.roe || '-',
        updatedAt: stock.updatedAt || '-',
      }
    })
    return {
      ...metadata,
      source: 'refresh-data',
      task: 'value-analysis',
      summary: '갱신 시점의 종목별 가치분석 스냅샷입니다.',
      total: rows.length,
      columns: [
        { key: 'ticker', label: '종목' },
        { key: 'name', label: '종목명' },
        { key: 'currentPrice', label: '현재가' },
        { key: 'fairPrice', label: '적정 주가 범위' },
        { key: 'valuation', label: '판단' },
        { key: 'opinion', label: '투자의견' },
        { key: 'per', label: 'PER' },
        { key: 'epsTtm', label: 'EPS(TTM)' },
        { key: 'roe', label: 'ROE' },
        { key: 'industry', label: '산업' },
      ],
      rows,
    }
  }

  function buildTechnicalAnalysisLogMetadata(metadata: Record<string, unknown>) {
    const rows = logStocksForTickers(metadata.tickers).map((stock) => {
      const technical = apiTechnicalRows[stock.ticker]
      const decision = technical?.decisionLog || technical?.conditionSummary || '-'
      return {
        ticker: stock.ticker,
        name: stock.name,
        market: stock.market,
        industry: displayIndustryLabel(stock.industry),
        opinion: displayStockOpinion(stock),
        strategy: stock.strategies.join(', ') || technicalValue(technical, ['진입 전략']),
        decision,
        currentPrice: technicalValue(technical, ['현재가']) || displayCurrentPriceText(stock),
        rsi: technicalValue(technical, ['RSI']),
        pctB: technicalValue(technical, ['%B']),
        ma200: technicalValue(technical, ['MA200', '200일선']),
        updatedAt: stock.updatedAt || '-',
      }
    })
    return {
      ...metadata,
      source: 'refresh-data',
      task: 'technical-analysis',
      summary: '갱신 시점의 종목별 기술분석 판단 로그입니다.',
      total: rows.length,
      columns: [
        { key: 'ticker', label: '종목' },
        { key: 'name', label: '종목명' },
        { key: 'market', label: '시장' },
        { key: 'industry', label: '산업' },
        { key: 'opinion', label: '투자의견' },
        { key: 'strategy', label: '진입 전략' },
        { key: 'decision', label: '판단 로그' },
        { key: 'currentPrice', label: '현재가' },
        { key: 'rsi', label: 'RSI' },
        { key: 'pctB', label: '%B' },
        { key: 'ma200', label: 'MA200' },
        { key: 'updatedAt', label: '갱신' },
      ],
      rows,
    }
  }

  function buildMarketTrendsLogMetadata(metadata: Record<string, unknown>) {
    const rows = apiMarketTrendRows.slice(0, 12).flatMap((trend) => trend.ranks.map((rankText, index) => {
      const [sector = rankText, keywords = ''] = String(rankText).split('|').map((part) => part.trim())
      return {
        date: trend.date,
        rank: index + 1,
        sector,
        keywords,
        summary: trend.summary || '-',
      }
    }))
    return {
      ...metadata,
      source: 'refresh-data',
      task: 'market-trends',
      summary: '갱신 시점의 시장 트렌드 순위 데이터입니다.',
      total: rows.length,
      columns: [
        { key: 'date', label: '기준일' },
        { key: 'rank', label: '순위' },
        { key: 'sector', label: '섹터' },
        { key: 'keywords', label: '키워드' },
        { key: 'summary', label: '요약' },
      ],
      rows,
    }
  }

  function buildRefreshLogMetadata(tab: ApiLogTrigger, metadata: Record<string, unknown>) {
    if (tab === 'value-analysis') return buildValueAnalysisLogMetadata(metadata)
    if (tab === 'technical-analysis') return buildTechnicalAnalysisLogMetadata(metadata)
    return buildMarketTrendsLogMetadata(metadata)
  }

  async function recordRefreshDataLogs(status: 'success' | 'failure', message: string, metadata: Record<string, unknown> = {}) {
    await Promise.all(apiLogTabs.map((tab) => recordApiLog(tab.key, status, message, buildRefreshLogMetadata(tab.key, metadata))))
  }

  async function loadWatchlist(scope: 'personal' | 'operator', session: UserSession | null): Promise<LoadedWatchlist> {
    if (!supabase) {
      return {
        tickers: scope === 'operator' ? readStoredOperatorWatchlist() : readStoredWatchlist(session),
        watchlistSort: scope === 'operator' ? readOperatorWatchlistSortSettings() : null,
        updatedAt: null,
      }
    }
    const client = supabase

    const selectWatchlist = async (columns: string) => {
      let query = client
        .from('watchlists')
        .select(columns)
        .eq('scope', scope)

      query = scope === 'operator'
        ? query.is('owner_id', null)
        : query.eq('owner_id', session?.id ?? '')

      return query.maybeSingle()
    }

    const baseColumns = scope === 'operator'
      ? 'tickers, watchlist_sort, updated_at, tickers_by_type'
      : 'tickers, watchlist_sort, updated_at'
    let { data, error } = await selectWatchlist(baseColumns)
    if (error && scope === 'operator') {
      // tickers_by_type 컬럼이 없는 구버전 DB 대비 폴백.
      const retry = await selectWatchlist('tickers, watchlist_sort, updated_at')
      data = retry.data
      error = retry.error
    }
    if (error) {
      const fallback = await selectWatchlist('tickers')
      if (fallback.error) throw error
      data = fallback.data
    }
    const row = data as { tickers?: unknown, watchlist_sort?: unknown, updated_at?: unknown, tickers_by_type?: unknown } | null

    const watchlistSort = scope === 'operator'
      ? normalizeWatchlistSortSettings(row?.watchlist_sort)
      : null

    return {
      tickers: normalizeWatchlistTickers(row?.tickers),
      watchlistSort,
      updatedAt: parseRemoteUpdatedAt(row?.updated_at),
      tickersByType: scope === 'operator' ? normalizeWatchlistByType(row?.tickers_by_type) : null,
    }
  }

  async function persistWatchlist(scope: 'personal' | 'operator', tickers: string[], session = userSession): Promise<WatchlistPersistResult> {
    if (scope === 'operator') {
      storePendingOperatorWatchlist(tickers)
    } else if (session) {
      storePendingPersonalWatchlist(session, tickers)
    }

    // 로컬 테스트 세션은 원격 인증 세션이 없어 원격 저장이 항상 실패한다.
    // 다른 동기화와 동일하게 로컬 저장만 하고 성공 처리한다. (잘못된 만료 알림 방지)
    if (!supabase || isLocalTestSession(session)) {
      if (scope === 'operator') {
        storeRemoteOperatorWatchlist(tickers)
        clearPendingOperatorWatchlist()
      } else if (session) {
        localStorage.setItem(personalWatchlistStorageKey(session), JSON.stringify(tickers))
        clearPendingPersonalWatchlist(session)
      }
      return { ok: true }
    }

    if (scope === 'personal' && !session) return { ok: false, reason: 'auth' }
    const client = supabase
    const markWatchlistPersisted = () => {
      if (scope === 'operator') {
        storeRemoteOperatorWatchlist(tickers)
        clearPendingOperatorWatchlist()
        return
      }
      if (session) {
        localStorage.setItem(personalWatchlistStorageKey(session), JSON.stringify(tickers))
        clearPendingPersonalWatchlist(session)
      }
    }

    // Watchlist rows are protected by RLS: operator rows are world-readable but
    // admin-only for writes. An expired auth token therefore lets reads keep
    // showing the old list while writes silently fail, leaving local pending and
    // the server permanently out of sync. Require a valid session up front so the
    // failure surfaces (the pending change is kept and re-synced after re-login).
    const { data: sessionInfo } = await client.auth.getSession()
    if (!sessionInfo.session) {
      return { ok: false, reason: 'auth' }
    }

    const payload = scope === 'operator'
      ? { tickers, watchlist_sort: watchlistSortSettings }
      : { tickers }

    const updateWatchlist = async (nextPayload: Record<string, unknown>) => {
      let updateQuery = client
        .from('watchlists')
        .update(nextPayload)
        .eq('scope', scope)

      updateQuery = scope === 'operator'
        ? updateQuery.is('owner_id', null)
        : updateQuery.eq('owner_id', session?.id ?? '')

      return updateQuery.select('id')
    }

    try {
      let { data, error } = await updateWatchlist(payload)
      if (error && scope === 'operator') {
        const fallback = await updateWatchlist({ tickers })
        data = fallback.data
        error = fallback.error
      }
      if (error) return { ok: false, error }
      if (data && data.length > 0) {
        markWatchlistPersisted()
        return { ok: true }
      }

      const insertPayload = {
        owner_id: scope === 'operator' ? null : session?.id,
        scope,
        ...payload,
      }
      const { error: insertError } = await client
        .from('watchlists')
        .insert(insertPayload as never)
      if (!insertError) {
        markWatchlistPersisted()
        return { ok: true }
      }
      if (scope !== 'operator') return { ok: false, error: insertError }

      const { error: fallbackInsertError } = await client
        .from('watchlists')
        .insert({
          owner_id: null,
          scope,
          tickers,
        })
      if (fallbackInsertError) return { ok: false, error: fallbackInsertError }
      markWatchlistPersisted()
      return { ok: true }
    } catch (error) {
      return { ok: false, error }
    }
  }

  function notifyWatchlistPersistFailure(result: WatchlistPersistResult) {
    if (result.ok) return
    const message = result.reason === 'auth'
      ? '로그인이 만료되어 관심 종목 변경이 저장되지 않았습니다.\n다시 로그인한 뒤 시도해 주세요. (변경 내용은 보관되어 재로그인 시 자동으로 반영됩니다.)'
      : '관심 종목 변경을 저장하지 못했습니다.\n잠시 후 다시 시도해 주세요. (변경 내용은 보관되어 다음 접속 시 다시 동기화됩니다.)'
    if (typeof window !== 'undefined') window.alert(message)
  }

  async function persistOperatorWatchlistSort(watchlistSort: WatchlistSortSettings, session = userSession) {
    storeOperatorWatchlistSortSettings(watchlistSort)
    if (!supabase || !session || !isConfiguredAdminEmail(session.email)) return
    const client = supabase

    try {
      const updateQuery = client
        .from('watchlists')
        .update({ watchlist_sort: watchlistSort })
        .eq('scope', 'operator')
        .is('owner_id', null)

      const { error } = await updateQuery.select('id')
      if (error) return
    } catch {
      // Older databases without watchlist_sort still use the local fallback.
    }
  }

  // 운영자 관심종목의 유형별 전체 목록을 DB에 저장한다. 일반 계정은 이 값을 읽어 자신의 성향에 맞는 목록만 가져온다.
  async function persistOperatorWatchlistByType(map: Record<InvestmentType, string[]>, session = userSession) {
    storeOperatorWatchlistByType(map)
    if (!supabase || !session || !isConfiguredAdminEmail(session.email)) return
    const client = supabase

    try {
      const { error } = await client
        .from('watchlists')
        .update({ tickers_by_type: map })
        .eq('scope', 'operator')
        .is('owner_id', null)
        .select('id')
      if (error) return
    } catch {
      // tickers_by_type 컬럼이 없는 구버전 DB는 로컬 저장으로만 유지한다.
    }
  }

  async function loadBoardPosts() {
    if (!supabase) return

    const { data, error } = await supabase
      .from('board_posts')
      .select('id, category, content, created_at, author_id, author_name, hidden, board_comments(id, post_id, content, created_at, author_id, author_name)')
      .order('created_at', { ascending: false })
      .limit(BOARD_POST_PAGE_SIZE)

    if (error) throw error
    setBoardPosts((data ?? []).map(mapBoardPost))
  }

  async function loadServiceData(session: UserSession | null) {
    try {
      const personalTickersPromise = session ? loadWatchlist('personal', session) : Promise.resolve(null)
      const loadedSettingsPromise = loadUserSettings(session)
      const loadedPortfolioStatePromise = loadPortfolioState(session)
      void loadBoardPosts().catch(() => undefined)
      void loadedSettingsPromise.then((settings) => {
        setWatchlistSortSettings(settings.watchlistSort)
        setNotificationPreferences(settings.notificationPreferences)
        setInvestmentType(settings.investmentType)
      }).catch(() => undefined)

      const operatorTickersFromDb = await loadWatchlist('operator', session)
      const operatorDefaultSort = operatorTickersFromDb?.watchlistSort
      const resolvedOperatorWatchlist = resolveWatchlistWithPending(
        { tickers: operatorTickersFromDb?.tickers ?? null, updatedAt: operatorTickersFromDb?.updatedAt ?? null },
        readPendingOperatorWatchlist(),
      )
      setOperatorWatchlist(resolvedOperatorWatchlist.tickers)
      storeRemoteOperatorWatchlist(resolvedOperatorWatchlist.tickers)
      if (resolvedOperatorWatchlist.clearPending) {
        clearPendingOperatorWatchlist()
      } else if (resolvedOperatorWatchlist.pendingToSync && session && isConfiguredAdminEmail(session.email)) {
        void persistWatchlist('operator', resolvedOperatorWatchlist.pendingToSync, session).catch(() => undefined)
      }

      const [personalTickers, loadedSettings, loadedPortfolioState] = await Promise.all([
        personalTickersPromise,
        loadedSettingsPromise,
        loadedPortfolioStatePromise,
      ])
      const nextSortSettings = session ? loadedSettings.watchlistSort : operatorDefaultSort ?? loadedSettings.watchlistSort
      setWatchlistSortSettings(nextSortSettings)
      if (session && isConfiguredAdminEmail(session.email)) {
        await persistOperatorWatchlistSort(loadedSettings.watchlistSort, session)
      } else if (operatorDefaultSort) {
        storeOperatorWatchlistSortSettings(operatorDefaultSort)
      }
      setNotificationPreferences(loadedSettings.notificationPreferences)
      setInvestmentType(loadedSettings.investmentType)
      setContributionSettings(loadedPortfolioState.contributionSettings)
      setPersonalTradeLogs(loadedPortfolioState.personalTradeLogs)

      // 운영자 관심종목의 유형별 목록을 복원해 일반 계정의 '공수성가 가져오기'가 성향별로 분기되도록 한다.
      const operatorByTypeFromDb = operatorTickersFromDb?.tickersByType
      const cachedOperatorByType = readOperatorWatchlistByType()
      const nextOperatorByType: Record<InvestmentType, string[]> = {
        long_term: operatorByTypeFromDb?.long_term ?? cachedOperatorByType?.long_term ?? [],
        swing: operatorByTypeFromDb?.swing ?? cachedOperatorByType?.swing ?? [],
      }
      if (session && isConfiguredAdminEmail(session.email)) {
        // 어드민은 단일 tickers(=현재 활성 유형 목록)를 해당 유형의 최신 원본으로 본다.
        const adminActiveType = loadedSettings.investmentType ?? DEFAULT_INVESTMENT_TYPE
        nextOperatorByType[adminActiveType] = resolvedOperatorWatchlist.tickers
      }
      setOperatorWatchlistByType(nextOperatorByType)
      storeOperatorWatchlistByType(nextOperatorByType)
      operatorWatchlistByTypeLoadedRef.current = true
      const legacyTickers = session ? readLegacyWatchlist(session) : null
      const resolvedPersonalWatchlist = resolveWatchlistWithPending(
        { tickers: personalTickers?.tickers ?? null, updatedAt: personalTickers?.updatedAt ?? null },
        readPendingPersonalWatchlist(session),
      )
      const nextPersonalTickers = resolvedPersonalWatchlist.tickers.length > 0
        ? resolvedPersonalWatchlist.tickers
        : legacyTickers ?? initialWatchlist

      setWatchlist(session ? nextPersonalTickers : readStoredWatchlist(null))
      if (resolvedPersonalWatchlist.clearPending) {
        clearPendingPersonalWatchlist(session)
      } else if (session && resolvedPersonalWatchlist.pendingToSync) {
        void persistWatchlist('personal', resolvedPersonalWatchlist.pendingToSync, session).catch(() => undefined)
      }

      if (session && !resolvedPersonalWatchlist.pendingToSync && !personalTickers?.tickers?.length && legacyTickers) {
        await persistWatchlist('personal', legacyTickers, session)
      }
    } finally {
      setIsRemoteDataReady(true)
    }
  }

  useEffect(() => {
    let isMounted = true
    let isCheckingLatestData = false

    const loadLatestData = async (forceApply = false) => {
      if (isCheckingLatestData) return
      isCheckingLatestData = true
      try {
        const data = await fetchAppData<Stock, ValuationMetric, MarketEventGroup, MarketTrendRow, TradeLog>()
        if (!isMounted) return
        if (forceApply || appDataMetaChanged(data, apiMetasRef.current)) {
          applyLoadedData(data)
        }
      } finally {
        isCheckingLatestData = false
      }
    }

    const loadLatestDataWhenVisible = () => {
      if (document.visibilityState === 'visible') {
        void loadLatestData()
      }
    }

    void loadLatestData(true)
    const refreshInterval = window.setInterval(loadLatestDataWhenVisible, APP_DATA_AUTO_REFRESH_INTERVAL_MS)
    window.addEventListener('focus', loadLatestDataWhenVisible)
    document.addEventListener('visibilitychange', loadLatestDataWhenVisible)

    return () => {
      isMounted = false
      window.clearInterval(refreshInterval)
      window.removeEventListener('focus', loadLatestDataWhenVisible)
      document.removeEventListener('visibilitychange', loadLatestDataWhenVisible)
    }
  }, [])

  useEffect(() => {
    if (isStockSearchLoaded) return

    let isMounted = true
    fetchStockSearchData<Stock>().then((data) => {
      const rows = data?.rows ?? []
      if (!isMounted || rows.length === 0) return
      setApiSearchStocks((currentStocks) => mergeStocks(rows, currentStocks))
      setIsStockSearchLoaded(true)
    })

    return () => {
      isMounted = false
    }
  }, [isStockSearchLoaded])

  useEffect(() => {
    const normalized = normalizeQuery(query)
    if (!normalized || isStockSearchLoaded) return

    let isMounted = true
    fetchStockSearchData<Stock>().then((data) => {
      const rows = data?.rows ?? []
      if (!isMounted || rows.length === 0) return
      setApiSearchStocks((currentStocks) => mergeStocks(apiStocks, [...currentStocks, ...rows]))
      setIsStockSearchLoaded(true)
    })

    return () => {
      isMounted = false
    }
  }, [apiStocks, isStockSearchLoaded, query])

  useEffect(() => {
    if (!activeTooltip) return

    const closeTooltip = () => setActiveTooltip(null)
    const closeTooltipOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setActiveTooltip(null)
    }

    document.addEventListener('click', closeTooltip)
    document.addEventListener('keydown', closeTooltipOnEscape)
    return () => {
      document.removeEventListener('click', closeTooltip)
      document.removeEventListener('keydown', closeTooltipOnEscape)
    }
  }, [activeTooltip])

  useEffect(() => {
    let isMounted = true

    if (!supabase) {
      return () => {
        isMounted = false
      }
    }
    const authClient = supabase

    const authErrorMessage = authCallbackMessage()
    const authSuccessMessage = authCallbackSuccessMessage()
    const syncAuthUser = async (user: User | null, keepLoginModal = false) => {
      if (!isMounted) return
      if (!user) {
        const storedTestSession = readStoredLocalTestSession()
        if (storedTestSession) {
          setUserSession(storedTestSession)
          setCanUseAccountSwitch(true)
          applyLocalTestSessionData(storedTestSession)
          setIsRemoteDataReady(true)
          return
        }
        setUserSession(null)
        setCanUseAccountSwitch(false)
        setWatchlist(readStoredWatchlist(null))
        setBoardPosts([])
        await loadServiceData(null)
        return
      }

      const nextSession = sessionFromSupabaseUser(user)
      const storedTestSession = isConfiguredAdminEmail(nextSession.email)
        ? readStoredLocalTestSession({ allowProduction: true })
        : null
      const effectiveSession = storedTestSession ?? nextSession
      setUserSession(effectiveSession)
      setCanUseAccountSwitch(isConfiguredAdminEmail(nextSession.email))
      if (hasAuthCallbackPayload()) {
        if (authSuccessMessage) {
          setAuthInfoMessage(authSuccessMessage)
          setIsLoginOpen(true)
        }
        clearAuthCallbackFromUrl()
      }
      if (hasNotificationSettingsDeepLink()) {
        setIsLoginOpen(true)
        setAuthMode('login')
        setAuthInfoMessage(notificationSettingsDeepLinkMessage())
      } else if (!keepLoginModal && !authSuccessMessage) {
        setIsLoginOpen(false)
        setAuthMode('login')
      }
      localStorage.removeItem(LEGACY_AUTH_SESSION_STORAGE_KEY)
      if (!storedTestSession) {
        storeLocalTestSession(null, { allowProduction: true })
        await ensureProfile(nextSession)
        await loadServiceData(nextSession)
        return
      }
      applyLocalTestSessionData(storedTestSession)
      setIsRemoteDataReady(true)
    }

    if (authErrorMessage) {
      Promise.resolve().then(() => {
        if (!isMounted) return
        setAuthMode('login')
        setAuthInfoMessage(authErrorMessage)
        setIsLoginOpen(true)
        clearAuthCallbackErrorFromUrl()
        authClient.auth.signOut().then(() => {
          void syncAuthUser(null, true)
        })
      })
    } else {
      authClient.auth.getSession().then(({ data }) => {
        void syncAuthUser(data.session?.user ?? null)
      })
    }

    const { data: authListener } = authClient.auth.onAuthStateChange((event, session) => {
      if (event === 'PASSWORD_RECOVERY') {
        setAuthMode('reset')
        setLoginPassword('')
        setLoginPasswordConfirm('')
        setLoginError('')
        setAuthInfoMessage('')
        setIsLoginOpen(true)
      } else if (event === 'SIGNED_IN' && session?.user) {
        const successMessage = authCallbackSuccessMessage()
        if (successMessage) {
          setAuthInfoMessage(successMessage)
          setIsLoginOpen(true)
        }
        clearAuthCallbackFromUrl()
      }
      void syncAuthUser(session?.user ?? null, event === 'PASSWORD_RECOVERY')
    })

    return () => {
      isMounted = false
      authListener.subscription.unsubscribe()
    }
    // Supabase auth subscription is intentionally established once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!isAddingStock) return

    const closeInlineAddOnOutsideClick = (event: MouseEvent) => {
      const target = event.target as Node

      if (inlineAddRef.current?.contains(target) || addStockButtonRef.current?.contains(target)) {
        return
      }

      setIsAddingStock(false)
    }

    document.addEventListener('mousedown', closeInlineAddOnOutsideClick)
    return () => document.removeEventListener('mousedown', closeInlineAddOnOutsideClick)
  }, [isAddingStock])

  useEffect(() => {
    if (!isWatchlistSortOpen) return

    const closeSortOnOutsideClick = (event: MouseEvent) => {
      const target = event.target as Node
      if (watchlistSortMenuRef.current?.contains(target)) return
      setIsWatchlistSortOpen(false)
    }

    document.addEventListener('mousedown', closeSortOnOutsideClick)
    return () => document.removeEventListener('mousedown', closeSortOnOutsideClick)
  }, [isWatchlistSortOpen])

  const watchlistStocks = useMemo(
    () => watchlist
      .map((ticker) => resolveStockForTicker(ticker, apiStocks, apiSearchStocks))
      .filter((stock): stock is Stock => Boolean(stock)),
    [apiSearchStocks, apiStocks, watchlist],
  )

  const operatorFallbackTickers = useMemo(
    () => Array.from(new Set(systemTradeLogs.map((trade) => trade.ticker))).filter(Boolean),
    [systemTradeLogs],
  )
  const effectiveOperatorWatchlist = isSupabaseConfigured ? operatorWatchlist : operatorWatchlist.length > 0 ? operatorWatchlist : operatorFallbackTickers
  const operatorStocks = useMemo(
    () => effectiveOperatorWatchlist
      .map((ticker) => resolveStockForTicker(ticker, apiStocks, apiSearchStocks))
      .filter((stock): stock is Stock => Boolean(stock)),
    [apiSearchStocks, apiStocks, effectiveOperatorWatchlist],
  )

  const searchResults = useMemo(() => {
    const normalized = normalizeQuery(query)
    if (!normalized) return []

    return apiSearchStocks
      .map((stock) => ({ stock, rank: stockSearchRank(stock, normalized) }))
      .filter(({ rank }) => rank < 99)
      .sort((a, b) => a.rank - b.rank || a.stock.ticker.localeCompare(b.stock.ticker))
      .map(({ stock }) => stock)
  }, [apiSearchStocks, query])

  const trimmedLoginEmail = loginEmail.trim().toLowerCase()
  const isAdminUser = isConfiguredAdminEmail(userSession?.email)

  useEffect(() => {
    if (!isAdminUser) return undefined

    const timeoutId = window.setTimeout(() => {
      setCanUseAccountSwitch(true)
      void loadApiLogs()
    }, 0)

    return () => window.clearTimeout(timeoutId)
  }, [isAdminUser, userSession?.id])

  const effectiveViewMode = isAdminUser ? 'operator' : viewMode
  const isOperatorDataMode = effectiveViewMode === 'operator'
  const displayedInvestmentType = investmentType ?? DEFAULT_INVESTMENT_TYPE
  // Admins are forced into operator data, but the operator preview still needs profile-specific views.
  const shouldApplyInvestmentTypeView = isOperatorDataMode || !isAdminUser
  const isLongTermInvestor = shouldApplyInvestmentTypeView && displayedInvestmentType === 'long_term'
  const rawScopedTrades = isOperatorDataMode
    ? shouldApplyInvestmentTypeView
      ? systemTradeLogs.filter((trade) => !trade.investmentType || trade.investmentType === displayedInvestmentType)
      : systemTradeLogs
    : personalTradeLogs.filter((trade) => !trade.investmentType || trade.investmentType === displayedInvestmentType)
  // 가치투자는 자동 매도(청산)를 시스템상 수행하지 않는다. 공용 트레이딩 로그에서 자동 청산된 거래는
  // 보유 중으로 되돌려 보유 종목·로그·포트폴리오에서 계속 보유한 것으로 취급한다.
  // 단, 개인이 직접 청산한 거래(manualExit)는 실제 청산으로 그대로 둔다.
  const scopedTrades = isLongTermInvestor
    ? rawScopedTrades.map((trade) => (trade.status !== '보유 중' && !trade.manualExit
      ? { ...trade, status: '보유 중' as TradeStatus, sellDate: '-', sellPrice: '-', returnPct: 0, holdingDays: '-' as const }
      : trade))
    : rawScopedTrades
  const scopedOpenTrades = scopedTrades.filter((trade) => trade.status === '보유 중')
  // 가치투자는 자동 매도가 없으므로 보유 중 + 개인 수동 청산(manualExit)만 로그에 노출한다.
  const visibleProfileTrades = isLongTermInvestor
    ? scopedTrades.filter((trade) => trade.status === '보유 중' || trade.manualExit)
    : scopedTrades
  const filteredTrades = visibleProfileTrades
    .filter((trade) => selectedStrategy === '전체' || strategyCode(trade.strategy) === selectedStrategy)
    .slice()
    .sort((a, b) => {
      const aTime = new Date(a.buyDate.replaceAll('.', '-')).getTime()
      const bTime = new Date(b.buyDate.replaceAll('.', '-')).getTime()
      return sortDirection === 'desc' ? bTime - aTime : aTime - bTime
    })
  const displayedTradeRows = filteredTrades.map((trade, index) => ({
    trade,
    rowNumber: index + 1,
  }))
  const visibleWinRates = [
    formatWinRate('통합', scopedTrades),
    ...strategyFilters
      .map((code) => formatWinRate(code, scopedTrades.filter((trade) => strategyCode(trade.strategy) === code))),
  ].join(', ')
  const strategyCriteriaLine = isLongTermInvestor
    ? "장기형은 매도 신호를 제외하고 매수/관망 기준으로만 보여줍니다. 실제 청산은 '보유중인 종목' 표에서 직접 처리합니다."
    : '공통: 15거래일 +8% 미달 청산. A/B/C(+20%, -30%), D(+12%, -25%, 30일), E/F(+20% 후 MACD·5일, -30%), G(+12%, -10%, 40일)'
  const investingDays = daysFromFirstTrade(visibleProfileTrades)
  const portfolioSummary = buildPortfolioSummary(
    visibleProfileTrades,
    apiStocks,
    tradeBuyPriority,
    contributionSettings,
    displayedInvestmentType,
    userSession || isOperatorDataMode ? contributionSettings.initialCapital : 0,
  )
  const contributionDayValidationMessage = contributionDraft?.frequency === 'monthly'
    ? contributionDayMessage(contributionDraft.dayOfMonth)
    : ''
  const isContributionDayInvalid = Boolean(
    contributionDayValidationMessage
    && !contributionDayValidationMessage.includes('없는 달')
    && !contributionDayValidationMessage.includes('윤년'),
  )
  const isContributionSaveDisabled = contributionSettingsMode === 'cash' && isContributionDayInvalid
  const canEditContributionSettings = Boolean(userSession && (!isOperatorDataMode || isAdminUser))
  const canManageHoldingTrades = effectiveViewMode === 'personal' || isAdminUser
  const activeAllocation = contributionDraft?.allocationByInvestmentType[displayedInvestmentType]
  const displayedAllocationSettings = contributionSettings.allocationByInvestmentType[displayedInvestmentType]
  const displayedAllocationLabel = displayedInvestmentType === 'swing' ? '스윙 투자' : '가치 투자'
  const displayedAllocationDescription = displayedInvestmentType === 'swing'
    ? '스윙 투자는 신호가 잡힌 순서대로 제한된 슬롯에 집중 배분합니다. 매도되어 슬롯이 비면 다음 새 매수 신호에서 현금 기준 비중을 다시 계산합니다.'
    : '가치 투자는 여러 종목을 오래 가져가는 전제로 슬롯을 넓게 나눕니다. 보유 중인 신호만 집계하고, 새 매수 신호가 들어올 때 빈 슬롯 비중만큼 배정합니다.'
  const displayedAllocationSummary = allocationSummaryText(displayedAllocationSettings)
  const assetSummaryItems: Array<{
    label: string
    value: string
    action?: () => void
    clickable?: boolean
    strong?: boolean
    tone?: string
    detail?: string
    detailTooltipRows?: Array<{ label: string; value: string }>
  }> = [
    {
      label: '보유 현금',
      value: formatKrwAmount(portfolioSummary.cash),
      action: openContributionSettings,
      clickable: canEditContributionSettings,
    },
    {
      label: '평가 투자금',
      value: formatKrwAmount(portfolioSummary.openInvestmentAmount),
      action: openInvestmentAllocationSettings,
      clickable: canEditContributionSettings,
    },
    { label: '누적 매수금', value: formatKrwAmount(portfolioSummary.cumulativeInvestmentAmount) },
    {
      label: '예상 손익',
      value: `${formatKrwAmount(portfolioSummary.profitAmount)} (${portfolioSummary.profitRate >= 0 ? '+' : ''}${portfolioSummary.profitRate.toFixed(1)}%)`,
      detail: `실현 ${formatKrwAmount(portfolioSummary.realizedProfitAmount)} · 평가 ${formatKrwAmount(portfolioSummary.unrealizedProfitAmount)}`,
      detailTooltipRows: [
        { label: '실현손익', value: formatKrwAmount(portfolioSummary.realizedProfitAmount) },
        { label: '평가손익', value: formatKrwAmount(portfolioSummary.unrealizedProfitAmount) },
      ],
      tone: tradeProfitClass(portfolioSummary.profitAmount),
    },
    { label: '총 자산', value: formatKrwAmount(portfolioSummary.totalAsset), strong: true },
  ]
  const visibleGnbMenus = isAdminUser ? adminGnbMenus : gnbMenus
  const currentActivePage = !isAdminUser && (activePage === 'board' || activePage === 'admin-logs') ? 'home' : activePage
  const homeSheetResetKey = `${currentActivePage}-${effectiveViewMode}-${displayedInvestmentType}-${userSession?.id ?? 'guest'}`
  useLayoutEffect(() => {
    resetHomeSheetScroll()
  }, [currentActivePage, displayedInvestmentType, effectiveViewMode, userSession?.id])
  const isLoginEmailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedLoginEmail)
  const shouldShowEmailValidation = loginEmail.trim().length > 0 && !isLoginEmailValid
  const shouldShowPasswordValidation = loginPassword.trim().length > 0 && loginPassword.trim().length < 8
  const shouldShowPasswordConfirmValidation = (authMode === 'signup' || authMode === 'reset')
    && loginPasswordConfirm.trim().length > 0
    && loginPassword.trim() !== loginPasswordConfirm.trim()
  const isAuthSubmitDisabled = authMode === 'recover'
    ? !isLoginEmailValid || isRecoverySent
    : authMode === 'reset'
      ? loginPassword.trim().length < 8 || loginPasswordConfirm.trim().length < 8 || loginPassword.trim() !== loginPasswordConfirm.trim()
      : authMode === 'signup'
        ? !isLoginEmailValid || loginPassword.trim().length < 8 || loginPasswordConfirm.trim().length < 8 || loginPassword.trim() !== loginPasswordConfirm.trim()
        : !isLoginEmailValid || loginPassword.trim().length < 8
  const serviceStatusMessage = !isSupabaseConfigured
    ? 'Supabase 프로젝트 URL과 anon key를 .env에 입력해 주세요.'
    : !isRemoteDataReady
      ? '계정 데이터를 불러오는 중입니다.'
      : ''
  const canUseLocalAuthBypass = import.meta.env.DEV
  const shouldShowInvestmentProfileOnboarding = Boolean(userSession && !isAdminUser && !investmentType && !isLoginOpen)

  const markViewModeHintSeen = () => {
    localStorage.setItem(VIEW_MODE_HINT_STORAGE_KEY, 'true')
    setShowViewModeHint(false)
  }

  const changeViewMode = (nextViewMode: 'personal' | 'operator') => {
    if (isAdminUser && nextViewMode === 'personal') return
    localStorage.setItem(VIEW_MODE_STORAGE_KEY, nextViewMode)
    setViewMode(nextViewMode)
    setSelectedTickers([])
    setSelectedHoldingTradeKeys([])
    markViewModeHintSeen()
    resetHomeSheetScroll()
  }

  const openLoginForAddStock = () => {
    setIsAddingStock(false)
    setAuthMode('login')
    setIsRecoverySent(false)
    setLoginError('')
    setIsLoginOpen(true)
  }

  const requestAddStock = () => {
    if (!userSession) {
      openLoginForAddStock()
      return
    }

    setIsAddingStock((value) => !value)
  }

  const addToWatchlist = async (ticker: string) => {
    if (!userSession) {
      openLoginForAddStock()
      return
    }

    const targetWatchlist = isOperatorDataMode ? operatorWatchlist : watchlist
    if (targetWatchlist.length >= MAX_WATCHLIST_ITEMS) {
      setIsAddingStock(true)
      return
    }

    resetSyncGenerationRef.current += 1

    const stockToAdd = resolveStockForTicker(ticker, apiStocks, apiSearchStocks)
    if (stockToAdd) {
      setApiStocks((currentStocks) => mergeStocks(currentStocks, [stockToAdd]))
    }
    const resolvedTicker = stockToAdd?.ticker ?? ticker

    if (isOperatorDataMode) {
      const nextWatchlist = operatorWatchlist.includes(resolvedTicker)
        ? operatorWatchlist
        : [...operatorWatchlist, resolvedTicker]
      setOperatorWatchlist(nextWatchlist)
      void persistWatchlist('operator', nextWatchlist).then(notifyWatchlistPersistFailure)
    } else {
      const nextWatchlist = watchlist.includes(resolvedTicker) ? watchlist : [...watchlist, resolvedTicker]
      setWatchlist(nextWatchlist)
      void persistWatchlist('personal', nextWatchlist).then(notifyWatchlistPersistFailure)
    }
    setQuery('')
    setIsAddingStock(true)
  }

  const removeSelectedStocks = async () => {
    let result: WatchlistPersistResult
    if (isOperatorDataMode) {
      const nextWatchlist = operatorWatchlist.filter((ticker) => !selectedTickers.includes(ticker))
      setOperatorWatchlist(nextWatchlist)
      result = await persistWatchlist('operator', nextWatchlist)
    } else {
      const nextWatchlist = watchlist.filter((ticker) => !selectedTickers.includes(ticker))
      setWatchlist(nextWatchlist)
      result = await persistWatchlist('personal', nextWatchlist)
    }
    notifyWatchlistPersistFailure(result)
    setSelectedTickers([])
  }

  const toggleSelectedTicker = (ticker: string) => {
    setSelectedTickers((current) => (
      current.includes(ticker)
        ? current.filter((item) => item !== ticker)
        : [...current, ticker]
    ))
  }

  const closeOperatorImportModal = () => {
    setIsOperatorImportOpen(false)
    setOperatorImportTickers([])
  }

  const toggleSelectedHoldingTrade = (key: string) => {
    setSelectedHoldingTradeKeys((current) => (
      current.includes(key)
        ? current.filter((item) => item !== key)
        : [...current, key]
    ))
  }

  const commitPersonalTradeLogs = (updater: (current: TradeLog[]) => TradeLog[]) => {
    setPersonalTradeLogs((current) => {
      const next = updater(current)
      void persistPortfolioState(next, contributionSettings)
      return next
    })
  }

  const saveAdminSystemTradeLogs = async (nextTrades: TradeLog[]) => {
    if (!supabase) {
      throw new Error('Supabase 연결값이 설정되지 않았습니다.')
    }

    const { data: authData } = await supabase.auth.getSession()
    const saved = await saveTradeLogs(nextTrades, apiMetas.tradeLogs, {
      accessToken: authData.session?.access_token,
    })
    setSystemTradeLogs(saved.rows)
    setApiMetas((current) => ({ ...current, tradeLogs: saved.meta }))
    setRefreshDataMessage('보유 종목 변경이 반영됐습니다.')
  }

  const commitManagedHoldingTradeLogs = async (updater: (current: TradeLog[]) => TradeLog[]) => {
    if (isAdminUser && isOperatorDataMode) {
      const nextTrades = updater(systemTradeLogs)
      setIsSavingTradeLogs(true)
      try {
        await saveAdminSystemTradeLogs(nextTrades)
      } catch (error) {
        setRefreshDataMessage(error instanceof Error ? error.message : '트레이딩 로그 저장에 실패했습니다.')
        throw error
      } finally {
        setIsSavingTradeLogs(false)
      }
      return
    }

    commitPersonalTradeLogs(updater)
  }

  function openContributionSettings() {
    setContributionSettingsMode('cash')
    setContributionDraft(contributionSettingsDraftFrom(contributionSettings))
  }

  function openInvestmentAllocationSettings() {
    setContributionSettingsMode('investment')
    setContributionDraft(contributionSettingsDraftFrom(contributionSettings))
  }

  const saveContributionSettings = () => {
    if (!contributionDraft) return
    const dayMessage = contributionDayMessage(contributionDraft.dayOfMonth)
    if (contributionSettingsMode === 'cash' && contributionDraft.frequency === 'monthly' && dayMessage && !dayMessage.includes('없는 달') && !dayMessage.includes('윤년')) {
      return
    }
    const dayOfMonth = Number(contributionDraft.dayOfMonth)
    const nextSettings = {
      initialCapital: parseAmountValue(contributionDraft.initialCapital) ?? DEFAULT_CONTRIBUTION_SETTINGS.initialCapital,
      frequency: contributionDraft.frequency,
      amount: parseAmountValue(contributionDraft.amount) ?? 0,
      dayOfWeek: Number(contributionDraft.dayOfWeek),
      dayOfMonth,
      allocationByInvestmentType: {
        swing: normalizeAllocationSettings({
          slotCount: Number(contributionDraft.allocationByInvestmentType.swing.slotCount),
          slotPercents: contributionDraft.allocationByInvestmentType.swing.slotPercents.map((value) => Number(value)),
        }, 'swing'),
        long_term: normalizeAllocationSettings({
          slotCount: Number(contributionDraft.allocationByInvestmentType.long_term.slotCount),
          slotPercents: contributionDraft.allocationByInvestmentType.long_term.slotPercents.map((value) => Number(value)),
        }, 'long_term'),
      },
    }
    setContributionSettings(nextSettings)
    void persistPortfolioState(personalTradeLogs, nextSettings)
    setContributionDraft(null)
  }

  const removeSelectedHoldingTrades = async () => {
    if (selectedHoldingTradeKeys.length === 0 || isSavingTradeLogs) return
    try {
      await commitManagedHoldingTradeLogs((current) => current.filter((trade) => !selectedHoldingTradeKeys.includes(tradeKey(trade))))
      setSelectedHoldingTradeKeys([])
      setIsHoldingDeleteConfirmOpen(false)
    } catch {
      // The user-facing save error is surfaced in the refresh message area.
    }
  }

  const openHoldingLiquidationModal = () => {
    const targetTrades = scopedOpenTrades.filter((trade) => (
      trade.status === '보유 중' && selectedHoldingTradeKeys.includes(tradeKey(trade))
    ))
    if (targetTrades.length === 0) return

    setHoldingLiquidationDrafts(targetTrades.map((trade) => {
      const fallbackStock = apiStocks.find((stock) => stock.ticker === trade.ticker)
      return {
        key: tradeKey(trade),
        ticker: trade.ticker,
        name: tradeName(trade),
        buyDate: trade.buyDate,
        buyPrice: trade.buyPrice === '-' ? '' : trade.buyPrice,
        sellDate: todayTradeDateString(),
        sellPrice: trade.currentPrice || fallbackStock?.currentPrice || '',
      }
    }))
    setIsHoldingLiquidationOpen(true)
  }

  const closeHoldingLiquidationModal = () => {
    setIsHoldingLiquidationOpen(false)
    setHoldingLiquidationDrafts([])
  }

  const updateHoldingLiquidationDraft = (key: string, field: 'buyPrice' | 'sellDate' | 'sellPrice', value: string) => {
    setHoldingLiquidationDrafts((current) => current.map((draft) => (
      draft.key === key ? { ...draft, [field]: value } : draft
    )))
  }

  const isHoldingLiquidationReady = holdingLiquidationDrafts.length > 0 && holdingLiquidationDrafts.every((draft) => (
    parsePriceValue(draft.buyPrice) !== null
    && parsePriceValue(draft.sellPrice) !== null
    && !Number.isNaN(parseTradeDate(draft.sellDate))
  ))

  const confirmHoldingLiquidation = async () => {
    if (!isHoldingLiquidationReady || isSavingTradeLogs) return

    const draftMap = new Map(holdingLiquidationDrafts.map((draft) => [draft.key, draft]))
    try {
      await commitManagedHoldingTradeLogs((current) => current.map((trade) => {
        const draft = draftMap.get(tradeKey(trade))
        if (!draft) return trade

        const buyPrice = parsePriceValue(draft.buyPrice) ?? 0
        const sellPrice = parsePriceValue(draft.sellPrice) ?? 0
        const returnPct = buyPrice > 0 ? ((sellPrice - buyPrice) / buyPrice) * 100 : 0
        const sellDate = normalizeTradeDateInput(draft.sellDate)
        const holdingDays = Math.max(0, Math.ceil((parseTradeDate(sellDate) - parseTradeDate(trade.buyDate)) / 86_400_000))

        return {
          ...trade,
          buyPrice: formatTradePrice(trade, buyPrice > 0 ? buyPrice : null, draft.buyPrice),
          sellDate,
          sellPrice: formatTradePrice(trade, sellPrice > 0 ? sellPrice : null, draft.sellPrice),
          returnPct,
          holdingDays,
          status: returnPct >= 0 ? '익절' : '손절',
          manualExit: true,
        }
      }))
      setSelectedHoldingTradeKeys([])
      closeHoldingLiquidationModal()
    } catch {
      // The user-facing save error is surfaced in the refresh message area.
    }
  }

  // 세션이 바뀌면(로그인/로그아웃/계정 전환) 해당 세션의 유형별 보관소를 다시 읽어온다.
  // (아래 동기화 effect보다 먼저 정의해 마운트/세션 전환 시 활성 유형 값이 덮어써지지 않게 한다.)
  useEffect(() => {
    const stored = readPersonalWatchlistByType(userSession)
    setPersonalWatchlistByType({
      long_term: stored?.long_term ?? [],
      swing: stored?.swing ?? [],
    })
    // 활성 유형은 아래 동기화 effect가 watchlist 기준으로 곧바로 채운다.
  }, [userSession?.id])

  // 활성 유형의 관심종목(watchlist)을 유형별 보관소에 계속 반영해 둔다.
  useEffect(() => {
    setPersonalWatchlistByType((prev) => {
      if (sameWatchlistTickers(prev[displayedInvestmentType], watchlist)) return prev
      const next = { ...prev, [displayedInvestmentType]: watchlist }
      storePersonalWatchlistByType(userSession, next)
      return next
    })
  }, [watchlist, displayedInvestmentType, userSession?.id])

  // 운영자 모드에서도 활성 유형의 관심종목(operatorWatchlist)을 유형별 보관소에 반영해 둔다.
  useEffect(() => {
    if (!isOperatorDataMode) return
    setOperatorWatchlistByType((prev) => {
      if (sameWatchlistTickers(prev[displayedInvestmentType], effectiveOperatorWatchlist)) return prev
      const next = { ...prev, [displayedInvestmentType]: effectiveOperatorWatchlist }
      storeOperatorWatchlistByType(next)
      return next
    })
  }, [effectiveOperatorWatchlist, displayedInvestmentType, isOperatorDataMode])

  // 어드민이 유형별 운영자 관심종목을 변경하면 DB에 반영해 일반 계정이 성향별로 가져올 수 있게 한다.
  // DB에서 한 번 복원(operatorWatchlistByTypeLoadedRef)한 뒤에만 저장해 초기 로드 시 빈 값으로 덮어쓰지 않는다.
  useEffect(() => {
    if (!isAdminUser) return undefined
    if (!operatorWatchlistByTypeLoadedRef.current) return undefined
    const timeoutId = window.setTimeout(() => {
      void persistOperatorWatchlistByType(operatorWatchlistByType)
    }, 500)
    return () => window.clearTimeout(timeoutId)
  }, [operatorWatchlistByType, isAdminUser])

  const selectInvestmentType = (nextInvestmentType: InvestmentType) => {
    const currentType = investmentType ?? DEFAULT_INVESTMENT_TYPE
    // 유형을 바꾸면 관심종목도 유형별로 스왑한다. 운영자(어드민) 모드와 개인 모드를 각각의 보관소로 처리한다.
    if (nextInvestmentType !== currentType) {
      if (isOperatorDataMode) {
        const saved: Record<InvestmentType, string[]> = { ...operatorWatchlistByType, [currentType]: effectiveOperatorWatchlist }
        const nextList = saved[nextInvestmentType] ?? []
        setOperatorWatchlistByType(saved)
        storeOperatorWatchlistByType(saved)
        setOperatorWatchlist(nextList)
        void persistWatchlist('operator', nextList).then(notifyWatchlistPersistFailure)
      } else {
        const saved: Record<InvestmentType, string[]> = { ...personalWatchlistByType, [currentType]: watchlist }
        const nextList = saved[nextInvestmentType] ?? []
        setPersonalWatchlistByType(saved)
        storePersonalWatchlistByType(userSession, saved)
        setWatchlist(nextList)
        if (userSession) {
          void persistWatchlist('personal', nextList).then(notifyWatchlistPersistFailure)
        }
      }
    }
    setInvestmentType(nextInvestmentType)
    void persistUserSettings(watchlistSortSettings, notificationPreferences, nextInvestmentType)
    resetHomeSheetScroll()
  }

  const confirmInvestmentProfileOnboarding = () => {
    selectInvestmentType(onboardingInvestmentType)
  }

  const closeInvestmentProfileOnboarding = () => {
    selectInvestmentType(DEFAULT_INVESTMENT_TYPE)
  }

  const resetSystemRecords = () => {
    if (isAdminUser) {
      setIsResetConfirmOpen(false)
      return
    }

    const session = userSession
    const emptyTrades: TradeLog[] = []

    setWatchlist([])
    const emptyWatchlistByType: Record<InvestmentType, string[]> = { long_term: [], swing: [] }
    setPersonalWatchlistByType(emptyWatchlistByType)
    storePersonalWatchlistByType(session, emptyWatchlistByType)
    setPersonalTradeLogs(emptyTrades)
    storePersonalTradeLogs(session, emptyTrades)
    if (session) {
      storePendingPersonalWatchlist(session, [])
    }

    setSelectedTickers([])
    setSelectedHoldingTradeKeys([])
    setQuery('')
    setIsAddingStock(false)
    setSelectedStrategy('전체')
    setIsResetConfirmOpen(false)
    setIsHoldingDeleteConfirmOpen(false)
    setIsHoldingLiquidationOpen(false)

    if (!session || !supabase || isLocalTestSession(session)) return

    resetSyncGenerationRef.current += 1
    const syncGeneration = resetSyncGenerationRef.current
    const ownerId = session.id
    void Promise.all([
      persistWatchlist('personal', [], session),
      persistPortfolioState(emptyTrades, contributionSettings, session),
    ]).catch(() => {
      if (resetSyncGenerationRef.current !== syncGeneration) return
      if (userSession?.id !== ownerId) return
      storePendingPersonalWatchlist(session, [])
    })
  }

  const clearAuthForm = () => {
    setLoginEmail('')
    setLoginPassword('')
    setLoginPasswordConfirm('')
    setLoginError('')
    setAuthInfoMessage('')
    setSignupConfirmationEmail('')
    setIsRecoverySent(false)
  }

  const clearSessionLocalData = (session: UserSession | null) => {
    if (!session) return
    localStorage.removeItem(personalWatchlistStorageKey(session))
    localStorage.removeItem(personalWatchlistPendingStorageKey(session))
    localStorage.removeItem(personalTradeLogsStorageKey(session))
    localStorage.removeItem(contributionSettingsStorageKey(session))
    localStorage.removeItem(userSettingsStorageKey(session))
  }

  const switchAuthMode = (mode: AuthMode) => {
    setAuthMode(mode)
    clearAuthForm()
  }

  const submitLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const email = trimmedLoginEmail
    const password = loginPassword.trim()
    const passwordConfirm = loginPasswordConfirm.trim()

    if (!supabase) {
      setLoginError('Supabase 연결값이 설정되지 않았습니다.\n.env에 VITE_SUPABASE_URL과 VITE_SUPABASE_ANON_KEY를 입력해 주세요.')
      return
    }

    if (authMode !== 'reset' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setLoginError('이메일 형식이 올바르지 않습니다.')
      return
    }

    if (authMode === 'recover') {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: window.location.origin,
      })
      if (error) {
        setLoginError(`비밀번호 재설정 안내를 보내지 못했습니다.\n${error.message}`)
        return
      }
      setLoginError('')
      setAuthInfoMessage('계정이 등록된 이메일이라면 재설정 안내가 발송됩니다.\n입력한 이메일함을 확인해 주세요.')
      setIsRecoverySent(true)
      return
    }

    if (password.length < 8) {
      setLoginError('비밀번호는 8자 이상이어야 합니다.\n8자 이상 입력하면 계속 진행할 수 있습니다.')
      return
    }

    if (authMode === 'reset') {
      if (password !== passwordConfirm) {
        setLoginError('비밀번호가 일치하지 않습니다.\n비밀번호 확인란을 다시 입력해 주세요.')
        return
      }

      const { data, error } = await supabase.auth.updateUser({ password })
      if (error || !data.user) {
        setLoginError('비밀번호를 변경하지 못했습니다.\n재설정 링크를 다시 요청해 주세요.')
        return
      }

      const nextSession = sessionFromSupabaseUser(data.user)
      setUserSession(nextSession)
      await ensureProfile(nextSession)
      await loadServiceData(nextSession)
      setSelectedTickers([])
      setSelectedHoldingTradeKeys([])
      clearAuthForm()
      setAuthMode('login')
      setIsLoginOpen(false)
      return
    }

    if (authMode === 'signup') {
      if (password !== passwordConfirm) {
        setLoginError('비밀번호가 일치하지 않습니다.\n비밀번호 확인란을 다시 입력해 주세요.')
        return
      }

      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          emailRedirectTo: window.location.origin,
          data: {
            name: email.split('@')[0],
          },
        },
      })
      if (error) {
        setLoginError(error.message.includes('already registered')
          ? '이미 가입된 이메일입니다.\n로그인 탭에서 기존 계정으로 로그인해 주세요.'
          : `회원가입을 완료하지 못했습니다.\n${error.message}`)
        return
      }
      if (Array.isArray(data.user?.identities) && data.user.identities.length === 0) {
        clearAuthForm()
        setAuthMode('login')
        setSignupConfirmationEmail(email)
        setAuthInfoMessage('이미 가입 요청된 이메일이거나 확인 대기 중인 계정일 수 있습니다.\n메일이 오지 않았다면 확인 메일을 다시 보내고, 이미 인증한 계정이면 로그인 또는 비밀번호 재설정을 이용해 주세요.')
        return
      }

      clearAuthForm()
      setAuthMode('login')
      setSignupConfirmationEmail(email)
      setAuthInfoMessage('가입 확인 메일을 보냈습니다.\n이메일 인증 후 로그인해 주세요. 메일이 안 오면 아래 재발송을 눌러 주세요.')
      return
    }

    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    })
    if (error || !data.user) {
      setLoginError('이메일 또는 비밀번호가 일치하지 않습니다.\n입력한 계정 정보를 다시 확인해 주세요.')
      return
    }

    const nextSession = sessionFromSupabaseUser(data.user)
    setUserSession(nextSession)
    await ensureProfile(nextSession)
    await loadServiceData(nextSession)
    setSelectedTickers([])
    setSelectedHoldingTradeKeys([])
    clearAuthForm()
    setAuthMode('login')
    setIsLoginOpen(false)
  }

  const logout = async () => {
    await supabase?.auth.signOut()
    storeLocalTestSession(null, { allowProduction: true })
    setUserSession(null)
    setCanUseAccountSwitch(false)
    setWatchlist(readStoredWatchlist(null))
    setPersonalTradeLogs(readStoredPersonalTradeLogs(null))
    const guestSettings = readStoredUserSettings(null)
    setWatchlistSortSettings(guestSettings.watchlistSort)
    setInvestmentType(guestSettings.investmentType)
    setContributionSettings(readStoredContributionSettings(null))
    setSelectedTickers([])
    setSelectedHoldingTradeKeys([])
    closeHoldingLiquidationModal()
    clearAuthForm()
    setAuthMode('login')
    setIsLoginOpen(false)
  }

  const logoutAndOpenLogin = async () => {
    await logout()
    setAuthMode('login')
    setAuthInfoMessage('기존 계정에서 로그아웃했습니다.\n다른 메일로 로그인하거나 회원가입 탭에서 새 계정을 추가해 주세요.')
    setIsLoginOpen(true)
  }

  const resendSignupConfirmation = async () => {
    if (!supabase || !signupConfirmationEmail) return
    const { error } = await supabase.auth.resend({
      type: 'signup',
      email: signupConfirmationEmail,
      options: {
        emailRedirectTo: window.location.origin,
      },
    })
    if (error) {
      setLoginError(`확인 메일을 다시 보내지 못했습니다.\n${error.message}`)
      return
    }
    setLoginError('')
    setAuthInfoMessage(`확인 메일을 다시 보냈습니다.\n${signupConfirmationEmail} 메일함과 스팸함을 확인해 주세요.`)
  }

  const deleteAccount = async () => {
    if (!userSession || isDeletingAccount) return
    if (!supabase) {
      setAccountDeleteError('Supabase 연결값이 없어 회원탈퇴를 처리할 수 없습니다.')
      setIsAccountDeleteConfirmOpen(false)
      return
    }

    setIsDeletingAccount(true)
    setAccountDeleteError('')
    const deletingSession = userSession
    try {
      const { error } = await supabase.rpc('delete_own_account')
      if (error) {
        const message = error.message.includes('delete_own_account') || error.message.includes('schema cache')
          ? '회원탈퇴 RPC가 아직 DB에 적용되지 않았습니다.\nSupabase migration 008_refresh_delete_own_account_rpc.sql을 적용한 뒤 다시 시도해 주세요.'
          : `회원탈퇴를 완료하지 못했습니다.\n${error.message}`
        setAccountDeleteError(message)
        setIsAccountDeleteConfirmOpen(false)
        setIsLoginOpen(true)
        return
      }

      await supabase.auth.signOut()
      clearSessionLocalData(deletingSession)
      storeLocalTestSession(null, { allowProduction: true })
      setUserSession(null)
      setCanUseAccountSwitch(false)
      setWatchlist(readStoredWatchlist(null))
      setPersonalTradeLogs(readStoredPersonalTradeLogs(null))
      const guestSettings = readStoredUserSettings(null)
      setWatchlistSortSettings(guestSettings.watchlistSort)
      setInvestmentType(guestSettings.investmentType)
      setContributionSettings(readStoredContributionSettings(null))
      setSelectedTickers([])
      setSelectedHoldingTradeKeys([])
      closeHoldingLiquidationModal()
      clearAuthForm()
      setAuthMode('login')
      setIsAccountDeleteConfirmOpen(false)
      setIsLoginOpen(false)
    } finally {
      setIsDeletingAccount(false)
    }
  }

  const closeLoginModalAfterAccountSwitch = () => {
    setIsLoginOpen(false)
    window.setTimeout(() => setIsLoginOpen(false), 0)
  }

  const switchTestSession = (mode: 'admin' | 'user') => {
    closeLoginModalAfterAccountSwitch()
    setRefreshDataMessage('')
    const adminEmail = configuredAdminEmails()[0] ?? DEFAULT_ADMIN_EMAILS[0]
    const nextSession = mode === 'admin'
      ? {
          id: 'local-test-admin',
          email: adminEmail,
          name: '어드민',
          loggedInAt: new Date().toISOString(),
        }
      : {
          ...TEST_USER_SESSION,
          loggedInAt: new Date().toISOString(),
        }

    setUserSession(nextSession)
    storeLocalTestSession(nextSession, { allowProduction: true })
    setCanUseAccountSwitch(true)
    applyLocalTestSessionData(nextSession)
    setSelectedTickers([])
    setSelectedHoldingTradeKeys([])
    closeHoldingLiquidationModal()
    localStorage.setItem(VIEW_MODE_STORAGE_KEY, mode === 'admin' ? 'operator' : 'personal')
    setViewMode(mode === 'admin' ? 'operator' : 'personal')
    resetHomeSheetScroll()
    clearAuthForm()
    setAuthMode('login')
    closeLoginModalAfterAccountSwitch()
  }

  const closeLoginModal = () => {
    setIsLoginOpen(false)
    clearAuthForm()
    setAuthMode('login')
  }

  const updateMarketEventEntry = (
    groupIndex: number,
    entryIndex: number,
    field: keyof MarketEventEntry,
    value: string,
  ) => {
    setIsMarketEventsDirty(true)
    setApiMarketEventGroups((current) => current.map((group, currentGroupIndex) => {
      if (currentGroupIndex !== groupIndex) return group
      return {
        ...group,
        entries: group.entries.map((entry, currentEntryIndex) => (
          currentEntryIndex === entryIndex
            ? { ...entry, [field]: value, ...(field === 'date' ? { status: undefined } : {}) }
            : entry
        )),
      }
    }))
  }

  const updateMarketEventYearLabel = (value: string) => {
    setMarketEventYearLabel(value)
    setIsMarketEventsDirty(true)
  }

  const updateMarketEventMonth = (monthIndex: number, value: string) => {
    setMarketEventMonths((current) => current.map((month, index) => (index === monthIndex ? value : month)))
    setApiMarketEventGroups((current) => current.map((group) => ({
      ...group,
      entries: group.entries.map((entry, index) => (index === monthIndex ? { ...entry, month: value } : entry)),
    })))
    setIsMarketEventsDirty(true)
  }

  const toggleSelectedMarketTrendRow = (rowKey: string) => {
    setSelectedMarketTrendRowKeys((current) => (
      current.includes(rowKey)
        ? current.filter((key) => key !== rowKey)
        : [...current, rowKey]
    ))
  }

  const openMarketTrendDeleteConfirm = () => {
    if (selectedMarketTrendRowKeys.length === 0) return
    setPendingMarketTrendDeleteKeys(selectedMarketTrendRowKeys)
  }

  const updateWatchlistSortSetting = (value: WatchlistSortKey) => {
    const nextSort = { primary: value, secondary: 'registered' as WatchlistSortKey }
    setWatchlistSortSettings(nextSort)
    if (isAdminUser && isOperatorDataMode) {
      void persistOperatorWatchlistSort(nextSort)
    }
    setIsWatchlistSortOpen(false)
    void persistUserSettings(nextSort, notificationPreferences)
  }

  const updateNotificationPreference = (key: NotificationPreferenceKey, value: boolean) => {
    const nextPreferences = { ...notificationPreferences, [key]: value }
    setNotificationPreferences(nextPreferences)
    void persistUserSettings(watchlistSortSettings, nextPreferences)
  }

  const updateNotificationRecipientEmail = (value: string) => {
    const nextPreferences = { ...notificationPreferences, recipientEmail: value }
    setNotificationPreferences(nextPreferences)
    void persistUserSettings(watchlistSortSettings, nextPreferences)
  }

  const selectEmailNotificationChannel = () => {
    const nextPreferences = { ...notificationPreferences, notificationChannel: 'email' as const }
    setNotificationPreferences(nextPreferences)
    void persistUserSettings(watchlistSortSettings, nextPreferences)
  }

  const selectNotificationIntegrationChannel = (channel: NotificationIntegrationChannel) => {
    if (!isNotificationIntegrationConnected(channel)) return
    const nextPreferences = { ...notificationPreferences, notificationChannel: channel }
    setNotificationPreferences(nextPreferences)
    void persistUserSettings(watchlistSortSettings, nextPreferences)
  }

  const connectNotificationChannel = async (channel: NotificationIntegrationChannel) => {
    if (channel === 'kakaoTalk') return
    if (isNotificationIntegrationConnected(channel)) {
      selectNotificationIntegrationChannel(channel)
      return
    }
    if (!userSession || !supabase) {
      setAuthInfoMessage('슬랙 알림을 연동하려면 먼저 로그인해 주세요.')
      setIsLoginOpen(true)
      return
    }

    setConnectingNotificationChannel(channel)
    const oauthWindow = window.open('about:blank', '_blank')
    try {
      const { data } = await supabase.auth.getSession()
      const accessToken = data.session?.access_token
      if (!accessToken) {
        throw new Error('로그인이 필요합니다.')
      }
      const response = await fetch('/api/slack/oauth/start', {
        method: 'POST',
        headers: {
          authorization: `Bearer ${accessToken}`,
        },
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || !payload?.url) {
        throw new Error(payload?.error || 'Slack 연동을 시작하지 못했습니다.')
      }
      if (oauthWindow) {
        oauthWindow.opener = null
        oauthWindow.location.assign(String(payload.url))
      } else {
        window.open(String(payload.url), '_blank', 'noopener,noreferrer')
      }
    } catch (error) {
      oauthWindow?.close()
      setAuthInfoMessage(error instanceof Error ? error.message : 'Slack 연동을 시작하지 못했습니다.')
    } finally {
      setConnectingNotificationChannel(null)
    }
  }

  const disconnectNotificationChannel = async (channel: NotificationIntegrationChannel) => {
    const nextPreferences: NotificationPreferences = {
      ...notificationPreferences,
      notificationChannel: notificationPreferences.notificationChannel === channel ? 'email' : notificationPreferences.notificationChannel,
      ...(channel === 'kakaoTalk'
        ? { kakaoTalkConnected: false, kakaoTalkConnectedAt: '' }
        : { slackConnected: false, slackConnectedAt: '' }),
    }
    setNotificationPreferences(nextPreferences)
    void persistUserSettings(watchlistSortSettings, nextPreferences)
    if (channel !== 'slack' || !supabase) return

    try {
      const { data } = await supabase.auth.getSession()
      const accessToken = data.session?.access_token
      if (!accessToken) return
      await fetch('/api/slack/integration', {
        method: 'DELETE',
        headers: {
          authorization: `Bearer ${accessToken}`,
        },
      })
    } catch {
      // Local preference already falls back to email; the server cleanup can be retried by reconnecting/disconnecting later.
    }
  }

  const saveMarketEventEntries = async () => {
    if (!isAdminUser || !isMarketEventsDirty) return
    const normalizedGroups = normalizeMarketEventDdays(apiMarketEventGroups)
    setIsSavingMarketEvents(true)
    try {
      const { data: authData } = supabase ? await supabase.auth.getSession() : { data: { session: null } }
      const saved = await saveMarketEvents(normalizedGroups, marketEventsMeta, {
        yearLabel: marketEventYearLabel,
        months: marketEventMonths,
        accessToken: authData.session?.access_token,
      })
      setApiMarketEventGroups(saved.groups)
      setMarketEventsMeta(saved.meta)
      setApiMetas((current) => ({ ...current, marketEvents: saved.meta }))
      if (saved.yearLabel) {
        setMarketEventYearLabel(saved.yearLabel)
      }
      if (saved.months) {
        setMarketEventMonths(saved.months)
      }
      setIsMarketEventsDirty(false)
      await recordApiLog('market-events', 'success', '시장 주요 이벤트를 저장했습니다.', { groups: normalizedGroups.length })
    } catch (error) {
      await recordApiLog('market-events', 'failure', error instanceof Error ? error.message : '시장 주요 이벤트 저장에 실패했습니다.')
    } finally {
      setIsSavingMarketEvents(false)
    }
  }

  const removeSelectedMarketTrendRows = async () => {
    if (!isAdminUser || pendingMarketTrendDeleteKeys.length === 0) return
    const deleteKeys = new Set(pendingMarketTrendDeleteKeys)
    const deletedRowCount = pendingMarketTrendDeleteKeys.length
    const previousRows = apiMarketTrendRows
    const previousSelectedRowKeys = selectedMarketTrendRowKeys
    const nextRows = apiMarketTrendRows.filter((row) => !deleteKeys.has(marketTrendRowKey(row)))

    setIsSavingMarketTrends(true)
    setApiMarketTrendRows(nextRows)
    setSelectedMarketTrendRowKeys((current) => current.filter((key) => !deleteKeys.has(key)))
    setPendingMarketTrendDeleteKeys([])
    try {
      const { data: authData } = supabase ? await supabase.auth.getSession() : { data: { session: null } }
      const saved = await saveMarketTrends(nextRows, apiMetas.marketTrends, {
        accessToken: authData.session?.access_token,
      })
      setApiMarketTrendRows(saved.rows)
      setApiMetas((current) => ({ ...current, marketTrends: saved.meta }))
      void recordApiLog('market-trends', 'success', '시장 트렌드 row를 삭제했습니다.', { rows: deletedRowCount })
    } catch (error) {
      setApiMarketTrendRows(previousRows)
      setSelectedMarketTrendRowKeys(previousSelectedRowKeys)
      void recordApiLog('market-trends', 'failure', error instanceof Error ? error.message : '시장 트렌드 삭제에 실패했습니다.')
    } finally {
      setIsSavingMarketTrends(false)
    }
  }

  const refreshCurrentData = async () => {
    if (!isAdminUser) return

    const tickers = Array.from(new Set(tableStocks.map((stock) => stock.ticker)))
    if (tickers.length === 0) {
      setRefreshDataMessage('먼저 관심종목을 추가해 주세요.')
      return
    }

    setIsRefreshingData(true)
    setRefreshDataMessage('데이터 갱신 작업을 실행하는 중입니다...')
    try {
      if (!supabase) {
        throw new Error('Supabase 연결값이 설정되지 않았습니다.')
      }

      const { data: authData } = await supabase.auth.getSession()
      const accessToken = authData.session?.access_token
      const previousMetas = apiMetas
      const result = await refreshAppData(tickers, accessToken)

      if (result.mode === 'workflow_dispatch') {
        setRefreshDataMessage('데이터 갱신 워크플로를 실행했습니다. 최신 데이터 반영 여부를 확인하는 중입니다...')
        for (let attempt = 1; attempt <= 40; attempt += 1) {
          await wait(attempt <= 3 ? 8000 : 15000)
          const data = await fetchAppData<Stock, ValuationMetric, MarketEventGroup, MarketTrendRow, TradeLog>()
          const isRefreshed = appDataMetaChanged(data, previousMetas)
          if (isRefreshed) {
            applyLoadedData(data)
            const rowCount = data.stocks?.rows?.length ?? result.refreshedTickers.length
            setRefreshDataMessage(`최신 데이터가 반영됐습니다. ${rowCount}개 종목 기준으로 갱신되었습니다.`)
            await recordRefreshDataLogs('success', `${rowCount}개 종목 최신 데이터가 반영됐습니다.`, { tickers: result.refreshedTickers })
            return
          }
          if (attempt === 3 || attempt % 4 === 0) {
            setRefreshDataMessage(`데이터 갱신 워크플로가 진행 중입니다. 최신 데이터 반영을 확인하는 중입니다... (${attempt}/40)`)
          }
        }
        setRefreshDataMessage('데이터 갱신 워크플로를 실행했습니다. 아직 반영 확인이 끝나지 않았습니다. 잠시 후 새로고침해 주세요.')
        return
      }

      const data = await fetchAppData<Stock, ValuationMetric, MarketEventGroup, MarketTrendRow, TradeLog>()
      applyLoadedData(data)
      setRefreshDataMessage(`${result.refreshedTickers.length}개 종목을 현재 시점 기준으로 갱신했습니다.`)
      await recordRefreshDataLogs('success', `${result.refreshedTickers.length}개 종목을 갱신했습니다.`, { tickers: result.refreshedTickers })
    } catch (error) {
      setRefreshDataMessage('즉시 갱신에 실패했습니다. GitHub Actions 토큰과 Vercel 환경 변수를 확인해 주세요.')
      await recordRefreshDataLogs('failure', error instanceof Error ? error.message : '데이터 즉시 갱신에 실패했습니다.', { tickers })
    } finally {
      setIsRefreshingData(false)
    }
  }

  const submitBoardPost = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextContent = boardContent.trim()
    if (!nextContent || !userSession) return

    if (supabase) {
      const { data, error } = await supabase
        .from('board_posts')
        .insert({
          category: boardCategory,
          content: nextContent,
          author_id: userSession.id,
          author_name: boardCurrentUserName(userSession),
        })
        .select('id, category, content, created_at, author_id, author_name, hidden, board_comments(id, post_id, content, created_at, author_id, author_name)')
        .single()

      if (error) return
      setBoardPosts((currentPosts) => [mapBoardPost(data), ...currentPosts])
    } else {
      setBoardPosts((currentPosts) => [
        {
          id: String(Date.now()),
          category: boardCategory,
          content: nextContent,
          createdAt: new Date().toISOString(),
          authorId: boardCurrentUserId(userSession),
          authorName: boardCurrentUserName(userSession),
          comments: [],
        },
        ...currentPosts,
      ])
    }
    setBoardContent('')
    setBoardFilter('전체')
    setBoardPage(1)
    setShowMineOnly(false)
    setBoardSortDirection('desc')
  }

  const updateBoardCommentDraft = (postId: string, content: string) => {
    setBoardCommentDrafts((current) => ({ ...current, [postId]: content.slice(0, MAX_BOARD_COMMENT_LENGTH) }))
  }

  const submitBoardComment = async (event: FormEvent<HTMLFormElement>, post: BoardPost) => {
    event.preventDefault()
    const nextContent = (boardCommentDrafts[post.id] ?? '').trim()
    if (!nextContent || !userSession || post.comments.length >= MAX_BOARD_COMMENTS_PER_POST) return

    const draftComment: BoardComment = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      postId: post.id,
      content: nextContent,
      createdAt: new Date().toISOString(),
      authorId: boardCurrentUserId(userSession),
      authorName: boardCurrentUserName(userSession),
    }

    if (supabase) {
      const { data, error } = await supabase
        .from('board_comments')
        .insert({
          post_id: post.id,
          content: nextContent,
          author_id: userSession.id,
          author_name: boardCurrentUserName(userSession),
        })
        .select('id, post_id, content, created_at, author_id, author_name')
        .single()
      if (error) return
      draftComment.id = data.id
      draftComment.createdAt = data.created_at
      draftComment.authorId = data.author_id
      draftComment.authorName = data.author_name
    }

    setBoardPosts((currentPosts) => currentPosts.map((currentPost) => (
      currentPost.id === post.id
        ? { ...currentPost, comments: [...currentPost.comments, draftComment] }
        : currentPost
    )))
    setBoardCommentDrafts((current) => ({ ...current, [post.id]: '' }))
  }

  const deleteBoardPost = (postId: string) => {
    setPendingBoardDeleteIds([postId])
  }

  const hideSelectedBoardPosts = async () => {
    if (selectedBoardPostIds.length === 0) return
    const selectedIds = new Set(selectedBoardPostIds)
    if (supabase) {
      const { error } = await supabase
        .from('board_posts')
        .update({ hidden: true })
        .in('id', selectedBoardPostIds)
      if (error) return
    }
    setBoardPosts((currentPosts) => currentPosts.map((post) => (
      selectedIds.has(post.id) ? { ...post, hidden: true } : post
    )))
    setSelectedBoardPostIds([])
    setBoardPage(1)
  }

  const removeSelectedBoardPosts = () => {
    if (selectedBoardPostIds.length === 0) return
    setPendingBoardDeleteIds(selectedBoardPostIds)
  }

  function closeTopModal() {
    if (pendingMarketTrendDeleteKeys.length > 0 && !isSavingMarketTrends) {
      setPendingMarketTrendDeleteKeys([])
      return
    }
    if (isHoldingDeleteConfirmOpen) {
      setIsHoldingDeleteConfirmOpen(false)
      return
    }
    if (isHoldingLiquidationOpen) {
      closeHoldingLiquidationModal()
      return
    }
    if (contributionDraft) {
      setContributionDraft(null)
      return
    }
    if (pendingBoardDeleteIds.length > 0) {
      setPendingBoardDeleteIds([])
      return
    }
    if (isResetConfirmOpen) {
      setIsResetConfirmOpen(false)
      return
    }
    if (isAccountDeleteConfirmOpen && !isDeletingAccount) {
      setIsAccountDeleteConfirmOpen(false)
      return
    }
    if (isLoginOpen) {
      closeLoginModal()
      return
    }
    if (shouldShowInvestmentProfileOnboarding) {
      closeInvestmentProfileOnboarding()
      return
    }
    if (isWatchlistTypeImportOpen) {
      closeWatchlistTypeImportModal()
      return
    }
    if (isOperatorImportOpen) {
      closeOperatorImportModal()
    }
  }

  const confirmBoardPostDeletion = async () => {
    if (pendingBoardDeleteIds.length === 0) return
    const deleteIds = new Set(pendingBoardDeleteIds)
    if (supabase) {
      const { error } = await supabase
        .from('board_posts')
        .delete()
        .in('id', pendingBoardDeleteIds)
      if (error) return
    }
    setBoardPosts((currentPosts) => currentPosts.filter((post) => (
      !deleteIds.has(post.id) || (!isAdminUser && post.authorId !== boardCurrentUserId(userSession))
    )))
    setSelectedBoardPostIds([])
    setPendingBoardDeleteIds([])
    setBoardPage(1)
  }

  const currentWatchlistTickers = isOperatorDataMode ? effectiveOperatorWatchlist : watchlist

  useEffect(() => {
    const handleModalEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      closeTopModal()
    }

    document.addEventListener('keydown', handleModalEscape)
    return () => document.removeEventListener('keydown', handleModalEscape)
  })

  useEffect(() => {
    setRefreshDataMessage('')
  }, [userSession?.id])

  useEffect(() => {
    if (hasAuthCallbackPayload()) return
    localStorage.setItem(ACTIVE_PAGE_STORAGE_KEY, activePage)
    const nextHash = activePageHash(activePage)
    if (activePageFromHash() !== activePage) {
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${nextHash}`)
    }
  }, [activePage])

  useEffect(() => {
    const syncPageFromHash = () => {
      const page = activePageFromHash()
      if (page) setActivePage(page)
      if (hasNotificationSettingsDeepLink()) {
        setAuthMode('login')
        setAuthInfoMessage(notificationSettingsDeepLinkMessage())
        setIsLoginOpen(true)
        if (userSession) {
          void loadServiceData(userSession)
        }
      }
    }
    window.addEventListener('hashchange', syncPageFromHash)
    return () => window.removeEventListener('hashchange', syncPageFromHash)
  }, [userSession?.id])

  const rawTableStocks = isOperatorDataMode ? operatorStocks : watchlistStocks
  const tableStocks = sortWatchlistStocks(rawTableStocks, watchlistSortSettings, currentWatchlistTickers, scopedTrades)
  const canEditCurrentWatchlist = effectiveViewMode === 'personal' || isAdminUser
  const isCurrentWatchlistEmpty = tableStocks.length === 0
  const shouldDimPanelsForFirstVisitGuide = isCurrentWatchlistEmpty && scopedTrades.length === 0
  const isCurrentWatchlistFull = canEditCurrentWatchlist && currentWatchlistTickers.length >= MAX_WATCHLIST_ITEMS
  const personalRemainingSlots = Math.max(0, MAX_WATCHLIST_ITEMS - watchlist.length)
  // 일반 계정의 '공수성가 가져오기'는 자신의 투자 성향에 맞는 운영자 관심종목만 후보로 노출한다.
  // 유형별 데이터가 아직 없는(구버전) 경우에만 단일 운영자 목록으로 폴백한다.
  const operatorImportCandidates = useMemo(() => {
    const hasByTypeData = operatorWatchlistByType.long_term.length > 0 || operatorWatchlistByType.swing.length > 0
    const sourceTickers = hasByTypeData
      ? operatorWatchlistByType[displayedInvestmentType] ?? []
      : effectiveOperatorWatchlist
    return sourceTickers
      .filter((ticker) => !watchlist.includes(ticker))
      .map((ticker) => apiStocks.find((stock) => stock.ticker === ticker) ?? apiSearchStocks.find((stock) => stock.ticker === ticker))
      .filter((stock): stock is Stock => Boolean(stock))
      .sort((a, b) => marketSortRank(a.market) - marketSortRank(b.market))
  }, [apiSearchStocks, apiStocks, effectiveOperatorWatchlist, operatorWatchlistByType, displayedInvestmentType, watchlist])
  const isOperatorImportSelectionFull = operatorImportTickers.length >= personalRemainingSlots
  const canShowOperatorImport = Boolean(userSession) && effectiveViewMode === 'personal' && canEditCurrentWatchlist
  const toggleOperatorImportTicker = (ticker: string) => {
    setOperatorImportTickers((current) => {
      if (current.includes(ticker)) return current.filter((item) => item !== ticker)
      if (current.length >= personalRemainingSlots) return current
      return [...current, ticker]
    })
  }
  // 남은 슬롯 한도 안에서 선택 가능한 종목 전체를 토글한다.
  const operatorImportSelectableTickers = operatorImportCandidates.slice(0, personalRemainingSlots).map((stock) => stock.ticker)
  const isAllOperatorImportSelected = operatorImportSelectableTickers.length > 0
    && operatorImportSelectableTickers.every((ticker) => operatorImportTickers.includes(ticker))
  const toggleSelectAllOperatorImport = () => {
    setOperatorImportTickers(isAllOperatorImportSelected ? [] : operatorImportSelectableTickers)
  }
  const importOperatorStocks = async () => {
    if (!userSession || operatorImportTickers.length === 0 || personalRemainingSlots <= 0) return

    const tickersToImport = operatorImportTickers
      .filter((ticker) => !watchlist.includes(ticker))
      .slice(0, personalRemainingSlots)
    if (tickersToImport.length === 0) {
      closeOperatorImportModal()
      return
    }

    const nextWatchlist = [...watchlist, ...tickersToImport]
    setWatchlist(nextWatchlist)
    await persistWatchlist('personal', nextWatchlist)

    const importedStocks = tickersToImport
      .map((ticker) => operatorImportCandidates.find((stock) => stock.ticker === ticker))
      .filter((stock): stock is Stock => Boolean(stock))
    if (importedStocks.length > 0) {
      setApiStocks((currentStocks) => {
        const currentTickers = new Set(currentStocks.map((stock) => stock.ticker))
        return [...currentStocks, ...importedStocks.filter((stock) => !currentTickers.has(stock.ticker))]
      })
    }
    closeOperatorImportModal()
  }

  // 상대 투자 유형(가치투자 ↔ 스윙투자)의 관심종목을 현재 유형으로 불러오는 기능.
  const otherInvestmentType: InvestmentType = displayedInvestmentType === 'long_term' ? 'swing' : 'long_term'
  const investmentTypeLabel = (type: InvestmentType) => (type === 'swing' ? '스윙 투자' : '가치 투자')
  const otherInvestmentTypeLabel = investmentTypeLabel(otherInvestmentType)
  const currentInvestmentTypeLabel = investmentTypeLabel(displayedInvestmentType)
  // 운영자(어드민)는 운영자 보관소를, 개인은 개인 보관소를 원본으로 사용한다.
  const activeWatchlistByType = isOperatorDataMode ? operatorWatchlistByType : personalWatchlistByType
  const otherTypeWatchlistTickers = activeWatchlistByType[otherInvestmentType] ?? []
  const activeWatchlistRemainingSlots = Math.max(0, MAX_WATCHLIST_ITEMS - currentWatchlistTickers.length)
  const watchlistTypeImportCandidates = useMemo(
    () => otherTypeWatchlistTickers
      .filter((ticker) => !currentWatchlistTickers.includes(ticker))
      .map((ticker) => resolveStockForTicker(ticker, apiStocks, apiSearchStocks))
      .sort((a, b) => marketSortRank(a.market) - marketSortRank(b.market)),
    [apiSearchStocks, apiStocks, otherTypeWatchlistTickers, currentWatchlistTickers],
  )
  const isWatchlistTypeImportSelectionFull = watchlistTypeImportTickers.length >= activeWatchlistRemainingSlots
  const canShowWatchlistTypeImport = Boolean(userSession) && canEditCurrentWatchlist
  const closeWatchlistTypeImportModal = () => {
    setIsWatchlistTypeImportOpen(false)
    setWatchlistTypeImportTickers([])
  }
  const toggleWatchlistTypeImportTicker = (ticker: string) => {
    setWatchlistTypeImportTickers((current) => {
      if (current.includes(ticker)) return current.filter((item) => item !== ticker)
      if (current.length >= activeWatchlistRemainingSlots) return current
      return [...current, ticker]
    })
  }
  // 남은 슬롯 한도 안에서 선택 가능한 종목 전체를 토글한다.
  const watchlistTypeImportSelectableTickers = watchlistTypeImportCandidates.slice(0, activeWatchlistRemainingSlots).map((stock) => stock.ticker)
  const isAllWatchlistTypeImportSelected = watchlistTypeImportSelectableTickers.length > 0
    && watchlistTypeImportSelectableTickers.every((ticker) => watchlistTypeImportTickers.includes(ticker))
  const toggleSelectAllWatchlistTypeImport = () => {
    setWatchlistTypeImportTickers(isAllWatchlistTypeImportSelected ? [] : watchlistTypeImportSelectableTickers)
  }
  const importWatchlistTypeStocks = async () => {
    if (!userSession || watchlistTypeImportTickers.length === 0 || activeWatchlistRemainingSlots <= 0) return

    const tickersToImport = watchlistTypeImportTickers
      .filter((ticker) => !currentWatchlistTickers.includes(ticker))
      .slice(0, activeWatchlistRemainingSlots)
    if (tickersToImport.length === 0) {
      closeWatchlistTypeImportModal()
      return
    }

    const nextWatchlist = [...currentWatchlistTickers, ...tickersToImport]
    if (isOperatorDataMode) {
      setOperatorWatchlist(nextWatchlist)
      await persistWatchlist('operator', nextWatchlist)
    } else {
      setWatchlist(nextWatchlist)
      await persistWatchlist('personal', nextWatchlist)
    }

    const importedStocks = tickersToImport
      .map((ticker) => watchlistTypeImportCandidates.find((stock) => stock.ticker === ticker))
      .filter((stock): stock is Stock => Boolean(stock))
    if (importedStocks.length > 0) {
      setApiStocks((currentStocks) => {
        const currentTickers = new Set(currentStocks.map((stock) => stock.ticker))
        return [...currentStocks, ...importedStocks.filter((stock) => !currentTickers.has(stock.ticker))]
      })
    }
    closeWatchlistTypeImportModal()
  }

  function megaTrendStatus(trade: TradeLog) {
    const stock = apiStocks.find((candidate) => candidate.ticker === trade.ticker)
    const industry = primaryIndustryLabel(stock?.industry)
    const rank = trendReportRankForTrade(trade)

    return rank !== null && rank <= 3
      ? `충족(${industry})`
      : '미충족'
  }

  function trendReportRankForTrade(trade: TradeLog) {
    const stock = apiStocks.find((candidate) => candidate.ticker === trade.ticker)
    const keywords = industryTrendKeywords(stock?.industry)
    if (keywords.length === 0) return null

    const matchedTrend = apiMarketTrendRows.find((row) => isSameTrendWeek(trade.buyDate, row.date))
    const matchedIndex = matchedTrend?.ranks.slice(0, 10).findIndex((rankText) => {
      const normalizedRankText = normalizeTrendText(rankText)
      return keywords.some((keyword) => normalizedRankText.includes(keyword))
    }) ?? -1

    return matchedIndex >= 0 ? matchedIndex + 1 : null
  }

  function tradeBuyPriority(trade: TradeLog): TradeBuyPriority {
    const rank = trendReportRankForTrade(trade)
    return {
      megaRank: rank !== null && rank <= 3 ? 0 : 1,
      trendRank: rank ?? 99,
    }
  }
  const exampleStock = rawTableStocks[0]
  const fairPricePendingLabel = nextMidnightUpdateLabel()
  const currentPricePendingLabel = nextTwoHourUpdateLabel()
  const showEmptyTradeExample = tableStocks.length > 0 && scopedTrades.length === 0
  const showEmptyHoldingExample = tableStocks.length > 0 && scopedOpenTrades.length === 0
  const tradeBlankRows = Math.max(3, (isLongTermInvestor ? 23 : 22) - filteredTrades.length - (showEmptyTradeExample ? 1 : 0))
  const watchlistBlankRows = Math.max(0, 10 - tableStocks.length)
  const holdingBlankRows = Math.max(0, 12 - scopedOpenTrades.length - (showEmptyHoldingExample ? 1 : 0))
  const visibleWatchlistSortOptions = isLongTermInvestor
    ? watchlistSortOptions.filter((option) => option.value !== 'opinion_sell_first')
    : watchlistSortOptions
  const currentWatchlistSortOption = visibleWatchlistSortOptions.find((option) => option.value === watchlistSortSettings.primary) ?? visibleWatchlistSortOptions[0]
  const isEmailNotificationChannel = notificationPreferences.notificationChannel === 'email'
  const isNotificationIntegrationConnected = (channel: NotificationIntegrationChannel) => (
    channel === 'kakaoTalk' ? notificationPreferences.kakaoTalkConnected : notificationPreferences.slackConnected
  )
  const shouldApplyHomePinnedInlineStyle = typeof window !== 'undefined' && window.innerWidth > 760
  const watchlistPinnedStyle = isWatchlistPinned && shouldApplyHomePinnedInlineStyle ? homePinnedStyles.watchlist : undefined
  const holdingPinnedStyle = isHoldingPinned && shouldApplyHomePinnedInlineStyle ? homePinnedStyles.holding : undefined
  const tradingPinnedStyle = isTradingPinned && shouldApplyHomePinnedInlineStyle ? homePinnedStyles.trading : undefined

  useEffect(() => {
    if (!isTradingPinned && !isWatchlistPinned && !isHoldingPinned) return

    const refreshAllPinnedStyles = () => {
      if (window.innerWidth <= 760) {
        setHomePinnedStyles({})
        return
      }

      setHomePinnedStyles((current) => ({
        trading: isTradingPinned ? homePinnedStyleFor(tradingLogScrollRef.current, 'trading') : current.trading,
        watchlist: isWatchlistPinned ? homePinnedStyleFor(watchlistSheetRef.current, 'watchlist') : current.watchlist,
        holding: isHoldingPinned ? homePinnedStyleFor(holdingSheetRef.current, 'holding') : current.holding,
      }))
    }

    refreshAllPinnedStyles()
    const onResize = () => refreshAllPinnedStyles()
    window.addEventListener('resize', onResize)
    window.addEventListener('orientationchange', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      window.removeEventListener('orientationchange', onResize)
    }
  }, [
    isTradingPinned,
    isWatchlistPinned,
    isHoldingPinned,
    canManageHoldingTrades,
    canEditCurrentWatchlist,
    isLongTermInvestor,
  ])

  const addStockInlineControl = isAddingStock && canEditCurrentWatchlist && !isCurrentWatchlistFull ? (
    <div className="inline-add analysis-inline-add" ref={inlineAddRef}>
      {(canShowOperatorImport || canShowWatchlistTypeImport) && (
        <div className="inline-add-toolbar">
          <span>직접 검색하거나 목록에서 가져올 수 있습니다.</span>
          <div className="inline-add-toolbar-actions">
            {canShowWatchlistTypeImport && (
              <button
                className="import-operator-button"
                type="button"
                onClick={() => setIsWatchlistTypeImportOpen(true)}
              >
                {otherInvestmentTypeLabel} 관심종목 불러오기
              </button>
            )}
            {canShowOperatorImport && (
              <button
                className="import-operator-button"
                type="button"
                onClick={() => setIsOperatorImportOpen(true)}
              >
                공수성가 종목 가져오기
              </button>
            )}
          </div>
        </div>
      )}
      <input
        autoFocus
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="삼성전자, 005930, AAPL"
      />
      {query && (
        <div className="inline-results">
          {searchResults.length > 0 ? searchResults.slice(0, 50).map((stock) => {
            const watchlistTickerSet = new Set(currentWatchlistTickers.map((item) => item.trim().toUpperCase()))
            const isAlreadyAdded = watchlistTickerSet.has(stock.ticker.trim().toUpperCase())

            return (
              <button
                disabled={isAlreadyAdded}
                key={stock.ticker}
                type="button"
                onClick={() => addToWatchlist(stock.ticker)}
              >
                <span>
                  <strong>{stock.name}</strong>
                  <small>{stock.ticker} · {stock.market}</small>
                </span>
                <span>{isAlreadyAdded ? '이미 추가됨' : '추가하기'}</span>
              </button>
            )
          }) : (
            <div className="empty-result">
              검색 결과가 없습니다.<br />
              다른 종목명이나 티커로 다시 검색해 주세요.<br />
              현재는 한국, 미국 주식만 추가가 가능합니다.
            </div>
          )}
        </div>
      )}
    </div>
  ) : null

  return (
    <main className={`app-shell ${showViewModeHint ? 'onboarding-active' : ''}`}>
      {showViewModeHint && <button className="view-mode-scrim" type="button" aria-label="안내 닫기" onClick={markViewModeHintSeen} />}
      {isOperatorImportOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={closeOperatorImportModal}>
          <section
            aria-labelledby="operator-import-title"
            aria-modal="true"
            className="confirm-modal operator-import-modal"
            role="dialog"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button className="modal-close-button" type="button" aria-label="닫기" onClick={closeOperatorImportModal}>×</button>
            <h3 id="operator-import-title">공수성가 종목 가져오기</h3>
            <p>
              내 관심종목에 없는 공수성가 종목만 가져옵니다. 남은 슬롯 {personalRemainingSlots}개.
            </p>
            <div className="operator-import-status">
              <div className="operator-import-status-head">
                <strong>{operatorImportTickers.length}개 선택</strong>
                <button
                  className="operator-import-select-all"
                  type="button"
                  disabled={operatorImportSelectableTickers.length === 0}
                  onClick={toggleSelectAllOperatorImport}
                >
                  {isAllOperatorImportSelected ? '선택 해제' : '전체 선택'}
                </button>
              </div>
              <span>
                {personalRemainingSlots > 0
                  ? `${personalRemainingSlots}개까지 선택할 수 있어요. 한도에 도달하면 기존 관심종목을 제거한 뒤 다시 추가해 주세요.`
                  : '관심종목 50개 한도에 도달했습니다. 기존 종목을 제거한 뒤 다시 가져올 수 있습니다.'}
              </span>
            </div>
            <div className="operator-import-list">
              {operatorImportCandidates.length > 0 ? operatorImportCandidates.map((stock) => {
                const isChecked = operatorImportTickers.includes(stock.ticker)
                const isDisabled = !isChecked && isOperatorImportSelectionFull

                return (
                  <label className={`operator-import-option ${isDisabled ? 'disabled' : ''}`} key={stock.ticker}>
                    <input
                      checked={isChecked}
                      disabled={isDisabled}
                      type="checkbox"
                      onChange={() => toggleOperatorImportTicker(stock.ticker)}
                    />
                    <span className="market-flag" aria-hidden="true">{marketFlag(stock.market)}</span>
                    <span>
                      <strong>{stock.name}</strong>
                      <small>{stock.ticker} · {displayIndustryLabel(stock.industry)}</small>
                    </span>
                  </label>
                )
              }) : (
                <div className="operator-import-empty">
                  가져올 수 있는 공수성가 종목이 없습니다. 이미 모두 추가했거나 공수성가 목록을 불러오는 중입니다.
                </div>
              )}
            </div>
            {isOperatorImportSelectionFull && operatorImportCandidates.length > operatorImportTickers.length && (
              <div className="operator-import-limit-message">
                남은 {personalRemainingSlots}개를 모두 선택했습니다. 더 가져오려면 기존 관심종목을 제거한 다음 다시 추가해 주세요.
              </div>
            )}
            <div className="modal-actions">
              <button className="modal-cancel" type="button" onClick={closeOperatorImportModal}>취소</button>
              <button
                className="modal-confirm"
                disabled={operatorImportTickers.length === 0}
                type="button"
                onClick={() => void importOperatorStocks()}
              >
                선택한 종목 가져오기
              </button>
            </div>
          </section>
        </div>
      )}
      {isWatchlistTypeImportOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={closeWatchlistTypeImportModal}>
          <section
            aria-labelledby="watchlist-type-import-title"
            aria-modal="true"
            className="confirm-modal operator-import-modal"
            role="dialog"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button className="modal-close-button" type="button" aria-label="닫기" onClick={closeWatchlistTypeImportModal}>×</button>
            <h3 id="watchlist-type-import-title">{otherInvestmentTypeLabel} 관심종목 불러오기</h3>
            <p>
              {currentInvestmentTypeLabel} 관심종목에 없는 {otherInvestmentTypeLabel} 종목만 가져옵니다. 남은 슬롯 {activeWatchlistRemainingSlots}개.
            </p>
            <div className="operator-import-status">
              <div className="operator-import-status-head">
                <strong>{watchlistTypeImportTickers.length}개 선택</strong>
                <button
                  className="operator-import-select-all"
                  type="button"
                  disabled={watchlistTypeImportSelectableTickers.length === 0}
                  onClick={toggleSelectAllWatchlistTypeImport}
                >
                  {isAllWatchlistTypeImportSelected ? '선택 해제' : '전체 선택'}
                </button>
              </div>
              <span>
                {activeWatchlistRemainingSlots > 0
                  ? `${activeWatchlistRemainingSlots}개까지 선택할 수 있어요. 한도에 도달하면 기존 관심종목을 제거한 뒤 다시 추가해 주세요.`
                  : `관심종목 ${MAX_WATCHLIST_ITEMS}개 한도에 도달했습니다. 기존 종목을 제거한 뒤 다시 가져올 수 있습니다.`}
              </span>
            </div>
            <div className="operator-import-list">
              {watchlistTypeImportCandidates.length > 0 ? watchlistTypeImportCandidates.map((stock) => {
                const isChecked = watchlistTypeImportTickers.includes(stock.ticker)
                const isDisabled = !isChecked && isWatchlistTypeImportSelectionFull

                return (
                  <label className={`operator-import-option ${isDisabled ? 'disabled' : ''}`} key={stock.ticker}>
                    <input
                      checked={isChecked}
                      disabled={isDisabled}
                      type="checkbox"
                      onChange={() => toggleWatchlistTypeImportTicker(stock.ticker)}
                    />
                    <span className="market-flag" aria-hidden="true">{marketFlag(stock.market)}</span>
                    <span>
                      <strong>{stock.name}</strong>
                      <small>{stock.ticker} · {displayIndustryLabel(stock.industry)}</small>
                    </span>
                  </label>
                )
              }) : (
                <div className="operator-import-empty">
                  가져올 수 있는 {otherInvestmentTypeLabel} 종목이 없습니다. 이미 모두 추가했거나 {otherInvestmentTypeLabel} 관심종목이 비어 있습니다.
                </div>
              )}
            </div>
            {isWatchlistTypeImportSelectionFull && watchlistTypeImportCandidates.length > watchlistTypeImportTickers.length && (
              <div className="operator-import-limit-message">
                남은 {activeWatchlistRemainingSlots}개를 모두 선택했습니다. 더 가져오려면 기존 관심종목을 제거한 다음 다시 추가해 주세요.
              </div>
            )}
            <div className="modal-actions">
              <button className="modal-cancel" type="button" onClick={closeWatchlistTypeImportModal}>취소</button>
              <button
                className="modal-confirm"
                disabled={watchlistTypeImportTickers.length === 0}
                type="button"
                onClick={() => void importWatchlistTypeStocks()}
              >
                선택한 종목 가져오기
              </button>
            </div>
          </section>
        </div>
      )}
      <header className={`app-header ${showViewModeHint ? 'onboarding-header' : ''}`}>
        <div className="brand">
          <img alt="공수성가 로고" className="brand-logo" src="/gongsu-logo.png" />
          <span>공수성가</span>
        </div>
        <nav className="gnb-menu" aria-label="주요 메뉴">
          {visibleGnbMenus.map((menu) => {
            const isActive = (menu === 'HOME' && currentActivePage === 'home') || (menu === '가치 분석' && currentActivePage === 'value-analysis') || (menu === '기술 분석' && currentActivePage === 'technical-analysis') || (menu === '시장 주요 이벤트' && currentActivePage === 'market-events') || (menu === '시장 트렌드' && currentActivePage === 'market-trends') || (menu === '운영 로그' && currentActivePage === 'admin-logs') || (menu === '게시판' && currentActivePage === 'board')

            return (
              <button
                className={isActive ? 'active' : ''}
                key={menu}
                type="button"
                onClick={() => {
                  if (menu === 'HOME') setActivePage('home')
                  if (menu === '가치 분석') setActivePage('value-analysis')
                  if (menu === '기술 분석') setActivePage('technical-analysis')
                  if (menu === '시장 주요 이벤트') setActivePage('market-events')
                  if (menu === '시장 트렌드') setActivePage('market-trends')
                  if (menu === '운영 로그') setActivePage('admin-logs')
                  if (menu === '게시판') setActivePage('board')
                }}
              >
                {menu}
              </button>
            )
          })}
        </nav>
        <div className="updated-text">
          <span>데이터는 분석 별로 정해진 주기에 맞춰 업데이트됩니다.</span>
          <span>공수성가 또한 실제 데이터이며, 참고할 수 있게 제공됩니다.</span>
          <span>단, 모든 투자의 책임은 본인에게 있습니다.</span>
          {isAdminUser && refreshDataMessage && (
            <strong className={`refresh-data-message ${isRefreshingData ? 'refresh-data-message-active' : ''} ${refreshDataMessage.includes('반영됐습니다') ? 'refresh-data-message-success' : ''}`}>
              {refreshDataMessage}
            </strong>
          )}
        </div>
        <div className={`segmented-tabs global-tabs view-mode-tabs ${showViewModeHint ? 'view-mode-tabs-highlight' : ''}`} aria-label="화면 기준">
          <button
            className={effectiveViewMode === 'personal' ? 'active' : ''}
            disabled={isAdminUser}
            title={isAdminUser ? '어드민 계정은 공수성가 탭만 사용할 수 있습니다.' : undefined}
            type="button"
            onClick={() => changeViewMode('personal')}
          >
            본인
          </button>
          <button className={effectiveViewMode === 'operator' ? 'active' : ''} type="button" onClick={() => changeViewMode('operator')}>
            공수성가
          </button>
          {showViewModeHint && (
            <div className="view-mode-hint">
              <div className="view-mode-hint-copy">
                <span className="view-mode-hint-kicker">TIP</span>
                <span>본인과 공수성가 데이터를 이 탭에서 바로 바꿔볼 수 있어요. 잘 모르겠다면 먼저 공수성가부터 구경하면 돼요.</span>
              </div>
              <button className="view-mode-hint-close" type="button" aria-label="안내 닫기" onClick={markViewModeHintSeen} />
            </div>
          )}
        </div>
        {userSession && !isAdminUser && (
          <button className="reset-button" type="button" onClick={() => setIsResetConfirmOpen(true)}>
            초기화
          </button>
        )}
        {isAdminUser && (
          <button className="refresh-data-button" disabled={isRefreshingData} type="button" onClick={refreshCurrentData}>
            {isRefreshingData ? '갱신 중' : '즉시 갱신'}
          </button>
        )}
        <button
          className={`login-button ${userSession ? 'logged-in-button' : ''}`}
          type="button"
          onClick={() => setIsLoginOpen(true)}
        >
          {userSession ? userSession.name : '로그인'}
        </button>
      </header>

      {currentActivePage === 'home' ? (
      <section className={`dashboard-grid ${isLongTermInvestor ? 'long-term-home-grid' : 'swing-home-grid'}`}>
        <section className={`panel trading-log-panel ${shouldDimPanelsForFirstVisitGuide ? 'dimmed-panel' : ''}`}>
          <div className="log-header">
            <div className="log-title-row">
              <h2>트레이딩 로그</h2>
              <div className="strategy-filter" aria-label="전략 필터">
                <span className="strategy-filter-label">전략</span>
                {['전체', ...strategyFilters].map((code) => (
                  <button
                    className={selectedStrategy === code ? 'active' : ''}
                    key={code}
                    type="button"
                    onClick={() => setSelectedStrategy(code)}
                  >
                    {code}
                  </button>
                ))}
              </div>
            </div>
            <div className="log-sub-row">
              <div className="log-meta">
                <p>총 투자 기간 {investingDays}일</p>
                {!isLongTermInvestor && <p>승률: {visibleWinRates}</p>}
                <p className="log-criteria-line">성공/실패: {strategyCriteriaLine}</p>
              </div>
              <button
                className="sort-button"
                type="button"
                onClick={() => setSortDirection((current) => current === 'desc' ? 'asc' : 'desc')}
              >
                정렬
                <span aria-hidden="true">{sortDirection === 'desc' ? '↓' : '↑'}</span>
              </button>
            </div>
          </div>

          <div className="asset-summary-box" aria-label="현재 자산 요약">
            {assetSummaryItems.map((item) => {
              const itemClassName = `asset-summary-item ${item.strong ? 'strong' : ''}`.trim()
              const detailTitle = item.detailTooltipRows
                ? item.detailTooltipRows.map((row) => `${row.label}: ${row.value}`).join('\n')
                : item.detail
              const detailTooltip = item.detailTooltipRows ? (
                <span className="asset-summary-tooltip" role="tooltip">
                  {item.detailTooltipRows.map((row) => (
                    <span className="asset-summary-tooltip-row" key={row.label}>
                      <span className="asset-summary-tooltip-label">{row.label}</span>
                      <strong>{row.value}</strong>
                    </span>
                  ))}
                </span>
              ) : null
              if (item.clickable) {
                return (
                  <button className={`${itemClassName} asset-summary-action`} key={item.label} type="button" onClick={item.action}>
                    <span>{item.label}</span>
                    <strong className="asset-summary-value asset-summary-button">{item.value}</strong>
                    {item.detail && (
                      <span className="asset-summary-detail-wrap" title={detailTitle}>
                        <small className="asset-summary-detail">{item.detail}</small>
                        {detailTooltip}
                      </span>
                    )}
                  </button>
                )
              }

              return (
                <div className={itemClassName} key={item.label}>
                  <span>{item.label}</span>
                  <strong className={`asset-summary-value ${item.tone ?? ''}`}>{item.value}</strong>
                  {item.detail && (
                    <span
                      className="asset-summary-detail-wrap"
                      tabIndex={0}
                      title={detailTitle}
                    >
                      <small className="asset-summary-detail">{item.detail}</small>
                      {detailTooltip}
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          <div className="sheet-wrap trading-log-scroll" key={`trades-${homeSheetResetKey}`} ref={tradingLogWheelRef}>
            <table
              className={`sheet-table trading-log-table ${isLongTermInvestor ? 'long-term-trading-log-table' : ''} ${isTradingPinned ? 'pinned-home-table' : 'unpinned-home-table'}`}
              style={tradingPinnedStyle}
            >
              <thead>
                <tr>
                  <th>No</th>
                  <th className="home-name-header">
                    <span>종목명</span>
                    <button
                      aria-label={isTradingPinned ? '트레이딩로그 종목명 고정 끄기' : '트레이딩로그 종목명 고정 켜기'}
                      aria-pressed={isTradingPinned}
                      className={`home-pin-toggle ${isTradingPinned ? 'active' : ''}`}
                      title={isTradingPinned ? '종목명 고정 끄기' : '종목명 고정 켜기'}
                      type="button"
                      onClick={toggleTradingPinned}
                    >
                      <span aria-hidden="true">📌</span>
                    </button>
                  </th>
                  <th>티커</th>
                  <th>매수 신호일</th>
                  <th>매수 신호 가격</th>
                  {!isLongTermInvestor && <th>매도 신호일</th>}
                  {!isLongTermInvestor && <th>매도 신호 가격</th>}
                  <th>전략</th>
                  <th>
                    <MetricValue
                      tooltip="매수한 종목의 산업군이 그 주 시장 트렌드 Top 3에 있으면 충족입니다. 아니면 미충족으로 표시합니다."
                      onTooltipClose={() => setActiveTooltip(null)}
                      onTooltipOpen={setActiveTooltip}
                    >
                      메가 트렌드
                    </MetricValue>
                  </th>
                  <th>{isLongTermInvestor ? '현재가(수익률)' : '가격(수익률)'}</th>
                  <th>투자금</th>
                  <th>예상 손익</th>
                  <th>보유 기간</th>
                  {!isLongTermInvestor && <th>결과</th>}
                </tr>
              </thead>
              <tbody>
                {showEmptyTradeExample && exampleStock && (
                  <tr className="example-row">
                    <td className="numbering-cell">예시</td>
                    <td className="name-data-cell">
                      <StockNameCell
                        market={exampleStock.market}
                        name={exampleStock.name}
                        onTooltipClose={() => setActiveTooltip(null)}
                        onTooltipOpen={setActiveTooltip}
                      />
                    </td>
                    <td className="ticker-cell">{exampleStock.ticker}</td>
                    <td>신호 발생 시</td>
                    <td className="number-cell">{displayCurrentPriceText(exampleStock)}</td>
                    {!isLongTermInvestor && <td className="dash-cell">-</td>}
                    {!isLongTermInvestor && <td className="dash-cell">-</td>}
                    <td><span className="example-note">매수 시그널 충족 시 기록됩니다.</span></td>
                    <td className="dash-cell">미충족</td>
                    <td className="dash-cell">-</td>
                    <td className="dash-cell">-</td>
                    <td className="dash-cell">-</td>
                    <td className="dash-cell">-</td>
                    {!isLongTermInvestor && <td><span className="example-note">예시</span></td>}
                  </tr>
                )}
                {displayedTradeRows.map(({ trade, rowNumber }) => {
                  const profileReturnPct = displayedTradeReturnPct(trade, apiStocks)
                  const returnPriceText = tradeReturnPriceText(trade, apiStocks)
                  const investedAmount = tradeInvestmentAmount(trade, portfolioSummary.amountByTradeKey)
                  const profitAmount = tradeProfitAmount(trade, apiStocks, portfolioSummary.amountByTradeKey)
                  return (
                    <tr key={tradeKey(trade)}>
                      <td className="numbering-cell">{rowNumber}</td>
                      <td className="name-data-cell">
                        <StockNameCell
                          market={tradeMarket(trade)}
                          name={tradeName(trade)}
                          onTooltipClose={() => setActiveTooltip(null)}
                          onTooltipOpen={setActiveTooltip}
                        />
                      </td>
                      <td className="ticker-cell">{trade.ticker}</td>
                      <td>{trade.buyDate}</td>
                      <td className="number-cell">{trade.buyPrice}</td>
                      {!isLongTermInvestor && <td>{trade.sellDate}</td>}
                      {!isLongTermInvestor && <td className={trade.sellPrice === '-' ? 'dash-cell' : 'number-cell'}>{trade.sellPrice}</td>}
                      <td className="strategy-data-cell">
                        <StrategyTag
                          onTooltipClose={() => setActiveTooltip(null)}
                          onTooltipOpen={setActiveTooltip}
                          strategy={trade.strategy}
                        />
                      </td>
                      <td className={megaTrendStatus(trade).startsWith('충족') ? 'mega-trend-cell positive' : 'mega-trend-cell neutral'}>
                        {megaTrendStatus(trade)}
                      </td>
                      {profileReturnPct === null ? (
                        <td className={returnPriceText === '-' ? 'dash-cell' : 'number-cell'}>{returnPriceText === '-' ? '-' : formatPriceWithReturn(returnPriceText, null)}</td>
                      ) : (
                        <td className={`number-cell ${tradeReturnClass(trade, profileReturnPct)}`}>
                          {formatPriceWithReturn(returnPriceText, profileReturnPct)}
                        </td>
                      )}
                      <td className="number-cell">{formatKrwAmount(investedAmount)}</td>
                      <td className={`number-cell ${tradeProfitClass(profitAmount)}`}>{profitAmount === null ? '-' : formatKrwAmount(profitAmount)}</td>
                      <td>{holdingPeriodDays(trade)}</td>
                      {!isLongTermInvestor && (
                        <td>
                          <ResultBadge
                            onTooltipClose={() => setActiveTooltip(null)}
                            onTooltipOpen={setActiveTooltip}
                            trade={trade}
                          />
                        </td>
                      )}
                    </tr>
                  )
                })}
                {Array.from({ length: tradeBlankRows }).map((_, index) => (
                  <tr className="blank-row" key={`trade-blank-${index}`}>
                    {Array.from({ length: isLongTermInvestor ? 11 : 14 }).map((_, cellIndex) => (
                      <td className={cellIndex === 0 ? 'numbering-cell' : undefined} key={`trade-blank-${index}-${cellIndex}`}>{cellIndex === 0 ? '\u00a0' : ''}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="right-column">
          <section className="panel watchlist-panel">
            <div className="section-heading">
              <div className="section-title-inline">
                <h2>관심 종목</h2>
                <span>총 {tableStocks.length}개</span>
              </div>
              <div className="heading-actions">
                {canEditCurrentWatchlist ? (
                  <>
                    {isCurrentWatchlistFull && (
                      <span className="watchlist-limit-copy">
                        관심 종목은 최대 {MAX_WATCHLIST_ITEMS}개까지 등록할 수 있습니다.
                        <br />
                        새 종목을 추가하려면 기존 관심 종목을 제거해 주세요.
                      </span>
                    )}
                    {selectedTickers.length > 0 && (
                      <button className="remove-selected-button" type="button" onClick={removeSelectedStocks}>
                        제거
                      </button>
                    )}
                    <button
                      className={`add-stock-button ${isCurrentWatchlistFull ? 'watchlist-limit-button' : ''}`}
                      disabled={isCurrentWatchlistFull}
                      ref={addStockButtonRef}
                      type="button"
                      onClick={requestAddStock}
                    >
                      + 추가
                    </button>
                  </>
                ) : (
                  <button
                    aria-disabled="true"
                    className="add-stock-button readonly-mode-button"
                    tabIndex={-1}
                    type="button"
                  >
                    공수성가 기준
                  </button>
                )}
                <div className="watchlist-sort-menu" ref={watchlistSortMenuRef}>
                  <button
                    aria-expanded={isWatchlistSortOpen}
                    aria-label={`관심 종목 정렬: ${currentWatchlistSortOption.label}`}
                    className={`sort-icon-button ${isWatchlistSortOpen ? 'active' : ''}`}
                    type="button"
                    onClick={() => setIsWatchlistSortOpen((current) => !current)}
                  >
                    <svg aria-hidden="true" viewBox="0 0 24 24">
                      <path d="M4 7h10" />
                      <path d="M18 7h2" />
                      <path d="M16 5v4" />
                      <path d="M4 12h3" />
                      <path d="M11 12h9" />
                      <path d="M9 10v4" />
                      <path d="M4 17h8" />
                      <path d="M16 17h4" />
                      <path d="M14 15v4" />
                    </svg>
                  </button>
                  {isWatchlistSortOpen && (
                    <div className="watchlist-sort-popover">
                      <div className="watchlist-sort-popover-header">
                        <strong>관심종목 정렬</strong>
                        <span>지금 보고 싶은 기준 하나만 선택하세요.</span>
                      </div>
                      <div className="watchlist-sort-options">
                        {visibleWatchlistSortOptions.map((option) => (
                          <button
                            className={watchlistSortSettings.primary === option.value ? 'active' : ''}
                            key={option.value}
                            type="button"
                            onClick={() => updateWatchlistSortSetting(option.value)}
                          >
                            <span>
                              <strong>{option.label}</strong>
                              <small>{option.description}</small>
                            </span>
                            {watchlistSortSettings.primary === option.value && <b aria-hidden="true">✓</b>}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {addStockInlineControl}

            <div className="sheet-wrap watchlist-sheet" key={`watchlist-${homeSheetResetKey}`} ref={watchlistSheetWheelRef}>
              {tableStocks.length === 0 ? (
                <div className="watchlist-empty-panel">
                  <div className="empty-watchlist">
                    <strong>관심 종목이 없습니다.</strong>
                    <span>
                      {isOperatorDataMode ? (
                        '포트폴리오 조정 중, 조금만 기다려 주세요.'
                      ) : '먼저 종목을 추가해 주세요.'}
                    </span>
                    {canEditCurrentWatchlist && (
                      <button type="button" onClick={requestAddStock}>관심 종목 추가</button>
                    )}
                  </div>
                </div>
              ) : (
                <table
                  className={`sheet-table watchlist-table ${canEditCurrentWatchlist ? 'editable-home-table' : 'readonly-home-table'} ${isWatchlistPinned ? 'pinned-home-table' : 'unpinned-home-table'}`}
                  style={watchlistPinnedStyle}
                >
                  <thead>
                    <tr>
                      {canEditCurrentWatchlist && <th>선택</th>}
                      <th>No</th>
                      <th className="home-name-header">
                        <span>종목명</span>
                        <button
                          aria-label={isWatchlistPinned ? '관심 종목명 고정 끄기' : '관심 종목명 고정 켜기'}
                          aria-pressed={isWatchlistPinned}
                          className={`home-pin-toggle ${isWatchlistPinned ? 'active' : ''}`}
                          title={isWatchlistPinned ? '종목명 고정 끄기' : '종목명 고정 켜기'}
                          type="button"
                          onClick={toggleWatchlistPinned}
                        >
                          <span aria-hidden="true">📌</span>
                        </button>
                      </th>
                      <th>티커</th>
                      <th>산업군</th>
                      <th>
                        <MetricValue
                          tooltip={FAIR_PRICE_RANGE_TOOLTIP}
                          onTooltipClose={() => setActiveTooltip(null)}
                          onTooltipOpen={setActiveTooltip}
                        >
                          적정 주가 범위
                        </MetricValue>
                      </th>
                      <th>현재가</th>
                      <th>가치 분석</th>
                      <th>기술 분석</th>
                      <th>시스템 보유</th>
                      <th>매수 전략</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableStocks.map((stock, index) => {
                      const displayValuation = displayStockValuation(stock)
                      const displayOpinion = isLongTermInvestor && stock.opinion === '매도' ? '관망' : displayStockOpinion(stock)
                      const isHolding = isSystemHolding(stock.ticker, scopedTrades)
                      const buyStrategies = displayStrategiesForStock(stock, scopedTrades)

                      return (
                      <tr key={stock.ticker}>
                        {canEditCurrentWatchlist && (
                          <td className="checkbox-cell">
                            <input
                              aria-label={`${stock.name} 선택`}
                              checked={selectedTickers.includes(stock.ticker)}
                              onChange={() => toggleSelectedTicker(stock.ticker)}
                              type="checkbox"
                            />
                          </td>
                        )}
                        <td className="numbering-cell">
                          <span>{index + 1}</span>
                        </td>
                        <td className="name-data-cell">
                          <StockNameCell
                            market={stock.market}
                            name={stock.name}
                            onTooltipClose={() => setActiveTooltip(null)}
                            onTooltipOpen={setActiveTooltip}
                          />
                        </td>
                        <td className="ticker-cell">{stock.ticker}</td>
                        <td className="industry-cell">{displayIndustryLabel(stock.industry)}</td>
                        <td className="number-cell">
                          {isFairPriceUnavailable(stock) ? (
                            <span className="unavailable-value-label">{displayFairPriceText(stock)}</span>
                          ) : isPendingValue(stock.fairPrice) ? (
                            <span className="pending-update-label">{fairPricePendingLabel}</span>
                          ) : displayFairPriceText(stock)}
                        </td>
                        <td className="number-cell">
                          {isPendingValue(stock.currentPrice) ? (
                            <span className="pending-update-label">{currentPricePendingLabel}</span>
                          ) : displayCurrentPriceText(stock)}
                        </td>
                        <td><span className={`status-badge ${valuationBadgeClass(displayValuation)}`}>{displayValuation}</span></td>
                        <td><span className={`status-badge ${statusClass(displayOpinion)}`}>{displayOpinion}</span></td>
                        <td>
                          {isHolding ? '보유 중' : '미보유'}
                        </td>
                        <td className={isHolding ? 'strategy-data-cell' : 'strategy-data-cell dash-cell'}>
                          {isHolding && buyStrategies.length > 0 ? buyStrategies.map((strategy) => (
                            <StrategyTag
                              key={strategy}
                              onTooltipClose={() => setActiveTooltip(null)}
                              onTooltipOpen={setActiveTooltip}
                              strategy={strategy}
                            />
                          )) : '-'}
                        </td>
                      </tr>
                      )
                    })}
                    {Array.from({ length: watchlistBlankRows }).map((_, index) => (
                      <tr className="blank-row" key={`watchlist-blank-${index}`}>
                        {canEditCurrentWatchlist && <td></td>}
                        <td className="numbering-cell">&nbsp;</td>
                        <td>&nbsp;</td>
                        <td></td>
                        <td></td>
                        <td></td>
                        <td></td>
                        <td></td>
                        <td></td>
                        <td></td>
                        <td></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section className={`panel ${shouldDimPanelsForFirstVisitGuide ? 'dimmed-panel' : ''}`}>
            <div className="section-heading holding-heading">
              <div className="section-title-inline">
                <h2>보유중인 종목 (전략 단위)</h2>
                <span>총 {scopedOpenTrades.length}개</span>
              </div>
              <div className="heading-actions">
                {canManageHoldingTrades && (
                  <>
                    <button
                      aria-hidden={selectedHoldingTradeKeys.length === 0}
                      className={`liquidation-selected-button ${selectedHoldingTradeKeys.length === 0 ? 'reserved-action-button' : ''}`}
                      tabIndex={selectedHoldingTradeKeys.length === 0 ? -1 : 0}
                      type="button"
                      onClick={() => {
                        if (selectedHoldingTradeKeys.length > 0 && !isSavingTradeLogs) openHoldingLiquidationModal()
                      }}
                    >
                      {isSavingTradeLogs ? '저장 중' : '청산'}
                    </button>
                    <button
                      aria-hidden={selectedHoldingTradeKeys.length === 0}
                      className={`remove-selected-button ${selectedHoldingTradeKeys.length === 0 ? 'reserved-action-button' : ''}`}
                      tabIndex={selectedHoldingTradeKeys.length === 0 ? -1 : 0}
                      type="button"
                      onClick={() => {
                        if (selectedHoldingTradeKeys.length > 0 && !isSavingTradeLogs) setIsHoldingDeleteConfirmOpen(true)
                      }}
                    >
                      삭제
                    </button>
                  </>
                )}
              </div>
            </div>

            <p className="section-note">시스템 기준 보유 종목으로, 실제 보유 여부와 다를 수 있어 개인 판단이 필요합니다.</p>

            <div className="sheet-wrap holding-sheet" key={`holdings-${homeSheetResetKey}`} ref={holdingSheetWheelRef}>
              <table
                className={`sheet-table holding-table ${isLongTermInvestor ? 'long-term-holding-table' : ''} ${canManageHoldingTrades ? 'editable-home-table' : 'readonly-home-table'} ${isHoldingPinned ? 'pinned-home-table' : 'unpinned-home-table'}`}
                style={holdingPinnedStyle}
              >
                <thead>
                  <tr>
                    {canManageHoldingTrades && <th>선택</th>}
                    <th>No</th>
                    <th className="home-name-header">
                      <span>종목명</span>
                      <button
                        aria-label={isHoldingPinned ? '보유 종목명 고정 끄기' : '보유 종목명 고정 켜기'}
                        aria-pressed={isHoldingPinned}
                        className={`home-pin-toggle ${isHoldingPinned ? 'active' : ''}`}
                        title={isHoldingPinned ? '종목명 고정 끄기' : '종목명 고정 켜기'}
                        type="button"
                        onClick={toggleHoldingPinned}
                      >
                        <span aria-hidden="true">📌</span>
                      </button>
                    </th>
                    <th>티커</th>
                    <th>매수 신호일</th>
                    <th>매수 신호 가격</th>
                    <th>매수 전략</th>
                    <th>현재가(수익률)</th>
                    <th>보유 기간</th>
                  </tr>
                </thead>
                <tbody>
                  {showEmptyHoldingExample && exampleStock && (
                    <tr className="example-row">
                      {canManageHoldingTrades && <td></td>}
                      <td className="numbering-cell">예시</td>
                      <td className="name-data-cell">
                        <StockNameCell
                          market={exampleStock.market}
                          name={exampleStock.name}
                          onTooltipClose={() => setActiveTooltip(null)}
                          onTooltipOpen={setActiveTooltip}
                        />
                      </td>
                      <td className="ticker-cell">{exampleStock.ticker}</td>
                      <td>신호 발생 시</td>
                      <td className="number-cell">{displayCurrentPriceText(exampleStock)}</td>
                      <td className="holding-example-note-cell"><span className="example-note">보유 전환 시 표시됩니다.</span></td>
                      <td className="dash-cell">-</td>
                      <td className="dash-cell">-</td>
                    </tr>
                  )}
                  {scopedOpenTrades.map((trade, index) => {
                    const openReturnPct = currentReturnPct(trade, apiStocks)
                    const currentPriceText = tradeCurrentPriceText(trade, apiStocks)

                    return (
                      <tr key={`open-${tradeKey(trade)}`}>
                        {canManageHoldingTrades && (
                          <td className="checkbox-cell">
                            <input
                              aria-label={`${tradeName(trade)} 보유 항목 선택`}
                              checked={selectedHoldingTradeKeys.includes(tradeKey(trade))}
                              disabled={isSavingTradeLogs}
                              onChange={() => toggleSelectedHoldingTrade(tradeKey(trade))}
                              type="checkbox"
                            />
                          </td>
                        )}
                        <td className="numbering-cell">{index + 1}</td>
                        <td className="name-data-cell">
                          <StockNameCell
                            market={tradeMarket(trade)}
                            name={tradeName(trade)}
                            onTooltipClose={() => setActiveTooltip(null)}
                            onTooltipOpen={setActiveTooltip}
                          />
                        </td>
                        <td className="ticker-cell">{trade.ticker}</td>
                        <td>{trade.buyDate}</td>
                        <td className="number-cell">{trade.buyPrice}</td>
                        <td className="strategy-data-cell">
                          <StrategyTag
                            onTooltipClose={() => setActiveTooltip(null)}
                            onTooltipOpen={setActiveTooltip}
                            strategy={trade.strategy}
                          />
                        </td>
                        {currentPriceText === '-' ? (
                          <td className="dash-cell">-</td>
                        ) : (
                          <td className={`number-cell ${openReturnPct === null ? '' : returnClass(openReturnPct)}`}>
                            {formatPriceWithReturn(currentPriceText, openReturnPct)}
                          </td>
                        )}
                        <td>{holdingPeriodDays(trade)}</td>
                      </tr>
                    )
                  })}
                  {Array.from({ length: holdingBlankRows }).map((_, index) => (
                    <tr className="blank-row" key={`holding-blank-${index}`}>
                      {canManageHoldingTrades && <td></td>}
                      <td className="numbering-cell">&nbsp;</td>
                      <td></td>
                      <td>&nbsp;</td>
                      <td></td>
                      <td></td>
                      <td></td>
                      <td></td>
                      <td></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </section>
      ) : currentActivePage === 'market-events' ? (
        <MarketEventsPage
          groups={apiMarketEventGroups}
          yearLabel={marketEventYearLabel}
          months={marketEventMonths}
          isAdmin={isAdminUser}
          isSaving={isSavingMarketEvents}
          isDirty={isMarketEventsDirty}
          onTooltipClose={() => setActiveTooltip(null)}
          onTooltipOpen={setActiveTooltip}
          onYearLabelChange={updateMarketEventYearLabel}
          onMonthChange={updateMarketEventMonth}
          onEventChange={updateMarketEventEntry}
          onSave={saveMarketEventEntries}
        />
      ) : currentActivePage === 'market-trends' ? (
        <MarketTrendsPage
          rows={apiMarketTrendRows}
          updateLabel={formatUpdateLabel(apiMetas.marketTrends)}
          isAdmin={isAdminUser}
          selectedRowKeys={selectedMarketTrendRowKeys}
          isSaving={isSavingMarketTrends}
          onToggleRow={toggleSelectedMarketTrendRow}
          onDeleteSelected={openMarketTrendDeleteConfirm}
        />
      ) : currentActivePage === 'admin-logs' && isAdminUser ? (
        <AdminLogsPage logs={apiLogs} isLoading={isLoadingApiLogs} onRefresh={loadApiLogs} />
      ) : currentActivePage === 'board' && isAdminUser ? (
        <BoardPage
          category={boardCategory}
          content={boardContent}
          commentDrafts={boardCommentDrafts}
          currentUserId={boardCurrentUserId(userSession)}
          filter={boardFilter}
          page={boardPage}
          posts={boardPosts}
          selectedPostIds={selectedBoardPostIds}
          showMineOnly={showMineOnly}
          sortDirection={boardSortDirection}
          onCategoryChange={setBoardCategory}
          onCommentChange={updateBoardCommentDraft}
          onContentChange={setBoardContent}
          onDeletePost={deleteBoardPost}
          onFilterChange={setBoardFilter}
          onHideSelectedPosts={hideSelectedBoardPosts}
          onPageChange={setBoardPage}
          onRemoveSelectedPosts={removeSelectedBoardPosts}
          onSelectedPostIdsChange={setSelectedBoardPostIds}
          onShowMineOnlyChange={setShowMineOnly}
          onSortDirectionChange={setBoardSortDirection}
          onSubmit={submitBoardPost}
          onSubmitComment={submitBoardComment}
        />
      ) : currentActivePage === 'value-analysis' ? (
        <ValueAnalysisPage
          stocks={tableStocks}
          viewMode={effectiveViewMode}
          valuationRows={apiValuationMetrics}
          updateLabel={formatUpdateLabel(apiMetas.valuation)}
          addStockControl={addStockInlineControl}
          onTooltipClose={() => setActiveTooltip(null)}
          onTooltipOpen={setActiveTooltip}
          onAddStock={requestAddStock}
        />
      ) : (
        <TechnicalAnalysisPage
          stocks={tableStocks}
          viewMode={effectiveViewMode}
          marketSnapshot={apiMarketSnapshot}
          technicalRows={apiTechnicalRows}
          tradeLogs={systemTradeLogs}
          hideSellSignals={isLongTermInvestor}
          updateLabel={formatUpdateLabel(apiMetas.technical)}
          addStockControl={addStockInlineControl}
          onTooltipClose={() => setActiveTooltip(null)}
          onTooltipOpen={setActiveTooltip}
          onAddStock={requestAddStock}
        />
      )}
      {activeTooltip && (
        <div
          className={`floating-tooltip mobile-floating-tooltip ${currentActivePage === 'market-events' ? 'market-events-floating-tooltip' : ''} ${activeTooltip.className ?? ''}`}
          style={{
            left: activeTooltip.x,
            top: activeTooltip.y,
          }}
          onClick={(event) => event.stopPropagation()}
        >
          {activeTooltip.text}
        </div>
      )}
      {shouldShowInvestmentProfileOnboarding && (
        <div className="modal-backdrop" role="presentation">
          <section aria-modal="true" className="confirm-modal investment-profile-modal" role="dialog">
            <button className="modal-close-button" type="button" aria-label="닫기" onClick={closeInvestmentProfileOnboarding}>
              ×
            </button>
            <div className="investment-profile-header">
              <span>첫 설정</span>
              <h3>투자성향을 선택해 주세요</h3>
              <p>원하는 성향을 선택한 뒤 확인을 눌러 주세요. 닫으면 기본값인 천천히 모아가는 투자자 (가치 투자)로 시작합니다.</p>
            </div>
            <div className="investment-option-grid">
              {investmentProfileOptions.map((option) => (
                <button
                  className={`investment-option-card ${onboardingInvestmentType === option.value ? 'active' : ''}`}
                  key={option.value}
                  type="button"
                  onClick={() => setOnboardingInvestmentType(option.value)}
                >
                  <strong>{option.title}</strong>
                  <span>{option.description}</span>
                  <ul>
                    {option.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}
                  </ul>
                </button>
              ))}
            </div>
            <div className="modal-actions investment-profile-actions">
              <button className="modal-confirm" type="button" onClick={confirmInvestmentProfileOnboarding}>
                확인
              </button>
            </div>
          </section>
        </div>
      )}
      {isLoginOpen && (
        <div className="modal-backdrop" role="presentation">
          <form
            aria-modal="true"
            className={`confirm-modal login-modal ${userSession && authMode !== 'reset' ? 'account-modal' : ''}`}
            role="dialog"
            onSubmit={submitLogin}
          >
            <button className="modal-close-button" type="button" aria-label="닫기" onClick={closeLoginModal}>
              ×
            </button>
            <h3>{userSession && authMode !== 'reset' ? '내 계정' : authMode === 'recover' ? '비밀번호 찾기' : authMode === 'reset' ? '비밀번호 변경' : '로그인'}</h3>
            {userSession && authMode !== 'reset' ? (
              <>
                {authInfoMessage && (
                  <div className="recovery-sent-card account-auth-feedback">
                    {authInfoMessage.split('\n').map((line, index) => (
                      index === 0 ? <strong key={`${line}-${index}`}>{line}</strong> : <span key={`${line}-${index}`}>{line}</span>
                    ))}
                  </div>
                )}
                <div className="account-settings-stack">
                  <div className="login-account-card">
                    <span>로그인 계정</span>
                    <strong>{userSession.email}</strong>
                  </div>
                  <div className="account-alert-card notification-channel-card">
                    <div className="account-alert-header">
                      <span>알림 수신처</span>
                    </div>
                    <div className="notification-channel-options">
                      <div className="notification-channel-option">
                        <button
                          className={`notification-channel-button email-channel-button ${isEmailNotificationChannel ? 'active' : ''}`}
                          disabled={isEmailNotificationChannel}
                          type="button"
                          onClick={selectEmailNotificationChannel}
                        >
                          <span className="notification-integration-logo email-logo" aria-hidden="true">@</span>
                          <span>
                            <strong>이메일</strong>
                            <small>{isEmailNotificationChannel ? '수신 중' : '메일로 받기'}</small>
                          </span>
                        </button>
                      </div>
                      {notificationIntegrationOptions.map((option) => {
                        const isConnected = isNotificationIntegrationConnected(option.channel)
                        const isActive = notificationPreferences.notificationChannel === option.channel
                        const isUnavailable = Boolean(option.disabled)
                        const isConnecting = connectingNotificationChannel === option.channel

                        return (
                          <div
                            className={`notification-channel-option ${isConnected && !isUnavailable ? 'connected' : ''}`}
                            key={option.channel}
                          >
                            <button
                              className={`notification-channel-button ${option.channel === 'kakaoTalk' ? 'kakao-card' : 'slack-card'} ${isActive ? 'active' : ''} ${isUnavailable ? 'unavailable' : ''}`}
                              disabled={isActive || isUnavailable || isConnecting}
                              type="button"
                              onClick={() => {
                                if (isConnected) {
                                  selectNotificationIntegrationChannel(option.channel)
                                  return
                                }
                                void connectNotificationChannel(option.channel)
                              }}
                            >
                              <span className="notification-integration-logo" aria-hidden="true">
                                {option.channel === 'slack' ? (
                                  <span className="slack-logo-mark">
                                    <i className="slack-dot slack-dot-green"></i>
                                    <i className="slack-dot slack-dot-blue"></i>
                                    <i className="slack-dot slack-dot-yellow"></i>
                                    <i className="slack-dot slack-dot-red"></i>
                                  </span>
                                ) : (
                                  <img alt="" src={option.logoSrc} />
                                )}
                              </span>
                              <span>
                                <strong>{option.shortTitle}</strong>
                                <small>{isUnavailable ? '비용 문제로 당분간 도입 계획 없음' : isConnecting ? '연동 중' : isActive ? '수신 중' : isConnected ? '연동됨' : '연동'}</small>
                              </span>
                            </button>
                            {isConnected && !isUnavailable && (
                              <button
                                className="notification-channel-disconnect"
                                type="button"
                                onClick={() => disconnectNotificationChannel(option.channel)}
                              >
                                해제
                              </button>
                            )}
                          </div>
                        )
                      })}
                    </div>
                    {isEmailNotificationChannel && (
                      <label className="account-alert-email-field notification-channel-email-field">
                        <span>알림 받을 이메일</span>
                        <input
                          autoComplete="email"
                          inputMode="email"
                          placeholder={userSession.email}
                          type="email"
                          value={notificationPreferences.recipientEmail}
                          onChange={(event) => updateNotificationRecipientEmail(event.target.value)}
                        />
                        <small>비워두면 가입한 이메일({userSession.email})을 사용합니다.</small>
                      </label>
                    )}
                  </div>
                  <div className="account-alert-card">
                    <div className="account-alert-header">
                      <span>알림 설정</span>
                    </div>
                    {[...notificationOptions, ...(isAdminUser ? adminNotificationOptions : [])].map((option) => (
                      <label className="account-alert-toggle" key={option.key}>
                        <span>
                          <strong>{option.title}</strong>
                          <small>{option.description}</small>
                        </span>
                        <input
                          checked={notificationPreferences[option.key]}
                          type="checkbox"
                          onChange={(event) => updateNotificationPreference(option.key, event.target.checked)}
                        />
                      </label>
                    ))}
                  </div>
                  <div className="account-alert-card investment-settings-card">
                    <div className="account-alert-header">
                      <span>성향</span>
                      <small>성향에 따라 신호가 달라집니다.</small>
                    </div>
                    <div className="investment-option-grid compact">
                      {investmentProfileOptions.map((option) => (
                        <button
                          className={`investment-option-card ${displayedInvestmentType === option.value ? 'active' : ''}`}
                          key={option.value}
                          type="button"
                          onClick={() => selectInvestmentType(option.value)}
                        >
                          <strong>{option.title}</strong>
                          <span>{option.description}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                {canUseAccountSwitch && (
                  <div className="account-bypass-card">
                    <span>테스트 전환</span>
                    <div className="account-bypass-actions">
                      <button
                        className={!isAdminUser ? 'active' : ''}
                        type="button"
                        onClick={(event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          switchTestSession('user')
                        }}
                      >
                        일반 계정
                      </button>
                      <button
                        className={isAdminUser ? 'active' : ''}
                        type="button"
                        onClick={(event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          switchTestSession('admin')
                        }}
                      >
                        어드민 계정
                      </button>
                    </div>
                  </div>
                )}
                <div className="modal-actions auth-modal-actions">
                  <button className="modal-confirm logout-confirm auth-submit-button" type="button" onClick={logout}>
                    로그아웃
                  </button>
                </div>
                <button className="auth-secondary-text-button" type="button" onClick={() => void logoutAndOpenLogin()}>
                  다른 메일로 로그인
                </button>
                {accountDeleteError && (
                  <span className="login-error account-delete-error">
                    {accountDeleteError.split('\n').map((line, index) => (
                      <Fragment key={`${line}-${index}`}>
                        {line}
                        {index < accountDeleteError.split('\n').length - 1 && <br />}
                      </Fragment>
                    ))}
                  </span>
                )}
                <div className="account-delete-footer">
                  <button
                    className="account-delete-text-button"
                    type="button"
                    onClick={() => {
                      setAccountDeleteError('')
                      setIsAccountDeleteConfirmOpen(true)
                    }}
                  >
                    회원탈퇴
                  </button>
                </div>
              </>
            ) : (
              <>
                {authMode !== 'recover' && authMode !== 'reset' ? (
                  <div className="auth-mode-tabs" aria-label="인증 방식">
                    <button className={authMode === 'login' ? 'active' : ''} type="button" onClick={() => switchAuthMode('login')}>
                      로그인
                    </button>
                    <button className={authMode === 'signup' ? 'active' : ''} type="button" onClick={() => switchAuthMode('signup')}>
                      회원가입
                    </button>
                  </div>
                ) : (
                  <button className="auth-back-button" type="button" onClick={() => switchAuthMode('login')}>
                    로그인으로 돌아가기
                  </button>
                )}
                <p>{authMode === 'login' ? '가입한 이메일과 비밀번호로 로그인해 주세요.' : authMode === 'signup' ? '이메일 인증으로 계정을 만들어 주세요.' : authMode === 'reset' ? '새 비밀번호를 입력해 변경을 완료해 주세요.' : '가입한 이메일을 입력하면 비밀번호 재설정 안내를 받을 수 있습니다.'}</p>
                {serviceStatusMessage && (
                  <div className="recovery-sent-card">
                    <strong>{isSupabaseConfigured ? '계정 동기화 중입니다.' : '서비스 계정 설정이 필요합니다.'}</strong>
                    <span>{serviceStatusMessage}</span>
                  </div>
                )}
                {canUseLocalAuthBypass && authMode !== 'reset' && (
                  <div className="account-bypass-card">
                    <span>로컬 테스트 우회</span>
                    <div className="account-bypass-actions">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          switchTestSession('user')
                        }}
                      >
                        일반 계정으로 입장
                      </button>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          switchTestSession('admin')
                        }}
                      >
                        어드민 계정으로 입장
                      </button>
                    </div>
                  </div>
                )}
                {authMode !== 'reset' && (
                  <label className="login-field">
                    <span>이메일</span>
                  <input
                    autoFocus
                    aria-invalid={shouldShowEmailValidation}
                    value={loginEmail}
                    onChange={(event) => {
                      setLoginEmail(event.target.value)
                      setLoginError('')
                      setIsRecoverySent(false)
                    }}
                    placeholder="name@example.com"
                    type="email"
                    />
                  </label>
                )}
                {authMode !== 'reset' && shouldShowEmailValidation && <span className="login-error">이메일 형식이 올바르지 않습니다.</span>}
                {authMode !== 'recover' && (
                  <>
                    <label className="login-field">
                      <span>비밀번호</span>
                      <input
                        aria-invalid={shouldShowPasswordValidation}
                        value={loginPassword}
                        onChange={(event) => {
                          setLoginPassword(event.target.value)
                          setLoginError('')
                        }}
                        placeholder="8자 이상"
                        type="password"
                      />
                    </label>
                    {shouldShowPasswordValidation && <span className="login-error">비밀번호는 8자 이상이어야 합니다.</span>}
                    {authMode === 'login' && (
                      <button className="forgot-password-button" type="button" onClick={() => switchAuthMode('recover')}>
                        비밀번호를 잊으셨나요?
                      </button>
                    )}
                    {(authMode === 'signup' || authMode === 'reset') && (
                      <label className="login-field">
                        <span>비밀번호 확인</span>
                        <input
                          aria-invalid={shouldShowPasswordConfirmValidation}
                          value={loginPasswordConfirm}
                          onChange={(event) => {
                            setLoginPasswordConfirm(event.target.value)
                            setLoginError('')
                          }}
                          placeholder="비밀번호 재입력"
                          type="password"
                        />
                      </label>
                    )}
                    {shouldShowPasswordConfirmValidation && <span className="login-error">비밀번호가 일치하지 않습니다.</span>}
                  </>
                )}
                {authInfoMessage && (
                  <div className="recovery-sent-card">
                    {authInfoMessage.split('\n').map((line, index) => (
                      index === 0 ? <strong key={line}>{line}</strong> : <span key={line}>{line}</span>
                    ))}
                    {signupConfirmationEmail && (
                      <button className="auth-resend-button" type="button" onClick={() => void resendSignupConfirmation()}>
                        확인 메일 다시 보내기
                      </button>
                    )}
                  </div>
                )}
                {loginError && <span className="login-error">{loginError}</span>}
                <div className="modal-actions auth-modal-actions">
                  <button className="modal-confirm auth-submit-button" disabled={isAuthSubmitDisabled} type="submit">
                    {authMode === 'login' ? '로그인' : authMode === 'signup' ? '회원가입' : authMode === 'reset' ? '비밀번호 변경하기' : '재설정 안내 받기'}
                  </button>
                </div>
              </>
            )}
          </form>
        </div>
      )}
      {isResetConfirmOpen && (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="confirm-modal" role="dialog">
            <button className="modal-close-button" type="button" aria-label="닫기" onClick={() => setIsResetConfirmOpen(false)}>×</button>
            <h3>{isAdminUser ? '공수성가 기록을 모두 초기화할까요?' : '본인 기록을 모두 초기화할까요?'}</h3>
            <p>
              {isAdminUser
                ? '어드민 계정에서는 본인 탭과 공수성가 탭이 같은 데이터를 사용합니다. 초기화하면 공수성가 관심 종목 데이터가 삭제됩니다.'
                : '본인 관심 종목, 보유중인 종목, 트레이딩 로그 등 시스템에 기록된 본인 데이터를 모두 삭제합니다. 단, 공수성가 데이터는 유지됩니다.'}
            </p>
            <div className="modal-actions">
              <button className="modal-cancel" type="button" onClick={() => setIsResetConfirmOpen(false)}>
                취소
              </button>
              <button className="modal-confirm" type="button" onClick={resetSystemRecords}>
                초기화
              </button>
            </div>
          </div>
        </div>
      )}
      {pendingBoardDeleteIds.length > 0 && (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="confirm-modal" role="dialog">
            <button className="modal-close-button" type="button" aria-label="닫기" onClick={() => setPendingBoardDeleteIds([])}>×</button>
            <h3>게시글을 삭제할까요?</h3>
            <p>
              선택한 게시글 {pendingBoardDeleteIds.length}개를 삭제합니다. 삭제한 게시글은 다시 되돌릴 수 없습니다.
            </p>
            <div className="modal-actions">
              <button className="modal-cancel" type="button" onClick={() => setPendingBoardDeleteIds([])}>
                취소
              </button>
              <button className="modal-confirm" type="button" onClick={confirmBoardPostDeletion}>
                삭제
              </button>
            </div>
          </div>
        </div>
      )}
      {isAccountDeleteConfirmOpen && (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="confirm-modal account-delete-modal" role="dialog">
            <button
              className="modal-close-button"
              disabled={isDeletingAccount}
              type="button"
              aria-label="닫기"
              onClick={() => setIsAccountDeleteConfirmOpen(false)}
            >
              ×
            </button>
            <h3>정말 회원탈퇴할까요?</h3>
            <p>
              계정, 관심종목, 투자 설정, 개인 트레이딩 로그, 게시글과 댓글, 알림 연동 정보가 DB에서 삭제됩니다.
              삭제 후에는 되돌릴 수 없습니다.
            </p>
            <div className="modal-actions">
              <button className="modal-cancel" disabled={isDeletingAccount} type="button" onClick={() => setIsAccountDeleteConfirmOpen(false)}>
                취소
              </button>
              <button className="modal-confirm danger-confirm" disabled={isDeletingAccount} type="button" onClick={() => void deleteAccount()}>
                {isDeletingAccount ? '탈퇴 처리 중' : '회원탈퇴'}
              </button>
            </div>
          </div>
        </div>
      )}
      {contributionDraft && (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="confirm-modal amount-edit-modal" role="dialog">
            <button className="modal-close-button" type="button" aria-label="닫기" onClick={() => setContributionDraft(null)}>×</button>
            {contributionSettingsMode === 'cash' ? (
              <>
                <h3>현금 투입 설정</h3>
                <p>초기 자금과 정기 입금액을 기준으로 보유 현금액이 늘어납니다. 매수 신호가 새로 잡힐 때만 현재 투자성향의 슬롯 비중으로 투자금을 배정합니다.</p>
                <label className="login-field">
                  <span>초기 자금</span>
                  <input
                    autoFocus
                    inputMode="numeric"
                    value={amountInputValue(contributionDraft.initialCapital)}
                    onChange={(event) => setContributionDraft((current) => current ? { ...current, initialCapital: amountDraftValue(event.target.value) } : current)}
                  />
                </label>
                <label className="login-field">
                  <span>입금 주기</span>
                  <select
                    value={contributionDraft.frequency}
                    onChange={(event) => setContributionDraft((current) => current ? { ...current, frequency: event.target.value as ContributionFrequency } : current)}
                  >
                    <option value="weekly">매주</option>
                    <option value="monthly">매월</option>
                  </select>
                </label>
                {contributionDraft.frequency === 'weekly' ? (
                  <label className="login-field">
                    <span>입금 요일</span>
                    <select
                      value={contributionDraft.dayOfWeek}
                      onChange={(event) => setContributionDraft((current) => current ? { ...current, dayOfWeek: event.target.value } : current)}
                    >
                      {weekdayOptions.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label className="login-field">
                    <span>입금일</span>
                    <input
                      inputMode="numeric"
                      max="31"
                      min="1"
                      step="1"
                      value={contributionDraft.dayOfMonth}
                      onChange={(event) => setContributionDraft((current) => current ? { ...current, dayOfMonth: event.target.value } : current)}
                    />
                    {contributionDayValidationMessage && (
                      <span className={isContributionDayInvalid ? 'field-message field-message-error' : 'field-message field-message-note'}>
                        {contributionDayValidationMessage}
                      </span>
                    )}
                  </label>
                )}
                <label className="login-field">
                  <span>입금액</span>
                  <input
                    inputMode="numeric"
                    value={amountInputValue(contributionDraft.amount)}
                    onChange={(event) => setContributionDraft((current) => current ? { ...current, amount: amountDraftValue(event.target.value) } : current)}
                  />
                </label>
              </>
            ) : (
              <>
                <h3>{displayedAllocationLabel} 투자금 배정</h3>
                <p>{displayedAllocationDescription}</p>
                <div className="allocation-rule-note">
                  <strong>현재 배정 기준</strong>
                  <span>{displayedAllocationSummary}</span>
                  <em>0원으로 기록된 신호는 나중에 매도 현금이 생겨도 다시 배정하지 않고, 다음 새 매수 신호부터 현금이 있으면 배정합니다.</em>
                </div>
                {activeAllocation && (
                  <>
                    <label className="login-field">
                      <span>제한 슬롯 수</span>
                      <input
                        autoFocus
                        inputMode="numeric"
                        value={activeAllocation.slotCount}
                        onChange={(event) => {
                          const nextSlotCount = event.target.value.replace(/[^0-9]/g, '')
                          const parsedSlotCount = Math.min(20, Math.max(1, Number(nextSlotCount) || 1))
                          setContributionDraft((current) => {
                            if (!current) return current
                            const currentAllocation = current.allocationByInvestmentType[displayedInvestmentType]
                            const fallbackPercents = DEFAULT_ALLOCATION_SETTINGS[displayedInvestmentType].slotPercents
                            const slotPercents = Array.from({ length: parsedSlotCount }, (_, index) => currentAllocation.slotPercents[index] ?? String(fallbackPercents[index] ?? 0))
                            return {
                              ...current,
                              allocationByInvestmentType: {
                                ...current.allocationByInvestmentType,
                                [displayedInvestmentType]: {
                                  slotCount: nextSlotCount,
                                  slotPercents,
                                },
                              },
                            }
                          })
                        }}
                      />
                    </label>
                    <div className="allocation-percent-grid" aria-label={`${displayedAllocationLabel} 슬롯 비중`}>
                      {activeAllocation.slotPercents.map((percent, index) => (
                        <label className="login-field" key={`${displayedInvestmentType}-slot-${index + 1}`}>
                          <span>{index + 1}번 슬롯 비중(%)</span>
                          <input
                            inputMode="numeric"
                            value={percent}
                            onChange={(event) => {
                              const nextPercent = event.target.value.replace(/[^0-9]/g, '')
                              setContributionDraft((current) => {
                                if (!current) return current
                                const currentAllocation = current.allocationByInvestmentType[displayedInvestmentType]
                                const slotPercents = currentAllocation.slotPercents.map((value, percentIndex) => percentIndex === index ? nextPercent : value)
                                return {
                                  ...current,
                                  allocationByInvestmentType: {
                                    ...current.allocationByInvestmentType,
                                    [displayedInvestmentType]: {
                                      ...currentAllocation,
                                      slotPercents,
                                    },
                                  },
                                }
                              })
                            }}
                          />
                        </label>
                      ))}
                    </div>
                  </>
                )}
              </>
            )}
            <div className="modal-actions">
              <button className="modal-cancel" type="button" onClick={() => setContributionDraft(null)}>취소</button>
              <button className="modal-confirm" disabled={isContributionSaveDisabled} type="button" onClick={saveContributionSettings}>저장</button>
            </div>
          </div>
        </div>
      )}
      {isHoldingLiquidationOpen && (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="confirm-modal holding-liquidation-modal" role="dialog">
            <button className="modal-close-button" disabled={isSavingTradeLogs} type="button" aria-label="닫기" onClick={closeHoldingLiquidationModal}>×</button>
            <h3>선택한 보유 종목을 청산할까요?</h3>
            <p>실제 매수가와 매도가를 확인해 수정하면, 해당 거래가 보유 목록에서 빠지고 트레이딩 로그에 반영됩니다.</p>
            <div className="holding-liquidation-list">
              {holdingLiquidationDrafts.map((draft) => {
                const buyPrice = parsePriceValue(draft.buyPrice)
                const sellPrice = parsePriceValue(draft.sellPrice)
                const draftReturn = buyPrice && sellPrice !== null ? ((sellPrice - buyPrice) / buyPrice) * 100 : null

                return (
                  <div className="holding-liquidation-row" key={draft.key}>
                    <div className="holding-liquidation-title">
                      <strong>{draft.name}</strong>
                      <span>{draft.ticker} · 매수 신호일 {draft.buyDate}</span>
                    </div>
                    <label>
                      <span>매수가</span>
                      <input
                        inputMode="decimal"
                        disabled={isSavingTradeLogs}
                        value={draft.buyPrice}
                        onChange={(event) => updateHoldingLiquidationDraft(draft.key, 'buyPrice', event.target.value)}
                      />
                    </label>
                    <label>
                      <span>매도일</span>
                      <input
                        disabled={isSavingTradeLogs}
                        type="date"
                        value={tradeDateInputValue(draft.sellDate)}
                        onChange={(event) => updateHoldingLiquidationDraft(draft.key, 'sellDate', normalizeTradeDateInput(event.target.value))}
                      />
                    </label>
                    <label>
                      <span>매도가</span>
                      <input
                        inputMode="decimal"
                        disabled={isSavingTradeLogs}
                        value={draft.sellPrice}
                        onChange={(event) => updateHoldingLiquidationDraft(draft.key, 'sellPrice', event.target.value)}
                      />
                    </label>
                    <label className="holding-liquidation-return-field">
                      <span>수익률</span>
                      <output className={`holding-liquidation-return ${draftReturn === null ? '' : returnClass(draftReturn)}`}>
                        {draftReturn === null ? '-' : `${draftReturn >= 0 ? '+' : ''}${draftReturn.toFixed(1)}%`}
                      </output>
                    </label>
                  </div>
                )
              })}
            </div>
            <div className="modal-actions">
              <button className="modal-cancel" disabled={isSavingTradeLogs} type="button" onClick={closeHoldingLiquidationModal}>
                취소
              </button>
              <button className="modal-confirm" disabled={!isHoldingLiquidationReady || isSavingTradeLogs} type="button" onClick={() => void confirmHoldingLiquidation()}>
                {isSavingTradeLogs ? '저장 중...' : '청산 반영'}
              </button>
            </div>
          </div>
        </div>
      )}
      {isHoldingDeleteConfirmOpen && (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="confirm-modal" role="dialog">
            <button className="modal-close-button" disabled={isSavingTradeLogs} type="button" aria-label="닫기" onClick={() => setIsHoldingDeleteConfirmOpen(false)}>×</button>
            <h3>선택한 보유 종목을 삭제할까요?</h3>
            <p>선택한 보유중인 종목 기록이 삭제되며, 연결된 트레이딩 로그도 함께 삭제됩니다. 이 작업은 복구할 수 없습니다.</p>
            <div className="modal-actions">
              <button className="modal-cancel" disabled={isSavingTradeLogs} type="button" onClick={() => setIsHoldingDeleteConfirmOpen(false)}>
                취소
              </button>
              <button className="modal-confirm" disabled={isSavingTradeLogs} type="button" onClick={() => void removeSelectedHoldingTrades()}>
                {isSavingTradeLogs ? '삭제 중...' : '삭제'}
              </button>
            </div>
          </div>
        </div>
      )}
      {pendingMarketTrendDeleteKeys.length > 0 && (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="confirm-modal" role="dialog">
            <button className="modal-close-button" disabled={isSavingMarketTrends} type="button" aria-label="닫기" onClick={() => setPendingMarketTrendDeleteKeys([])}>×</button>
            <h3>선택한 시장 트렌드를 삭제할까요?</h3>
            <p>선택한 시장 트렌드 row {pendingMarketTrendDeleteKeys.length}개를 삭제합니다. 저장되면 일반 계정에도 삭제된 row는 보이지 않습니다.</p>
            <div className="modal-actions">
              <button className="modal-cancel" disabled={isSavingMarketTrends} type="button" onClick={() => setPendingMarketTrendDeleteKeys([])}>
                취소
              </button>
              <button className="modal-confirm" disabled={isSavingMarketTrends} type="button" onClick={() => void removeSelectedMarketTrendRows()}>
                {isSavingMarketTrends ? '삭제 중...' : '삭제'}
              </button>
            </div>
          </div>
        </div>
      )}
      <footer className="app-footer">
        <p>© 2026 공수성가 All rights reserved.</p>
        <div className="footer-links" aria-label="서비스 정책">
          <a href="/terms.html" target="_blank" rel="noreferrer">이용약관</a>
          <span aria-hidden="true">|</span>
          <a href="/privacy.html" target="_blank" rel="noreferrer">개인정보처리방침</a>
        </div>
      </footer>
    </main>
  )
}

export default App
