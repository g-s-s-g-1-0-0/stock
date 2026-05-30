"""
backtest_h_tuning.py
====================
H(BB 상단 눌림) 진입은 고정, 청산/이격캡만 그리드로 바꿔가며 기대값이
개선되는지 확인한다. 기준선(A안): cap0.60 / 목표0.12·정체15·0.08 / G형.
"""
from __future__ import annotations
import os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_qqq_block_v2 as bt
import backtest_bb_pullback as H
from calculator.indicators import add_indicators

EVAL_START = bt.EVAL_START


def simulate_h(d, entries, prem_a, cfg):
    c = d["Close"].to_numpy(); ma200 = d["MA200"].to_numpy(); dates = d.index
    cap, tgt, stop, sd, sr, mx = cfg["cap"], cfg["tgt"], cfg["stop"], cfg["sd"], cfg["sr"], cfg["mx"]
    holding = False; ep = ei = 0; cooldown = 0; trades = []
    for i in range(len(d)):
        if dates[i] < EVAL_START or np.isnan(prem_a[i]):
            continue
        if holding:
            r = (c[i]-ep)/ep; days = i-ei; reason = ""
            if r >= tgt: reason = "목표"
            elif r <= -stop: reason = "손절"
            elif days >= sd and r < sr: reason = "정체"
            elif days >= mx: reason = "최대보유"
            if reason:
                trades.append({"ret": r, "days": days, "reason": reason}); holding = False; cooldown = 2
            continue
        if cooldown > 0:
            cooldown -= 1; continue
        if not entries[i]:
            continue
        if ma200[i] and ma200[i] > 0 and (c[i]/ma200[i]-1) > cap:
            continue
        holding = True; ep = c[i]; ei = i
    return trades


def summ(trades):
    if not trades:
        return None
    r = np.array([t["ret"] for t in trades]); days = np.array([t["days"] for t in trades])
    pf_n = r[r > 0].sum(); pf_d = -r[r < 0].sum()
    return {"거래": len(trades), "승률%": round((r > 0).mean()*100, 1),
            "기대값%": round(r.mean()*100, 2), "중앙%": round(np.median(r)*100, 2),
            "PF": round(pf_n/pf_d, 2) if pf_d > 0 else 99,
            "손절%": round(sum(1 for t in trades if t["reason"] == "손절")/len(trades)*100, 1),
            "평균일": round(days.mean(), 1)}


CONFIGS = {
    "A안 기준(cap60/12·15·8/40)": {"cap": .60, "tgt": .12, "stop": .10, "sd": 15, "sr": .08, "mx": 40},
    "단기조임(cap60/8·10·5/25)":   {"cap": .60, "tgt": .08, "stop": .06, "sd": 10, "sr": .05, "mx": 25},
    "캡강화(cap40/12·15·8/40)":    {"cap": .40, "tgt": .12, "stop": .10, "sd": 15, "sr": .08, "mx": 40},
    "캡강화+단기(cap40/8·10·5/25)": {"cap": .40, "tgt": .08, "stop": .06, "sd": 10, "sr": .05, "mx": 25},
    "타이트목표(cap50/10·7·6/20)":  {"cap": .50, "tgt": .10, "stop": .07, "sd": 8,  "sr": .06, "mx": 20},
    "트렌드추종(cap40/15·8·10/50)": {"cap": .40, "tgt": .15, "stop": .08, "sd": 20, "sr": .10, "mx": 50},
}


def main():
    qqq = bt.dl("QQQ"); qstate = bt.build_qqq_state(qqq)
    print(f"{qstate.index[0].date()}~{qstate.index[-1].date()}  주요종목")
    acc = {k: [] for k in CONFIGS}
    n = 0
    for t in bt.UNIVERSE:
        df = bt.dl(t)
        if df is None or len(df) < 300:
            continue
        d = bt.supplement(add_indicators(df)).join(qstate, how="inner").dropna(subset=["premium"])
        if len(d) < 250:
            continue
        try:
            entries = H.build_entries(d)
        except Exception:
            continue
        n += 1
        prem = d["premium"].to_numpy()
        for k, cfg in CONFIGS.items():
            acc[k] += simulate_h(d, entries, prem, cfg)
    rows = []
    for k in CONFIGS:
        s = summ(acc[k]) or {}
        rows.append({"설정": k, **s})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)
    print("=" * 130)
    print(f"H 튜닝 그리드 · 종목 {n}개 · (A~G 참고: 기대값 D 1.37 / F 1.82 / G 3.25)")
    print("=" * 130)
    print(df.to_string(index=False))
    df.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_h_tuning_summary.csv"), index=False)


if __name__ == "__main__":
    main()
