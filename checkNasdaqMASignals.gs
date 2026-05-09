function checkNasdaqMASignals() {
  var RECIPIENT_EMAIL_CELL = "F1";
  var PEAK_STATE_KEY = "NasdaqPeakSellState";

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var targetSheet = ss.getSheetByName("기술분석");
  if (!targetSheet) return;

  var properties = PropertiesService.getScriptProperties();
  var now = new Date();

  var kstDate = Utilities.formatDate(now, "Asia/Seoul", "yyyy. MM. dd, HH:mm:ss");
  var estString = Utilities.formatDate(now, "America/New_York", "M/d/yyyy, h:mm:ss a");

  var recipientEmail = targetSheet.getRange(RECIPIENT_EMAIL_CELL).getValue();
  if (!recipientEmail || recipientEmail.length === 0) return;

  try {
    if (typeof getNasdaqPeakSignalState_ !== "function") {
      Logger.log("[고점 청산/강제매도 알림 FATAL] getNasdaqPeakSignalState_ 함수를 찾을 수 없습니다.");
      return;
    }

    var lastPeakState = properties.getProperty(PEAK_STATE_KEY) === "TRUE";
    var peakState = getNasdaqPeakSignalState_(targetSheet, properties.getProperties());
    var currentPrice = Number(peakState.currentPrice) || 0;
    var nasdaqMA200 = Number(peakState.nasdaqMA200) || 0;
    var nasdaqPremiumPercent = Number(peakState.premiumPercent);
    var qqqWeeklyRsi = Number(peakState.qqqWeeklyRsi) || 0;
    var qqqDailyRsi = Number(peakState.qqqDailyRsi) || 0;
    var qqqDailyRsiPrev = Number(peakState.qqqDailyRsiPrev) || 0;
    var qqqMacdHist = peakState.qqqMacdHist;
    var qqqMacdHistD1 = peakState.qqqMacdHistD1;
    var qqqMacdHistD2 = peakState.qqqMacdHistD2;
    var peakReason = peakState.peakReason || "국면별 QQQ 과열 기준";
    var regimeLabel = peakState.regimeLabel || "-";
    var directDist = Number(peakState.peakDirectDist) || 0;
    var confirmDist = Number(peakState.peakConfirmDist) || 0;
    var isPeakTriggered = peakState.nasdaqPeakAlert === true;

    if (!currentPrice || !nasdaqMA200 || !qqqWeeklyRsi || !qqqDailyRsi || !qqqDailyRsiPrev) {
      Logger.log("[고점 청산/강제매도 알림] 데이터 오류 — 현재가: " + currentPrice + ", MA200: " + nasdaqMA200 +
        ", 주봉 RSI: " + qqqWeeklyRsi + ", 일봉 RSI: " + qqqDailyRsi + ", 전일 RSI: " + qqqDailyRsiPrev);
      return;
    }

    Logger.log("[고점 청산/강제매도 알림] QQQ 현재가: " + currentPrice.toFixed(2));
    Logger.log("[고점 청산/강제매도 알림] QQQ MA200: " + nasdaqMA200.toFixed(2) + ", 시장 국면: " + regimeLabel);
    Logger.log("[고점 청산/강제매도 알림] MA200 대비: " + (nasdaqPremiumPercent >= 0 ? "+" : "") + nasdaqPremiumPercent.toFixed(2) + "%");
    Logger.log("[고점 청산/강제매도 알림] 가격 조건: 직접선 >" + directDist + "% / 확인선 >" + confirmDist + "%");
    Logger.log("[고점 청산/강제매도 알림] 기준 설명: " + peakReason);
    Logger.log("[고점 청산/강제매도 알림] QQQ 주봉 RSI: " + qqqWeeklyRsi.toFixed(2) + ", 일봉 RSI: " + qqqDailyRsi.toFixed(2) + ", 전일 RSI: " + qqqDailyRsiPrev.toFixed(2));
    Logger.log("[고점 청산/강제매도 알림] RSI 조건(주봉/일봉≥65 & 일봉 하락): " + (peakState.isRsiConditionMet ? "YES" : "NO"));
    Logger.log("[고점 청산/강제매도 알림] MACD Hist: " + qqqMacdHist + " / 전일 " + qqqMacdHistD1 + " / 전전일 " + qqqMacdHistD2 + " → " + (peakState.isMacdSlowing ? "둔화" : "미충족"));
    Logger.log("[고점 청산/강제매도 알림] 최종 청산 시그널: " + (isPeakTriggered ? "TRIGGERED" : "NOT TRIGGERED"));
    Logger.log("[고점 청산/강제매도 알림] 이전 알림 상태: " + (lastPeakState ? "SENT" : "NOT SENT"));

    if (isPeakTriggered && !lastPeakState) {
      var emailSubject = "나스닥 고점 구간 알림 (매도 시그널)";
      var emailBody =
        '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#222;padding-top:8px;">' +
          '<p style="font-size:16px;font-weight:bold;color:#333;margin:0 0 12px 0;">' +
            "QQQ가 고점 과열 구간에 진입했으며, RSI 둔화 신호가 감지되었습니다." +
          "</p>" +
          '<div style="margin:0 0 14px 0;">' +
            '<div style="margin:4px 0;"><strong>QQQ 현재가:</strong> ' + currentPrice.toFixed(2) + "</div>" +
            '<div style="margin:4px 0;"><strong>QQQ 200일 이평선:</strong> ' + nasdaqMA200.toFixed(2) + "</div>" +
            '<div style="margin:4px 0;"><strong>200일선 대비:</strong> ' + (nasdaqPremiumPercent >= 0 ? "+" : "") + nasdaqPremiumPercent.toFixed(2) + "%</div>" +
            '<div style="margin:4px 0;"><strong>시장 국면:</strong> ' + regimeLabel + "</div>" +
            '<div style="margin:4px 0;"><strong>고점 기준:</strong> ' + peakReason + "</div>" +
          "</div>" +
          '<div style="margin:0 0 14px 0;">' +
            '<div style="margin:4px 0;"><strong>QQQ 주봉 RSI(14):</strong> ' + qqqWeeklyRsi.toFixed(2) + "</div>" +
            '<div style="margin:4px 0;"><strong>QQQ 일봉 RSI(14):</strong> ' + qqqDailyRsi.toFixed(2) + "</div>" +
            '<div style="margin:4px 0;"><strong>QQQ 일봉 RSI 전일:</strong> ' + qqqDailyRsiPrev.toFixed(2) + "</div>" +
            '<div style="margin:4px 0;"><strong>QQQ MACD Hist:</strong> ' + qqqMacdHist + " / " + qqqMacdHistD1 + " / " + qqqMacdHistD2 + "</div>" +
          "</div>" +
          '<p style="margin:0 0 12px 0;">' +
            "QQQ가 국면별 고점 청산 기준을 충족했습니다." +
            " 비회복장은 +16%와 +14% 확인선, 회복장은 +22%와 +18% 확인선을 사용하며," +
            " 확인선에서는 RSI 과열 하락과 MACD 둔화를 함께 확인합니다." +
            " 따라서 보유 중인 종목의 부분 매도 또는 일괄 매도를 신중히 고려하시기 바랍니다." +
          "</p>" +
          '<p style="margin:0 0 12px 0;">' +
            "단, 시장 전체의 방향성과 별개로 산업군·종목에 따라 개별 상승 모멘텀이 유효한 경우도 있으며," +
            " 금리·인플레이션 등 거시 지표나 주요 기업 실적발표 일정에 따라 국면이 달라질 수 있습니다." +
            " 매수 조건을 충족한 종목은 이후에도 시그널 메일이 발송될 수 있으나," +
            " 가급적 당분간은 신규 진입을 자제하고 개별 종목 단위의 진입 여부는 시황을 직접 확인한 후 스스로 판단하시기 바랍니다." +
          "</p>" +
          '<p style="margin:0 0 12px 0;">' +
            "※ 알림은 조건 충족 시 <strong>한 번만</strong> 발송되며, QQQ가 기준선 아래로 하락 시 재알림이 가능합니다." +
          "</p>" +
          '<p style="margin:0;">' +
            "발송 시각 (한국 날짜): " + kstDate + "<br>" +
            "발송 시각 (미 동부 시간): " + estString +
          "</p>" +
        "</div>";

      try {
        GmailApp.sendEmail(recipientEmail, emailSubject, "", { htmlBody: emailBody });
        Logger.log("[고점 청산/강제매도 알림 SUCCESS] 알림 발송 완료. 상태 TRUE 저장. (현재가: " + currentPrice.toFixed(2) + ")");
      } catch (e) {
        Logger.log("[고점 청산/강제매도 알림 FATAL] 이메일 발송 실패: " + e.toString());
      }
    } else {
      Logger.log("[고점 청산/강제매도 알림] 시그널 미감지 또는 이미 발송됨 — 스킵");
    }

    if (!isPeakTriggered && lastPeakState) {
      Logger.log("[고점 청산/강제매도 알림] QQQ가 국면별 청산 확인선 아래 또는 조건 미충족 상태로 전환. 상태 FALSE 초기화됨 (재알림 가능).");
    }
  } catch (e) {
    Logger.log("[고점 청산/강제매도 알림 FATAL] 처리 중 오류: " + e.toString());
  }
}
