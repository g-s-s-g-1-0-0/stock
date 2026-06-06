"""
backtest_disparity_removal.py
=============================
질문: "전략별로 이격도(QQQ/종목) 매수 제한을 없애는 게 의미가 있는 전략이 있는가?"

방식
- 전략 A~G 각각을 '단일 전략 모드'로 격리해(우선순위 충돌 제거) 진입/청산을 시뮬레이션한다.
- 같은 진입 신호에 대해 두 모드를 비교한다.
    · 제한 ON  : 현행 그대로 (QQQ 이격도 게이트 포함)
    · 제한 OFF : 해당 전략의 이격도 매수 제한만 제거
- '이격도 매수 제한'의 정의(전략별):
    · A/C/D : nasdaq_acd_gate = 상단 과열 차단(회복18/비회복9) + 하한 -3% 게이트
    · B     : 상단 과열 차단(하단차단 nasdaq_below_buy_block)
    · E/F   : 상단 과열 차단(nasdaq_bottom)
    · G     : 종목 MA200 이격 ≤ +80% 캡(g_cond10) + QQQ 상단 과열 차단
              (단, G의 +8~+18% 회복장 윈도우는 전략 정의이므로 유지)
- 청산 엔진/지표/규칙은 프로젝트 코드(calculator/*, rules)를 그대로 재사용.

유니버스(볼 수 있는 종목 최대치) / 기간(볼 수 있는 최대치 = yfinance period=max).
"""
from __future__ import annotations
import os, sys, time, json, warnings, dataclasses
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calculator.indicators import add_indicators
from calculator import rules
import backtest_qqq_block_v2 as bt  # build_qqq_state, supplement, prebuild_rows, weekly_rsi, equity_mdd

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, ".bt_cache")
os.makedirs(CACHE, exist_ok=True)

STRATS = ["A", "B", "C", "D", "E", "F", "G"]
EF = {"E", "F"}
LABEL = {"A": "모멘텀재가속", "B": "공황저점", "C": "스퀴즈돌파", "D": "추세강화",
         "E": "스퀴즈저점", "F": "BB극단저점", "G": "회복장20일선눌림"}

# ── 유니버스 정의 ────────────────────────────────────────────────────────────
# 관심종목(미국) : data/cache/stocks.json market==US (HOOG=HOOD 오타 보정)
def _watchlist_us():
    try:
        d = json.load(open(os.path.join(ROOT, "data/cache/stocks.json")))
        us = [r["ticker"] for r in d["rows"] if r.get("market") == "US"]
        fix = {"HOOG": "HOOD"}
        return sorted({fix.get(t, t) for t in us})
    except Exception:
        return []

DOW30 = ["AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
         "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
         "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT"]

UNIVERSES = {
    "관심종목(US)": _watchlist_us(),
    "나스닥100": bt.NASDAQ100,
    "다우30": DOW30,
}


# ── 데이터 로딩 (최대 기간) ──────────────────────────────────────────────────
def get(ticker: str) -> pd.DataFrame | None:
    fp = os.path.join(CACHE, f"dr_{ticker.replace('^', '_')}.pkl")
    if os.path.exists(fp):
        try:
            df = pd.read_pickle(fp)
            if len(df) > 50:
                return df
        except Exception:
            pass
    try:
        df = yf.download(ticker, period="max", auto_adjust=True, progress=False)
        if df is None or df.empty:
            raise ValueError("empty")
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df.to_pickle(fp)
        return df
    except Exception:
        # fallback: 기존 캐시(2009~)
        for alt in (f"v2_{ticker.replace('^','_')}.pkl", f"{ticker.replace('^','_')}.pkl"):
            ap = os.path.join(CACHE, alt)
            if os.path.exists(ap):
                try:
                    return pd.read_pickle(ap)
                except Exception:
                    pass
    return None


# ── 진입 신호: 전략 격리 + 이격도 제한 ON/OFF ───────────────────────────────
def entry_signal(r, vix, prem, recovery, strat, mode) -> bool:
    block_max = 18.0 if recovery else 9.0
    ev = rules.evaluate_buy_condition(
        r, vix, prem, False, nasdaq_buy_block_max=block_max, is_recovery_market=recovery)
    cond = ev["conditions"][strat]
    if mode == "ON":
        return all(cond)
    # OFF: 이격도 매수 제한 제거
    if strat in ("A", "B", "C", "D", "E", "F"):
        return all(cond[:-1])  # 마지막 원소 = QQQ 이격도 게이트
    # G: 상단 과열 차단 제거(block_max=999) + 종목 MA200 이격 캡(g_cond10) 제거
    ev2 = rules.evaluate_buy_condition(
        r, vix, prem, False, nasdaq_buy_block_max=999.0, is_recovery_market=recovery)
    cg = ev2["conditions"]["G"]
    return all(cg[:9])  # g_cond1..g_cond9 (g_cond10 = MA200 이격 ≤+80% 제거)


def simulate_single(d, rows, vixarr, peak_a, eval_start, strat, mode, entry_fn=None):
    close_a = d["Close"].to_numpy()
    prem_a = d["premium"].to_numpy(); rec_a = d["recovery"].to_numpy()
    dates = d.index
    fire = entry_fn or entry_signal
    trades = []
    holding = False; ep = ei = 0; ef_wait = 0; cooldown = 0
    last_exit_price = None; last_exit_i = -10**9
    reentry_days = int(rules.STRATEGY_RULES["REENTRY_DAYS"])
    for i in range(len(d)):
        if dates[i] < eval_start:
            continue
        r = rows[i]
        if r is None or np.isnan(prem_a[i]):
            continue
        prem = float(prem_a[i]); recovery = bool(rec_a[i])
        if holding:
            row = dataclasses.replace(r, entry_price=ep)
            tdays = i - ei
            res = rules.evaluate_exit_condition(
                row, strategy_type=strat, nasdaq_peak_alert=bool(peak_a[i]),
                trading_days=tdays,
                upper_exit_wait_days=ef_wait if strat in EF else None)
            if strat in EF:
                rp = (row.current_price - ep) / ep
                tgt = float(rules.STRATEGY_RULES[f"TARGET_PCT_{strat}"])
                ef_wait = ef_wait + 1 if rp >= tgt else 0
            if res["shouldExit"]:
                trades.append({"strat": strat, "ret": (close_a[i] - ep) / ep,
                               "days": tdays, "reason": res["reason"] or "", "exit_i": i})
                holding = False; ep = ei = 0; ef_wait = 0; cooldown = 2
                last_exit_price = close_a[i]; last_exit_i = i
            continue
        if cooldown > 0:
            cooldown -= 1; continue
        if last_exit_price is not None and (i - last_exit_i) <= reentry_days:
            if close_a[i] > last_exit_price * (1 - 0.03):
                continue
        if fire(r, vixarr[i], prem, recovery, strat, mode):
            holding = True; ep = close_a[i]; ei = i; ef_wait = 0
    return trades


def metrics(trades):
    if not trades:
        return dict(거래=0, 승률=np.nan, 기대값=np.nan, 중앙=np.nan,
                    합=np.nan, PF=np.nan, 손절=np.nan, MDD=np.nan, 평균일=np.nan)
    r = np.array([t["ret"] for t in trades])
    pf_n = r[r > 0].sum(); pf_d = -r[r < 0].sum()
    stop = sum(1 for t in trades if "손절" in t["reason"])
    return dict(
        거래=len(trades),
        승률=round((r > 0).mean() * 100, 1),
        기대값=round(r.mean() * 100, 2),
        중앙=round(np.median(r) * 100, 2),
        합=round(r.sum() * 100, 0),
        PF=round(pf_n / pf_d, 2) if pf_d > 0 else 99.0,
        손절=round(stop / len(trades) * 100, 1),
        MDD=round(bt.equity_mdd(trades), 1),
        평균일=round(r.size and np.mean([t["days"] for t in trades]), 1),
    )


def load_universe(tickers, qstate, vix):
    stocks = {}
    for t in tickers:
        df = get(t)
        if df is None or len(df) < 300:
            continue
        d = bt.supplement(add_indicators(df)).join(qstate, how="inner").dropna(subset=["premium"])
        if len(d) < 200:
            continue
        rows = bt.prebuild_rows(d)
        vixarr = vix.reindex(d.index, method="ffill").to_numpy()
        peak_a = d["peak"].to_numpy()
        stocks[t] = (d, rows, vixarr, peak_a)
    return stocks


def run_universe(name, tickers, qstate, vix, eval_start):
    stocks = load_universe(tickers, qstate, vix)
    span = ""
    if stocks:
        starts = [d.index[0] for d, *_ in stocks.values()]
        ends = [d.index[-1] for d, *_ in stocks.values()]
        span = f"{min(starts).date()}~{max(ends).date()}"
    print(f"\n{'='*150}\n[{name}]  종목 {len(stocks)}/{len(tickers)}개  ·  기간 {span}\n{'='*150}")

    rows_out = []
    for s in STRATS:
        on, off = [], []
        for t, (d, rws, va, pk) in stocks.items():
            on += simulate_single(d, rws, va, pk, eval_start, s, "ON")
            off += simulate_single(d, rws, va, pk, eval_start, s, "OFF")
        mon, moff = metrics(on), metrics(off)
        verdict = judge(mon, moff)
        rows_out.append({
            "전략": f"{s} {LABEL[s]}",
            "거래ON": mon["거래"], "거래OFF": moff["거래"],
            "승률ON": mon["승률"], "승률OFF": moff["승률"],
            "기대ON": mon["기대값"], "기대OFF": moff["기대값"],
            "PF_ON": mon["PF"], "PF_OFF": moff["PF"],
            "MDD_ON": mon["MDD"], "MDD_OFF": moff["MDD"],
            "Δ기대": _delta(mon["기대값"], moff["기대값"]),
            "Δ거래": (moff["거래"] - mon["거래"]) if mon["거래"] or moff["거래"] else 0,
            "판정": verdict,
        })
    res = pd.DataFrame(rows_out)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40)
    print(res.to_string(index=False))
    res.insert(0, "유니버스", name)
    return res


def _delta(a, b):
    if a != a or b != b:
        return np.nan
    return round(b - a, 2)


def judge(mon, moff):
    """제한 OFF가 의미 있는지 간단 판정."""
    if moff["거래"] == 0 and mon["거래"] == 0:
        return "신호없음"
    if moff["거래"] == mon["거래"]:
        return "영향없음"  # 제한이 binding 아님
    # 추가된 거래가 있을 때, OFF의 기대값/PF가 ON 대비 어떤지
    de = _delta(mon["기대값"], moff["기대값"])
    if mon["거래"] == 0:
        # ON은 진입 자체가 거의 없던 전략 → OFF로 거래가 생김
        return "신규개방" if (moff["기대값"] == moff["기대값"] and moff["기대값"] > 0) else "개방-부진"
    if de is None or de != de:
        return "?"
    pf_ok = (moff["PF"] >= mon["PF"] - 0.05)
    if de >= 0.3 and pf_ok:
        return "★완화유리"
    if de >= 0 and pf_ok:
        return "△소폭개선"
    if de <= -0.5 or moff["PF"] < mon["PF"] - 0.3:
        return "✗완화불리"
    return "≈중립"


def main():
    t0 = time.time()
    print("QQQ / VIX (최대 기간) 로딩…")
    qqq = get("QQQ"); vixdf = get("^VIX")
    qstate = bt.build_qqq_state(qqq)
    qstate = qstate.dropna(subset=["premium"])
    vix = vixdf["Close"].reindex(qstate.index, method="ffill")
    eval_start = qstate.index[0]
    rec_share = qstate["recovery"].mean() * 100
    print(f"QQQ 상태 기간 {qstate.index[0].date()}~{qstate.index[-1].date()} "
          f"({len(qstate)}일), 회복장비중 {rec_share:.0f}%, EVAL_START={eval_start.date()}")

    all_res = []
    for name, tickers in UNIVERSES.items():
        if not tickers:
            continue
        all_res.append(run_universe(name, tickers, qstate, vix, eval_start))

    if all_res:
        big = pd.concat(all_res, ignore_index=True)
        out = os.path.join(ROOT, "backtest_disparity_removal_summary.csv")
        big.to_csv(out, index=False)
        print(f"\n저장: {out}")
    print(f"\n총 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
