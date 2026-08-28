"""TE·COHR이 실제로 '전략 4 조건'에 걸리는 종목인지 원자료로 확인.

ma200_macd_slope.py에서 COHR은 최근 400일 신호가 0건으로 나왔다. 조건을 못
만족한 건지 데이터 문제인지 가르려고 MA200 위치와 MACD 상태를 직접 본다.
TE는 신호가 34건인데 날짜가 붙어 있어서, 연속일을 하나의 사건으로 묶어
'독립 사건'이 몇 번이었는지 다시 센다.
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calculator.indicators import add_indicators
from ma200_macd_golden import dl

TICKERS = ["TE", "COHR"]


def prep(t: str) -> pd.DataFrame:
    d = add_indicators(dl(t)).dropna(subset=["MA200", "MACD_Hist", "MACD_Hist_D1",
                                             "MACD_Hist_D2"])
    d["below200"] = d["Close"] < d["MA200"]
    d["distMA200"] = (d["Close"] / d["MA200"] - 1) * 100
    d["golden"] = (d["MACD_Hist_D1"] <= 0) & (d["MACD_Hist"] > 0)
    d["histUp2"] = (d["MACD_Hist"] > d["MACD_Hist_D1"]) & (d["MACD_Hist_D1"] > d["MACD_Hist_D2"])
    return d


def ma200_position(d: pd.DataFrame, t: str) -> None:
    last = d[d.index >= d.index.max() - pd.Timedelta(days=400)]
    below = last["below200"]
    print(f"\n▸ {t} — 최근 400일 MA200 위치")
    print(f"  거래일 {len(last)}일 중 MA200 아래 {int(below.sum())}일 "
          f"({below.mean() * 100:.1f}%)")
    print(f"  현재가 {last['Close'].iloc[-1]:.2f} / MA200 {last['MA200'].iloc[-1]:.2f} "
          f"→ 이격 {last['distMA200'].iloc[-1]:+.1f}%")
    if below.any():
        runs, cur = [], None
        for dt, v in below.items():
            if v and cur is None:
                cur = dt
            elif not v and cur is not None:
                runs.append((cur, dt))
                cur = None
        if cur is not None:
            runs.append((cur, last.index[-1]))
        print(f"  MA200 아래에 머문 구간 {len(runs)}개:")
        for a, b in runs[-6:]:
            print(f"    {a.date()} ~ {b.date()} ({(b - a).days}일)")
    else:
        print("  최근 400일 동안 MA200 아래로 내려간 적이 한 번도 없음")

    gc = last[last["golden"]]
    print(f"  MACD 골든크로스 {len(gc)}회 · 그중 MA200 아래에서 발생 "
          f"{int(gc['below200'].sum())}회")
    if len(gc):
        show = gc[["Close", "MA200", "distMA200", "below200"]].tail(8).round(2)
        show.index = show.index.date
        print(show.to_string())


def episodes(d: pd.DataFrame, t: str) -> None:
    """연속된 신호일을 하나의 사건으로 묶는다 (5거래일 이내면 같은 사건)."""
    sig = d[d["below200"] & (d["golden"] | d["histUp2"])]
    if sig.empty:
        print(f"\n▸ {t} — 전체 기간 신호 없음")
        return
    idx = {dt: i for i, dt in enumerate(d.index)}
    pos = np.array([idx[x] for x in sig.index])
    breaks = np.flatnonzero(np.diff(pos) > 5)
    groups = np.split(pos, breaks + 1)
    cl = d["Close"].to_numpy()
    rows = []
    for g in groups:
        i0 = g[0]
        if i0 + 21 >= len(cl):
            continue
        ep = cl[i0]
        rows.append({"시작": d.index[i0].date(), "신호일수": len(g),
                     "20일%": round((cl[i0 + 20] / ep - 1) * 100, 1)})
    ep_df = pd.DataFrame(rows)
    print(f"\n▸ {t} — 전체 기간 신호 {len(sig)}건이지만 독립 사건은 {len(ep_df)}건")
    if not ep_df.empty:
        v = ep_df["20일%"]
        print(f"  사건 단위 20일 수익률: 평균 {v.mean():+.2f}% · 중앙 {v.median():+.2f}% · "
              f"승률 {(v > 0).mean() * 100:.1f}%")
        print(f"  최근 8개 사건:\n{ep_df.tail(8).to_string(index=False)}")


def main():
    pd.set_option("display.width", 200)
    for t in TICKERS:
        d = prep(t)
        print("=" * 110)
        print(f"{t}: {d.index.min().date()} ~ {d.index.max().date()} ({len(d):,}일)")
        ma200_position(d, t)
        episodes(d, t)


if __name__ == "__main__":
    main()
