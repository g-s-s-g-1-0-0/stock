"""
analyze_strategy_overlap.py
===========================
A~G 전략의 실제 중복/MECE 여부를 전 유니버스(주요 종목 ~139개, 2010~2026)
일별 데이터로 실증한다. 우선순위 가드(not entry_a ...)를 '제거'한 raw 조건으로
각 전략 충족 여부를 따로 계산해, 동시에 몇 개가 충족되는지/어떤 쌍이 겹치는지/
가드가 어떤 하위 전략을 가리는지 집계한다.
"""
from __future__ import annotations
import os, sys, itertools
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_qqq_block_v2 as bt
from calculator import rules

EVAL_START = bt.EVAL_START
STRATS = ["A", "B", "C", "D", "E", "F", "G"]


def main():
    qqq = bt.dl("QQQ"); vixdf = bt.dl("^VIX")
    qstate = bt.build_qqq_state(qqq)
    vix = vixdf["Close"].reindex(qstate.index, method="ffill")

    raw_counts = {s: 0 for s in STRATS}          # 우선순위 무시, 단독 raw 충족 횟수
    chosen_counts = {s: 0 for s in STRATS}       # 실제 우선순위로 '채택'된 횟수
    masked_counts = {s: 0 for s in STRATS}       # raw 충족했으나 상위 전략에 밀려 가려진 횟수
    pair_counts = {f"{a}&{b}": 0 for a, b in itertools.combinations(STRATS, 2)}
    multi_hist = {}                              # 동시 충족 개수 분포
    total_days = 0

    for t in bt.UNIVERSE:
        df = bt.dl(t)
        if df is None or len(df) < 300:
            continue
        from calculator.indicators import add_indicators
        d = bt.supplement(add_indicators(df)).join(qstate, how="inner").dropna(subset=["premium"])
        if len(d) < 200:
            continue
        rows = bt.prebuild_rows(d)
        vixarr = vix.reindex(d.index, method="ffill").to_numpy()
        prem_a = d["premium"].to_numpy(); rec_a = d["recovery"].to_numpy()
        dates = d.index
        for i in range(len(d)):
            if dates[i] < EVAL_START:
                continue
            r = rows[i]
            if r is None or np.isnan(prem_a[i]):
                continue
            recovery = bool(rec_a[i])
            block = 18 if recovery else 9
            ev = rules.evaluate_buy_condition(
                r, vixarr[i], float(prem_a[i]), False,
                nasdaq_buy_block_max=block, is_recovery_market=recovery,
                recovery_momentum_exception=False,
            )
            cond = ev["conditions"]
            raw = {s: bool(all(cond[s])) for s in STRATS}
            hits = [s for s in STRATS if raw[s]]
            total_days += 1
            if not hits:
                continue
            multi_hist[len(hits)] = multi_hist.get(len(hits), 0) + 1
            for s in hits:
                raw_counts[s] += 1
            for a, b in itertools.combinations(hits, 2):
                pair_counts[f"{a}&{b}"] += 1
            # 우선순위 채택 = 첫 번째(A>B>C>D>E>F>G)
            winner = hits[0]
            chosen_counts[winner] += 1
            for s in hits[1:]:
                masked_counts[s] += 1

    print("=" * 78)
    print("전략별 raw 충족 / 실제 채택 / 가려짐 (전 유니버스 · 2010~2026)")
    print("=" * 78)
    print(f"{'전략':<4}{'raw충족':>10}{'채택':>10}{'가려짐':>10}{'가려짐비율':>12}")
    for s in STRATS:
        rc = raw_counts[s]; mk = masked_counts[s]
        ratio = (mk / rc * 100) if rc else 0
        print(f"{s:<4}{rc:>10}{chosen_counts[s]:>10}{mk:>10}{ratio:>11.1f}%")

    print("\n동시 충족 개수 분포 (raw, 우선순위 무시):")
    for k in sorted(multi_hist):
        print(f"  {k}개 동시 충족: {multi_hist[k]:,}일")

    print("\n전략 쌍별 동시 충족 횟수 (0이면 절대 안 겹침):")
    for k, v in sorted(pair_counts.items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k}: {v:,}")
    zeros = [k for k, v in pair_counts.items() if v == 0]
    print(f"\n절대 동시 충족 안 되는 쌍 ({len(zeros)}개): {', '.join(zeros)}")


if __name__ == "__main__":
    main()
