"""
backtest_disparity_components.py
================================
A/C/D 전략의 QQQ 이격도 게이트는 두 부분으로 구성된다.
  · 상단 과열 차단 : ixic_dist <= block_max (회복18/비회복9)
  · 하한 -3% 게이트 : ixic_dist >= NASDAQ_DIST_UPPER(-3)
어느 부분이 성과를 좌우하는지(어느 쪽을 풀면/지키면 좋은지) 분해 비교한다.
모드: ON(둘 다) / 상단만해제 / 하한만해제 / 둘다해제.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from calculator import rules
import backtest_disparity_removal as dr
import backtest_qqq_block_v2 as bt

ACD = ["A", "C", "D"]
MODES = ["ON", "상단만해제", "하한만해제", "둘다해제"]


def entry_component(r, vix, prem, recovery, strat, mode):
    block_max = 18.0 if recovery else 9.0
    if mode == "ON":
        bm, floor = block_max, -3.0
    elif mode == "상단만해제":
        bm, floor = 999.0, -3.0
    elif mode == "하한만해제":
        bm, floor = block_max, -999.0
    else:  # 둘다해제
        bm, floor = 999.0, -999.0
    orig = rules.STRATEGY_RULES["NASDAQ_DIST_UPPER"]
    rules.STRATEGY_RULES["NASDAQ_DIST_UPPER"] = floor
    try:
        ev = rules.evaluate_buy_condition(
            r, vix, prem, False, nasdaq_buy_block_max=bm, is_recovery_market=recovery)
        return all(ev["conditions"][strat])
    finally:
        rules.STRATEGY_RULES["NASDAQ_DIST_UPPER"] = orig


def main():
    qqq = dr.get("QQQ"); vixdf = dr.get("^VIX")
    qstate = bt.build_qqq_state(qqq).dropna(subset=["premium"])
    vix = vixdf["Close"].reindex(qstate.index, method="ffill")
    eval_start = qstate.index[0]
    print(f"기간 {qstate.index[0].date()}~{qstate.index[-1].date()}")

    all_rows = []
    for uname, tickers in dr.UNIVERSES.items():
        if not tickers:
            continue
        stocks = dr.load_universe(tickers, qstate, vix)
        print(f"\n{'='*140}\n[{uname}] 종목 {len(stocks)}개\n{'='*140}")
        rows = []
        for s in ACD:
            for m in MODES:
                trades = []
                for t, (d, rws, va, pk) in stocks.items():
                    trades += dr.simulate_single(d, rws, va, pk, eval_start, s, m,
                                                 entry_fn=entry_component)
                mt = dr.metrics(trades)
                rows.append({"전략": f"{s} {dr.LABEL[s]}", "모드": m,
                             "거래": mt["거래"], "승률": mt["승률"], "기대값": mt["기대값"],
                             "PF": mt["PF"], "MDD": mt["MDD"], "평균일": mt["평균일"]})
        res = pd.DataFrame(rows)
        pd.set_option("display.width", 240); pd.set_option("display.max_columns", 30)
        print(res.to_string(index=False))
        res.insert(0, "유니버스", uname)
        all_rows.append(res)

    if all_rows:
        big = pd.concat(all_rows, ignore_index=True)
        out = os.path.join(dr.ROOT, "backtest_disparity_components_summary.csv")
        big.to_csv(out, index=False)
        print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
