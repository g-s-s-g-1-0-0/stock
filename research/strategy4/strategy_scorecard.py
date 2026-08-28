"""전략별 성과·위험을 같은 잣대로 세운 스코어카드.

'연환산 %'는 슬롯 하나를 무한히 재활용한다고 가정한 값이라, 하루에 10개씩
신호를 뿌리는 전략과 6일에 하나 내는 전략을 같은 줄에 놓으면 왜곡된다.
그래서 세 가지를 같이 본다.

  (1) 거래 단위 성과 — 달성률·손절률·평균손익
  (2) 거래 단위 위험 — 최대 연속손실, 누적 낙폭, 하루 최대 동시 발동
  (3) 슬롯 5개짜리 실제 계좌 시뮬 — 자본 제약을 넣으면 순위가 바뀐다
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

from ma200_macd_golden import OUT_DIR, build_qqq_state
from washout_rules import build, market_frame
from strategy_compare import attach, masks, trades

TP, SL, MAXHOLD = 0.10, 0.10, 60
SLOTS = 5


def risk_stats(tr: pd.DataFrame) -> dict:
    seq = tr.sort_values("date")
    eq = seq["ret"].cumsum().to_numpy()
    mdd = float((eq - np.maximum.accumulate(eq)).min())
    loss = (seq["code"] != 1).to_numpy()
    run = best = 0
    for x in loss:
        run = run + 1 if x else 0
        best = max(best, run)
    per_day = tr["date"].value_counts()
    yr = tr.groupby(tr["date"].dt.year)["ret"].mean()
    yr = yr[tr.groupby(tr["date"].dt.year).size() >= 5]
    return {
        "최대연속손실": best,
        "누적낙폭%p": round(mdd, 1),
        "하루최대동시": int(per_day.max()),
        "플러스연도": f"{int((yr > 0).sum())}/{len(yr)}" if len(yr) else "-",
    }


def core_stats(tr: pd.DataFrame, name: str) -> dict:
    win = tr["code"] == 1
    return {
        "전략": name,
        "거래": len(tr),
        "신호일수": tr["date"].nunique(),
        "달성률%": round(win.mean() * 100, 1),
        "손절률%": round((tr["code"] == -1).mean() * 100, 1),
        "달성중앙일": int(np.median(tr.loc[win, "days"])) if win.any() else np.nan,
        "평균보유일": round(tr["days"].mean(), 1),
        "평균손익%": round(tr["ret"].mean(), 2),
        "연환산%": round(tr["ret"].mean() / tr["days"].mean() * 252, 1),
        **risk_stats(tr),
    }


def portfolio(tr: pd.DataFrame, cal: pd.DatetimeIndex, slots: int = SLOTS) -> dict:
    """슬롯이 한정된 실제 계좌를 흉내낸다. 먼저 뜬 신호부터 채운다."""
    if tr.empty:
        return {}
    pos = {d: i for i, d in enumerate(cal)}
    ev = tr.copy()
    ev["i"] = ev["date"].map(pos)
    ev = ev.dropna(subset=["i"]).sort_values(["i", "ticker"])
    ev["i"] = ev["i"].astype(int)
    ev["exit"] = ev["i"] + 1 + ev["days"]

    cash, equity = 1.0, 1.0
    open_pos: list[tuple[int, float, float]] = []
    curve, taken, skipped = [], 0, 0
    by_day: dict[int, pd.DataFrame] = {k: v for k, v in ev.groupby("i")}

    for i in range(len(cal)):
        still = []
        for xi, stake, r in open_pos:
            if xi <= i:
                cash += stake * (1 + r / 100)
            else:
                still.append((xi, stake, r))
        open_pos = still
        equity = cash + sum(s for _, s, _ in open_pos)
        day = by_day.get(i)
        if day is not None:
            for _, row in day.iterrows():
                if len(open_pos) >= slots:
                    skipped += 1
                    continue
                stake = equity / slots
                if stake > cash:
                    skipped += 1
                    continue
                cash -= stake
                open_pos.append((int(row["exit"]), stake, float(row["ret"])))
                taken += 1
        curve.append(cash + sum(s for _, s, _ in open_pos))

    eq = np.array(curve)
    yrs = len(cal) / 252
    cagr = (eq[-1] ** (1 / yrs) - 1) * 100
    mdd = float(((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min() * 100)
    invested = np.mean([1 if c < 1 else 0 for c in curve])
    return {
        "최종배수": round(eq[-1], 2),
        "CAGR%": round(cagr, 1),
        "최대낙폭%": round(mdd, 1),
        "체결/신호": f"{taken}/{taken + skipped}",
        "체결률%": round(taken / max(1, taken + skipped) * 100, 1),
    }


def combo(p: pd.DataFrame, prices: dict, ms: dict, names: list[str],
          cal: pd.DatetimeIndex) -> dict:
    """여러 전략을 동시에 켠 계좌. 같은 종목·같은 날 중복 신호는 하나로 친다."""
    m = pd.Series(False, index=p.index)
    for n in names:
        m |= ms[n].fillna(False)
    tr = trades(p, prices, m, TP, SL, MAXHOLD).drop_duplicates(["ticker", "date"])
    if tr.empty:
        return {}
    gap = np.diff(np.unique(np.sort(tr["date"].map(
        {d: i for i, d in enumerate(cal)}).dropna().to_numpy())))
    return {
        "조합": " + ".join(n.replace("전략 ", "").replace(" (신규)", "") for n in names),
        "거래": len(tr),
        "달성률%": round((tr["code"] == 1).mean() * 100, 1),
        "평균손익%": round(tr["ret"].mean(), 2),
        "평균공백일": round(gap.mean(), 1) if len(gap) else 0,
        "최장공백일": int(gap.max()) if len(gap) else 0,
        **portfolio(tr, cal),
    }


def combo_mixed(p: pd.DataFrame, prices: dict, ms: dict,
                spec: list[tuple[str, int]], cal: pd.DatetimeIndex) -> dict:
    """전략마다 최대 보유일이 다를 때. D는 규칙상 30일이 상한이다."""
    parts = []
    for name, mh in spec:
        parts.append(trades(p, prices, ms[name].fillna(False), TP, SL, mh))
    tr = pd.concat(parts).drop_duplicates(["ticker", "date"]).sort_values("date")
    return {"조합": " + ".join(f"{n.replace('전략 ', '')}({m}일)" for n, m in spec),
            "거래": len(tr), **portfolio(tr, cal)}


def main():
    pd.set_option("display.width", 400)
    pd.set_option("display.max_columns", 60)
    qstate = build_qqq_state()
    cal = qstate.index
    p, prices = build(market_frame())
    p = attach(p)
    q = qstate.rename_axis("date").reset_index()[["date", "regime"]]
    p = p.merge(q, on="date", how="left")
    ms = masks(p)

    cache = {}
    print("\n" + "=" * 175)
    print(f"전 구간 (2000-03 ~ 2026-08, 137종목) — +{TP:.0%} 익절 / -{SL:.0%} 손절 / 최대 {MAXHOLD}일")
    print("=" * 175)
    rows = []
    for name, m in ms.items():
        tr = trades(p, prices, m.fillna(False), TP, SL, MAXHOLD)
        cache[name] = tr
        if len(tr) >= 50:
            rows.append(core_stats(tr, name))
    full = pd.DataFrame(rows).sort_values("연환산%", ascending=False)
    print(full.to_string(index=False))
    full.to_csv(os.path.join(OUT_DIR, "scorecard_full.csv"), index=False)

    print("\n" + "=" * 175)
    print("정상장 한정 (2,220거래일)")
    print("=" * 175)
    rows = []
    for name, m in ms.items():
        tr = trades(p, prices, m.fillna(False) & (p["regime"] == "정상장"),
                    TP, SL, MAXHOLD)
        if len(tr) >= 50:
            rows.append(core_stats(tr, name))
    norm = pd.DataFrame(rows).sort_values("연환산%", ascending=False)
    print(norm.to_string(index=False))
    norm.to_csv(os.path.join(OUT_DIR, "scorecard_normal.csv"), index=False)

    print("\n" + "=" * 175)
    print(f"슬롯 {SLOTS}개 계좌 시뮬 — 자본이 한정되면 어떻게 되는가 (전 구간)")
    print("=" * 175)
    rows = []
    for name, tr in cache.items():
        if len(tr) < 50:
            continue
        s = portfolio(tr, cal)
        if s:
            rows.append({"전략": name, **s})
    pf = pd.DataFrame(rows).sort_values("CAGR%", ascending=False)
    print(pf.to_string(index=False))
    pf.to_csv(os.path.join(OUT_DIR, "scorecard_portfolio.csv"), index=False)

    print("\n" + "=" * 175)
    print(f"핵심 질문 — 전략 1·2에 무엇을 하나 더 켜야 하는가 (슬롯 {SLOTS}개)")
    print("=" * 175)
    base = ["전략 1", "전략 2"]
    sets = [base] + [base + [x] for x in
                     ["전략 A", "전략 C", "전략 D", "전략 E", "전략 F",
                      "전략 G", "전략 H", "R2 (신규)"]]
    rows = [combo(p, prices, ms, s, cal) for s in sets]
    cm = pd.DataFrame([r for r in rows if r])
    print(cm.to_string(index=False))
    cm.to_csv(os.path.join(OUT_DIR, "scorecard_combo.csv"), index=False)

    print("\n" + "=" * 175)
    print("각 전략의 실제 보유 상한을 적용한 조합 (D 30일 · G/H 40일 · 나머지 120일)")
    print("=" * 175)
    caps = {"전략 A": 120, "전략 C": 120, "전략 D": 30, "전략 E": 120,
            "전략 F": 120, "전략 G": 40, "전략 H": 40, "R2 (신규)": 60}
    base = [("전략 1", 60), ("전략 2", 60)]
    specs = [base] + [base + [(k, v)] for k, v in caps.items()]
    r = pd.DataFrame([combo_mixed(p, prices, ms, s, cal) for s in specs])
    print(r.sort_values("CAGR%", ascending=False).to_string(index=False))
    r.to_csv(os.path.join(OUT_DIR, "scorecard_combo_realcap.csv"), index=False)


if __name__ == "__main__":
    main()
