"""R2를 기존 A~H·전략1/2와 같은 잣대로 비교하고 위험을 정량화한다.

7월 29일 사례가 운이었는지 보려면 두 가지를 봐야 한다.
  (1) 그날을 빼고도 성적이 유지되는가 — 기간을 잘라 확인
  (2) 성공 전에 얼마나 얻어맞는가 — 연속 손절, 동시 발동 집중도, 누적 낙폭

모든 전략을 동일하게 '신호 다음날 시가 진입 → 목표 도달 또는 손절 또는 기간
만료'로 처리한다. A~H와 전략1/2 신호는 기존 패널(s4_panel.pkl)에서 가져온다.
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

from ma200_macd_golden import FEE, OUT_DIR, PANEL_PATH
from washout_rules import build, market_frame

AH = list("ABCDEFGH")


def attach(p: pd.DataFrame) -> pd.DataFrame:
    base = pd.read_pickle(PANEL_PATH)[["ticker", "date", "ahCode", "liveCode"]]
    return p.merge(base, on=["ticker", "date"], how="left")


def masks(p: pd.DataFrame) -> dict[str, pd.Series]:
    m = {f"전략 {c}": (p["ahCode"] == c) for c in AH}
    m["전략 1"] = p["liveCode"] == "1"
    m["전략 2"] = p["liveCode"] == "2"
    m["R2 (신규)"] = (p["RSI"] < 30) & (p["dd60"] < -45)
    return m


def trades(p: pd.DataFrame, prices: dict, mask: pd.Series,
           tp: float, sl: float, maxhold: int) -> pd.DataFrame:
    rows = []
    for t, grp in p[mask.fillna(False)].groupby("ticker"):
        px = prices.get(t)
        if px is None:
            continue
        pos = {d: i for i, d in enumerate(px.index)}
        op, hi, lo, cl = (px["Open"].to_numpy(), px["High"].to_numpy(),
                          px["Low"].to_numpy(), px["Close"].to_numpy())
        for d in grp["date"]:
            i = pos.get(d)
            if i is None or i + 1 >= len(cl):
                continue
            ep = op[i + 1] * (1 + FEE)
            if not np.isfinite(ep) or ep <= 0:
                continue
            end = min(i + 1 + maxhold, len(cl))
            sh, sll = hi[i + 1:end], lo[i + 1:end]
            if len(sh) == 0:
                continue
            ht, hs = sh >= ep * (1 + tp), sll <= ep * (1 - sl)
            k_tp = int(np.argmax(ht)) if ht.any() else -1
            k_sl = int(np.argmax(hs)) if hs.any() else -1
            if k_sl >= 0 and (k_tp < 0 or k_sl <= k_tp):
                k, code, r = k_sl, -1, -sl
            elif k_tp >= 0:
                k, code, r = k_tp, 1, tp
            else:
                k = len(sh) - 1
                code, r = 0, cl[i + 1 + k] / ep - 1
            rows.append({"ticker": t, "date": d, "code": code, "days": k + 1,
                         "ret": (r - FEE) * 100})
    return pd.DataFrame(rows)


def stats(tr: pd.DataFrame, name: str) -> dict:
    if tr.empty:
        return {"전략": name, "거래": 0}
    win = tr["code"] == 1
    seq = tr.sort_values("date")
    eq = seq["ret"].cumsum().to_numpy()
    mdd = float((eq - np.maximum.accumulate(eq)).min())
    loss = (seq["code"] != 1).to_numpy()
    run, best = 0, 0
    for x in loss:
        run = run + 1 if x else 0
        best = max(best, run)
    days_with = tr["date"].nunique()
    top = tr["date"].value_counts()
    return {
        "전략": name, "거래": len(tr), "종목": tr["ticker"].nunique(),
        "달성률%": round(win.mean() * 100, 1),
        "손절률%": round((tr["code"] == -1).mean() * 100, 1),
        "달성중앙일": int(np.median(tr.loc[win, "days"])) if win.any() else np.nan,
        "평균보유일": round(tr["days"].mean(), 1),
        "평균손익%": round(tr["ret"].mean(), 2),
        "연환산%": round(tr["ret"].mean() / tr["days"].mean() * 252, 1),
        "최대연속손실": best,
        "누적낙폭%p": round(mdd, 1),
        "신호일수": days_with,
        "하루최대동시": int(top.max()),
        "상위1%일 비중%": round(top.head(max(1, days_with // 100)).sum() / len(tr) * 100, 1),
    }


def period_split(p: pd.DataFrame, prices: dict, mask: pd.Series,
                 name: str) -> pd.DataFrame:
    cuts = [("1999~2012", None, "2012-12-31"),
            ("2013~2026", "2013-01-01", None),
            ("2026 제외", None, "2025-12-31"),
            ("2026-07-29 하루 제외", None, None)]
    rows = []
    for label, lo, hi in cuts:
        m = mask.fillna(False).copy()
        if lo:
            m &= p["date"] >= lo
        if hi:
            m &= p["date"] <= hi
        if label.endswith("하루 제외"):
            m &= p["date"] != pd.Timestamp("2026-07-29")
        tr = trades(p, prices, m, 0.10, 0.10, 60)
        if tr.empty:
            continue
        s = stats(tr, label)
        rows.append({"구간": label, "거래": s["거래"], "달성률%": s["달성률%"],
                     "달성중앙일": s["달성중앙일"], "평균손익%": s["평균손익%"],
                     "연환산%": s["연환산%"]})
    print(f"\n[{name} · 기간 분할]")
    print(pd.DataFrame(rows).to_string(index=False))


def yearly(tr: pd.DataFrame, name: str) -> None:
    g = tr.groupby(tr["date"].dt.year)
    t = pd.DataFrame({"거래": g.size(),
                      "달성률%": (g["code"].apply(lambda s: (s == 1).mean()) * 100).round(1),
                      "평균손익%": g["ret"].mean().round(2)})
    t = t[t["거래"] >= 5]
    pos = int((t["평균손익%"] > 0).sum())
    print(f"\n[{name} · 연도별] {len(t)}개 연도 중 플러스 {pos}년 "
          f"({pos / len(t) * 100:.0f}%) · 최악 "
          f"{t['평균손익%'].idxmin()}년 {t['평균손익%'].min():+.2f}%")
    print(t.to_string())


def recent_episode(p: pd.DataFrame, prices: dict, mask: pd.Series) -> None:
    """2026년 7월 하락 구간 — 바닥 전에 몇 번 맞았는가."""
    m = mask.fillna(False) & p["date"].between("2026-07-01", "2026-08-07")
    tr = trades(p, prices, m, 0.10, 0.10, 60).sort_values("date")
    if tr.empty:
        print("\n[2026년 7월 구간] 신호 없음")
        return
    tr["구분"] = np.where(tr["date"] < "2026-07-29", "7/29 이전",
                        np.where(tr["date"] == "2026-07-29", "7/29 당일", "7/29 이후"))
    g = tr.groupby("구분").agg(거래=("ret", "size"),
                             달성률=("code", lambda s: round((s == 1).mean() * 100, 1)),
                             평균손익=("ret", "mean"))
    g["평균손익"] = g["평균손익"].round(2)
    print("\n[2026년 7월 하락 구간 — 137종목 기준]")
    print(g.to_string())
    print(f"  7/29 이전 손절 {int((tr[tr['구분'] == '7/29 이전']['code'] == -1).sum())}건 / "
          f"7/29 당일 동시 발동 {int((tr['구분'] == '7/29 당일').sum())}종목")


def main():
    pd.set_option("display.width", 400)
    pd.set_option("display.max_columns", 50)
    p, prices = build(market_frame())
    p = attach(p)
    ms = masks(p)

    for tp, sl in [(0.10, 0.10), (0.15, 0.15)]:
        print("\n" + "=" * 170)
        print(f"전략 비교 — +{tp:.0%} 익절 / -{sl:.0%} 손절 / 최대 60거래일 "
              f"(2000-03 ~ 2026-08, 137종목)")
        print("=" * 170)
        rows = []
        for name, m in ms.items():
            tr = trades(p, prices, m, tp, sl, 60)
            if len(tr) >= 50:
                rows.append(stats(tr, name))
        t = pd.DataFrame(rows).sort_values("연환산%", ascending=False)
        print(t.to_string(index=False))
        t.to_csv(os.path.join(OUT_DIR, f"strategy_compare_{int(tp*100)}.csv"), index=False)

    r2 = ms["R2 (신규)"]
    tr = trades(p, prices, r2, 0.10, 0.10, 60)
    yearly(tr, "R2")
    period_split(p, prices, r2, "R2")
    recent_episode(p, prices, r2)

    print("\n" + "=" * 170)
    print("연속 손실 분포 — 성공 전에 몇 번 맞는가 (+10%/-10%/60일)")
    print("=" * 170)
    rows = []
    for name, m in ms.items():
        t2 = trades(p, prices, m, 0.10, 0.10, 60)
        if len(t2) < 50:
            continue
        seq = t2.sort_values("date")["code"].to_numpy() != 1
        runs, cur = [], 0
        for x in seq:
            if x:
                cur += 1
            elif cur:
                runs.append(cur)
                cur = 0
        if cur:
            runs.append(cur)
        runs = np.array(runs) if runs else np.array([0])
        rows.append({"전략": name, "손실군집수": len(runs),
                     "평균연속손실": round(runs.mean(), 1),
                     "중앙값": int(np.median(runs)),
                     "90%분위": int(np.percentile(runs, 90)),
                     "최대": int(runs.max())})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
