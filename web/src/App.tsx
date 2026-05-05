import './App.css'
import { Fragment, type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import type { User } from '@supabase/supabase-js'
import { fetchAppData, refreshAppData, saveMarketEvents, type AppData, type RuntimeMeta } from './api'
import { isSupabaseConfigured, supabase, userDisplayName } from './supabase'

type Market = 'KR' | 'US'
type Valuation = '저평가' | '보통' | '고평가'
type Opinion = '매수' | '관망' | '매도'
type TradeStatus = '익절' | '손절' | '실패 익절' | '보유 중'

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
  updatedAt: string
}

type TradeLog = {
  ticker: string
  strategy: string
  buyDate: string
  buyPrice: string
  sellDate: string
  sellPrice: string
  returnPct: number
  holdingDays: number | '-'
  status: TradeStatus
}

type TooltipState = {
  text: string
  x: number
  y: number
}

type ActivePage = 'home' | 'value-analysis' | 'technical-analysis' | 'market-events' | 'market-trends' | 'board'

type AuthMode = 'login' | 'signup' | 'recover'
type BoardCategory = '칭찬' | '버그' | '건의' | '기타'
type BoardFilter = '전체' | BoardCategory
type BoardSortDirection = 'desc' | 'asc'

type UserSession = {
  id: string
  email: string
  name: string
  loggedInAt: string
}

type TechnicalColumn = {
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
  hidden?: boolean
}

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
const WATCHLIST_STORAGE_KEY = 'gongsu-watchlist'
const OPERATOR_WATCHLIST_STORAGE_KEY = 'gongsu-operator-watchlist'
const VIEW_MODE_STORAGE_KEY = 'gongsu-view-mode'
const VIEW_MODE_HINT_STORAGE_KEY = 'gongsu-view-mode-hint-seen'
const DEFAULT_ADMIN_EMAILS = ['admin@gongsu.local']

function configuredAdminEmails() {
  return (import.meta.env.VITE_ADMIN_EMAILS ?? DEFAULT_ADMIN_EMAILS.join(','))
    .split(',')
    .map((email: string) => email.trim().toLowerCase())
    .filter(Boolean)
}

function personalWatchlistStorageKey(session: UserSession | null) {
  return `${WATCHLIST_STORAGE_KEY}:${session?.email.toLowerCase() ?? 'guest'}`
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

function readStoredViewMode() {
  return localStorage.getItem(VIEW_MODE_STORAGE_KEY) === 'operator' ? 'operator' : 'personal'
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
}): BoardPost {
  return {
    id: row.id,
    category: boardCategories.includes(row.category as BoardCategory) ? row.category as BoardCategory : '기타',
    content: row.content,
    createdAt: row.created_at,
    authorId: row.author_id,
    authorName: row.author_name,
    hidden: row.hidden ?? false,
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
    ...stock,
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

const initialWatchlist: string[] = []

const trades: TradeLog[] = [
  {
    ticker: 'AAPL',
    strategy: 'C. 200일선 상방 & 스퀴즈 거래량 돌파',
    buyDate: '2026.03.18',
    buyPrice: '$195.42',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 3.4,
    holdingDays: 44,
    status: '보유 중',
  },
  {
    ticker: 'NVDA',
    strategy: 'A. 200일선 상방 & 모멘텀 재가속',
    buyDate: '2026.02.04',
    buyPrice: '$109.88',
    sellDate: '2026.03.26',
    sellPrice: '$121.20',
    returnPct: 10.3,
    holdingDays: 50,
    status: '익절',
  },
  {
    ticker: 'TSLA',
    strategy: 'F. 200일선 상방 & BB 극단 저점',
    buyDate: '2026.01.12',
    buyPrice: '$265.30',
    sellDate: '2026.02.19',
    sellPrice: '$248.90',
    returnPct: -6.2,
    holdingDays: 38,
    status: '손절',
  },
  {
    ticker: '035420',
    strategy: 'E. 200일선 상방 & 스퀴즈 저점',
    buyDate: '2026.04.12',
    buyPrice: '₩209,500',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 1.9,
    holdingDays: 19,
    status: '보유 중',
  },
  {
    ticker: '005930',
    strategy: 'D. 200일선 상방 & 상승 흐름 강화',
    buyDate: '2026.04.05',
    buyPrice: '₩84,200',
    sellDate: '2026.04.18',
    sellPrice: '₩88,500',
    returnPct: 5.1,
    holdingDays: 13,
    status: '익절',
  },
  {
    ticker: 'ONON',
    strategy: 'B. 200일선 하방 & 공황 저점',
    buyDate: '2026.03.02',
    buyPrice: '$38.30',
    sellDate: '2026.03.20',
    sellPrice: '$44.55',
    returnPct: 16.3,
    holdingDays: 18,
    status: '익절',
  },
  {
    ticker: 'BE',
    strategy: 'F. 200일선 상방 & BB 극단 저점',
    buyDate: '2026.02.21',
    buyPrice: '$20.70',
    sellDate: '2026.03.04',
    sellPrice: '$19.30',
    returnPct: -6.8,
    holdingDays: 11,
    status: '손절',
  },
  {
    ticker: 'LRCX',
    strategy: 'D. 200일선 상방 & 상승 흐름 강화',
    buyDate: '2026.01.28',
    buyPrice: '$95.20',
    sellDate: '2026.02.27',
    sellPrice: '$105.41',
    returnPct: 10.7,
    holdingDays: 30,
    status: '실패 익절',
  },
  {
    ticker: '042700',
    strategy: 'D. 200일선 상방 & 상승 흐름 강화',
    buyDate: '2026.04.24',
    buyPrice: '₩169,400',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    ticker: '247540',
    strategy: 'E. 200일선 상방 & 스퀴즈 저점',
    buyDate: '2026.04.22',
    buyPrice: '₩151,800',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    ticker: 'ONON',
    strategy: 'B. 200일선 하방 & 공황 저점',
    buyDate: '2026.04.19',
    buyPrice: '$38.30',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    ticker: 'BE',
    strategy: 'F. 200일선 상방 & BB 극단 저점',
    buyDate: '2026.04.18',
    buyPrice: '$20.70',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    ticker: 'LRCX',
    strategy: 'D. 200일선 상방 & 상승 흐름 강화',
    buyDate: '2026.04.16',
    buyPrice: '$95.20',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    ticker: 'SNDK',
    strategy: 'A. 200일선 상방 & 모멘텀 재가속',
    buyDate: '2026.04.15',
    buyPrice: '$57.40',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    ticker: 'TSLA',
    strategy: 'F. 200일선 상방 & BB 극단 저점',
    buyDate: '2026.04.13',
    buyPrice: '$265.30',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    ticker: '005930',
    strategy: 'D. 200일선 상방 & 상승 흐름 강화',
    buyDate: '2026.04.11',
    buyPrice: '₩84,200',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    ticker: 'MSFT',
    strategy: 'C. 200일선 상방 & 스퀴즈 거래량 돌파',
    buyDate: '2026.04.09',
    buyPrice: '$485.90',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
  {
    ticker: 'NVDA',
    strategy: 'A. 200일선 상방 & 모멘텀 재가속',
    buyDate: '2026.04.07',
    buyPrice: '$109.88',
    sellDate: '보유 중',
    sellPrice: '-',
    returnPct: 0,
    holdingDays: '-',
    status: '보유 중',
  },
]

const operatorTickers: string[] = []
const strategyFilters = ['A', 'B', 'C', 'D', 'E', 'F']
const personalTrades: TradeLog[] = []
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

function statusClass(value: Valuation | Opinion | TradeStatus) {
  if (value === '저평가' || value === '매수' || value === '익절') return 'positive'
  if (value === '고평가' || value === '매도' || value === '손절' || value === '실패 익절') return 'negative'
  return 'neutral'
}

function valuationBadgeClass(value: Valuation) {
  if (value === '저평가') return 'valuation-low'
  if (value === '고평가') return 'valuation-high'
  return 'valuation-normal'
}

function returnClass(value: number) {
  if (value > 0) return 'return-positive'
  if (value < 0) return 'return-negative'
  return ''
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
    return `${code} 전략 기준: 성공은 매수가 대비 +20% 도달 시 즉시 익절입니다. -30%에 닿으면 손절 실패이고, 60거래일 경과 후 수익 중이거나 120거래일 최대 보유 기간에 걸려 청산되면 수익이어도 목표 미달 실패(익절)로 볼 수 있습니다.`
  }

  if (code === 'D') {
    return 'D 전략 기준: 성공은 매수가 대비 +12% 도달 시 즉시 익절입니다. -25%에 닿으면 손절 실패이고, 30거래일 최대 보유 기간 안에 목표를 채우지 못해 청산되면 수익이어도 목표 미달 실패(익절)로 볼 수 있습니다.'
  }

  if (['E', 'F'].includes(code)) {
    return `${code} 전략 기준: 성공은 +20% 도달 후 MACD 둔화 신호가 나오거나 목표 도달 후 5거래일 대기 만료 시 청산입니다. -30%에 닿으면 손절 실패이고, 60거래일 수익 중 청산이나 120거래일 최대 보유 기간 청산은 조건 충족 여부에 따라 수익이어도 실패(익절)로 볼 수 있습니다.`
  }

  return '전략별 성공/실패 기준 정보가 준비 중입니다.'
}

function tradeResultInfo(trade: TradeLog) {
  if (trade.status !== '보유 중') return tradeCriteriaInfo(trade.strategy)
  return '아직 매도 신호가 없어 성공/실패를 확정하지 않은 보유 중 거래입니다.'
}

function isSystemHolding(ticker: string, targetTrades: TradeLog[]) {
  return targetTrades.some((trade) => trade.ticker === ticker && trade.status === '보유 중')
}

function stockName(ticker: string) {
  return searchUniverse.find((stock) => stock.ticker === ticker)?.name ?? ticker
}

function stockMarket(ticker: string) {
  return searchUniverse.find((stock) => stock.ticker === ticker)?.market ?? 'US'
}

function marketFlag(market: Market) {
  return market === 'KR' ? '🇰🇷' : '🇺🇸'
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

function holdingPeriodDays(trade: TradeLog) {
  const endTime = trade.status === '보유 중' ? Date.now() : parseTradeDate(trade.sellDate)
  return Math.max(0, Math.ceil((endTime - parseTradeDate(trade.buyDate)) / 86_400_000))
}

function parsePriceValue(value: string) {
  const parsed = Number(value.replace(/[^0-9.-]/g, ''))
  return Number.isFinite(parsed) ? parsed : null
}

function currentReturnPct(trade: TradeLog) {
  const buyPrice = parsePriceValue(trade.buyPrice)
  const currentPrice = parsePriceValue(searchUniverse.find((stock) => stock.ticker === trade.ticker)?.currentPrice ?? '')

  if (!buyPrice || currentPrice === null) return null
  return ((currentPrice - buyPrice) / buyPrice) * 100
}

function valuationFromPriceRange(currentPrice: string, fairPrice: string): Valuation | null {
  const current = parsePriceValue(currentPrice)
  const [lowText, highText] = fairPrice.split('~').map((value) => value.trim())
  const low = parsePriceValue(lowText ?? '')
  const high = parsePriceValue(highText ?? '')

  if (current === null || low === null || high === null) return null
  if (current < low) return '저평가'
  if (current > high) return '고평가'
  return '보통'
}

function tradeKey(trade: TradeLog) {
  return `${trade.ticker}-${trade.buyDate}`
}

function primaryIndustryLabel(industry?: string) {
  return industry?.split(/[,|/]/)[0]?.trim() || '-'
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
const adminGnbMenus = [...gnbMenus, '게시판']
const boardCategories: BoardCategory[] = ['칭찬', '버그', '건의', '기타']
const boardFilters: BoardFilter[] = ['전체', ...boardCategories]

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
      { month: '1월', date: '2026. 1. 29', dday: '94', time: '3:00' },
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
      { month: '2월', date: '2026. 2. 6', dday: '86', time: '22:30' },
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
      { month: '2월', date: '2026. 2. 11', dday: '81', time: '22:30' },
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
      { month: '1월', date: '2026. 1. 14', dday: '109', time: '22:30' },
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
      { month: '3월', date: '2026. 3. 21', dday: '43', time: '6:00' },
      { month: '4월', date: '-', dday: '-', time: '-' },
      { month: '5월', date: '-', dday: '-', time: '-' },
      { month: '6월', date: '2026. 6. 20', dday: '-48', time: '5:00', highlighted: true },
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
      { month: '3월', date: '2026. 3. 21', dday: '43', time: '6:00' },
      { month: '4월', date: '-', dday: '-', time: '-' },
      { month: '5월', date: '-', dday: '-', time: '-' },
      { month: '6월', date: '2026. 6. 20', dday: '-48', time: '5:00', highlighted: true },
      { month: '7월', date: '-', dday: '-', time: '-' },
      { month: '8월', date: '-', dday: '-', time: '-' },
      { month: '9월', date: '2026. 9. 19', dday: '-139', time: '5:00', highlighted: true },
      { month: '10월', date: '-', dday: '-', time: '-' },
      { month: '11월', date: '-', dday: '-', time: '-' },
      { month: '12월', date: '2026. 12. 19', dday: '-230', time: '6:00', highlighted: true },
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
  { label: '실적발표일', value: (metric) => metric.earningsDate },
]

const technicalMarketSnapshot: string[][] = [
  ['시장 주요 이벤트', '당분간 없음'],
  ['VIX (변동성지수) 당일·전날', '16.99 / 16.89'],
  ['미국 10년물 금리', '4.378'],
  ['달러 인덱스', '98.21'],
  ['QQQ 주봉 RSI (14)', '64.16'],
  ['QQQ 일봉 RSI (14, 당일)', '82.79'],
  ['QQQ 일봉 RSI (14, 전날)', '82.78'],
  ['나스닥 (QQQ, 당일)', '674.18'],
  ['나스닥 (QQQ, 20일 이동평균선)', '638.20'],
  ['나스닥 (QQQ, 60일 이동평균선)', '611.53'],
  ['나스닥 (QQQ, 144일 이동평균선)', '614.24'],
  ['나스닥 (QQQ, 200일 이동평균선)', '604.08'],
]

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
  const defaultLabels = new Set(technicalMarketSnapshot.map(([label]) => label))
  const extraRows = snapshot.filter(([label]) => !defaultLabels.has(label) && label !== '기술분석 갱신 주기')
  const mergedDefaults = technicalMarketSnapshot.map(([label, value]) => [label, incomingValues.get(label) ?? value])
  const [eventRow, ...restRows] = mergedDefaults
  const vixRows = restRows.filter(([label]) => label.startsWith('VIX'))
  const otherRows = restRows.filter(([label]) => !label.startsWith('VIX'))

  return [
    eventRow,
    ...vixRows,
    ...extraRows,
    ...otherRows,
  ]
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

function technicalEntryPrice(stock: Stock) {
  const holdingTrade = trades.find((trade) => trade.ticker === stock.ticker && trade.status === '보유 중')
  return holdingTrade?.buyPrice ?? '-'
}

function technicalEntryDate(stock: Stock) {
  const holdingTrade = trades.find((trade) => trade.ticker === stock.ticker && trade.status === '보유 중')
  return holdingTrade?.buyDate.replaceAll('.', '-') ?? '-'
}

function technicalEntryStrategy(stock: Stock) {
  const holdingTrade = trades.find((trade) => trade.ticker === stock.ticker && trade.status === '보유 중')
  return holdingTrade?.strategy ?? '-'
}

const technicalMetricColumns: TechnicalColumn[] = [
  { label: 'RSI (D)', tooltip: '최근 14일 기준으로 주가가 얼마나 강하게 올랐는지 봅니다. 70 이상은 과열, 30 이하는 과매도에 가깝습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 1, 29, 58), 2) },
  { label: 'RSI (D-1)', tooltip: '어제 기준 RSI입니다. 오늘 값과 비교해 매수세가 더 강해졌는지 약해졌는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 2, 28, 57), 2) },
  { label: 'RSI Signal', tooltip: 'RSI의 움직임을 부드럽게 만든 비교선입니다. RSI가 이 선 위면 단기 흐름이 강하고, 아래면 힘이 약해질 수 있습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 3, 32, 48), 2) },
  { label: 'RSI 기울기', tooltip: '오늘 RSI가 어제보다 얼마나 변했는지 봅니다. 플러스면 힘이 강해지고, 마이너스면 힘이 약해지는 흐름입니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 4, -9, 16), 2) },
  { label: 'CCI (D)', tooltip: '현재 가격이 평소 범위보다 얼마나 벗어났는지 봅니다. +100 이상은 강세, -100 이하는 약세나 과매도에 가깝습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 5, -130, 280), 2) },
  { label: 'CCI (D-1)', tooltip: '어제 기준 CCI입니다. 오늘 값과 비교해 강세나 약세가 이어지는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 6, -125, 270), 2) },
  { label: 'CCI Signal', tooltip: 'CCI의 움직임을 부드럽게 만든 비교선입니다. CCI가 이 선 위로 올라서면 단기 반등 힘이 붙었다고 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 7, -90, 240), 2) },
  { label: 'CCI 기울기', tooltip: '오늘 CCI가 어제보다 얼마나 변했는지 봅니다. 크게 오르면 반등 시도, 크게 내리면 힘이 약해진 흐름입니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 8, -58, 136), 2) },
  { label: 'MACD (12, 26, D)', tooltip: '짧은 평균가격과 긴 평균가격의 차이입니다. 0보다 높으면 상승 흐름, 낮으면 하락 흐름이 우세합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 9, -900, 12000), 2) },
  { label: 'MACD (12, 26, D-1)', tooltip: '어제 기준 MACD입니다. 오늘 값과 비교해 추세가 강해졌는지 약해졌는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 10, -850, 11200), 2) },
  { label: 'MACD Signal', tooltip: 'MACD의 비교선입니다. MACD가 이 선 위면 상승 힘이 있고, 아래면 힘이 약해질 수 있습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 11, -700, 9800), 2) },
  { label: 'MACD Histogram (D)', tooltip: 'MACD와 비교선의 차이입니다. 값이 커지면 추세가 강해지고, 작아지면 힘이 약해질 수 있습니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 12, -4200, 7600), 2) },
  { label: 'M - H (D-1)', tooltip: '어제 기준 MACD 차이값입니다. 오늘 값과 비교해 방향 전환이 이어지는지 봅니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 13, -2400, 5000), 2) },
  { label: 'M - H (D-2)', tooltip: '2거래일 전 MACD 차이값입니다. 최근 3일 흐름을 같이 봐서 일시적인 신호를 줄입니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 14, -2100, 4600), 2) },
  { label: 'MACD 기울기', tooltip: 'MACD 차이값이 얼마나 변했는지 봅니다. 플러스면 힘이 강해지고, 마이너스면 상승 힘이 약해질 수 있습니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 15, -620, 1360), 2) },
  { label: '+DI (DMI, 14)', tooltip: '상승 힘을 보여주는 지표입니다. +DI가 -DI보다 높으면 매수세가 더 강하다고 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 16, 12, 52), 2) },
  { label: '-DI (DMI, 14)', tooltip: '하락 힘을 보여주는 지표입니다. -DI가 +DI보다 높으면 매도 압력이 더 강하다고 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 17, 9, 48), 2) },
  { label: 'ADX (14, D)', tooltip: '상승이든 하락이든 추세가 얼마나 강한지 봅니다. 20 이상이면 추세가 생겼고, 40 이상이면 강한 편입니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 18, 14, 58), 2) },
  { label: 'ADX (14, D-1)', tooltip: '어제 기준 ADX입니다. 오늘 값과 비교해 추세의 힘이 커졌는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 19, 13, 57), 2) },
  { label: 'ADX (14, D-2)', tooltip: '2거래일 전 ADX입니다. 최근 3일 동안 추세의 힘이 강해지는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 20, 13, 55), 2) },
  { label: 'ADX 기울기', tooltip: 'ADX가 얼마나 변했는지 봅니다. 오르면 추세가 강해지고, 내리면 횡보 가능성이 커집니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 21, -6, 12), 2) },
  { label: 'Candle Open', tooltip: '오늘 장이 시작된 가격입니다. 종가와 비교해 장중에 매수세가 강했는지 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 22, 0.965, 0.07, 4)) },
  { label: 'C - High', tooltip: '오늘 가장 높게 거래된 가격입니다. 종가가 고가에 가까우면 매수세가 끝까지 강했다고 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 23, 1.005, 0.06, 4)) },
  { label: 'C - Low', tooltip: '오늘 가장 낮게 거래된 가격입니다. 저가에서 얼마나 회복했는지로 반등 힘을 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 24, 0.925, 0.065, 4)) },
  { label: 'C - Close', tooltip: '오늘 마감 가격입니다. 대부분의 기술 지표가 이 가격을 기준으로 계산됩니다.', value: (stock) => stock.currentPrice },
  { label: 'C - Volume', tooltip: '오늘 거래된 주식 수입니다. 가격 움직임에 거래량이 같이 붙으면 신뢰도가 높아집니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 25) },
  { label: '아래꼬리 길이', tooltip: '장중 저점에서 다시 올라온 폭입니다. 길수록 저점 매수세가 들어왔다고 볼 수 있습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 26, 0, 18), 2) },
  { label: '위꼬리 길이', tooltip: '장중 고점에서 밀려 내려온 폭입니다. 길수록 위에서 매물이 많이 나왔다고 볼 수 있습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 27, 0, 16), 2) },
  { label: '몸통 길이', tooltip: '시작 가격과 마감 가격의 차이입니다. 클수록 그날 방향성이 뚜렷합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 28, 0.2, 22), 2) },
  { label: '거래량 (D)', tooltip: '오늘 거래량입니다. 돌파나 반등이 거래량 증가와 함께 나왔는지 확인합니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 29) },
  { label: '거래량 (D-1)', tooltip: '어제 거래량입니다. 오늘 거래량과 비교해 관심이 늘었는지 봅니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 30) },
  { label: '20일 평균 대비 거래량 (D)', tooltip: '최근 20일 평균보다 오늘 거래가 얼마나 많은지 봅니다. 100% 이상이면 평소보다 활발합니다.', value: (stock, index) => `${formatTechnicalNumber(technicalNumber(stock, index, 31, 45, 165), 0)}%` },
  { label: '절대 거래량 (D)', tooltip: '실제로 거래가 충분히 되는지 보는 값입니다. 거래가 너무 적으면 신호가 좋아도 매매가 어려울 수 있습니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 32) },
  { label: '볼린저밴드 %B (종가)', tooltip: '종가가 가격 범위 안에서 위쪽인지 아래쪽인지 봅니다. 80 이상은 상단, 20 이하는 하단에 가깝습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 33, 5, 112), 2) },
  { label: '볼린저밴드 %B (저가)', tooltip: '오늘 저가가 가격 범위 안에서 어디였는지 봅니다. 장중에 아래쪽을 찍고 회복했는지 확인합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 34, 0, 105), 2) },
  { label: '볼린저밴드 Peak (D)', tooltip: '최근 가격 범위 안에서 가장 높았던 위치입니다. 과열 후 힘이 약해지는지 볼 때 씁니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 35, 20, 95), 2) },
  { label: '볼린저밴드 Peak (D-1)', tooltip: '어제 기준 가격 범위의 고점 위치입니다. 오늘과 비교해 과열이 이어지는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 36, 18, 92), 2) },
  { label: '볼린저밴드 폭 (D)', tooltip: '가격이 움직이는 범위의 넓이입니다. 좁으면 조용한 구간, 넓으면 크게 움직이는 구간입니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 37, 8, 48), 2) },
  { label: '볼린저밴드 폭 (D-1)', tooltip: '어제 기준 가격 범위의 넓이입니다. 오늘과 비교해 움직임이 커졌는지 작아졌는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 38, 8, 46), 2) },
  { label: '지난 60일 볼린저밴드 폭 평균', tooltip: '최근 60일 동안의 평균 가격 범위입니다. 현재 범위가 평소보다 좁은지 넓은지 비교합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 39, 12, 42), 2) },
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
    const minX = 280
    const maxX = window.innerWidth - 280
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
      onClick={(event) => openTooltip(event.currentTarget)}
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
  addStockControl,
  onAddStock,
  onTooltipOpen,
  onTooltipClose,
}: {
  stocks: Stock[]
  viewMode: 'personal' | 'operator'
  valuationRows: Record<string, ValuationMetric>
  addStockControl?: ReactNode
  onAddStock: () => void
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  const visibleStocks = stocks.slice(0, MAX_WATCHLIST_ITEMS)
  const blankRowCount = Math.max(MAX_WATCHLIST_ITEMS - visibleStocks.length, 0)
  const isEmpty = stocks.length === 0

  return (
    <section className="panel value-analysis-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>가치 분석</h2>
          <p>Home 관심 종목 기준으로 핵심 재무 지표를 확인해 적정가를 계산하고, 현재가를 기준으로 저평가/고평가 여부를 판단합니다.</p>
          <p className="page-update-note">각 지표는 매일 자정에 1회 업데이트됩니다.</p>
        </div>
        <span>총 {visibleStocks.length}개</span>
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
        <div className="sheet-wrap value-analysis-sheet">
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
              <th>적정 주가 범위</th>
              <th>현재가</th>
              <th>가치 평가</th>
              {valueMetricColumns.map((column) => (
                <th key={column.label}>
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
              const displayValuation = valuationFromPriceRange(stock.currentPrice, stock.fairPrice) ?? stock.valuation

              return (
                <tr key={stock.ticker}>
                  <td className="name-data-cell">
                    <div className="name-cell">
                      <span className="market-flag" aria-hidden="true">{marketFlag(stock.market)}</span>
                      <span>{stock.name}</span>
                    </div>
                  </td>
                  <td className="ticker-cell">{stock.ticker}</td>
                  <td>{stock.category ?? (stock.market === 'KR' ? '성장주' : '혼합주')}</td>
                  <td className="industry-cell">{stock.industry ?? '-'}</td>
                  <td className="number-cell">{stock.fairPrice}</td>
                  <td className="number-cell">{stock.currentPrice}</td>
                  <td><span className={`status-badge ${valuationBadgeClass(displayValuation)}`}>{displayValuation}</span></td>
                  {valueMetricColumns.map((column) => (
                    <td className="number-cell" key={column.label}>
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
  marketSnapshot,
  addStockControl,
  onAddStock,
  onTooltipOpen,
  onTooltipClose,
}: {
  stocks: Stock[]
  viewMode: 'personal' | 'operator'
  technicalRows: Record<string, Record<string, string>>
  marketSnapshot: string[][]
  addStockControl?: ReactNode
  onAddStock: () => void
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  const visibleStocks = stocks.slice(0, MAX_WATCHLIST_ITEMS)
  const blankRowCount = Math.max(MAX_WATCHLIST_ITEMS - visibleStocks.length, 0)
  const isEmpty = stocks.length === 0
  const vixSnapshot = marketSnapshot.find(([label]) => label === 'VIX (변동성지수) 당일·전날')?.[1] ?? '16.99 / 16.89'
  const fearGreedSnapshot = marketSnapshot.find(([label]) => label === 'CNN 공포·탐욕지수 당일·전날')?.[1]
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
        <span>총 {visibleStocks.length}개</span>
      </div>

      <details className="technical-summary-disclosure">
        <summary>
          <span>공통 지표</span>
          <strong>VIX (변동성지수) {vixSnapshot}</strong>
          {fearGreedSnapshot && <strong>CNN 공포·탐욕지수 {fearGreedSnapshot}</strong>}
          <strong>{qqqSummary}</strong>
          <strong>미국 10년물 금리 4.378</strong>
          <strong>달러 인덱스 98.21</strong>
          <strong>QQQ 일봉 RSI 당일 82.79 / 전날 82.78</strong>
          <em>펼쳐보기</em>
        </summary>
        <div className="technical-summary-strip" aria-label="기술 분석 시장 요약">
          {marketSnapshot.map(([label, value]) => (
            <div className="technical-summary-item" key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
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
        <div className="sheet-wrap value-analysis-sheet technical-analysis-sheet">
          <table className="sheet-table value-analysis-table technical-analysis-table">
            <thead>
              <tr>
                <th>종목명</th>
                <th>티커</th>
                <th>투자의견</th>
                {technicalMetricColumns.map((column) => (
                  <th key={column.label}>
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

                return (
                <tr key={stock.ticker}>
                  <td className="name-data-cell">
                    <div className="name-cell">
                      <span className="market-flag" aria-hidden="true">{marketFlag(stock.market)}</span>
                      <span>{stock.name}</span>
                    </div>
                  </td>
                  <td className="ticker-cell">{stock.ticker}</td>
                  <td><span className={`status-badge ${statusClass(stock.opinion)}`}>{stock.opinion}</span></td>
                  {technicalMetricColumns.map((column) => {
                    const value = apiRow?.[column.label] ?? '-'
                    const isEntryStrategy = column.label === '진입 전략'
                    const cellClassName = value === '-'
                      ? 'dash-cell'
                      : isEntryStrategy ? 'strategy-data-cell technical-strategy-cell' : 'number-cell'

                    return (
                      <td className={cellClassName} key={column.label}>
                        {isEntryStrategy && value !== '-' ? (
                          <StrategyTag
                            onTooltipClose={onTooltipClose}
                            onTooltipOpen={onTooltipOpen}
                            strategy={value}
                          />
                        ) : value}
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
  return String(Math.round((todayDate.getTime() - eventDate.getTime()) / msPerDay))
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
  const weekdays = ['일', '월', '화', '수', '목', '금', '토']
  return `현재 날짜: ${date.getFullYear()}년 ${date.getMonth() + 1}월 ${date.getDate()}일 (${weekdays[date.getDay()]})`
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
          <p>금리, 고용, 물가, 리밸런싱 등 시장 변동성을 키울 수 있는 주요 이벤트 일정을 확인합니다. 모든 날짜는 한국 시간 기준입니다.</p>
          <p className="page-warning">※ 이벤트 일정은 미국 정부 상황에 따라 유동적으로 달라져 간혹 맞지 않을 수 있습니다.</p>
        </div>
        <span>{formatCurrentDateLabel()}</span>
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
                  <th className={groupIndex > 0 ? 'event-group-start' : undefined}>발표일</th>
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

function MarketTrendsPage({ rows }: { rows: MarketTrendRow[] }) {
  const [page, setPage] = useState(1)
  const sortedMarketTrendRows = [...rows].sort((a, b) => new Date(b.date.replaceAll('.', '-')).getTime() - new Date(a.date.replaceAll('.', '-')).getTime())
  const pageSize = 50
  const totalPages = Math.max(1, Math.ceil(sortedMarketTrendRows.length / pageSize))
  const safePage = Math.min(page, totalPages)
  const pageStart = (safePage - 1) * pageSize
  const visibleMarketTrendRows = sortedMarketTrendRows.slice(pageStart, pageStart + pageSize)
  const blankRowCount = Math.max(MAX_WATCHLIST_ITEMS - visibleMarketTrendRows.length, 0)

  return (
    <section className="panel value-analysis-panel market-trends-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>시장 트렌드</h2>
          <p>주간 시장에서 자주 언급된 핵심 테마와 섹터를 순위별로 확인합니다.</p>
        </div>
        <span>총 {rows.length}개</span>
      </div>

      <div className="sheet-wrap market-trends-sheet">
        <table className="sheet-table market-trends-table">
          <thead>
            <tr>
              <th>날짜</th>
              {Array.from({ length: 10 }).map((_, index) => (
                <th key={`trend-rank-${index + 1}`}>{index + 1}위</th>
              ))}
              <th>시장요약</th>
            </tr>
          </thead>
          <tbody>
            {visibleMarketTrendRows.map((row) => (
              <tr key={row.date}>
                <td className="number-cell trend-date-cell">{row.date}</td>
                {Array.from({ length: 10 }).map((_, index) => (
                  <td className="trend-rank-cell" key={`${row.date}-${index + 1}`}>{row.ranks[index] ?? '-'}</td>
                ))}
                <td className="trend-summary-cell">{row.summary}</td>
              </tr>
            ))}
            {Array.from({ length: blankRowCount }).map((_, rowIndex) => (
              <tr className="blank-row" key={`market-trend-blank-${rowIndex}`}>
                {Array.from({ length: 12 }).map((__, cellIndex) => (
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

function formatBoardPostDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')

  return `${year}.${month}.${day} ${hours}:${minutes}`
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

function BoardPage({
  posts,
  category,
  content,
  filter,
  currentUserId,
  page,
  showMineOnly,
  sortDirection,
  onCategoryChange,
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
  selectedPostIds,
}: {
  posts: BoardPost[]
  category: BoardCategory
  content: string
  filter: BoardFilter
  currentUserId: string
  page: number
  showMineOnly: boolean
  sortDirection: BoardSortDirection
  selectedPostIds: string[]
  onCategoryChange: (category: BoardCategory) => void
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
                  </div>
                  <div className="board-post-meta-right">
                    <time dateTime={post.createdAt}>{formatBoardPostDate(post.createdAt)}</time>
                    {post.authorId === currentUserId && (
                      <button type="button" onClick={() => onDeletePost(post.id)}>삭제</button>
                    )}
                  </div>
                </div>
                <p>{post.content}</p>
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
  const [query, setQuery] = useState('')
  const [watchlist, setWatchlist] = useState<string[]>(() => readStoredWatchlist())
  const [operatorWatchlist, setOperatorWatchlist] = useState<string[]>(() => readStoredOperatorWatchlist())
  const [personalTradeLogs, setPersonalTradeLogs] = useState<TradeLog[]>(personalTrades)
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
  const [isLoginOpen, setIsLoginOpen] = useState(false)
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginPasswordConfirm, setLoginPasswordConfirm] = useState('')
  const [loginError, setLoginError] = useState('')
  const [isRecoverySent, setIsRecoverySent] = useState(false)
  const [boardPosts, setBoardPosts] = useState<BoardPost[]>(initialBoardPosts)
  const [boardCategory, setBoardCategory] = useState<BoardCategory>('건의')
  const [boardContent, setBoardContent] = useState('')
  const [boardFilter, setBoardFilter] = useState<BoardFilter>('전체')
  const [boardPage, setBoardPage] = useState(1)
  const [showMineOnly, setShowMineOnly] = useState(false)
  const [boardSortDirection, setBoardSortDirection] = useState<BoardSortDirection>('desc')
  const [selectedBoardPostIds, setSelectedBoardPostIds] = useState<string[]>([])
  const [pendingBoardDeleteIds, setPendingBoardDeleteIds] = useState<string[]>([])
  const [userSession, setUserSession] = useState<UserSession | null>(null)
  const [authInfoMessage, setAuthInfoMessage] = useState('')
  const [isRemoteDataReady, setIsRemoteDataReady] = useState(!isSupabaseConfigured)
  const [apiStocks, setApiStocks] = useState<Stock[]>(() => searchUniverse.map(stockSearchShell))
  const [apiValuationMetrics, setApiValuationMetrics] = useState<Record<string, ValuationMetric>>({})
  const [apiTechnicalRows, setApiTechnicalRows] = useState<Record<string, Record<string, string>>>({})
  const [apiMarketSnapshot, setApiMarketSnapshot] = useState<string[][]>(technicalMarketSnapshot)
  const [apiMarketEventGroups, setApiMarketEventGroups] = useState<MarketEventGroup[]>(marketEventGroups)
  const [marketEventYearLabel, setMarketEventYearLabel] = useState('2026년')
  const [marketEventMonths, setMarketEventMonths] = useState(eventMonths)
  const [apiMarketTrendRows, setApiMarketTrendRows] = useState<MarketTrendRow[]>([])
  const [marketEventsMeta, setMarketEventsMeta] = useState<RuntimeMeta | undefined>()
  const [isSavingMarketEvents, setIsSavingMarketEvents] = useState(false)
  const [isMarketEventsDirty, setIsMarketEventsDirty] = useState(false)
  const [isRefreshingData, setIsRefreshingData] = useState(false)
  const [refreshDataMessage, setRefreshDataMessage] = useState('')
  const [activePage, setActivePage] = useState<ActivePage>('home')
  const addStockButtonRef = useRef<HTMLButtonElement | null>(null)
  const inlineAddRef = useRef<HTMLDivElement | null>(null)

  const applyLoadedData = (data: AppData<Stock, ValuationMetric, MarketEventGroup, MarketTrendRow>) => {
    if (data.stocks?.rows && data.stocks.rows.length > 0) {
      setApiStocks(data.stocks.rows)
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
  }

  async function ensureProfile(session: UserSession) {
    if (!supabase) return

    await supabase
      .from('profiles')
      .upsert({
        id: session.id,
        email: session.email,
        name: session.name,
      })
  }

  async function loadWatchlist(scope: 'personal' | 'operator', session: UserSession | null) {
    if (!supabase) {
      return scope === 'operator' ? readStoredOperatorWatchlist() : readStoredWatchlist(session)
    }

    let query = supabase
      .from('watchlists')
      .select('tickers')
      .eq('scope', scope)

    query = scope === 'operator'
      ? query.is('owner_id', null)
      : query.eq('owner_id', session?.id ?? '')

    const { data, error } = await query.maybeSingle()
    if (error) throw error

    const tickers = Array.isArray(data?.tickers)
      ? data.tickers.filter((ticker): ticker is string => typeof ticker === 'string')
      : null

    return tickers
  }

  async function persistWatchlist(scope: 'personal' | 'operator', tickers: string[], session = userSession) {
    if (!supabase) {
      if (scope === 'operator') {
        localStorage.setItem(OPERATOR_WATCHLIST_STORAGE_KEY, JSON.stringify(tickers))
      } else {
        localStorage.setItem(personalWatchlistStorageKey(session), JSON.stringify(tickers))
      }
      return
    }

    if (scope === 'personal' && !session) return

    let updateQuery = supabase
      .from('watchlists')
      .update({ tickers })
      .eq('scope', scope)

    updateQuery = scope === 'operator'
      ? updateQuery.is('owner_id', null)
      : updateQuery.eq('owner_id', session?.id ?? '')

    const { data, error } = await updateQuery.select('id')
    if (error) throw error
    if (data && data.length > 0) return

    await supabase
      .from('watchlists')
      .insert({
        owner_id: scope === 'operator' ? null : session?.id,
        scope,
        tickers,
      })
  }

  async function loadBoardPosts() {
    if (!supabase) return

    const { data, error } = await supabase
      .from('board_posts')
      .select('id, category, content, created_at, author_id, author_name, hidden')
      .order('created_at', { ascending: false })

    if (error) throw error
    setBoardPosts((data ?? []).map(mapBoardPost))
  }

  async function loadServiceData(session: UserSession | null) {
    setIsRemoteDataReady(false)
    try {
      const [personalTickers, operatorTickersFromDb] = await Promise.all([
        session ? loadWatchlist('personal', session) : Promise.resolve(null),
        loadWatchlist('operator', session),
      ])
      await loadBoardPosts()
      const legacyTickers = session ? readLegacyWatchlist(session) : null
      const nextPersonalTickers = personalTickers && personalTickers.length > 0
        ? personalTickers
        : legacyTickers ?? initialWatchlist

      setWatchlist(session ? nextPersonalTickers : readStoredWatchlist(null))
      setOperatorWatchlist(operatorTickersFromDb && operatorTickersFromDb.length > 0 ? operatorTickersFromDb : operatorTickers)

      if (session && (!personalTickers || personalTickers.length === 0) && legacyTickers) {
        await persistWatchlist('personal', legacyTickers, session)
      }
    } finally {
      setIsRemoteDataReady(true)
    }
  }

  useEffect(() => {
    let isMounted = true

    fetchAppData<Stock, ValuationMetric, MarketEventGroup, MarketTrendRow>().then((data) => {
      if (!isMounted) return
      applyLoadedData(data)
    })

    return () => {
      isMounted = false
    }
  }, [])

  useEffect(() => {
    let isMounted = true

    if (!supabase) {
      return () => {
        isMounted = false
      }
    }

    const syncAuthUser = async (user: User | null) => {
      if (!isMounted) return
      if (!user) {
        setUserSession(null)
        setWatchlist(readStoredWatchlist(null))
        setBoardPosts([])
        await loadServiceData(null)
        return
      }

      const nextSession = sessionFromSupabaseUser(user)
      setUserSession(nextSession)
      localStorage.removeItem(LEGACY_AUTH_SESSION_STORAGE_KEY)
      await ensureProfile(nextSession)
      await loadServiceData(nextSession)
    }

    supabase.auth.getSession().then(({ data }) => {
      void syncAuthUser(data.session?.user ?? null)
    })

    const { data: authListener } = supabase.auth.onAuthStateChange((_event, session) => {
      void syncAuthUser(session?.user ?? null)
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

  const watchlistStocks = useMemo(
    () => watchlist
      .map((ticker) => apiStocks.find((stock) => stock.ticker === ticker))
      .filter((stock): stock is Stock => Boolean(stock)),
    [apiStocks, watchlist],
  )

  const operatorStocks = useMemo(
    () => operatorWatchlist
      .map((ticker) => apiStocks.find((stock) => stock.ticker === ticker))
      .filter((stock): stock is Stock => Boolean(stock)),
    [apiStocks, operatorWatchlist],
  )

  const searchResults = useMemo(() => {
    const normalized = normalizeQuery(query)
    if (!normalized) return []
    return apiStocks.filter((stock) => {
      const ticker = normalizeQuery(stock.ticker)
      const name = normalizeQuery(stock.name)

      return ticker.includes(normalized) || name.includes(normalized)
    })
  }, [apiStocks, query])

  const trimmedLoginEmail = loginEmail.trim().toLowerCase()
  const isAdminUser = userSession ? configuredAdminEmails().includes(userSession.email.toLowerCase()) : false
  const effectiveViewMode = isAdminUser ? 'operator' : viewMode
  const isOperatorDataMode = effectiveViewMode === 'operator'
  const scopedTrades = isOperatorDataMode ? operatorTrades : personalTradeLogs
  const scopedOpenTrades = scopedTrades.filter((trade) => trade.status === '보유 중')
  const filteredTrades = scopedTrades
    .filter((trade) => selectedStrategy === '전체' || strategyCode(trade.strategy) === selectedStrategy)
    .slice()
    .sort((a, b) => {
      const aTime = new Date(a.buyDate.replaceAll('.', '-')).getTime()
      const bTime = new Date(b.buyDate.replaceAll('.', '-')).getTime()
      return sortDirection === 'desc' ? bTime - aTime : aTime - bTime
    })
  const visibleWinRates = [
    formatWinRate('통합', scopedTrades),
    ...strategyFilters
      .map((code) => formatWinRate(code, scopedTrades.filter((trade) => strategyCode(trade.strategy) === code))),
  ].join(', ')
  const strategyCriteriaLine = 'A/B/C(+20% 즉시, -30%), D(+12%, -25%, 최대 30일), E/F(+20% 후 MACD 둔화·5일 대기, -30%)'
  const investingDays = daysFromFirstTrade(scopedTrades)
  const visibleGnbMenus = isAdminUser ? adminGnbMenus : gnbMenus
  const currentActivePage = !isAdminUser && activePage === 'board' ? 'home' : activePage
  const isLoginEmailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedLoginEmail)
  const shouldShowEmailValidation = loginEmail.trim().length > 0 && !isLoginEmailValid
  const shouldShowPasswordValidation = loginPassword.trim().length > 0 && loginPassword.trim().length < 8
  const shouldShowPasswordConfirmValidation = authMode === 'signup'
    && loginPasswordConfirm.trim().length > 0
    && loginPassword.trim() !== loginPasswordConfirm.trim()
  const isAuthSubmitDisabled = authMode === 'recover'
    ? !isLoginEmailValid || isRecoverySent
    : authMode === 'signup'
      ? !isLoginEmailValid || loginPassword.trim().length < 8 || loginPasswordConfirm.trim().length < 8 || loginPassword.trim() !== loginPasswordConfirm.trim()
      : !isLoginEmailValid || loginPassword.trim().length < 8
  const serviceStatusMessage = !isSupabaseConfigured
    ? 'Supabase 프로젝트 URL과 anon key를 .env에 입력해 주세요.'
    : !isRemoteDataReady
      ? '계정 데이터를 불러오는 중입니다.'
      : ''

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

    if (isOperatorDataMode) {
      const nextWatchlist = operatorWatchlist.includes(ticker) ? operatorWatchlist : [...operatorWatchlist, ticker]
      setOperatorWatchlist(nextWatchlist)
      await persistWatchlist('operator', nextWatchlist)
    } else {
      const nextWatchlist = watchlist.includes(ticker) ? watchlist : [...watchlist, ticker]
      setWatchlist(nextWatchlist)
      await persistWatchlist('personal', nextWatchlist)
    }
    setQuery('')
    setIsAddingStock(false)
  }

  const removeSelectedStocks = async () => {
    if (isOperatorDataMode) {
      const nextWatchlist = operatorWatchlist.filter((ticker) => !selectedTickers.includes(ticker))
      setOperatorWatchlist(nextWatchlist)
      await persistWatchlist('operator', nextWatchlist)
    } else {
      const nextWatchlist = watchlist.filter((ticker) => !selectedTickers.includes(ticker))
      setWatchlist(nextWatchlist)
      await persistWatchlist('personal', nextWatchlist)
    }
    setSelectedTickers([])
  }

  const toggleSelectedTicker = (ticker: string) => {
    setSelectedTickers((current) => (
      current.includes(ticker)
        ? current.filter((item) => item !== ticker)
        : [...current, ticker]
    ))
  }

  const toggleSelectedHoldingTrade = (key: string) => {
    setSelectedHoldingTradeKeys((current) => (
      current.includes(key)
        ? current.filter((item) => item !== key)
        : [...current, key]
    ))
  }

  const removeSelectedHoldingTrades = () => {
    setPersonalTradeLogs((current) => current.filter((trade) => !selectedHoldingTradeKeys.includes(tradeKey(trade))))
    setSelectedHoldingTradeKeys([])
    setIsHoldingDeleteConfirmOpen(false)
  }

  const resetSystemRecords = async () => {
    if (isAdminUser) {
      setOperatorWatchlist([])
      await persistWatchlist('operator', [])
    } else {
      setWatchlist([])
      await persistWatchlist('personal', [])
      setPersonalTradeLogs([])
    }
    setSelectedTickers([])
    setSelectedHoldingTradeKeys([])
    setQuery('')
    setIsAddingStock(false)
    setSelectedStrategy('전체')
    setIsResetConfirmOpen(false)
    setIsHoldingDeleteConfirmOpen(false)
  }

  const clearAuthForm = () => {
    setLoginEmail('')
    setLoginPassword('')
    setLoginPasswordConfirm('')
    setLoginError('')
    setAuthInfoMessage('')
    setIsRecoverySent(false)
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

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setLoginError('이메일 형식이 올바르지 않습니다.')
      return
    }

    if (authMode === 'recover') {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: window.location.origin,
      })
      if (error) {
        setLoginError('비밀번호 재설정 안내를 보내지 못했습니다.\n잠시 후 다시 시도해 주세요.')
        return
      }
      setLoginError('')
      setAuthInfoMessage('비밀번호 재설정 안내를 보냈습니다.\n입력한 이메일함을 확인해 주세요.')
      setIsRecoverySent(true)
      return
    }

    if (password.length < 8) {
      setLoginError('비밀번호는 8자 이상이어야 합니다.\n8자 이상 입력하면 계속 진행할 수 있습니다.')
      return
    }

    if (authMode === 'signup') {
      if (password !== passwordConfirm) {
        setLoginError('비밀번호가 일치하지 않습니다.\n비밀번호 확인란을 다시 입력해 주세요.')
        return
      }

      const { error } = await supabase.auth.signUp({
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
          : '회원가입을 완료하지 못했습니다.\n잠시 후 다시 시도해 주세요.')
        return
      }

      clearAuthForm()
      setAuthMode('login')
      setAuthInfoMessage('가입 확인 메일을 보냈습니다.\n이메일 인증 후 로그인해 주세요.')
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
    setUserSession(null)
    setWatchlist(readStoredWatchlist(null))
    setSelectedTickers([])
    setSelectedHoldingTradeKeys([])
    clearAuthForm()
    setAuthMode('login')
    setIsLoginOpen(false)
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

  const saveMarketEventEntries = async () => {
    if (!isAdminUser || !isMarketEventsDirty) return
    const normalizedGroups = normalizeMarketEventDdays(apiMarketEventGroups)
    setIsSavingMarketEvents(true)
    try {
      const saved = await saveMarketEvents(normalizedGroups, marketEventsMeta, {
        yearLabel: marketEventYearLabel,
        months: marketEventMonths,
      })
      setApiMarketEventGroups(saved.groups)
      setMarketEventsMeta(saved.meta)
      if (saved.yearLabel) {
        setMarketEventYearLabel(saved.yearLabel)
      }
      if (saved.months) {
        setMarketEventMonths(saved.months)
      }
      setIsMarketEventsDirty(false)
    } finally {
      setIsSavingMarketEvents(false)
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
    setRefreshDataMessage('현재 시점 기준으로 데이터를 불러오는 중입니다...')
    try {
      const result = await refreshAppData(tickers)
      const data = await fetchAppData<Stock, ValuationMetric, MarketEventGroup, MarketTrendRow>()
      applyLoadedData(data)
      setRefreshDataMessage(`${result.refreshedTickers.length}개 종목을 현재 시점 기준으로 갱신했습니다.`)
    } catch {
      setRefreshDataMessage('즉시 갱신에 실패했습니다. 로컬 API 서버를 켠 뒤 다시 시도해 주세요.')
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
        .select('id, category, content, created_at, author_id, author_name, hidden')
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

  const tableStocks = isOperatorDataMode ? operatorStocks : watchlistStocks
  const canEditCurrentWatchlist = effectiveViewMode === 'personal' || isAdminUser
  const currentWatchlistTickers = isOperatorDataMode ? operatorWatchlist : watchlist
  const isCurrentWatchlistEmpty = tableStocks.length === 0
  const isCurrentWatchlistFull = canEditCurrentWatchlist && currentWatchlistTickers.length >= MAX_WATCHLIST_ITEMS
  const megaTrendStatus = (trade: TradeLog) => {
    const stock = apiStocks.find((candidate) => candidate.ticker === trade.ticker)
    const industry = primaryIndustryLabel(stock?.industry)
    const keywords = industryTrendKeywords(stock?.industry)
    if (industry === '-' || keywords.length === 0) return '미충족'

    const matchedTrend = apiMarketTrendRows.find((row) => isSameTrendWeek(trade.buyDate, row.date))
    const topThreeTrendText = matchedTrend?.ranks.slice(0, 3).map(normalizeTrendText).join(' ') ?? ''

    return keywords.some((keyword) => topThreeTrendText.includes(keyword))
      ? `충족(${industry})`
      : '미충족'
  }
  const exampleStock = tableStocks[0]
  const fairPricePendingLabel = nextMidnightUpdateLabel()
  const currentPricePendingLabel = nextTwoHourUpdateLabel()
  const showEmptyTradeExample = tableStocks.length > 0 && scopedTrades.length === 0
  const showEmptyHoldingExample = tableStocks.length > 0 && scopedOpenTrades.length === 0
  const tradeBlankRows = Math.max(3, 22 - filteredTrades.length - (showEmptyTradeExample ? 1 : 0))
  const watchlistBlankRows = Math.max(0, 10 - tableStocks.length)
  const holdingBlankRows = Math.max(0, 10 - scopedOpenTrades.length - (showEmptyHoldingExample ? 1 : 0))
  const addStockInlineControl = isAddingStock && canEditCurrentWatchlist && !isCurrentWatchlistFull ? (
    <div className="inline-add analysis-inline-add" ref={inlineAddRef}>
      <input
        autoFocus
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="삼성전자, 005930, AAPL"
      />
      {query && (
        <div className="inline-results">
          {searchResults.length > 0 ? searchResults.slice(0, 50).map((stock) => {
            const isAlreadyAdded = currentWatchlistTickers.includes(stock.ticker)

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
      <header className={`app-header ${showViewModeHint ? 'onboarding-header' : ''}`}>
        <div className="brand">
          <img alt="공수성가 로고" className="brand-logo" src="/gongsu-logo.png" />
          <span>공수성가</span>
        </div>
        <nav className="gnb-menu" aria-label="주요 메뉴">
          {visibleGnbMenus.map((menu) => {
            const isActive = (menu === 'HOME' && currentActivePage === 'home') || (menu === '가치 분석' && currentActivePage === 'value-analysis') || (menu === '기술 분석' && currentActivePage === 'technical-analysis') || (menu === '시장 주요 이벤트' && currentActivePage === 'market-events') || (menu === '시장 트렌드' && currentActivePage === 'market-trends') || (menu === '게시판' && currentActivePage === 'board')

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
                  if (menu === '게시판') setActivePage('board')
                }}
              >
                {menu}
              </button>
            )
          })}
        </nav>
        <div className="updated-text">
          <span>데이터는 2시간 간격으로 정각에 업데이트됩니다.</span>
          <span>공수성가 또한 실제 데이터이며, 참고할 수 있게 제공됩니다.</span>
          <span>단, 모든 투자의 책임은 본인에게 있습니다.</span>
          {isAdminUser && refreshDataMessage && <strong>{refreshDataMessage}</strong>}
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
        <button className="reset-button" type="button" onClick={() => setIsResetConfirmOpen(true)}>
          초기화
        </button>
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
      <section className="dashboard-grid">
        <section className={`panel trading-log-panel ${isCurrentWatchlistEmpty ? 'dimmed-panel' : ''}`}>
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
                <p>총 투자 기간 {investingDays}일 <span>|</span> 승률: {visibleWinRates}</p>
                <p>성공/실패 기준: {strategyCriteriaLine}</p>
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

          <div className="sheet-wrap trading-log-scroll">
            <table className="sheet-table trading-log-table">
              <thead>
                <tr>
                  <th>No</th>
                  <th>종목명</th>
                  <th>티커</th>
                  <th>매수 신호일</th>
                  <th>매수 신호 가격</th>
                  <th>매도 신호일</th>
                  <th>매도 신호 가격</th>
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
                  <th>수익률</th>
                  <th>보유 기간</th>
                  <th>결과</th>
                </tr>
              </thead>
              <tbody>
                {showEmptyTradeExample && exampleStock && (
                  <tr className="example-row">
                    <td className="numbering-cell">예시</td>
                    <td>
                      <div className="name-cell">
                        <span className="market-flag" aria-hidden="true">{marketFlag(exampleStock.market)}</span>
                        <span>{exampleStock.name}</span>
                      </div>
                    </td>
                    <td className="ticker-cell">{exampleStock.ticker}</td>
                    <td>신호 발생 시</td>
                    <td className="number-cell">{exampleStock.currentPrice}</td>
                    <td className="dash-cell">-</td>
                    <td className="dash-cell">-</td>
                    <td><span className="example-note">매수 시그널 충족 시 기록됩니다.</span></td>
                    <td className="dash-cell">미충족</td>
                    <td className="dash-cell">-</td>
                    <td className="dash-cell">-</td>
                    <td><span className="example-note">예시</span></td>
                  </tr>
                )}
                {filteredTrades.map((trade, index) => (
                  <tr key={`${trade.ticker}-${trade.buyDate}`}>
                    <td className="numbering-cell">{index + 1}</td>
                    <td>
                      <div className="name-cell">
                        <span className="market-flag" aria-hidden="true">{marketFlag(stockMarket(trade.ticker))}</span>
                        <span>{stockName(trade.ticker)}</span>
                      </div>
                    </td>
                    <td className="ticker-cell">{trade.ticker}</td>
                    <td>{trade.buyDate}</td>
                    <td className="number-cell">{trade.buyPrice}</td>
                    <td>{trade.sellDate}</td>
                    <td className={trade.sellPrice === '-' ? 'dash-cell' : 'number-cell'}>{trade.sellPrice}</td>
                    <td>
                      <StrategyTag
                        onTooltipClose={() => setActiveTooltip(null)}
                        onTooltipOpen={setActiveTooltip}
                        strategy={trade.strategy}
                      />
                    </td>
                    <td className={megaTrendStatus(trade).startsWith('충족') ? 'mega-trend-cell positive' : 'mega-trend-cell neutral'}>
                      {megaTrendStatus(trade)}
                    </td>
                    {trade.status === '보유 중' ? (
                      <td className="dash-cell">-</td>
                    ) : (
                      <td className={`number-cell ${returnClass(trade.returnPct)}`}>
                        {trade.returnPct >= 0 ? '+' : ''}{trade.returnPct.toFixed(1)}%
                      </td>
                    )}
                    <td>{holdingPeriodDays(trade)}</td>
                    <td>
                      <ResultBadge
                        onTooltipClose={() => setActiveTooltip(null)}
                        onTooltipOpen={setActiveTooltip}
                        trade={trade}
                      />
                    </td>
                  </tr>
                ))}
                {Array.from({ length: tradeBlankRows }).map((_, index) => (
                  <tr className="blank-row" key={`trade-blank-${index}`}>
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
                    <td></td>
                    <td></td>
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
              </div>
            </div>

            {addStockInlineControl}

            <div className="sheet-wrap watchlist-sheet">
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
                <table className="sheet-table watchlist-table">
                  <thead>
                    <tr>
                      {canEditCurrentWatchlist && <th>선택</th>}
                      <th>No</th>
                      <th>종목명</th>
                      <th>티커</th>
                      <th>산업군</th>
                      <th>적정 가격</th>
                      <th>현재가</th>
                      <th>가치 분석</th>
                      <th>기술 분석</th>
                      <th>시스템 보유</th>
                      <th>매수 전략</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableStocks.map((stock, index) => {
                      const displayValuation = valuationFromPriceRange(stock.currentPrice, stock.fairPrice) ?? stock.valuation

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
                          <div className="name-cell">
                            <span className="market-flag" aria-hidden="true">{marketFlag(stock.market)}</span>
                            <span>{stock.name}</span>
                          </div>
                        </td>
                        <td className="ticker-cell">{stock.ticker}</td>
                        <td className="industry-cell">{stock.industry ?? '-'}</td>
                        <td className="number-cell">
                          {isPendingValue(stock.fairPrice) ? (
                            <span className="pending-update-label">{fairPricePendingLabel}</span>
                          ) : stock.fairPrice}
                        </td>
                        <td className="number-cell">
                          {isPendingValue(stock.currentPrice) ? (
                            <span className="pending-update-label">{currentPricePendingLabel}</span>
                          ) : stock.currentPrice}
                        </td>
                        <td><span className={`status-badge ${valuationBadgeClass(displayValuation)}`}>{displayValuation}</span></td>
                        <td><span className={`status-badge ${statusClass(stock.opinion)}`}>{stock.opinion}</span></td>
                        <td>
                          {isSystemHolding(stock.ticker, scopedTrades) ? '보유 중' : '미보유'}
                        </td>
                        <td className={isSystemHolding(stock.ticker, scopedTrades) ? 'strategy-data-cell' : 'strategy-data-cell dash-cell'}>
                          {isSystemHolding(stock.ticker, scopedTrades) ? stock.strategies.map((strategy) => (
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

          <section className={`panel ${isCurrentWatchlistEmpty ? 'dimmed-panel' : ''}`}>
            <div className="section-heading">
              <div className="section-title-inline">
                <h2>보유중인 종목</h2>
                <span>총 {scopedOpenTrades.length}개</span>
              </div>
              <div className="heading-actions">
                {effectiveViewMode === 'personal' && (
                  <button
                    aria-hidden={selectedHoldingTradeKeys.length === 0}
                    className={`remove-selected-button ${selectedHoldingTradeKeys.length === 0 ? 'reserved-action-button' : ''}`}
                    tabIndex={selectedHoldingTradeKeys.length === 0 ? -1 : 0}
                    type="button"
                    onClick={() => {
                      if (selectedHoldingTradeKeys.length > 0) setIsHoldingDeleteConfirmOpen(true)
                    }}
                  >
                    제거
                  </button>
                )}
              </div>
            </div>

            <div className="sheet-wrap holding-sheet">
              <table className="sheet-table holding-table">
                <thead>
                  <tr>
                    {effectiveViewMode === 'personal' && <th>선택</th>}
                    <th>No</th>
                    <th>티커</th>
                    <th>종목명</th>
                    <th>신호일</th>
                    <th>매수 전략</th>
                    <th>현재 수익률</th>
                    <th>보유 기간</th>
                  </tr>
                </thead>
                <tbody>
                  {showEmptyHoldingExample && exampleStock && (
                    <tr className="example-row">
                      {effectiveViewMode === 'personal' && <td></td>}
                      <td className="numbering-cell">예시</td>
                      <td className="ticker-cell">{exampleStock.ticker}</td>
                      <td>
                        <div className="name-cell">
                          <span className="market-flag" aria-hidden="true">{marketFlag(exampleStock.market)}</span>
                          <span>{exampleStock.name}</span>
                        </div>
                      </td>
                      <td>신호 발생 시</td>
                      <td className="holding-example-note-cell"><span className="example-note">보유 전환 시 표시됩니다.</span></td>
                      <td className="dash-cell">-</td>
                      <td className="dash-cell">-</td>
                    </tr>
                  )}
                  {scopedOpenTrades.map((trade, index) => (
                    <tr key={`open-${tradeKey(trade)}`}>
                      {effectiveViewMode === 'personal' && (
                        <td className="checkbox-cell">
                          <input
                            aria-label={`${stockName(trade.ticker)} 보유 항목 선택`}
                            checked={selectedHoldingTradeKeys.includes(tradeKey(trade))}
                            onChange={() => toggleSelectedHoldingTrade(tradeKey(trade))}
                            type="checkbox"
                          />
                        </td>
                      )}
                      <td className="numbering-cell">{index + 1}</td>
                      <td className="ticker-cell">{trade.ticker}</td>
                      <td>
                        <div className="name-cell">
                          <span className="market-flag" aria-hidden="true">{marketFlag(stockMarket(trade.ticker))}</span>
                          <span>{stockName(trade.ticker)}</span>
                        </div>
                      </td>
                      <td>{trade.buyDate}</td>
                      <td>
                        <StrategyTag
                          onTooltipClose={() => setActiveTooltip(null)}
                          onTooltipOpen={setActiveTooltip}
                          strategy={trade.strategy}
                        />
                      </td>
                      {currentReturnPct(trade) === null ? (
                        <td className="dash-cell">-</td>
                      ) : (
                        <td className={`number-cell ${returnClass(currentReturnPct(trade) ?? 0)}`}>
                          {(currentReturnPct(trade) ?? 0) >= 0 ? '+' : ''}{(currentReturnPct(trade) ?? 0).toFixed(1)}%
                        </td>
                      )}
                      <td>{holdingPeriodDays(trade)}</td>
                    </tr>
                  ))}
                  {Array.from({ length: holdingBlankRows }).map((_, index) => (
                    <tr className="blank-row" key={`holding-blank-${index}`}>
                      {effectiveViewMode === 'personal' && <td></td>}
                      <td className="numbering-cell">&nbsp;</td>
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
        <MarketTrendsPage rows={apiMarketTrendRows} />
      ) : currentActivePage === 'board' && isAdminUser ? (
        <BoardPage
          category={boardCategory}
          content={boardContent}
          currentUserId={boardCurrentUserId(userSession)}
          filter={boardFilter}
          page={boardPage}
          posts={boardPosts}
          selectedPostIds={selectedBoardPostIds}
          showMineOnly={showMineOnly}
          sortDirection={boardSortDirection}
          onCategoryChange={setBoardCategory}
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
        />
      ) : currentActivePage === 'value-analysis' ? (
        <ValueAnalysisPage
          stocks={tableStocks}
          viewMode={effectiveViewMode}
          valuationRows={apiValuationMetrics}
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
          addStockControl={addStockInlineControl}
          onTooltipClose={() => setActiveTooltip(null)}
          onTooltipOpen={setActiveTooltip}
          onAddStock={requestAddStock}
        />
      )}
      {activeTooltip && (
        <div
          className={`floating-tooltip ${currentActivePage === 'market-events' ? 'market-events-floating-tooltip' : ''}`}
          style={{
            left: activeTooltip.x,
            top: activeTooltip.y,
          }}
        >
          {activeTooltip.text}
        </div>
      )}
      {isLoginOpen && (
        <div className="modal-backdrop" role="presentation">
          <form aria-modal="true" className="confirm-modal login-modal" role="dialog" onSubmit={submitLogin}>
            <button className="modal-close-button" type="button" aria-label="닫기" onClick={closeLoginModal}>
              ×
            </button>
            <h3>{userSession ? '내 계정' : authMode === 'recover' ? '비밀번호 찾기' : '로그인'}</h3>
            {userSession ? (
              <>
                <p>현재 계정으로 관심 종목과 게시글을 여러 기기에서 관리할 수 있습니다.</p>
                <div className="login-account-card">
                  <span>로그인 계정</span>
                  <strong>{userSession.email}</strong>
                </div>
                <div className="modal-actions auth-modal-actions">
                  <button className="modal-confirm logout-confirm auth-submit-button" type="button" onClick={logout}>
                    로그아웃
                  </button>
                </div>
              </>
            ) : (
              <>
                {authMode !== 'recover' ? (
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
                <p>{authMode === 'login' ? '가입한 이메일과 비밀번호로 로그인해 주세요.' : authMode === 'signup' ? '이메일 인증으로 계정을 만들어 주세요.' : '가입한 이메일로 비밀번호 재설정 안내를 받을 수 있습니다.'}</p>
                {serviceStatusMessage && (
                  <div className="recovery-sent-card">
                    <strong>{isSupabaseConfigured ? '계정 동기화 중입니다.' : '서비스 계정 설정이 필요합니다.'}</strong>
                    <span>{serviceStatusMessage}</span>
                  </div>
                )}
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
                {shouldShowEmailValidation && <span className="login-error">이메일 형식이 올바르지 않습니다.</span>}
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
                    {authMode === 'signup' && (
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
                  </div>
                )}
                {loginError && <span className="login-error">{loginError}</span>}
                <div className="modal-actions auth-modal-actions">
                  <button className="modal-confirm auth-submit-button" disabled={isAuthSubmitDisabled} type="submit">
                    {authMode === 'login' ? '로그인' : authMode === 'signup' ? '회원가입' : '재설정 안내 받기'}
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
      {isHoldingDeleteConfirmOpen && (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="confirm-modal" role="dialog">
            <h3>선택한 보유 종목을 삭제할까요?</h3>
            <p>선택한 보유중인 종목 기록이 삭제되며, 연결된 트레이딩 로그도 함께 삭제됩니다. 이 작업은 복구할 수 없습니다.</p>
            <div className="modal-actions">
              <button className="modal-cancel" type="button" onClick={() => setIsHoldingDeleteConfirmOpen(false)}>
                취소
              </button>
              <button className="modal-confirm" type="button" onClick={removeSelectedHoldingTrades}>
                삭제
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
