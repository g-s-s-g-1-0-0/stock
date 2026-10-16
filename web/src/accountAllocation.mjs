// One allocation calculation for the browser and scheduled account reconciliation.
const SWING_RISK_GROUP_RULES = [
  ['반도체·AI 인프라', ['반도체', 'hbm', 'dram', 'nand', 'gpu', 'asic', 'ai 인프라', 'ai 데이터센터', '데이터센터 연결', '인터커넥트', '광인터커넥트', '광통신', '트랜시버']],
  ['전력·에너지', ['전력', '에너지', '원전', 'smr', '태양광', '풍력', '연료전지', '수소']],
  ['방산·우주', ['방산', '무기', '레이더', '드론', '무인체계', '우주', '위성', '발사체']],
  ['자동차·배터리', ['자동차', '전기차', '배터리', '2차전지', '리튬', '모빌리티']],
  ['금융·가상자산', ['금융', '은행', '보험', '증권', '핀테크', '가상화폐', '암호화폐', '비트코인']],
  ['바이오·헬스케어', ['바이오', '제약', '헬스케어', '의료', '진단']],
  ['소프트웨어·클라우드', ['소프트웨어', '클라우드', '사이버보안', 'ai 플랫폼']],
  ['산업재·건설', ['산업재', '건설', '플랜트', '철강', '조선', '물류', '자동화']],
  ['소비재', ['소비재', '식품', '유통', '화장품', '뷰티', '패션', '의류']],
  ['원자재', ['원자재', '광산', '희토류', '구리', '알루미늄', '금속']],
]
const trendThemeRules = [
  {
    theme: 'AI 인프라',
    keywords: ['AI 인프라', 'AI 서버', 'AI 팩토리', '데이터센터', 'GPU 클라우드', 'GPU 클러스터', 'HPC', '액침냉각', 'UPS'],
  },
  {
    theme: 'AI 반도체',
    keywords: ['AI GPU', 'AI칩', 'AI 칩', 'AI 반도체', 'AI 반도체 기판', 'CUDA', 'HBM', 'ASIC', 'GPU', '파운드리', '반도체', '첨단패키징', 'FC-BGA', '글라스 기판', 'CCL', '레이저 어닐링'],
  },
  {
    theme: '우주항공',
    keywords: ['우주', '위성', '발사체', '항공우주', '항공엔진', 'LEO', 'D2D', 'SpaceX', 'Rocket Lab', 'AST SpaceMobile', 'Planet Labs'],
  },
  {
    theme: '방산·드론',
    keywords: ['AI 방산', '방산', '국방', '드론', '무인기', '무인체계', '유도무기', '레이더', '자율무기'],
  },
  {
    theme: '전력 인프라',
    keywords: ['전력', '전력망', '전기장비', '가스터빈', '원전', 'SMR', '연료전지', '수소', '에너지 저장', '데이터센터 전력', 'AI 데이터센터'],
  },
  {
    theme: '광통신·네트워크',
    keywords: ['광통신', '광트랜시버', '트랜시버', '광케이블', '광송수신기', '광인터커넥트', '스위칭', '이더넷'],
  },
  {
    theme: '로봇·자동화',
    keywords: ['피지컬 AI', 'Physical AI', '로봇', '로보틱스', '협동로봇', '자동화', '휴머노이드', 'Optimus'],
  },
  {
    theme: '양자컴퓨팅',
    keywords: ['양자', '이온트랩', 'Quantum', '양자 네트워크'],
  },
  {
    theme: '암호화폐·핀테크',
    keywords: ['가상화폐', '비트코인', '이더리움', 'Solana', '스테이블코인', 'USDC', 'Coinbase', '블록체인'],
  },
  {
    theme: '전기차·배터리',
    keywords: ['전기차', '배터리', '2차전지', '리튬', '양극재', '자율주행', '로보택시'],
  },
  {
    theme: '바이오·헬스케어',
    keywords: ['바이오', '제약', '헬스케어', '의료', '재생의료', '바이오프린팅', 'Therapeutics'],
  },
  {
    theme: '글로벌 K-뷰티',
    keywords: ['K-뷰티', 'K뷰티', '글로벌 K-뷰티', '뷰티테크', '홈 뷰티', '화장품', '소셜커머스'],
  },
  {
    theme: '원자재·희토류',
    keywords: ['희토류', '리튬', '구리', '알루미늄', '광산', '금속', '자석'],
  },
]


const SWING_RISK_GROUP_MAX_PERCENT = 20
const price = (value) => Number(String(value || '').replace(/[^0-9.-]/g, '')) || 0
const parseTradeDate = (value) => Date.parse(String(value || '').replaceAll('.', '-').slice(0, 10)) || 0
const tradeDateObject = (value) => new Date(parseTradeDate(value))
export function accountTradeKey(trade) {
  const strategy = String(trade.strategy || '')
  const code = strategy.trim().match(/^([1-7])\b/)?.[1]
    || (/^B\b/i.test(strategy.trim()) ? '1' : strategy.slice(0, 1))
  return trade.slotId || `${trade.investmentType ?? 'shared'}-${trade.ticker}-${trade.buyDate}-${code}-${trade.buyPrice}`
}
const tradeKey = accountTradeKey
const normalizeTrendText = (value) => String(value || '').toLowerCase().replace(/\s+/g, '').replace(/[·,|/()]/g, '')
const normalizedKeywords = (values) => values.map(normalizeTrendText).filter((v) => v.length > 1 && v !== 'ai')
function tradePriority(trade, stocks, trends) {
  const industry = normalizeTrendText(stocks.find((s) => s.ticker === trade.ticker)?.industry)
  const rules = trendThemeRules.filter((r) => normalizedKeywords(r.keywords).some((k) => industry.includes(k)))
  const trend = trends.find((r) => { const days = (parseTradeDate(trade.buyDate) - parseTradeDate(r.date)) / 86400000; return days >= 0 && days < 7 })
  const index = trend?.ranks?.slice(0, 10).findIndex((rank) => rules.some((r) => {
    const text = normalizeTrendText(rank)
    return text.includes(normalizeTrendText(r.theme)) || normalizedKeywords(r.keywords).some((k) => text.includes(k))
  })) ?? -1
  return { megaRank: index >= 0 && index < 5 ? 0 : 1, trendRank: index >= 0 ? index + 1 : 99 }
}
function swingRiskGroupForTrade(trade, stocks) {
  if (trade.riskGroup && trade.riskGroup !== '분류 확인 필요') return trade.riskGroup
  const stock = stocks.get(trade.ticker) || {}
  const industry = stock.industry || ''
  const text = `${trade.ticker} ${trade.name || stock.name || ''} ${industry}`.toLowerCase()
  return SWING_RISK_GROUP_RULES.find(([, words]) => words.some((w) => text.includes(w)))?.[0]
    || (industry && industry !== '-' ? industry.split(',')[0].trim() : '분류 확인 필요')
}
function isLeveragedEtfTrade(trade, stocks) {
  const stock = stocks.get(trade.ticker) || {}
  const text = `${trade.ticker} ${trade.name || stock.name || ''} ${stock.industry || ''}`.toLowerCase()
  return ['etf','etn','direxion','proshares','kodex','tiger'].some((v) => text.includes(v))
    && (['레버리지','인버스','곱버스','ultra','bull','bear'].some((v) => text.includes(v)) || /(^|\W)[+-]?[23]x(\W|$)/.test(text))
}
function scheduledContributionBetween(start, end, settings) {
  let total = 0
  for (let time = start.getTime() + 86400000; time <= end.getTime(); time += 86400000) {
    const day = new Date(time)
    if (settings.frequency === 'weekly' ? day.getUTCDay() === settings.dayOfWeek : day.getUTCDate() === settings.dayOfMonth) total += settings.amount
  }
  return total
}
const allocationWeightsForProfile = (type, settings) => settings.allocationByInvestmentType[type].slotPercents.slice(0, settings.allocationByInvestmentType[type].slotCount).map((p) => p / 100)
function displayedTradeReturnPct(trade, stocks) {
  if (!['보유 중','매수 보류'].includes(trade.status)) return trade.returnPct || 0
  const entry = price(trade.buyPrice)
  const current = price(trade.currentPrice || stocks.find((s) => s.ticker === trade.ticker)?.currentPrice)
  return entry && current ? (current / entry - 1) * 100 : 0
}
export function normalizeAccountSettings(candidate = {}) {
  const number = (value, fallback) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback
  const allocationByInvestmentType = {}
  for (const type of ['swing','long_term']) {
    const raw = candidate.allocationByInvestmentType?.[type] || {}
    const legacy = type === 'swing' && raw.slotCount === 3 && String(raw.slotPercents) === '50,25,25'
    const count = legacy ? 10 : Math.min(20, Math.max(1, Math.round(number(raw.slotCount, 10))))
    allocationByInvestmentType[type] = { slotCount: count, megaTrendOnly: raw.megaTrendOnly === true,
      slotPercents: Array.from({length: count}, (_, i) => legacy ? 10 : Math.min(100, number(raw.slotPercents?.[i], i < 10 ? 10 : 0))) }
  }
  return { initialCapital: number(candidate.initialCapital, 10000000), amount: number(candidate.amount, 1000000),
    frequency: candidate.frequency === 'weekly' ? 'weekly' : 'monthly', dayOfWeek: number(candidate.dayOfWeek, 1),
    dayOfMonth: number(candidate.dayOfMonth, 1), allocationByInvestmentType }
}
export function calculateAccountPortfolio(inputTrades, stocks = [], trends = [], rawSettings = {}, investmentType = 'swing', initialCashOverride, asOf = new Date().toISOString()) {
  const settings = normalizeAccountSettings(rawSettings)
  const initialCash = initialCashOverride ?? settings.initialCapital
  const trades = inputTrades.map((t) => ({...t, status: t.allocationSource === 'account' && ['보유 중', '매수 보류'].includes(t.status) ? (t.allocationSignalStatus || t.status) : t.status}))
  const buyPriorityForTrade = (trade) => tradePriority(trade, stocks, trends)
  let runningCash = initialCash
  const slotWeights = allocationWeightsForProfile(investmentType, settings)
  const megaTrendOnly = settings.allocationByInvestmentType[investmentType].megaTrendOnly
  const allocationReasons = new Map()
  const allocationPercents = new Map()
  const stocksByTicker = new Map(stocks.map((stock) => [stock.ticker, stock]))
  const occupiedSlots = new Map()
  const occupiedTickerCounts = new Map()
  const swingRiskGroupPercent = new Map()
  const swingAllocationByTradeKey = new Map()
  const amountByTradeKey = new Map()
  let openInvestmentAmount = 0
  let cumulativeInvestmentAmount = 0
  let positionValue = 0
  let profitAmount = 0
  let realizedProfitAmount = 0
  let unrealizedProfitAmount = 0
  const eventsByDate = new Map()
  const addEvent = (date, field, trade) => {
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
      if (!occupiedSlots.has(key)) continue
      occupiedSlots.delete(key)
      const tickerCount = occupiedTickerCounts.get(trade.ticker) ?? 0
      if (tickerCount <= 1) occupiedTickerCounts.delete(trade.ticker)
      else occupiedTickerCounts.set(trade.ticker, tickerCount - 1)
      const swingAllocation = swingAllocationByTradeKey.get(key)
      if (swingAllocation) {
        const nextPercent = Math.max(0, (swingRiskGroupPercent.get(swingAllocation.group) ?? 0) - swingAllocation.percent)
        if (nextPercent === 0) swingRiskGroupPercent.delete(swingAllocation.group)
        else swingRiskGroupPercent.set(swingAllocation.group, nextPercent)
        swingAllocationByTradeKey.delete(key)
      }
    }

    const cashBeforeBuys = runningCash
    const allocationBaseBeforeBuys = cashBeforeBuys + [...occupiedSlots.keys()].reduce(
      (sum, key) => sum + (amountByTradeKey.get(key) ?? 0),
      0,
    )
    const orderedBuys = [...events.buys].sort((a, b) => {
      const aPriority = buyPriorityForTrade(a)
      const bPriority = buyPriorityForTrade(b)
      return aPriority.megaRank - bPriority.megaRank
        || aPriority.trendRank - bPriority.trendRank
        || a.ticker.localeCompare(b.ticker)
    })

    for (const trade of orderedBuys) {
      const key = tradeKey(trade)
      if (trade.status === '매수 보류' || trade.allocationSignalStatus === '매수 보류') {
        amountByTradeKey.set(key, 0)
        allocationReasons.set(key, trade.allocationReason || "서버 진입 한도에 따른 매수 보류")
        continue
      }
      const requestedAmount = trade.allocationRequestedAmount ?? (trade.allocationSource !== 'account' ? trade.investmentAmount : null)
      const fixedAmount = typeof requestedAmount === 'number' && Number.isFinite(requestedAmount)
        ? Math.max(0, Math.round(requestedAmount)) : null
      const blockedByMegaTrend = megaTrendOnly && fixedAmount === null && buyPriorityForTrade(trade).megaRank !== 0
      const duplicateSwingTicker = investmentType === 'swing' && (occupiedTickerCounts.get(trade.ticker) ?? 0) > 0
      const riskGroup = investmentType === 'swing' ? swingRiskGroupForTrade(trade, stocksByTicker) : ''
      const slotIndex = fixedAmount === 0 || blockedByMegaTrend || duplicateSwingTicker
        ? -1
        : slotWeights.findIndex((_, index) => ![...occupiedSlots.values()].includes(index))
      const configuredPercent = slotIndex >= 0 ? slotWeights[slotIndex] * 100 : 0
      const fixedPercent = fixedAmount !== null && allocationBaseBeforeBuys > 0 ? fixedAmount / allocationBaseBeforeBuys * 100 : null
      const leveragedEtf = investmentType === 'swing' && isLeveragedEtfTrade(trade, stocksByTicker)
      const recommendedPercent = investmentType === 'swing'
        ? (fixedPercent ?? (slotIndex >= 0 ? (leveragedEtf ? Math.min(5, configuredPercent) : configuredPercent) : 0))
        : configuredPercent
      const blockedByRiskGroup = investmentType === 'swing'
        && (
          riskGroup === '분류 확인 필요'
          || (swingRiskGroupPercent.get(riskGroup) ?? 0) + recommendedPercent > SWING_RISK_GROUP_MAX_PERCENT
        )
      const blockedByPositionSize = investmentType === 'swing'
        && fixedPercent !== null
        && fixedPercent > (leveragedEtf ? 5 : Math.max(configuredPercent, 10))
      const amount = slotIndex >= 0 && !blockedByRiskGroup && !blockedByPositionSize
        ? fixedAmount !== null
          ? Math.min(runningCash, fixedAmount)
          : Math.min(runningCash, Math.max(0, Math.floor(allocationBaseBeforeBuys * recommendedPercent / 100)))
        : 0
      amountByTradeKey.set(key, amount)
      allocationPercents.set(key, recommendedPercent)
      allocationReasons.set(key, amount > 0 ? ''
        : blockedByMegaTrend ? '메가트렌드 Top 5 미충족'
        : duplicateSwingTicker ? '동일 종목은 한 포지션만 허용'
        : fixedAmount === 0 ? '투자금 0원으로 지정'
        : slotIndex < 0 ? `전체 ${slotWeights.length}슬롯 사용 중`
        : riskGroup === '분류 확인 필요' ? '대표 위험군 분류 확인 필요'
        : blockedByRiskGroup ? `${riskGroup} 산업 비중 20% 한도 초과`
        : blockedByPositionSize ? '종목별 투자 비중 한도 초과'
        : runningCash <= 0 ? '매수 시점 보유 현금 부족'
        : '슬롯 비중 또는 배정 가능한 투자금이 0원')
      if (slotIndex >= 0 && amount > 0) {
        occupiedSlots.set(key, slotIndex)
        occupiedTickerCounts.set(trade.ticker, (occupiedTickerCounts.get(trade.ticker) ?? 0) + 1)
        if (investmentType === 'swing') {
          swingRiskGroupPercent.set(riskGroup, (swingRiskGroupPercent.get(riskGroup) ?? 0) + recommendedPercent)
          swingAllocationByTradeKey.set(key, { group: riskGroup, percent: recommendedPercent })
        }
      }
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
    } else if (trade.status !== '매수 보류') {
      realizedProfitAmount += tradeProfit
    }
  }

  runningCash += scheduledContributionBetween(contributionCursor, new Date(asOf), settings)
  const projectedCash = Math.round(runningCash)
  const cash = projectedCash
  const investedAmount = openInvestmentAmount
  const totalCapital = openInvestmentAmount
  const totalAsset = cash + positionValue
  const profitRate = cumulativeInvestmentAmount > 0 ? profitAmount / cumulativeInvestmentAmount * 100 : 0

  const resolvedTrades = trades.map((trade) => {
    const { allocationSignalStatus, ...original } = trade
    const key = tradeKey(trade)
    const amount = amountByTradeKey.get(key) ?? 0
    const tracked = ['보유 중', '매수 보류'].includes(trade.status)
    return {
      ...original,
      allocationSignalStatus: allocationSignalStatus || trade.status,
      allocationSource: 'account',
      ...(trade.allocationRequestedAmount !== undefined || trade.allocationSource !== 'account' && typeof trade.investmentAmount === 'number' ? { allocationRequestedAmount: trade.allocationRequestedAmount ?? trade.investmentAmount } : {}),
      investmentAmount: amount,
      ...(tracked ? {
        status: amount > 0 ? '보유 중' : '매수 보류',
        sellDate: amount > 0 ? '보유 중' : '-',
        allocationStatus: amount > 0 ? '진입 가능' : '매수 보류',
        recommendedAllocationPercent: allocationPercents.get(key) ?? trade.recommendedAllocationPercent ?? 0,
        allocationReason: allocationReasons.get(key) || '',
      } : {}),
    }
  })
  return {
    trades: resolvedTrades,
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
