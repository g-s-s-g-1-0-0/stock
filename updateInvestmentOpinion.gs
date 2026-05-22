const CONSTANTS = {
  COL_INDICES: {
    stockName:    0,
    stockLabel:   1,
    currentPrice: 44,
    opinion:      3,
    rsi:          4,
    cci:          8,
    macdHist:     15,
    macdHistD1:   16,
    macdHistD2:   17,
    pctB:         37,
    pctBLow:      38,
    candleLow:    27,
    ma20:         46,
    bbWidth:      41,
    bbWidthD1:    42,
    bbWidthAvg60: 43,
    ma200:        49,
    lrTrendline:  50,
    entryPrice:    52,
    entryDate:     53,
    entryStrategy: 54,
    volRatio:  35,
    plusDI:    19,
    minusDI:   20,
    adx:       21,
    adxD1:     22,
  },
  STRATEGY: {
    VIX_MIN:         30,
    VIX_RELEASE:     23,
    RSI_MAX:         35,
    CCI_MIN:        -150,
    LR_TOUCH_RATIO:  1.05,
    TARGET_PCT_A:           0.20,
    CIRCUIT_PCT_A:          0.30,
    GOLDEN_CROSS_PCTB_MIN:  80,
    GOLDEN_CROSS_RSI_MIN:   70,
    TARGET_PCT_B:    0.20,
    CIRCUIT_PCT_B:   0.30,
    TARGET_PCT_C:              0.20,
    CIRCUIT_PCT_C:             0.30,
    C_SQUEEZE_RATIO:           0.45,
    BB_EXPAND_RATIO:           1.00,
    SQUEEZE_BREAKOUT_VOL_RATIO: 1.5,
    SQUEEZE_BREAKOUT_PCTB_MIN:  55,
    TARGET_PCT_D:    0.12,
    CIRCUIT_PCT_D:   0.25,
    ADX_MIN:         30,
    ADX_PCTB_MIN:    30,
    ADX_PCTB_MAX:    75,
    TARGET_PCT_E:    0.20,
    CIRCUIT_PCT_E:   0.30,
    SQUEEZE_RATIO:   0.5,
    SQUEEZE_PCT_B_MAX: 50,
    TARGET_PCT_F:    0.20,
    CIRCUIT_PCT_F:   0.30,
    BB_PCT_B_LOW_MAX: 5,
    TARGET_PCT_G:    0.12,
    CIRCUIT_PCT_G:   0.10,
    G_QQQ_DIST_MIN:  8,
    G_QQQ_DIST_MAX:  18,
    G_MA20_SLOPE5_MIN: 0.005,
    G_RSI_MIN:       45,
    G_RSI_MAX:       80,
    G_VOL_RATIO20_MAX: 2.0,
    G_MA200_OVERHEAT_MAX: 0.80,
    STALLED_EXIT_DAYS: 5,
    STALLED_EXIT_MIN_RETURN: 0.05,
    HALF_EXIT_DAYS:    60,
    MAX_HOLD_DAYS:     120,
    MAX_HOLD_DAYS_D:   30,
    MAX_HOLD_DAYS_G:   40,
    SELL_HOLD_HOURS:   48,
    REENTRY_DAYS:      10,
    REENTRY_DROP:      0.03,
    NASDAQ_BUY_BLOCK_MAX: 9,
    NASDAQ_RECOVERY_BUY_BLOCK_MAX: 18,
    NASDAQ_DIST_UPPER:   -3,
    NASDAQ_DIST_LOWER:   -12,
    NASDAQ_DIST_RELEASE: -2.5,
    QQQ_RECOVERY_MIN_DIST: -5,
    QQQ_NORMAL_PEAK_DIRECT_DIST: 16,
    QQQ_NORMAL_PEAK_CONFIRM_DIST: 14,
    QQQ_RECOVERY_PEAK_DIRECT_DIST: 22,
    QQQ_RECOVERY_PEAK_CONFIRM_DIST: 18,
    QQQ_PEAK_RSI_THRESHOLD: 65,
    UPPER_EXIT_MAX_WAIT_DAYS: 5,
    HOLD_RESTORE_DROP:               0.10,
    HOLD_RESTORE_MIN_TRADING_DAYS:   10
  }
};

const HOLD_ANCHOR_PREFIX   = "HOLD_ANCHOR_";
const HOLD_WATCH_PREFIX    = "HOLD_WATCH_";
const UPPER_EXIT_ARM_PREFIX = "UPPER_EXIT_ARM_";
const NASDAQ_PEAK_EXIT_EXEMPT_STRATEGIES = ["A", "C", "E", "F", "G"];

function isNasdaqPeakExitExemptStrategy(strategyType) {
  return NASDAQ_PEAK_EXIT_EXEMPT_STRATEGIES.indexOf(String(strategyType || "A").toUpperCase()) !== -1;
}

function nasdaqPeakExitApplies(strategyType) {
  return !isNasdaqPeakExitExemptStrategy(strategyType);
}

function clearNasdaqPeakEligibleSlots(stockName, slots, props, sellDate, sellPrice) {
  if (typeof Utils === "undefined" || typeof Utils.clearSlot !== "function") return [];
  const closed = [];
  const dateStr = sellDate instanceof Date
    ? Utilities.formatDate(sellDate, "Asia/Seoul", "yyyy-MM-dd")
    : String(sellDate || "");
  (slots || []).forEach(slot => {
    if (isNasdaqPeakExitExemptStrategy(slot.strategy)) return;
    Utils.clearSlot(stockName, slot.id, props);
    if (dateStr) props.setProperty(`SLOT_SELL_${stockName}_${slot.strategy}`, `${dateStr}|${sellPrice}`);
    closed.push(slot);
  });
  return closed;
}

function clearAHoldRestoreProps(stockName) {
  const p = PropertiesService.getScriptProperties();
  p.deleteProperty(HOLD_ANCHOR_PREFIX + stockName);
  p.deleteProperty(HOLD_WATCH_PREFIX  + stockName);
  p.deleteProperty("A_HOLD_ANCHOR_" + stockName);
  p.deleteProperty("A_HOLD_WATCH_"  + stockName);
}

function getHoldRestoreState(stockName, currentPrice, now, allProperties) {
  const S     = CONSTANTS.STRATEGY;
  const props = PropertiesService.getScriptProperties();
  const entry = parseEntryInfo(
    allProperties[`ENTRY_${stockName}`] || props.getProperty(`ENTRY_${stockName}`)
  );
  const watchStr =
    allProperties[HOLD_WATCH_PREFIX + stockName] || props.getProperty(HOLD_WATCH_PREFIX + stockName) ||
    allProperties["A_HOLD_WATCH_" + stockName]   || props.getProperty("A_HOLD_WATCH_" + stockName);
  const watchDate = watchStr ? parseDateKST(watchStr) : null;
  const requiredPrice = entry.price > 0 ? entry.price * (1 - S.HOLD_RESTORE_DROP) : 0;
  const ddOk   = entry.price > 0 && currentPrice > 0 && currentPrice <= requiredPrice;
  const days   = watchDate ? calcTradingDays(watchDate, now) : 0;
  const daysOk = watchDate ? days >= S.HOLD_RESTORE_MIN_TRADING_DAYS : false;
  return {
    entryPrice: entry.price,
    requiredPrice,
    watchStr,
    watchDate,
    days,
    ddOk,
    daysOk,
    allowed: ddOk && daysOk,
    missingEntry: !(entry.price > 0),
    missingWatch: !watchDate
  };
}

/** 보유 중 관망→추가 매수 신호 허용 여부 (A-F 공통) */
function aHoldRestoreAllowed(stockName, strategyType, currentPrice, now, allProperties) {
  return getHoldRestoreState(stockName, currentPrice, now, allProperties).allowed;
}

function buildHoldRestorePendingReason(stockName, strategyType, currentPrice, now, allProperties) {
  const S     = CONSTANTS.STRATEGY;
  const state = getHoldRestoreState(stockName, currentPrice, now, allProperties);
  const label = strategyType || "-";
  if (state.missingEntry) {
    return `보유 유지 (${label}그룹 추가 매수 대기: 전 진입가 정보 없음)`;
  }
  if (state.missingWatch) {
    return `보유 유지 (${label}그룹 추가 매수 대기: 전 진입가 ${fmtPrice(state.entryPrice, stockName)} 대비 -${(S.HOLD_RESTORE_DROP * 100).toFixed(0)}% 및 관망 ${S.HOLD_RESTORE_MIN_TRADING_DAYS}거래일 경과 시 허용)`; 
  }
  return `보유 유지 (${label}그룹 추가 매수 대기: 전 진입가 ${fmtPrice(state.entryPrice, stockName)} 대비 -${(S.HOLD_RESTORE_DROP * 100).toFixed(0)}% 및 관망 ${S.HOLD_RESTORE_MIN_TRADING_DAYS}거래일 경과 시 허용)`;
}

function ensureHoldRestoreWatchState(stockName, currentPrice, now, allProperties, props) {
  const state = getHoldRestoreState(stockName, currentPrice, now, allProperties);
  if (!state.missingWatch) return state;
  const store = props || PropertiesService.getScriptProperties();
  store.setProperty(
    HOLD_WATCH_PREFIX + stockName,
    Utilities.formatDate(now, "Asia/Seoul", "yyyy-MM-dd'T'HH:mm:ss") + "+09:00"
  );
  if (currentPrice > 0) {
    store.setProperty(HOLD_ANCHOR_PREFIX + stockName, String(currentPrice));
  }
  return getHoldRestoreState(stockName, currentPrice, now, allProperties);
}

const NASDAQ_AB_LATCH_KEY = "NasdaqABFilterLatched";

/** QQQ 이격도(%) 기준 하락장 필터 활성 여부 (E/F그룹용 히스테리시스 포함) */
function computeNasdaqABFilterActive(ixicDist) {
  const S     = CONSTANTS.STRATEGY;
  const props = PropertiesService.getScriptProperties();
  const lower   = S.NASDAQ_DIST_LOWER;
  const upper   = S.NASDAQ_DIST_UPPER;
  const release = S.NASDAQ_DIST_RELEASE;
  const inDeath = ixicDist > lower && ixicDist < upper;
  const bottom  = ixicDist <= lower;
  const cleared = ixicDist >= release;

  let active;
  if (bottom) {
    active = false;
    props.deleteProperty(NASDAQ_AB_LATCH_KEY);
  } else if (inDeath) {
    active = true;
    props.setProperty(NASDAQ_AB_LATCH_KEY, "TRUE");
  } else if (cleared) {
    active = false;
    props.deleteProperty(NASDAQ_AB_LATCH_KEY);
  } else {
    active = props.getProperty(NASDAQ_AB_LATCH_KEY) === "TRUE";
  }
  return active;
}

function updateInvestmentOpinion() {
  const startTime = Date.now();
  const { targetSheet } = initializeSheets();
  if (!targetSheet) return;
  SpreadsheetApp.flush();
  console.log("[대기 생략] 상위 트리거 대기 이후 즉시 투자의견 계산 진행");
  const globalData    = loadGlobalData(targetSheet);
  const timeData      = getTimeData();
  const ixicFilterActive = computeNasdaqABFilterActive(globalData.ixicDist);
  const Sg = CONSTANTS.STRATEGY;

  // allProperties를 먼저 한 번에 로드하여 이후 모든 getProperty 호출을 대체
  const allProperties = PropertiesService.getScriptProperties().getProperties();

  const marketData = {
    ...globalData, ...timeData,
    nasdaqPeakAlert: globalData.nasdaqPeakAlert,
    ixicFilterActive
  };
  allProperties.__IS_RECOVERY_MARKET__ = marketData.isRecoveryMarket ? "TRUE" : "";
  const buyBlockMax = marketData.nasdaqBuyBlockMax || Sg.NASDAQ_BUY_BLOCK_MAX;
  const buyBlockActive = Number.isFinite(marketData.ixicDist) && marketData.ixicDist > buyBlockMax;
  console.log(
    `[글로벌] 이벤트: "${marketData.event}", VIX: ${marketData.vixD}, QQQ 이격도(현재): ${marketData.ixicDist.toFixed(2)}%, ` +
    `하락장 필터(A/C/D/E/F/G 차단, 데스존 ${Sg.NASDAQ_DIST_LOWER}%~${Sg.NASDAQ_DIST_UPPER}%): ${ixicFilterActive ? "활성" : "비활성"}, ` +
    `상단 매수 차단(신규/재진입만, >${buyBlockMax}%): ${buyBlockActive ? "활성" : "비활성"}, ` +
    `고점 청산/강제매도(${marketData.nasdaqPeakReason || "국면별 기준"}): ${marketData.nasdaqPeakAlert ? "활성" : "비활성"}`
  );
  const stockData     = loadStockData(targetSheet);
  console.log(`[로드] 종목 데이터 로드 완료: ${stockData.length}행`);
  const changedStocks = processStocks(stockData, marketData, targetSheet, allProperties, startTime);
  console.log(`[완료] 전체 실행 시간: ${((Date.now() - startTime) / 1000).toFixed(1)}초`);
  logResults(changedStocks);
}

function initializeSheets() {
  const spreadsheet   = SpreadsheetApp.getActiveSpreadsheet();
  const sheet         = spreadsheet.getSheetByName("기술분석");
  const spreadsheetId = sheet.getRange("I1").getValue();
  console.log(`[초기화] 대상 스프레드시트 ID: ${spreadsheetId}`);
  try {
    const targetSpreadsheet = SpreadsheetApp.openById(spreadsheetId);
    const targetSheet       = targetSpreadsheet.getSheetByName("기술분석");
    console.log(`[초기화] 스프레드시트 접근 성공`);
    return { targetSheet, spreadsheetId };
  } catch (e) {
    console.log(`FATAL ERROR: 스프레드시트 접근 실패 (${spreadsheetId}). 오류: ${e.toString()}`);
    return { targetSheet: null, spreadsheetId };
  }
}

function loadGlobalData(targetSheet) {
  const event     = String(targetSheet.getRange("M1").getValue()).trim() || "당분간 없음";
  const vixD      = Number(targetSheet.getRange("O1").getValue()) || 0;
  const ixicPrice = Number(targetSheet.getRange("W1").getValue()) || 0;
  const ixicMa200 = Number(targetSheet.getRange("AE1").getValue()) || 0;
  const ixicDist  = (ixicPrice > 0 && ixicMa200 > 0) ? (ixicPrice / ixicMa200 - 1) * 100 : 100;
  const peakState = typeof getNasdaqPeakSignalState_ === "function"
    ? getNasdaqPeakSignalState_(targetSheet, PropertiesService.getScriptProperties().getProperties())
    : { nasdaqPeakAlert: false };
  console.log(`[글로벌 로드] 이벤트: "${event}", VIX: ${vixD}, QQQ: ${ixicPrice}, QQQ MA200: ${ixicMa200}, QQQ 이격도(현재): ${ixicDist.toFixed(2)}%`);
  return {
    event,
    vixD,
    ixicDist,
    nasdaqPeakAlert: peakState.nasdaqPeakAlert,
    isRecoveryMarket: !!peakState.isRecoveryMarket,
    qqqRegimeLabel: peakState.regimeLabel || "",
    nasdaqBuyBlockMax: peakState.buyBlockMax || (typeof getNasdaqBuyBlockMax_ === "function" ? getNasdaqBuyBlockMax_(ixicDist, PropertiesService.getScriptProperties().getProperties()) : CONSTANTS.STRATEGY.NASDAQ_BUY_BLOCK_MAX),
    nasdaqPeakReason: peakState.peakReason || "국면별 QQQ 과열 기준"
  };
}

function loadStockData(targetSheet) {
  const lastRow = targetSheet.getLastRow();
  console.log(`[로드] 마지막 행: ${lastRow}, 범위: A3:BC${lastRow}`);
  return targetSheet.getRange("A3:BC" + lastRow).getValues();
}

function getTimeData() {
  const now = new Date();
  return {
    now,
    kstHour:   Number(Utilities.formatDate(now, "Asia/Seoul", "HH")),
    kstMinute: Number(Utilities.formatDate(now, "Asia/Seoul", "mm"))
  };
}

function isDaylightSaving(now) {
  const year = now.getFullYear();
  const marchSecondSunday   = new Date(year, 2, 14 - new Date(year, 2, 1).getDay());
  const novemberFirstSunday = new Date(year, 10, 7 - new Date(year, 10, 1).getDay());
  return now.getTime() >= marchSecondSunday.getTime() && now.getTime() < novemberFirstSunday.getTime();
}

function isKoreanStock(stockName) {
  return /^\d{6}$/.test(String(stockName || "").trim());
}

function fetchUSExtendedCurrentPrice_(symbol) {
  try {
    const url = "https://query1.finance.yahoo.com/v8/finance/chart/" +
      encodeURIComponent(symbol) + "?range=1d&interval=1m&includePrePost=true";
    const response = UrlFetchApp.fetch(url, {
      muteHttpExceptions: true,
      headers: {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Cache-Control": "no-cache"
      }
    });
    if (response.getResponseCode() !== 200) return null;

    const data = JSON.parse(response.getContentText());
    const result = data && data.chart && data.chart.result && data.chart.result[0];
    if (!result) return null;

    const quote = result.indicators && result.indicators.quote && result.indicators.quote[0];
    const closes = quote && quote.close ? quote.close : [];
    for (let i = closes.length - 1; i >= 0; i--) {
      const price = Number(closes[i]);
      if (Number.isFinite(price) && price > 0) return price;
    }

    const meta = result.meta || {};
    for (const key of ["postMarketPrice", "preMarketPrice", "regularMarketPrice"]) {
      const price = Number(meta[key]);
      if (Number.isFinite(price) && price > 0) return price;
    }
  } catch (e) {
    console.log(`[미국 확장 현재가 실패] ${symbol}: ${e}`);
  }
  return null;
}

function getUSExtendedSellPrice_(stockName, displayName, fallbackPrice, isKR, isHolding, context) {
  if (isKR || !isHolding) return null;
  const symbol = String(stockName || "").trim().toUpperCase();
  if (!symbol) return null;

  const cache = context.usExtendedPriceCache || (context.usExtendedPriceCache = {});
  if (!Object.prototype.hasOwnProperty.call(cache, symbol)) {
    cache[symbol] = fetchUSExtendedCurrentPrice_(symbol);
  }

  const price = Number(cache[symbol]);
  if (!Number.isFinite(price) || price <= 0) return null;
  const base = Number(fallbackPrice) || 0;
  if (base > 0 && Math.abs(price - base) >= 0.01) {
    console.log(`[미국 확장 현재가] ${displayName}: 정규장 기준 ${fmtPrice(base, stockName)} → 매도판단 ${fmtPrice(price, stockName)}`);
  }
  return price;
}

/** A~F 전략 코드 → 시트 표시용 전체 이름 */
function strategyDisplayName(type) {
  const map = {
    "A": "A. 200일선 상방 & 모멘텀 재가속",
    "B": "B. 200일선 하방 & 공황 저점",
    "C": "C. 200일선 상방 & 스퀴즈 거래량 돌파",
    "D": "D. 200일선 상방 & 상승 흐름 강화",
    "E": "E. 200일선 상방 & 스퀴즈 저점",
    "F": "F. 200일선 상방 & BB 극단 저점",
    "G": "G. 급락 후 회복장 20일선 눌림"
  };
  return map[type] || type;
}

/** 시트 BC열 값(전체 이름 또는 단일 문자) → A~G 코드 추출 */
function parseStrategyCode(cellValue) {
  if (!cellValue) return null;
  const s = String(cellValue).trim();
  if (/^[A-G]$/.test(s)) return s;                  // 단일 문자 (레거시)
  if (/^[A-G]\.\s/.test(s)) return s.charAt(0);     // "E. 200일선 ..." 형식
  return null;
}

function fetchGMa20PullbackState_(symbol) {
  const cache = CacheService.getScriptCache();
  const cacheKey = "G_MA20_PULLBACK_" + String(symbol || "").trim().toUpperCase();
  const cached = cache.get(cacheKey);
  if (cached) {
    try {
      const parsed = JSON.parse(cached);
      if (isCompleteGMa20PullbackState_(parsed)) return parsed;
    } catch (e) {}
  }

  const resolved = resolveToTickerForRSI(symbol);
  let rows = [];
  if (resolved.type === "US") {
    const url = "https://query1.finance.yahoo.com/v8/finance/chart/" + encodeURIComponent(resolved.code) + "?range=1y&interval=1d";
    const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: { "User-Agent": "Mozilla/5.0", "Accept": "application/json" } });
    if (response.getResponseCode() !== 200) return null;
    const data = JSON.parse(response.getContentText());
    const result = ((((data || {}).chart || {}).result || [])[0] || {});
    const quote = ((result.indicators || {}).quote || [])[0] || {};
    const closes = quote.close || [];
    const lows = quote.low || [];
    const volumes = quote.volume || [];
    for (let i = 0; i < closes.length; i++) {
      const close = Number(closes[i]);
      const low = Number(lows[i]);
      if (!Number.isFinite(close) || !Number.isFinite(low)) continue;
      rows.push({ close, low, volume: Number(volumes[i]) || 0 });
    }
  } else if (resolved.type === "KR") {
    const url = "https://fchart.stock.naver.com/sise.nhn?symbol=" + resolved.code + "&timeframe=day&count=260&requestType=0";
    const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: { "User-Agent": "Mozilla/5.0" } });
    if (response.getResponseCode() !== 200) return null;
    const xml = response.getContentText("EUC-KR");
    const itemRegex = /item data="([^"]+)"/g;
    let match;
    while ((match = itemRegex.exec(xml)) !== null) {
      const parts = match[1].split("|");
      const low = Number(parts[3]);
      const close = Number(parts[4]);
      if (!Number.isFinite(close) || !Number.isFinite(low)) continue;
      rows.push({ close, low, volume: Number(parts[5]) || 0 });
    }
  }

  if (rows.length < 25) return null;
  const avg = (slice) => slice.reduce((sum, value) => sum + value, 0) / slice.length;
  const closes = rows.map(row => row.close);
  const volumes = rows.map(row => row.volume).filter(value => Number.isFinite(value) && value > 0);
  const latest = rows[rows.length - 1];
  const prev = rows[rows.length - 2];
  const ma20 = avg(closes.slice(-20));
  const ma20D1 = avg(closes.slice(-21, -1));
  const ma20Prev5 = avg(closes.slice(-25, -5));
  const vol20 = volumes.slice(-20);
  const avgVol20 = vol20.length ? avg(vol20) : 0;
  const state = {
    close: latest.close,
    low: latest.low,
    closeD1: prev.close,
    ma20,
    ma20D1,
    ma20Prev5,
    ma20Slope5: ma20Prev5 > 0 ? (ma20 / ma20Prev5 - 1) : null,
    volRatio20: avgVol20 > 0 && latest.volume > 0 ? latest.volume / avgVol20 : null
  };
  cache.put(cacheKey, JSON.stringify(state), 900);
  return state;
}

function isFiniteGNumber_(value) {
  return Number.isFinite(Number(value));
}

function isCompleteGMa20PullbackState_(state) {
  return !!state
    && isFiniteGNumber_(state.close)
    && isFiniteGNumber_(state.low)
    && isFiniteGNumber_(state.closeD1)
    && isFiniteGNumber_(state.ma20)
    && isFiniteGNumber_(state.ma20D1)
    && isFiniteGNumber_(state.ma20Prev5)
    && isFiniteGNumber_(state.ma20Slope5)
    && isFiniteGNumber_(state.volRatio20);
}

function formatGMa20Slope_(gState) {
  const slope = gState ? Number(gState.ma20Slope5) : NaN;
  return Number.isFinite(slope) ? (slope * 100).toFixed(2) + "%" : "데이터 없음";
}

function formatGVolRatio20_(gState) {
  const ratio = gState ? Number(gState.volRatio20) : NaN;
  return Number.isFinite(ratio) ? ratio.toFixed(2) : "데이터 없음";
}

function checkMarketOpen(now, isKR = false) {
  const kstHour      = Number(Utilities.formatDate(now, "Asia/Seoul", "HH"));
  const kstMinute    = Number(Utilities.formatDate(now, "Asia/Seoul", "mm"));
  const kstDayOfWeek = Number(Utilities.formatDate(now, "Asia/Seoul", "u")) % 7;
  if (isKR) {
    if (kstDayOfWeek === 0 || kstDayOfWeek === 6) return false;
    return (kstHour > 9 || (kstHour === 9 && kstMinute >= 0)) && (kstHour < 15 || (kstHour === 15 && kstMinute <= 30));
  } else {
    // 미국장은 뉴욕 현지 요일/시간으로 판정해야 KST 자정 이후(뉴욕 전일 장중)를 오판하지 않는다.
    const nyHour      = Number(Utilities.formatDate(now, "America/New_York", "HH"));
    const nyMinute    = Number(Utilities.formatDate(now, "America/New_York", "mm"));
    const nyDayOfWeek = Number(Utilities.formatDate(now, "America/New_York", "u")) % 7;
    if (nyDayOfWeek === 0 || nyDayOfWeek === 6) return false;
    return (nyHour > 9 || (nyHour === 9 && nyMinute >= 30)) && (nyHour < 16);
  }
}

function extractIndicators(row) {
  const C         = CONSTANTS.COL_INDICES;
  const stockName = String(row[C.stockName]).trim();
  const stockLabel = row.length > 1 ? String(row[C.stockLabel] || "").trim() : "";
  const displayName = isKoreanStock(stockName) && stockLabel ? `${stockLabel}(${stockName})` : stockName;

  if (row.length < 54) {
    console.log(`[RAW 경고] ${displayName} — 행 길이 부족: ${row.length}열`);
    return {
      stockName, displayName, stockLabel,
      currentPrice: null, opinion: "", rsi: null, cci: null,
      macdHist: null, macdHistD1: null, macdHistD2: null,
      candleLow: null, pctBLow: null, pctB: null,
      ma20: null,
      bbWidth: null, bbWidthD1: null, bbWidthAvg60: null,
      ma200: null, lrTrendline: null,
      volRatio: null, plusDI: null, minusDI: null, adx: null, adxD1: null,
      entryPrice: 0, entryDate: null
    };
  }

  const toNum = (val) => {
    if (val === null || val === undefined || val === "" || val instanceof Date || typeof val === "object") return null;
    const s = String(val).trim();
    if (s.indexOf("#") === 0 || s.toLowerCase() === "loading..." || s === "데이터 부족") return null;
    const n = Number(val);
    return isNaN(n) ? null : n;
  };

  const rawEntryDate = row[C.entryDate];
  let entryDate = null;
  if (rawEntryDate instanceof Date && !isNaN(rawEntryDate.getTime())) {
    entryDate = rawEntryDate;
  } else if (typeof rawEntryDate === "string" && rawEntryDate.trim() !== "") {
    const parsed = new Date(rawEntryDate);
    if (!isNaN(parsed.getTime())) entryDate = parsed;
  }

  // 컬럼 인덱스가 -1이면 row[-1] = undefined → toNum = null (조건 비활성)
  const result = {
    stockName, stockLabel, displayName,
    currentPrice:  toNum(row[C.currentPrice]),
    opinion:       String(row[C.opinion]).trim(),
    rsi:           toNum(row[C.rsi]),
    cci:           toNum(row[C.cci]),
    macdHist:      toNum(row[C.macdHist]),
    macdHistD1:    toNum(row[C.macdHistD1]),
    macdHistD2:    toNum(row[C.macdHistD2]),
    candleLow:     toNum(row[C.candleLow]),
    pctB:          toNum(row[C.pctB]),
    pctBLow:       toNum(row[C.pctBLow]),
    ma20:          C.ma20 >= 0 ? toNum(row[C.ma20]) : null,
    bbWidth:       toNum(row[C.bbWidth]),
    bbWidthD1:     toNum(row[C.bbWidthD1]),
    bbWidthAvg60:  toNum(row[C.bbWidthAvg60]),
    ma200:         toNum(row[C.ma200]),
    lrTrendline:   toNum(row[C.lrTrendline]),
    volRatio:      C.volRatio  >= 0 ? toNum(row[C.volRatio])  : null,
    plusDI:        C.plusDI    >= 0 ? toNum(row[C.plusDI])    : null,
    minusDI:       C.minusDI   >= 0 ? toNum(row[C.minusDI])   : null,
    adx:           C.adx       >= 0 ? toNum(row[C.adx])       : null,
    adxD1:         C.adxD1     >= 0 ? toNum(row[C.adxD1])     : null,
    entryPrice:    toNum(row[C.entryPrice]) || 0,
    entryDate
  };

  return result;
}

function calcTradingDays(fromDate, toDate) {
  if (!fromDate || !toDate) return 0;
  let count = 0;
  const cursor = new Date(fromDate);
  cursor.setHours(0, 0, 0, 0);
  const end = new Date(toDate);
  end.setHours(0, 0, 0, 0);
  while (cursor < end) {
    cursor.setDate(cursor.getDate() + 1);
    const dow = cursor.getDay();
    if (dow !== 0 && dow !== 6) count++;
  }
  return count;
}

function parseDateKST(str) {
  if (!str) return null;
  if (/[+-]\d{2}:\d{2}$/.test(str) || str.endsWith("Z")) return new Date(str);
  if (/^\d{4}-\d{2}-\d{2}$/.test(str)) return new Date(str + "T00:00:00+09:00");
  if (/^\d{4}\.\s*\d{2}\.\s*\d{2}$/.test(str)) {
    const normalized = str.replace(/\s/g, "").replace(/\./g, "-");
    return new Date(normalized + "T00:00:00+09:00");
  }
  if (/^\d{4}\.\s*\d{2}\.\s*\d{2},\s*\d{2}:\d{2}:\d{2}$/.test(str)) {
    const m = str.match(/^(\d{4})\.\s*(\d{2})\.\s*(\d{2}),\s*(\d{2}):(\d{2}):(\d{2})$/);
    if (m) return new Date(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}+09:00`);
  }
  return new Date(str + "+09:00");
}

function saveUpperExitArm(stockName, date) {
  const value = Utilities.formatDate(date, "Asia/Seoul", "yyyy-MM-dd'T'HH:mm:ss") + "+09:00";
  PropertiesService.getScriptProperties().setProperty(UPPER_EXIT_ARM_PREFIX + stockName, value);
}

function loadUpperExitArm(stockName, allProperties) {
  const props = PropertiesService.getScriptProperties();
  const value = (allProperties && allProperties[UPPER_EXIT_ARM_PREFIX + stockName]) || props.getProperty(UPPER_EXIT_ARM_PREFIX + stockName);
  return value ? parseDateKST(value) : null;
}

function clearUpperExitArm(stockName) {
  PropertiesService.getScriptProperties().deleteProperty(UPPER_EXIT_ARM_PREFIX + stockName);
}

function saveEntryInfo(stockName, price, date, strategyType = "A", options = {}) {
  const preserveRestoreState = !!options.preserveRestoreState;
  if (!preserveRestoreState) clearAHoldRestoreProps(stockName);
  clearUpperExitArm(stockName);
  const val = `${price}|${Utilities.formatDate(date, "Asia/Seoul", "yyyy-MM-dd'T'HH:mm:ss")}+09:00|${strategyType}`;
  PropertiesService.getScriptProperties().setProperty(`ENTRY_${stockName}`, val);
}

function parseEntryInfo(val) {
  if (!val) return { price: 0, date: null, strategyType: "A" };
  const parts = val.split("|");
  const rawType = parts[2] || "A";
  // 레거시 문자열 키만 재매핑, A-G letter는 현재 체계를 그대로 사용
  const legacyMap = {
    "squeeze": "E", "ma200u": "F", "ma200d": "B"
  };
  const strategyType = /^[A-G]$/.test(rawType)
    ? rawType
    : (legacyMap[rawType] !== undefined ? legacyMap[rawType] : rawType);
  return { price: Number(parts[0]) || 0, date: parts[1] ? parseDateKST(parts[1]) : null, strategyType };
}

function clearEntryInfo(stockName) {
  clearAHoldRestoreProps(stockName);
  clearUpperExitArm(stockName);
  PropertiesService.getScriptProperties().deleteProperty(`ENTRY_${stockName}`);
}

function saveSellInfo(stockName, date, price) {
  const dateStr = Utilities.formatDate(date, "Asia/Seoul", "yyyy-MM-dd'T'HH:mm:ss") + "+09:00";
  PropertiesService.getScriptProperties().setProperty(`SELL_${stockName}`, price ? `${dateStr}|${price}` : dateStr);
}

function parseSellInfo(val) {
  if (!val) return { date: null, price: 0 };
  const parts = val.split("|");
  return { date: parts[0] ? parseDateKST(parts[0]) : null, price: parts[1] ? Number(parts[1]) : 0 };
}

function getActiveSlotsFromProperties(stockName, allProperties) {
  if (typeof Utils === "undefined" || typeof Utils.loadSlots !== "function") return [];
  return Utils.loadSlots(stockName, allProperties)
    .sort((a, b) => {
      const aTime = a.date ? a.date.getTime() : 0;
      const bTime = b.date ? b.date.getTime() : 0;
      return aTime - bTime; // oldest first → ENTRY_ 표시 기준
    });
}

function pickLatestSlot(slots, predicate) {
  const candidates = predicate ? (slots || []).filter(predicate) : (slots || []);
  return candidates.length > 0 ? candidates[0] : null;
}

function clearSellInfo(stockName) {
  PropertiesService.getScriptProperties().deleteProperty(`SELL_${stockName}`);
}

function saveExitReason(stockName, reason) {
  if (!reason) return;
  PropertiesService.getScriptProperties().setProperty(`EXIT_REASON_${stockName}`, reason);
}

function loadExitReason(stockName) {
  return PropertiesService.getScriptProperties().getProperty(`EXIT_REASON_${stockName}`) || null;
}

function clearExitReason(stockName) {
  PropertiesService.getScriptProperties().deleteProperty(`EXIT_REASON_${stockName}`);
}

/**
 * 매수 조건 평가 — 우선순위: A > B > C > D > E > F > G
 *
 * A: MA200 위 + MACD 골든크로스 + %B>80 + RSI>70          (강세장 전용, 나스닥 ≥ -3%)
 * B: MA200 아래 + VIX≥25 + 과매도 + 추세선 터치            (나스닥 필터 미적용)
 * C: MA200 위 + BB스퀴즈 돌파 + 거래량 폭발 + %B>55        (강세장 전용, 나스닥 ≥ -3%)
 * D: MA200 위 + ADX>30 + +DI>-DI + ADX상승 + MACD>0 + %B 30~75 (강세장 전용, 나스닥 ≥ -3%)
 * E: MA200 위 + BB스퀴즈 + 저가%B≤50                       (히스테리시스 + 찐바닥 허용)
 * F: MA200 위 + 저가%B≤5                                   (히스테리시스 + 찐바닥 허용)
 * G: 회복장 + QQQ 8~18% + MA20 눌림 후 회복                 (고점 청산 적용)
 */
function evaluateBuyCondition(ind, vixD, ixicDist, ixicFilterActive, isHolding = false, holdingStrategyType = null, allProperties = null, nasdaqBuyBlockMax = null) {
  const S            = CONSTANTS.STRATEGY;
  const vixThreshold = isHolding ? S.VIX_RELEASE : S.VIX_MIN;
  const buyBlockMax = Number.isFinite(Number(nasdaqBuyBlockMax))
    ? Number(nasdaqBuyBlockMax)
    : (typeof getNasdaqBuyBlockMax_ === "function" ? getNasdaqBuyBlockMax_(ixicDist, allProperties) : S.NASDAQ_BUY_BLOCK_MAX);
  const nasdaqBelowBuyBlock = Number.isFinite(ixicDist) && ixicDist <= buyBlockMax;

  const nasdaqAllowsStrictMomentum = nasdaqBelowBuyBlock && !ixicFilterActive && ixicDist >= S.NASDAQ_DIST_UPPER;
  const nasdaqAllowsBottomBuy = nasdaqBelowBuyBlock && !ixicFilterActive;
  const isRecoveryMarket = !!(allProperties && allProperties.__IS_RECOVERY_MARKET__) || false;
  const nasdaqAllowsGRecovery = isRecoveryMarket
    && nasdaqBelowBuyBlock
    && !ixicFilterActive
    && Number.isFinite(ixicDist)
    && ixicDist >= S.G_QQQ_DIST_MIN
    && ixicDist <= S.G_QQQ_DIST_MAX;

  const aCond1 = ind.currentPrice > ind.ma200;
  const aCond2 = ind.macdHistD1 !== null && ind.macdHistD1 <= 0
              && ind.macdHist   !== null && ind.macdHist   >  0;
  const aCond3 = ind.pctB !== null && ind.pctB > S.GOLDEN_CROSS_PCTB_MIN;
  const aCond4 = ind.rsi  !== null && ind.rsi  > S.GOLDEN_CROSS_RSI_MIN;
  const entryGroupA = aCond1 && aCond2 && aCond3 && aCond4 && nasdaqAllowsStrictMomentum;

  const hasRsi = ind.rsi !== null;
  const hasCci = ind.cci !== null;
  const rsiOk  = hasRsi && ind.rsi < S.RSI_MAX;
  const cciOk  = hasCci && ind.cci < S.CCI_MIN;
  const bCond3       = rsiOk || cciOk;
  const bCond3Hold   = (hasRsi || hasCci) && bCond3;
  const bCond3Released = (hasRsi || hasCci) && !rsiOk && !cciOk;

  const bCond1 = ind.currentPrice < ind.ma200;
  const bCond2 = vixD >= vixThreshold;
  const lrSlope = getLRSlope(ind.stockName, allProperties);
  const bCond4 = lrSlope > 0;
  const bCond5 = ind.lrTrendline !== null && ind.lrTrendline > 0
              && ind.candleLow  !== null && ind.candleLow <= ind.lrTrendline * S.LR_TOUCH_RATIO;
  const entryGroupB = bCond1 && bCond2 && bCond3 && bCond4 && bCond5 && nasdaqBelowBuyBlock;

  const bbPairOk = ind.bbWidth !== null && ind.bbWidthAvg60 !== null && ind.bbWidthAvg60 > 0;
  const cCond1 = ind.currentPrice > ind.ma200;
  const cCond2 = bbPairOk && ind.bbWidthD1 !== null
              && (ind.bbWidthD1 / ind.bbWidthAvg60) < S.C_SQUEEZE_RATIO;
  const cCond3 = bbPairOk && ind.bbWidthD1 !== null
              && ind.bbWidth > ind.bbWidthD1 * S.BB_EXPAND_RATIO;
  const cCond4 = ind.volRatio !== null && ind.volRatio >= S.SQUEEZE_BREAKOUT_VOL_RATIO;
  const cCond5 = ind.pctB !== null && ind.pctB > S.SQUEEZE_BREAKOUT_PCTB_MIN;
  const cCond6 = ind.macdHist !== null && ind.macdHist > 0;
  const entryGroupC = !entryGroupA && !entryGroupB
                   && cCond1 && cCond2 && cCond3 && cCond4 && cCond5 && cCond6
                   && nasdaqAllowsStrictMomentum;

  const dCond1 = ind.currentPrice > ind.ma200;
  const dCond2 = ind.plusDI !== null && ind.minusDI !== null && ind.plusDI > ind.minusDI;
  const dCond3 = ind.adx !== null && ind.adx > S.ADX_MIN;
  const dCond4 = ind.adx !== null && ind.adxD1 !== null && ind.adx > ind.adxD1;
  const dCond5 = ind.macdHist !== null && ind.macdHist > 0;
  const dCond6 = ind.pctB !== null && ind.pctB >= S.ADX_PCTB_MIN && ind.pctB <= S.ADX_PCTB_MAX;
  const entryGroupD = !entryGroupA && !entryGroupB && !entryGroupC
                   && dCond1 && dCond2 && dCond3 && dCond4 && dCond5 && dCond6
                   && nasdaqAllowsStrictMomentum;

  const eCond1 = ind.currentPrice > ind.ma200;
  const eCond2 = bbPairOk && (ind.bbWidth / ind.bbWidthAvg60) < S.SQUEEZE_RATIO;
  const eCond3 = ind.pctBLow !== null && ind.pctBLow <= S.SQUEEZE_PCT_B_MAX;
  const entryGroupE = !entryGroupA && !entryGroupB && !entryGroupC && !entryGroupD
                   && eCond1 && eCond2 && eCond3 && nasdaqAllowsBottomBuy;

  const fCond1 = ind.currentPrice > ind.ma200;
  const fCond2 = ind.pctBLow !== null && ind.pctBLow <= S.BB_PCT_B_LOW_MAX;
  const entryGroupF = !entryGroupA && !entryGroupB && !entryGroupC && !entryGroupD && !entryGroupE
                   && fCond1 && fCond2 && nasdaqAllowsBottomBuy;

  const gState = nasdaqAllowsGRecovery && ind.currentPrice > ind.ma200
    ? fetchGMa20PullbackState_(ind.stockName)
    : null;
  const gMa20 = gState && Number.isFinite(Number(gState.ma20)) ? Number(gState.ma20) : ind.ma20;
  const gClose = gState && Number.isFinite(Number(gState.close)) ? Number(gState.close) : ind.currentPrice;
  const gLow = gState && Number.isFinite(Number(gState.low)) ? Number(gState.low) : ind.candleLow;
  const gCond1 = nasdaqAllowsGRecovery;
  const gCond2 = ind.currentPrice > ind.ma200;
  const gCond3 = gMa20 !== null && ind.ma200 !== null && gMa20 > ind.ma200;
  const gCond4 = gLow !== null && gMa20 !== null && gLow <= gMa20;
  const gCond5 = gClose !== null && gMa20 !== null && gClose > gMa20;
  const gCond6 = !!(gState && Number.isFinite(Number(gState.closeD1)) && Number.isFinite(Number(gState.ma20D1)) && Number(gState.closeD1) > Number(gState.ma20D1));
  const gCond7 = !!(gState && Number.isFinite(Number(gState.ma20Slope5)) && Number(gState.ma20Slope5) >= S.G_MA20_SLOPE5_MIN);
  const gCond8 = ind.rsi !== null && ind.rsi >= S.G_RSI_MIN && ind.rsi <= S.G_RSI_MAX;
  const gCond9 = !!(gState && Number.isFinite(Number(gState.volRatio20)) && Number(gState.volRatio20) <= S.G_VOL_RATIO20_MAX);
  const gCond10 = ind.currentPrice !== null && ind.ma200 !== null && ind.ma200 > 0 && (ind.currentPrice / ind.ma200 - 1) <= S.G_MA200_OVERHEAT_MAX;
  const entryGroupG = !entryGroupA && !entryGroupB && !entryGroupC && !entryGroupD && !entryGroupE && !entryGroupF
                   && gCond1 && gCond2 && gCond3 && gCond4 && gCond5 && gCond6 && gCond7 && gCond8 && gCond9 && gCond10;

  const entryTriggered = entryGroupA || entryGroupB || entryGroupC || entryGroupD || entryGroupE || entryGroupF || entryGroupG;

  let triggered = entryTriggered;
  if (isHolding && holdingStrategyType) {
    if (holdingStrategyType === "A") {
      const macdOk = ind.macdHist !== null && ind.macdHist > 0;
      triggered = aCond1 && !ixicFilterActive && nasdaqBelowBuyBlock && ixicDist >= S.NASDAQ_DIST_UPPER && macdOk;
    } else if (holdingStrategyType === "B") {
      triggered = bCond1 && bCond2 && bCond3Hold && bCond4 && nasdaqBelowBuyBlock;
    } else if (holdingStrategyType === "C") {
      const macdOkC = ind.macdHist !== null && ind.macdHist > 0;
      triggered = cCond1 && !ixicFilterActive && nasdaqBelowBuyBlock && ixicDist >= S.NASDAQ_DIST_UPPER && macdOkC;
    } else if (holdingStrategyType === "D") {
      const diOk   = ind.plusDI !== null && ind.minusDI !== null && ind.plusDI > ind.minusDI;
      const macdOkD = ind.macdHist !== null && ind.macdHist > 0;
      triggered = dCond1 && !ixicFilterActive && nasdaqBelowBuyBlock && ixicDist >= S.NASDAQ_DIST_UPPER && diOk && macdOkD;
    } else if (holdingStrategyType === "E") {
      triggered = eCond1 && !ixicFilterActive && nasdaqBelowBuyBlock
               && bbPairOk && ind.pctBLow !== null && eCond2 && eCond3;
    } else if (holdingStrategyType === "F") {
      triggered = fCond1 && !ixicFilterActive && nasdaqBelowBuyBlock
               && ind.pctBLow !== null && fCond2;
    } else if (holdingStrategyType === "G") {
      triggered = gCond1 && gCond2 && gCond3 && gCond5 && gCond6 && gCond7 && gCond8 && gCond9 && gCond10;
    }
  }

  const strategyType = entryGroupA ? "A" : entryGroupB ? "B" : entryGroupC ? "C"
                     : entryGroupD ? "D" : entryGroupE ? "E" : entryGroupF ? "F" : entryGroupG ? "G" : null;

  return {
    triggered, strategyType,
    aCond1, aCond2, aCond3, aCond4,
    bCond1, bCond2, bCond3, bCond3Hold, bCond3Released, bCond4, bCond5,
    hasRsi, hasCci, rsiOk, cciOk, vixThreshold, lrSlope,
    cCond1, cCond2, cCond3, cCond4, cCond5, cCond6, bbPairOk,
    dCond1, dCond2, dCond3, dCond4, dCond5, dCond6,
    eCond1, eCond2, eCond3,
    fCond1, fCond2,
    gCond1, gCond2, gCond3, gCond4, gCond5, gCond6, gCond7, gCond8, gCond9, gCond10,
    gState, gMa20, gClose, gLow, nasdaqAllowsGRecovery,
    nasdaqAllowsStrictMomentum, nasdaqAllowsBottomBuy, nasdaqBelowBuyBlock, ixicDist, ixicFilterActive,
    entryTriggered,
    cond2: bCond2, cond3: bCond3, cond3Hold: bCond3Hold,
    cond3Released: bCond3Released, cond4: bCond4, cond5: bCond5
  };
}

function evaluateExitCondition(ind, now, nasdaqPeakAlert, strategyType = "A", allProperties = null) {
  const S = CONSTANTS.STRATEGY;
  if (!ind.entryPrice || ind.entryPrice <= 0 || !ind.entryDate) return { shouldExit: false, reason: null };
  if (nasdaqPeakAlert && nasdaqPeakExitApplies(strategyType)) return { shouldExit: true, reason: "나스닥 고점 청산/강제매도 — 국면별 QQQ 과열 기준 충족" };

  const targetPct = strategyType === "A" ? S.TARGET_PCT_A
                  : strategyType === "B" ? S.TARGET_PCT_B
                  : strategyType === "C" ? S.TARGET_PCT_C
                  : strategyType === "D" ? S.TARGET_PCT_D
                  : strategyType === "E" ? S.TARGET_PCT_E
                  : strategyType === "F" ? S.TARGET_PCT_F
                  : S.TARGET_PCT_G;
  const circuitPct = strategyType === "A" ? S.CIRCUIT_PCT_A
                   : strategyType === "B" ? S.CIRCUIT_PCT_B
                   : strategyType === "C" ? S.CIRCUIT_PCT_C
                   : strategyType === "D" ? S.CIRCUIT_PCT_D
                   : strategyType === "E" ? S.CIRCUIT_PCT_E
                   : strategyType === "F" ? S.CIRCUIT_PCT_F
                   : S.CIRCUIT_PCT_G;
  const stratLabel = strategyType === "A" ? `200일선 상방 & 모멘텀 재가속 기준 +${targetPct * 100}%`
                   : strategyType === "B" ? `200일선 하방 & 공황 저점 기준 +${targetPct * 100}%`
                   : strategyType === "C" ? `200일선 상방 & 스퀴즈 거래량 돌파 기준 +${targetPct * 100}%`
                   : strategyType === "D" ? `200일선 상방 & 상승 흐름 강화 기준 +${targetPct * 100}%`
                   : strategyType === "E" ? `200일선 상방 & 스퀴즈 저점 기준 +${targetPct * 100}%`
                   : strategyType === "F" ? `200일선 상방 & BB 극단 저점 기준 +${targetPct * 100}%`
                   :                        `급락 후 회복장 20일선 눌림 기준 +${targetPct * 100}%`;
  const maxHoldDays = strategyType === "D" ? S.MAX_HOLD_DAYS_D : strategyType === "G" ? S.MAX_HOLD_DAYS_G : S.MAX_HOLD_DAYS;

  const returnPct   = (ind.currentPrice - ind.entryPrice) / ind.entryPrice;
  const tradingDays = calcTradingDays(ind.entryDate, now);

  const isEfStrategy = strategyType === "E" || strategyType === "F";
  let upperExitArmDate = isEfStrategy ? loadUpperExitArm(ind.stockName, allProperties) : null;

  if (isEfStrategy && returnPct >= targetPct && !upperExitArmDate) {
    saveUpperExitArm(ind.stockName, now);
    upperExitArmDate = now;
  }

  if (isEfStrategy && upperExitArmDate) {
    const histTurnSignal =
      ind.macdHist !== null && ind.macdHistD1 !== null && ind.macdHistD2 !== null &&
      (ind.macdHist - ind.macdHistD1) < (ind.macdHistD1 - ind.macdHistD2);
    const waitDays = calcTradingDays(upperExitArmDate, now);
    if (returnPct >= targetPct && histTurnSignal) {
      return { shouldExit: true, reason: `목표 수익 구간 + MACD 히스토그램 둔화전환 매도 +${(returnPct * 100).toFixed(2)}% [${stratLabel}]` };
    }
    if (waitDays >= S.UPPER_EXIT_MAX_WAIT_DAYS) {
      return { shouldExit: true, reason: `목표 수익 도달 후 ${S.UPPER_EXIT_MAX_WAIT_DAYS}거래일 대기 만료 매도 ${(returnPct * 100).toFixed(2)}% [${stratLabel}]` };
    }
  }

  if (!isEfStrategy && returnPct >= targetPct) {
    return { shouldExit: true, reason: `목표 수익 달성 즉시 매도 +${(returnPct * 100).toFixed(2)}% [${stratLabel}]` };
  }

  if (returnPct <= -circuitPct)    return { shouldExit: true, reason: `손절 기준 도달 -${Math.abs(returnPct * 100).toFixed(2)}% [손절 -${circuitPct * 100}%]` };
  if (tradingDays >= S.STALLED_EXIT_DAYS && returnPct < S.STALLED_EXIT_MIN_RETURN) {
    return {
      shouldExit: true,
      reason: `${S.STALLED_EXIT_DAYS}거래일 반등 미달 청산 (${tradingDays}일, ${(returnPct * 100).toFixed(2)}% < +${(S.STALLED_EXIT_MIN_RETURN * 100).toFixed(0)}%)`
    };
  }
  if (strategyType !== "G" && tradingDays >= S.HALF_EXIT_DAYS && returnPct > 0) return { shouldExit: true, reason: `60거래일 경과 + 수익 중 자동 매도 (${tradingDays}일, +${(returnPct * 100).toFixed(2)}%)` };
  if (tradingDays >= maxHoldDays)  return { shouldExit: true, reason: `최대 보유 기간 초과 자동 매도 (${tradingDays}일, ${(returnPct * 100).toFixed(2)}%) [한도 ${maxHoldDays}일]` };

  return { shouldExit: false, reason: null };
}

function fmtPrice(v, stockName) {
  const isKR = /[ㄱ-ㅎ가-힣]/.test(stockName || "") || /^\d{6}$/.test(String(stockName || "").trim());
  return isKR ? "₩" + Math.round(Number(v)).toLocaleString("ko-KR") : "$" + Number(v).toFixed(2);
}

function fmtNumOrDash(v, decimals) {
  if (v === null || v === undefined || isNaN(v)) return "-";
  return Number(v).toFixed(decimals !== undefined ? decimals : 2);
}

function processStocks(stockData, marketData, targetSheet, allProperties, outerStartTime) {
  const processStartTime = outerStartTime || Date.now();
  const TIMEOUT_GUARD_MS = 320000;
  const props = PropertiesService.getScriptProperties();

  const changedStocks    = [];
  const C                = CONSTANTS.COL_INDICES;
  const S                = CONSTANTS.STRATEGY;
  const isEventWatch     = (marketData.event !== "당분간 없음");
  const { now, vixD, ixicDist, nasdaqPeakAlert, ixicFilterActive: ixicFilterFromMd } = marketData;
  const ixicFilterActive = ixicFilterFromMd !== undefined ? ixicFilterFromMd : computeNasdaqABFilterActive(ixicDist);
  const opinionWrites       = {};
  const entryPriceWrites    = {};
  const entryDateWrites     = {};
  const entryStrategyWrites = {};

  if (nasdaqPeakAlert) console.log(`[나스닥 고점 청산/강제매도] 조건 충족(${marketData.nasdaqPeakReason || "국면별 QQQ 과열 기준"}) — B/D 전략 보유분 강제 매도, A/C/E/F/G 보유분 제외 + 신규/재진입 차단`);

  if (ixicFilterActive) {
    const rawDeath = ixicDist > S.NASDAQ_DIST_LOWER && ixicDist < S.NASDAQ_DIST_UPPER;
    console.log(
      `[나스닥 하락장 필터] A/C/D/E/F/G 차단 (B는 미적용, 청산 아님) — QQQ 이격도 ${ixicDist.toFixed(2)}%` +
      (rawDeath ? ` (데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)` : ` (히스테리시스 유지, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`)
    );
  }
  if (Number.isFinite(ixicDist) && ixicDist > (marketData.nasdaqBuyBlockMax || S.NASDAQ_BUY_BLOCK_MAX)) {
    console.log(`[나스닥 상단 매수 차단] QQQ 이격도 ${ixicDist.toFixed(2)}% > ${marketData.nasdaqBuyBlockMax || S.NASDAQ_BUY_BLOCK_MAX}% — 전략 공통 신규/재진입 차단 (청산 기준 아님)`);
  }

  for (let i = 0; i < stockData.length; i++) {
    if (Date.now() - processStartTime > TIMEOUT_GUARD_MS) {
      throw new Error(`[타임아웃 방지] ${i + 1}/${stockData.length} 종목 처리 중 중단 (${((Date.now() - processStartTime) / 1000).toFixed(0)}초 경과) — 부분 반영 방지`);
    }

    const row = stockData[i];
    const ind = extractIndicators(row);
    if (!ind.stockName) continue;

    const isKR         = isKoreanStock(ind.stockName);
    const isMarketOpen = checkMarketOpen(now, isKR);

    if (ind.currentPrice === null || ind.currentPrice === 0 || ind.ma200 === null || ind.ma200 === 0) {
      if (ind.opinion === "") { opinionWrites[i + 3] = "관망"; console.log(`[초기화] ${ind.displayName} — 데이터 오류, 빈칸 → 관망`); }
      else console.log(`[SKIP] ${ind.displayName} — 데이터 오류 (현재가: ${ind.currentPrice}, MA200: ${ind.ma200}), 기존 의견 "${ind.opinion}" 유지`);
      continue;
    }

    const isInitializing = ind.opinion === "";
    if (isInitializing) { opinionWrites[i + 3] = "관망"; ind.opinion = "관망"; console.log(`[초기화] ${ind.displayName} — 빈칸 → 관망`); }

    const rawEntry = allProperties[`ENTRY_${ind.stockName}`];
    let saved      = parseEntryInfo(rawEntry);
    const sellInfo = parseSellInfo(allProperties[`SELL_${ind.stockName}`]);
    let activeSlots = getActiveSlotsFromProperties(ind.stockName, allProperties);
    console.log(`[ENTRY_키] ${ind.displayName} — price: ${saved.price}, date: ${saved.date ? Utilities.formatDate(saved.date, "Asia/Seoul", "yyyy-MM-dd") : "null"}, strategy: ${saved.price > 0 ? saved.strategyType : "-"}`);

    if (!rawEntry && activeSlots.length === 0) {
      clearAHoldRestoreProps(ind.stockName);
    }

    if (saved.price <= 0 && activeSlots.length > 0) {
      const promotedSlot = pickLatestSlot(activeSlots);
      if (promotedSlot) {
        saveEntryInfo(ind.stockName, promotedSlot.price, promotedSlot.date, promotedSlot.strategy, { preserveRestoreState: ind.opinion === "관망" });
        if (typeof Utils !== "undefined" && typeof Utils.clearSlot === "function") {
          Utils.clearSlot(ind.stockName, promotedSlot.id, props);
        }
        saved = { price: promotedSlot.price, date: promotedSlot.date, strategyType: promotedSlot.strategy };
        activeSlots = activeSlots.filter(slot => slot.id !== promotedSlot.id);
        ind.entryPrice = promotedSlot.price;
        ind.entryDate = promotedSlot.date;
        entryPriceWrites[i + 3] = promotedSlot.price;
        entryDateWrites[i + 3] = Utilities.formatDate(promotedSlot.date, "Asia/Seoul", "yyyy-MM-dd");
        entryStrategyWrites[i + 3] = strategyDisplayName(promotedSlot.strategy);
        console.log(` → [SLOT 승격] ${ind.displayName}: ${strategyDisplayName(promotedSlot.strategy)} 슬롯을 PRIMARY로 승격`);
      }
    }

    const isHolding = saved.price > 0;
    const buy  = evaluateBuyCondition(ind, vixD, ixicDist, ixicFilterActive, isHolding, isHolding ? saved.strategyType : null, allProperties, marketData.nasdaqBuyBlockMax);
    const extendedSellPrice = getUSExtendedSellPrice_(ind.stockName, ind.displayName, ind.currentPrice, isKR, isHolding, marketData);
    const exitInd = extendedSellPrice ? { ...ind, currentPrice: extendedSellPrice } : ind;

    if (saved.price > 0) {
      // ENTRY_ 키가 source of truth — 시트와 불일치하면 ENTRY_ 키 값으로 덮어씀
      ind.entryPrice = saved.price;
      ind.entryDate  = saved.date;
      exitInd.entryPrice = saved.price;
      exitInd.entryDate  = saved.date;

      const sheetPrice    = Number(row[C.entryPrice]) || 0;
      const sheetDateRaw  = row[C.entryDate];
      const sheetDateStr  = sheetDateRaw instanceof Date
        ? Utilities.formatDate(sheetDateRaw, "Asia/Seoul", "yyyy-MM-dd")
        : (typeof sheetDateRaw === "string" ? sheetDateRaw.trim() : "");
      const savedDateStr  = saved.date ? Utilities.formatDate(saved.date, "Asia/Seoul", "yyyy-MM-dd") : "";
      const sheetStratCode = parseStrategyCode(row[C.entryStrategy]);

      if (sheetPrice !== saved.price) {
        entryPriceWrites[i + 3] = saved.price;
        console.log(` → [진입가 동기화] ${ind.displayName}: 시트 ${fmtPrice(sheetPrice, ind.stockName)} → ENTRY_ ${fmtPrice(saved.price, ind.stockName)}`);
      }
      if (sheetDateStr !== savedDateStr && savedDateStr) {
        entryDateWrites[i + 3] = savedDateStr;
        console.log(` → [진입일 동기화] ${ind.displayName}: 시트 "${sheetDateStr}" → ENTRY_ "${savedDateStr}"`);
      }
      if (sheetStratCode !== saved.strategyType && /^[A-G]$/.test(saved.strategyType)) {
        entryStrategyWrites[i + 3] = strategyDisplayName(saved.strategyType);
        console.log(` → [전략 동기화] ${ind.displayName}: 시트 "${sheetStratCode || "없음"}" → ENTRY_ "${strategyDisplayName(saved.strategyType)}"`);
      }
    }

    const exit = isHolding ? evaluateExitCondition(exitInd, now, nasdaqPeakAlert, saved.strategyType, allProperties) : { shouldExit: false, reason: null };
    const shouldDeferHoldingChange = isHolding && shouldDeferHoldingOpinionChange(saved.strategyType, ind, buy);

    logStockAnalysis(exitInd, vixD, ixicDist, marketData.event, buy, exit, now, isHolding, nasdaqPeakAlert, saved.strategyType, isMarketOpen, isKR, sellInfo, marketData.isRecoveryMarket);

    let newOpinion    = ind.opinion;
    let newEntryPrice = ind.entryPrice;
    let newEntryDate  = ind.entryDate;
    const liquidateAllHoldings = (reason) => {
      newOpinion = "매도";
      newEntryPrice = 0;
      newEntryDate = null;
      if (typeof Utils !== "undefined" && typeof Utils.clearAllSlotStateForStock === "function") {
        Utils.clearAllSlotStateForStock(
          ind.stockName,
          exitInd.currentPrice,
          Utilities.formatDate(now, "Asia/Seoul", "yyyy-MM-dd"),
          props,
          allProperties
        );
      }
      clearEntryInfo(ind.stockName);
      saveSellInfo(ind.stockName, now, exitInd.currentPrice);
      saveExitReason(ind.stockName, reason);
      entryStrategyWrites[i + 3] = "";  // BC열 초기화
    };
    const liquidatePrimaryOnly = (reason) => {
      newOpinion = "매도";
      newEntryPrice = 0;
      newEntryDate = null;
      clearEntryInfo(ind.stockName);
      saveSellInfo(ind.stockName, now, exitInd.currentPrice);
      saveExitReason(ind.stockName, reason);
      entryStrategyWrites[i + 3] = "";
    };
    const promoteSlotToPrimary = (predicate) => {
      const promotedSlot = pickLatestSlot(activeSlots, predicate);
      if (!promotedSlot) return false;
      const exitedPrimaryStrategy = saved.strategyType;

      if (typeof Utils !== "undefined" && typeof Utils.recordSellSignal === "function") {
        Utils.recordSellSignal(ind.stockName, Utilities.formatDate(now, "Asia/Seoul", "yyyy-MM-dd"), exitInd.currentPrice, strategyDisplayName(exitedPrimaryStrategy));
      }

      saveEntryInfo(ind.stockName, promotedSlot.price, promotedSlot.date, promotedSlot.strategy);
      if (typeof Utils !== "undefined" && typeof Utils.clearSlot === "function") {
        Utils.clearSlot(ind.stockName, promotedSlot.id, props);
      }
      activeSlots = activeSlots.filter(slot => slot.id !== promotedSlot.id);

      const promotedBuy = evaluateBuyCondition(ind, vixD, ixicDist, ixicFilterActive, true, promotedSlot.strategy, allProperties, marketData.nasdaqBuyBlockMax);
      saved = { price: promotedSlot.price, date: promotedSlot.date, strategyType: promotedSlot.strategy };
      newEntryPrice = promotedSlot.price;
      newEntryDate = promotedSlot.date;
      newOpinion = promotedBuy.triggered ? "매수" : "관망";
      entryPriceWrites[i + 3] = promotedSlot.price;
      entryDateWrites[i + 3] = Utilities.formatDate(promotedSlot.date, "Asia/Seoul", "yyyy-MM-dd");
      entryStrategyWrites[i + 3] = strategyDisplayName(promotedSlot.strategy);
      console.log(` → [PRIMARY 승격] ${ind.displayName}: ${strategyDisplayName(exitedPrimaryStrategy)} 청산 후 ${strategyDisplayName(promotedSlot.strategy)} 슬롯을 PRIMARY로 승격`);
      return true;
    };

    if (isEventWatch && !nasdaqPeakAlert) {
      if (isHolding) {
        if (exit.shouldExit) {
          if (!promoteSlotToPrimary()) {
            liquidateAllHoldings(exit.reason);
            console.log(` → [매도] ${ind.displayName}: ${exit.reason}`);
          } else {
            console.log(` → [부분 매도] ${ind.displayName}: ${exit.reason}`);
          }
        } else if (ind.opinion === "매수") {
          if (buy.triggered) {
            console.log(` → [이벤트 중 보유 유지] ${ind.displayName}: 기존 보유 포지션 유지, 신규 진입만 차단`);
          } else if (shouldDeferHoldingChange) {
            console.log(` → [판단 유예] ${ind.displayName}: 보유 중 핵심 지표 결측 — 이벤트 기간에도 기존 의견 유지`);
          } else {
            newOpinion = "관망";
            console.log(` → [매수 조건 이탈 → 관망] ${ind.displayName}: 이벤트 기간에도 보유 해제 조건은 정상 반영`);
            props.setProperty(
              HOLD_ANCHOR_PREFIX + ind.stockName,
              String(ind.currentPrice)
            );
            props.setProperty(
              HOLD_WATCH_PREFIX + ind.stockName,
              Utilities.formatDate(now, "Asia/Seoul", "yyyy-MM-dd'T'HH:mm:ss") + "+09:00"
            );
          }
        } else {
          if (buy.triggered) console.log(` → [보유 유지/관망] ${ind.displayName}: 이벤트 기간 중 추가 매수 보류`);
          else if (shouldDeferHoldingChange) console.log(` → [보유 유지/관망] ${ind.displayName}: 핵심 지표 결측으로 복원/해제 판단 유예`);
          else console.log(` → [보유 유지/관망] ${ind.displayName}: 이벤트 기간, 매도 조건 미충족으로 관망 유지`);
        }
      } else if (ind.opinion === "매도") {
        const elapsedHours = sellInfo.date ? (now - sellInfo.date) / (1000 * 60 * 60) : S.SELL_HOLD_HOURS + 1;
        if (elapsedHours >= S.SELL_HOLD_HOURS) { newOpinion = "관망"; console.log(` → [매도 → 관망] ${ind.displayName}: 이벤트 기간 중 48시간 경과 → 관망 전환`); }
        else console.log(` → [매도 유지] ${ind.displayName}: 이벤트 기간, ${elapsedHours.toFixed(1)}시간 경과 / 48시간 대기 중`);
      } else {
        console.log(` → [이벤트 관망 유지] ${ind.displayName}: 이벤트 기간 — 신규 진입 차단`);
      }
    } else if (isHolding) {
      if (exit.shouldExit) {
        if (nasdaqPeakAlert && nasdaqPeakExitApplies(saved.strategyType)) {
          const closedPeakSlots = clearNasdaqPeakEligibleSlots(ind.stockName, activeSlots, props, now, exitInd.currentPrice);
          activeSlots = getActiveSlotsFromProperties(ind.stockName, props.getProperties());
          if (!promoteSlotToPrimary(slot => isNasdaqPeakExitExemptStrategy(slot.strategy))) {
            liquidatePrimaryOnly(exit.reason);
            console.log(` → [고점 청산] ${ind.displayName}: ${exit.reason} (PRIMARY ${saved.strategyType} 전략 청산, A/C/E/F/G 슬롯 제외)`);
          } else {
            console.log(` → [고점 부분 청산] ${ind.displayName}: PRIMARY ${saved.strategyType} 전략 및 B/D 슬롯 ${closedPeakSlots.length}개 청산, A/C/E/F/G 슬롯 보존`);
          }
        } else if (!promoteSlotToPrimary()) {
          liquidateAllHoldings(exit.reason);
          console.log(` → [매도] ${ind.displayName}: ${exit.reason}`);
        } else {
          console.log(` → [부분 매도] ${ind.displayName}: ${exit.reason}`);
        }
      } else if (ind.opinion === "매수") {
        if (buy.triggered) console.log(` → [매수 유지] ${ind.displayName}: 매수 조건 충족 중`);
        else if (shouldDeferHoldingChange) {
          console.log(` → [판단 유예] ${ind.displayName}: 보유 중 핵심 지표 결측 — 기존 매수 유지`);
        }
        else {
          newOpinion = "관망";
          console.log(` → [매수 조건 이탈 → 관망] ${ind.displayName}: ENTRY_ 키 유지, 매도 조건 계속 추적`);
          props.setProperty(
            HOLD_ANCHOR_PREFIX + ind.stockName,
            String(ind.currentPrice)
          );
          props.setProperty(
            HOLD_WATCH_PREFIX + ind.stockName,
            Utilities.formatDate(now, "Asia/Seoul", "yyyy-MM-dd'T'HH:mm:ss") + "+09:00"
          );
        }
      } else {
        if (buy.triggered && !isEventWatch) {
          const restoreState = getHoldRestoreState(ind.stockName, ind.currentPrice, now, allProperties);
          if (restoreState.allowed) {
            newOpinion = "매수";
            clearAHoldRestoreProps(ind.stockName);
            const restoreBasis = `전 진입가 ${fmtPrice(restoreState.entryPrice, ind.stockName)} 대비 -${(S.HOLD_RESTORE_DROP * 100).toFixed(0)}% 눌림 및 관망 ${restoreState.days}거래일 경과`;
            console.log(` → [보유 유지/관망→추가 매수 신호] ${ind.displayName}: 매수 조건 재충족 (${restoreBasis})`);
          } else {
            const repairedState = ensureHoldRestoreWatchState(ind.stockName, ind.currentPrice, now, allProperties, props);
            const restoreWait = repairedState.missingEntry
              ? "전 진입가 정보 없음"
              : repairedState.missingWatch
              ? "관망 시작 시각 복구 실패"
              : `전 진입가 ${fmtPrice(repairedState.entryPrice, ind.stockName)} 대비 -${(S.HOLD_RESTORE_DROP * 100).toFixed(0)}% 및 관망 ${S.HOLD_RESTORE_MIN_TRADING_DAYS}거래일`;
            console.log(` → [${saved.strategyType} 추가 매수 보류] ${ind.displayName}: ${restoreWait} 충족 시에만 추가 매수 허용`);
          }
        } else if (shouldDeferHoldingChange) {
          console.log(` → [보유 유지/관망] ${ind.displayName}: 핵심 지표 결측으로 복원/해제 판단 유예`);
        } else if (buy.triggered) console.log(` → [보유 유지/관망] ${ind.displayName}: 매수 조건 재충족이나 이벤트 당일 — 추가 매수 보류`);
        else console.log(` → [보유 유지/관망] ${ind.displayName}: ${calcTradingDays(ind.entryDate, now)}거래일, 수익률 ${((ind.currentPrice - ind.entryPrice) / ind.entryPrice * 100).toFixed(2)}% — 매도 조건 미충족, 관망 유지`);
      }
    } else {
      const sellTime  = sellInfo.date;
      const sellPrice = sellInfo.price;
      const elapsedHours = sellTime ? (now - sellTime) / (1000 * 60 * 60) : S.SELL_HOLD_HOURS + 1;
      const tradingDaysSinceSell = sellTime ? calcTradingDays(sellTime, now) : 0;

      let isReentryAllowed = true;
      let reentryLog = "";
      if (sellTime) {
        if (elapsedHours < S.SELL_HOLD_HOURS) {
          isReentryAllowed = false; reentryLog = "48시간 대기 중";
        } else if (tradingDaysSinceSell <= S.REENTRY_DAYS) {
          if (sellPrice > 0 && ind.currentPrice <= sellPrice * (1 - S.REENTRY_DROP)) { reentryLog = `매도 후 ${tradingDaysSinceSell}일, -3% 하락 조건 충족`; }
          else { isReentryAllowed = false; reentryLog = `매도 후 10일 이내, -3% 하락 미달`; }
        } else { reentryLog = "매도 후 10일 경과 (쿨다운 완전 해제)"; }
      }

      if (ind.opinion === "매도") {
        if (elapsedHours < S.SELL_HOLD_HOURS) {
          if (nasdaqPeakAlert) {
            console.log(` → [매도 유지] ${ind.displayName}: 고점 청산/강제매도 후 48시간 대기 중 (${elapsedHours.toFixed(1)}시간 경과)`);
          } else {
            console.log(` → [매도 유지] ${ind.displayName}: ${elapsedHours.toFixed(1)}시간 경과 / 48시간 대기 중`);
          }
        } else if (nasdaqPeakAlert) {
          newOpinion = "관망";
          console.log(` → [매도 → 관망] ${ind.displayName}: 48시간 경과 후에도 고점 청산/강제매도 상태 유지 — 신규/재진입 차단 지속`);
        } else if (buy.triggered && !isEventWatch) {
          if (isReentryAllowed) {
            newOpinion = "매수"; newEntryPrice = ind.currentPrice; newEntryDate = now;
            saveEntryInfo(ind.stockName, ind.currentPrice, now, buy.strategyType); clearExitReason(ind.stockName); clearSellInfo(ind.stockName);
            if (buy.strategyType) entryStrategyWrites[i + 3] = strategyDisplayName(buy.strategyType);
            console.log(` → [매도 → 매수] ${ind.displayName}: 재진입 조건 충족 및 쿨다운 통과 (${reentryLog})`);
          } else {
            newOpinion = "관망";
            console.log(` → [매도 → 관망] ${ind.displayName}: 매수 조건 충족이나 재진입 쿨다운 제한 중 (${reentryLog})`);
          }
        } else {
          newOpinion = "관망";
          if (isEventWatch) {
            console.log(` → [매도 → 관망] ${ind.displayName}: 48시간 경과 — 이벤트 기간 중 신규 진입 차단 유지`);
          } else {
            console.log(` → [매도 → 관망] ${ind.displayName}: 48시간 경과 (${elapsedHours.toFixed(1)}시간) - 재진입 필터는 10일간 계속 유지`);
          }
        }
      } else {
        if (nasdaqPeakAlert) { console.log(` → [진입 차단] ${ind.displayName}: 고점 청산/강제매도 상태 — 신규/재진입 차단`); }
        else if (isEventWatch) { console.log(` → [이벤트 관망] ${ind.displayName}: 신규 진입 차단 (이벤트: ${marketData.event})`); }
        else if (ixicDist > (marketData.nasdaqBuyBlockMax || S.NASDAQ_BUY_BLOCK_MAX) && !buy.triggered) { console.log(` → [상단 매수 차단] ${ind.displayName}: QQQ 이격도 ${ixicDist.toFixed(1)}% > ${marketData.nasdaqBuyBlockMax || S.NASDAQ_BUY_BLOCK_MAX}% — 신규/재진입 차단만 적용 (청산 아님)`); }
        else if (buy.ixicFilterActive && !buy.triggered) { console.log(` → [하락장 필터 차단] ${ind.displayName}: QQQ 이격도 ${ixicDist.toFixed(1)}% — A/C/D/E/F/G그룹 차단, B 조건 미충족 (청산 아님)`); }
        else if (buy.triggered) {
          if (isReentryAllowed) {
            newOpinion = "매수"; newEntryPrice = ind.currentPrice; newEntryDate = now;
            saveEntryInfo(ind.stockName, ind.currentPrice, now, buy.strategyType); clearExitReason(ind.stockName); clearSellInfo(ind.stockName);
            if (buy.strategyType) entryStrategyWrites[i + 3] = strategyDisplayName(buy.strategyType);
            const entryLog = _buildEntryLog(buy.strategyType, ind, vixD);
            console.log(` → [매수] ${ind.displayName}: ${entryLog}`);
          } else { console.log(` → [관망 유지] ${ind.displayName}: 매수 조건 충족이나 재진입 쿨다운 제한 중 (${reentryLog})`); }
        }
      }
    }

    if (newOpinion !== ind.opinion) {
      opinionWrites[i + 3] = newOpinion;
      let changeReason;
      if (newOpinion === "매수") {
        const effectiveStratType = buy.strategyType || (isHolding ? saved.strategyType : null);
        changeReason = _buildChangeReasonBuy(effectiveStratType, ind, vixD);
      } else if (newOpinion === "매도") {
        changeReason = exit.reason || "매도 조건 충족";
      } else if (newOpinion === "관망" && ind.opinion === "매수") {
        if (isEventWatch && !nasdaqPeakAlert && isHolding && buy.triggered) {
          changeReason = `이벤트 기간 관망 전환 (${marketData.event}) — 보유 데이터 유지`;
        } else {
          changeReason = `매수 조건 이탈 (${_buildReleaseReason(saved.strategyType, ind, buy, vixD, ixicDist, S)}) — 보유 중 계속 추적`;
        }
      } else if (newOpinion === "관망" && ind.opinion === "매도") {
        changeReason = nasdaqPeakAlert
          ? "고점 청산/강제매도 상태 유지 중 48시간 경과 → 관망 전환 (신규/재진입 차단 유지)"
          : "매도 후 대기 완료 → 관망 전환 (재진입 필터 유지)";
      } else {
        changeReason = isInitializing ? "초기값 설정" : "관망 전환";
      }
      changedStocks.push({ stock: ind.displayName, from: isInitializing ? "초기값" : ind.opinion, to: newOpinion, reason: changeReason });
    } else if (isInitializing) {
      changedStocks.push({ stock: ind.displayName, from: "초기값", to: "관망", reason: "초기값 설정" });
    }

    const newEntryPriceVal = newEntryPrice > 0 ? newEntryPrice : "";
    if (newEntryPriceVal !== (ind.entryPrice > 0 ? ind.entryPrice : "")) { entryPriceWrites[i + 3] = newEntryPriceVal; console.log(` → [진입가 예약] ${ind.displayName}: ${ind.entryPrice > 0 ? ind.entryPrice : ""} → ${newEntryPriceVal}`); }

    const newEntryDateStr = newEntryDate ? Utilities.formatDate(newEntryDate, "Asia/Seoul", "yyyy-MM-dd") : "";
    const oldEntryDateStr = ind.entryDate ? Utilities.formatDate(ind.entryDate, "Asia/Seoul", "yyyy-MM-dd") : "";
    if (newEntryDateStr !== oldEntryDateStr) { entryDateWrites[i + 3] = newEntryDateStr; console.log(` → [진입일 예약] ${ind.displayName}: "${oldEntryDateStr}" → "${newEntryDateStr}"`); }

    if (isHolding) {
      const effOp = opinionWrites[i + 3] !== undefined ? opinionWrites[i + 3] : ind.opinion;
      if (effOp === "매수" && ind.currentPrice > 0) {
        props.setProperty(HOLD_ANCHOR_PREFIX + ind.stockName, String(ind.currentPrice));
      }
    }
  }

  flushWrites(targetSheet, opinionWrites,       C.opinion + 1,       "투자의견");
  flushWrites(targetSheet, entryPriceWrites,    C.entryPrice + 1,    "진입가");
  flushWrites(targetSheet, entryDateWrites,     C.entryDate + 1,     "진입일");
  flushWrites(targetSheet, entryStrategyWrites, C.entryStrategy + 1, "진입전략");
  return changedStocks;
}

/** 진입 로그 문자열 */
function _buildEntryLog(stratType, ind, vixD) {
  const fP = v => fmtPrice(v, ind.stockName);
  const fn = (v, d) => fmtNumOrDash(v, d);
  switch (stratType) {
    case "A": return `200일선 상방 & 모멘텀 재가속 — 현재가 ${fP(ind.currentPrice)} > MA200 ${fP(ind.ma200)}, MACD hist ${fn(ind.macdHist, 4)}, 종가%B ${fn(ind.pctB, 1)}, RSI ${fn(ind.rsi, 1)}`;
    case "B": return `200일선 하방 & 공황 저점 — 현재가 ${fP(ind.currentPrice)}, MA200 ${fP(ind.ma200)}, VIX ${vixD.toFixed(2)}, RSI ${fn(ind.rsi, 2)} / CCI ${fn(ind.cci, 2)}, LR추세선 ${fP(ind.lrTrendline)}, 저가 ${fP(ind.candleLow)}`;
    case "C": return `200일선 상방 & 스퀴즈 거래량 돌파 — 현재가 ${fP(ind.currentPrice)} > MA200 ${fP(ind.ma200)}, BB폭 ${fn(ind.bbWidth, 2)} / 전일 ${fn(ind.bbWidthD1, 2)} / 60일평균 ${fn(ind.bbWidthAvg60, 2)}, 거래량비율 ${fn(ind.volRatio, 2)}, 종가%B ${fn(ind.pctB, 1)}, MACD hist ${fn(ind.macdHist, 4)}`;
    case "D": return `200일선 상방 & 상승 흐름 강화 — 현재가 ${fP(ind.currentPrice)} > MA200 ${fP(ind.ma200)}, +DI ${fn(ind.plusDI, 1)} / -DI ${fn(ind.minusDI, 1)}, ADX ${fn(ind.adx, 1)} (전일 ${fn(ind.adxD1, 1)}), 종가%B ${fn(ind.pctB, 1)}, MACD hist ${fn(ind.macdHist, 4)}`;
    case "E": {
      const sqRatio = (ind.bbWidth !== null && ind.bbWidthAvg60 !== null && ind.bbWidthAvg60 > 0) ? ((ind.bbWidth / ind.bbWidthAvg60) * 100).toFixed(1) + "%" : "-";
      return `200일선 상방 & 스퀴즈 저점 — 현재가 ${fP(ind.currentPrice)} > MA200 ${fP(ind.ma200)}, BB폭 압축 ${sqRatio}, 저가%B ${fn(ind.pctBLow, 2)}`;
    }
    case "F": return `200일선 상방 & BB 극단 저점 — 현재가 ${fP(ind.currentPrice)} > MA200 ${fP(ind.ma200)}, 저가%B ${fn(ind.pctBLow, 2)}`;
    case "G": {
      const gState = fetchGMa20PullbackState_(ind.stockName);
      const gMa20 = gState && Number.isFinite(Number(gState.ma20)) ? Number(gState.ma20) : ind.ma20;
      return `급락 후 회복장 20일선 눌림 — 현재가 ${fP(ind.currentPrice)} > MA200 ${fP(ind.ma200)}, MA20 ${fP(gMa20)}, RSI ${fn(ind.rsi, 1)}, MA20 기울기 ${formatGMa20Slope_(gState)}, 20일 거래량비 ${formatGVolRatio20_(gState)}`;
    }
    default:  return `진입 — 현재가 ${fP(ind.currentPrice)}`;
  }
}

/** 매수 변경 이유 문자열 (changedStocks 기록용) */
function _buildChangeReasonBuy(stratType, ind, vixD) {
  const fP = v => fmtPrice(v, ind.stockName);
  const fn = (v, d) => fmtNumOrDash(v, d);
  switch (stratType) {
    case "A": return `200일선 상방 & 모멘텀 재가속 진입 — 현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)} | MACD hist ${fn(ind.macdHist, 4)} | 종가%B ${fn(ind.pctB, 1)} | RSI ${fn(ind.rsi, 1)}`;
    case "B": return `200일선 하방 & 공황 저점 진입 — 현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)} | VIX ${vixD.toFixed(2)} | RSI ${fn(ind.rsi, 2)} / CCI ${fn(ind.cci, 2)} | LR추세선 ${fP(ind.lrTrendline)} / 저가 ${fP(ind.candleLow)}`;
    case "C": return `200일선 상방 & 스퀴즈 거래량 돌파 진입 — 현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)} | BB폭 ${fn(ind.bbWidth, 2)} / 전일 ${fn(ind.bbWidthD1, 2)} | 거래량비율 ${fn(ind.volRatio, 2)} | 종가%B ${fn(ind.pctB, 1)}`;
    case "D": return `200일선 상방 & 상승 흐름 강화 진입 — 현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)} | +DI ${fn(ind.plusDI, 1)} / -DI ${fn(ind.minusDI, 1)} | ADX ${fn(ind.adx, 1)} | 종가%B ${fn(ind.pctB, 1)}`;
    case "E": {
      const sqRatio = (ind.bbWidth !== null && ind.bbWidthAvg60 !== null && ind.bbWidthAvg60 > 0) ? ((ind.bbWidth / ind.bbWidthAvg60) * 100).toFixed(1) + "%" : "-";
      return `200일선 상방 & 스퀴즈 저점 진입 — 현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)} | BB폭 ${fn(ind.bbWidth, 2)} / 60일평균 ${fn(ind.bbWidthAvg60, 2)} (압축 ${sqRatio}) | 저가%B ${fn(ind.pctBLow, 2)}`;
    }
    case "F": return `200일선 상방 & BB 극단 저점 진입 — 현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)} | 저가%B ${fn(ind.pctBLow, 2)}`;
    case "G": {
      const gState = fetchGMa20PullbackState_(ind.stockName);
      const gMa20 = gState && Number.isFinite(Number(gState.ma20)) ? Number(gState.ma20) : ind.ma20;
      return `급락 후 회복장 20일선 눌림 진입 — 현재가 ${fP(ind.currentPrice)} / MA20 ${fP(gMa20)} / MA200 ${fP(ind.ma200)} | RSI ${fn(ind.rsi, 1)} | MA20 기울기 ${formatGMa20Slope_(gState)} | 20일 거래량비 ${formatGVolRatio20_(gState)}`;
    }
    default:  return `진입 — 현재가 ${fP(ind.currentPrice)}`;
  }
}

/** 매수 조건 이탈 이유 문자열 */
function _buildReleaseReason(stratType, ind, buy, vixD, ixicDist, S) {
  const fP = v => fmtPrice(v, ind.stockName);
  const fn = (v, d) => fmtNumOrDash(v, d);
  // 보유 중인 종목은 상단 과열 구간에서 매수 조건 이탈로 관망 전환하되, 청산 기준은 아니다.
  const buyBlockMax = typeof getNasdaqBuyBlockMax_ === "function" ? getNasdaqBuyBlockMax_(ixicDist) : S.NASDAQ_BUY_BLOCK_MAX;
  if (Number.isFinite(ixicDist) && ixicDist > buyBlockMax) {
    return `나스닥 상단 과열 (QQQ 이격도 ${ixicDist.toFixed(1)}% > ${buyBlockMax}%)`;
  }
  switch (stratType) {
    case "A":
      if (!buy.aCond1) return `200일선 하방 이탈 (현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)})`;
      if (!buy.nasdaqAllowsStrictMomentum) return `나스닥 이격도 부족 (${ixicDist.toFixed(1)}% < ${S.NASDAQ_DIST_UPPER}%)`;
      if (ind.macdHist === null) return "MACD 히스토그램 일시 결측 (모멘텀 소멸로 단정하지 않음)";
      return `MACD 히스토그램 음전환 (hist ${fn(ind.macdHist, 4)} ≤ 0)`;
    case "B":
      if (!buy.bCond1) return `주가가 200일선 위로 회복 (현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)})`;
      if (!buy.bCond2) return `시장 공포 수치 완화 (VIX ${vixD} < ${buy.vixThreshold})`;
      if (!buy.hasRsi && !buy.hasCci) return "RSI/CCI 일시 결측 (과매도 해소로 단정하지 않음)";
      if (!buy.bCond3Hold) return `과매도 해소 (RSI ${fn(ind.rsi, 2)} / CCI ${fn(ind.cci, 2)})`;
      return `추세선 기울기 하락 전환 (기울기 ≤ 0)`;
    case "C":
      if (!buy.cCond1) return `200일선 하방 이탈 (현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)})`;
      if (!buy.nasdaqAllowsStrictMomentum) return `나스닥 이격도 부족 (${ixicDist.toFixed(1)}% < ${S.NASDAQ_DIST_UPPER}%)`;
      if (ind.macdHist === null) return "MACD 히스토그램 일시 결측 (모멘텀 소멸로 단정하지 않음)";
      return `MACD 히스토그램 음전환 (hist ${fn(ind.macdHist, 4)} ≤ 0)`;
    case "D":
      if (!buy.dCond1) return `200일선 하방 이탈 (현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)})`;
      if (!buy.nasdaqAllowsStrictMomentum) return `나스닥 이격도 부족 (${ixicDist.toFixed(1)}% < ${S.NASDAQ_DIST_UPPER}%)`;
      if (ind.plusDI === null || ind.minusDI === null || ind.macdHist === null) return "DMI/MACD 일시 결측 (추세 약화로 단정하지 않음)";
      return `추세 흐름 약화 (+DI ${fn(ind.plusDI, 1)} / -DI ${fn(ind.minusDI, 1)} 또는 MACD hist ${fn(ind.macdHist, 4)})`;
    case "E": {
      if (!buy.nasdaqAllowsBottomBuy) {
        const inDeath = ixicDist > S.NASDAQ_DIST_LOWER && ixicDist < S.NASDAQ_DIST_UPPER;
        return inDeath
          ? `나스닥 하락장 필터 진입 (QQQ 이격도 ${ixicDist.toFixed(1)}% → 데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)`
          : `나스닥 E/F 차단 유지 (히스테리시스 이격도 ${ixicDist.toFixed(1)}%, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`;
      }
      if (!buy.eCond1) return `200일선 하방 이탈 (현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)})`;
      if (!buy.bbPairOk || ind.pctBLow === null) return "BB·저가%B 일시 결측 (스퀴즈 이탈로 단정하지 않음)";
      if (buy.bbPairOk && !buy.eCond2) return `BB 스퀴즈 해소 (BB폭 ${fn(ind.bbWidth, 2)} / 60일평균 ${fn(ind.bbWidthAvg60, 2)})`;
      return `저가 %B 상승 (${fn(ind.pctBLow, 2)} > ${S.SQUEEZE_PCT_B_MAX})`;
    }
    case "F": {
      if (!buy.nasdaqAllowsBottomBuy) {
        const inDeath = ixicDist > S.NASDAQ_DIST_LOWER && ixicDist < S.NASDAQ_DIST_UPPER;
        return inDeath
          ? `나스닥 하락장 필터 진입 (QQQ 이격도 ${ixicDist.toFixed(1)}% → 데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)`
          : `나스닥 F 차단 유지 (히스테리시스 이격도 ${ixicDist.toFixed(1)}%, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`;
      }
      if (!buy.fCond1) return `200일선 하방 이탈 (현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)})`;
      if (ind.pctBLow === null) return "저가 %B 일시 결측 (눌림 해소로 단정하지 않음)";
      return `BB 하단 눌림 해소 (저가%B ${fn(ind.pctBLow, 2)} > ${S.BB_PCT_B_LOW_MAX})`;
    }
    case "G": {
      if (!buy.gCond1) return `G 회복장 조건 이탈 (QQQ 이격도 ${ixicDist.toFixed(1)}%, 기준 ${S.G_QQQ_DIST_MIN}~${S.G_QQQ_DIST_MAX}%)`;
      if (!buy.gCond2) return `200일선 하방 이탈 (현재가 ${fP(ind.currentPrice)} / MA200 ${fP(ind.ma200)})`;
      if (!buy.gState) return "MA20 눌림 데이터 일시 결측";
      if (!buy.gCond5) return `20일선 회복 실패 (종가 ${fP(buy.gClose)} / MA20 ${fP(buy.gMa20)})`;
      if (!buy.gCond7) return `MA20 기울기 둔화 (${fn(buy.gState.ma20Slope5 * 100, 2)}% < ${(S.G_MA20_SLOPE5_MIN * 100).toFixed(1)}%)`;
      return `G그룹 눌림 조건 이탈 (현재가 ${fP(ind.currentPrice)} / MA20 ${fP(buy.gMa20)} / RSI ${fn(ind.rsi, 1)})`;
    }
    default: return "매수 조건 이탈";
  }
}

function shouldDeferHoldingOpinionChange(stratType, ind, buy) {
  if (!stratType) return false;
  switch (stratType) {
    case "A":
    case "C":
      return ind.macdHist === null;
    case "B":
      return !buy.hasRsi && !buy.hasCci;
    case "D":
      return ind.plusDI === null || ind.minusDI === null || ind.macdHist === null;
    case "E":
      return !buy.bbPairOk || ind.pctBLow === null;
    case "F":
      return ind.pctBLow === null;
    case "G":
      return !buy.gState;
    default:
      return false;
  }
}

function flushWrites(sheet, writes, col, label) {
  const rows = Object.keys(writes);
  if (rows.length === 0) return;
  rows.sort((a, b) => Number(a) - Number(b));
  let batchStart = null;
  let batchVals  = [];
  const commitBatch = () => {
    if (batchVals.length === 0) return;
    if (batchVals.length === 1) sheet.getRange(batchStart, col).setValue(batchVals[0]);
    else sheet.getRange(batchStart, col, batchVals.length, 1).setValues(batchVals.map(v => [v]));
    console.log(`[배치 쓰기] ${label} — ${batchStart}행~${batchStart + batchVals.length - 1}행 (${batchVals.length}건)`);
    batchStart = null; batchVals = [];
  };
  for (let idx = 0; idx < rows.length; idx++) {
    const rowNum = Number(rows[idx]);
    if (batchStart === null) { batchStart = rowNum; batchVals = [writes[rowNum]]; }
    else if (rowNum === batchStart + batchVals.length) { batchVals.push(writes[rowNum]); }
    else { commitBatch(); batchStart = rowNum; batchVals = [writes[rowNum]]; }
  }
  commitBatch();
}

function logStockAnalysis(ind, vixD, ixicDist, event, buy, exit, now, isHolding, nasdaqPeakAlert, strategyType, isMarketOpen, isKR, sellInfo, isRecoveryMarket) {
  const S            = CONSTANTS.STRATEGY;
  const fmt          = v => Number(v).toFixed(2);
  const fmtP         = v => fmtPrice(v, ind.stockName);
  const fn           = (v, d) => fmtNumOrDash(v, d);
  const entryDateStr = ind.entryDate ? Utilities.formatDate(ind.entryDate, "Asia/Seoul", "yyyy-MM-dd") : "-";
  const returnPct    = ind.entryPrice > 0 ? ((ind.currentPrice - ind.entryPrice) / ind.entryPrice * 100).toFixed(2) : "-";
  const tradingDays  = ind.entryDate ? calcTradingDays(ind.entryDate, now) : "-";
  const sellTime     = sellInfo ? sellInfo.date : null;
  const sellPrice    = sellInfo ? sellInfo.price : 0;
  const sellElapsed  = sellTime ? `${((now - sellTime) / (1000 * 60 * 60)).toFixed(1)}시간 경과` : "-";
  const daysSinceSell = sellTime ? calcTradingDays(sellTime, now) : "-";

  const activePct = strategyType === "A" ? S.TARGET_PCT_A  : strategyType === "B" ? S.TARGET_PCT_B
                  : strategyType === "C" ? S.TARGET_PCT_C  : strategyType === "D" ? S.TARGET_PCT_D
                  : strategyType === "E" ? S.TARGET_PCT_E  : strategyType === "F" ? S.TARGET_PCT_F : S.TARGET_PCT_G;
  const activeCircuit = strategyType === "A" ? S.CIRCUIT_PCT_A  : strategyType === "B" ? S.CIRCUIT_PCT_B
                      : strategyType === "C" ? S.CIRCUIT_PCT_C  : strategyType === "D" ? S.CIRCUIT_PCT_D
                      : strategyType === "E" ? S.CIRCUIT_PCT_E  : strategyType === "F" ? S.CIRCUIT_PCT_F : S.CIRCUIT_PCT_G;
  const stratLabel = strategyType === "A" ? "200일선 상방 & 모멘텀 재가속"
                   : strategyType === "B" ? "200일선 하방 & 공황 저점"
                   : strategyType === "C" ? "200일선 상방 & 스퀴즈 거래량 돌파"
                   : strategyType === "D" ? "200일선 상방 & 상승 흐름 강화"
                   : strategyType === "E" ? "200일선 상방 & 스퀴즈 저점"
                   : strategyType === "F" ? "200일선 상방 & BB 극단 저점"
                   : "급락 후 회복장 20일선 눌림";

  const isEfStrategy = strategyType === "E" || strategyType === "F";
  const upperExitArmDate = isHolding && isEfStrategy ? loadUpperExitArm(ind.stockName) : null;
  const upperExitWaitDays = upperExitArmDate ? calcTradingDays(upperExitArmDate, now) : null;
  const histTurnSignal =
    ind.macdHist !== null && ind.macdHistD1 !== null && ind.macdHistD2 !== null &&
    (ind.macdHist - ind.macdHistD1) < (ind.macdHistD1 - ind.macdHistD2);

  const rawInDeath = ixicDist > S.NASDAQ_DIST_LOWER && ixicDist < S.NASDAQ_DIST_UPPER;
  const buyBlockMax = typeof getNasdaqBuyBlockMax_ === "function" ? getNasdaqBuyBlockMax_(ixicDist) : S.NASDAQ_BUY_BLOCK_MAX;
  const ixicFilterLabel = buy.ixicFilterActive
    ? (rawInDeath
      ? `🚫 활성: A/C/D/E/F/G 차단, B 미적용 (데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)`
      : `🚫 활성 유지: A/C/D/E/F/G 차단, B 미적용 (히스테리시스, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`)
    : ixicDist <= S.NASDAQ_DIST_LOWER ? `✅ 비활성: 찐바닥 구간(≤ ${S.NASDAQ_DIST_LOWER}%)` : `✅ 비활성: 강세/정상 구간(≥ ${S.NASDAQ_DIST_RELEASE}%)`;
  const buyBlockLabel = Number.isFinite(ixicDist) && ixicDist > buyBlockMax
    ? `🚫 활성: 신규/재진입 차단 (>${buyBlockMax}%, 청산 아님)`
    : `✅ 비활성: 신규/재진입 허용 범위(≤ ${buyBlockMax}%)`;
  const peakExitLabel = nasdaqPeakAlert
    ? `🚨 활성: 보유 종목 강제매도 + 신규/재진입 차단 (국면별 QQQ 과열 기준)`
    : "없음";

  let reentryState = "";
  if (!isHolding && sellTime) {
    if (nasdaqPeakAlert) {
      reentryState = `\n  재진입 차단: 고점 청산/강제매도 상태 유지 중`;
    } else if (daysSinceSell <= S.REENTRY_DAYS) {
      const dropPct  = sellPrice > 0 ? ((ind.currentPrice - sellPrice) / sellPrice * 100).toFixed(1) : 0;
      const isDropOk = sellPrice > 0 && ind.currentPrice <= sellPrice * (1 - S.REENTRY_DROP);
      reentryState = `\n  재진입 쿨다운 중 (매도 후 ${daysSinceSell}일 / 요구:-3%, 현재:${dropPct}%) → ${isDropOk ? "✅ 통과" : "❌ 미달"}`;
    } else { reentryState = `\n  재진입 쿨다운 해제 (매도 후 ${daysSinceSell}일)`; }
  }

  console.log(
    `\n====== ${ind.displayName} ======` +
    `\n[시장]` +
    `\n  이벤트: ${event}` +
    `\n  VIX: ${fmt(vixD)} (진입 ≥${S.VIX_MIN} / 해제 <${S.VIX_RELEASE}${isHolding ? " [보유중 적용]" : ""}): ${buy.cond2 ? "✅" : "❌"}` +
    `\n  QQQ 이격도(현재): ${ixicDist.toFixed(2)}%` +
    `\n  하락장 필터(데스존/히스테리시스, A/C/D/E/F/G 차단): ${ixicFilterLabel}` +
    `\n  상단 매수 차단(>${buyBlockMax}%, 신규/재진입만): ${buyBlockLabel}` +
    `\n  고점 청산/강제매도(국면별 기준): ${peakExitLabel}` +
    `\n  ${isKR ? "한국 장" : "미국 장"} 개장(참고): ${isMarketOpen ? "✅ 개장 중" : "❌ 미개장"}` +

    `\n[A그룹: 200일선 상방 & 모멘텀 재가속 (나스닥 ≥${S.NASDAQ_DIST_UPPER}%)]` +
    `\n  ① 나스닥 필터(강세장전용): ${buy.nasdaqAllowsStrictMomentum ? "✅" : "❌"} (이격도 ${ixicDist.toFixed(1)}%)` +
    `\n  ② 현재가(${fmtP(ind.currentPrice)}) > MA200(${fmtP(ind.ma200)}): ${buy.aCond1 ? "✅" : "❌"}` +
    `\n  ③ MACD 골든크로스 (전일hist ${fn(ind.macdHistD1, 4)}, 당일 ${fn(ind.macdHist, 4)} | 조건: 전일 ≤ 0 && 당일 > 0): ${buy.aCond2 ? "✅" : "❌"}` +
    `\n  ④ 종가%B(${fn(ind.pctB, 1)}) > ${S.GOLDEN_CROSS_PCTB_MIN}: ${buy.aCond3 ? "✅" : "❌"}` +
    `\n  ⑤ RSI(${fn(ind.rsi, 1)}) > ${S.GOLDEN_CROSS_RSI_MIN}: ${buy.aCond4 ? "✅" : "❌"}` +

    `\n[B그룹: 200일선 하방 & 공황 저점 (나스닥 필터 미적용)]` +
    `\n  ① 현재가(${fmtP(ind.currentPrice)}) < MA200(${fmtP(ind.ma200)}): ${buy.bCond1 ? "✅" : "❌"}` +
    `\n  ② VIX(${fmt(vixD)}) ≥ ${buy.vixThreshold}: ${buy.bCond2 ? "✅" : "❌"}` +
    `\n  ③ RSI(${fn(ind.rsi, 2)}) < ${S.RSI_MAX}: ${buy.rsiOk ? "✅" : "❌"}  |  CCI(${fn(ind.cci, 2)}) < ${S.CCI_MIN}: ${buy.cciOk ? "✅" : "❌"}  → OR: ${(isHolding && strategyType === "B" ? buy.bCond3Hold : buy.bCond3) ? "✅" : "❌"}${isHolding && strategyType === "B" && ind.rsi === null && ind.cci === null ? " (결측 → 추가 매수 보류)" : ""}` +
    `\n  ④ LR추세선 기울기(${buy.lrSlope !== undefined ? buy.lrSlope.toFixed(6) : "-"}) > 0: ${buy.bCond4 ? "✅" : "❌"}` +
    `\n  ⑤ 저가(${fn(ind.candleLow, 2)}) ≤ 추세선(${fn(ind.lrTrendline, 2)}) × ${S.LR_TOUCH_RATIO.toFixed(2)}: ${buy.bCond5 ? "✅" : "❌"}` +

    `\n[C그룹: 200일선 상방 & 스퀴즈 거래량 돌파 (나스닥 ≥${S.NASDAQ_DIST_UPPER}%)]` +
    `\n  ① 나스닥 필터(강세장전용): ${buy.nasdaqAllowsStrictMomentum ? "✅" : "❌"}` +
    `\n  ② 현재가(${fmtP(ind.currentPrice)}) > MA200(${fmtP(ind.ma200)}): ${buy.cCond1 ? "✅" : "❌"}` +
    `\n  ③ 전일 BB스퀴즈 (전일폭 ${fn(ind.bbWidthD1, 2)} / 60일평균 ${fn(ind.bbWidthAvg60, 2)} | 조건: 비율 < ${S.C_SQUEEZE_RATIO * 100}%): ${buy.cCond2 ? "✅" : "❌"}` +
    `\n  ④ 당일 BB확장 (당일폭 ${fn(ind.bbWidth, 2)}, 전일폭 ${fn(ind.bbWidthD1, 2)} | 조건: 당일 > 전일 × ${S.BB_EXPAND_RATIO}): ${buy.cCond3 ? "✅" : "❌"}` +
    `\n  ⑤ 거래량비율(${fn(ind.volRatio, 2)}) ≥ ${S.SQUEEZE_BREAKOUT_VOL_RATIO}${ind.volRatio === null ? " [컬럼 미설정 → 비활성]" : ""}: ${buy.cCond4 ? "✅" : "❌"}` +
    `\n  ⑥ 종가%B(${fn(ind.pctB, 1)}) > ${S.SQUEEZE_BREAKOUT_PCTB_MIN}: ${buy.cCond5 ? "✅" : "❌"}` +
    `\n  ⑦ MACD hist(${fn(ind.macdHist, 4)}) > 0: ${buy.cCond6 ? "✅" : "❌"}` +

    `\n[D그룹: 200일선 상방 & 상승 흐름 강화 (나스닥 ≥${S.NASDAQ_DIST_UPPER}%)]` +
    `\n  ① 나스닥 필터(강세장전용): ${buy.nasdaqAllowsStrictMomentum ? "✅" : "❌"} (이격도 ${ixicDist.toFixed(1)}%)` +
    `\n  ② 현재가(${fmtP(ind.currentPrice)}) > MA200(${fmtP(ind.ma200)}): ${buy.dCond1 ? "✅" : "❌"}` +
    `\n  ③ +DI(${fn(ind.plusDI, 1)}) > -DI(${fn(ind.minusDI, 1)})${ind.plusDI === null ? " [컬럼 미설정 → 비활성]" : ""}: ${buy.dCond2 ? "✅" : "❌"}` +
    `\n  ④ ADX(${fn(ind.adx, 1)}) > ${S.ADX_MIN}: ${buy.dCond3 ? "✅" : "❌"}` +
    `\n  ⑤ ADX 상승 (당일 ${fn(ind.adx, 1)}, 전일 ${fn(ind.adxD1, 1)} | 조건: 당일 > 전일): ${buy.dCond4 ? "✅" : "❌"}` +
    `\n  ⑥ MACD hist(${fn(ind.macdHist, 4)}) > 0: ${buy.dCond5 ? "✅" : "❌"}` +
    `\n  ⑦ 종가%B(${fn(ind.pctB, 1)}) 범위 ${S.ADX_PCTB_MIN}~${S.ADX_PCTB_MAX}: ${buy.dCond6 ? "✅" : "❌"}` +

    `\n[E그룹: 200일선 상방 & 스퀴즈 저점 (히스테리시스+찐바닥 허용)]` +
    `\n  ① 나스닥 필터(E/F): ${buy.nasdaqAllowsBottomBuy ? "✅" : "❌ 차단"} (이격도 ${ixicDist.toFixed(1)}%)` +
    `\n  ② 현재가(${fmtP(ind.currentPrice)}) > MA200(${fmtP(ind.ma200)}): ${buy.eCond1 ? "✅" : "❌"}` +
    `\n  ③ BB폭(${fn(ind.bbWidth, 2)}) / 60일평균(${fn(ind.bbWidthAvg60, 2)}) | 조건: 비율 < ${S.SQUEEZE_RATIO * 100}%: ${buy.eCond2 ? "✅" : "❌"}` +
    `\n  ④ 저가%B(${fn(ind.pctBLow, 2)}) ≤ ${S.SQUEEZE_PCT_B_MAX}: ${buy.eCond3 ? "✅" : "❌"}` +

    `\n[F그룹: 200일선 상방 & BB 극단 저점 (히스테리시스+찐바닥 허용)]` +
    `\n  ① 나스닥 필터(E/F): ${buy.nasdaqAllowsBottomBuy ? "✅" : "❌ 차단"} (이격도 ${ixicDist.toFixed(1)}%)` +
    `\n  ② 현재가(${fmtP(ind.currentPrice)}) > MA200(${fmtP(ind.ma200)}): ${buy.fCond1 ? "✅" : "❌"}` +
    `\n  ③ 저가%B(${fn(ind.pctBLow, 2)}) ≤ ${S.BB_PCT_B_LOW_MAX}: ${buy.fCond2 ? "✅" : "❌"}` +

    `\n[G그룹: 급락 후 회복장 20일선 눌림 (QQQ ${S.G_QQQ_DIST_MIN}~${S.G_QQQ_DIST_MAX}%)]` +
    `\n  ① 회복장 & QQQ 이격도 범위: ${buy.gCond1 ? "✅" : "❌"} (이격도 ${ixicDist.toFixed(1)}%, 회복장 ${isRecoveryMarket ? "✅" : "❌"})` +
    `\n  ② 현재가(${fmtP(ind.currentPrice)}) > MA200(${fmtP(ind.ma200)}): ${buy.gCond2 ? "✅" : "❌"}` +
    `\n  ③ MA20(${fmtP(buy.gMa20)}) > MA200(${fmtP(ind.ma200)}): ${buy.gCond3 ? "✅" : "❌"}` +
    `\n  ④ 저가(${fmtP(buy.gLow)}) ≤ MA20(${fmtP(buy.gMa20)}): ${buy.gCond4 ? "✅" : "❌"}` +
    `\n  ⑤ 종가(${fmtP(buy.gClose)}) > MA20(${fmtP(buy.gMa20)}): ${buy.gCond5 ? "✅" : "❌"}` +
    `\n  ⑥ 전일 종가 > 전일 MA20: ${buy.gCond6 ? "✅" : "❌"}` +
    `\n  ⑦ MA20 5일 기울기(${buy.gState && buy.gState.ma20Slope5 !== null ? (buy.gState.ma20Slope5 * 100).toFixed(2) + "%" : "-"}) ≥ ${(S.G_MA20_SLOPE5_MIN * 100).toFixed(1)}%: ${buy.gCond7 ? "✅" : "❌"}` +
    `\n  ⑧ RSI(${fn(ind.rsi, 1)}) ${S.G_RSI_MIN}~${S.G_RSI_MAX}: ${buy.gCond8 ? "✅" : "❌"}` +
    `\n  ⑨ 20일 거래량비(${buy.gState && buy.gState.volRatio20 !== null ? Number(buy.gState.volRatio20).toFixed(2) : "-"}) ≤ ${S.G_VOL_RATIO20_MAX}: ${buy.gCond9 ? "✅" : "❌"}` +
    `\n  ⑩ MA200 이격 ≤ ${(S.G_MA200_OVERHEAT_MAX * 100).toFixed(0)}%: ${buy.gCond10 ? "✅" : "❌"}` +

    `\n  → 최종 매수 신호: ${buy.triggered ? `✅ 충족 [${(isHolding ? strategyType : buy.strategyType) || "?"}그룹]` : "❌ 미충족"}${isHolding && ind.opinion === "관망" && buy.entryTriggered !== buy.triggered ? " (신규진입 기준과는 별도 복원 기준 적용)" : ""}` +
    (isHolding
      ? `\n[포지션]\n  상태: 보유 중 (시트의견: ${ind.opinion}, 진입 기준: ${stratLabel})` +
        `\n  진입가: ${fmtP(ind.entryPrice)} | 진입일: ${entryDateStr} | 보유: ${tradingDays}거래일` +
        `\n  현재가: ${fmtP(ind.currentPrice)} | 수익률: ${returnPct}%` +
        `\n  목표가: ${ind.entryPrice > 0 ? fmtP(ind.entryPrice * (1 + activePct)) : "-"} (+${activePct * 100}%) | 서킷가: ${ind.entryPrice > 0 ? fmtP(ind.entryPrice * (1 - activeCircuit)) : "-"} (-${activeCircuit * 100}%)` +
        (isEfStrategy
          ? `\n  MACD Hist: ${fn(ind.macdHist, 4)} / 전일 ${fn(ind.macdHistD1, 4)} / 전전일 ${fn(ind.macdHistD2, 4)} → ${histTurnSignal ? "둔화전환" : "유지"}` +
            `\n  상방 익절 대기: ${upperExitArmDate ? `${Utilities.formatDate(upperExitArmDate, "Asia/Seoul", "yyyy-MM-dd")}부터 ${upperExitWaitDays}거래일 경과 / 최대 ${S.UPPER_EXIT_MAX_WAIT_DAYS}일` : "미시작"}`
          : strategyType === "A" || strategyType === "C"
          ? `\n  [${strategyType}그룹 모멘텀] MACD hist ${fn(ind.macdHist, 4)} (목표 +${activePct * 100}% 즉시 매도)`
          : strategyType === "B"
          ? `\n  [B그룹 공황] VIX ${fmt(vixD)} | RSI ${fn(ind.rsi, 2)} / CCI ${fn(ind.cci, 2)} (목표 +${activePct * 100}% 즉시 매도)`
          : `\n  [D그룹 추세] +DI ${fn(ind.plusDI, 1)} / -DI ${fn(ind.minusDI, 1)} | ADX ${fn(ind.adx, 1)} (목표 +${activePct * 100}% 즉시 매도)`) +
        `\n  → ${exit.shouldExit ? `매도 신호: ${exit.reason}` : "보유 유지"}`
      : `\n[포지션]\n  상태: 미보유` + (sellTime ? `\n  매도 후 경과: ${sellElapsed}` + reentryState : ""))
  );
}

function logResults(changedStocks) {
  if (changedStocks.length === 0) { console.log("\n투자의견 변경이 없습니다."); return; }
  console.log("\n--- 투자의견 업데이트 결과 ---");
  changedStocks.forEach(c => console.log(` 종목: ${c.stock}, 변경: '${c.from}' → '${c.to}' (${c.reason})`));
  console.log("----------------------------");
}
