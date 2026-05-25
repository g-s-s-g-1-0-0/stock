function trackChanges() {
  const startTime = Date.now();
  console.log("========== 투자의견 추적 시작 ==========");

  const { sheet, targetSheet } = Utils.getSheets("기술분석");
  if (!targetSheet) { console.log("[단계1 실패] 스프레드시트 접근 실패"); return; }

  const now = new Date();
  const { kstDate, kstDateOnly, kstHour, kstMinute, estString } = Utils.getTimeDetails(now);
  const props             = PropertiesService.getScriptProperties();
  const allProperties     = props.getProperties();
  const currentGlobalData = Utils.getGlobalData(targetSheet, allProperties);
  allProperties.__IS_RECOVERY_MARKET__ = currentGlobalData.isRecoveryMarket ? "TRUE" : "";
  const Sg                = Utils.STRATEGY;
  const buyBlockMax       = currentGlobalData.nasdaqBuyBlockMax || Sg.NASDAQ_BUY_BLOCK_MAX;
  const buyBlockActive    = Number.isFinite(currentGlobalData.ixicDist) && currentGlobalData.ixicDist > buyBlockMax;
  const lastValues        = Utils.getLastValues();
  let currentValidOpinions = { ...lastValues.lastValidOpinions };

  console.log(
    `[글로벌] 이벤트: "${currentGlobalData.event}", VIX: ${currentGlobalData.vixToday}, QQQ 이격도(현재): ${currentGlobalData.ixicDist.toFixed(2)}%, ` +
    `하락장 필터(A/C/D/E/F/G 차단, 데스존 ${Sg.NASDAQ_DIST_LOWER}%~${Sg.NASDAQ_DIST_UPPER}%): ${currentGlobalData.ixicFilterActive ? "활성" : "비활성"}, ` +
    `상단 매수 차단(신규/재진입만, >${buyBlockMax}%): ${buyBlockActive ? "활성" : "비활성"}, ` +
    `고점 청산/강제매도(${currentGlobalData.nasdaqPeakReason || "국면별 기준"}): ${currentGlobalData.nasdaqPeakAlert ? "활성" : "비활성"}`
  );

  if (Utils.isInitialRun(lastValues, targetSheet, currentGlobalData)) { console.log("[초기 실행 감지] 종료"); return; }

  const currentData   = targetSheet.getRange(3, 1, targetSheet.getLastRow() - 2, targetSheet.getLastColumn()).getValues();
  const trendData     = Utils.getLatestTrendData(targetSheet);
  const industryMap   = Utils.buildIndustryMap(targetSheet);

  const { changes, buyOpinions, watchHoldingOpinions, sellOpinions, updatedOpinions } = processData(
    currentData, currentGlobalData, lastValues.event, currentValidOpinions,
    { kstDate: kstDateOnly, kstHour, kstMinute, now }, allProperties, props
  );

  changes.forEach(c => {
    c.industry   = industryMap[c.ticker] || null;
    c.trendBadge = (c.to === "매수" && c.industry && trendData) ? Utils.buildTrendBadge(c.industry, trendData) : null;
  });

  console.log(`[분석 완료] 변경: ${changes.length}건, 현재 매수 의견: ${buyOpinions.length}개(${buyOpinions.length > 0 ? buyOpinions.join(", ") : "없음"}), 보유 중 관망: ${watchHoldingOpinions.length}개(${watchHoldingOpinions.length > 0 ? watchHoldingOpinions.join(", ") : "없음"}), 현재 매도 의견: ${sellOpinions.length}개(${sellOpinions.length > 0 ? sellOpinions.join(", ") : "없음"})`);
  if (changes.length > 0) {
    const emailSent = Utils.sendEmailAlert(targetSheet.getRange("F1").getValue(), changes, buyOpinions, watchHoldingOpinions, sellOpinions, kstDate, estString, currentGlobalData, trendData);
    if (!emailSent) {
      console.log("[이메일 미발송] lastValues 저장 보류 — 다음 실행에서 동일 변경 재시도");
      throw new Error("투자의견 변경 이메일 발송 실패");
    }
  }

  Utils.saveLastValues(currentData, updatedOpinions, currentGlobalData);
  console.log(`[완료] ${((Date.now() - startTime) / 1000).toFixed(1)}초`);
  console.log("========== 투자의견 추적 종료 ==========");
}

function processData(currentData, currentGlobalData, lastEvent, currentValidOpinions, timeDetails, allProperties, props) {
  const { kstDate, now } = timeDetails;
  const changes          = [];
  const buyOpinions      = [];
  const watchHoldingOpinions = [];
  const sellOpinions     = [];
  const updatedOpinions  = { ...currentValidOpinions };

  currentData.forEach((row) => {
    const C         = Utils.COL_INDICES;
    const stockName = String(row[C.stockName]).trim();
    if (!stockName || row.length < 54) return;

    const currentOpinion = String(row[C.opinion]).trim();
    const displayName    = Utils.getDisplayName(stockName, row);
    if (currentOpinion === "매수") buyOpinions.push(displayName);
    if (currentOpinion === "관망" && Utils.loadEntryInfoFrom(stockName, allProperties).price > 0) watchHoldingOpinions.push(displayName);
    if (currentOpinion === "매도") sellOpinions.push(displayName);

    if (!Utils.toNum(row[C.currentPrice]) || !Utils.toNum(row[C.ma200])) { console.log(`[SKIP] ${displayName} — 데이터 오류`); return; }

    const lastOpinionData = updatedOpinions[stockName] || { opinion: "초기값", reason: "초기값 설정" };
    const lastOpinion     = lastOpinionData.opinion;
    const lastReason      = lastOpinionData.reason;
    const evaluated       = Utils.evaluateOpinion(row, currentGlobalData, now, allProperties);

    if (currentOpinion !== lastOpinion) {
      handleOpinionChange(stockName, lastOpinion, currentOpinion, row, currentGlobalData, lastEvent, kstDate, lastReason, changes, updatedOpinions, now, evaluated.reason, evaluated.strategyType, allProperties, props);
    } else if (Utils.isValidOpinion(currentOpinion)) {
      updatedOpinions[stockName] = { opinion: currentOpinion, reason: Utils.summarizeChangeReason(currentOpinion, currentOpinion, currentGlobalData, lastEvent, row, now, lastReason, allProperties) };
    }

    processMultiSlots(stockName, row, currentGlobalData, now, allProperties, kstDate, changes, props);
  });

  const additionalBuyTickers = {};
  changes.forEach(c => {
    if (c && c.eventType === "additional_buy" && c.ticker) additionalBuyTickers[c.ticker] = true;
  });
  const visibleChanges = changes.filter(c =>
    !(c && c.eventType === "holding_buy_signal" && c.ticker && additionalBuyTickers[c.ticker])
  );

  return { changes: visibleChanges, buyOpinions, watchHoldingOpinions, sellOpinions, updatedOpinions };
}

function processMultiSlots(stockName, row, globalData, now, allProperties, kstDate, changes, props) {
  const C              = Utils.COL_INDICES;
  const S              = Utils.STRATEGY;
  const displayName    = Utils.getDisplayName(stockName, row);
  const currentOpinion = String(row[C.opinion] || "").trim();
  const price          = Number(row[C.currentPrice]) || 0;
  const fmtP           = Utils.fmtPrice(price, stockName);
  if (!price) return;
  if (currentOpinion === "매도") return;

  const dateStr = typeof kstDate === "string" ? kstDate : Utilities.formatDate(kstDate, "Asia/Seoul", "yyyy-MM-dd");

  const stratShortLabel = s =>
      s === "A" ? "A그룹 [모멘텀 재가속]"
    : s === "B" ? "B그룹 [공황 저점]"
    : s === "C" ? "C그룹 [스퀴즈 거래량 돌파]"
    : s === "D" ? "D그룹 [상승 흐름 강화]"
    : s === "E" ? "E그룹 [스퀴즈 저점]"
    : s === "F" ? "F그룹 [BB 극단 저점]"
    :             "G그룹 [회복장 20일선 눌림]";

  const activeSlots = Utils.loadSlots(stockName, allProperties);
  const sellPrice = getUSExtendedSellPrice_(stockName, displayName, price, Utils.isKoreanStock(stockName), activeSlots.length > 0, globalData) || price;
  const sellRow = sellPrice !== price ? row.slice() : row;
  if (sellRow !== row) sellRow[C.currentPrice] = sellPrice;
  const fmtSellP = Utils.fmtPrice(sellPrice, stockName);

  for (const slot of activeSlots) {
    const slotExit = Utils.evaluateSlotExit(sellRow, globalData, now, slot, slot.strategy, allProperties);
    if (!slotExit) continue;

    const slotDateStr = slot.date ? Utilities.formatDate(slot.date, "Asia/Seoul", "yyyy.MM.dd") : "-";
    const returnPct   = ((sellPrice - slot.price) / slot.price * 100).toFixed(2);
    const entryInfo   = `진입가 ${Utils.fmtPrice(slot.price, stockName)} (${slotDateStr}) · 수익률 ${Number(returnPct) >= 0 ? "+" : ""}${returnPct}%`;

    Utils.clearSlot(stockName, slot.id, props);
    props.setProperty(`SLOT_SELL_${stockName}_${slot.strategy}`, `${dateStr}|${price}`);

    const remaining = Utils.loadSlots(stockName, props.getProperties());
    const remainingNote = remaining.length > 0
      ? `\n▪ 잔여 보유: ${remaining.map(s => {
          const sd = s.date ? Utilities.formatDate(s.date instanceof Date ? s.date : Utils.parseDateKST(s.date), "Asia/Seoul", "yyyy.MM.dd") : "-";
          return `${stratShortLabel(s.strategy)} ${Utils.fmtPrice(s.price, stockName)} (${sd})`;
        }).join(", ")}`
      : "";

    changes.push({
      stock: displayName, ticker: stockName,
      from:  currentOpinion,
      to:    "매도",
      reason: `${stratShortLabel(slot.strategy)} ${slotExit.reason}`,
      price: fmtSellP,
      entryNote: entryInfo + remainingNote,
      stopLoss: ""
    });

    Utils.recordSlotSellSignal(stockName, slot.strategy, dateStr, sellPrice);
    console.log(`[슬롯 매도] ${displayName} ${slot.strategy}그룹: ${slotExit.reason}`);
  }

  const primaryEntry = Utils.loadEntryInfoFrom(stockName, allProperties);
  if (!primaryEntry || primaryEntry.price <= 0) return;

  const STRATEGIES = ["A", "B", "C", "D", "E", "F", "G"];

  for (const strategy of STRATEGIES) {
    const liveProps  = props.getProperties();
    const liveSlots  = Utils.loadSlots(stockName, liveProps);
    const sameStrategySlotCount = liveSlots.filter(s => s.strategy === strategy).length;
    const primarySameStrategyCount = primaryEntry.price > 0 && primaryEntry.strategyType === strategy ? 1 : 0;
    if (sameStrategySlotCount + primarySameStrategyCount >= S.MAX_OPEN_PER_STRATEGY) {
      console.log(`[슬롯 진입 건너뜀] ${displayName} ${strategy}그룹: 동일 전략 최대 슬롯 수(${S.MAX_OPEN_PER_STRATEGY}) 도달`);
      continue;
    }

    const canEnter = Utils.evaluateSlotEntry(row, globalData, strategy, stockName, allProperties);
    if (!canEnter) continue;

    const mergedProps = { ...allProperties, ...liveProps };
    const restoreState = Utils.getHoldRestoreState(stockName, price, now, mergedProps);
    if (!restoreState.allowed) {
      console.log(`[슬롯 진입 보류] ${displayName} ${strategy}그룹: ${Utils.buildHoldRestorePendingReason(stockName, price, now, mergedProps, strategy)}`);
      continue;
    }

    const slotSellVal = liveProps[`SLOT_SELL_${stockName}_${strategy}`] || allProperties[`SLOT_SELL_${stockName}_${strategy}`];
    if (slotSellVal) {
      const sellTime      = Utils.parseDateKST(slotSellVal.split("|")[0]);
      const sellPrice     = Number(slotSellVal.split("|")[1]) || 0;
      const elapsedHours  = sellTime ? (now - sellTime) / (1000 * 60 * 60) : S.SELL_HOLD_HOURS + 1;
      const daysSinceSell = Utils.calcTradingDays(sellTime, now);
      if (elapsedHours < S.SELL_HOLD_HOURS) {
        console.log(`[슬롯 진입 보류] ${displayName} ${strategy}그룹: 매도 후 ${elapsedHours.toFixed(1)}h 대기중`);
        continue;
      }
      if (daysSinceSell <= S.REENTRY_DAYS && !(sellPrice > 0 && price <= sellPrice * (1 - S.REENTRY_DROP))) {
        console.log(`[슬롯 진입 보류] ${displayName} ${strategy}그룹: 재진입 필터`);
        continue;
      }
    }

    const prevCount  = parseInt(liveProps[`REENTRY_COUNT_${stockName}`] || allProperties[`REENTRY_COUNT_${stockName}`] || "0");
    const newCount   = prevCount + 1;
    const cyclePrice = parseFloat(liveProps[`CYCLE_ENTRY_${stockName}`] || allProperties[`CYCLE_ENTRY_${stockName}`] || "0") || primaryEntry.price;
    props.setProperty(`REENTRY_COUNT_${stockName}`, String(newCount));

    const label     = strategyDisplayName(strategy);
    const reason    = Utils.buildSlotBuyReason(strategy, row, globalData);
    const entryNote = cyclePrice > 0
      ? `재진입 ${newCount}회차 — 최초 진입가 ${Utils.fmtPrice(cyclePrice, stockName)}`
      : `재진입 ${newCount}회차`;

    changes.push({
      stock: displayName, ticker: stockName,
      from:  currentOpinion,
      to:    "매수",
      fromLabel: "매수(보유중)",
      toLabel: "추가 매수",
      eventType: "additional_buy",
      reason, price: fmtP, entryNote, stopLoss: ""
    });

    Utils.saveSlot(stockName, strategy, price, dateStr, props);
    Utils.recordBuySignal(stockName, dateStr, price, label);
    console.log(`[슬롯 매수] ${displayName} ${strategy}그룹 재진입 ${newCount}회차: ${reason}`);
  }
}

function handleOpinionChange(stockName, fromOpinion, toOpinion, row, currentGlobalData, lastEvent, kstDate, lastReason, changes, updatedOpinions, now, evaluatedReason, evaluatedStrategyType, allProperties, props) {
  const isCooldownMsg = r => typeof r === "string" && r.indexOf("매도 유지") !== -1 && (r.indexOf("48시간") !== -1 || r.indexOf("재진입 필터") !== -1 || r.indexOf("쿨다운") !== -1);
  const isReentryMsg  = r => typeof r === "string" && r.indexOf("재진입 조건 충족") !== -1;
  const C             = Utils.COL_INDICES;
  const entryStrategyCode = String(row[C.entryStrategy] || "").trim().charAt(0).toUpperCase();
  const buyStrategyHint = toOpinion === "매수"
    ? (evaluatedStrategyType || (/^[A-G]$/.test(entryStrategyCode) ? entryStrategyCode : null))
    : null;

  let reason;
  if (toOpinion === "매도") {
    const savedExitReason = allProperties[`EXIT_REASON_${stockName}`] || null;
    reason = (savedExitReason)
      ? savedExitReason
      : (evaluatedReason && !isCooldownMsg(evaluatedReason) && !isReentryMsg(evaluatedReason))
      ? evaluatedReason
      : Utils.summarizeChangeReason(fromOpinion, toOpinion, currentGlobalData, lastEvent, row, now, lastReason, allProperties);
  } else if (fromOpinion === "초기값" && toOpinion === "매수") {
    reason = Utils.summarizeChangeReason("관망", "매수", currentGlobalData, lastEvent, row, now, lastReason, allProperties, buyStrategyHint);
  } else {
    reason = Utils.summarizeChangeReason(fromOpinion, toOpinion, currentGlobalData, lastEvent, row, now, lastReason, allProperties, buyStrategyHint);
  }

  const sheetPrice  = Number(row[C.currentPrice]) || 0;
  const savedSellPrice = toOpinion === "매도" ? Utils.loadSellPriceFrom(stockName, allProperties) : 0;
  const price       = savedSellPrice > 0 ? savedSellPrice : sheetPrice;
  const fmtP        = Utils.fmtPrice(price, stockName);
  const displayName = Utils.getDisplayName(stockName, row);
  const existingEntry = Utils.loadEntryInfoFrom(stockName, allProperties);
  const hasRestoreWatch = !!(allProperties[`HOLD_WATCH_${stockName}`] || allProperties[`A_HOLD_WATCH_${stockName}`]);
  const isHoldingRestore = toOpinion === "매수" && fromOpinion === "관망" && existingEntry.price > 0 && hasRestoreWatch;
  let entryNote     = null;
  let fromLabel     = null;
  let toLabel       = null;
  let eventType     = null;

  if (toOpinion === "매수") {
    props.deleteProperty(`UPPER_EXIT_ARM_${stockName}`);
    if (isHoldingRestore) {
      const prevCount  = parseInt(allProperties[`REENTRY_COUNT_${stockName}`] || "0");
      const newCount   = prevCount + 1;
      const cyclePrice = parseFloat(allProperties[`CYCLE_ENTRY_${stockName}`] || "0") || existingEntry.price || price;
      entryNote = cyclePrice > 0
        ? `재진입 ${newCount}회차 — 최초 진입가 ${Utils.fmtPrice(cyclePrice, stockName)}`
        : `재진입 ${newCount}회차`;
      fromLabel = "매수(보유중)";
      toLabel = "추가 매수";
      eventType = "holding_buy_signal";
      console.log(`[진입 구분] ${displayName}: ${entryNote}`);
    } else {
      const hasOpenPosition = existingEntry.price > 0 || Utils.loadSlots(stockName, allProperties).length > 0;
      const isNewTrade = !hasOpenPosition;
      if (isNewTrade) {
        entryNote = "신규 진입";
        props.setProperty(`REENTRY_COUNT_${stockName}`, "0");
        props.setProperty(`CYCLE_ENTRY_${stockName}`, String(price));
        console.log(`[진입 구분] ${displayName}: 신규 진입 (가격: ${fmtP})`);
      } else {
        const prevCount  = parseInt(allProperties[`REENTRY_COUNT_${stockName}`] || "0");
        const newCount   = prevCount + 1;
        const cyclePrice = parseFloat(allProperties[`CYCLE_ENTRY_${stockName}`] || "0") || price;
        if (!allProperties[`CYCLE_ENTRY_${stockName}`] && cyclePrice > 0) props.setProperty(`CYCLE_ENTRY_${stockName}`, String(cyclePrice));
        props.setProperty(`REENTRY_COUNT_${stockName}`, String(newCount));
        entryNote = cyclePrice > 0
          ? `재진입 ${newCount}회차 — 최초 진입가 ${Utils.fmtPrice(cyclePrice, stockName)}`
          : `재진입 ${newCount}회차`;
        console.log(`[진입 구분] ${displayName}: ${entryNote}`);
      }
    }
  }

  if (toOpinion === "매도") {
    props.deleteProperty(`UPPER_EXIT_ARM_${stockName}`);
    const saved = Utils.loadEntryInfoFrom(stockName, allProperties);
    if (saved.price > 0) {
      const entryDateStr = saved.date ? Utilities.formatDate(new Date(saved.date), "Asia/Seoul", "yyyy.MM.dd") : "-";
      const returnPct    = ((price - saved.price) / saved.price * 100).toFixed(2);
      entryNote = `진입가 ${Utils.fmtPrice(saved.price, stockName)} (${entryDateStr}) · 수익률 ${Number(returnPct) >= 0 ? "+" : ""}${returnPct}%`;
    }
    const isPeakSell = typeof reason === "string" && reason.indexOf("고점 청산/강제매도") !== -1;
    const keepPeakStrategies = isPeakSell ? ["A", "C", "E", "F"] : null;
    Utils.clearAllSlotStateForStock(stockName, price, kstDate, props, allProperties, { keepStrategies: keepPeakStrategies });
  }

  changes.push({ stock: displayName, ticker: stockName, from: fromOpinion, to: toOpinion, fromLabel, toLabel, eventType, reason, price: fmtP, entryNote, stopLoss: "" });

  if (toOpinion === "매수" && fromOpinion !== "매수") {
    // 관망 상태도 포지션 보유 중 → 다른 전략 신호 충돌 감지 대상에 포함
    const hasConflictingPrimary = (fromOpinion === "매수" || fromOpinion === "관망")
      && existingEntry.price > 0
      && existingEntry.strategyType
      && evaluatedStrategyType                                // 새 전략이 확정된 경우에만 충돌로 판단
      && existingEntry.strategyType !== evaluatedStrategyType;

    if (hasConflictingPrimary) {
      console.log(`[멀티슬롯 위임] ${displayName}: 기존 ${existingEntry.strategyType}그룹 PRIMARY 보유 중 (${fromOpinion} 상태) → ${evaluatedStrategyType}그룹 신호는 processMultiSlots에 위임 (ENTRY_ 덮어쓰기 방지)`);
    } else if (isHoldingRestore) {
      console.log(`[트레이딩로그 위임] ${displayName}: 기존 보유 포지션의 관망→매수 신호 — 추가 슬롯 로깅은 processMultiSlots에서 처리`);
    } else {
      // 전략 타입 결정 우선순위: evaluatedStrategyType → ENTRY_ 키 → 시트 BC열
      // "F" 기본값 제거: 타이밍 차이로 evaluatedStrategyType이 null이더라도 기존 보유 전략 사용
      let resolvedBuyStrategy = evaluatedStrategyType;
      if (!resolvedBuyStrategy && existingEntry.price > 0 && existingEntry.strategyType) {
        resolvedBuyStrategy = existingEntry.strategyType;
        console.log(`[전략 보완] ${displayName}: evaluatedStrategyType 미결정 → ENTRY_ 키 전략 "${resolvedBuyStrategy}" 사용`);
      }
      if (!resolvedBuyStrategy) {
        const sheetStratStr = String(row[Utils.COL_INDICES.entryStrategy] || "").trim();
        if (sheetStratStr) {
          resolvedBuyStrategy = sheetStratStr.charAt(0).toUpperCase();
          console.log(`[전략 보완] ${displayName}: ENTRY_ 키 없음 → 시트 BC열 전략 "${resolvedBuyStrategy}" 사용`);
        }
      }
      if (!resolvedBuyStrategy) {
        console.log(`[경고] ${displayName}: 매수 신호 기록 시 전략 타입 미결정 — 레이블 없이 기록`);
      }
      Utils.recordBuySignal(stockName, kstDate, price, resolvedBuyStrategy ? strategyDisplayName(resolvedBuyStrategy) : "");
    }
  }
  if (toOpinion === "매도" && fromOpinion !== "매도") {
    const isBulkSell = typeof reason === "string" && reason.indexOf("나스닥 고점 경고") !== -1;
    let resolvedSellStrategy = existingEntry.strategyType;
    if (!resolvedSellStrategy) {
      const sheetStratStr = String(row[Utils.COL_INDICES.entryStrategy] || "").trim();
      if (sheetStratStr) {
        resolvedSellStrategy = sheetStratStr.charAt(0).toUpperCase();
      }
    }

    if (isBulkSell) {
      Utils.recordAllOpenSellSignals(stockName, kstDate, price);
    } else {
      if (!resolvedSellStrategy) {
        console.log(`[경고] ${displayName}: 매도 신호 기록 시 전략 타입 미결정 — 레이블 없이 기록`);
      }
      Utils.recordSellSignal(
        stockName,
        kstDate,
        price,
        resolvedSellStrategy ? strategyDisplayName(resolvedSellStrategy) : ""
      );
    }
  }

  updatedOpinions[stockName] = { opinion: toOpinion, reason: Utils.summarizeChangeReason(toOpinion, toOpinion, currentGlobalData, lastEvent, row, now, reason, allProperties) };
}

var NASDAQ_PEAK_SIGNAL_CONFIG = {
  currentPriceCell: "W1",
  vixTodayCell: "O1",
  vixYesterdayCell: "Q1",
  ma200Cell: "AE1",
  weeklyRsiCell: "AS1",
  dailyRsiCell: "AU1",
  dailyRsiPrevCell: "AW1",
  recentMinPremiumCell: "AY1",
  macdHistCell: "P26",
  macdHistD1Cell: "Q26",
  macdHistD2Cell: "R26",
  normalBuyBlockMax: 9,
  recoveryBuyBlockMax: 18,
  lookbackDays: 60,
  recoveryMinDist: -5,
  normalPeakDirectDist: 16,
  normalPeakConfirmDist: 14,
  recoveryPeakDirectDist: 22,
  recoveryPeakConfirmDist: 18,
  rsiThreshold: 65,
  stateKey: "NasdaqPeakSellState",
  dailyReachedKey: "NasdaqPeakReachedToday",
  lastResetDateKey: "NasdaqPeakLastResetDate",
  premiumHistoryKey: "NasdaqPremiumHistory",
  latestRecentMinKey: "NasdaqRecent60MinPremium"
};

function getNasdaqPremiumHistory_(cached, props, cfg) {
  const raw = (cached && cached[cfg.premiumHistoryKey]) || props.getProperty(cfg.premiumHistoryKey) || "[]";
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(row => row && typeof row.date === "string" && Number.isFinite(Number(row.dist))) : [];
  } catch (e) {
    return [];
  }
}

function updateNasdaqPremiumHistory_(props, cfg, kstDateOnly, premiumPercent) {
  const history = getNasdaqPremiumHistory_(props.getProperties(), props, cfg)
    .filter(row => row.date !== kstDateOnly);
  history.push({ date: kstDateOnly, dist: premiumPercent });
  const trimmed = history.slice(-(cfg.lookbackDays || 60));
  props.setProperty(cfg.premiumHistoryKey, JSON.stringify(trimmed));
  return trimmed;
}

function buildNasdaqMarketState_(premiumPercent, history, cfg, recentMinOverride) {
  const recentValues = history.map(row => Number(row.dist)).filter(v => Number.isFinite(v));
  if (Number.isFinite(premiumPercent)) recentValues.push(premiumPercent);
  const historyMinDist = recentValues.length ? Math.min.apply(null, recentValues.slice(-(cfg.lookbackDays || 60))) : null;
  let recentMinDist = Number.isFinite(Number(recentMinOverride)) ? Number(recentMinOverride) : historyMinDist;
  if (Number.isFinite(premiumPercent) && recentMinDist !== null) {
    recentMinDist = Math.min(recentMinDist, premiumPercent);
  }
  const isRecoveryMarket = recentMinDist !== null && recentMinDist <= cfg.recoveryMinDist && premiumPercent >= 0;
  const buyBlockMax = isRecoveryMarket ? cfg.recoveryBuyBlockMax : cfg.normalBuyBlockMax;
  return {
    recent60MinPremiumPercent: recentMinDist,
    isRecoveryMarket,
    regimeLabel: isRecoveryMarket ? "급락 후 회복장" : "비회복장/고점 횡보장",
    buyBlockMax,
    peakDirectDist: isRecoveryMarket ? cfg.recoveryPeakDirectDist : cfg.normalPeakDirectDist,
    peakConfirmDist: isRecoveryMarket ? cfg.recoveryPeakConfirmDist : cfg.normalPeakConfirmDist
  };
}

function getNasdaqBuyBlockMax_(ixicDist, allProperties) {
  const cfg = NASDAQ_PEAK_SIGNAL_CONFIG;
  const props = PropertiesService.getScriptProperties();
  const history = getNasdaqPremiumHistory_(allProperties, props, cfg);
  const recentMinFromProps = Number((allProperties && allProperties[cfg.latestRecentMinKey]) || props.getProperty(cfg.latestRecentMinKey));
  return buildNasdaqMarketState_(ixicDist, history, cfg, recentMinFromProps).buyBlockMax;
}

function readOptionalNumberCell_(sheet, cellRef) {
  if (!cellRef) return null;
  const value = Number(sheet.getRange(cellRef).getValue());
  return Number.isFinite(value) && value !== 0 ? value : null;
}

function readNumberCell_(sheet, cellRef) {
  if (!cellRef) return null;
  const raw = sheet.getRange(cellRef).getValue();
  if (raw === "" || raw === null || raw === undefined) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

/**
 * AY1 셀에서 쓰는 회복장 판정용 QQQ 최근 60거래일 최저 MA200 이격도.
 * 시트에는 =getQQQRecent60MinPremium() 형태로 넣으면 된다.
 *
 * @customfunction
 */
function getQQQRecent60MinPremium(lookbackDays) {
  const lookback = Number(lookbackDays) > 0 ? Number(lookbackDays) : 60;
  try {
    const closes = typeof _fetchUSChartCloses === "function"
      ? _fetchUSChartCloses("QQQ", "2y", "1d", "US_QQQ_RECENT_MA200_MIN")
      : fetchQQQClosesForRecentMin_("QQQ", "2y", "1d");
    const valid = closes.filter(v => Number.isFinite(Number(v))).map(Number);
    const distances = [];
    for (let i = 199; i < valid.length; i++) {
      const ma200 = valid.slice(i - 199, i + 1).reduce((a, b) => a + b, 0) / 200;
      if (ma200 > 0) {
        distances.push((valid[i] / ma200 - 1) * 100);
      }
    }
    if (distances.length === 0) return "데이터 부족";
    const recent = distances.slice(-lookback);
    const minDist = Math.min.apply(null, recent);
    return Math.round(minDist * 100) / 100;
  } catch (e) {
    return "오류";
  }
}

function fetchQQQClosesForRecentMin_(symbol, range, interval) {
  const url = "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol +
    "?range=" + range + "&interval=" + interval;
  const response = UrlFetchApp.fetch(url, {
    muteHttpExceptions: true,
    headers: {
      "User-Agent": "Mozilla/5.0",
      "Accept": "application/json",
      "Cache-Control": "no-cache"
    }
  });
  const data = JSON.parse(response.getContentText());
  const result = ((((data || {}).chart || {}).result || [])[0] || {});
  const quote = ((result.indicators || {}).quote || [])[0] || {};
  return quote.close || [];
}

function getNasdaqPeakSignalState_(targetSheet, allProperties) {
  const cfg = NASDAQ_PEAK_SIGNAL_CONFIG;
  const props = PropertiesService.getScriptProperties();
  const now = new Date();
  const kstDateOnly = Utilities.formatDate(now, "Asia/Seoul", "yyyy-MM-dd");

  const cached = allProperties || props.getProperties();
  const lastResetDate = cached[cfg.lastResetDateKey] || props.getProperty(cfg.lastResetDateKey);
  if (lastResetDate !== kstDateOnly) {
    props.setProperty(cfg.dailyReachedKey, "FALSE");
    props.setProperty(cfg.lastResetDateKey, kstDateOnly);
  }

  const currentPrice = Number(targetSheet.getRange(cfg.currentPriceCell).getValue()) || 0;
  const vixToday = Number(targetSheet.getRange(cfg.vixTodayCell).getValue()) || 0;
  const vixYesterday = Number(targetSheet.getRange(cfg.vixYesterdayCell).getValue()) || 0;
  const nasdaqMA200 = Number(targetSheet.getRange(cfg.ma200Cell).getValue()) || 0;
  const qqqWeeklyRsi = Number(targetSheet.getRange(cfg.weeklyRsiCell).getValue()) || 0;
  const qqqDailyRsi = Number(targetSheet.getRange(cfg.dailyRsiCell).getValue()) || 0;
  const qqqDailyRsiPrev = Number(targetSheet.getRange(cfg.dailyRsiPrevCell).getValue()) || 0;
  const recentMinPremiumFromCell = readNumberCell_(targetSheet, cfg.recentMinPremiumCell);
  const qqqMacdHist = readOptionalNumberCell_(targetSheet, cfg.macdHistCell);
  const qqqMacdHistD1 = readOptionalNumberCell_(targetSheet, cfg.macdHistD1Cell);
  const qqqMacdHistD2 = readOptionalNumberCell_(targetSheet, cfg.macdHistD2Cell);

  if (!(currentPrice > 0) || !(nasdaqMA200 > 0) ||
      !(qqqWeeklyRsi > 0) || !(qqqDailyRsi > 0) || !(qqqDailyRsiPrev > 0)) {
    props.setProperty(cfg.stateKey, "FALSE");
    return {
      nasdaqPeakAlert: false,
      currentPrice,
      nasdaqMA200,
      thresholdPrice: 0,
      premiumPercent: 0,
      vixToday,
      vixYesterday,
      vixChangePercent: 0,
      qqqWeeklyRsi,
      qqqDailyRsi,
      qqqDailyRsiPrev,
      isPeakReachedToday: false,
      isVixConditionMet: false,
      isRsiConditionMet: false,
      isRecoveryMarket: false,
      buyBlockMax: cfg.normalBuyBlockMax,
      peakDirectDist: cfg.normalPeakDirectDist,
      peakConfirmDist: cfg.normalPeakConfirmDist,
      peakReason: "데이터 부족"
    };
  }

  const premiumPercent = (currentPrice / nasdaqMA200 - 1) * 100;
  const history = updateNasdaqPremiumHistory_(props, cfg, kstDateOnly, premiumPercent);
  const marketState = buildNasdaqMarketState_(premiumPercent, history, cfg, recentMinPremiumFromCell);
  if (Number.isFinite(Number(marketState.recent60MinPremiumPercent))) {
    props.setProperty(cfg.latestRecentMinKey, String(marketState.recent60MinPremiumPercent));
  }
  const vixChangePercent = vixYesterday !== 0 ? ((vixToday / vixYesterday - 1) * 100) : 0;
  const isRsiConditionMet =
    qqqWeeklyRsi >= cfg.rsiThreshold &&
    qqqDailyRsi >= cfg.rsiThreshold &&
    qqqDailyRsi < qqqDailyRsiPrev;
  const isMacdSlowing =
    qqqMacdHist !== null && qqqMacdHistD1 !== null && qqqMacdHistD2 !== null &&
    qqqMacdHist < qqqMacdHistD1 && qqqMacdHistD1 < qqqMacdHistD2;

  let peakReachedToday = (cached[cfg.dailyReachedKey] || props.getProperty(cfg.dailyReachedKey)) === "TRUE";
  if (premiumPercent > marketState.peakDirectDist && !peakReachedToday) {
    props.setProperty(cfg.dailyReachedKey, "TRUE");
    peakReachedToday = true;
  }

  const isPeakTriggered = marketState.isRecoveryMarket
    ? premiumPercent > marketState.peakDirectDist
    : (
      isRsiConditionMet &&
      (
        premiumPercent > marketState.peakDirectDist ||
        (premiumPercent > marketState.peakConfirmDist && isMacdSlowing)
      )
    );
  if (isPeakTriggered) {
    props.setProperty(cfg.stateKey, "TRUE");
  } else if (premiumPercent <= (marketState.isRecoveryMarket ? marketState.peakDirectDist : marketState.peakConfirmDist)) {
    props.setProperty(cfg.stateKey, "FALSE");
  }

  return {
    nasdaqPeakAlert: props.getProperty(cfg.stateKey) === "TRUE",
    currentPrice,
    nasdaqMA200,
    thresholdPrice: nasdaqMA200 * (1 + marketState.peakConfirmDist / 100),
    premiumPercent,
    vixToday,
    vixYesterday,
    vixChangePercent,
    qqqWeeklyRsi,
    qqqDailyRsi,
    qqqDailyRsiPrev,
    qqqMacdHist,
    qqqMacdHistD1,
    qqqMacdHistD2,
    isPeakReachedToday: peakReachedToday,
    isVixConditionMet: false,
    isRsiConditionMet,
    isMacdSlowing,
    recent60MinPremiumPercent: marketState.recent60MinPremiumPercent,
    isRecoveryMarket: marketState.isRecoveryMarket,
    regimeLabel: marketState.regimeLabel,
    buyBlockMax: marketState.buyBlockMax,
    peakDirectDist: marketState.peakDirectDist,
    peakConfirmDist: marketState.peakConfirmDist,
    peakReason: marketState.isRecoveryMarket
      ? `회복장: >${marketState.peakDirectDist}%`
      : `비회복장: >${marketState.peakDirectDist}%+RSI하락 또는 >${marketState.peakConfirmDist}%+RSI하락+MACD둔화`
  };
}

const Utils = {

  _tradingLogSheetCache: null,
  _tradingLogSheetCacheId: null,
  _nextTradingLogRowCache: null,

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
    entryPrice:   52,
    entryDate:    53,
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
    STALLED_EXIT_DAYS: 15,
    STALLED_EXIT_MIN_RETURN: 0.08,
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
    UPPER_EXIT_MAX_WAIT_DAYS:       5,
    HOLD_RESTORE_DROP:              0.10,
    HOLD_RESTORE_MIN_TRADING_DAYS:  10,
    MAX_OPEN_PER_STRATEGY:          2
  },

  /** 시장트렌드 순위 키워드 ↔ 가치분석 산업 토큰 연결 (완전일치 외 보강용) */
  TREND_SYNONYM_GROUPS: [
    ["2차전지", "이차전지", "2차 전지", "이차 전지", "리튬이온", "리튬배터리", "전기차", "모빌리티"],
    ["배터리", "배터리소재", "전고체", "ESS"],
    ["양극재", "NCM", "NCA", "LFP", "전고체"],
    ["데이터센터", "데이터 센터", "IDC", "콜로케이션"],
    ["AI인프라", "AI 인프라", "인공지능인프라", "고속인터커넥트", "인터커넥트"],
    ["반도체", "시스템반도체", "비메모리", "메모리반도체", "메모리", "파운드리", "팹리스", "반도체산업"],
    ["후공정", "패키징", "테스트", "EMS", "어드밴스드패키징", "Advanced Packaging", "CoWoS", "패키지"],
    ["바이오", "제약", "바이오테크"],
    ["원전", "원자력", "SMR"],
    ["방산", "국방", "항공우주"],
    ["금융", "은행", "증권", "보험", "캐피탈"],
    ["엔터테인먼트", "미디어", "게임"]
  ],

  /** 산업/트렌드 매칭에서 단독으로 쓰면 오탐이 잦은 일반 토큰 */
  TREND_GENERIC_TOKENS: ["인프라", "플랫폼", "서비스", "시스템", "솔루션", "네트워크"],

  _normTrendToken(s) {
    const t = String(s || "").trim().replace(/^[(\[\s]+|[)\]\s]+$/g, "");
    if (/^[A-Za-z0-9.\-\s]+$/.test(t)) return t.replace(/\s+/g, "").toLowerCase();
    return t.replace(/\s+/g, "");
  },

  _isGenericTrendToken(token) {
    const base = Utils._normTrendToken(token);
    return Utils.TREND_GENERIC_TOKENS.some(t => Utils._normTrendToken(t) === base);
  },

  _expandSynonymTokens(token) {
    const raw = String(token || "").trim();
    if (!raw) return [];
    const base = Utils._normTrendToken(raw);
    const out  = new Set([raw, base]);
    for (const g of Utils.TREND_SYNONYM_GROUPS) {
      const hit = g.some(m => Utils._normTrendToken(m) === base || m === raw);
      if (!hit) continue;
      g.forEach(m => {
        out.add(m);
        out.add(Utils._normTrendToken(m));
      });
    }
    return [...out];
  },

  /** 동의어 확장 후 완전 일치만 허용 (일반 토큰/부분문자열 오탐 방지) */
  _trendTokensMatch(ik, tk) {
    const iList = Utils._expandSynonymTokens(ik);
    const tList = Utils._expandSynonymTokens(tk);
    for (const a of iList) {
      for (const b of tList) {
        const na = Utils._normTrendToken(a);
        const nb = Utils._normTrendToken(b);
        if (na.length < 2 || nb.length < 2) continue;
        if (Utils._isGenericTrendToken(na) || Utils._isGenericTrendToken(nb)) continue;
        if (na === nb) return true;
      }
    }
    return false;
  },

  parseDateKST(str) {
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
  },

  saveUpperExitArm(stockName, date) {
    const value = Utilities.formatDate(date, "Asia/Seoul", "yyyy-MM-dd'T'HH:mm:ss") + "+09:00";
    PropertiesService.getScriptProperties().setProperty(`UPPER_EXIT_ARM_${stockName}`, value);
  },

  loadUpperExitArmFrom(stockName, allProperties) {
    const value = allProperties && allProperties[`UPPER_EXIT_ARM_${stockName}`];
    return value ? Utils.parseDateKST(value) : null;
  },

  clearUpperExitArm(stockName) {
    PropertiesService.getScriptProperties().deleteProperty(`UPPER_EXIT_ARM_${stockName}`);
  },

  getDisplayName(stockName, row) {
    if (!Utils.isKoreanStock(stockName)) return stockName;
    const krName = String(row[Utils.COL_INDICES.stockLabel] || "").trim();
    return krName ? `${krName}(${stockName})` : stockName;
  },

  fmtPrice(v, stockName) {
    const isKR = /[ㄱ-ㅎ가-힣]/.test(stockName || "") || /^\d{6}$/.test(String(stockName || "").trim());
    return isKR ? "₩" + Math.round(Number(v)).toLocaleString("ko-KR") : "$" + Number(v).toFixed(2);
  },

  getTradingLogPriceValue(v, stockName) {
    const num = Number(v) || 0;
    return Utils.isKoreanStock(stockName) ? Math.round(num) : Number(num.toFixed(2));
  },

  parseTradingLogPriceInput(v) {
    if (v === null || v === undefined || v === "") return null;
    if (typeof v === "number") return isNaN(v) ? null : v;

    const normalized = String(v).trim().replace(/[₩$,]/g, "").replace(/,/g, "");
    if (!normalized) return null;

    const num = Number(normalized);
    return isNaN(num) ? null : num;
  },

  getTradingLogPriceFormat(stockName) {
    return Utils.isKoreanStock(stockName) ? '"₩"#,##0' : '"$"#,##0.00';
  },

  setTradingLogPriceCell(cell, stockName, price) {
    const logPrice = Utils.getTradingLogPriceValue(price, stockName);
    cell.setValue(logPrice);
    cell.setNumberFormat(Utils.getTradingLogPriceFormat(stockName));
    return logPrice;
  },

  normalizeTradingLogPriceCell(cell, stockName, rawValue) {
    const parsed = Utils.parseTradingLogPriceInput(rawValue);
    if (parsed === null) return false;
    Utils.setTradingLogPriceCell(cell, stockName, parsed);
    return true;
  },

  fmtNumOrDash(v, decimals) {
    if (v === null || v === undefined || isNaN(v)) return "-";
    return Number(v).toFixed(decimals !== undefined ? decimals : 2);
  },

  isKoreanStock(stockName) {
    return /^\d{6}$/.test(String(stockName || "").trim());
  },

  getTimeDetails(now) {
    return {
      kstDate:     Utilities.formatDate(now, "Asia/Seoul", "yyyy. MM. dd, HH:mm:ss"),
      kstDateOnly: Utilities.formatDate(now, "Asia/Seoul", "yyyy-MM-dd"),
      kstHour:     Number(Utilities.formatDate(now, "Asia/Seoul", "HH")),
      kstMinute:   Number(Utilities.formatDate(now, "Asia/Seoul", "mm")),
      estString:   Utilities.formatDate(now, "America/New_York", "M/d/yyyy, h:mm:ss a")
    };
  },

  isDST(date = new Date()) {
    const year                = date.getFullYear();
    const marchSecondSunday   = new Date(year, 2, 14 - new Date(year, 2, 1).getDay());
    const novemberFirstSunday = new Date(year, 10, 7 - new Date(year, 10, 1).getDay());
    return date.getTime() >= marchSecondSunday.getTime() && date.getTime() < novemberFirstSunday.getTime();
  },

  checkMarketOpen(now, isKR = false) {
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
  },

  getSheets(sheetName) {
    const spreadsheet   = SpreadsheetApp.getActiveSpreadsheet();
    const sheet         = spreadsheet.getSheetByName(sheetName);
    const spreadsheetId = sheet.getRange("I1").getValue();
    try {
      const targetSpreadsheet = SpreadsheetApp.openById(spreadsheetId);
      return { sheet, targetSheet: targetSpreadsheet.getSheetByName(sheetName) };
    } catch (e) {
      console.log(`FATAL: 스프레드시트 접근 실패 (${spreadsheetId}). 오류: ${e}`);
      return { sheet, targetSheet: null };
    }
  },

  getGlobalData(targetSheet, allProperties) {
    const event     = String(targetSheet.getRange("M1").getValue()).trim() || "당분간 없음";
    const vixToday  = Number(targetSheet.getRange("O1").getValue()) || 0;
    const ixicPrice = Number(targetSheet.getRange("W1").getValue()) || 0;
    const ixicMa60  = Number(targetSheet.getRange("AA1").getValue()) || 0;
    const ixicMa200 = Number(targetSheet.getRange("AE1").getValue()) || 0;
    const us10y     = Number(targetSheet.getRange("AO1").getValue()) || 0;
    const dxy       = Number(targetSheet.getRange("AQ1").getValue()) || 0;
    const ixicDist  = (ixicPrice > 0 && ixicMa200 > 0) ? (ixicPrice / ixicMa200 - 1) * 100 : 100;
    const ixicFilterActive = typeof computeNasdaqABFilterActive === "function"
      ? computeNasdaqABFilterActive(ixicDist)
      : ixicDist < Utils.STRATEGY.NASDAQ_DIST_UPPER && ixicDist > Utils.STRATEGY.NASDAQ_DIST_LOWER;
    const peakState = getNasdaqPeakSignalState_(targetSheet, allProperties);
    const nasdaqPeakAlert = peakState.nasdaqPeakAlert;
    const nasdaqBuyBlockMax = peakState.buyBlockMax || Utils.STRATEGY.NASDAQ_BUY_BLOCK_MAX;
    const macroRisk = {
      highRate:     us10y >= 4.2,
      strongDollar: dxy >= 103,
      highVix:      vixToday >= 20,
      techWeak:     ixicPrice > 0 && ixicMa60 > 0 ? ixicPrice < ixicMa60 : false
    };
    return {
      vixToday, event, ixicPrice, ixicMa60, ixicDist, ixicFilterActive, nasdaqPeakAlert,
      nasdaqBuyBlockMax,
      nasdaqPeakReason: peakState.peakReason,
      isRecoveryMarket: !!peakState.isRecoveryMarket,
      qqqRegimeLabel: peakState.regimeLabel,
      us10y, dxy, macroRisk
    };
  },

  buildMacroContextHtml(globalData) {
    if (!globalData) return "";

    const fmtPct = v => (v === null || v === undefined || isNaN(v))
      ? "데이터 없음"
      : `${Number(v).toFixed(2)}%`;
    const fmtIdx = v => (v === null || v === undefined || isNaN(v))
      ? "데이터 없음"
      : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const fmtVix = v => (v === null || v === undefined || isNaN(v) || v === 0)
      ? "데이터 없음"
      : Number(v).toFixed(2);

    const hasNasdaqData = Number(globalData.ixicPrice) > 0 && Number(globalData.ixicMa60) > 0;
    const nasdaqStatus = hasNasdaqData
      ? `${fmtIdx(globalData.ixicPrice)} / 60일선 ${fmtIdx(globalData.ixicMa60)} (${globalData.macroRisk && globalData.macroRisk.techWeak ? "하회" : "상회"})`
      : "데이터 없음";

    const activeFlags = [];
    if (globalData.macroRisk && globalData.macroRisk.highRate)     activeFlags.push("고금리");
    if (globalData.macroRisk && globalData.macroRisk.strongDollar) activeFlags.push("강달러");
    if (globalData.macroRisk && globalData.macroRisk.highVix)      activeFlags.push("시장 불안(VIX)");
    if (globalData.macroRisk && globalData.macroRisk.techWeak)     activeFlags.push("기술주 약세");

    const statusLine = activeFlags.length > 0
      ? `현재 체크 구간: <strong style="color:#c0392b;">${activeFlags.join(" · ")}</strong>`
      : `현재 체크 구간: <strong style="color:#27ae60;">해당 없음</strong>`;

    return (
      `<div style="margin:12px 0 14px;padding:10px 12px;background:#fff8e8;border-left:3px solid #f39c12;font-size:13px;color:#444;">` +
      `<strong>매크로 참고</strong><br>` +
      `단, 고금리(미국 10년물 4.2% 이상), 강달러(달러 인덱스 103 이상), 시장 불안(VIX 20 이상), 기술주 약세(QQQ 60일선 하회) 구간에서는 적자 성장주보다 <strong>실적이 확인되는 종목</strong>을 우선할 것을 권장합니다.<br>` +
      `현재값: 미국 10년물 <strong>${fmtPct(globalData.us10y)}</strong> · 달러 인덱스 <strong>${fmtIdx(globalData.dxy)}</strong> · VIX <strong>${fmtVix(globalData.vixToday)}</strong> · QQQ <strong>${nasdaqStatus}</strong><br>` +
      `${statusLine}` +
      `</div>`
    );
  },

  buildTrendTop3Html(trendData) {
    if (!trendData || !trendData.ranks || trendData.ranks.length === 0) return "";
    const top3 = trendData.ranks.filter(r => r.rank <= 3).sort((a, b) => a.rank - b.rank);
    if (top3.length === 0) return "";
    const rowsHtml = top3.map(r =>
      `<div style="padding:5px 0;border-bottom:1px solid #e8f0fe;font-size:13px;">` +
      `<span style="color:#3498db;font-weight:bold;min-width:28px;display:inline-block;">${r.rank}위</span>` +
      `<strong style="color:#222;">${r.sector}</strong>` +
      `<span style="color:#666;margin-left:8px;">${r.keywords}</span>` +
      `</div>`
    ).join("");
    const dateStr = trendData.date ? ` (기준: ${trendData.date})` : "";
    const summaryHtml = trendData.summary
      ? `<div style="margin-top:8px;font-size:12px;color:#555;">※ ${trendData.summary}</div>`
      : "";
    return (
      `<div style="margin:0 0 14px;padding:10px 12px;background:#f0f7ff;border-left:3px solid #3498db;font-size:13px;color:#444;">` +
      `<strong>이번 주 시장 트렌드 Top 3</strong>${dateStr}<br>` +
      `<div style="margin-top:6px;">${rowsHtml}</div>` +
      summaryHtml +
      `</div>`
    );
  },

  getLastValues() {
    const saved  = PropertiesService.getScriptProperties().getProperty("lastValues");
    // data 필드는 더 이상 저장하지 않음 (JSON 크기 절감)
    let result   = saved ? JSON.parse(saved) : { initialized: false, vixToday: 0, event: "당분간 없음", lastValidOpinions: {} };
    // 레거시 마이그레이션: data 필드가 있던 구 버전은 initialized: true 로 취급
    if (!Object.prototype.hasOwnProperty.call(result, "initialized")) {
      result.initialized = Array.isArray(result.data) && result.data.length > 0;
    }
    delete result.data; // 혹여 남아있는 구 data 필드 제거 (메모리 절감)
    if (result.lastValidOpinions && Object.keys(result.lastValidOpinions).length > 0) {
      const firstVal = result.lastValidOpinions[Object.keys(result.lastValidOpinions)[0]];
      if (typeof firstVal === "string") {
        const migrated = {};
        for (const stock in result.lastValidOpinions) migrated[stock] = { opinion: result.lastValidOpinions[stock], reason: `${result.lastValidOpinions[stock]} 조건 충족` };
        result.lastValidOpinions = migrated;
      }
    }
    if (!result.vixToday) result.vixToday = 0;
    if (!result.event)    result.event    = "당분간 없음";
    return result;
  },

  // currentData 파라미터는 하위 호환성을 위해 유지하지만 저장하지 않음
  // getLastValues()를 재호출하지 않도록 직접 구성 (Props 읽기 1회 절감)
  saveLastValues(_currentData, updatedValidOpinions = null, currentGlobalData = {}) {
    const toSave = {
      initialized:       true,
      vixToday:          currentGlobalData.vixToday  ?? 0,
      event:             currentGlobalData.event      ?? "당분간 없음",
      lastValidOpinions: updatedValidOpinions         ?? {},
    };
    PropertiesService.getScriptProperties().setProperty("lastValues", JSON.stringify(toSave));
  },

  isInitialRun(lastValues, targetSheet, currentGlobalData) {
    if (!lastValues.initialized) {
      const currentData     = targetSheet.getRange(3, 1, targetSheet.getLastRow() - 2, targetSheet.getLastColumn()).getValues();
      const initialOpinions = {};
      const C               = Utils.COL_INDICES;
      currentData.forEach(row => {
        const name    = String(row[C.stockName]).trim();
        const opinion = String(row[C.opinion]).trim();
        if (name && Utils.isValidOpinion(opinion)) initialOpinions[name] = { opinion, reason: "초기값 설정" };
      });
      Utils.saveLastValues(null, initialOpinions, currentGlobalData);
      console.log("초기 실행: 현재 의견 저장 후 종료");
      return true;
    }
    return false;
  },

  isValidOpinion(value) {
    return typeof value === "string" && ["매수", "관망", "매도"].includes(value);
  },

  toNum(val) {
    if (val === null || val === undefined || val === "" || val instanceof Date || typeof val === "object") return null;
    const s = String(val).trim();
    if (s.indexOf("#") === 0 || s.toLowerCase() === "loading..." || s === "데이터 부족") return null;
    const n = Number(val);
    return isNaN(n) ? null : n;
  },

  calcTradingDays(fromDate, toDate) {
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
  },

  getHoldRestoreState(stockName, currentPrice, now, allProperties) {
    const S = Utils.STRATEGY;
    const props = PropertiesService.getScriptProperties();
    const merged = allProperties || {};
    const entry = Utils.loadEntryInfoFrom(stockName, merged);
    const watchStr =
      merged[`HOLD_WATCH_${stockName}`] || props.getProperty(`HOLD_WATCH_${stockName}`) ||
      merged[`A_HOLD_WATCH_${stockName}`] || props.getProperty(`A_HOLD_WATCH_${stockName}`);
    const watchDate = watchStr ? Utils.parseDateKST(watchStr) : null;
    const requiredPrice = entry.price > 0 ? entry.price * (1 - S.HOLD_RESTORE_DROP) : 0;
    const ddOk = entry.price > 0 && currentPrice > 0 && currentPrice <= requiredPrice;
    const days = watchDate ? Utils.calcTradingDays(watchDate, now) : 0;
    const daysOk = watchDate ? days >= S.HOLD_RESTORE_MIN_TRADING_DAYS : false;
    return {
      entryPrice: entry.price,
      requiredPrice,
      watchDate,
      days,
      ddOk,
      daysOk,
      allowed: ddOk && daysOk,
      missingEntry: !(entry.price > 0),
      missingWatch: !watchDate
    };
  },

  buildHoldRestorePendingReason(stockName, currentPrice, now, allProperties, strategy) {
    const S = Utils.STRATEGY;
    const state = Utils.getHoldRestoreState(stockName, currentPrice, now, allProperties);
    const label = strategy || "-";
    if (state.missingEntry) {
      return `${label}그룹 추가 매수 대기: 전 진입가 정보 없음`;
    }
    return `${label}그룹 추가 매수 대기: 전 진입가 ${Utils.fmtPrice(state.entryPrice, stockName)} 대비 -${(S.HOLD_RESTORE_DROP * 100).toFixed(0)}% 및 관망 ${S.HOLD_RESTORE_MIN_TRADING_DAYS}거래일 경과 시 허용`;
  },

  loadEntryInfoFrom(stockName, allProperties) {
    const val = allProperties[`ENTRY_${stockName}`];
    if (!val) return { price: 0, date: null, strategyType: "A" };
    const parts = val.split("|");
    const rawType = parts[2] || "A";
    // 레거시 문자열 키만 재매핑, A-F letter는 현재 체계를 그대로 사용
    const legacyMap = {
      "squeeze": "E", "ma200u": "F", "ma200d": "B"
    };
    const strategyType = /^[A-G]$/.test(rawType)
      ? rawType
      : (legacyMap[rawType] !== undefined ? legacyMap[rawType] : rawType);
    return { price: Number(parts[0]) || 0, date: parts[1] ? Utils.parseDateKST(parts[1]) : null, strategyType };
  },

  loadSellTimeFrom(stockName, allProperties) {
    const val = allProperties[`SELL_${stockName}`];
    return val ? Utils.parseDateKST(val.split("|")[0]) : null;
  },

  loadSellPriceFrom(stockName, allProperties) {
    const val = allProperties[`SELL_${stockName}`];
    if (!val) return 0;
    const parts = val.split("|");
    return parts[1] ? Number(parts[1]) : 0;
  },

  calcSqueeze(row) {
    const C            = Utils.COL_INDICES;
    const bbWidth      = Utils.toNum(row[C.bbWidth]);
    const bbWidthAvg60 = Utils.toNum(row[C.bbWidthAvg60]);
    if (bbWidth === null || bbWidthAvg60 === null || bbWidthAvg60 <= 0) return false;
    return (bbWidth / bbWidthAvg60) < Utils.STRATEGY.SQUEEZE_RATIO;
  },

  evaluateOpinion(row, globalData, now, allProperties = {}) {
    const C            = Utils.COL_INDICES;
    const S            = Utils.STRATEGY;
    const stockName    = String(row[C.stockName]).trim();
    const currentPrice = Utils.toNum(row[C.currentPrice]);
    const ma200        = Utils.toNum(row[C.ma200]);
    const ma20         = C.ma20 >= 0 ? Utils.toNum(row[C.ma20]) : null;
    const rsi          = Utils.toNum(row[C.rsi]);
    const cci          = Utils.toNum(row[C.cci]);
    const macdHist     = Utils.toNum(row[C.macdHist]);
    const macdHistD1   = Utils.toNum(row[C.macdHistD1]);
    const macdHistD2   = Utils.toNum(row[C.macdHistD2]);
    const pctB         = Utils.toNum(row[C.pctB]);
    const pctBLow      = Utils.toNum(row[C.pctBLow]);
    const bbWidth      = Utils.toNum(row[C.bbWidth]);
    const bbWidthD1    = Utils.toNum(row[C.bbWidthD1]);
    const bbWidthAvg60 = Utils.toNum(row[C.bbWidthAvg60]);
    const candleLow    = Utils.toNum(row[C.candleLow]);
    const lrTrendline  = Utils.toNum(row[C.lrTrendline]);
    const volRatio     = C.volRatio  >= 0 ? Utils.toNum(row[C.volRatio])  : null;
    const plusDI       = C.plusDI    >= 0 ? Utils.toNum(row[C.plusDI])    : null;
    const minusDI      = C.minusDI   >= 0 ? Utils.toNum(row[C.minusDI])   : null;
    const adx          = C.adx       >= 0 ? Utils.toNum(row[C.adx])       : null;
    const adxD1        = C.adxD1     >= 0 ? Utils.toNum(row[C.adxD1])     : null;
    const vixToday     = globalData.vixToday;
    const ixicDist     = globalData.ixicDist !== undefined ? globalData.ixicDist : 100;
    const ixicFilterActive = globalData.ixicFilterActive !== undefined
      ? globalData.ixicFilterActive
      : (typeof computeNasdaqABFilterActive === "function" ? computeNasdaqABFilterActive(ixicDist) : ixicDist < S.NASDAQ_DIST_UPPER && ixicDist > S.NASDAQ_DIST_LOWER);
    const currentOpinion  = String(row[C.opinion]).trim();
    const isEventWatch    = globalData.event !== "당분간 없음";
    const nasdaqPeakAlert = globalData.nasdaqPeakAlert;
    const buyBlockMax = globalData.nasdaqBuyBlockMax || (typeof getNasdaqBuyBlockMax_ === "function" ? getNasdaqBuyBlockMax_(ixicDist, allProperties) : S.NASDAQ_BUY_BLOCK_MAX);
    const nasdaqBelowBuyBlock = Number.isFinite(ixicDist) && ixicDist <= buyBlockMax;

    const saved         = Utils.loadEntryInfoFrom(stockName, allProperties);
    const entryPrice    = saved.price > 0 ? saved.price : (Utils.toNum(row[C.entryPrice]) || 0);
    const entryDate     = saved.date || (row[C.entryDate] instanceof Date ? row[C.entryDate] : null);
    const isHolding     = entryPrice > 0;
    const savedStrategy = isHolding ? (saved.strategyType || "A") : null;
    const vixThreshold  = isHolding ? S.VIX_RELEASE : S.VIX_MIN;

    const nasdaqAllowsStrictMomentum = nasdaqBelowBuyBlock && !ixicFilterActive && ixicDist >= S.NASDAQ_DIST_UPPER;
    const nasdaqAllowsBottomBuy = nasdaqBelowBuyBlock && !ixicFilterActive;
    const nasdaqAllowsGRecovery = !!globalData.isRecoveryMarket
      && nasdaqBelowBuyBlock
      && !ixicFilterActive
      && Number.isFinite(ixicDist)
      && ixicDist >= S.G_QQQ_DIST_MIN
      && ixicDist <= S.G_QQQ_DIST_MAX;

    const hasRsi = rsi !== null;
    const hasCci = cci !== null;
    const rsiOk  = hasRsi && rsi < S.RSI_MAX;
    const cciOk  = hasCci && cci < S.CCI_MIN;
    const bCond3     = rsiOk || cciOk;
    const bCond3Hold = (hasRsi || hasCci) && bCond3;
    const bbPairOk   = bbWidth !== null && bbWidthAvg60 !== null && bbWidthAvg60 > 0;

    const aCond1 = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const aCond2 = macdHistD1 !== null && macdHist !== null && macdHistD1 <= 0 && macdHist > 0;
    const aCond3 = pctB !== null && pctB > S.GOLDEN_CROSS_PCTB_MIN;
    const aCond4 = rsi !== null && rsi > S.GOLDEN_CROSS_RSI_MIN;
    const entryGroupA = aCond1 && aCond2 && aCond3 && aCond4 && nasdaqAllowsStrictMomentum;

    const bCond1 = currentPrice !== null && ma200 !== null && currentPrice < ma200;
    const bCond2 = vixToday >= vixThreshold;
    const lrSlope = (typeof getLRSlope === "function") ? getLRSlope(stockName) : 0;
    const bCond4 = lrSlope > 0;
    const bCond5 = lrTrendline !== null && lrTrendline > 0 && candleLow !== null && candleLow <= lrTrendline * S.LR_TOUCH_RATIO;
    const entryGroupB = bCond1 && bCond2 && bCond3 && bCond4 && bCond5 && nasdaqBelowBuyBlock;

    const cCond1 = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const cCond2 = bbPairOk && bbWidthD1 !== null && (bbWidthD1 / bbWidthAvg60) < S.C_SQUEEZE_RATIO;
    const cCond3 = bbPairOk && bbWidthD1 !== null && bbWidth > bbWidthD1 * S.BB_EXPAND_RATIO;
    const cCond4 = volRatio !== null && volRatio >= S.SQUEEZE_BREAKOUT_VOL_RATIO;
    const cCond5 = pctB !== null && pctB > S.SQUEEZE_BREAKOUT_PCTB_MIN;
    const cCond6 = macdHist !== null && macdHist > 0;
    const entryGroupC = !entryGroupA && !entryGroupB
                     && cCond1 && cCond2 && cCond3 && cCond4 && cCond5 && cCond6
                     && nasdaqAllowsStrictMomentum;

    const dCond1 = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const dCond2 = plusDI !== null && minusDI !== null && plusDI > minusDI;
    const dCond3 = adx !== null && adx > S.ADX_MIN;
    const dCond4 = adx !== null && adxD1 !== null && adx > adxD1;
    const dCond5 = macdHist !== null && macdHist > 0;
    const dCond6 = pctB !== null && pctB >= S.ADX_PCTB_MIN && pctB <= S.ADX_PCTB_MAX;
    const entryGroupD = !entryGroupA && !entryGroupB && !entryGroupC
                     && dCond1 && dCond2 && dCond3 && dCond4 && dCond5 && dCond6
                     && nasdaqAllowsStrictMomentum;

    const eCond1 = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const eCond2 = bbPairOk && (bbWidth / bbWidthAvg60) < S.SQUEEZE_RATIO;
    const eCond3 = pctBLow !== null && pctBLow <= S.SQUEEZE_PCT_B_MAX;
    const entryGroupE = !entryGroupA && !entryGroupB && !entryGroupC && !entryGroupD
                     && eCond1 && eCond2 && eCond3 && nasdaqAllowsBottomBuy;

    const fCond1 = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const fCond2 = pctBLow !== null && pctBLow <= S.BB_PCT_B_LOW_MAX;
    const entryGroupF = !entryGroupA && !entryGroupB && !entryGroupC && !entryGroupD && !entryGroupE
                     && fCond1 && fCond2 && nasdaqAllowsBottomBuy;

    const gState = nasdaqAllowsGRecovery && currentPrice !== null && ma200 !== null && currentPrice > ma200
      ? fetchGMa20PullbackState_(stockName)
      : null;
    const gMa20 = gState && Number.isFinite(Number(gState.ma20)) ? Number(gState.ma20) : ma20;
    const gClose = gState && Number.isFinite(Number(gState.close)) ? Number(gState.close) : currentPrice;
    const gLow = gState && Number.isFinite(Number(gState.low)) ? Number(gState.low) : candleLow;
    const gCond1 = nasdaqAllowsGRecovery;
    const gCond2 = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const gCond3 = gMa20 !== null && ma200 !== null && gMa20 > ma200;
    const gCond4 = gLow !== null && gMa20 !== null && gLow <= gMa20;
    const gCond5 = gClose !== null && gMa20 !== null && gClose > gMa20;
    const gCond6 = !!(gState && Number.isFinite(Number(gState.closeD1)) && Number.isFinite(Number(gState.ma20D1)) && Number(gState.closeD1) > Number(gState.ma20D1));
    const gCond7 = !!(gState && Number.isFinite(Number(gState.ma20Slope5)) && Number(gState.ma20Slope5) >= S.G_MA20_SLOPE5_MIN);
    const gCond8 = rsi !== null && rsi >= S.G_RSI_MIN && rsi <= S.G_RSI_MAX;
    const gCond9 = !!(gState && Number.isFinite(Number(gState.volRatio20)) && Number(gState.volRatio20) <= S.G_VOL_RATIO20_MAX);
    const gCond10 = currentPrice !== null && ma200 !== null && ma200 > 0 && (currentPrice / ma200 - 1) <= S.G_MA200_OVERHEAT_MAX;
    const entryGroupG = !entryGroupA && !entryGroupB && !entryGroupC && !entryGroupD && !entryGroupE && !entryGroupF
                     && gCond1 && gCond2 && gCond3 && gCond4 && gCond5 && gCond6 && gCond7 && gCond8 && gCond9 && gCond10;

    let buyTriggered = entryGroupA || entryGroupB || entryGroupC || entryGroupD || entryGroupE || entryGroupF || entryGroupG;
    const newStrategy = entryGroupA ? "A" : entryGroupB ? "B" : entryGroupC ? "C"
                      : entryGroupD ? "D" : entryGroupE ? "E" : entryGroupF ? "F" : entryGroupG ? "G" : null;

    if (isHolding && entryPrice > 0 && entryDate) {
      if (savedStrategy === "A") {
        const macdOk = macdHist !== null && macdHist > 0;
        buyTriggered = aCond1 && !ixicFilterActive && nasdaqBelowBuyBlock && ixicDist >= S.NASDAQ_DIST_UPPER && macdOk;
      } else if (savedStrategy === "B") {
        buyTriggered = bCond1 && bCond2 && bCond3Hold && bCond4 && nasdaqBelowBuyBlock;
      } else if (savedStrategy === "C") {
        const macdOkC = macdHist !== null && macdHist > 0;
        buyTriggered = cCond1 && !ixicFilterActive && nasdaqBelowBuyBlock && ixicDist >= S.NASDAQ_DIST_UPPER && macdOkC;
      } else if (savedStrategy === "D") {
        const diOk    = plusDI !== null && minusDI !== null && plusDI > minusDI;
        const macdOkD = macdHist !== null && macdHist > 0;
        buyTriggered = dCond1 && !ixicFilterActive && nasdaqBelowBuyBlock && ixicDist >= S.NASDAQ_DIST_UPPER && diOk && macdOkD;
      } else if (savedStrategy === "E") {
        buyTriggered = eCond1 && !ixicFilterActive && nasdaqBelowBuyBlock && bbPairOk && pctBLow !== null && eCond2 && eCond3;
      } else if (savedStrategy === "F") {
        buyTriggered = fCond1 && !ixicFilterActive && nasdaqBelowBuyBlock && pctBLow !== null && fCond2;
      } else if (savedStrategy === "G") {
        buyTriggered = gCond1 && gCond2 && gCond3 && gCond5 && gCond6 && gCond7 && gCond8 && gCond9 && gCond10;
      }

      if (nasdaqPeakAlert && typeof nasdaqPeakExitApplies === "function" && nasdaqPeakExitApplies(savedStrategy)) return { opinion: "매도", reason: `나스닥 고점 청산/강제매도 — ${globalData.nasdaqPeakReason || "국면별 QQQ 과열 기준 충족"}`, strategyType: savedStrategy };

      const cp          = currentPrice !== null ? currentPrice : 0;
      const returnPct   = (cp - entryPrice) / entryPrice;
      const tradingDays = Utils.calcTradingDays(entryDate, now);

      const targetPct = savedStrategy === "A" ? S.TARGET_PCT_A
                      : savedStrategy === "B" ? S.TARGET_PCT_B
                      : savedStrategy === "C" ? S.TARGET_PCT_C
                      : savedStrategy === "D" ? S.TARGET_PCT_D
                      : savedStrategy === "E" ? S.TARGET_PCT_E
                      : savedStrategy === "F" ? S.TARGET_PCT_F
                      : S.TARGET_PCT_G;
      const circuitPct = savedStrategy === "A" ? S.CIRCUIT_PCT_A
                       : savedStrategy === "B" ? S.CIRCUIT_PCT_B
                       : savedStrategy === "C" ? S.CIRCUIT_PCT_C
                       : savedStrategy === "D" ? S.CIRCUIT_PCT_D
                       : savedStrategy === "E" ? S.CIRCUIT_PCT_E
                       : savedStrategy === "F" ? S.CIRCUIT_PCT_F
                       : S.CIRCUIT_PCT_G;
      const label = savedStrategy === "A" ? "200일선 상방 & 모멘텀 재가속"
                  : savedStrategy === "B" ? "200일선 하방 & 공황 저점"
                  : savedStrategy === "C" ? "200일선 상방 & 스퀴즈 거래량 돌파"
                  : savedStrategy === "D" ? "200일선 상방 & 상승 흐름 강화"
                  : savedStrategy === "E" ? "200일선 상방 & 스퀴즈 저점"
                  : savedStrategy === "F" ? "200일선 상방 & BB 극단 저점"
                  : "급락 후 회복장 20일선 눌림";
      const maxHoldDays = savedStrategy === "D" ? S.MAX_HOLD_DAYS_D : savedStrategy === "G" ? S.MAX_HOLD_DAYS_G : S.MAX_HOLD_DAYS;

      const isEfStrategy = savedStrategy === "E" || savedStrategy === "F";
      let upperExitArmDate = isEfStrategy ? Utils.loadUpperExitArmFrom(stockName, allProperties) : null;

      if (isEfStrategy && returnPct >= targetPct && !upperExitArmDate) {
        Utils.saveUpperExitArm(stockName, now);
        upperExitArmDate = now;
      }

      if (isEfStrategy && upperExitArmDate) {
        const histTurnSignal =
          macdHist !== null && macdHistD1 !== null && macdHistD2 !== null &&
          (macdHist - macdHistD1) < (macdHistD1 - macdHistD2);
        const waitDays = Utils.calcTradingDays(upperExitArmDate, now);
        if (returnPct >= targetPct && histTurnSignal) {
          return { opinion: "매도", reason: `목표 수익 구간 + MACD 히스토그램 둔화전환 매도 +${(returnPct * 100).toFixed(2)}% [${label}]`, strategyType: savedStrategy };
        }
        if (waitDays >= S.UPPER_EXIT_MAX_WAIT_DAYS) {
          return { opinion: "매도", reason: `목표 수익 도달 후 ${S.UPPER_EXIT_MAX_WAIT_DAYS}거래일 대기 만료 매도 ${(returnPct * 100).toFixed(2)}% [${label}]`, strategyType: savedStrategy };
        }
      }

      if (!isEfStrategy && returnPct >= targetPct) {
        return { opinion: "매도", reason: `목표 수익 달성 즉시 매도 +${(returnPct * 100).toFixed(2)}% [${label}]`, strategyType: savedStrategy };
      }

      if (returnPct <= -circuitPct)                           return { opinion: "매도", reason: `손절 기준 도달 -${Math.abs(returnPct * 100).toFixed(2)}% [${label}]`, strategyType: savedStrategy };
      // 반등 미달 청산은 기간 내 터치 여부가 아니라 판단 시점의 현재 수익률로 판정한다.
      if (tradingDays >= S.STALLED_EXIT_DAYS && returnPct < S.STALLED_EXIT_MIN_RETURN) {
        return {
          opinion: "매도",
          reason: `${S.STALLED_EXIT_DAYS}거래일 반등 미달 청산 (${tradingDays}일, ${(returnPct * 100).toFixed(2)}% < +${(S.STALLED_EXIT_MIN_RETURN * 100).toFixed(0)}%)`,
          strategyType: savedStrategy
        };
      }
      if (savedStrategy !== "G" && tradingDays >= S.HALF_EXIT_DAYS && returnPct > 0)  return { opinion: "매도", reason: "60거래일 경과 + 수익 중", strategyType: savedStrategy };
      if (tradingDays >= maxHoldDays)                        return { opinion: "매도", reason: `최대 보유 기간 초과 (${maxHoldDays}일)`, strategyType: savedStrategy };

      if (buyTriggered) {
        if (isEventWatch) {
          if (currentOpinion === "매수") {
            return { opinion: "매수", reason: "보유 유지 (이벤트 기간, 기존 매수 유지)", strategyType: savedStrategy };
          }
          return { opinion: "관망", reason: "보유 유지 (매수 조건 재충족, 이벤트 기간 — 추가 매수 보류)", strategyType: savedStrategy };
        }
        if (
          currentOpinion === "관망" &&
          typeof aHoldRestoreAllowed === "function" &&
          !aHoldRestoreAllowed(stockName, savedStrategy, currentPrice, now, allProperties)
        ) {
          return {
            opinion: "관망",
            reason: typeof buildHoldRestorePendingReason === "function"
              ? buildHoldRestorePendingReason(stockName, savedStrategy, currentPrice, now, allProperties)
              : `보유 유지 (${savedStrategy}그룹 추가 매수 대기: 전 진입가 대비 -${(S.HOLD_RESTORE_DROP * 100).toFixed(0)}% 및 관망 ${S.HOLD_RESTORE_MIN_TRADING_DAYS}거래일 경과 시 허용)`,
            strategyType: savedStrategy
          };
        }
        return { opinion: "매수", reason: "보유 유지 (매수 조건 충족 중)", strategyType: savedStrategy };
      }
      return { opinion: "관망", reason: "보유 유지 (매수 조건 이탈, 매도 조건 미충족)", strategyType: savedStrategy };
    }

    const sellTime     = Utils.loadSellTimeFrom(stockName, allProperties);
    const sellPrice    = Utils.loadSellPriceFrom(stockName, allProperties);
    const elapsedHours = sellTime ? (now - sellTime) / (1000 * 60 * 60) : S.SELL_HOLD_HOURS + 1;

    let isReentryAllowed = true;
    if (sellTime) {
      const daysSinceSell = Utils.calcTradingDays(sellTime, now);
      if (elapsedHours < S.SELL_HOLD_HOURS) {
        isReentryAllowed = false;
      } else if (daysSinceSell <= S.REENTRY_DAYS && !(sellPrice > 0 && currentPrice !== null && currentPrice <= sellPrice * (1 - S.REENTRY_DROP))) {
        isReentryAllowed = false;
      }
    }

    if (currentOpinion === "매도") {
      if (elapsedHours < S.SELL_HOLD_HOURS) {
        return {
          opinion: "매도",
          reason: nasdaqPeakAlert
            ? `매도 유지 (고점 청산/강제매도 후 ${elapsedHours.toFixed(1)}시간 / 48시간 대기)`
            : `매도 유지 (${elapsedHours.toFixed(1)}시간 / 48시간 대기)`,
          strategyType: null
        };
      }
      if (nasdaqPeakAlert) {
        return { opinion: "관망", reason: "고점 청산/강제매도 상태 유지 — 48시간 경과 후에도 신규/재진입 차단", strategyType: null };
      }
      if (buyTriggered && !isEventWatch) {
        if (isReentryAllowed) return { opinion: "매수", reason: "매도 후 재진입 조건 충족", strategyType: newStrategy };
        return { opinion: "관망", reason: "매수 조건 충족되나 재진입 쿨다운 중", strategyType: null };
      }
      if (isEventWatch) return { opinion: "관망", reason: `이벤트 기간 관망 (${globalData.event})`, strategyType: null };
      return { opinion: "관망", reason: "매도 후 대기 완료 → 관망 전환", strategyType: null };
    }

    if (!isEventWatch && !nasdaqPeakAlert && buyTriggered) {
      if (isReentryAllowed) return { opinion: "매수", reason: "매수 조건 충족", strategyType: newStrategy };
      return { opinion: "관망", reason: "매수 조건 충족되나 재진입 쿨다운 중", strategyType: null };
    }
    if (nasdaqPeakAlert) return { opinion: "관망", reason: "고점 청산/강제매도 상태 유지 — 신규/재진입 차단", strategyType: null };
    return { opinion: "관망", reason: isEventWatch ? `이벤트 기간 관망 (${globalData.event})` : "매수 조건 미충족", strategyType: null };
  },

  summarizeChangeReason(fromOpinion, toOpinion, currentGlobalData, lastEvent, row, now, lastReason, allProperties = {}, hintStrategyType = null) {
    const C            = Utils.COL_INDICES;
    const S            = Utils.STRATEGY;
    const stockName    = String(row[C.stockName]).trim();
    const currentPrice = Utils.toNum(row[C.currentPrice]);
    const ma200        = Utils.toNum(row[C.ma200]);
    const rsi          = Utils.toNum(row[C.rsi]);
    const cci          = Utils.toNum(row[C.cci]);
    const macdHist     = Utils.toNum(row[C.macdHist]);
    const macdHistD1   = Utils.toNum(row[C.macdHistD1]);
    const pctB         = Utils.toNum(row[C.pctB]);
    const pctBLow      = Utils.toNum(row[C.pctBLow]);
    const ma20         = C.ma20 >= 0 ? Utils.toNum(row[C.ma20]) : null;
    const bbWidth      = Utils.toNum(row[C.bbWidth]);
    const bbWidthD1    = Utils.toNum(row[C.bbWidthD1]);
    const bbWidthAvg60 = Utils.toNum(row[C.bbWidthAvg60]);
    const candleLow    = Utils.toNum(row[C.candleLow]);
    const lrTrendline  = Utils.toNum(row[C.lrTrendline]);
    const volRatio     = C.volRatio  >= 0 ? Utils.toNum(row[C.volRatio])  : null;
    const plusDI       = C.plusDI    >= 0 ? Utils.toNum(row[C.plusDI])    : null;
    const minusDI      = C.minusDI   >= 0 ? Utils.toNum(row[C.minusDI])   : null;
    const adx          = C.adx       >= 0 ? Utils.toNum(row[C.adx])       : null;
    const adxD1        = C.adxD1     >= 0 ? Utils.toNum(row[C.adxD1])     : null;
    const vixToday     = currentGlobalData.vixToday;
    const ixicDist     = currentGlobalData.ixicDist !== undefined ? currentGlobalData.ixicDist : 100;
    const ixicFilterActive = currentGlobalData.ixicFilterActive !== undefined
      ? currentGlobalData.ixicFilterActive
      : (typeof computeNasdaqABFilterActive === "function" ? computeNasdaqABFilterActive(ixicDist) : ixicDist < S.NASDAQ_DIST_UPPER && ixicDist > S.NASDAQ_DIST_LOWER);
    const buyBlockMax = currentGlobalData.nasdaqBuyBlockMax || (typeof getNasdaqBuyBlockMax_ === "function" ? getNasdaqBuyBlockMax_(ixicDist, allProperties) : S.NASDAQ_BUY_BLOCK_MAX);
    const fmt          = v => Number(v).toFixed(2);
    const fmtP         = v => Utils.fmtPrice(v, stockName);

    const hasRsi = rsi !== null;
    const hasCci = cci !== null;
    const rsiOk  = hasRsi && rsi < S.RSI_MAX;
    const cciOk  = hasCci && cci < S.CCI_MIN;
    const cond3Released = (hasRsi || hasCci) && !rsiOk && !cciOk;

    const bbPairOk = bbWidth !== null && bbWidthAvg60 !== null && bbWidthAvg60 > 0;
    const nasdaqBelowBuyBlock = Number.isFinite(ixicDist) && ixicDist <= buyBlockMax;
    const nasdaqAllowsStrictMomentum = nasdaqBelowBuyBlock && !ixicFilterActive && ixicDist >= S.NASDAQ_DIST_UPPER;
    const nasdaqAllowsBottomBuy = nasdaqBelowBuyBlock && !ixicFilterActive;
    const nasdaqAllowsGRecovery = !!currentGlobalData.isRecoveryMarket
      && nasdaqBelowBuyBlock
      && !ixicFilterActive
      && Number.isFinite(ixicDist)
      && ixicDist >= S.G_QQQ_DIST_MIN
      && ixicDist <= S.G_QQQ_DIST_MAX;

    // 그룹 재감지 (현재 지표 기준)
    const aCond1 = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const aCond2 = macdHistD1 !== null && macdHist !== null && macdHistD1 <= 0 && macdHist > 0;
    const aCond3 = pctB !== null && pctB > S.GOLDEN_CROSS_PCTB_MIN;
    const aCond4 = rsi !== null && rsi > S.GOLDEN_CROSS_RSI_MIN;
    const groupA = aCond1 && aCond2 && aCond3 && aCond4 && nasdaqAllowsStrictMomentum;

    const bCond1   = currentPrice !== null && ma200 !== null && currentPrice < ma200;
    const lrSlope  = (typeof getLRSlope === "function") ? getLRSlope(stockName) : 0;
    const groupB   = !groupA && bCond1 && (vixToday >= S.VIX_MIN)
                  && (rsiOk || cciOk) && lrSlope > 0
                  && lrTrendline !== null && lrTrendline > 0 && candleLow !== null && candleLow <= lrTrendline * S.LR_TOUCH_RATIO;

    const cCond1   = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const cCond2   = bbPairOk && bbWidthD1 !== null && (bbWidthD1 / bbWidthAvg60) < S.C_SQUEEZE_RATIO;
    const cCond3   = bbPairOk && bbWidthD1 !== null && bbWidth > bbWidthD1 * S.BB_EXPAND_RATIO;
    const cCond4   = volRatio !== null && volRatio >= S.SQUEEZE_BREAKOUT_VOL_RATIO;
    const cCond5   = pctB !== null && pctB > S.SQUEEZE_BREAKOUT_PCTB_MIN;
    const cCond6   = macdHist !== null && macdHist > 0;
    const groupC   = !groupA && !groupB && cCond1 && cCond2 && cCond3 && cCond4 && cCond5 && cCond6 && nasdaqAllowsStrictMomentum;

    const dCond1   = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const dCond2   = plusDI !== null && minusDI !== null && plusDI > minusDI;
    const dCond3   = adx !== null && adx > S.ADX_MIN;
    const dCond4   = adx !== null && adxD1 !== null && adx > adxD1;
    const dCond5   = macdHist !== null && macdHist > 0;
    const dCond6   = pctB !== null && pctB >= S.ADX_PCTB_MIN && pctB <= S.ADX_PCTB_MAX;
    const groupD   = !groupA && !groupB && !groupC && dCond1 && dCond2 && dCond3 && dCond4 && dCond5 && dCond6 && nasdaqAllowsStrictMomentum;

    const eCond1   = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const eCond2   = bbPairOk && (bbWidth / bbWidthAvg60) < S.SQUEEZE_RATIO;
    const eCond3   = pctBLow !== null && pctBLow <= S.SQUEEZE_PCT_B_MAX;
    const groupE   = !groupA && !groupB && !groupC && !groupD && eCond1 && eCond2 && eCond3 && nasdaqAllowsBottomBuy;

    const fCond1   = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const fCond2   = pctBLow !== null && pctBLow <= S.BB_PCT_B_LOW_MAX;
    const groupF   = !groupA && !groupB && !groupC && !groupD && !groupE && fCond1 && fCond2 && nasdaqAllowsBottomBuy;

    const gState = (nasdaqAllowsGRecovery || hintStrategyType === "G") && currentPrice !== null && ma200 !== null && currentPrice > ma200
      ? fetchGMa20PullbackState_(stockName)
      : null;
    const gMa20 = gState && Number.isFinite(Number(gState.ma20)) ? Number(gState.ma20) : ma20;
    const gClose = gState && Number.isFinite(Number(gState.close)) ? Number(gState.close) : currentPrice;
    const gLow = gState && Number.isFinite(Number(gState.low)) ? Number(gState.low) : candleLow;
    const gCond1 = nasdaqAllowsGRecovery;
    const gCond2 = currentPrice !== null && ma200 !== null && currentPrice > ma200;
    const gCond3 = gMa20 !== null && ma200 !== null && gMa20 > ma200;
    const gCond4 = gLow !== null && gMa20 !== null && gLow <= gMa20;
    const gCond5 = gClose !== null && gMa20 !== null && gClose > gMa20;
    const gCond6 = !!(gState && Number.isFinite(Number(gState.closeD1)) && Number.isFinite(Number(gState.ma20D1)) && Number(gState.closeD1) > Number(gState.ma20D1));
    const gCond7 = !!(gState && Number.isFinite(Number(gState.ma20Slope5)) && Number(gState.ma20Slope5) >= S.G_MA20_SLOPE5_MIN);
    const gCond8 = rsi !== null && rsi >= S.G_RSI_MIN && rsi <= S.G_RSI_MAX;
    const gCond9 = !!(gState && Number.isFinite(Number(gState.volRatio20)) && Number(gState.volRatio20) <= S.G_VOL_RATIO20_MAX);
    const gCond10 = currentPrice !== null && ma200 !== null && ma200 > 0 && (currentPrice / ma200 - 1) <= S.G_MA200_OVERHEAT_MAX;
    const groupG = !groupA && !groupB && !groupC && !groupD && !groupE && !groupF
      && gCond1 && gCond2 && gCond3 && gCond4 && gCond5 && gCond6 && gCond7 && gCond8 && gCond9 && gCond10;

    const strategyType = groupA ? "A" : groupB ? "B" : groupC ? "C" : groupD ? "D" : groupE ? "E" : groupF ? "F" : groupG ? "G" : null;
    const resolvedType = strategyType || hintStrategyType;

    if (fromOpinion === toOpinion) {
      if (toOpinion === "매수") {
        const saved     = Utils.loadEntryInfoFrom(stockName, allProperties);
        const cp        = currentPrice !== null ? currentPrice : 0;
        const returnPct = saved.price > 0 ? ((cp - saved.price) / saved.price * 100).toFixed(2) : "-";
        const days      = saved.date ? Utils.calcTradingDays(saved.date, now) : "-";
        return `보유 유지 (${days}거래일, 수익률 ${returnPct}%, 현재가 ${fmtP(cp)})`;
      }
      if (toOpinion === "매도") {
        const sellTime     = Utils.loadSellTimeFrom(stockName, allProperties);
        const elapsedHours = sellTime ? ((now - sellTime) / (1000 * 60 * 60)).toFixed(1) : "-";
        return currentGlobalData.nasdaqPeakAlert
          ? `매도 유지 (${elapsedHours}시간 경과 / 고점 청산·강제매도 상태로 신규·재진입 차단 중)`
          : `매도 유지 (${elapsedHours}시간 경과 / 재진입 대기 중)`;
      }
      return "관망 유지";
    }

    if (fromOpinion === "초기값") return "초기값 설정";

    const buildBuyReason = (type) => {
      const sqRatio = bbPairOk ? ((bbWidth / bbWidthAvg60) * 100).toFixed(1) + "%" : "-";
      const gSlopeText = gState && Number.isFinite(Number(gState.ma20Slope5)) ? (Number(gState.ma20Slope5) * 100).toFixed(2) + "%" : "데이터 없음";
      const gVol20Text = gState && Number.isFinite(Number(gState.volRatio20)) ? Number(gState.volRatio20).toFixed(2) : "데이터 없음";
      if (type === "A") return `A. 200일선 상방 & 모멘텀 재가속 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | 종가 %B ${pctB !== null ? fmt(pctB) : "-"} | RSI ${Utils.fmtNumOrDash(rsi, 2)} | MACD Hist ${Utils.fmtNumOrDash(macdHist, 4)}`;
      if (type === "B") return `B. 200일선 하방 & 공황 저점 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | VIX ${fmt(vixToday)} | RSI ${Utils.fmtNumOrDash(rsi, 2)} / CCI ${Utils.fmtNumOrDash(cci, 2)} | LR추세선 ${lrTrendline !== null ? fmtP(lrTrendline) : "-"} / 저가 ${candleLow !== null ? fmtP(candleLow) : "-"}`;
      if (type === "C") return `C. 200일선 상방 & 스퀴즈 거래량 돌파 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | BB폭 ${bbWidth !== null ? fmt(bbWidth) : "-"} (전일 ${bbWidthD1 !== null ? fmt(bbWidthD1) : "-"} / 60일 ${bbWidthAvg60 !== null ? fmt(bbWidthAvg60) : "-"}) | 거래량비 ${volRatio !== null ? fmt(volRatio) : "-"} | 종가 %B ${pctB !== null ? fmt(pctB) : "-"} | MACD Hist ${Utils.fmtNumOrDash(macdHist, 4)}`;
      if (type === "D") return `D. 200일선 상방 & 상승 흐름 강화 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | +DI ${plusDI !== null ? fmt(plusDI) : "-"} / -DI ${minusDI !== null ? fmt(minusDI) : "-"} | ADX ${adx !== null ? fmt(adx) : "-"} | 종가 %B ${pctB !== null ? fmt(pctB) : "-"} | MACD Hist ${Utils.fmtNumOrDash(macdHist, 4)}`;
      if (type === "E") return `E. 200일선 상방 & 스퀴즈 저점 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | BB폭 ${bbWidth !== null ? fmt(bbWidth) : "-"} / 60일평균 ${bbWidthAvg60 !== null ? fmt(bbWidthAvg60) : "-"} (압축 ${sqRatio}) | 저가 %B ${pctBLow !== null ? fmt(pctBLow) : "-"}`;
      if (type === "F") return `F. 200일선 상방 & BB 극단 저점 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | 저가 %B ${pctBLow !== null ? fmt(pctBLow) : "-"}`;
      if (type === "G") return `G. 급락 후 회복장 20일선 눌림 — 현재가 ${fmtP(currentPrice)} / MA20 ${fmtP(gMa20)} / MA200 ${fmtP(ma200)} | RSI ${Utils.fmtNumOrDash(rsi, 2)} | MA20 기울기 ${gSlopeText} | 20일 거래량비 ${gVol20Text}`;
      return currentPrice !== null && ma200 !== null && currentPrice > ma200
        ? `200일선 상방 진입 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)}`
        : `200일선 하방 진입 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)}`;
    };

    if (toOpinion === "관망" && currentGlobalData.event !== "당분간 없음" && lastEvent === "당분간 없음")
      return `이벤트 기간 관망 전환 (${currentGlobalData.event})`;

    if (currentGlobalData.event === "당분간 없음" && lastEvent !== "당분간 없음") {
      const base = `이벤트 해소 (${lastEvent})`;
      if (toOpinion === "매수")  return `${base} → ${buildBuyReason(resolvedType)}`;
      if (toOpinion === "매도")  return `${base} → 매도 조건 충족`;
      return base;
    }

    if (toOpinion === "매수") return buildBuyReason(resolvedType);
    if (toOpinion === "매도") return lastReason || "매도 조건 충족";

    if (toOpinion === "관망") {
      if (fromOpinion === "매수") {
        const savedEntry = Utils.loadEntryInfoFrom(stockName, allProperties);
        const stratType  = savedEntry.strategyType || "A";
        const rawDeath = ixicDist > S.NASDAQ_DIST_LOWER && ixicDist < S.NASDAQ_DIST_UPPER;
        let releaseDetail;

        if (Number.isFinite(ixicDist) && ixicDist > buyBlockMax) {
          releaseDetail = `나스닥 상단 과열 (QQQ 이격도 ${ixicDist.toFixed(1)}% > ${buyBlockMax}%)`;
        } else if ((stratType === "E" || stratType === "F") && ixicFilterActive) {
          releaseDetail = rawDeath
            ? `나스닥 하락장 필터 진입 (QQQ 이격도 ${ixicDist.toFixed(1)}% → 데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)`
            : `나스닥 E/F 차단 유지 (히스테리시스 QQQ 이격도 ${ixicDist.toFixed(1)}%, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`;
        } else if (stratType === "A") {
          releaseDetail = currentPrice <= ma200
            ? `200일선 하방 이탈 (현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)})`
            : macdHist === null
            ? "MACD 히스토그램 일시 결측 (모멘텀 소멸로 단정하지 않음)"
            : macdHist !== null && macdHist <= 0
            ? `MACD 골든크로스 소멸 (hist ${Utils.fmtNumOrDash(macdHist, 4)} ≤ 0)`
            : ixicFilterActive
            ? (rawDeath
              ? `나스닥 하락장 필터 진입 — A그룹 차단 (QQQ 이격도 ${ixicDist.toFixed(1)}% → 데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)`
              : `나스닥 하락장 필터 유지 — A그룹 차단 (히스테리시스 QQQ 이격도 ${ixicDist.toFixed(1)}%, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`)
            : `모멘텀 재가속 조건 이탈 (종가 %B ${pctB !== null ? fmt(pctB) : "-"} / RSI ${Utils.fmtNumOrDash(rsi, 2)})`;
        } else if (stratType === "B") {
          releaseDetail = currentPrice >= ma200
            ? `주가가 200일선 위로 회복 (현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)})`
            : vixToday < S.VIX_RELEASE ? `시장 공포 수치 완화 (VIX ${fmt(vixToday)} < ${S.VIX_RELEASE})`
            : (!hasRsi && !hasCci) ? "RSI/CCI 일시 결측 (과매도 해소로 단정하지 않음)"
            : cond3Released ? `과매도 해소 (RSI ${Utils.fmtNumOrDash(rsi, 2)} / CCI ${Utils.fmtNumOrDash(cci, 2)})`
            : lrSlope <= 0 ? `추세선 기울기 하락 전환 (기울기 ≤ 0)`
            : `저가 추세선 이탈 (저가 ${candleLow !== null ? fmtP(candleLow) : "-"} > 추세선 ${lrTrendline !== null ? fmtP(lrTrendline) : "-"} × ${S.LR_TOUCH_RATIO.toFixed(2)})`;
        } else if (stratType === "C") {
          releaseDetail = currentPrice <= ma200
            ? `200일선 하방 이탈 (현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)})`
            : macdHist === null
            ? "MACD 히스토그램 일시 결측 (모멘텀 소멸로 단정하지 않음)"
            : macdHist !== null && macdHist <= 0
            ? `MACD 소멸 (hist ${Utils.fmtNumOrDash(macdHist, 4)} ≤ 0)`
            : ixicFilterActive
            ? (rawDeath
              ? `나스닥 하락장 필터 진입 — C그룹 차단 (QQQ 이격도 ${ixicDist.toFixed(1)}% → 데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)`
              : `나스닥 하락장 필터 유지 — C그룹 차단 (히스테리시스 QQQ 이격도 ${ixicDist.toFixed(1)}%, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`)
            : `스퀴즈 거래량 돌파 조건 이탈 (거래량비 ${volRatio !== null ? fmt(volRatio) : "-"} / 종가 %B ${pctB !== null ? fmt(pctB) : "-"})`;
        } else if (stratType === "D") {
          releaseDetail = currentPrice <= ma200
            ? `200일선 하방 이탈 (현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)})`
            : (plusDI === null || minusDI === null || macdHist === null)
            ? "DMI/MACD 일시 결측 (추세 약화로 단정하지 않음)"
            : (plusDI !== null && minusDI !== null && plusDI <= minusDI)
            ? `DMI 방향 전환 (+DI ${plusDI !== null ? fmt(plusDI) : "-"} ≤ -DI ${minusDI !== null ? fmt(minusDI) : "-"})`
            : macdHist !== null && macdHist <= 0
            ? `MACD 소멸 (hist ${Utils.fmtNumOrDash(macdHist, 4)} ≤ 0)`
            : ixicFilterActive
            ? (rawDeath
              ? `나스닥 하락장 필터 진입 — D그룹 차단 (QQQ 이격도 ${ixicDist.toFixed(1)}% → 데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)`
              : `나스닥 하락장 필터 유지 — D그룹 차단 (히스테리시스 QQQ 이격도 ${ixicDist.toFixed(1)}%, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`)
            : `상승 흐름 조건 이탈 (+DI ${plusDI !== null ? fmt(plusDI) : "-"} / -DI ${minusDI !== null ? fmt(minusDI) : "-"} / MACD Hist ${Utils.fmtNumOrDash(macdHist, 4)})`;
        } else if (stratType === "E") {
          const isSqueeze = Utils.calcSqueeze(row);
          releaseDetail = ixicFilterActive
            ? (rawDeath
              ? `나스닥 하락장 필터 진입 (QQQ 이격도 ${ixicDist.toFixed(1)}% → 데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)`
              : `나스닥 E그룹 차단 유지 (히스테리시스 QQQ 이격도 ${ixicDist.toFixed(1)}%, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`)
            : currentPrice <= ma200
            ? `200일선 하방 이탈 (현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)})`
            : !bbPairOk || pctBLow === null
            ? `BB·저가%B 일시 결측 (스퀴즈 이탈로 단정하지 않음)`
            : !isSqueeze ? `BB 스퀴즈 해소 (BB폭 ${Utils.fmtNumOrDash(bbWidth, 2)} / 60일평균 ${Utils.fmtNumOrDash(bbWidthAvg60, 2)})`
            : `저가 %B 상승 (${Utils.fmtNumOrDash(pctBLow, 2)} > ${S.SQUEEZE_PCT_B_MAX})`;
        } else if (stratType === "F") {
          releaseDetail = ixicFilterActive
            ? (rawDeath
              ? `나스닥 하락장 필터 진입 (QQQ 이격도 ${ixicDist.toFixed(1)}% → 데스존 ${S.NASDAQ_DIST_UPPER}% ~ ${S.NASDAQ_DIST_LOWER}%)`
              : `나스닥 F그룹 차단 유지 (히스테리시스 QQQ 이격도 ${ixicDist.toFixed(1)}%, 해제 ≥ ${S.NASDAQ_DIST_RELEASE}%)`)
            : currentPrice <= ma200
            ? `200일선 하방 이탈 (현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)})`
            : pctBLow !== null
            ? `BB 하단 눌림 해소 (저가 %B ${Utils.fmtNumOrDash(pctBLow, 2)} > ${S.BB_PCT_B_LOW_MAX})`
            : `저가 %B 일시 결측 (눌림 해소로 단정하지 않음)`;
        } else {
          releaseDetail = !gCond1
            ? `G 회복장 조건 이탈 (QQQ 이격도 ${ixicDist.toFixed(1)}%, 기준 ${S.G_QQQ_DIST_MIN}~${S.G_QQQ_DIST_MAX}%)`
            : currentPrice <= ma200
            ? `200일선 하방 이탈 (현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)})`
            : !gState
            ? "MA20 눌림 데이터 일시 결측"
            : !gCond5
            ? `20일선 회복 실패 (종가 ${fmtP(gClose)} / MA20 ${fmtP(gMa20)})`
            : !gCond7
            ? `MA20 기울기 둔화 (${gState && Number.isFinite(Number(gState.ma20Slope5)) ? (Number(gState.ma20Slope5) * 100).toFixed(2) + "%" : "데이터 없음"} < ${(S.G_MA20_SLOPE5_MIN * 100).toFixed(1)}%)`
            : `G그룹 눌림 조건 이탈 (현재가 ${fmtP(currentPrice)} / MA20 ${fmtP(gMa20)} / RSI ${Utils.fmtNumOrDash(rsi, 2)})`;
        }
        return `매수 조건 해제 — ${releaseDetail} (보유 포지션 유지, 매도 조건 계속 추적)`;
      }
      if (fromOpinion === "매도") {
        if (currentGlobalData.nasdaqPeakAlert) {
          return "고점 청산/강제매도 상태 유지 중 48시간 경과 → 관망 전환 (신규/재진입 차단 유지)";
        }
        return "매도 후 대기 완료 → 관망 전환 (재진입 필터 유지)";
      }
      return "관망 전환";
    }
    return "투자의견 변경";
  },

  getLatestTrendData(targetSheet) {
    try {
      const trendSheet = targetSheet.getParent().getSheetByName("시장트렌드");
      if (!trendSheet || trendSheet.getLastRow() < 2) return null;
      const row   = trendSheet.getRange(trendSheet.getLastRow(), 1, 1, 12).getValues()[0];
      const ranks = [];
      for (let i = 1; i <= 10; i++) {
        const cell  = String(row[i] || "").trim();
        if (!cell || cell === "-") continue;
        const parts = cell.split("|");
        ranks.push({ rank: i, sector: (parts[0] || "").trim(), keywords: (parts[1] || "").trim() });
      }
      return { date: row[0], ranks, summary: String(row[11] || "") };
    } catch (e) {
      console.log(`[getLatestTrendData 오류] ${e}`);
      return null;
    }
  },

  buildIndustryMap(targetSheet) {
    try {
      const valueSheet = targetSheet.getParent().getSheetByName("가치분석");
      if (!valueSheet || valueSheet.getLastRow() < 2) return {};
      const map = {};
      valueSheet.getRange(2, 1, valueSheet.getLastRow() - 1, 4).getValues().forEach(row => {
        const ticker   = String(row[0]).trim();
        const industry = String(row[3]).trim();
        if (ticker && industry) map[ticker] = industry;
      });
      return map;
    } catch (e) {
      console.log(`[buildIndustryMap 오류] ${e}`);
      return {};
    }
  },

  buildTrendBadge(industryStr, trendData) {
    const ranks = trendData && trendData.ranks;
    if (!industryStr || !trendData || !ranks) return null;
    if (!ranks.length) return null;

    const iKeys = industryStr
      .split(/[,·\/]+/)
      .map(k => k.trim())
      .filter(k => k.length >= 2 && !Utils._isGenericTrendToken(k));
    let bestRank = 999, bestSector = "", bestKeyword = "";
    ranks.forEach(r => {
      const tKeys = [r.sector]
        .concat(String(r.keywords || "").split(/[,\|·\/]+/))
        .map(k => k.trim())
        .filter(k => k.length >= 2 && !Utils._isGenericTrendToken(k));
      iKeys.forEach(ik => {
        tKeys.forEach(tk => {
          if (Utils._trendTokensMatch(ik, tk) && r.rank < bestRank) {
            bestRank = r.rank;
            bestSector = r.sector;
            bestKeyword = ik;
          }
        });
      });
    });

    if (bestRank < 999) {
      const fire      = bestRank <= 3 ? "[주도]" : bestRank <= 6 ? "[강세]" : "[주시]";
      const kwDisplay = bestKeyword && bestKeyword !== bestSector ? ` (${bestKeyword})` : "";
      return `${fire} 이번 주 ${bestRank}위 — ${bestSector}${kwDisplay}`;
    }
    return "[트렌드] 순위표에 직접 매칭 없음";
  },

  getTradingLogSheet() {
    const sheet         = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("기술분석");
    const spreadsheetId = sheet.getRange("I1").getValue();
    if (!spreadsheetId) {
      console.log("[트레이딩로그] I1이 비어 있음 — 트레이딩로그 스프레드시트 ID를 기술분석 시트 I1에 입력하세요");
      return null;
    }
    if (Utils._tradingLogSheetCache && Utils._tradingLogSheetCacheId === String(spreadsheetId)) {
      return Utils._tradingLogSheetCache;
    }
    try {
      const targetSpreadsheet = SpreadsheetApp.openById(spreadsheetId);
      let logSheet = targetSpreadsheet.getSheetByName("트레이딩로그");
      if (!logSheet) {
        logSheet = targetSpreadsheet.insertSheet("트레이딩로그");
        logSheet.getRange(1, 1, 1, 6).setValues([["종목", "매수 날짜", "매수 가격", "매도 날짜", "매도 가격", "기준"]]);
        logSheet.setFrozenRows(1);
        logSheet.setColumnWidths(1, 6, 120);
      }
      Utils._tradingLogSheetCache = logSheet;
      Utils._tradingLogSheetCacheId = String(spreadsheetId);
      Utils._nextTradingLogRowCache = null;
      return logSheet;
    } catch (e) {
      console.log(`ERROR: 트레이딩 로그 시트 접근 실패. 오류: ${e}`);
      return null;
    }
  },

  getNextTradingLogRow(logSheet) {
    if (Utils._nextTradingLogRowCache !== null) return Utils._nextTradingLogRowCache;
    const nextRow = Utils.findFirstEmptyRow(logSheet);
    Utils._nextTradingLogRowCache = nextRow;
    return nextRow;
  },

  findFirstEmptyRow(logSheet) {
    const lastRow = logSheet.getLastRow();
    if (lastRow < 3) return 3;
    // 1행은 헤더, 2행은 안내/요약 텍스트로 사용하므로 3행부터만 로그 데이터로 취급.
    // G열 이후 수식/서식이 길게 깔려 있어 getLastRow()가 과대평가될 수 있으므로
    // 실제 로그 영역인 A:F만 기준으로 첫 빈 행을 찾는다.
    const data = logSheet.getRange(3, 1, lastRow - 2, 6).getDisplayValues();
    for (let i = 0; i < data.length; i++) {
      const row = data[i];
      const hasData = row.some(cell => String(cell || "").trim() !== "");
      if (!hasData) return i + 3;
    }
    return lastRow + 1;
  },

  parseTradingLogStrategyCode(label) {
    const text = String(label || "").trim();
    const match = text.match(/^([A-G])\s*\./i) || text.match(/^([A-G])$/i);
    return match ? match[1].toUpperCase() : null;
  },

  clearAllSlotStateForStock(stockName, sellPrice, sellDate, props, allProperties, options = {}) {
    const properties = props || PropertiesService.getScriptProperties();
    const snapshot   = allProperties || properties.getProperties();
    const keepStrategies = new Set((options.keepStrategies || []).map(s => String(s).toUpperCase()));
    const slots = Utils.loadSlots(stockName, snapshot);
    const slotsToKeep = keepStrategies.size > 0 ? slots.filter(slot => keepStrategies.has(String(slot.strategy).toUpperCase())) : [];
    const slotsToClear = keepStrategies.size > 0 ? slots.filter(slot => !keepStrategies.has(String(slot.strategy).toUpperCase())) : slots;

    // SLOT_UPPER_EXIT_ARM_ 키 제거. 고점 부분청산에서는 A/C/E/F 슬롯 arm은 보존한다.
    Object.keys(snapshot)
      .filter(k => k.startsWith(`SLOT_UPPER_EXIT_ARM_${stockName}_`))
      .forEach(k => {
        const strategy = k.replace(`SLOT_UPPER_EXIT_ARM_${stockName}_`, "").charAt(0).toUpperCase();
        if (!keepStrategies.has(strategy)) properties.deleteProperty(k);
      });

    // 각 청산 슬롯 전략에 대해 SLOT_SELL_ 쿨다운 기록
    if (sellDate) {
      const dateStr = sellDate instanceof Date
        ? Utilities.formatDate(sellDate, "Asia/Seoul", "yyyy-MM-dd")
        : String(sellDate);
      slotsToClear.forEach(slot => {
        properties.setProperty(`SLOT_SELL_${stockName}_${slot.strategy}`, `${dateStr}|${sellPrice}`);
      });
    }

    if (slotsToKeep.length > 0) {
      properties.setProperty(`SLOTS_${stockName}`, JSON.stringify(slotsToKeep.map(slot => ({
        ...slot,
        date: slot.date instanceof Date
          ? Utilities.formatDate(slot.date, "Asia/Seoul", "yyyy-MM-dd'T'HH:mm:ss") + "+09:00"
          : slot.date
      }))));
    } else {
      properties.deleteProperty(`SLOTS_${stockName}`);
    }

    // 레거시 SLOT_{stockName}_* 키 정리 (구 형식 잔재)
    Object.keys(snapshot)
      .filter(k => k.startsWith(`SLOT_${stockName}_`)
               && !k.startsWith(`SLOT_SELL_${stockName}_`)
               && !k.startsWith(`SLOT_UPPER_EXIT_ARM_${stockName}_`))
      .forEach(k => {
        const strategy = k.replace(`SLOT_${stockName}_`, "").charAt(0).toUpperCase();
        if (!keepStrategies.has(strategy)) properties.deleteProperty(k);
      });
  },

  recordAllOpenSellSignals(stockName, sellDate, sellPrice) {
    const logSheet = Utils.getTradingLogSheet();
    if (!logSheet) { console.log(`[로깅 실패] ${stockName}: 시트 없음`); return 0; }
    const lastRow = logSheet.getLastRow();
    if (lastRow < 3) return 0;
    const data = logSheet.getRange(3, 1, lastRow - 2, 6).getValues();
    let updateCount = 0;
    for (let i = 0; i < data.length; i++) {
      if (String(data[i][0]).trim() !== stockName || data[i][3]) continue;
      try {
        logSheet.getRange(i + 3, 4).setValue(sellDate);
        Utils.setTradingLogPriceCell(logSheet.getRange(i + 3, 5), stockName, sellPrice);
        updateCount++;
        console.log(`[로깅] 일괄 매도: ${stockName} ${Utils.fmtPrice(sellPrice, stockName)} 행:${i + 3}`);
      } catch (e) {
        console.log(`[로깅 실패] ${stockName} 행${i + 3}: ${e}`);
      }
    }
    if (updateCount === 0) console.log(`[로깅 건너띔] ${stockName}: 청산할 매수 기록 없음`);
    return updateCount;
  },

  // ── 멀티 슬롯 관리 ─────────────────────────────────────────────────────────
  // SLOTS_${stockName}: JSON 배열 — [{ id, strategy, price, date }, ...]
  // SLOT_SELL_${stockName}_${strategy}: "dateStr|sellPrice" (재진입 쿨다운용)

  // 전체 슬롯 배열 로드
  loadSlots(stockName, allProperties) {
    const raw = (allProperties && allProperties[`SLOTS_${stockName}`])
      || PropertiesService.getScriptProperties().getProperty(`SLOTS_${stockName}`);
    if (!raw) return [];
    try {
      return JSON.parse(raw).map(s => ({ ...s, date: s.date ? Utils.parseDateKST(s.date) : null }));
    } catch(e) {
      console.log(`[SLOTS_ 파싱 오류] ${stockName}: ${e}`);
      return [];
    }
  },

  // 특정 전략 첫 슬롯 반환 (하위 호환)
  loadSlot(stockName, strategy, allProperties) {
    return Utils.loadSlots(stockName, allProperties).find(s => s.strategy === strategy) || null;
  },

  // 슬롯 추가 — 배열에 append (덮어쓰기 없음)
  saveSlot(stockName, strategy, price, dateStr, props) {
    Utils.clearSlotUpperExitArm(stockName, strategy, props);
    const properties = props || PropertiesService.getScriptProperties();
    const existing = JSON.parse(properties.getProperty(`SLOTS_${stockName}`) || '[]');
    existing.push({ id: `${strategy}_${Date.now()}`, strategy, price, date: dateStr });
    properties.setProperty(`SLOTS_${stockName}`, JSON.stringify(existing));
  },

  // 슬롯 제거 — ID 기준
  clearSlot(stockName, slotId, props) {
    const properties = props || PropertiesService.getScriptProperties();
    const raw = properties.getProperty(`SLOTS_${stockName}`);
    if (!raw) return;
    const updated = JSON.parse(raw).filter(s => s.id !== slotId);
    if (updated.length === 0) {
      properties.deleteProperty(`SLOTS_${stockName}`);
    } else {
      properties.setProperty(`SLOTS_${stockName}`, JSON.stringify(updated));
    }
    Utils.clearSlotUpperExitArm(stockName, String(slotId).split('_')[0], props);
  },

  saveSlotUpperExitArm(stockName, strategy, date, props) {
    const value = Utilities.formatDate(date, "Asia/Seoul", "yyyy-MM-dd'T'HH:mm:ss") + "+09:00";
    (props || PropertiesService.getScriptProperties()).setProperty(`SLOT_UPPER_EXIT_ARM_${stockName}_${strategy}`, value);
  },

  loadSlotUpperExitArm(stockName, strategy, allProperties) {
    const key   = `SLOT_UPPER_EXIT_ARM_${stockName}_${strategy}`;
    const value = allProperties && allProperties[key];
    return value ? Utils.parseDateKST(value) : null;
  },

  clearSlotUpperExitArm(stockName, strategy, props) {
    (props || PropertiesService.getScriptProperties()).deleteProperty(`SLOT_UPPER_EXIT_ARM_${stockName}_${strategy}`);
  },

  // 슬롯 진입 조건 체크 (strategy별 독립 평가 — 주 전략 제외 없음)
  evaluateSlotEntry(row, globalData, strategy, stockName, allProperties = {}) {
    const C            = Utils.COL_INDICES;
    const S            = Utils.STRATEGY;
    const currentPrice = Utils.toNum(row[C.currentPrice]);
    const ma200        = Utils.toNum(row[C.ma200]);
    const ma20         = C.ma20 >= 0 ? Utils.toNum(row[C.ma20]) : null;
    const rsi          = Utils.toNum(row[C.rsi]);
    const cci          = Utils.toNum(row[C.cci]);
    const pctBLow      = Utils.toNum(row[C.pctBLow]);
    const pctB         = Utils.toNum(row[C.pctB]);
    const bbWidth      = Utils.toNum(row[C.bbWidth]);
    const bbWidthD1    = Utils.toNum(row[C.bbWidthD1]);
    const bbWidthAvg60 = Utils.toNum(row[C.bbWidthAvg60]);
    const macdHist     = Utils.toNum(row[C.macdHist]);
    const macdHistD1   = Utils.toNum(row[C.macdHistD1]);
    const candleLow    = Utils.toNum(row[C.candleLow]);
    const lrTrendline  = Utils.toNum(row[C.lrTrendline]);
    const volRatio     = C.volRatio  >= 0 ? Utils.toNum(row[C.volRatio])  : null;
    const plusDI       = C.plusDI    >= 0 ? Utils.toNum(row[C.plusDI])    : null;
    const minusDI      = C.minusDI   >= 0 ? Utils.toNum(row[C.minusDI])   : null;
    const adx          = C.adx       >= 0 ? Utils.toNum(row[C.adx])       : null;
    const adxD1        = C.adxD1     >= 0 ? Utils.toNum(row[C.adxD1])     : null;
    const { ixicFilterActive, ixicDist, nasdaqPeakAlert, vixToday } = globalData;
    const isEventWatch = globalData.event !== "당분간 없음";
    const buyBlockMax = globalData.nasdaqBuyBlockMax || (typeof getNasdaqBuyBlockMax_ === "function" ? getNasdaqBuyBlockMax_(ixicDist, allProperties) : S.NASDAQ_BUY_BLOCK_MAX);
    const nasdaqBelowBuyBlock = Number.isFinite(ixicDist) && ixicDist <= buyBlockMax;

    if (!currentPrice || !ma200) return false;
    if (nasdaqPeakAlert || isEventWatch) return false;

    const bbPairOk                 = bbWidth !== null && bbWidthAvg60 !== null && bbWidthAvg60 > 0;
    const nasdaqAllowsStrictMomentum = nasdaqBelowBuyBlock && !ixicFilterActive && (ixicDist !== undefined ? ixicDist : 100) >= S.NASDAQ_DIST_UPPER;
    const nasdaqAllowsBottomBuy    = nasdaqBelowBuyBlock && !ixicFilterActive;
    const nasdaqAllowsGRecovery = !!globalData.isRecoveryMarket
      && nasdaqBelowBuyBlock
      && !ixicFilterActive
      && Number.isFinite(ixicDist)
      && ixicDist >= S.G_QQQ_DIST_MIN
      && ixicDist <= S.G_QQQ_DIST_MAX;
    const hasRsi = rsi !== null, hasCci = cci !== null;
    const rsiOk  = hasRsi && rsi < S.RSI_MAX;
    const cciOk  = hasCci && cci < S.CCI_MIN;
    const cond3  = rsiOk || cciOk;

    if (strategy === "A") {
      return currentPrice > ma200
        && macdHistD1 !== null && macdHist !== null && macdHistD1 <= 0 && macdHist > 0
        && pctB !== null && pctB > S.GOLDEN_CROSS_PCTB_MIN
        && rsi !== null && rsi > S.GOLDEN_CROSS_RSI_MIN
        && nasdaqAllowsStrictMomentum;
    }
    if (strategy === "B") {
      const lrSlope = (typeof getLRSlope === "function") ? getLRSlope(stockName) : 0;
      return currentPrice < ma200
        && vixToday >= S.VIX_MIN && cond3 && lrSlope > 0
        && lrTrendline !== null && lrTrendline > 0
        && candleLow !== null && candleLow <= lrTrendline * S.LR_TOUCH_RATIO
        && nasdaqBelowBuyBlock;
    }
    if (strategy === "C") {
      return currentPrice > ma200
        && bbPairOk && bbWidthD1 !== null && (bbWidthD1 / bbWidthAvg60) < S.C_SQUEEZE_RATIO
        && bbWidth > bbWidthD1 * S.BB_EXPAND_RATIO
        && volRatio !== null && volRatio >= S.SQUEEZE_BREAKOUT_VOL_RATIO
        && pctB !== null && pctB > S.SQUEEZE_BREAKOUT_PCTB_MIN
        && macdHist !== null && macdHist > 0
        && nasdaqAllowsStrictMomentum;
    }
    if (strategy === "D") {
      return currentPrice > ma200
        && plusDI !== null && minusDI !== null && plusDI > minusDI
        && adx !== null && adx > S.ADX_MIN
        && adx !== null && adxD1 !== null && adx > adxD1
        && macdHist !== null && macdHist > 0
        && pctB !== null && pctB >= S.ADX_PCTB_MIN && pctB <= S.ADX_PCTB_MAX
        && nasdaqAllowsStrictMomentum;
    }
    if (strategy === "E") {
      return currentPrice > ma200
        && bbPairOk && (bbWidth / bbWidthAvg60) < S.SQUEEZE_RATIO
        && pctBLow !== null && pctBLow <= S.SQUEEZE_PCT_B_MAX
        && nasdaqAllowsBottomBuy;
    }
    if (strategy === "F") {
      return currentPrice > ma200
        && pctBLow !== null && pctBLow <= S.BB_PCT_B_LOW_MAX
        && nasdaqAllowsBottomBuy;
    }
    if (strategy === "G") {
      const gState = nasdaqAllowsGRecovery ? fetchGMa20PullbackState_(stockName) : null;
      const gMa20 = gState && Number.isFinite(Number(gState.ma20)) ? Number(gState.ma20) : ma20;
      const gClose = gState && Number.isFinite(Number(gState.close)) ? Number(gState.close) : currentPrice;
      const gLow = gState && Number.isFinite(Number(gState.low)) ? Number(gState.low) : candleLow;
      return currentPrice > ma200
        && nasdaqAllowsGRecovery
        && gMa20 !== null && gMa20 > ma200
        && gLow !== null && gLow <= gMa20
        && gClose !== null && gClose > gMa20
        && !!(gState && Number.isFinite(Number(gState.closeD1)) && Number.isFinite(Number(gState.ma20D1)) && Number(gState.closeD1) > Number(gState.ma20D1))
        && !!(gState && Number.isFinite(Number(gState.ma20Slope5)) && Number(gState.ma20Slope5) >= S.G_MA20_SLOPE5_MIN)
        && rsi !== null && rsi >= S.G_RSI_MIN && rsi <= S.G_RSI_MAX
        && !!(gState && Number.isFinite(Number(gState.volRatio20)) && Number(gState.volRatio20) <= S.G_VOL_RATIO20_MAX)
        && (currentPrice / ma200 - 1) <= S.G_MA200_OVERHEAT_MAX;
    }
    return false;
  },

  // 슬롯 청산 조건 체크 (주 전략과 동일한 익절/손절/보유기간 규칙 적용)
  evaluateSlotExit(row, globalData, now, slot, strategy, allProperties) {
    const C            = Utils.COL_INDICES;
    const S            = Utils.STRATEGY;
    const stockName    = String(row[C.stockName]).trim();
    const currentPrice = Utils.toNum(row[C.currentPrice]);
    if (!currentPrice || !slot.price) return null;

    const macdHist     = Utils.toNum(row[C.macdHist]);
    const macdHistD1   = Utils.toNum(row[C.macdHistD1]);
    const macdHistD2   = Utils.toNum(row[C.macdHistD2]);
    const returnPct   = (currentPrice - slot.price) / slot.price;
    const tradingDays = Utils.calcTradingDays(slot.date, now);
    const targetPct   = strategy === "A" ? S.TARGET_PCT_A
                      : strategy === "B" ? S.TARGET_PCT_B
                      : strategy === "C" ? S.TARGET_PCT_C
                      : strategy === "D" ? S.TARGET_PCT_D
                      : strategy === "E" ? S.TARGET_PCT_E
                      : strategy === "F" ? S.TARGET_PCT_F
                      : S.TARGET_PCT_G;
    const circuitPct  = strategy === "A" ? S.CIRCUIT_PCT_A
                      : strategy === "B" ? S.CIRCUIT_PCT_B
                      : strategy === "C" ? S.CIRCUIT_PCT_C
                      : strategy === "D" ? S.CIRCUIT_PCT_D
                      : strategy === "E" ? S.CIRCUIT_PCT_E
                      : strategy === "F" ? S.CIRCUIT_PCT_F
                      : S.CIRCUIT_PCT_G;
    const label       = strategy === "A" ? "200일선 상방 & 모멘텀 재가속"
                      : strategy === "B" ? "200일선 하방 & 공황 저점"
                      : strategy === "C" ? "200일선 상방 & 스퀴즈 거래량 돌파"
                      : strategy === "D" ? "200일선 상방 & 상승 흐름 강화"
                      : strategy === "E" ? "200일선 상방 & 스퀴즈 저점"
                      : strategy === "F" ? "200일선 상방 & BB 극단 저점"
                      : "급락 후 회복장 20일선 눌림";
    const maxHoldDays = strategy === "D" ? S.MAX_HOLD_DAYS_D : strategy === "G" ? S.MAX_HOLD_DAYS_G : S.MAX_HOLD_DAYS;
    const isEfStrategy = strategy === "E" || strategy === "F";
    let upperExitArmDate = isEfStrategy ? Utils.loadSlotUpperExitArm(stockName, strategy, allProperties) : null;

    if (globalData.nasdaqPeakAlert && typeof nasdaqPeakExitApplies === "function" && nasdaqPeakExitApplies(strategy)) return { reason: `나스닥 고점 청산/강제매도 — ${globalData.nasdaqPeakReason || "국면별 QQQ 과열 기준 충족"} [${label}]` };
    if (returnPct <= -circuitPct)                return { reason: `손절 기준 도달 -${Math.abs(returnPct * 100).toFixed(2)}% [${label}]` };
    // 반등 미달 청산은 기간 내 터치 여부가 아니라 판단 시점의 현재 수익률로 판정한다.
    if (tradingDays >= S.STALLED_EXIT_DAYS && returnPct < S.STALLED_EXIT_MIN_RETURN) {
      return { reason: `${S.STALLED_EXIT_DAYS}거래일 반등 미달 청산 (${tradingDays}일, ${(returnPct * 100).toFixed(2)}% < +${(S.STALLED_EXIT_MIN_RETURN * 100).toFixed(0)}%) [${label}]` };
    }

    if (isEfStrategy && returnPct >= targetPct && !upperExitArmDate) {
      Utils.saveSlotUpperExitArm(stockName, strategy, now);
      upperExitArmDate = now;
    }

    if (isEfStrategy && upperExitArmDate) {
      const histTurnSignal =
        macdHist !== null && macdHistD1 !== null && macdHistD2 !== null &&
        (macdHist - macdHistD1) < (macdHistD1 - macdHistD2);
      const waitDays = Utils.calcTradingDays(upperExitArmDate, now);
      if (returnPct >= targetPct && histTurnSignal) {
        return { reason: `목표 수익 구간 + MACD 히스토그램 둔화전환 매도 +${(returnPct * 100).toFixed(2)}% [${label}]` };
      }
      if (waitDays >= S.UPPER_EXIT_MAX_WAIT_DAYS) {
        return { reason: `목표 수익 도달 후 ${S.UPPER_EXIT_MAX_WAIT_DAYS}거래일 대기 만료 매도 ${(returnPct * 100).toFixed(2)}% [${label}]` };
      }
    }

    if (!isEfStrategy && returnPct >= targetPct) return { reason: `목표 수익 달성 +${(returnPct * 100).toFixed(2)}% [${label}]` };
    if (strategy !== "G" && tradingDays >= S.HALF_EXIT_DAYS && returnPct > 0) return { reason: `60거래일 경과 + 수익 중 [${label}]` };
    if (tradingDays >= maxHoldDays)              return { reason: `최대 보유 기간 초과 (${maxHoldDays}일) [${label}]` };
    return null;
  },

  // 슬롯용 매도 로그 (전략 레이블 기준으로 특정 행만 업데이트)
  recordSlotSellSignal(stockName, strategy, sellDate, sellPrice) {
    const logSheet = Utils.getTradingLogSheet();
    if (!logSheet) { console.log(`[슬롯 매도 로깅 실패] ${stockName} ${strategy}그룹: 시트 없음`); return; }
    const lastRow = logSheet.getLastRow();
    if (lastRow < 3) return;
    const data = logSheet.getRange(3, 1, lastRow - 2, 6).getValues();

    const targetLabel = strategyDisplayName(strategy);
    const normalizeLabel = (l) => String(l || "").replace(/^[A-G]\.\s*/, "").trim();

    for (let i = 0; i < data.length; i++) {
      if (String(data[i][0]).trim() === stockName
          && !data[i][3]
          && normalizeLabel(data[i][5]) === normalizeLabel(targetLabel)) {
        try {
          logSheet.getRange(i + 3, 4).setValue(sellDate);
          Utils.setTradingLogPriceCell(logSheet.getRange(i + 3, 5), stockName, sellPrice);
          console.log(`[슬롯 매도 로깅] ${stockName} ${strategy}그룹 → ${i + 3}행`);
        } catch (e) { console.log(`[슬롯 매도 로깅 실패] ${stockName}: ${e}`); }
        return;
      }
    }
    console.log(`[슬롯 매도 로깅 건너띔] ${stockName} ${strategy}그룹: 매칭 행 없음`);
  },

  // 슬롯 매수 이유 문자열 생성
  buildSlotBuyReason(strategy, row, globalData) {
    const C            = Utils.COL_INDICES;
    const S            = Utils.STRATEGY;
    const currentPrice = Utils.toNum(row[C.currentPrice]);
    const ma200        = Utils.toNum(row[C.ma200]);
    const ma20         = C.ma20 >= 0 ? Utils.toNum(row[C.ma20]) : null;
    const pctBLow      = Utils.toNum(row[C.pctBLow]);
    const pctB         = Utils.toNum(row[C.pctB]);
    const bbWidth      = Utils.toNum(row[C.bbWidth]);
    const bbWidthD1    = Utils.toNum(row[C.bbWidthD1]);
    const bbWidthAvg60 = Utils.toNum(row[C.bbWidthAvg60]);
    const rsi          = Utils.toNum(row[C.rsi]);
    const cci          = Utils.toNum(row[C.cci]);
    const macdHist     = Utils.toNum(row[C.macdHist]);
    const candleLow    = Utils.toNum(row[C.candleLow]);
    const lrTrendline  = Utils.toNum(row[C.lrTrendline]);
    const volRatio     = C.volRatio  >= 0 ? Utils.toNum(row[C.volRatio])  : null;
    const plusDI       = C.plusDI    >= 0 ? Utils.toNum(row[C.plusDI])    : null;
    const minusDI      = C.minusDI   >= 0 ? Utils.toNum(row[C.minusDI])   : null;
    const adx          = C.adx       >= 0 ? Utils.toNum(row[C.adx])       : null;
    const stockName    = String(row[C.stockName]).trim();
    const fmtP         = v => Utils.fmtPrice(v, stockName);
    const fmt          = (v, d) => v !== null ? Number(v).toFixed(d) : "-";

    if (strategy === "A") {
      return `A. 200일선 상방 & 모멘텀 재가속 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | 종가 %B ${fmt(pctB, 2)} | RSI ${fmt(rsi, 1)} | MACD hist ${fmt(macdHist, 4)}`;
    }
    if (strategy === "B") {
      return `B. 200일선 하방 & 공황 저점 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | VIX ${globalData.vixToday !== undefined ? globalData.vixToday.toFixed(2) : "-"} | RSI ${fmt(rsi, 1)} / CCI ${fmt(cci, 1)} | LR추세선 ${fmtP(lrTrendline)} / 저가 ${fmtP(candleLow)}`;
    }
    if (strategy === "C") {
      const sqRatio = (bbWidthD1 !== null && bbWidthAvg60 !== null && bbWidthAvg60 > 0)
        ? ((bbWidthD1 / bbWidthAvg60) * 100).toFixed(1) + "%" : "-";
      return `C. 200일선 상방 & 스퀴즈 거래량 돌파 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | BB폭 ${fmt(bbWidth, 2)} (전일 ${fmt(bbWidthD1, 2)} / 60일 ${fmt(bbWidthAvg60, 2)}) | 거래량비 ${fmt(volRatio, 2)} | 종가 %B ${fmt(pctB, 2)}`;
    }
    if (strategy === "D") {
      return `D. 200일선 상방 & 상승 흐름 강화 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | +DI ${fmt(plusDI, 2)} / -DI ${fmt(minusDI, 2)} | ADX ${fmt(adx, 2)} | 종가 %B ${fmt(pctB, 2)} | MACD hist ${fmt(macdHist, 4)}`;
    }
    if (strategy === "E") {
      const sqRatio = (bbWidth !== null && bbWidthAvg60 !== null && bbWidthAvg60 > 0)
        ? ((bbWidth / bbWidthAvg60) * 100).toFixed(1) + "%" : "-";
      return `E. 200일선 상방 & 스퀴즈 저점 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | BB폭 압축 ${sqRatio} | 저가 %B ${fmt(pctBLow, 2)}`;
    }
    if (strategy === "F") {
      return `F. 200일선 상방 & BB 극단 저점 — 현재가 ${fmtP(currentPrice)} / MA200 ${fmtP(ma200)} | 저가 %B ${fmt(pctBLow, 2)}`;
    }
    const gState = fetchGMa20PullbackState_(stockName);
    const gMa20 = gState && Number.isFinite(Number(gState.ma20)) ? Number(gState.ma20) : ma20;
    const slope = gState && Number.isFinite(Number(gState.ma20Slope5)) ? (Number(gState.ma20Slope5) * 100).toFixed(2) + "%" : "데이터 없음";
    const vol20 = gState && Number.isFinite(Number(gState.volRatio20)) ? Number(gState.volRatio20).toFixed(2) : "데이터 없음";
    return `G. 급락 후 회복장 20일선 눌림 — 현재가 ${fmtP(currentPrice)} / MA20 ${fmtP(gMa20)} / MA200 ${fmtP(ma200)} | RSI ${fmt(rsi, 1)} | MA20 기울기 ${slope} | 20일 거래량비 ${vol20}`;
  },

  recordBuySignal(stockName, buyDate, buyPrice, strategyLabel) {
    console.log(`[로깅 시도] 매수: ${stockName} / 가격: ${buyPrice} / 전략: ${strategyLabel} / 날짜: ${buyDate}`);
    const logSheet = Utils.getTradingLogSheet();
    if (!logSheet) {
      console.log(`[로깅 실패] ${stockName}: 트레이딩로그 시트 접근 불가 — I1 셀의 스프레드시트 ID를 확인하세요`);
      return;
    }
    try {
      const row = Utils.getNextTradingLogRow(logSheet);
      console.log(`[로깅 대상 행] ${stockName}: ${row}행`);
      logSheet.getRange(row, 1, 1, 6).setValues([[stockName, buyDate, "", "", "", strategyLabel]]);
      Utils.setTradingLogPriceCell(logSheet.getRange(row, 3), stockName, buyPrice);
      SpreadsheetApp.flush();
      Utils._nextTradingLogRowCache = row + 1;
      console.log(`[로깅 완료] 매수: ${stockName} ${Utils.fmtPrice(buyPrice, stockName)} (${strategyLabel}) → ${row}행`);
    } catch (e) {
      console.log(`[로깅 실패] ${stockName}: ${e.message || e}`);
    }
  },

  recordSellSignal(stockName, sellDate, sellPrice, strategyLabel) {
    const logSheet = Utils.getTradingLogSheet();
    if (!logSheet) { console.log(`[로깅 실패] ${stockName}: 시트 없음`); return; }
    const lastRow = logSheet.getLastRow();
    if (lastRow < 3) return;
    const data         = logSheet.getRange(3, 1, lastRow - 2, 6).getValues();
    const normalizeLabel = (l) => String(l || "").replace(/^[A-G]\.\s*/, "").trim();
    let updateCount    = 0;
    for (let i = 0; i < data.length; i++) {
      if (String(data[i][0]).trim() === stockName && !data[i][3]) {
        if (strategyLabel && normalizeLabel(data[i][5]) !== normalizeLabel(strategyLabel)) continue;
        try {
          logSheet.getRange(i + 3, 4).setValue(sellDate);
          Utils.setTradingLogPriceCell(logSheet.getRange(i + 3, 5), stockName, sellPrice);
          updateCount++;
          console.log(`[로깅] 매도: ${stockName} ${Utils.fmtPrice(sellPrice, stockName)} 행:${i + 3}`);
        } catch (e) { console.log(`[로깅 실패] ${stockName} 행${i + 3}: ${e}`); }
      }
    }
    if (updateCount === 0) console.log(`[로깅 건너띔] ${stockName}: 청산할 매수 기록 없음`);
  },

  sendEmailAlert(recipientEmail, changes, buyOpinions, watchHoldingOpinions, sellOpinions, kstDate, estString, globalData, trendData = null) {
    const stockSymbols = changes.map(c => c.ticker).join(", ");
    const displayFrom = c => c.fromLabel || ((c.from === "매수" && c.to === "매수") ? "매수(보유중)" : c.from);
    const displayTo   = c => c.toLabel   || ((c.from === "매수" && c.to === "매수") ? "추가 매수" : c.to);
    const hasBuyTransition = changes.some(c => c.to === "매수" && (c.from !== "매수" || displayTo(c).includes("추가 매수")));
    const changesHtml  = changes.map((c, i) => {
      const fromLabel    = displayFrom(c);
      const toLabel      = displayTo(c);
      const isBuySignal  = c.to === "매수" || toLabel.includes("매수");
      const isSellSignal = c.to === "매도" || toLabel.includes("매도");
      const borderColor = isBuySignal ? "#2ecc71" : isSellSignal ? "#e74c3c" : "#95a5a6";
      const toColor     = isBuySignal ? "#27ae60" : isSellSignal ? "#c0392b" : "#7f8c8d";
      let entryNoteHtml = "";
      if (c.entryNote) {
        const isNew   = c.entryNote === "신규 진입";
        const isReent = c.entryNote.startsWith("재진입");
        const noteColor = isNew ? "#2980b9" : isReent ? "#e67e22" : "#7f8c8d";
        entryNoteHtml = `<br><span style="font-size:12px;color:${noteColor};">${c.entryNote.replace(/\n/g, "<br>")}</span>`;
      }
      return (
        `<div style="margin-bottom:8px;padding:8px;background:#f9f9f9;border-left:3px solid ${borderColor};">` +
        `${i + 1}. <strong>${c.stock}</strong> &nbsp;<span style="color:#888;">'${fromLabel}'</span> → <strong style="color:${toColor};">${toLabel}</strong><br>` +
        `<span style="font-size:13px;">이유: ${c.reason}</span><br>` +
        `<span style="font-size:13px;">현재가: <strong>${c.price}</strong></span>` +
        entryNoteHtml +
        (c.industry   ? `<br><span style="font-size:12px;color:#666;">산업: ${c.industry}</span>` : "") +
        (c.trendBadge ? `<br><span style="font-size:12px;color:#e67e22;">${c.trendBadge}</span>` : "") +
        `</div>`
      );
    }).join("");

    const macroContextHtml = hasBuyTransition ? Utils.buildMacroContextHtml(globalData) : "";
    const trendTop3Html    = hasBuyTransition ? Utils.buildTrendTop3Html(trendData) : "";

    const emailBody = `
    <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;max-width:600px;">
      <p style="font-size:16px;font-weight:bold;color:#333;border-bottom:2px solid #eee;padding-bottom:8px;">투자의견이 변경된 종목이 있습니다.</p>
      <div>${changesHtml}</div>
      ${macroContextHtml}
      ${trendTop3Html}
      <p style="margin:0;"><strong>현재 매수 의견 종목:</strong> ${buyOpinions.length > 0 ? buyOpinions.join(", ") : "없음"}</p>
      <p style="margin:0;"><strong>보유 중 관망 종목:</strong> ${watchHoldingOpinions.length > 0 ? watchHoldingOpinions.join(", ") : "없음"}</p>
      <p style="margin:0;"><strong>현재 매도 의견 종목:</strong> ${sellOpinions.length > 0 ? sellOpinions.join(", ") : "없음"}</p><br>
      <p style="color:#888;font-size:12px;">발송 시각 (한국): ${kstDate}<br>발송 시각 (미 동부): ${estString}</p>
    </div>`;

    if (!(recipientEmail && recipientEmail.length > 0)) {
      console.log("[이메일 실패] F1 셀 이메일 주소 없음");
      return false;
    }

    const subject = `투자의견 변경 알림 (${stockSymbols})`;
    const maxAttempts = 3;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        GmailApp.sendEmail(recipientEmail, subject, "", { htmlBody: emailBody });
        console.log(`[이메일 발송] ${stockSymbols} → ${recipientEmail} (시도 ${attempt}/${maxAttempts})`);
        return true;
      } catch (e) {
        console.log(`[이메일 실패] 시도 ${attempt}/${maxAttempts}: ${e}`);
        if (attempt < maxAttempts) Utilities.sleep(1500 * attempt);
      }
    }
    console.log("[이메일 FATAL] 재시도 후에도 발송 실패");
    return false;
  }
};

