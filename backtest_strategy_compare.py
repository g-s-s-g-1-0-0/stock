"""
backtest_strategy_compare.py
============================
A~G(현행 청산엔진) vs H(A안: 차단면제 + MA200 이격≤60% 캡 + G형 청산)을
전략별로 분해해 승률/기대값(평균수익)/보유기간 등으로 직접 비교한다.
- A~G: backtest_qqq_block_v2.simulate(AS-IS: 회복18/비회복9, 모멘텀예외 OFF)
- H : 본 스크립트 simulate_h (진입은 BB 알림 규칙, 청산은 evaluate_exit_condition('G'))
"""
from __future__ import annotations
import os, sys, dataclasses
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_qqq_block_v2 as bt
import backtest_bb_pullback as H
from calculator.indicators import add_indicators
from calculator import rules

EVAL_START = bt.EVAL_START
H_DIST_CAP = 0.60  # MA200 이격 상한


def simulate_h(d, entries, prem_a, rec_a, peak_a, rows, vixarr):
    c = d["Close"].to_numpy(); ma200 = d["MA200"].to_numpy(); dates = d.index
    holding = False; ep = ei = 0; cooldown = 0
    trades = []
    for i in range(len(d)):
        if dates[i] < EVAL_START or np.isnan(prem_a[i]):
            continue
        if holding:
            row = dataclasses.replace(rows[i], entry_price=ep) if rows[i] else None
            if row is None:
                continue
            res = rules.evaluate_exit_condition(
                row, strategy_type="G", nasdaq_peak_alert=bool(peak_a[i]),
                trading_days=i - ei)
            if res["shouldExit"]:
                trades.append({"strat": "H", "ret": (c[i]-ep)/ep, "days": i-ei,
                               "reason": res["reason"] or "", "exit_i": i})
                holding = False; cooldown = 2
            continue
        if cooldown > 0:
            cooldown -= 1; continue
        if not entries[i] or rows[i] is None:
            continue
        # A안: 공통 상단차단 면제, 단 MA200 이격 ≤60% 과열 가드
        if ma200[i] and ma200[i] > 0 and (c[i]/ma200[i] - 1) > H_DIST_CAP:
            continue
        holding = True; ep = c[i]; ei = i
    return trades


def per_strat(trades):
    r = np.array([t["ret"] for t in trades])
    pf_n = r[r > 0].sum(); pf_d = -r[r < 0].sum()
    days = np.array([t["days"] for t in trades])
    return {
        "거래": len(trades),
        "승률%": round((r > 0).mean()*100, 1),
        "기대값%": round(r.mean()*100, 2),
        "중앙%": round(np.median(r)*100, 2),
        "합%": round(r.sum()*100, 0),
        "PF": round(pf_n/pf_d, 2) if pf_d > 0 else 99,
        "손절%": round(sum(1 for t in trades if "손절" in t["reason"])/len(trades)*100, 1),
        "곡선MDD%": round(bt.equity_mdd(trades), 1),
        "평균일": round(days.mean(), 1),
        "중앙일": int(np.median(days)),
    }


def main():
    qqq = bt.dl("QQQ"); qstate = bt.build_qqq_state(qqq)
    vix = bt.dl("^VIX")["Close"].reindex(qstate.index, method="ffill")
    print(f"유니버스 / {qstate.index[0].date()}~{qstate.index[-1].date()}")

    ag_trades = []   # A~G
    h_trades = []
    n_stock = 0
    for t in bt.UNIVERSE:
        df = bt.dl(t)
        if df is None or len(df) < 300:
            continue
        d = bt.supplement(add_indicators(df)).join(qstate, how="inner").dropna(subset=["premium"])
        if len(d) < 250:
            continue
        n_stock += 1
        rows = bt.prebuild_rows(d)
        vixarr = vix.reindex(d.index, method="ffill").to_numpy()
        # A~G (AS-IS)
        ag_trades += bt.simulate(d, rows, vixarr, recovery_block=18, normal_block=9)
        # H
        try:
            entries = H.build_entries(d)
        except Exception:
            continue
        h_trades += simulate_h(d, entries, d["premium"].to_numpy(), d["recovery"].to_numpy(),
                               d["peak"].to_numpy(), rows, vixarr)

    by = {}
    for t in ag_trades:
        by.setdefault(t["strat"], []).append(t)
    by["H"] = h_trades

    print(f"종목 {n_stock}개\n")
    order = ["A", "B", "C", "D", "E", "F", "G", "H"]
    label = {"A": "모멘텀재가속", "B": "공황저점", "C": "스퀴즈돌파", "D": "추세강화",
             "E": "스퀴즈저점", "F": "BB극단저점", "G": "회복장20일선눌림", "H": "BB상단눌림(신규)"}
    out = []
    for s in order:
        if s not in by or not by[s]:
            out.append({"전략": f"{s} {label.get(s,'')}", "거래": 0}); continue
        row = {"전략": f"{s} {label.get(s,'')}"}; row.update(per_strat(by[s]))
        out.append(row)
    res = pd.DataFrame(out)
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
    print("=" * 160)
    print("전략별 성과 비교 — A~G(현행 청산) vs H(A안) · 2010~2026 · 주요종목 · 균등배분 근사")
    print("=" * 160)
    print(res.to_string(index=False))
    res.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_strategy_compare_summary.csv"), index=False)


if __name__ == "__main__":
    main()
