"""
backtest_bb_bounce_confirm.py
=============================
E(스퀴즈 저점)·F(BB 극단 저점)는 '저가 %B'만 보고 진입한다.
즉 저가가 밴드에 닿으면, 종가가 BB 중간선 아래로 더 내려가 마감(반등 실패)해도
신호가 난다. '반등을 확인하고 진입'할 때와 '현행(반등 무시)'을 비교한다.

모드(진입가는 진입 시점 종가):
  · 현행          : 저가 %B 조건만 (종가 위치 무관, 200일선만 충족)  → 신호일 종가 진입
  · 종가>밴드하단 : 추가로 종가 %B > 0  (하단밴드 위로 마감)         → 신호일 종가 진입
  · 종가>=BB중간  : 추가로 종가 %B >= 50 (BB 중간선 위 회복=반등)    → 신호일 종가 진입
  · 익일종가반등  : 신호 다음날 종가 > 신호일 종가일 때만 진입       → 익일 종가 진입

청산/지표/규칙은 프로젝트 코드 재사용. 유니버스/기간은 최대치.
"""
from __future__ import annotations
import os, sys, time, dataclasses, warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calculator import rules
import backtest_qqq_block_v2 as bt
import backtest_disparity_removal as dr

STRATS = ["E", "F"]
EF = {"E", "F"}
LABEL = {"E": "스퀴즈저점", "F": "BB극단저점"}
SAMEDAY_MODES = ["현행", "종가>밴드하단", "종가>=BB중간"]
ALL_MODES = SAMEDAY_MODES + ["익일종가반등"]


def _base_fire(r, vix, prem, recovery, strat):
    block_max = 18.0 if recovery else 9.0
    ev = rules.evaluate_buy_condition(
        r, vix, prem, False, nasdaq_buy_block_max=block_max, is_recovery_market=recovery)
    return all(ev["conditions"][strat])


def entry_sameday(r, vix, prem, recovery, strat, mode):
    if not _base_fire(r, vix, prem, recovery, strat):
        return False
    if mode == "현행":
        return True
    pb = r.pct_b  # 종가 %B
    if pb is None:
        return False
    if mode == "종가>밴드하단":
        return pb > 0.0
    if mode == "종가>=BB중간":
        return pb >= 50.0
    return False


def _exit_check(r, ep, ei, i, strat, peak_i, ef_wait):
    row = dataclasses.replace(r, entry_price=ep)
    tdays = i - ei
    res = rules.evaluate_exit_condition(
        row, strategy_type=strat, nasdaq_peak_alert=bool(peak_i),
        trading_days=tdays, upper_exit_wait_days=ef_wait if strat in EF else None)
    new_wait = ef_wait
    if strat in EF:
        rp = (row.current_price - ep) / ep
        tgt = float(rules.STRATEGY_RULES[f"TARGET_PCT_{strat}"])
        new_wait = ef_wait + 1 if rp >= tgt else 0
    return res, tdays, new_wait


def simulate_nextday(d, rows, vixarr, peak_a, eval_start, strat):
    close_a = d["Close"].to_numpy()
    prem_a = d["premium"].to_numpy(); rec_a = d["recovery"].to_numpy()
    dates = d.index; trades = []
    holding = False; ep = ei = 0; ef_wait = 0; cooldown = 0
    last_exit_price = None; last_exit_i = -10**9; pending = None
    reentry_days = int(rules.STRATEGY_RULES["REENTRY_DAYS"])

    def reentry_blocked(i):
        return (last_exit_price is not None and (i - last_exit_i) <= reentry_days
                and close_a[i] > last_exit_price * (1 - 0.03))

    for i in range(len(d)):
        if dates[i] < eval_start:
            continue
        r = rows[i]
        if r is None or np.isnan(prem_a[i]):
            continue
        if holding:
            res, tdays, ef_wait = _exit_check(r, ep, ei, i, strat, peak_a[i], ef_wait)
            if res["shouldExit"]:
                trades.append({"strat": strat, "ret": (close_a[i] - ep) / ep,
                               "days": tdays, "reason": res["reason"] or "", "exit_i": i})
                holding = False; ep = ei = 0; ef_wait = 0; cooldown = 2
                last_exit_price = close_a[i]; last_exit_i = i
            continue
        if cooldown > 0:
            cooldown -= 1; pending = None; continue
        # 전일 신호의 익일 반등 확인
        if pending is not None:
            if close_a[i] > close_a[pending] and not reentry_blocked(i):
                holding = True; ep = close_a[i]; ei = i; ef_wait = 0; pending = None
                continue
            pending = None
        if reentry_blocked(i):
            continue
        if _base_fire(r, vixarr[i], float(prem_a[i]), bool(rec_a[i]), strat):
            pending = i
    return trades


def run_universe(name, tickers, qstate, vix, eval_start):
    stocks = dr.load_universe(tickers, qstate, vix)
    span = ""
    if stocks:
        starts = [d.index[0] for d, *_ in stocks.values()]
        ends = [d.index[-1] for d, *_ in stocks.values()]
        span = f"{min(starts).date()}~{max(ends).date()}"
    print(f"\n{'='*150}\n[{name}]  종목 {len(stocks)}/{len(tickers)}개  ·  기간 {span}\n{'='*150}")

    rows = []
    base = {}
    for s in STRATS:
        for m in ALL_MODES:
            trades = []
            for t, (d, rws, va, pk) in stocks.items():
                if m == "익일종가반등":
                    trades += simulate_nextday(d, rws, va, pk, eval_start, s)
                else:
                    trades += dr.simulate_single(d, rws, va, pk, eval_start, s, m,
                                                 entry_fn=entry_sameday)
            mt = dr.metrics(trades)
            if m == "현행":
                base[s] = mt
            d_ev = dr._delta(base[s]["기대값"], mt["기대값"]) if base.get(s) else np.nan
            rows.append({"전략": f"{s} {LABEL[s]}", "모드": m,
                         "거래": mt["거래"], "승률": mt["승률"], "기대값": mt["기대값"],
                         "중앙": mt["중앙"], "합": mt["합"], "PF": mt["PF"],
                         "손절%": mt["손절"], "MDD": mt["MDD"], "평균일": mt["평균일"],
                         "Δ기대(vs현행)": d_ev})
    res = pd.DataFrame(rows)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40)
    print(res.to_string(index=False))
    res.insert(0, "유니버스", name)
    return res


def main():
    t0 = time.time()
    print("QQQ / VIX (최대 기간) 로딩…")
    qqq = dr.get("QQQ"); vixdf = dr.get("^VIX")
    qstate = bt.build_qqq_state(qqq).dropna(subset=["premium"])
    vix = vixdf["Close"].reindex(qstate.index, method="ffill")
    eval_start = qstate.index[0]
    print(f"기간 {qstate.index[0].date()}~{qstate.index[-1].date()} ({len(qstate)}일)")

    all_res = []
    for name, tickers in dr.UNIVERSES.items():
        if not tickers:
            continue
        all_res.append(run_universe(name, tickers, qstate, vix, eval_start))

    if all_res:
        big = pd.concat(all_res, ignore_index=True)
        out = os.path.join(dr.ROOT, "backtest_bb_bounce_confirm_summary.csv")
        big.to_csv(out, index=False)
        print(f"\n저장: {out}")
    print(f"\n총 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
