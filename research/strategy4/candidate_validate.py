"""condition_scan에서 뽑힌 상위 후보를 실제 채택 가능한지 정밀 검증.

스캔 단계는 평균 초과수익만 본다. 평균은 몇 개 연도·몇 개 종목의 대박에
끌려갈 수 있으므로 여기서는 다음을 확인한다.
  1) 연도별로 꾸준한가 (27년 중 몇 년이 플러스인가)
  2) 특정 종목에 쏠려 있지 않은가
  3) 실제 TP/SL/보유한도를 걸고 거래로 돌렸을 때 남는가
  4) 기존 A~H·전략1/2와 겹치지 않는가
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

from condition_scan import build
from ma200_macd_golden import FEE, OUT_DIR, PANEL_PATH, REGIME_ORDER, dl
from calculator.indicators import add_indicators

CANDIDATES = {
    "α 강세 눌림목 (60일+30% & 추세선-5%↓)":
        lambda p: (p["ret60"] > 0.30) & (p["distLR"] < -0.05),
    "α' 강세 눌림목 (60일+30% & CCI<-100)":
        lambda p: (p["ret60"] > 0.30) & (p["CCI"] < -100),
    "β 급락 과매도 (52주고점-50%↓ & RSI<25)":
        lambda p: (p["dd252"] < -0.50) & (p["RSI"] < 25),
    "β' 급락 과매도 (52주고점-50%↓ & %B<0)":
        lambda p: (p["dd252"] < -0.50) & (p["PctB"] < 0),
    "γ 스퀴즈 눌림 (스퀴즈<0.7 & 20일-15%↓)":
        lambda p: (p["squeeze"] < 0.7) & (p["ret20"] < -0.15),
    "참고: 영상전략 계열 (MA200위 & MACD>0 & ADX>25)":
        lambda p: (p["distMA200"] > 0) & (p["MACD_Hist"] > 0) & (p["ADX"] > 25),
}


def yearly(p: pd.DataFrame, m: pd.Series) -> pd.DataFrame:
    sub = p[m]
    g = sub.groupby(sub["date"].dt.year)
    t = pd.DataFrame({"신호수": g.size(), "초과%": g["ex"].mean().round(2),
                      "절대%": g["fwd"].mean().round(2)})
    return t[t["신호수"] >= 5]


def concentration(p: pd.DataFrame, m: pd.Series) -> str:
    sub = p[m]
    tot = sub.groupby("ticker")["ex"].sum()
    share = tot.sort_values(ascending=False).head(3)
    denom = tot[tot > 0].sum()
    pct = share.sum() / denom * 100 if denom > 0 else np.nan
    return f"상위3종목({', '.join(share.index)})이 총 플러스 초과수익의 {pct:.0f}%"


def sim(p: pd.DataFrame, m: pd.Series, prices: dict, tp: float, sl: float,
        hold: int) -> dict:
    trades = []
    for t, grp in p[m].groupby("ticker"):
        px = prices.get(t)
        if px is None:
            continue
        idx, op, cl = px.index, px["Open"].to_numpy(), px["Close"].to_numpy()
        pos = {d: i for i, d in enumerate(idx)}
        busy = -1
        for d in grp["date"].sort_values():
            i0 = pos.get(d)
            if i0 is None or i0 <= busy or i0 + 1 >= len(idx):
                continue
            ep = op[i0 + 1] * (1 + FEE)
            if not np.isfinite(ep) or ep <= 0:
                continue
            ret, days = None, 0
            for j in range(i0 + 1, min(i0 + 1 + hold, len(idx))):
                days = j - i0
                r = cl[j] * (1 - FEE) / ep - 1
                if r >= tp or r <= -sl or days >= hold:
                    ret = r
                    break
            if ret is None:
                ret = cl[min(i0 + hold, len(idx) - 1)] * (1 - FEE) / ep - 1
            busy = i0 + days
            trades.append((ret * 100, days))
    if not trades:
        return {}
    r = np.array([x[0] for x in trades])
    dd = np.array([x[1] for x in trades])
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {"거래": len(r), "승률%": round((r > 0).mean() * 100, 1),
            "평균%": round(r.mean(), 2), "PF": round(gains / losses, 2) if losses else np.inf,
            "최악%": round(r.min(), 1), "평균일": round(dd.mean(), 1),
            "연환산%": round(r.mean() * (252 / max(dd.mean(), 1)), 1)}


def overlap(p: pd.DataFrame, m: pd.Series) -> str:
    if not os.path.exists(PANEL_PATH):
        return "패널 없음"
    base = pd.read_pickle(PANEL_PATH)[["ticker", "date", "ahCode", "liveCode"]]
    mm = p[m][["ticker", "date"]].merge(base, on=["ticker", "date"], how="left")
    n = len(mm)
    hit = mm["ahCode"].notna().sum() + mm["liveCode"].notna().sum()
    parts = []
    for code in list("ABCDEFGH"):
        k = int((mm["ahCode"] == code).sum())
        if k / n > 0.005:
            parts.append(f"{code} {k / n * 100:.1f}%")
    for code in ("1", "2"):
        k = int((mm["liveCode"] == code).sum())
        if k / n > 0.005:
            parts.append(f"전략{code} {k / n * 100:.1f}%")
    return f"기존 룰과 동시 발동 {hit / n * 100:.1f}% ({', '.join(parts) or '유의미한 겹침 없음'})"


def main():
    pd.set_option("display.width", 320)
    p = build()
    print(f"패널 {p['date'].min().date()} ~ {p['date'].max().date()} / "
          f"{p['ticker'].nunique()}종목 / {len(p):,} 종목·일\n")

    prices = {}
    for t in p["ticker"].unique():
        raw = dl(t)
        if raw is not None:
            prices[t] = raw

    summary = []
    for name, fn in CANDIDATES.items():
        m = fn(p)
        yt = yearly(p, m)
        pos_years = int((yt["초과%"] > 0).sum())
        print("=" * 130)
        print(f"{name}   신호 {int(m.sum()):,}건 / 초과수익 {p.loc[m, 'ex'].mean():+.2f}%")
        print(f"  연도별: {len(yt)}개 연도 중 {pos_years}년 플러스 "
              f"({pos_years / len(yt) * 100:.0f}%)")
        print(f"  쏠림: {concentration(p, m)}")
        print(f"  {overlap(p, m)}")
        reg = {r: round(p.loc[m & (p['regime'] == r), 'ex'].mean(), 2)
               for r in REGIME_ORDER if (m & (p["regime"] == r)).sum() >= 30}
        print(f"  국면별 초과: {reg}")
        best = None
        for tp, sl, hold in [(0.10, 0.07, 20), (0.15, 0.10, 40), (0.20, 0.10, 60),
                             (0.08, 0.05, 15)]:
            s = sim(p, m, prices, tp, sl, hold)
            if s:
                s = {"TP/SL/보유": f"{tp:.0%}/{sl:.0%}/{hold}일", **s}
                print("   ", s)
                if best is None or s["연환산%"] > best["연환산%"]:
                    best = s
        print(f"  연도별 상세:\n{yt.to_string()}")
        summary.append({"후보": name, "신호수": int(m.sum()),
                        "초과%": round(p.loc[m, "ex"].mean(), 2),
                        "플러스연도": f"{pos_years}/{len(yt)}",
                        **{k: v for k, v in (best or {}).items() if k != "TP/SL/보유"}})
    print("\n" + "=" * 130)
    print("[요약]")
    sm = pd.DataFrame(summary)
    print(sm.to_string(index=False))
    sm.to_csv(os.path.join(OUT_DIR, "candidate_summary.csv"), index=False)


if __name__ == "__main__":
    main()
