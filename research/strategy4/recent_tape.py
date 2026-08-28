"""최근 시세를 그대로 펼쳐서 '며칠 전 무슨 일이 있었는지' 먼저 확인.

전략을 만들기 전에 사실관계부터 잡는다. 반등 당일에 화면에서 볼 수 있었던
값(MA200 이격, MACD 히스토그램, RSI, 거래량비, 직전 낙폭)만 같이 찍는다.
미래 정보는 넣지 않는다.
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

TICKERS = ["COHR", "TE", "RKLB", "IONQ"]
DAYS = 26


def tape(t: str) -> None:
    d = add_indicators(dl(t)).dropna(subset=["MA200", "MACD_Hist"])
    cl = d["Close"]
    d = d.assign(
        distMA200=(cl / d["MA200"] - 1) * 100,
        volRatio=d["Volume"] / d["Volume"].rolling(20).mean(),
        dd60=(cl / cl.rolling(60).max() - 1) * 100,
        ret1=cl.pct_change() * 100,
    )
    last = d.tail(DAYS)
    show = pd.DataFrame({
        "종가": last["Close"].round(2),
        "일간%": last["ret1"].round(1),
        "MA200": last["MA200"].round(2),
        "이격%": last["distMA200"].round(1),
        "MACD히스토": last["MACD_Hist"].round(3),
        "RSI": last["RSI"].round(0),
        "거래량배": last["volRatio"].round(1),
        "60일고점대비%": last["dd60"].round(1),
    })
    show.index = show.index.date
    print(f"\n{'=' * 118}\n{t} — 최근 {DAYS}거래일\n{'=' * 118}")
    print(show.to_string())

    below = last["distMA200"] < 0
    if below.any():
        lo = last.loc[below, "Close"].idxmin()
        i = d.index.get_loc(lo)
        fwd = {f"+{h}일": round((d["Close"].iloc[i + h] / d["Close"].iloc[i] - 1) * 100, 1)
               for h in (1, 3, 5) if i + h < len(d)}
        print(f"  MA200 아래 구간 저점: {lo.date()} {d['Close'].iloc[i]:.2f} → {fwd}")
        print(f"  현재 {d['Close'].iloc[-1]:.2f} (저점 대비 "
              f"{(d['Close'].iloc[-1] / d['Close'].iloc[i] - 1) * 100:+.1f}%)")


def main():
    pd.set_option("display.width", 260)
    for t in TICKERS:
        tape(t)


if __name__ == "__main__":
    main()
