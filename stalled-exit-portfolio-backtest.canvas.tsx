import React from 'react'

const results = [
  {
    slots: 5,
    current: { totalReturn: 1095.58, cagr: 5.63, mdd: -39.78, trades: 1339, winRate: 52.7, avgHold: 6.6, exposure: 15.8, turnover: 5.91, stalled: 1191 },
    without: { totalReturn: 1294.63, cagr: 5.99, mdd: -72.46, trades: 440, winRate: 71.8, avgHold: 49.4, exposure: 38.6, turnover: 1.94, stalled: 0 },
  },
  {
    slots: 10,
    current: { totalReturn: 479.85, cagr: 3.96, mdd: -37.02, trades: 1567, winRate: 53.7, avgHold: 6.5, exposure: 9.1, turnover: 3.46, stalled: 1379 },
    without: { totalReturn: 1593.78, cagr: 6.44, mdd: -58.25, trades: 731, winRate: 73.2, avgHold: 49.0, exposure: 31.9, turnover: 1.61, stalled: 0 },
  },
  {
    slots: 15,
    current: { totalReturn: 290.03, cagr: 3.05, mdd: -31.42, trades: 1609, winRate: 53.9, avgHold: 6.6, exposure: 6.3, turnover: 2.37, stalled: 1409 },
    without: { totalReturn: 1485.28, cagr: 6.29, mdd: -50.03, trades: 906, winRate: 74.1, avgHold: 46.8, exposure: 25.2, turnover: 1.33, stalled: 0 },
  },
  {
    slots: 20,
    current: { totalReturn: 187.0, cagr: 2.35, mdd: -24.28, trades: 1619, winRate: 54.1, avgHold: 6.6, exposure: 4.8, turnover: 1.79, stalled: 1418 },
    without: { totalReturn: 1153.79, cagr: 5.74, mdd: -41.54, trades: 989, winRate: 74.3, avgHold: 45.6, exposure: 20.1, turnover: 1.09, stalled: 0 },
  },
]

const savedLosses = [
  ['ACLS', 'F', '2008-06-24', -6.51, -74.14, 67.63],
  ['000150', 'B', '2020-02-27', 2.38, -37.93, 40.31],
  ['ACLS', 'F', '2007-03-14', 4.08, -34.42, 38.5],
  ['STX', 'F', '2011-06-16', 4.46, -33.97, 38.43],
  ['LITE', 'F', '2018-09-12', -0.74, -38.22, 37.48],
  ['SOXL', 'F', '2011-04-18', 3.64, -33.46, 37.09],
  ['039030', 'E', '2016-04-07', 2.02, -34.99, 37.02],
  ['TSLA', 'E', '2018-11-28', 4.37, -32.41, 36.77],
]

const missedRebounds = [
  ['AEHR', 'F', '2022-12-28', -13.22, 55.55, -68.77],
  ['IREN', 'F', '2023-09-28', -16.45, 30.9, -47.35],
  ['CIFR', 'F', '2023-09-28', 2.51, 47.28, -44.77],
  ['CRDO', 'F', '2024-04-17', -4.36, 40.24, -44.59],
  ['SNDK', 'E', '2026-02-26', -13.24, 30.66, -43.9],
]

function pct(value: number) {
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {children}
    </section>
  )
}

export default function StalledExitPortfolioBacktest() {
  return (
    <main className="wrap">
      <style>{`
        .wrap { font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 28px; color: #111827; background: #f8fafc; min-height: 100vh; }
        h1 { font-size: 28px; margin: 0 0 8px; letter-spacing: -0.03em; }
        h2 { font-size: 18px; margin: 0 0 14px; letter-spacing: -0.02em; }
        p { margin: 6px 0; color: #475569; line-height: 1.55; }
        .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }
        .metric { background: #fff; border: 1px solid #e5e7eb; border-radius: 16px; padding: 16px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }
        .metric b { display: block; font-size: 24px; letter-spacing: -0.03em; margin-top: 6px; }
        .card { background: #fff; border: 1px solid #e5e7eb; border-radius: 18px; padding: 18px; margin: 14px 0; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05); }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { padding: 10px 9px; border-bottom: 1px solid #eef2f7; text-align: right; white-space: nowrap; }
        th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
        th { color: #64748b; font-weight: 700; background: #f8fafc; }
        .good { color: #047857; font-weight: 700; }
        .bad { color: #dc2626; font-weight: 700; }
        .note { padding: 12px 14px; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 14px; color: #9a3412; }
        .pill { display: inline-flex; gap: 6px; align-items: center; padding: 6px 10px; border-radius: 999px; background: #eef2ff; color: #3730a3; font-size: 12px; font-weight: 700; margin-right: 6px; }
      `}</style>

      <h1>5거래일 +5% 반등 미달 청산: 회전율 포함 백테스트</h1>
      <p>
        현재 어드민 관심종목 캐시 35개 기준. 기간은 확보 가능한 최대 일봉 기준 1981-01-29 ~ 2026-05-22이며,
        미국 주식은 Yahoo 최대 일봉을 adjclose 비율로 분할 보정했습니다.
      </p>
      <p>
        신규 진입은 당시 총자산을 슬롯 수로 나눈 금액만큼 배분하고, 슬롯이 차 있으면 다음 신호를 놓치는 방식으로 회전율을 반영했습니다.
      </p>

      <div className="grid">
        <div className="metric">원시 매수 신호<b>5,112</b></div>
        <div className="metric">관심종목<b>35개</b></div>
        <div className="metric">대표 비교 슬롯<b>10개</b></div>
        <div className="metric">대표 결론<b className="bad">수익률 훼손</b></div>
      </div>

      <Card title="슬롯별 핵심 결과">
        <table>
          <thead>
            <tr>
              <th>슬롯</th>
              <th>조건</th>
              <th>총수익</th>
              <th>CAGR</th>
              <th>MDD</th>
              <th>거래수</th>
              <th>승률</th>
              <th>평균보유</th>
              <th>노출</th>
              <th>회전율/슬롯/년</th>
            </tr>
          </thead>
          <tbody>
            {results.flatMap((row) => [
              <tr key={`${row.slots}-current`}>
                <td>{row.slots}</td>
                <td>현재: 반등 미달 청산 유지</td>
                <td>{pct(row.current.totalReturn)}</td>
                <td>{pct(row.current.cagr)}</td>
                <td className="good">{pct(row.current.mdd)}</td>
                <td>{row.current.trades}</td>
                <td>{pct(row.current.winRate)}</td>
                <td>{row.current.avgHold}일</td>
                <td>{pct(row.current.exposure)}</td>
                <td>{row.current.turnover}</td>
              </tr>,
              <tr key={`${row.slots}-without`}>
                <td>{row.slots}</td>
                <td>제거: 기존 목표/손절/시간청산만</td>
                <td className="good">{pct(row.without.totalReturn)}</td>
                <td className="good">{pct(row.without.cagr)}</td>
                <td className="bad">{pct(row.without.mdd)}</td>
                <td>{row.without.trades}</td>
                <td className="good">{pct(row.without.winRate)}</td>
                <td>{row.without.avgHold}일</td>
                <td>{pct(row.without.exposure)}</td>
                <td>{row.without.turnover}</td>
              </tr>,
            ])}
          </tbody>
        </table>
      </Card>

      <Card title="해석">
        <p>
          반등 미달 청산은 의도대로 거래를 빠르게 닫습니다. 10슬롯 기준 평균 보유일은 49.0일에서 6.5일로 줄고,
          회전율은 슬롯당 연 1.61회에서 3.46회로 올라갑니다.
        </p>
        <p>
          하지만 최대기간 포트폴리오 결과에서는 이 빠른 청산이 수익률을 크게 깎았습니다. 10슬롯 기준 총수익은
          +1,593.78%에서 +479.85%로 낮아졌고, CAGR도 +6.44%에서 +3.96%로 내려갔습니다.
        </p>
        <p className="note">
          대신 방어 효과는 분명합니다. 10슬롯 기준 MDD는 -58.25%에서 -37.02%로 개선됩니다.
          즉 이 규칙은 수익 극대화 규칙이라기보다 최대낙폭을 줄이는 방어형 규칙에 가깝습니다.
        </p>
      </Card>

      <Card title="10슬롯 기준: 손실을 막은 사례">
        <table>
          <thead>
            <tr><th>티커</th><th>전략</th><th>진입일</th><th>청산 유지</th><th>청산 제거</th><th>개선폭</th></tr>
          </thead>
          <tbody>
            {savedLosses.map((row) => (
              <tr key={`${row[0]}-${row[2]}`}>
                <td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td>
                <td>{pct(row[3] as number)}</td><td className="bad">{pct(row[4] as number)}</td><td className="good">{pct(row[5] as number)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="10슬롯 기준: 놓친 큰 반등 사례">
        <table>
          <thead>
            <tr><th>티커</th><th>전략</th><th>진입일</th><th>청산 유지</th><th>청산 제거</th><th>손실폭</th></tr>
          </thead>
          <tbody>
            {missedRebounds.map((row) => (
              <tr key={`${row[0]}-${row[2]}`}>
                <td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td>
                <td className="bad">{pct(row[3] as number)}</td><td className="good">{pct(row[4] as number)}</td><td className="bad">{pct(row[5] as number)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="판단">
        <p>
          공격형 성향이면 현재의 전 그룹 공통 5거래일 +5% 규칙은 너무 빠릅니다.
          특히 E/F/G처럼 눌림 후 반등을 기다리는 전략에서 큰 반등을 잘라내는 비용이 큽니다.
        </p>
        <p>
          내 판단은 “전면 유지”보다는 완화입니다.
          A/D 같은 속도형에는 일부 유지하고, E/F/G는 10거래일 또는 -손실 상태일 때만 청산하는 식으로 바꾸는 편이 더 맞습니다.
        </p>
      </Card>

      <div>
        <span className="pill">과거 이벤트 캘린더 제외</span>
        <span className="pill">동일 티커 추가진입은 -10%/10거래일 근사</span>
        <span className="pill">세금·수수료 제외</span>
      </div>
    </main>
  )
}
