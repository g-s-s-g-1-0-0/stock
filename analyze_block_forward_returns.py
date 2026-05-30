"""
analyze_block_forward_returns.py
================================
완결 트레이드는 회복장>18% 표본이 거의 없으므로,
'사건연구(event study)'로 더 많은 표본을 확보한다.

질문: QQQ 이격도 구간별로, '매수할 만한 강한 종목'(MA200 위 + RSI 55~80 + 종가%B>60 + MACD hist>0)을
      그날 진입했다면 향후 20/40/60거래일 수익률은 어땠나?
      차단 구간(QQQ>9%, >18%)에서도 plus였나?
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calculator.indicators import add_indicators
from calculator import market_regime as mr
from backtest_qqq_block_improved import dl, build_qqq_state, US_TICKERS, EVAL_START

FWD = [20, 40, 60]


def main():
    qqq = dl("QQQ")
    qstate = build_qqq_state(qqq)
    rows = []
    for t in US_TICKERS:
        df = dl(t)
        if df is None or len(df) < 260:
            continue
        d = add_indicators(df).join(qstate, how="inner")
        c = d["Close"].to_numpy()
        n = len(d)
        for i in range(n):
            ts = d.index[i]
            if ts < EVAL_START:
                continue
            prem = d["premium"].iloc[i]
            if pd.isna(prem):
                continue
            ma200 = d["MA200"].iloc[i]; rsi = d["RSI"].iloc[i]
            pctb = d["PctB"].iloc[i]; mh = d["MACD_Hist"].iloc[i]
            if pd.isna(ma200) or pd.isna(rsi) or pd.isna(pctb) or pd.isna(mh):
                continue
            strong = (c[i] > ma200) and (55 <= rsi <= 80) and (pctb > 60) and (mh > 0)
            if not strong:
                continue
            fwd = {}
            ok = True
            for h in FWD:
                if i + h < n:
                    fwd[h] = c[i + h] / c[i] - 1
                else:
                    ok = False
            if not ok:
                continue
            rows.append({"prem": float(prem), "recovery": bool(d["recovery"].iloc[i]),
                         **{f"f{h}": fwd[h] for h in FWD}})
    df = pd.DataFrame(rows)
    print(f"강한 모멘텀 종목-일 표본: {len(df)}건\n")

    buckets = [("≤0%", df.prem <= 0), ("0~9%", (df.prem > 0) & (df.prem <= 9)),
               ("9~18%", (df.prem > 9) & (df.prem <= 18)), (">18%", df.prem > 18)]
    print("=" * 88)
    print("QQQ 이격도 구간별 — 강한 모멘텀 종목 향후 수익률 (전체 레짐)")
    print("=" * 88)
    print(f"{'구간':8} {'표본':>6} {'f20평균':>9} {'f20승률':>8} {'f40평균':>9} {'f40승률':>8} {'f60평균':>9} {'f60승률':>8}")
    for label, mask in buckets:
        s = df[mask]
        if len(s) == 0:
            print(f"{label:8} {0:>6}")
            continue
        def stat(h):
            r = s[f"f{h}"]
            return r.mean() * 100, (r > 0).mean() * 100
        a20, w20 = stat(20); a40, w40 = stat(40); a60, w60 = stat(60)
        print(f"{label:8} {len(s):>6} {a20:>8.2f}% {w20:>7.1f}% {a40:>8.2f}% {w40:>7.1f}% {a60:>8.2f}% {w60:>7.1f}%")

    print("\n" + "=" * 88)
    print("회복장으로 한정 — 강한 모멘텀 종목 향후 수익률")
    print("=" * 88)
    rec = df[df.recovery]
    print(f"회복장 표본 {len(rec)}건")
    rbuckets = [("0~9%", (rec.prem > 0) & (rec.prem <= 9)),
                ("9~18%", (rec.prem > 9) & (rec.prem <= 18)), (">18%", rec.prem > 18)]
    print(f"{'구간':8} {'표본':>6} {'f20평균':>9} {'f20승률':>8} {'f40평균':>9} {'f60평균':>9}")
    for label, mask in rbuckets:
        s = rec[mask]
        if len(s) == 0:
            print(f"{label:8} {0:>6}")
            continue
        print(f"{label:8} {len(s):>6} {s.f20.mean()*100:>8.2f}% {(s.f20>0).mean()*100:>7.1f}% "
              f"{s.f40.mean()*100:>8.2f}% {s.f60.mean()*100:>8.2f}%")


if __name__ == "__main__":
    main()
