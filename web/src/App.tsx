import './App.css'
import { Fragment, type FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { fetchAppData, saveMarketEvents, type RuntimeMeta } from './api'

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
  email: string
  name: string
  loggedInAt: string
}

type AuthAccount = {
  email: string
  name: string
  password: string
  createdAt: string
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
  id: number
  category: BoardCategory
  content: string
  createdAt: string
  authorId: string
  authorName: string
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
const AUTH_ACCOUNTS_STORAGE_KEY = 'gongsu-auth-accounts'
const AUTH_SESSION_STORAGE_KEY = 'gongsu-user-session'
const DEFAULT_ADMIN_EMAILS = ['admin@gongsu.local']

function configuredAdminEmails() {
  return (import.meta.env.VITE_ADMIN_EMAILS ?? DEFAULT_ADMIN_EMAILS.join(','))
    .split(',')
    .map((email: string) => email.trim().toLowerCase())
    .filter(Boolean)
}

function readStoredAccounts() {
  const storedAccounts = localStorage.getItem(AUTH_ACCOUNTS_STORAGE_KEY)
  if (!storedAccounts) return [] as AuthAccount[]

  try {
    const parsed = JSON.parse(storedAccounts)
    return Array.isArray(parsed) ? parsed as AuthAccount[] : []
  } catch {
    localStorage.removeItem(AUTH_ACCOUNTS_STORAGE_KEY)
    return [] as AuthAccount[]
  }
}

function saveStoredAccounts(accounts: AuthAccount[]) {
  localStorage.setItem(AUTH_ACCOUNTS_STORAGE_KEY, JSON.stringify(accounts))
}

const demoLimitStocks: Stock[] = Array.from({ length: 38 }, (_, index) => {
  const sequence = index + 1

  return {
    ticker: `DEMO${String(sequence).padStart(2, '0')}`,
    name: `데모종목 ${sequence}`,
    market: sequence % 3 === 0 ? 'KR' : 'US',
    fairPrice: sequence % 3 === 0 ? `₩${(42_000 + sequence * 1_150).toLocaleString()}` : `$${(36 + sequence * 1.7).toFixed(2)}`,
    currentPrice: sequence % 3 === 0 ? `₩${(39_500 + sequence * 1_030).toLocaleString()}` : `$${(34 + sequence * 1.45).toFixed(2)}`,
    valuation: sequence % 4 === 0 ? '고평가' : sequence % 2 === 0 ? '보통' : '저평가',
    opinion: sequence % 4 === 0 ? '매도' : sequence % 2 === 0 ? '관망' : '매수',
    strategies: ['D. 200일선 상방 & 상승 흐름 강화'],
    updatedAt: '데모',
  }
})

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
  ...demoLimitStocks,
]

const initialWatchlist = [
  'AAPL',
  '035420',
  'NVDA',
  '005930',
  '042700',
  '247540',
  'ONON',
  'BE',
  'LRCX',
  'SNDK',
  'TSLA',
  'MSFT',
  ...demoLimitStocks.map((stock) => stock.ticker),
]

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

const operatorTickers = ['005930', '042700', '247540', 'ONON', 'BE', 'LRCX', 'SNDK', 'AAPL', '035420', 'NVDA', 'TSLA', 'MSFT']
const strategyFilters = ['A', 'B', 'C', 'D', 'E', 'F']
const personalTradeTickers = new Set(['AAPL', 'NVDA', '035420'])
const personalTrades = trades.filter((trade) => personalTradeTickers.has(trade.ticker))
const operatorTrades = trades
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
    A: '강세 구조에서 눌림 이후 모멘텀이 다시 붙는 구간입니다. 추세가 살아 있을 때 재가속 신호를 우선 봅니다.',
    B: '200일선 아래에서 과매도와 공포가 겹친 구간입니다. 반등 가능성은 보지만 실패 시 손절 기준이 중요합니다.',
    C: '변동성이 압축된 뒤 거래량과 함께 방향성이 나오는 구간입니다. 돌파 이후 추세 지속 여부를 확인합니다.',
    D: '200일선 위에서 상승 흐름이 더 강해지는 구간입니다. 이미 강한 종목의 추세 추종 성격이 큽니다.',
    E: '상승 구조는 유지되지만 가격과 변동성이 눌린 구간입니다. 추세 안의 저점 재진입 후보로 봅니다.',
    F: '강세 구조 안에서 볼린저밴드 하단까지 과하게 밀린 구간입니다. 극단 저점 반등을 노리지만 변동성이 큽니다.',
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

function tradeKey(trade: TradeLog) {
  return `${trade.ticker}-${trade.buyDate}`
}

const gnbMenus = ['HOME', '가치 분석', '기술 분석', '시장 주요 이벤트', '시장 트렌드', '게시판']
const boardCategories: BoardCategory[] = ['칭찬', '버그', '건의', '기타']
const boardFilters: BoardFilter[] = ['전체', ...boardCategories]

const initialBoardPosts: BoardPost[] = [
  {
    id: 1,
    category: '건의',
    content: '관심 종목별로 알림 조건을 직접 켜고 끌 수 있으면 좋겠습니다.',
    createdAt: '2026-05-03T10:20:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 2,
    category: '칭찬',
    content: '가치분석과 기술분석을 한 화면에서 비교할 수 있어서 흐름 파악이 편합니다.',
    createdAt: '2026-05-03T12:05:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 3,
    category: '버그',
    content: '모바일에서 표를 가로 스크롤할 때 헤더가 살짝 늦게 따라오는 것 같습니다.',
    createdAt: '2026-05-03T14:10:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 4,
    category: '기타',
    content: '시장 주요 이벤트에서 당일 일정이 더 잘 보이게 바뀐 점이 좋습니다.',
    createdAt: '2026-05-03T15:40:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 5,
    category: '건의',
    content: '기술분석 공통지표를 접었을 때도 중요한 이벤트만 한 줄로 요약되면 좋겠습니다.',
    createdAt: '2026-05-03T16:15:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 6,
    category: '칭찬',
    content: '게시판을 페이지 전환 없이 바로 작성할 수 있어서 피드백 남기기 편합니다.',
    createdAt: '2026-05-03T17:02:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 7,
    category: '버그',
    content: '시장 트렌드 표에서 긴 텍스트가 있는 셀은 가로 스크롤 위치를 잃기 쉽습니다.',
    createdAt: '2026-05-03T18:24:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 8,
    category: '건의',
    content: '관심 종목을 전략별로 묶어서 볼 수 있는 필터가 있으면 좋겠습니다.',
    createdAt: '2026-05-03T19:11:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 9,
    category: '기타',
    content: '나중에 알림 설정 페이지가 생기면 게시판 건의와 연결해서 관리되면 좋겠습니다.',
    createdAt: '2026-05-03T20:36:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 10,
    category: '칭찬',
    content: '색상이 이전보다 훨씬 차분해져서 오래 봐도 덜 피로합니다.',
    createdAt: '2026-05-03T21:08:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 11,
    category: '건의',
    content: '시장 트렌드 요약에 관련 종목 예시도 같이 있으면 투자 아이디어를 잡기 쉬울 것 같습니다.',
    createdAt: '2026-05-03T22:17:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
  {
    id: 12,
    category: '버그',
    content: '로그인 모달에서 비밀번호 입력 후 엔터를 눌렀을 때 포커스 흐름을 한 번 확인해 주세요.',
    createdAt: '2026-05-03T23:04:00',
    authorId: 'sample-user',
    authorName: '사용자',
  },
]

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

const eventMonths = ['1월', '2월', '3월', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월']

const marketEventGroups: MarketEventGroup[] = [
  {
    title: '금리 발표',
    tooltip: '미국 기준금리 방향을 확인하는 FOMC 발표입니다. 금리 경로가 바뀌면 할인율, 성장주 밸류에이션, 환율 기대가 동시에 움직여 변동성이 커질 수 있습니다.',
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
    tooltip: '미국 고용시장 강도를 보여주는 핵심 지표 발표입니다. 고용이 예상보다 강하거나 약하면 금리 인하 기대와 경기 판단이 급변해 지수 변동성이 커질 수 있습니다.',
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
    tooltip: '소비자물가 상승률을 확인하는 대표 인플레이션 지표입니다. 예상치를 벗어나면 금리 기대가 크게 조정되어 채권, 달러, 성장주가 함께 흔들릴 수 있습니다.',
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
    tooltip: '생산자물가로 기업 비용 압력과 향후 소비자물가 방향을 가늠합니다. 원가 부담이 예상보다 크면 인플레이션 우려가 커져 금리와 주식 변동성이 확대될 수 있습니다.',
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
    tooltip: '연준이 선호하는 물가 지표로 소비와 인플레이션 흐름을 함께 봅니다. 예상보다 높거나 낮으면 통화정책 기대가 바뀌어 지수와 금리 변동성이 커질 수 있습니다.',
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
    tooltip: '주가지수·주식 옵션과 선물 만기가 겹치는 날입니다. 포지션 정리와 롤오버 수급이 집중되어 장중 거래량과 변동성이 평소보다 커질 수 있습니다.',
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
    tooltip: '나스닥 100 구성 종목과 비중이 조정되는 일정입니다. 편입·편출 및 비중 변화에 맞춘 패시브 수급이 발생해 관련 종목 변동성이 커질 수 있습니다.',
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
  { label: 'Market Cap', value: (metric) => metric.marketCap, tooltip: '기업의 전체 시장 가치입니다. 클수록 안정성은 높지만 성장 여지는 제한될 수 있으며, 동종 업계와 비교해 과도하게 비싼지 함께 봅니다.' },
  { label: 'Sales', value: (metric) => metric.sales, tooltip: '최근 매출 규모입니다. 클수록 사업 기반이 크다는 뜻이며, 성장률 없이 매출만 크면 매력도가 낮을 수 있습니다.' },
  { label: 'Sales Q/Q', value: (metric) => metric.salesQoq, tooltip: '전분기 대비 매출 성장률입니다. 양수이고 높을수록 단기 모멘텀이 좋고, 마이너스가 지속되면 수요 둔화를 의심합니다.' },
  { label: 'Sales Y/Y (TTM)', value: (metric) => metric.salesYoyTtm, tooltip: '최근 12개월 매출의 전년 대비 성장률입니다. 높을수록 구조적 성장 가능성이 크고, 둔화되면 밸류에이션 부담을 낮춰 봅니다.' },
  { label: 'Sales past 3/5Y', value: (metric) => metric.salesPastYears, tooltip: '최근 3년/5년 매출 성장 흐름입니다. 꾸준히 높으면 장기 성장성이 좋고, 변동이 크면 사이클 산업 여부를 확인합니다.' },
  { label: 'Current Ratio', value: (metric) => metric.currentRatio, tooltip: '유동자산을 유동부채로 나눈 단기 지급 능력입니다. 보통 1 이상이면 안정적으로 보고, 너무 낮으면 단기 재무 리스크가 커질 수 있습니다.' },
  { label: 'P/FCF', value: (metric) => metric.priceToFreeCashFlow, tooltip: '시가총액 대비 잉여현금흐름 배수입니다. 낮을수록 현금창출력 대비 저렴하고, 높으면 미래 성장 기대가 이미 반영됐을 수 있습니다.' },
  { label: 'P/S', value: (metric) => metric.priceToSales, tooltip: '시가총액을 매출로 나눈 배수입니다. 낮을수록 매출 대비 가격 부담이 작고, 고성장 기업은 업계 평균과 함께 비교합니다.' },
  { label: 'PER', value: (metric) => metric.per, tooltip: '주가를 주당순이익으로 나눈 배수입니다. 낮을수록 이익 대비 저렴할 수 있고, 성장률이 낮은데 높으면 부담이 큽니다.' },
  { label: 'PBR', value: (metric) => metric.pbr, tooltip: '주가를 주당순자산으로 나눈 배수입니다. 낮을수록 장부가 대비 저렴하고, ROE가 낮은 기업의 높은 PBR은 주의합니다.' },
  { label: 'ROE', value: (metric) => metric.roe, tooltip: '자기자본으로 얼마나 이익을 냈는지 보여줍니다. 높고 꾸준할수록 자본 효율이 좋으며, 부채로 높아진 ROE인지 함께 확인합니다.' },
  { label: 'PEG', value: (metric) => metric.peg, tooltip: 'PER을 이익 성장률로 나눈 값입니다. 1 안팎이면 성장 대비 가격이 합리적이고, 높을수록 성장 대비 비싸다는 신호입니다.' },
  { label: 'Shares Outstanding', value: (metric) => metric.sharesOutstanding, tooltip: '시장에 발행된 총 주식 수입니다. 증가하면 주주 지분이 희석될 수 있고, 자사주 매입으로 감소하면 주당 가치에 우호적입니다.' },
  { label: 'Gross Margin', value: (metric) => metric.grossMargin, tooltip: '매출에서 원가를 뺀 매출총이익률입니다. 높을수록 제품 경쟁력과 가격 결정력이 좋고, 하락 추세면 원가 부담을 의심합니다.' },
  { label: 'Oper. Margin', value: (metric) => metric.operatingMargin, tooltip: '영업이익을 매출로 나눈 수익성 지표입니다. 높고 안정적이면 본업 경쟁력이 좋고, 마이너스면 성장보다 비용 구조를 먼저 봅니다.' },
  { label: 'EPS (TTM)', value: (metric) => metric.epsTtm, tooltip: '최근 12개월 주당순이익입니다. 높고 증가하면 이익 체력이 좋으며, 일회성 이익인지 확인이 필요합니다.' },
  { label: 'EPS Next Y', value: (metric) => metric.epsNextYear, tooltip: '다음 해 예상 주당순이익입니다. 현재 EPS보다 높으면 이익 성장 기대가 있고, 예상치 하향이 반복되면 보수적으로 봅니다.' },
  { label: 'EPS Q/Q (%)', value: (metric) => metric.epsQoq, tooltip: '전분기 대비 주당순이익 변화율입니다. 양수이고 높으면 단기 실적 모멘텀이 좋고, 마이너스가 지속되면 수익성 둔화를 의심합니다.' },
  { label: 'Rule of 40%', value: (metric) => metric.ruleOf40, tooltip: '성장률과 수익성을 함께 보는 지표입니다. 40% 이상이면 성장과 수익의 균형이 좋다고 보고, 낮거나 음수면 성장의 질을 다시 확인합니다.' },
  { label: '실적발표일', value: (metric) => metric.earningsDate },
]

const technicalMarketSnapshot = [
  ['시장 주요 이벤트', '당분간 없음'],
  ['VIX (변동성지수, 당일)', '16.99'],
  ['VIX (변동성지수, 전날)', '16.89'],
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
  { label: 'RSI (D)', tooltip: '당일 기준 14일 RSI입니다. 70 이상은 과열, 30 이하는 과매도로 해석하지만 강한 추세에서는 과열권 유지 자체가 모멘텀 신호가 될 수 있습니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 1, 29, 58), 2) },
  { label: 'RSI (D-1)', tooltip: '전일 기준 RSI입니다. 당일 RSI와 비교해 단기 매수세가 강화됐는지 둔화됐는지 판단합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 2, 28, 57), 2) },
  { label: 'RSI Signal', tooltip: 'RSI를 평활화한 기준선입니다. RSI가 시그널 위에 있으면 단기 탄력이 우위이고, 아래로 꺾이면 과열 해소 또는 약세 전환을 의심합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 3, 32, 48), 2) },
  { label: 'RSI 기울기', tooltip: '당일 RSI와 전일 RSI의 차이입니다. 플러스면 모멘텀이 강화되고, 마이너스면 상승 탄력이 둔화되는 방향으로 봅니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 4, -9, 16), 2) },
  { label: 'CCI (D)', tooltip: '당일 CCI입니다. +100 이상은 강한 상승 탄력, -100 이하는 약세 또는 과매도 구간으로 보며 추세 전환 확인에 사용합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 5, -130, 280), 2) },
  { label: 'CCI (D-1)', tooltip: '전일 CCI입니다. 당일 값과 함께 CCI 기울기와 추세 지속 여부를 확인합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 6, -125, 270), 2) },
  { label: 'CCI Signal', tooltip: 'CCI 기준선 또는 평활 신호입니다. CCI가 시그널을 상향 돌파하면 단기 반등 탄력이 붙는 신호로 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 7, -90, 240), 2) },
  { label: 'CCI 기울기', tooltip: '당일 CCI와 전일 CCI의 차이입니다. 급격한 플러스 전환은 반등 시도, 급격한 마이너스는 탄력 약화를 뜻합니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 8, -58, 136), 2) },
  { label: 'MACD (12, 26, D)', tooltip: '12일 EMA와 26일 EMA의 차이입니다. 0선 위는 중기 상승 우위, 아래는 하락 우위로 해석합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 9, -900, 12000), 2) },
  { label: 'MACD (12, 26, D-1)', tooltip: '전일 MACD입니다. 당일 MACD와 비교해 추세 가속 또는 둔화를 확인합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 10, -850, 11200), 2) },
  { label: 'MACD Signal', tooltip: 'MACD의 신호선입니다. MACD가 시그널 위에 있으면 상승 모멘텀, 아래에 있으면 둔화 또는 약세 신호로 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 11, -700, 9800), 2) },
  { label: 'MACD Histogram (D)', tooltip: 'MACD와 Signal의 차이입니다. 히스토그램이 커지면 추세가 강해지고, 줄어들면 모멘텀 둔화 가능성이 커집니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 12, -4200, 7600), 2) },
  { label: 'M - H (D-1)', tooltip: '전일 MACD 히스토그램입니다. 당일 히스토그램과 함께 방향 전환의 연속성을 봅니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 13, -2400, 5000), 2) },
  { label: 'M - H (D-2)', tooltip: '2거래일 전 MACD 히스토그램입니다. 3일 연속 개선 또는 악화를 확인해 속임수를 줄입니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 14, -2100, 4600), 2) },
  { label: 'MACD 기울기', tooltip: 'MACD 히스토그램의 변화폭입니다. 플러스 전환은 추세 재가속, 마이너스 전환은 상승 탄력 둔화로 해석합니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 15, -620, 1360), 2) },
  { label: '+DI (DMI, 14)', tooltip: 'DMI의 상승 방향성 지표입니다. +DI가 -DI보다 높으면 매수 방향성이 우세합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 16, 12, 52), 2) },
  { label: '-DI (DMI, 14)', tooltip: 'DMI의 하락 방향성 지표입니다. -DI가 +DI보다 높으면 매도 압력이 우세합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 17, 9, 48), 2) },
  { label: 'ADX (14, D)', tooltip: '추세의 강도를 보여주는 지표입니다. 보통 20 이상이면 추세가 형성되고, 40 이상이면 강한 추세로 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 18, 14, 58), 2) },
  { label: 'ADX (14, D-1)', tooltip: '전일 ADX입니다. 당일 ADX와 비교해 추세 강도가 커지는지 확인합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 19, 13, 57), 2) },
  { label: 'ADX (14, D-2)', tooltip: '2거래일 전 ADX입니다. 최근 3일의 추세 강도 흐름을 확인합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 20, 13, 55), 2) },
  { label: 'ADX 기울기', tooltip: 'ADX의 단기 변화폭입니다. 상승하면 추세가 강화되고, 하락하면 방향성보다 횡보 가능성이 커집니다.', value: (stock, index) => formatSignedTechnical(technicalNumber(stock, index, 21, -6, 12), 2) },
  { label: 'Candle Open', tooltip: '당일 캔들의 시가입니다. 종가와 비교해 양봉/음봉 및 장중 수급 방향을 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 22, 0.965, 0.07, 4)) },
  { label: 'C - High', tooltip: '당일 고가입니다. 종가가 고가에 가까울수록 장중 매수세가 끝까지 유지됐다고 해석합니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 23, 1.005, 0.06, 4)) },
  { label: 'C - Low', tooltip: '당일 저가입니다. 저가 대비 종가 회복폭은 아래꼬리와 반등 강도 판단에 사용합니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 24, 0.925, 0.065, 4)) },
  { label: 'C - Close', tooltip: '당일 종가입니다. 대부분의 기술 지표 계산 기준이 되는 가격입니다.', value: (stock) => stock.currentPrice },
  { label: 'C - Volume', tooltip: '당일 거래량입니다. 가격 신호가 거래량을 동반할 때 신뢰도가 높아집니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 25) },
  { label: '아래꼬리 길이', tooltip: '저가에서 종가 또는 시가까지 회복한 폭입니다. 길수록 저점 매수세 또는 투매 후 반등 가능성을 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 26, 0, 18), 2) },
  { label: '위꼬리 길이', tooltip: '고가에서 종가 또는 시가까지 밀린 폭입니다. 길수록 고점 매물 부담이나 돌파 실패 가능성을 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 27, 0, 16), 2) },
  { label: '몸통 길이', tooltip: '시가와 종가의 차이입니다. 몸통이 클수록 당일 방향성이 뚜렷합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 28, 0.2, 22), 2) },
  { label: '거래량 (D)', tooltip: '당일 거래량입니다. 돌파, 반등, 이탈 신호가 거래량 증가와 함께 나왔는지 확인합니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 29) },
  { label: '거래량 (D-1)', tooltip: '전일 거래량입니다. 당일 거래량과 비교해 수급 유입이 증가했는지 판단합니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 30) },
  { label: '20일 평균 대비 거래량 (D)', tooltip: '최근 20일 평균 거래량 대비 당일 거래량 비율입니다. 100% 이상이면 평균보다 활발한 거래입니다.', value: (stock, index) => `${formatTechnicalNumber(technicalNumber(stock, index, 31, 45, 165), 0)}%` },
  { label: '절대 거래량 (D)', tooltip: '거래대금 성격으로 보는 절대 거래량입니다. 유동성이 충분해야 신호의 실행 가능성이 높습니다.', value: (stock, index) => formatTechnicalVolume(stock, index, 32) },
  { label: '볼린저밴드 %B (종가)', tooltip: '종가가 볼린저밴드 안에서 어디에 위치하는지 보여줍니다. 80 이상은 상단 접근, 20 이하는 하단 접근으로 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 33, 5, 112), 2) },
  { label: '볼린저밴드 %B (저가)', tooltip: '저가 기준 밴드 위치입니다. 장중 하단 터치 후 회복했는지 확인할 때 사용합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 34, 0, 105), 2) },
  { label: '볼린저밴드 Peak (D)', tooltip: '당일 기준 최근 밴드 위치의 고점입니다. 과열 이후 둔화 여부를 판단합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 35, 20, 95), 2) },
  { label: '볼린저밴드 Peak (D-1)', tooltip: '전일 볼린저밴드 Peak입니다. 당일 값과 비교해 밴드 과열이 이어지는지 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 36, 18, 92), 2) },
  { label: '볼린저밴드 폭 (D)', tooltip: '당일 볼린저밴드 폭입니다. 폭이 좁으면 변동성 압축, 넓으면 변동성 확대 상태입니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 37, 8, 48), 2) },
  { label: '볼린저밴드 폭 (D-1)', tooltip: '전일 볼린저밴드 폭입니다. 당일 폭과 비교해 스퀴즈 해소 또는 변동성 축소를 판단합니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 38, 8, 46), 2) },
  { label: '지난 60일 볼린저밴드 폭 평균', tooltip: '최근 60일 평균 밴드 폭입니다. 현재 폭이 평균보다 낮으면 압축, 높으면 변동성 확대로 봅니다.', value: (stock, index) => formatTechnicalNumber(technicalNumber(stock, index, 39, 12, 42), 2) },
  { label: '현재가', tooltip: '가장 최근 기준 가격입니다. 이동평균선, 밴드, 진입가와 비교해 현재 위치를 판단합니다.', value: (stock) => stock.currentPrice },
  { label: '5일 이동평균선', tooltip: '단기 가격 평균입니다. 현재가가 5일선 위에 있으면 단기 모멘텀이 살아 있다고 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 40, 0.965, 0.07, 4)) },
  { label: '20일 이동평균선', tooltip: '단기~중기 기준선입니다. 20일선 위 유지 여부로 추세 지속과 눌림목을 판단합니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 41, 0.92, 0.13, 4)) },
  { label: '60일 이동평균선', tooltip: '중기 추세 기준선입니다. 60일선 위에서는 상승 구조, 아래에서는 중기 약세를 의심합니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 42, 0.84, 0.2, 4)) },
  { label: '144일 이동평균선', tooltip: '장기 추세 전환을 완만하게 확인하는 기준선입니다. 200일선보다 민감하게 구조 변화를 볼 때 사용합니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 43, 0.78, 0.24, 4)) },
  { label: '200일 이동평균선', tooltip: '장기 추세의 핵심 기준선입니다. 현재가가 200일선 위에 있으면 장기 상승 구조로 보는 경우가 많습니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 44, 0.72, 0.28, 4)) },
  { label: '120일 저가 회귀 추세선', tooltip: '최근 120일 저점 흐름을 기준으로 만든 회귀 추세선입니다. 추세선 위에서는 저점이 높아지는 구조로 봅니다.', value: (stock, index) => formatTechnicalPrice(stock, stockPriceNumber(stock) * technicalNumber(stock, index, 45, 0.68, 0.34, 4)) },
  { label: '실적발표일 (한국 시간 기준)', tooltip: '한국 시간 기준 실적 발표 예정일입니다. 실적 전후에는 변동성이 커질 수 있어 진입·청산 판단에 반영합니다.', value: (stock) => technicalEarningsDate(stock) },
  { label: '진입가', tooltip: '현재 보유 중인 시스템 포지션의 진입 가격입니다. 보유 전이면 비워두며, 추후 사용자가 설명할 전략 기준에 맞춰 채울 예정입니다.', value: (stock) => technicalEntryPrice(stock) },
  { label: '진입일', tooltip: '현재 보유 중인 시스템 포지션의 진입일입니다. 보유 전이면 비워둡니다.', value: (stock) => technicalEntryDate(stock) },
  { label: '진입 전략', tooltip: '진입에 사용된 전략명입니다. A~F 전략의 세부 의미는 Home의 전략 툴팁과 같은 기준으로 해석합니다.', value: (stock) => technicalEntryStrategy(stock) },
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
  onAddStock,
  onTooltipOpen,
  onTooltipClose,
}: {
  stocks: Stock[]
  viewMode: 'personal' | 'operator'
  valuationRows: Record<string, ValuationMetric>
  onAddStock: () => void
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  const visibleStocks = stocks.slice(0, MAX_WATCHLIST_ITEMS)

  return (
    <section className="panel value-analysis-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>가치 분석</h2>
          <p>Home 관심 종목 기준으로 핵심 재무 지표를 확인해 적정가를 계산하고, 현재가를 기준으로 저평가/고평가 여부를 판단합니다.</p>
        </div>
        <span>총 {visibleStocks.length}개</span>
      </div>

      <div className="sheet-wrap value-analysis-sheet">
        {stocks.length === 0 ? (
          <div className="watchlist-empty-panel">
            <div className="empty-watchlist">
              <strong>관심 종목이 없습니다.</strong>
              <span>Home에서 종목을 추가하면 가치 분석 표에 표시됩니다.</span>
              {viewMode === 'personal' && (
                <button type="button" onClick={onAddStock}>관심 종목 추가</button>
              )}
            </div>
          </div>
        ) : (
          <table className="sheet-table value-analysis-table">
            <thead>
              <tr>
                <th>종목명</th>
                <th>티커</th>
                <th>구분</th>
                <th>산업</th>
                <th>적정 주가 범위</th>
                <th>현재가</th>
                <th>투자 의견</th>
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

                return (
                  <tr key={stock.ticker}>
                    <td className="name-data-cell">
                      <div className="name-cell">
                        <span className="market-flag" aria-hidden="true">{marketFlag(stock.market)}</span>
                        <span>{stock.name}</span>
                      </div>
                    </td>
                    <td className="ticker-cell">{stock.ticker}</td>
                    <td>{stock.market === 'KR' ? '성장주' : '가치주'}</td>
                    <td className="industry-cell">{stock.strategies[0].includes('스퀴즈') ? '반도체, AI, 소프트웨어' : '반도체, 커머스, 클라우드'}</td>
                    <td className="number-cell">{stock.fairPrice}</td>
                    <td className="number-cell">{stock.currentPrice}</td>
                    <td><span className={`status-badge ${statusClass(stock.valuation)}`}>{stock.valuation}</span></td>
                    {valueMetricColumns.map((column) => (
                      <td className="number-cell" key={column.label}>
                        {metric ? column.value(metric) : '-'}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

function TechnicalAnalysisPage({
  stocks,
  viewMode,
  technicalRows,
  marketSnapshot,
  onAddStock,
  onTooltipOpen,
  onTooltipClose,
}: {
  stocks: Stock[]
  viewMode: 'personal' | 'operator'
  technicalRows: Record<string, Record<string, string>>
  marketSnapshot: string[][]
  onAddStock: () => void
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
}) {
  const visibleStocks = stocks.slice(0, MAX_WATCHLIST_ITEMS)

  return (
    <section className="panel value-analysis-panel technical-analysis-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>기술 분석</h2>
          <p>Home 관심 종목 기준으로 RSI, CCI, MACD, DMI, 캔들, 거래량, 볼린저밴드, 이동평균 데이터 등의 기술 지표들을 활용해 매매 타이밍을 판단합니다.</p>
          <p className="page-warning">※ 기술 지표는 삼성증권 앱과 동일한 계산 방식을 적용해, 본인이 바라보는 지표와 일부 다를 수 있습니다.</p>
        </div>
        <span>총 {visibleStocks.length}개</span>
      </div>

      <details className="technical-summary-disclosure">
        <summary>
          <span>공통 지표</span>
          <strong>VIX (변동성지수) 16.99</strong>
          <strong>나스닥(QQQ) 674.18 / 200일선 604.08</strong>
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

      <div className="sheet-wrap value-analysis-sheet technical-analysis-sheet">
        {stocks.length === 0 ? (
          <div className="watchlist-empty-panel">
            <div className="empty-watchlist">
              <strong>관심 종목이 없습니다.</strong>
              <span>Home에서 종목을 추가하면 기술 분석 표에 표시됩니다.</span>
              {viewMode === 'personal' && (
                <button type="button" onClick={onAddStock}>관심 종목 추가</button>
              )}
            </div>
          </div>
        ) : (
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
              {visibleStocks.map((stock, index) => {
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
                    const value = apiRow?.[column.label] ?? column.value(stock, index)
                    const isEntryStrategy = column.label === '진입 전략'

                    return (
                      <td className={isEntryStrategy ? 'strategy-data-cell technical-strategy-cell' : 'number-cell'} key={column.label}>
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
            </tbody>
          </table>
        )}
      </div>
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
  if (entry.status) return entry.status

  const eventDate = parseMarketEventDate(entry.date)
  if (!eventDate) return 'none'

  const today = new Date()
  const todayDate = new Date(today.getFullYear(), today.getMonth(), today.getDate())

  if (eventDate.getTime() === todayDate.getTime()) return 'today'
  if (eventDate.getTime() < todayDate.getTime()) return 'past'
  return 'future'
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

function MarketEventsPage({
  groups,
  isAdmin,
  isSaving,
  onTooltipOpen,
  onTooltipClose,
  onEventChange,
  onSave,
}: {
  groups: MarketEventGroup[]
  isAdmin: boolean
  isSaving: boolean
  onTooltipOpen: (tooltip: TooltipState) => void
  onTooltipClose: () => void
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
          <span>어드민 모드: 발표일, D-day, 발표 시간을 수정할 수 있습니다.</span>
          <button disabled={isSaving} type="button" onClick={onSave}>
            {isSaving ? '저장 중...' : '이벤트 저장'}
          </button>
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
            {eventMonths.map((month, index) => (
              <tr key={month}>
                {index === 0 && <td className="event-year-cell" rowSpan={eventMonths.length}>2026년</td>}
                <td className="event-month-cell">{month}</td>
                {groups.map((group, groupIndex) => {
                  const entry = group.entries[index]
                  const isGroupStart = groupIndex > 0

                  return (
                    <Fragment key={`${group.title}-${month}`}>
                      <td className={marketEventDateClass(entry, isGroupStart)}>
                        {isAdmin ? (
                          <input
                            aria-label={`${group.title} ${month} 발표일`}
                            className="event-edit-input"
                            value={entry.date}
                            onChange={(event) => onEventChange(groupIndex, index, 'date', event.target.value)}
                          />
                        ) : entry.date}
                      </td>
                      <td className={marketEventDdayClass(entry)}>
                        {isAdmin ? (
                          <input
                            aria-label={`${group.title} ${month} D-day`}
                            className="event-edit-input event-edit-input-short"
                            value={entry.dday}
                            onChange={(event) => onEventChange(groupIndex, index, 'dday', event.target.value)}
                          />
                        ) : marketEventStatus(entry) === 'today' ? '0' : entry.dday}
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
  const sortedMarketTrendRows = [...rows].sort((a, b) => new Date(b.date.replaceAll('.', '-')).getTime() - new Date(a.date.replaceAll('.', '-')).getTime())

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
            {sortedMarketTrendRows.map((row) => (
              <tr key={row.date}>
                <td className="number-cell trend-date-cell">{row.date}</td>
                {row.ranks.map((rank, index) => (
                  <td className="trend-rank-cell" key={`${row.date}-${index + 1}`}>{rank}</td>
                ))}
                <td className="trend-summary-cell">{row.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
  if (!value) return '사용자'
  return `${value.slice(0, 3)}***`
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
  onPageChange,
  onShowMineOnlyChange,
  onSortDirectionChange,
  onSubmit,
}: {
  posts: BoardPost[]
  category: BoardCategory
  content: string
  filter: BoardFilter
  currentUserId: string
  page: number
  showMineOnly: boolean
  sortDirection: BoardSortDirection
  onCategoryChange: (category: BoardCategory) => void
  onContentChange: (content: string) => void
  onDeletePost: (postId: number) => void
  onFilterChange: (filter: BoardFilter) => void
  onPageChange: (page: number) => void
  onShowMineOnlyChange: (showMineOnly: boolean) => void
  onSortDirectionChange: (direction: BoardSortDirection) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}) {
  const postsPerPage = 10
  const filteredPosts = posts
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

  return (
    <section className="panel board-panel">
      <div className="section-heading value-analysis-heading">
        <div>
          <h2>게시판</h2>
          <p>서비스에 대한 칭찬, 버그, 건의, 기타 의견을 간편하게 남길 수 있습니다.</p>
        </div>
        <span>총 {posts.length}개</span>
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
                onPageChange(1)
              }}
            >
              내 글만 보기
            </button>
          </div>

          <div className="board-post-list">
            {paginatedPosts.length > 0 ? paginatedPosts.map((post) => (
              <article className={`board-post-card ${post.authorId === currentUserId ? 'my-board-post' : ''}`} key={post.id}>
                <div className="board-post-meta">
                  <div className="board-post-meta-left">
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
  const [watchlist, setWatchlist] = useState(initialWatchlist)
  const [operatorWatchlist, setOperatorWatchlist] = useState(operatorTickers)
  const [personalTradeLogs, setPersonalTradeLogs] = useState(personalTrades)
  const [isAddingStock, setIsAddingStock] = useState(false)
  const [viewMode, setViewMode] = useState<'personal' | 'operator'>('personal')
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
  const [userSession, setUserSession] = useState<UserSession | null>(() => {
    const storedSession = localStorage.getItem(AUTH_SESSION_STORAGE_KEY)
    if (!storedSession) return null

    try {
      return JSON.parse(storedSession) as UserSession
    } catch {
      localStorage.removeItem(AUTH_SESSION_STORAGE_KEY)
      return null
    }
  })
  const [apiStocks, setApiStocks] = useState<Stock[]>(searchUniverse)
  const [apiValuationMetrics, setApiValuationMetrics] = useState<Record<string, ValuationMetric>>(valuationMetrics)
  const [apiTechnicalRows, setApiTechnicalRows] = useState<Record<string, Record<string, string>>>({})
  const [apiMarketSnapshot, setApiMarketSnapshot] = useState<string[][]>(technicalMarketSnapshot)
  const [apiMarketEventGroups, setApiMarketEventGroups] = useState<MarketEventGroup[]>(marketEventGroups)
  const [apiMarketTrendRows, setApiMarketTrendRows] = useState<MarketTrendRow[]>(marketTrendRows)
  const [marketEventsMeta, setMarketEventsMeta] = useState<RuntimeMeta | undefined>()
  const [isSavingMarketEvents, setIsSavingMarketEvents] = useState(false)
  const [activePage, setActivePage] = useState<ActivePage>('home')
  const addStockButtonRef = useRef<HTMLButtonElement | null>(null)
  const inlineAddRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let isMounted = true

    fetchAppData<Stock, ValuationMetric, MarketEventGroup, MarketTrendRow>().then((data) => {
      if (!isMounted) return
      if (data.stocks?.rows && data.stocks.rows.length > 0) {
        setApiStocks(data.stocks.rows)
      }
      if (data.valuation?.rows && Object.keys(data.valuation.rows).length > 0) {
        const rows = data.valuation.rows
        setApiValuationMetrics((current) => ({ ...current, ...rows }))
      }
      if (data.technical?.rows) {
        setApiTechnicalRows(data.technical.rows)
      }
      if (data.technical?.marketSnapshot && data.technical.marketSnapshot.length > 0) {
        setApiMarketSnapshot(data.technical.marketSnapshot)
      }
      if (data.marketEvents?.groups && data.marketEvents.groups.length > 0) {
        setApiMarketEventGroups(data.marketEvents.groups)
      }
      if (data.marketEvents?.meta) {
        setMarketEventsMeta(data.marketEvents.meta)
      }
      if (data.marketTrends?.rows && data.marketTrends.rows.length > 0) {
        setApiMarketTrendRows(data.marketTrends.rows)
      }
    })

    return () => {
      isMounted = false
    }
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

      return ticker.startsWith(normalized) || name.startsWith(normalized)
    })
  }, [apiStocks, query])

  const scopedTrades = viewMode === 'personal' ? personalTradeLogs : operatorTrades
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
  const trimmedLoginEmail = loginEmail.trim().toLowerCase()
  const isAdminUser = userSession ? configuredAdminEmails().includes(userSession.email.toLowerCase()) : false
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

  const addToWatchlist = (ticker: string) => {
    if (watchlist.length >= MAX_WATCHLIST_ITEMS) {
      setIsAddingStock(true)
      return
    }

    setWatchlist((current) => current.includes(ticker) ? current : [...current, ticker])
    setQuery('')
    setIsAddingStock(false)
  }

  const removeSelectedStocks = () => {
    if (viewMode === 'personal') {
      setWatchlist((current) => current.filter((ticker) => !selectedTickers.includes(ticker)))
    } else {
      setOperatorWatchlist((current) => current.filter((ticker) => !selectedTickers.includes(ticker)))
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

  const resetSystemRecords = () => {
    setWatchlist([])
    setPersonalTradeLogs([])
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
    setIsRecoverySent(false)
  }

  const switchAuthMode = (mode: AuthMode) => {
    setAuthMode(mode)
    clearAuthForm()
  }

  const submitLogin = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const email = trimmedLoginEmail
    const password = loginPassword.trim()
    const passwordConfirm = loginPasswordConfirm.trim()

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setLoginError('이메일 형식이 올바르지 않습니다.')
      return
    }

    if (authMode === 'recover') {
      setIsRecoverySent(true)
      setLoginError('')
      return
    }

    if (password.length < 8) {
      setLoginError('비밀번호는 8자 이상이어야 합니다.\n8자 이상 입력하면 계속 진행할 수 있습니다.')
      return
    }

    const accounts = readStoredAccounts()
    const existingAccount = accounts.find((account) => account.email === email)

    if (authMode === 'signup') {
      if (existingAccount) {
        setLoginError('이미 가입된 이메일입니다.\n로그인 탭에서 기존 계정으로 로그인해 주세요.')
        return
      }

      if (password !== passwordConfirm) {
        setLoginError('비밀번호가 일치하지 않습니다.\n비밀번호 확인란을 다시 입력해 주세요.')
        return
      }

      accounts.push({
        email,
        name: email.split('@')[0],
        password,
        createdAt: new Date().toISOString(),
      })
      saveStoredAccounts(accounts)
    } else if (!existingAccount || existingAccount.password !== password) {
      setLoginError('이메일 또는 비밀번호가 일치하지 않습니다.\n입력한 계정 정보를 다시 확인해 주세요.')
      return
    }

    const accountName = authMode === 'signup' ? email.split('@')[0] : existingAccount?.name ?? email.split('@')[0]
    const nextSession = {
      email,
      name: accountName,
      loggedInAt: new Date().toISOString(),
    }

    localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(nextSession))
    setUserSession(nextSession)
    clearAuthForm()
    setAuthMode('login')
    setIsLoginOpen(false)
  }

  const logout = () => {
    localStorage.removeItem(AUTH_SESSION_STORAGE_KEY)
    setUserSession(null)
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
    setApiMarketEventGroups((current) => current.map((group, currentGroupIndex) => {
      if (currentGroupIndex !== groupIndex) return group
      return {
        ...group,
        entries: group.entries.map((entry, currentEntryIndex) => (
          currentEntryIndex === entryIndex ? { ...entry, [field]: value } : entry
        )),
      }
    }))
  }

  const saveMarketEventEntries = async () => {
    if (!isAdminUser) return
    setIsSavingMarketEvents(true)
    try {
      const saved = await saveMarketEvents(apiMarketEventGroups, marketEventsMeta)
      setApiMarketEventGroups(saved.groups)
      setMarketEventsMeta(saved.meta)
    } finally {
      setIsSavingMarketEvents(false)
    }
  }

  const submitBoardPost = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextContent = boardContent.trim()
    if (!nextContent) return

    setBoardPosts((currentPosts) => [
      {
        id: Date.now(),
        category: boardCategory,
        content: nextContent,
        createdAt: new Date().toISOString(),
        authorId: boardCurrentUserId(userSession),
        authorName: boardCurrentUserName(userSession),
      },
      ...currentPosts,
    ])
    setBoardContent('')
    setBoardFilter('전체')
    setBoardPage(1)
    setShowMineOnly(false)
    setBoardSortDirection('desc')
  }

  const deleteBoardPost = (postId: number) => {
    setBoardPosts((currentPosts) => currentPosts.filter((post) => post.id !== postId || post.authorId !== boardCurrentUserId(userSession)))
    setBoardPage(1)
  }

  const tableStocks = viewMode === 'personal' ? watchlistStocks : operatorStocks
  const isPersonalWatchlistEmpty = viewMode === 'personal' && tableStocks.length === 0
  const isPersonalWatchlistFull = viewMode === 'personal' && watchlist.length >= MAX_WATCHLIST_ITEMS
  const exampleStock = tableStocks[0]
  const showEmptyTradeExample = viewMode === 'personal' && tableStocks.length > 0 && scopedTrades.length === 0
  const showEmptyHoldingExample = viewMode === 'personal' && tableStocks.length > 0 && scopedOpenTrades.length === 0
  const tradeBlankRows = Math.max(3, 22 - filteredTrades.length - (showEmptyTradeExample ? 1 : 0))
  const watchlistBlankRows = Math.max(0, 10 - tableStocks.length)
  const holdingBlankRows = Math.max(0, 10 - scopedOpenTrades.length - (showEmptyHoldingExample ? 1 : 0))

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <img alt="공수성가 로고" className="brand-logo" src="/gongsu-logo.png" />
          <span>공수성가</span>
        </div>
        <nav className="gnb-menu" aria-label="주요 메뉴">
          {gnbMenus.map((menu) => {
            const isActive = (menu === 'HOME' && activePage === 'home') || (menu === '가치 분석' && activePage === 'value-analysis') || (menu === '기술 분석' && activePage === 'technical-analysis') || (menu === '시장 주요 이벤트' && activePage === 'market-events') || (menu === '시장 트렌드' && activePage === 'market-trends') || (menu === '게시판' && activePage === 'board')

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
          <span>지표와 판단 결과는 2시간 간격으로 정각에 업데이트됩니다.</span>
          <span>공수성가 또한 실제 데이터이며, 참고할 수 있게 제공됩니다.</span>
          <span>단, 모든 투자의 책임은 본인에게 있습니다.</span>
        </div>
        <div className="segmented-tabs global-tabs" aria-label="화면 기준">
          <button className={viewMode === 'personal' ? 'active' : ''} type="button" onClick={() => { setViewMode('personal'); setSelectedTickers([]); setSelectedHoldingTradeKeys([]) }}>
            본인
          </button>
          <button className={viewMode === 'operator' ? 'active' : ''} type="button" onClick={() => { setViewMode('operator'); setSelectedTickers([]); setSelectedHoldingTradeKeys([]) }}>
            공수성가
          </button>
        </div>
        <button className="reset-button" type="button" onClick={() => setIsResetConfirmOpen(true)}>
          초기화
        </button>
        <button
          className={`login-button ${userSession ? 'logged-in-button' : ''}`}
          type="button"
          onClick={() => setIsLoginOpen(true)}
        >
          {userSession ? userSession.name : '로그인'}
        </button>
      </header>

      {activePage === 'home' ? (
      <section className="dashboard-grid">
        <section className={`panel trading-log-panel ${isPersonalWatchlistEmpty ? 'dimmed-panel' : ''}`}>
          <div className="log-header">
            <div className="log-title-row">
              <h2>트레이딩 로그</h2>
              <div className="strategy-filter" aria-label="전략 필터">
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
                  <th>기준</th>
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
                    <td className="dash-cell">-</td>
                    <td className="dash-cell">-</td>
                    <td><span className="status-badge neutral">예시</span></td>
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
                {viewMode === 'personal' ? (
                  <>
                    {isPersonalWatchlistFull && (
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
                      className={`add-stock-button ${isPersonalWatchlistFull ? 'watchlist-limit-button' : ''}`}
                      disabled={isPersonalWatchlistFull}
                      ref={addStockButtonRef}
                      type="button"
                      onClick={() => setIsAddingStock((value) => !value)}
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

            {isAddingStock && viewMode === 'personal' && !isPersonalWatchlistFull && (
              <div className="inline-add" ref={inlineAddRef}>
                <input
                  autoFocus
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="삼성전자, 005930, AAPL"
                />
                {query && (
                  <div className="inline-results">
                    {searchResults.length > 0 ? searchResults.map((stock) => {
                      const isAlreadyAdded = watchlist.includes(stock.ticker)

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
                      <div className="empty-result">검색 결과가 없습니다.<br />다른 종목명이나 티커로 다시 검색해 주세요.</div>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="sheet-wrap watchlist-sheet">
              {tableStocks.length === 0 ? (
                <div className="watchlist-empty-panel">
                  <div className="empty-watchlist">
                    <strong>관심 종목이 없습니다.</strong>
                    <span>먼저 종목을 추가해 주세요.</span>
                    {viewMode === 'personal' && (
                      <button type="button" onClick={() => setIsAddingStock(true)}>관심 종목 추가</button>
                    )}
                  </div>
                </div>
              ) : (
                <table className="sheet-table watchlist-table">
                  <thead>
                    <tr>
                      {viewMode === 'personal' && <th>선택</th>}
                      <th>No</th>
                      <th>종목명</th>
                      <th>티커</th>
                      <th>적정 가격</th>
                      <th>현재가</th>
                      <th>가치 분석</th>
                      <th>기술 분석</th>
                      <th>시스템 보유</th>
                      <th>매수 전략</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableStocks.map((stock, index) => (
                      <tr key={stock.ticker}>
                        {viewMode === 'personal' && (
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
                        <td className="number-cell">{stock.fairPrice}</td>
                        <td className="number-cell">{stock.currentPrice}</td>
                        <td><span className={`status-badge ${statusClass(stock.valuation)}`}>{stock.valuation}</span></td>
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
                    ))}
                    {Array.from({ length: watchlistBlankRows }).map((_, index) => (
                      <tr className="blank-row" key={`watchlist-blank-${index}`}>
                        {viewMode === 'personal' && <td></td>}
                        <td className="numbering-cell">&nbsp;</td>
                        <td>&nbsp;</td>
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

          <section className={`panel ${isPersonalWatchlistEmpty ? 'dimmed-panel' : ''}`}>
            <div className="section-heading">
              <div className="section-title-inline">
                <h2>보유중인 종목</h2>
                <span>총 {scopedOpenTrades.length}개</span>
              </div>
              <div className="heading-actions">
                {viewMode === 'personal' && (
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
                    {viewMode === 'personal' && <th>선택</th>}
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
                      {viewMode === 'personal' && <td></td>}
                      <td className="numbering-cell">예시</td>
                      <td className="ticker-cell">{exampleStock.ticker}</td>
                      <td>
                        <div className="name-cell">
                          <span className="market-flag" aria-hidden="true">{marketFlag(exampleStock.market)}</span>
                          <span>{exampleStock.name}</span>
                        </div>
                      </td>
                      <td>신호 발생 시</td>
                      <td><span className="example-note">보유 전환 시 표시됩니다.</span></td>
                      <td className="dash-cell">-</td>
                      <td className="dash-cell">-</td>
                    </tr>
                  )}
                  {scopedOpenTrades.map((trade, index) => (
                    <tr key={`open-${tradeKey(trade)}`}>
                      {viewMode === 'personal' && (
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
                      {viewMode === 'personal' && <td></td>}
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
      ) : activePage === 'market-events' ? (
        <MarketEventsPage
          groups={apiMarketEventGroups}
          isAdmin={isAdminUser}
          isSaving={isSavingMarketEvents}
          onTooltipClose={() => setActiveTooltip(null)}
          onTooltipOpen={setActiveTooltip}
          onEventChange={updateMarketEventEntry}
          onSave={saveMarketEventEntries}
        />
      ) : activePage === 'market-trends' ? (
        <MarketTrendsPage rows={apiMarketTrendRows} />
      ) : activePage === 'board' ? (
        <BoardPage
          category={boardCategory}
          content={boardContent}
          currentUserId={boardCurrentUserId(userSession)}
          filter={boardFilter}
          page={boardPage}
          posts={boardPosts}
          showMineOnly={showMineOnly}
          sortDirection={boardSortDirection}
          onCategoryChange={setBoardCategory}
          onContentChange={setBoardContent}
          onDeletePost={deleteBoardPost}
          onFilterChange={setBoardFilter}
          onPageChange={setBoardPage}
          onShowMineOnlyChange={setShowMineOnly}
          onSortDirectionChange={setBoardSortDirection}
          onSubmit={submitBoardPost}
        />
      ) : activePage === 'value-analysis' ? (
        <ValueAnalysisPage
          stocks={tableStocks}
          viewMode={viewMode}
          valuationRows={apiValuationMetrics}
          onTooltipClose={() => setActiveTooltip(null)}
          onTooltipOpen={setActiveTooltip}
          onAddStock={() => {
            setActivePage('home')
            setIsAddingStock(true)
          }}
        />
      ) : (
        <TechnicalAnalysisPage
          stocks={tableStocks}
          viewMode={viewMode}
          marketSnapshot={apiMarketSnapshot}
          technicalRows={apiTechnicalRows}
          onTooltipClose={() => setActiveTooltip(null)}
          onTooltipOpen={setActiveTooltip}
          onAddStock={() => {
            setActivePage('home')
            setIsAddingStock(true)
          }}
        />
      )}
      {activeTooltip && (
        <div
          className="floating-tooltip"
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
                <p>현재 계정으로 관심 종목, 보유 종목, 알림 설정을 관리할 수 있습니다.</p>
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
                <p>{authMode === 'login' ? '가입한 이메일과 비밀번호로 로그인해 주세요.' : authMode === 'signup' ? '이메일과 비밀번호로 계정을 만들어 주세요.' : '가입한 이메일로 비밀번호 재설정 안내를 받을 수 있습니다.'}</p>
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
                {isRecoverySent && (
                  <div className="recovery-sent-card">
                    <strong>비밀번호 재설정 안내를 보냈습니다.</strong>
                    <span>입력한 이메일함을 확인해 주세요.</span>
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
            <h3>본인 기록을 모두 초기화할까요?</h3>
            <p>본인 관심 종목, 보유중인 종목, 트레이딩 로그 등 시스템에 기록된 본인 데이터를 모두 삭제합니다. 단, 공수성가 데이터는 유지됩니다.</p>
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
          <button type="button">이용약관</button>
          <span aria-hidden="true">|</span>
          <button type="button">개인정보처리방침</button>
        </div>
      </footer>
    </main>
  )
}

export default App
