"""R2 규칙(RSI<30 & 60일 고점 -45%↓) 정밀 검증.

7월 29일 사례에서 뽑은 규칙이라, 그 사례에 맞춰 깎은 건 아닌지 확인해야 한다.
  - 파라미터를 흔들어도 성적이 유지되는가 (과최적화 여부)
  - 연도별로 꾸준한가, 특정 위기 몇 번이 다 만든 건 아닌가
  - 특정 종목 쏠림은 없는가
  - 국면별로 어떤가
  - 기존 A~H·전략1/2와 겹치는가
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

from ma200_macd_golden import OUT_DIR, PANEL_PATH, build_qqq_state
from washout_rules import build, market_frame

R2 = lambda p, rsi=30, dd=-45: (p["RSI"] < rsi) & (p["dd60"] < dd)


def sensitivity(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for rsi in (25, 30, 35, 40):
        for dd in (-30, -40, -45, -50, -60):
            m = R2(p, rsi, dd)
            s = p[m]
            if len(s) < 150:
                continue
            rows.append({"RSI <": rsi, "60일 고점 대비 <": f"{dd}%", "신호수": len(s),
                         "5일%": round(s["fwd5"].mean(), 2),
                         "20일%": round(s["fwd20"].mean(), 2),
                         "초과20%p": round(s["ex20"].mean(), 2),
                         "20일승률%": round((s["fwd20"] > 0).mean() * 100, 1)})
    return pd.DataFrame(rows)


def yearly(p: pd.DataFrame, m: pd.Series) -> pd.DataFrame:
    s = p[m]
    g = s.groupby(s["date"].dt.year)
    t = pd.DataFrame({"신호": g.size(), "20일%": g["fwd20"].mean().round(2),
                      "초과%p": g["ex20"].mean().round(2)})
    return t[t["신호"] >= 5]


def concentration(p: pd.DataFrame, m: pd.Series) -> None:
    s = p[m]
    cnt = s["ticker"].value_counts()
    print(f"  종목 {s['ticker'].nunique()}개 / 상위 5종목이 전체의 "
          f"{cnt.head(5).sum() / len(s) * 100:.1f}% ({list(cnt.head(5).index)})")
    top = s.groupby("ticker")["ex20"].mean().sort_values(ascending=False).head(5)
    rest = s[~s["ticker"].isin(top.index)]
    print(f"  기여 상위 5종목 제외 시 초과수익 {rest['ex20'].mean():+.2f}%p "
          f"(전체 {s['ex20'].mean():+.2f}%p)")
    yr = s.groupby(s["date"].dt.year)["ex20"].mean()
    crisis = s[s["date"].dt.year.isin([2000, 2001, 2002, 2008, 2009, 2020, 2022])]
    calm = s[~s["date"].dt.year.isin([2000, 2001, 2002, 2008, 2009, 2020, 2022])]
    print(f"  위기연도(00~02·08·09·20·22) {len(crisis):,}건 {crisis['ex20'].mean():+.2f}%p / "
          f"그 외 {len(calm):,}건 {calm['ex20'].mean():+.2f}%p")


def regime(p: pd.DataFrame, m: pd.Series, qstate: pd.DataFrame) -> None:
    q = qstate.rename_axis("date").reset_index()[["date", "regime"]]
    s = p[m].merge(q, on="date", how="left")
    g = s.groupby("regime").agg(신호=("ex20", "size"), 이십일=("fwd20", "mean"),
                                초과=("ex20", "mean"))
    g.columns = ["신호수", "20일%", "초과%p"]
    print(g.round(2).to_string())


def overlap(p: pd.DataFrame, m: pd.Series) -> None:
    if not os.path.exists(PANEL_PATH):
        print("  기존 패널 없음")
        return
    base = pd.read_pickle(PANEL_PATH)[["ticker", "date", "ahCode", "liveCode"]]
    j = p[m][["ticker", "date"]].merge(base, on=["ticker", "date"], how="left")
    n = len(j)
    parts = []
    for c in list("ABCDEFGH"):
        k = int((j["ahCode"] == c).sum())
        if k / n > 0.01:
            parts.append(f"{c} {k / n * 100:.1f}%")
    for c in ("1", "2"):
        k = int((j["liveCode"] == c).sum())
        if k / n > 0.01:
            parts.append(f"전략{c} {k / n * 100:.1f}%")
    hit = ((j["ahCode"].notna()) | (j["liveCode"].notna())).sum()
    print(f"  기존 룰과 동시 발동 {hit / n * 100:.1f}% "
          f"({', '.join(parts) or '유의미한 겹침 없음'})")
    solo = j[j["ahCode"].isna() & j["liveCode"].isna()]
    idx = p[m].reset_index(drop=True)
    only = idx[j.reset_index(drop=True)["ahCode"].isna() &
               j.reset_index(drop=True)["liveCode"].isna()]
    print(f"  기존 룰이 못 잡는 {len(solo):,}건만의 초과수익 {only['ex20'].mean():+.2f}%p")


def main():
    pd.set_option("display.width", 300)
    pd.set_option("display.max_columns", 40)
    mkt = market_frame()
    p, _ = build(mkt)
    m = R2(p)

    print("=" * 120)
    print("파라미터 민감도 — 기준을 흔들어도 유지되는가")
    print("=" * 120)
    print(sensitivity(p).to_string(index=False))

    print("\n" + "=" * 120)
    print(f"R2 (RSI<30 & 60일 고점 -45%↓) — 신호 {int(m.sum()):,}건")
    print("=" * 120)
    yt = yearly(p, m)
    print(f"\n[연도별] {len(yt)}개 연도 중 초과수익 플러스 "
          f"{int((yt['초과%p'] > 0).sum())}년 "
          f"({(yt['초과%p'] > 0).mean() * 100:.0f}%)")
    print(yt.to_string())

    print("\n[쏠림]")
    concentration(p, m)

    print("\n[국면별]")
    regime(p, m, build_qqq_state())

    print("\n[기존 전략과 겹침]")
    overlap(p, m)

    p[m].to_csv(os.path.join(OUT_DIR, "washout_r2_signals.csv"), index=False)


if __name__ == "__main__":
    main()
