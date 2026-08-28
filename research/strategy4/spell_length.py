"""MA200 이탈 '구간' 단위로, 구간 길이별 수익률과 MACD 신호 포착률.

RKLB·IONQ의 대박 반등은 이탈 구간이 1~2일이었고 MACD 첫 신호가 아예 없었다.
MACD가 후행 지표라 1~2일 만에 회복하면 히스토그램이 아직 내려가는 중이다.
이게 전 종목에서도 성립하는지, 구간 길이별로 신호 포착률을 세어 확인한다.

또 fresh_breakdown.py의 10개 칸 중 유일하게 플러스였던
'MA200 우상향 & 이탈 1~3일차 & MACD 신호'가 진짜인지 연도별·부트스트랩으로 본다.
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

from ma200_macd_golden import OUT_DIR
from fresh_breakdown import panel, prep
from backtest_qqq_block_v2 import UNIVERSE

SPELL_BINS = [(1, 2), (3, 5), (6, 10), (11, 20), (21, 60), (61, 10_000)]


def spell_table(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for t, d in data.items():
        below = d["below200"].to_numpy()
        sig = d["signal"].to_numpy()
        up = d["ma200Up"].to_numpy()
        cl = d["Close"].to_numpy()
        starts = np.flatnonzero(below & ~np.concatenate([[False], below[:-1]]))
        for i in starts:
            end = i
            while end + 1 < len(below) and below[end + 1]:
                end += 1
            if i + 20 >= len(cl):
                continue
            insig = sig[i:end + 1]
            rows.append({
                "ticker": t, "len": end - i + 1, "ma200Up": bool(up[i]),
                "hasSignal": bool(insig.any()),
                "r5": (cl[i + 5] / cl[i] - 1) * 100,
                "r20": (cl[i + 20] / cl[i] - 1) * 100,
                "r60": (cl[min(i + 60, len(cl) - 1)] / cl[i] - 1) * 100,
            })
    return pd.DataFrame(rows)


def by_length(sp: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lo, hi in SPELL_BINS:
        s = sp[sp["len"].between(lo, hi)]
        if len(s) < 50:
            continue
        rows.append({
            "이탈 구간 길이": f"{lo}~{hi}일" if hi < 1000 else f"{lo}일+",
            "구간수": len(s),
            "MACD 신호 뜬 비율%": round(s["hasSignal"].mean() * 100, 1),
            "이탈일 기준 20일%": round(s["r20"].mean(), 2),
            "60일%": round(s["r60"].mean(), 2),
            "20일승률%": round((s["r20"] > 0).mean() * 100, 1),
        })
    return pd.DataFrame(rows)


def signal_split(sp: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lo, hi in SPELL_BINS:
        s = sp[sp["len"].between(lo, hi)]
        if len(s) < 100:
            continue
        a, b = s[s["hasSignal"]], s[~s["hasSignal"]]
        if len(b) < 30:
            continue
        rows.append({
            "구간 길이": f"{lo}~{hi}일" if hi < 1000 else f"{lo}일+",
            "신호 O 개수": len(a), "신호 O 20일%": round(a["r20"].mean(), 2),
            "신호 X 개수": len(b), "신호 X 20일%": round(b["r20"].mean(), 2),
            "차이%p": round(a["r20"].mean() - b["r20"].mean(), 2),
        })
    return pd.DataFrame(rows)


def validate_cell(p: pd.DataFrame) -> None:
    m = (p["below200"] & p["ma200Up"] & p["daysBelow"].between(1, 3) & p["signal"])
    s = p[m].dropna(subset=["ex20"])
    print(f"\n[검증 · MA200 우상향 & 이탈 1~3일차 & MACD 신호] 신호 {len(s):,}건")

    daily = s.groupby("date")["ex20"].mean().to_numpy()
    rng = np.random.default_rng(11)
    boot = np.array([rng.choice(daily, len(daily), replace=True).mean()
                     for _ in range(5000)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"  초과수익 평균 {s['ex20'].mean():+.3f}%p · 95% CI {lo:+.3f} ~ {hi:+.3f} "
          f"→ {'유의' if (lo > 0 or hi < 0) else '유의하지 않음 (0 포함)'}")

    yr = s.groupby(s["date"].dt.year)["ex20"].agg(["size", "mean"])
    yr = yr[yr["size"] >= 20]
    print(f"  연도별: {len(yr)}개 연도 중 플러스 {int((yr['mean'] > 0).sum())}년 "
          f"({(yr['mean'] > 0).mean() * 100:.0f}%)")

    top = s.groupby("ticker")["ex20"].agg(["size", "mean"]).sort_values("mean",
                                                                       ascending=False)
    top = top[top["size"] >= 10]
    print(f"  종목 쏠림: 상위 3종목 {list(top.head(3).index)} · "
          f"이들 제외 시 초과수익 "
          f"{s[~s['ticker'].isin(top.head(3).index)]['ex20'].mean():+.3f}%p")
    print(f"  10개 칸 중 1개만 플러스였으므로 다중검정 보정 시 유의수준 0.005 필요")


def main():
    pd.set_option("display.width", 340)
    pd.set_option("display.max_columns", 40)

    data = {}
    for t in UNIVERSE:
        d = prep(t)
        if d is not None:
            data[t] = d
    print(f"종목 {len(data)}개")

    sp = spell_table(data)
    print(f"MA200 이탈 구간 총 {len(sp):,}개")

    print("\n[구간 길이별 — MACD가 신호를 주는 비율과 실제 수익률]")
    print("(수익률은 MA200 아래로 내려간 그날 종가 기준)")
    print(by_length(sp).to_string(index=False))

    print("\n[MA200 우상향 구간만]")
    print(by_length(sp[sp["ma200Up"]]).to_string(index=False))

    print("\n[같은 길이 안에서 MACD 신호 유무로 갈랐을 때]")
    print(signal_split(sp).to_string(index=False))

    sp.to_csv(os.path.join(OUT_DIR, "spell_length.csv"), index=False)
    validate_cell(panel(data))


if __name__ == "__main__":
    main()
