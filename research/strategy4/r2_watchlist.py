"""관심종목 57개에 R2를 걸어 최근 발동 이력과 현재 상태를 본다.

평가는 20일 고정 수익률이 아니라 목표 달성 여부와 소요일로 한다.
아직 결과가 안 나온 진행 중 신호는 '진행중'으로 표시한다.
"""
from __future__ import annotations

import json
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
from ma200_macd_golden import CACHE, FEE, OUT_DIR, dl

TP, SL, MAXHOLD = 0.10, 0.10, 60
RECENT_DAYS = 120
BOTTOM = pd.Timestamp("2026-07-29")


def prep(sym: str) -> pd.DataFrame | None:
    raw = dl(sym)
    if raw is None or len(raw) < 300:
        return None
    d = add_indicators(raw).dropna(subset=["MA200", "RSI"])
    if len(d) < 250:
        return None
    cl = d["Close"]
    return d.assign(
        dd60=(cl / cl.rolling(60).max() - 1) * 100,
        dd252=(cl / cl.rolling(252).max() - 1) * 100,
        distMA200=(cl / d["MA200"] - 1) * 100,
        r2=(d["RSI"] < 30) & ((cl / cl.rolling(60).max() - 1) * 100 < -45),
    )


def outcome(d: pd.DataFrame, i: int) -> dict:
    """i일 신호 → 다음날 시가 진입 후 결과."""
    op, hi, lo, cl = (d["Open"].to_numpy(), d["High"].to_numpy(),
                      d["Low"].to_numpy(), d["Close"].to_numpy())
    n = len(d)
    if i + 1 >= n:
        return {"결과": "진입 전", "소요일": np.nan, "손익%": np.nan}
    ep = op[i + 1] * (1 + FEE)
    end = min(i + 1 + MAXHOLD, n)
    sh, sll = hi[i + 1:end], lo[i + 1:end]
    ht, hs = sh >= ep * (1 + TP), sll <= ep * (1 - SL)
    k_tp = int(np.argmax(ht)) if ht.any() else -1
    k_sl = int(np.argmax(hs)) if hs.any() else -1
    if k_sl >= 0 and (k_tp < 0 or k_sl <= k_tp):
        return {"결과": "손절", "소요일": k_sl + 1, "손익%": round(-SL * 100 - FEE * 100, 1)}
    if k_tp >= 0:
        return {"결과": "달성", "소요일": k_tp + 1, "손익%": round(TP * 100 - FEE * 100, 1)}
    days = len(sh)
    cur = round((cl[end - 1] * (1 - FEE) / ep - 1) * 100, 1)
    if end < i + 1 + MAXHOLD:
        return {"결과": "진행중", "소요일": days, "손익%": cur}
    return {"결과": "기간만료", "소요일": days, "손익%": cur}


def sweep(data: dict) -> pd.DataFrame:
    """관심종목은 변동성이 커서 손절폭에 민감하다. 조합별로 훑는다."""
    global TP, SL, MAXHOLD
    keep = (TP, SL, MAXHOLD)
    rows = []
    for tp, sl, mh in [(0.10, 0.10, 60), (0.10, 0.15, 60), (0.10, 0.20, 60),
                       (0.15, 0.15, 60), (0.15, 0.20, 60), (0.20, 0.20, 60),
                       (0.10, None, 60), (0.15, None, 60)]:
        TP, SL, MAXHOLD = tp, (sl if sl is not None else 9.99), mh
        res = []
        for d in data.values():
            for i in np.flatnonzero(d["r2"].to_numpy()):
                r = outcome(d, i)
                if r["결과"] in ("달성", "손절", "기간만료"):
                    res.append(r)
        if not res:
            continue
        hit = [r for r in res if r["결과"] == "달성"]
        pnl = np.array([r["손익%"] for r in res])
        days = np.array([r["소요일"] for r in res], dtype=float)
        rows.append({
            "익절/손절": f"+{tp:.0%} / {'없음' if sl is None else f'-{sl:.0%}'}",
            "거래": len(res), "달성률%": round(len(hit) / len(res) * 100, 1),
            "달성 중앙일": int(np.median([r["소요일"] for r in hit])) if hit else np.nan,
            "손절률%": round(np.mean([r["결과"] == "손절" for r in res]) * 100, 1),
            "평균손익%": round(pnl.mean(), 2), "평균보유일": round(days.mean(), 1),
            "연환산%": round(pnl.mean() / days.mean() * 252, 1),
        })
    TP, SL, MAXHOLD = keep
    return pd.DataFrame(rows)


def main():
    pd.set_option("display.width", 300)
    mapping = json.load(open(os.path.join(CACHE, "s4_watchlist_map.json")))

    data, stats, recent, live = {}, [], [], []
    for name, sym in mapping.items():
        d = prep(sym)
        if d is None:
            continue
        data[name] = d
        rows = np.flatnonzero(d["r2"].to_numpy())
        res = [outcome(d, i) for i in rows]
        done = [r for r in res if r["결과"] in ("달성", "손절", "기간만료")]
        if done:
            hit = [r for r in done if r["결과"] == "달성"]
            stats.append({
                "종목": name, "과거 신호": len(done),
                "달성률%": round(len(hit) / len(done) * 100, 1),
                "달성 중앙일": int(np.median([r["소요일"] for r in hit])) if hit else np.nan,
                "평균 손익%": round(np.mean([r["손익%"] for r in done]), 2),
            })
        cutoff = d.index.max() - pd.Timedelta(days=RECENT_DAYS)
        for i, r in zip(rows, res):
            if d.index[i] >= cutoff:
                recent.append({"종목": name, "신호일": d.index[i].date(),
                               "종가": round(d["Close"].iloc[i], 2),
                               "RSI": round(d["RSI"].iloc[i]),
                               "60일고점대비%": round(d["dd60"].iloc[i], 1),
                               "MA200이격%": round(d["distMA200"].iloc[i], 1), **r})
        if bool(d["r2"].iloc[-1]):
            live.append({"종목": name, "일자": d.index[-1].date(),
                         "종가": round(d["Close"].iloc[-1], 2),
                         "RSI": round(d["RSI"].iloc[-1]),
                         "60일고점대비%": round(d["dd60"].iloc[-1], 1)})

    print(f"관심종목 {len(data)}개 로드 (데이터 종료 {max(d.index.max() for d in data.values()).date()})")

    print("\n" + "=" * 130)
    print(f"최근 {RECENT_DAYS}일 R2 발동 이력 (+{TP:.0%} 익절 / -{SL:.0%} 손절 / 최대 {MAXHOLD}일)")
    print("=" * 130)
    if recent:
        rt = pd.DataFrame(recent).sort_values("신호일")
        print(rt.to_string(index=False))
        done = rt[rt["결과"].isin(["달성", "손절", "기간만료"])]
        if len(done):
            hit = (done["결과"] == "달성").sum()
            print(f"\n  종결 {len(done)}건 중 달성 {hit}건 ({hit / len(done) * 100:.0f}%) · "
                  f"평균 손익 {done['손익%'].mean():+.2f}% · "
                  f"달성 건 중앙 소요 "
                  f"{int(done[done['결과'] == '달성']['소요일'].median()) if hit else '-'}일")
    else:
        print("  발동 없음")

    print("\n" + "=" * 130)
    print(f"{BOTTOM.date()} 당일 R2가 지목한 관심종목")
    print("=" * 130)
    rows = []
    for name, d in data.items():
        if BOTTOM in d.index and bool(d.loc[BOTTOM, "r2"]):
            i = d.index.get_loc(BOTTOM)
            rows.append({"종목": name, "종가": round(d["Close"].iloc[i], 2),
                         "RSI": round(d["RSI"].iloc[i]),
                         "60일고점대비%": round(d["dd60"].iloc[i], 1),
                         "현재가": round(d["Close"].iloc[-1], 2),
                         "현재까지%": round((d["Close"].iloc[-1] / d["Close"].iloc[i] - 1) * 100, 1),
                         **outcome(d, i)})
    print(pd.DataFrame(rows).to_string(index=False) if rows else "  없음")

    print("\n" + "=" * 130)
    print("현재 발동 중 (마지막 거래일 기준)")
    print("=" * 130)
    print(pd.DataFrame(live).to_string(index=False) if live else "  현재 발동 중인 종목 없음")

    print("\n" + "=" * 130)
    print("관심종목별 R2 과거 성적 (신호 5건 이상, 달성률 순)")
    print("=" * 130)
    st = pd.DataFrame(stats)
    st = st[st["과거 신호"] >= 5].sort_values("달성률%", ascending=False)
    print(st.to_string(index=False))
    print(f"\n  합계 {int(st['과거 신호'].sum()):,}건 · "
          f"가중 달성률 "
          f"{(st['달성률%'] * st['과거 신호']).sum() / st['과거 신호'].sum():.1f}% · "
          f"평균 손익 {(st['평균 손익%'] * st['과거 신호']).sum() / st['과거 신호'].sum():+.2f}%")
    st.to_csv(os.path.join(OUT_DIR, "r2_watchlist.csv"), index=False)

    print("\n" + "=" * 130)
    print("익절/손절 조합 훑기 — 관심종목 전체 신호 기준")
    print("=" * 130)
    print(sweep(data).to_string(index=False))


if __name__ == "__main__":
    main()
