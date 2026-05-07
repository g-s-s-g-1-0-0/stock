// =============================================
//  weeklyTrendUpdate.gs
//  매주 일요일 자동 실행 — 시장 트렌드 분석 & 기록
//  사전 준비: Script Properties에 GROQ_API_KEY 저장
//  무료 발급: console.groq.com (카드 불필요, 영구 무료)
// =============================================

const NEWS_SOURCES = [
  "https://www.cnbc.com/id/100003114/device/rss/rss.html",
  "https://www.cnbc.com/id/19854910/device/rss/rss.html",
  "https://feeds.marketwatch.com/marketwatch/topstories/",
  "https://finance.yahoo.com/news/rssindex",
  "https://trends.google.com/trending/rss?geo=US"
];

function weeklyTrendUpdate() {
  console.log("===== 주간 트렌드 업데이트 시작 =====");

  const newsText = fetchAllNews();
  console.log(`[뉴스 수집] ${newsText.length}자 수집`);

  const result = analyzeWithGroq(newsText);

  if (result.error) {
    console.log(`[Groq 실패] ${result.error}`);
    sendApiFailureEmail(result.error, result.httpCode);
    return;
  }

  if (!result.analysis || result.analysis.ranks.length === 0) {
    console.log("[실패] 분석 결과 없음 — 종료");
    return;
  }

  updateTrendSheet(result.analysis);
  sendTrendEmail(result.analysis);

  console.log("===== 주간 트렌드 업데이트 완료 =====");
}

function fetchAllNews() {
  const titles = [];
  NEWS_SOURCES.forEach(url => {
    try {
      const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
      if (res.getResponseCode() !== 200) {
        console.log(`[RSS 스킵] ${url} — HTTP ${res.getResponseCode()}`);
        return;
      }
      const matches = res.getContentText().match(/<title>(.*?)<\/title>/gs) || [];
      const before  = titles.length;
      matches.slice(1, 25).forEach(m => {
        const t = m.replace(/<\/?title>/gi, "").replace(/<!\[CDATA\[|\]\]>/g, "").trim();
        if (t) titles.push(t);
      });
      console.log(`[RSS 수집] ${url} — ${titles.length - before}건`);
    } catch (e) {
      console.log(`[RSS 오류] ${url}: ${e}`);
    }
  });
  console.log(`[뉴스 합계] ${titles.length}건`);
  return titles.join("\n");
}

function analyzeWithGroq(newsText) {
  const apiKey = PropertiesService.getScriptProperties().getProperty("GROQ_API_KEY");
  if (!apiKey) {
    return { error: "GROQ_API_KEY가 Script Properties에 설정되어 있지 않습니다.", httpCode: null };
  }

  const prompt = `다음은 이번 주 미국 금융·기술 뉴스 헤드라인입니다.
주식 시장에서 현재 가장 주목받는 섹터/테마를 1위부터 10위까지 순위를 매겨주세요.

[분석 기준]
- 단순 언급 빈도가 아닌, 실제 자금이 몰리고 있는 테마 중심
- "AI 인프라" 같은 넓은 개념도 이번 주 특히 주목받는 세부 요소로 구체화
  예) "AI인프라 | 광통신, 트랜시버" / "AI인프라 | 전력인프라, 데이터센터냉각"
- 각 순위마다 섹터명과 핵심 키워드 3~5개

[출력 형식 — 반드시 이 형식으로만 출력, 다른 설명 없이]
1위: 섹터명 | 키워드1, 키워드2, 키워드3
2위: 섹터명 | 키워드1, 키워드2, 키워드3
...
10위: 섹터명 | 키워드1, 키워드2, 키워드3
요약: 이번 주 전체 시장 분위기 한 줄

[뉴스 헤드라인]
${newsText.substring(0, 6000)}`;

  const payload = {
    model:       "llama-3.3-70b-versatile",
    messages:    [{ role: "user", content: prompt }],
    temperature: 0.3,
    max_tokens:  1024
  };

  try {
    const res      = UrlFetchApp.fetch(
      "https://api.groq.com/openai/v1/chat/completions",
      {
        method:             "post",
        contentType:        "application/json",
        headers:            { "Authorization": `Bearer ${apiKey}` },
        payload:            JSON.stringify(payload),
        muteHttpExceptions: true
      }
    );
    const rawText  = res.getContentText();
    const httpCode = res.getResponseCode();
    console.log(`[Groq HTTP] ${httpCode}`);
    console.log(`[Groq 원본] ${rawText.substring(0, 500)}`);

    if (httpCode === 401 || httpCode === 403) {
      return { error: `API 키 인증 실패 (HTTP ${httpCode}). 키가 만료되었거나 유효하지 않습니다.`, httpCode };
    }

    if (httpCode === 404) {
      return { error: `모델을 찾을 수 없음 (HTTP 404). llama-3.3-70b-versatile 모델이 deprecated 되었을 수 있습니다.`, httpCode };
    }

    if (httpCode >= 500) {
      return { error: `Groq 서버 오류 (HTTP ${httpCode}). 일시적 장애일 수 있습니다.`, httpCode };
    }

    const json = JSON.parse(rawText);
    if (json.error) {
      const errMsg = `${json.error.type || "unknown"}: ${json.error.message || "상세 없음"}`;
      const isAuthError = /invalid.*key|expired|unauthorized|authentication/i.test(json.error.message || "");
      const isModelError = /model.*not.*found|deprecated|decommission/i.test(json.error.message || "");
      if (isAuthError || isModelError || httpCode >= 400) {
        return { error: `Groq API 오류 — ${errMsg}`, httpCode };
      }
      console.log(`[Groq API 오류] ${errMsg}`);
      return { analysis: null };
    }

    if (httpCode !== 200) {
      return { error: `Groq 비정상 응답 (HTTP ${httpCode}): ${rawText.substring(0, 300)}`, httpCode };
    }

    const text = json?.choices?.[0]?.message?.content || null;
    if (!text) {
      console.log("[Groq] 텍스트 없음");
      return { analysis: null };
    }
    console.log(`[Groq 응답]\n${text}`);
    return { analysis: parseTrendAnalysis(text) };
  } catch (e) {
    return { error: `Groq 호출 중 예외 발생: ${e}`, httpCode: null };
  }
}

function parseTrendAnalysis(text) {
  const ranks = [];
  let summary = "";
  text.split("\n").forEach(line => {
    const rm = line.match(/^(\d+)위:\s*(.+?)\s*\|\s*(.+)$/);
    if (rm) ranks.push({ rank: parseInt(rm[1]), sector: rm[2].trim(), keywords: rm[3].trim() });
    const sm = line.match(/^요약:\s*(.+)$/);
    if (sm) summary = sm[1].trim();
  });
  return { ranks, summary };
}

function updateTrendSheet(analysis) {
  const activeSheet       = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("기술분석");
  const spreadsheetId     = activeSheet.getRange("I1").getValue();
  const targetSpreadsheet = SpreadsheetApp.openById(spreadsheetId);
  const trendSheet        = targetSpreadsheet.getSheetByName("시장트렌드");

  if (!trendSheet) { console.log("[오류] 시장트렌드 시트 없음"); return; }

  if (trendSheet.getLastRow() === 0) {
    const headers = ["날짜", "1위", "2위", "3위", "4위", "5위", "6위", "7위", "8위", "9위", "10위", "시장요약"];
    trendSheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight("bold");
    trendSheet.setFrozenRows(1);
    trendSheet.setColumnWidth(1, 100);
    trendSheet.setColumnWidths(2, 10, 180);
    trendSheet.setColumnWidth(12, 300);
  }

  const kstDate = Utilities.formatDate(new Date(), "Asia/Seoul", "yyyy.MM.dd");
  const row = [kstDate];
  for (let i = 1; i <= 10; i++) {
    const r = analysis.ranks.find(r => r.rank === i);
    row.push(r ? `${r.sector} | ${r.keywords}` : "-");
  }
  row.push(analysis.summary);
  trendSheet.appendRow(row);
  console.log(`[시트 기록] ${kstDate} 완료`);
}

function sendTrendEmail(analysis) {
  const activeSheet       = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("기술분석");
  const spreadsheetId     = activeSheet.getRange("I1").getValue();
  const targetSpreadsheet = SpreadsheetApp.openById(spreadsheetId);
  const recipientEmail    = targetSpreadsheet.getSheetByName("기술분석").getRange("F1").getValue();

  if (!recipientEmail) { console.log("[이메일 실패] F1 셀 이메일 없음"); return; }

  const kstDate   = Utilities.formatDate(new Date(), "Asia/Seoul", "yyyy.MM.dd");
  const ranksHtml = analysis.ranks.map(r =>
    `<div style="padding:7px 0;border-bottom:1px solid #f0f0f0;font-size:14px;">
      <span style="color:#aaa;min-width:32px;display:inline-block;">${r.rank}위</span>
      <strong style="color:#222;">${r.sector}</strong>
      <span style="color:#666;margin-left:8px;font-size:13px;">${r.keywords}</span>
    </div>`
  ).join("");

  const emailBody = `
  <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.7;max-width:600px;">
    <p style="font-size:16px;font-weight:bold;color:#333;border-bottom:2px solid #eee;padding-bottom:8px;">
      주간 시장 트렌드 리포트 (${kstDate})
    </p>
    <div style="margin:12px 0;">${ranksHtml}</div>
    <div style="margin-top:16px;padding:10px 14px;background:#f0f7ff;border-left:3px solid #3498db;font-size:13px;color:#333;">
      ※ ${analysis.summary}
    </div>
    <p style="color:#bbb;font-size:11px;margin-top:20px;">매주 일요일 자동 발송</p>
  </div>`;

  try {
    GmailApp.sendEmail(recipientEmail, `[주간 트렌드] 시장 트렌드 리포트 (${kstDate})`, "", { htmlBody: emailBody });
    console.log(`[이메일 발송] → ${recipientEmail}`);
  } catch (e) {
    console.log(`[이메일 오류] ${e}`);
  }
}

function sendApiFailureEmail(errorDetail, httpCode) {
  let recipientEmail;
  try {
    const activeSheet       = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("기술분석");
    const spreadsheetId     = activeSheet.getRange("I1").getValue();
    const targetSpreadsheet = SpreadsheetApp.openById(spreadsheetId);
    recipientEmail          = targetSpreadsheet.getSheetByName("기술분석").getRange("F1").getValue();
  } catch (e) {
    console.log(`[알림 메일 실패] 이메일 주소 조회 오류: ${e}`);
    return;
  }

  if (!recipientEmail) {
    console.log("[알림 메일 실패] F1 셀 이메일 없음");
    return;
  }

  const kstDate = Utilities.formatDate(new Date(), "Asia/Seoul", "yyyy.MM.dd HH:mm");

  const emailBody = `
  <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.8;max-width:600px;">
    <p style="font-size:16px;font-weight:bold;color:#d32f2f;border-bottom:2px solid #ffcdd2;padding-bottom:8px;">
      Groq API 키 갱신 필요
    </p>

    <div style="margin:16px 0;padding:12px 16px;background:#fff3e0;border-left:3px solid #ff9800;font-size:13px;color:#333;">
      <strong>오류 내용:</strong> ${errorDetail}${httpCode ? ` (HTTP ${httpCode})` : ""}
    </div>

    <p style="margin-top:20px;font-weight:bold;color:#333;">1. 새 API 키 발급:</p>
    <ol style="padding-left:20px;color:#444;font-size:13px;">
      <li><a href="https://console.groq.com" style="color:#1976d2;">console.groq.com</a> 접속 → 로그인</li>
      <li>좌측 메뉴 <strong>API Keys</strong> 클릭</li>
      <li><strong>Create API Key</strong> 클릭 → 이름 입력 → 생성</li>
      <li>생성된 키 복사 (<code>gsk_</code>로 시작하는 문자열)</li>
    </ol>

    <p style="margin-top:20px;font-weight:bold;color:#333;">2. 스크립트에 새 키 적용:</p>
    <ol style="padding-left:20px;color:#444;font-size:13px;">
      <li>Apps Script 에디터에서 <code>setGroqApiKey()</code> 함수 찾기</li>
      <li>기존 키 값을 새로 복사한 키로 교체</li>
      <li>상단 함수 선택 드롭다운에서 <code>setGroqApiKey</code> 선택 → <strong>▶ 실행</strong></li>
    </ol>

    <div style="margin-top:20px;padding:10px 14px;background:#e8f5e9;border-left:3px solid #4caf50;font-size:12px;color:#555;">
      실행 완료 후 별도 조치 없이 다음 일요일 트리거에서 자동 적용됩니다.
    </div>

    <p style="color:#bbb;font-size:11px;margin-top:24px;">발생 시각: ${kstDate} (KST)</p>
  </div>`;

  try {
    GmailApp.sendEmail(
      recipientEmail,
      `[긴급] 주간 트렌드 — Groq API 키 갱신 필요`,
      "",
      { htmlBody: emailBody }
    );
    console.log(`[API 실패 알림] 이메일 발송 완료 → ${recipientEmail}`);
  } catch (e) {
    console.log(`[API 실패 알림 이메일 오류] ${e}`);
  }
}