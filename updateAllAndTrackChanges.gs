var PIPELINE_STATE_KEY = "UPDATE_ALL_PIPELINE_STATE";
var PIPELINE_FAILURE_COUNT_KEY = "UPDATE_ALL_PIPELINE_FAILURE_COUNT";
var PIPELINE_WARNING_SENT_KEY = "UPDATE_ALL_PIPELINE_WARNING_SENT";
var PIPELINE_LOCK_WAIT_MS = 5000;
var PIPELINE_RETRY_STAGES = {
  updateInvestmentOpinion: true,
  postUpdateWait: true,
  trackChanges: true
};

function updateAllAndTrackChanges() {
  const startMs = Date.now();
  const elapsed = () => `${((Date.now() - startMs) / 1000).toFixed(1)}s`;
  const lock = LockService.getScriptLock();
  const previousPipelineState = getPipelineState_();
  const preserveSnapshot = shouldPreserveLastValuesForRetry_(previousPipelineState);
  let currentStage = "start";
  const enterStage = (stage) => {
    currentStage = stage;
    setPipelineState_("running", stage, null);
  };

  if (!lock.tryLock(PIPELINE_LOCK_WAIT_MS)) {
    const lockError = "이전 실행이 아직 진행 중입니다.";
    recordPipelineFailure_("lock", lockError, !preserveSnapshot);
    console.log(`[트리거 건너뜀] ${lockError} (${new Date().toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })})`);
    return;
  }

  try {
    console.log(`[트리거 시작] updateAllAndTrackChanges (${new Date().toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })})`);
    setPipelineState_("running", "updateAllAndTrackChanges", null);

    if (shouldRetryTrackChangesOnly_(previousPipelineState)) {
      console.log(`[재시도] 이전 실행이 '${previousPipelineState.stage}' 단계에서 실패 — 시트 재계산 없이 변경 알림만 재시도`);
      enterStage("trackChanges");
      console.log(`[시작] trackChanges`);
      trackChanges();
      console.log(`[완료] trackChanges (${elapsed()})`);
      setPipelineState_("completed", "done", null);
      clearPipelineFailureState_();
      console.log(`[트리거 종료] 변경 알림 재시도 완료 (총 ${elapsed()})`);
      return;
    }

    enterStage("batchPrefetchPrices");
    console.log(`[시작] batchPrefetchPrices`);
    batchPrefetchPrices();
    console.log(`[완료] RSI/CCI 캐시 적재 (${elapsed()})`);

    enterStage("updateLRTrendlineAll");
    console.log(`[시작] updateLRTrendlineAll`);
    updateLRTrendlineAll();
    console.log(`[완료] LR 추세선 캐시 적재 (${elapsed()})`);

    enterStage("flush");
    SpreadsheetApp.flush();
    console.log(`[flush] 시트 쓰기 커밋 완료 (${elapsed()})`);

    enterStage("preUpdateWait");
    console.log(`[대기] 데이터 반영 대기 30초`);
    Utilities.sleep(30000);
    console.log(`[대기 완료] 나스닥 고점 상태 점검 시작`);

    // 고점 경고 상태는 같은 실행 안에서 바로 투자의견/매도 판단에 반영되어야 한다.
    // 기존에는 checkNasdaqMASignals()가 trackChanges() 뒤에 있어, 경고 메일이 와도
    // 실제 보유 종목 청산이 다음 트리거로 밀리는 순서 버그가 발생할 수 있었다.
    enterStage("checkNasdaqMASignals");
    console.log(`[시작] checkNasdaqMASignals`);
    checkNasdaqMASignals();
    console.log(`[완료] checkNasdaqMASignals (${elapsed()})`);

    enterStage("snapshotOpinionsBeforeUpdate");
    console.log(`[시작] 투자의견 업데이트 준비`);

    // updateInvestmentOpinion 실행 전 현재 시트 상태를 trackChanges 비교 기준으로 저장.
    // batchPrefetchPrices / updateLRTrendlineAll 실행 도중 Properties가 초기화되는 경우에도
    // lastValues 가 항상 올바른 "변경 전" 상태를 갖도록 보장한다.
    const snapshotSaved = snapshotOpinionsBeforeUpdate_(preserveSnapshot, previousPipelineState);
    console.log(`[스냅샷] ${snapshotSaved ? "투자의견 비교 기준 저장 완료" : "이전 기준값 보존/스킵"} (${elapsed()})`);

    enterStage("updateInvestmentOpinion");
    console.log(`[시작] updateInvestmentOpinion`);
    updateInvestmentOpinion();
    console.log(`[완료] 투자의견 업데이트 (${elapsed()})`);

    enterStage("postUpdateWait");
    console.log(`[대기] 투자의견 반영 대기 20초`);
    Utilities.sleep(20000);
    console.log(`[대기 완료] 투자의견 변경 감지 및 이메일 알림 시작`);

    enterStage("trackChanges");
    console.log(`[시작] trackChanges`);
    trackChanges();
    console.log(`[완료] trackChanges (${elapsed()})`);

    setPipelineState_("completed", "done", null);
    clearPipelineFailureState_();
    console.log(`[트리거 종료] 모든 작업 완료 (총 ${elapsed()})`);
  } catch (e) {
    const errorText = String(e && e.message ? e.message : e);
    recordPipelineFailure_(currentStage, errorText, true);
    console.log(`[FATAL] updateAllAndTrackChanges 실패: ${e && e.stack ? e.stack : e}`);
    throw e;
  } finally {
    lock.releaseLock();
  }
}

/**
 * updateInvestmentOpinion 실행 직전에 시트의 현재 투자의견을 lastValues로 저장.
 * trackChanges가 항상 "변경 전" 기준을 올바르게 갖도록 보장한다.
 */
function snapshotOpinionsBeforeUpdate_(preserveSnapshot, previousPipelineState) {
  if (preserveSnapshot) {
    console.log(`[스냅샷] 이전 실행이 '${previousPipelineState.stage}' 단계에서 실패 — lastValues 보존 후 변경 감지 재시도`);
    return false;
  }

  const ss        = SpreadsheetApp.getActiveSpreadsheet();
  const techSheet = ss.getSheetByName("기술분석");
  if (!techSheet) { console.log("[스냅샷] 기술분석 시트 없음 — 스킵"); return false; }

  const lastRow = techSheet.getLastRow();
  if (lastRow < 3) { console.log("[스냅샷] 데이터 없음 — 스킵"); return false; }

  const numRows  = lastRow - 2;
  const names    = techSheet.getRange(3, 1, numRows, 1).getValues();  // A열: 종목명 (COL_INDICES.stockName = 0)
  const opinions = techSheet.getRange(3, 4, numRows, 1).getValues();  // D열: 투자의견 (COL_INDICES.opinion = 3)

  const VALID = new Set(["매수", "매도", "관망"]);
  const lastValidOpinions = {};
  names.forEach(([name], i) => {
    const n  = String(name).trim();
    const op = String(opinions[i][0]).trim();
    if (!n || !VALID.has(op)) return;
    lastValidOpinions[n] = { opinion: op, reason: "트리거 실행 전 기준값" };
  });

  PropertiesService.getScriptProperties().setProperty("lastValues", JSON.stringify({
    initialized:       true,
    vixToday:          0,
    event:             "당분간 없음",
    lastValidOpinions,
  }));
  console.log(`[스냅샷] ${Object.keys(lastValidOpinions).length}종목 기준값 저장 완료`);
  return true;
}

function shouldPreserveLastValuesForRetry_(state) {
  if (!state || (state.status !== "failed" && state.status !== "running")) return false;

  const stage = String(state.stage || "");
  if (PIPELINE_RETRY_STAGES[stage]) return true;

  // 구버전은 실패 stage가 뭉뚱그려 저장되어 있을 수 있으므로,
  // Apps Script INTERNAL처럼 변경 감지 직전/중간 실패가 의심되는 경우 1회 보존한다.
  const error = String(state.error || "");
  return stage === "updateAllAndTrackChanges" && error.indexOf("INTERNAL") !== -1;
}

function shouldRetryTrackChangesOnly_(state) {
  if (!state || state.status !== "failed") return false;
  const stage = String(state.stage || "");
  return stage === "postUpdateWait" || stage === "trackChanges";
}

function getPipelineState_() {
  const raw = PropertiesService.getScriptProperties().getProperty(PIPELINE_STATE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (e) {
    console.log(`[파이프라인 상태 파싱 오류] ${e}`);
    return null;
  }
}

function setPipelineState_(status, stage, error) {
  const props = PropertiesService.getScriptProperties();
  const nowIso = new Date().toISOString();
  const next = {
    status: status,
    stage: stage || null,
    updatedAt: nowIso,
    error: error || null
  };
  props.setProperty(PIPELINE_STATE_KEY, JSON.stringify(next));
}

function clearPipelineFailureState_() {
  const props = PropertiesService.getScriptProperties();
  props.deleteProperty(PIPELINE_FAILURE_COUNT_KEY);
  props.deleteProperty(PIPELINE_WARNING_SENT_KEY);
}

function recordPipelineFailure_(stage, errorText, saveState) {
  if (saveState !== false) setPipelineState_("failed", stage, errorText);

  const props = PropertiesService.getScriptProperties();
  const count = Number(props.getProperty(PIPELINE_FAILURE_COUNT_KEY) || "0") + 1;
  props.setProperty(PIPELINE_FAILURE_COUNT_KEY, String(count));

  console.log(`[실패 카운트] updateAllAndTrackChanges 연속 실패 ${count}회`);
  if (count < 3 || props.getProperty(PIPELINE_WARNING_SENT_KEY) === "TRUE") return;

  const recipient = getPipelineAlertRecipient_();
  if (!recipient) {
    console.log("[경고 메일 실패] 수신자 이메일을 찾을 수 없음");
    return;
  }

  const now = new Date();
  const kstDate = Utilities.formatDate(now, "Asia/Seoul", "yyyy. MM. dd, HH:mm:ss");
  const subject = `[경고] 투자 알림 트리거 연속 실패 ${count}회`;
  const body = [
    `투자의견 업데이트/알림 트리거가 연속 ${count}회 실패했습니다.`,
    "",
    "2시간 주기 트리거 기준으로 약 6시간 동안 정상 완료되지 않았습니다.",
    "Apps Script 트리거, 권한, 실행 로그를 확인해 주세요.",
    "",
    `마지막 실패 단계: ${stage}`,
    `마지막 오류: ${errorText}`,
    `발송 시각 (한국): ${kstDate}`
  ].join("\n");

  try {
    GmailApp.sendEmail(recipient, subject, body);
    props.setProperty(PIPELINE_WARNING_SENT_KEY, "TRUE");
    console.log(`[경고 메일 발송] 연속 실패 ${count}회 → ${recipient}`);
  } catch (mailError) {
    console.log(`[경고 메일 실패] ${mailError}`);
  }
}

function getPipelineAlertRecipient_() {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const localTechSheet = ss.getSheetByName("기술분석");
    if (!localTechSheet) return "";

    const spreadsheetId = String(localTechSheet.getRange("I1").getValue() || "").trim();
    if (spreadsheetId) {
      const targetSheet = SpreadsheetApp.openById(spreadsheetId).getSheetByName("기술분석");
      if (targetSheet) {
        const targetEmail = String(targetSheet.getRange("F1").getValue() || "").trim();
        if (targetEmail) return targetEmail;
      }
    }

    return String(localTechSheet.getRange("F1").getValue() || "").trim();
  } catch (e) {
    console.log(`[경고 메일 수신자 조회 실패] ${e}`);
    return "";
  }
}
