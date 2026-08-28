"""2026-07-29에 무슨 일이 있었는지 — 종목 신호인가 시장 이벤트인가.

COHR·TE·RKLB·IONQ가 전부 같은 날 저점을 찍었다. 개별 종목 지표가 맞아떨어진
게 아니라 시장 전체가 바닥이었을 가능성이 크다. 지수와 시장 폭(breadth)을
같이 보고, 그날 화면에서 볼 수 있었던 값이 무엇이었는지 정리한다.
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
from backtest_qqq_block_v2 import UNIVERSE

WATCH = ["COHR", "TE", "RKLB", "IONQ"]
BOTTOM = pd.Timestamp("2026-07-29")


def index_tape() -> None:
    for sym in ("QQQ", "SPY", "^VIX"):
        raw = dl(sym)
        if raw is None:
            print(f"{sym}: 데이터 없음")
            continue
        d = add_indicators(raw).dropna(subset=["MA200"])
        d = d.assign(ret1=d["Close"].pct_change() * 100,
                     dist=(d["Close"] / d["MA200"] - 1) * 100,
                     dd60=(d["Close"] / d["Close"].rolling(60).max() - 1) * 100)
        last = d.tail(16)
        show = pd.DataFrame({"종가": last["Close"].round(2),
                             "일간%": last["ret1"].round(1),
                             "MA200이격%": last["dist"].round(1),
                             "RSI": last["RSI"].round(0),
                             "60일고점대비%": last["dd60"].round(1)})
        show.index = show.index.date
        print(f"\n[{sym}]")
        print(show.to_string())


def breadth() -> pd.DataFrame:
    """매일 '전체 종목 중 몇 %가 과매도인지' — 시장 바닥 신호."""
    rows = []
    for t in UNIVERSE:
        raw = dl(t)
        if raw is None or len(raw) < 300:
            continue
        d = add_indicators(raw).dropna(subset=["MA200", "RSI"])
        cl = d["Close"]
        rows.append(pd.DataFrame({
            "date": d.index,
            "below": (cl < d["MA200"]).to_numpy(),
            "rsi30": (d["RSI"] < 30).to_numpy(),
            "dd60_40": (cl / cl.rolling(60).max() - 1 < -0.40).to_numpy(),
        }))
    p = pd.concat(rows, ignore_index=True)
    g = p.groupby("date").mean(numeric_only=True) * 100
    g["n"] = p.groupby("date").size()
    return g


def snapshot() -> None:
    print(f"\n{'=' * 118}")
    print(f"{BOTTOM.date()} 당일 — 그날 화면에서 볼 수 있었던 값")
    print("=" * 118)
    rows = []
    for t in WATCH:
        d = add_indicators(dl(t)).dropna(subset=["MA200", "RSI"])
        if BOTTOM not in d.index:
            continue
        i = d.index.get_loc(BOTTOM)
        cl = d["Close"]
        h = d["MACD_Hist"]
        rows.append({
            "종목": t, "종가": round(cl.iloc[i], 2),
            "당일%": round((cl.iloc[i] / cl.iloc[i - 1] - 1) * 100, 1),
            "5일%": round((cl.iloc[i] / cl.iloc[i - 5] - 1) * 100, 1),
            "MA200이격%": round((cl.iloc[i] / d["MA200"].iloc[i] - 1) * 100, 1),
            "RSI": round(d["RSI"].iloc[i]),
            "%B": round(d["PctB"].iloc[i], 2) if "PctB" in d else np.nan,
            "CCI": round(d["CCI"].iloc[i]),
            "60일고점대비%": round((cl.iloc[i] / cl.iloc[i - 59:i + 1].max() - 1) * 100, 1),
            "52주고점대비%": round((cl.iloc[i] / cl.iloc[max(0, i - 251):i + 1].max() - 1) * 100, 1),
            "거래량배": round(d["Volume"].iloc[i] / d["Volume"].iloc[i - 20:i].mean(), 1),
            "MACD히스토": round(h.iloc[i], 3),
            "히스토방향": "상승" if h.iloc[i] > h.iloc[i - 1] else "하락",
        })
    t = pd.DataFrame(rows)
    print(t.to_string(index=False))

    print("\n[MACD 골든크로스는 언제 났나 — 저점 대비 며칠 뒤, 얼마나 오른 뒤]")
    rows = []
    for tk in WATCH:
        d = add_indicators(dl(tk)).dropna(subset=["MA200"])
        i = d.index.get_loc(BOTTOM)
        h = d["MACD_Hist"].to_numpy()
        cl = d["Close"].to_numpy()
        gc = [j for j in range(i, len(d)) if h[j] > 0 and h[j - 1] <= 0]
        if not gc:
            rows.append({"종목": tk, "골든크로스": "아직", "저점 후": "-", "이미 오른 폭": "-"})
            continue
        j = gc[0]
        rows.append({"종목": tk, "골든크로스": str(d.index[j].date()),
                     "저점 후": f"{j - i}거래일",
                     "이미 오른 폭": f"{(cl[j] / cl[i] - 1) * 100:+.1f}%",
                     "이후 현재까지": f"{(cl[-1] / cl[j] - 1) * 100:+.1f}%"})
    print(pd.DataFrame(rows).to_string(index=False))


def main():
    pd.set_option("display.width", 300)
    pd.set_option("display.max_columns", 40)

    print("=" * 118)
    print("지수 — 7월 말 시장 상황")
    print("=" * 118)
    index_tape()

    b = breadth()
    print(f"\n{'=' * 118}")
    print("시장 폭 — 137종목 중 과매도 비율 (최근 16거래일)")
    print("=" * 118)
    last = b.tail(16).round(1)
    last.index = last.index.date
    last.columns = ["MA200아래%", "RSI<30%", "60일고점-40%이하%", "종목수"]
    print(last.to_string())

    hist = b[b.index < BOTTOM]
    cur = b.loc[BOTTOM]
    print(f"\n{BOTTOM.date()} 기준 역사적 위치 (1999년 이후 {len(hist):,}일 중):")
    for col, label in (("rsi30", "RSI<30 종목 비율"),
                       ("dd60_40", "60일 고점 -40% 이하 비율"),
                       ("below", "MA200 아래 비율")):
        pct = (hist[col] < cur[col]).mean() * 100
        print(f"  {label} {cur[col]:.1f}% → 상위 {100 - pct:.1f}% "
              f"(과거 {pct:.1f}%의 날보다 높음)")

    snapshot()


if __name__ == "__main__":
    main()
