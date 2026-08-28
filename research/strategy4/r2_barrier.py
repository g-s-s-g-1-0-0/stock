"""R2 규칙을 '목표 달성 여부 · 달성까지 걸린 시간 · 승률'로만 평가.

고정 20일 수익률은 3일 만에 +12% 찍고 되밀린 거래를 실패로 기록한다.
실제 운용은 목표에 닿으면 파니까 그 기준으로 다시 잰다.

  달성률   = 최대 보유기간 안에 목표가에 닿은 비율 (= 승률)
  소요일   = 닿기까지 걸린 거래일 (분포까지)
  미달성   = 못 닿은 건들이 기간 만료 시 얼마였는지

비교군을 같은 규칙으로 함께 돌린다. 달성률은 보유기간만 늘려도 올라가서
단독으로는 의미가 없기 때문이다.
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

from ma200_macd_golden import FEE, OUT_DIR
from washout_rules import build, market_frame

SEED = 5
DAY_BUCKETS = [(1, 1), (2, 3), (4, 5), (6, 10), (11, 20), (21, 10_000)]

RULES = {
    "R2 (RSI<30 & 60일고점-45%↓)":
        lambda p: (p["RSI"] < 30) & (p["dd60"] < -45),
    "R2 완화 (RSI<35 & 60일고점-40%↓)":
        lambda p: (p["RSI"] < 35) & (p["dd60"] < -40),
    "R2 강화 (RSI<25 & 60일고점-50%↓)":
        lambda p: (p["RSI"] < 25) & (p["dd60"] < -50),
    "[비교] MACD 골든크로스 & MA200 아래":
        lambda p: p["below200"] & p["golden"],
    "[비교] 아무 날이나 매수":
        None,
}


def walk(px: pd.DataFrame, rows: np.ndarray, tp: float, sl: float | None,
         maxhold: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(결과코드, 보유일, 손익%) — 코드 1=목표달성 -1=손절 0=기간만료."""
    op, hi, lo, cl = (px["Open"].to_numpy(), px["High"].to_numpy(),
                      px["Low"].to_numpy(), px["Close"].to_numpy())
    n = len(px)
    codes, days, rets = [], [], []
    for i in rows:
        j0 = i + 1
        if j0 >= n:
            continue
        ep = op[j0] * (1 + FEE)
        if not np.isfinite(ep) or ep <= 0:
            continue
        end = min(j0 + maxhold, n)
        sh, sl_seg = hi[j0:end], lo[j0:end]
        if len(sh) == 0:
            continue
        ht = sh >= ep * (1 + tp)
        k_tp = int(np.argmax(ht)) if ht.any() else -1
        k_sl = -1
        if sl is not None:
            hs = sl_seg <= ep * (1 - sl)
            k_sl = int(np.argmax(hs)) if hs.any() else -1
        if k_sl >= 0 and (k_tp < 0 or k_sl <= k_tp):
            k, code, r = k_sl, -1, -sl
        elif k_tp >= 0:
            k, code, r = k_tp, 1, tp
        else:
            k = len(sh) - 1
            code, r = 0, cl[j0 + k] / ep - 1
        codes.append(code)
        days.append(k + 1)
        rets.append((r - FEE) * 100)
    return np.array(codes), np.array(days, dtype=float), np.array(rets)


def collect(p: pd.DataFrame, prices: dict, fn, tp: float, sl: float | None,
            maxhold: int, rng: np.random.Generator):
    idx = {}
    for t, px in prices.items():
        pos = {d: i for i, d in enumerate(px.index)}
        if fn is None:
            k = max(1, int(len(px) * 0.06))
            idx[t] = np.sort(rng.choice(len(px), size=k, replace=False))
        else:
            sub = p[(p["ticker"] == t)]
            m = fn(sub).fillna(False)
            idx[t] = np.sort(np.array([pos[d] for d in sub[m]["date"] if d in pos]))
    C, D, R = [], [], []
    for t, rows in idx.items():
        if len(rows) == 0:
            continue
        c, d, r = walk(prices[t], rows, tp, sl, maxhold)
        C.append(c)
        D.append(d)
        R.append(r)
    return np.concatenate(C), np.concatenate(D), np.concatenate(R)


def summarize(c, d, r, label: str, cfg: str) -> dict:
    win = c == 1
    lose = c == -1
    miss = c == 0
    rec = {"규칙": label, "설정": cfg, "거래": len(c),
           "달성률%": round(win.mean() * 100, 1)}
    if win.any():
        rec["달성 중앙일"] = int(np.median(d[win]))
        rec["달성 평균일"] = round(d[win].mean(), 1)
        rec["달성 75%일"] = int(np.percentile(d[win], 75))
    rec["손절률%"] = round(lose.mean() * 100, 1) if lose.any() else 0.0
    rec["미달성률%"] = round(miss.mean() * 100, 1)
    rec["미달성 손익%"] = round(r[miss].mean(), 2) if miss.any() else np.nan
    rec["전체 평균%"] = round(r.mean(), 2)
    rec["평균 보유일"] = round(d.mean(), 1)
    rec["연환산%"] = round(r.mean() / d.mean() * 252, 1)
    return rec


def day_distribution(d, c) -> dict:
    win = c == 1
    out = {}
    for lo, hi in DAY_BUCKETS:
        k = ((d >= lo) & (d <= hi) & win).sum()
        out[f"{lo}일" if lo == hi else (f"{lo}~{hi}일" if hi < 1000 else f"{lo}일+")] = \
            round(k / len(c) * 100, 1)
    return out


def main():
    pd.set_option("display.width", 360)
    pd.set_option("display.max_columns", 40)
    rng = np.random.default_rng(SEED)
    p, prices = build(market_frame())
    print(f"패널 {p['date'].min().date()} ~ {p['date'].max().date()} / "
          f"{p['ticker'].nunique()}종목")

    print("\n" + "=" * 160)
    print("목표 달성률 · 달성 소요일 — 손절 없이 순수하게 '목표에 닿는가'만")
    print("=" * 160)
    rows = []
    for tp in (0.10, 0.15, 0.20):
        for maxhold in (20, 60):
            for label, fn in RULES.items():
                c, d, r = collect(p, prices, fn, tp, None, maxhold, rng)
                rows.append(summarize(c, d, r, label, f"+{tp:.0%} / {maxhold}일 이내"))
    t = pd.DataFrame(rows)
    for cfg in t["설정"].unique():
        print(f"\n[{cfg}]")
        print(t[t["설정"] == cfg].drop(columns=["설정"]).to_string(index=False))
    t.to_csv(os.path.join(OUT_DIR, "r2_barrier.csv"), index=False)

    print("\n" + "=" * 160)
    print("달성까지 걸린 시간 분포 (+10% / 60일 이내, 전체 거래 대비 %)")
    print("=" * 160)
    rows = []
    for label, fn in RULES.items():
        c, d, r = collect(p, prices, fn, 0.10, None, 60, rng)
        rows.append({"규칙": label, **day_distribution(d, c),
                     "미달성%": round((c == 0).mean() * 100, 1)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n" + "=" * 160)
    print("손절을 걸었을 때 (실전 기준)")
    print("=" * 160)
    rows = []
    for tp, sl, mh in [(0.10, 0.10, 20), (0.10, 0.10, 60), (0.15, 0.10, 60),
                       (0.15, 0.15, 60), (0.20, 0.15, 60)]:
        for label, fn in RULES.items():
            c, d, r = collect(p, prices, fn, tp, sl, mh, rng)
            rows.append(summarize(c, d, r, label,
                                  f"+{tp:.0%} / -{sl:.0%} / {mh}일"))
    t2 = pd.DataFrame(rows)
    for cfg in t2["설정"].unique():
        print(f"\n[{cfg}]")
        print(t2[t2["설정"] == cfg].drop(columns=["설정"]).to_string(index=False))
    t2.to_csv(os.path.join(OUT_DIR, "r2_barrier_sl.csv"), index=False)


if __name__ == "__main__":
    main()
