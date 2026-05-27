import React from 'react'

const baseline = {
  label: '반등 미달 청산 제거',
  totalReturn: 1635.22,
  cagr: 6.5,
  mdd: -57.22,
  trades: 732,
  winRate: 73.4,
  avgHold: 49.0,
}

const grid = [
  { days: 3, threshold: 1, totalReturn: 639.71, cagr: 4.52, mdd: -33.73, trades: 1543, winRate: 35.3, avgHold: 7.8, stalled: 1281, delta: -995.51 },
  { days: 3, threshold: 2, totalReturn: 489.25, cagr: 3.99, mdd: -31.85, trades: 1611, winRate: 43.8, avgHold: 6.4, stalled: 1389, delta: -1145.97 },
  { days: 3, threshold: 3, totalReturn: 481.87, cagr: 3.96, mdd: -30.96, trades: 1670, winRate: 48.4, avgHold: 5.4, stalled: 1479, delta: -1153.35 },
  { days: 3, threshold: 5, totalReturn: 316.96, cagr: 3.2, mdd: -30.37, trades: 1737, winRate: 51.4, avgHold: 4.2, stalled: 1594, delta: -1318.26 },
  { days: 3, threshold: 8, totalReturn: 299.35, cagr: 3.1, mdd: -28.94, trades: 1780, winRate: 53.1, avgHold: 3.4, stalled: 1682, delta: -1335.87 },
  { days: 5, threshold: 1, totalReturn: 825.34, cagr: 5.03, mdd: -42.72, trades: 1413, winRate: 36.9, avgHold: 10.0, stalled: 1121, delta: -809.88 },
  { days: 5, threshold: 2, totalReturn: 679.72, cagr: 4.64, mdd: -38.01, trades: 1460, winRate: 45.6, avgHold: 8.8, stalled: 1198, delta: -955.5 },
  { days: 5, threshold: 3, totalReturn: 553.59, cagr: 4.23, mdd: -37.47, trades: 1503, winRate: 49.8, avgHold: 7.9, stalled: 1273, delta: -1081.63 },
  { days: 5, threshold: 5, totalReturn: 478.12, cagr: 3.95, mdd: -37.02, trades: 1570, winRate: 53.7, avgHold: 6.5, stalled: 1382, delta: -1157.1 },
  { days: 5, threshold: 8, totalReturn: 415.61, cagr: 3.69, mdd: -37.02, trades: 1610, winRate: 55.1, avgHold: 5.6, stalled: 1474, delta: -1219.61 },
  { days: 7, threshold: 1, totalReturn: 1570.5, cagr: 6.41, mdd: -35.46, trades: 1324, winRate: 39.2, avgHold: 12.0, stalled: 993, delta: -64.72 },
  { days: 7, threshold: 2, totalReturn: 1309.78, cagr: 6.01, mdd: -35.46, trades: 1368, winRate: 46.9, avgHold: 10.8, stalled: 1063, delta: -325.44 },
  { days: 7, threshold: 3, totalReturn: 1031.5, cagr: 5.5, mdd: -35.46, trades: 1399, winRate: 50.7, avgHold: 10.0, stalled: 1120, delta: -603.72 },
  { days: 7, threshold: 5, totalReturn: 1051.87, cagr: 5.54, mdd: -35.46, trades: 1448, winRate: 53.8, avgHold: 8.7, stalled: 1205, delta: -583.35 },
  { days: 7, threshold: 8, totalReturn: 1097.16, cagr: 5.63, mdd: -35.46, trades: 1489, winRate: 54.9, avgHold: 7.7, stalled: 1281, delta: -538.06 },
  { days: 10, threshold: 1, totalReturn: 1767.07, cagr: 6.67, mdd: -31.81, trades: 1191, winRate: 40.2, avgHold: 15.0, stalled: 833, delta: 131.85 },
  { days: 10, threshold: 2, totalReturn: 1579.61, cagr: 6.42, mdd: -31.81, trades: 1228, winRate: 46.4, avgHold: 13.9, stalled: 899, delta: -55.61 },
  { days: 10, threshold: 3, totalReturn: 1463.4, cagr: 6.26, mdd: -32.28, trades: 1250, winRate: 49.9, avgHold: 13.1, stalled: 940, delta: -171.82 },
  { days: 10, threshold: 5, totalReturn: 1560.41, cagr: 6.4, mdd: -32.28, trades: 1294, winRate: 53.1, avgHold: 11.8, stalled: 1007, delta: -74.81 },
  { days: 10, threshold: 8, totalReturn: 1759.63, cagr: 6.66, mdd: -32.28, trades: 1343, winRate: 55.0, avgHold: 10.6, stalled: 1091, delta: 124.41 },
  { days: 15, threshold: 1, totalReturn: 2367.88, cagr: 7.33, mdd: -35.0, trades: 1088, winRate: 44.3, avgHold: 19.2, stalled: 698, delta: 732.66 },
  { days: 15, threshold: 2, totalReturn: 1859.14, cagr: 6.79, mdd: -36.09, trades: 1113, winRate: 49.2, avgHold: 18.3, stalled: 749, delta: 223.92 },
  { days: 15, threshold: 3, totalReturn: 1903.51, cagr: 6.84, mdd: -34.79, trades: 1130, winRate: 51.9, avgHold: 17.6, stalled: 780, delta: 268.29 },
  { days: 15, threshold: 5, totalReturn: 1799.33, cagr: 6.71, mdd: -34.13, trades: 1169, winRate: 55.0, avgHold: 16.3, stalled: 848, delta: 164.11 },
  { days: 15, threshold: 8, totalReturn: 1717.46, cagr: 6.61, mdd: -33.76, trades: 1193, winRate: 56.4, avgHold: 15.2, stalled: 906, delta: 82.24 },
]

const bestReturn = [...grid].sort((a, b) => b.totalReturn - a.totalReturn)[0]
const current = grid.find((row) => row.days === 5 && row.threshold === 5)!
const fiveThree = grid.find((row) => row.days === 5 && row.threshold === 3)!

function pct(value: number) {
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function cls(value: number) {
  return value >= 0 ? 'good' : 'bad'
}

export default function StalledExitGridBacktest() {
  return (
    <main className="wrap">
      <style>{`
        .wrap { min-height: 100vh; padding: 28px; background: #f8fafc; color: #111827; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
        h1 { margin: 0 0 8px; font-size: 28px; letter-spacing: -0.03em; }
        h2 { margin: 0 0 12px; font-size: 18px; letter-spacing: -0.02em; }
        p { margin: 6px 0; line-height: 1.55; color: #475569; }
        .cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }
        .card, .panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 18px; box-shadow: 0 8px 24px rgba(15,23,42,.05); }
        .card { padding: 16px; }
        .card span { display: block; color: #64748b; font-size: 12px; font-weight: 700; }
        .card b { display: block; margin-top: 6px; font-size: 24px; letter-spacing: -0.03em; }
        .panel { padding: 18px; margin: 14px 0; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { padding: 9px 8px; border-bottom: 1px solid #eef2f7; text-align: right; white-space: nowrap; }
        th:first-child, td:first-child { text-align: left; }
        th { color: #64748b; background: #f8fafc; font-weight: 800; }
        .good { color: #047857; font-weight: 800; }
        .bad { color: #dc2626; font-weight: 800; }
        .muted { color: #64748b; }
        .note { padding: 12px 14px; border: 1px solid #bfdbfe; background: #eff6ff; border-radius: 14px; color: #1e40af; }
        .warn { padding: 12px 14px; border: 1px solid #fed7aa; background: #fff7ed; border-radius: 14px; color: #9a3412; }
      `}</style>

      <h1>반등 미달 청산 조합 그리드</h1>
      <p>
        현재 어드민 관심종목 35개, 10슬롯 포트폴리오, 최대 확보 일봉 1981-01-29 ~ 2026-05-22 기준입니다.
        미국 주식은 Yahoo 최대 일봉을 adjclose 비율로 분할 보정했습니다.
      </p>
      <p>
        이 표는 현재 코드와 같은 방식입니다. 즉 “N거래일째 현재 수익률이 +X% 미만이면 청산”입니다.
        “N일 안에 한 번이라도 +X% 터치하면 통과” 방식은 별도 상태 추적이 필요합니다.
      </p>

      <div className="cards">
        <div className="card"><span>기준: 반등 미달 청산 제거</span><b>{pct(baseline.totalReturn)}</b><p>CAGR {pct(baseline.cagr)}, MDD {pct(baseline.mdd)}</p></div>
        <div className="card"><span>현재 5일/+5%</span><b className="bad">{pct(current.totalReturn)}</b><p>CAGR {pct(current.cagr)}, MDD {pct(current.mdd)}</p></div>
        <div className="card"><span>질문한 5일/+3%</span><b className="bad">{pct(fiveThree.totalReturn)}</b><p>CAGR {pct(fiveThree.cagr)}, MDD {pct(fiveThree.mdd)}</p></div>
        <div className="card"><span>최고 총수익</span><b className="good">{bestReturn.days}일/+{bestReturn.threshold}%</b><p>{pct(bestReturn.totalReturn)}, CAGR {pct(bestReturn.cagr)}</p></div>
      </div>

      <section className="panel">
        <h2>전체 그리드</h2>
        <table>
          <thead>
            <tr>
              <th>조건</th>
              <th>총수익</th>
              <th>제거 대비</th>
              <th>CAGR</th>
              <th>MDD</th>
              <th>거래수</th>
              <th>승률</th>
              <th>평균보유</th>
              <th>청산수</th>
            </tr>
          </thead>
          <tbody>
            {grid.map((row) => (
              <tr key={`${row.days}-${row.threshold}`}>
                <td>{row.days}거래일 / +{row.threshold}%</td>
                <td className={cls(row.totalReturn - baseline.totalReturn)}>{pct(row.totalReturn)}</td>
                <td className={cls(row.delta)}>{pct(row.delta)}</td>
                <td>{pct(row.cagr)}</td>
                <td>{pct(row.mdd)}</td>
                <td>{row.trades}</td>
                <td>{pct(row.winRate)}</td>
                <td>{row.avgHold.toFixed(1)}일</td>
                <td>{row.stalled}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2>해석</h2>
        <p className="warn">
          5거래일 계열은 전부 기준선보다 나쁩니다. +3%로 낮춰도 총수익 +553.59%, CAGR +4.23%라서,
          반등 미달 청산 제거 기준의 +1,635.22%, CAGR +6.50%를 크게 밑돕니다.
        </p>
        <p className="note">
          반대로 10~15거래일로 늦추면 결과가 달라집니다. 10일/+1%, 10일/+8%, 15일/+1~8%는
          기준선보다 MDD를 크게 줄이면서 총수익도 같거나 더 높았습니다.
        </p>
        <p>
          내 선택은 공격형이면 15거래일/+1% 또는 15거래일/+3%입니다. 더 보수적으로 낙폭을 줄이고 싶으면 10거래일/+1%가 균형점입니다.
          현재 5거래일/+5%는 너무 많은 반등 후보를 초기에 잘라냅니다.
        </p>
      </section>
    </main>
  )
}
