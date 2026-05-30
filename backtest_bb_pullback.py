"""
backtest_bb_pullback.py
=======================
BB 상단 눌림 반등 후보(현행 알림)를 '전략 H'로 가정하고, 청산조건까지 붙여
실제 매매 성과를 백테스트한다. 진입 신호는 알림 코드(bb_pullback_signal)와 동일
규칙을 그대로 재현하고, 청산은 기존 A~G 청산엔진과 동일한 구조의 프리셋으로 비교.

- 유니버스/기간: backtest_qqq_block_v2 와 동일(주요 종목 ~139, 2010~2026)
- 진입: 전일 종가 %B≥100, 전일 고가 %B 120~160, 당일 -3~0% 눌림, 아래꼬리 회복,
        RSI 65~85, CCI 100~250, 5일평균比 거래량 1~2배 (알림과 1:1 동일)
- 진입 모드: (a) 차단무시(현행 알림과 동일) / (b) 공통 상단차단 준수
- 청산 프리셋: G형 / D형 / A·C형 / EF형(목표후 MACD둔화) / 커스텀 단기모멘텀
"""
from __future__ import annotations
import os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_qqq_block_v2 as bt
from calculator.indicators import add_indicators
from calculator.sheet_sources import calc_rsi, calc_cci
from scripts.web_refresh_notifications import has_lower_wick_rebound

EVAL_START = bt.EVAL_START


def pctb_series(close: pd.Series, price: pd.Series) -> pd.Series:
    """pct_b_value(price, closes[window]) 를 일별 벡터화. 20창, 모표준편차(ddof=0)."""
    sma = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    upper = sma + 2 * std
    lower = sma - 2 * std
    width = (upper - lower).replace(0, np.nan)
    return (price - lower) / width * 100


def macd_hist(close: pd.Series) -> pd.Series:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def _ralign(values, index) -> pd.Series:
    """길이가 짧은 지표 리스트를 인덱스 뒤쪽에 맞춰 정렬(앞쪽은 NaN)."""
    vals = list(values)
    if len(vals) < len(index):
        vals = [np.nan] * (len(index) - len(vals)) + vals
    elif len(vals) > len(index):
        vals = vals[-len(index):]
    return pd.Series(vals, index=index)


def build_entries(df: pd.DataFrame) -> np.ndarray:
    """알림 규칙과 동일한 일별 진입 트리거 boolean 배열."""
    c = df["Close"]; h = df["High"]; v = df["Volume"]
    pctb_c = pctb_series(c, c)            # %B(종가)
    pctb_h = pctb_series(c, h)            # %B(고가) — 동일 종가창 사용(알림과 동일)
    closes = c.tolist()
    rsi = _ralign(calc_rsi(closes), df.index)
    rows_list = df.reset_index().rename(columns=str.lower).to_dict("records")
    cci = _ralign(calc_cci([{k: r[k] for k in ("open", "high", "low", "close")} for r in rows_list], period=14), df.index)
    vol5 = v / v.shift(1).rolling(5).mean()
    pullback = (c / c.shift(1) - 1) * 100
    wick = np.array([
        has_lower_wick_rebound({"open": o, "high": hi, "low": lo, "close": cl})[0]
        if not any(pd.isna(x) for x in (o, hi, lo, cl)) else False
        for o, hi, lo, cl in zip(df["Open"], df["High"], df["Low"], df["Close"])
    ])
    trig = (
        (pctb_c.shift(1) >= 100)
        & (pctb_h.shift(1).between(120, 160))
        & (pullback.between(-3, 0))
        & pd.Series(wick, index=df.index)
        & (rsi.between(65, 85))
        & (cci.between(100, 250))
        & (vol5.between(1.0, 2.0))
    )
    return trig.fillna(False).to_numpy()


EXITS = {
    # name: (target, stop, stalled_days, stalled_min, half_days(or None), max_hold, ef_style)
    "G형(+12/-10/정체15/최대40)":       (0.12, 0.10, 15, 0.08, None, 40, False),
    "D형(+12/-25/정체15/최대30)":       (0.12, 0.25, 15, 0.08, 60, 30, False),
    "A·C형(+20/-30/정체15/하프60/120)": (0.20, 0.30, 15, 0.08, 60, 120, False),
    "EF형(+20후 MACD둔화/대기5)":        (0.20, 0.30, 15, 0.08, 60, 120, True),
    "커스텀단기(+10/-7/정체10/최대20)":  (0.10, 0.07, 10, 0.03, None, 20, True),
}
UPPER_WAIT = 5


def simulate(df, entries, mh, prem_a, rec_a, *, respect_block, exitcfg):
    target, stop, st_days, st_min, half_days, max_hold, ef = exitcfg
    c = df["Close"].to_numpy(); dates = df.index
    n = len(df)
    holding = False; ep = ei = 0; ef_wait = 0; cooldown = 0
    trades = []
    for i in range(n):
        if dates[i] < EVAL_START:
            continue
        if np.isnan(prem_a[i]):
            continue
        if holding:
            rp = (c[i] - ep) / ep
            td = i - ei
            exit_reason = None
            if ef and rp >= target:
                turn = (mh[i] - mh[i-1]) < (mh[i-1] - mh[i-2]) if i >= 2 else False
                if turn:
                    exit_reason = "목표후MACD둔화"
                else:
                    ef_wait += 1
                    if ef_wait >= UPPER_WAIT:
                        exit_reason = "목표후대기만료"
            elif rp >= target:
                exit_reason = "목표달성"
            if exit_reason is None:
                if rp <= -stop:
                    exit_reason = "손절"
                elif td >= st_days and rp < st_min:
                    exit_reason = "반등미달"
                elif half_days is not None and td >= half_days and rp > 0:
                    exit_reason = "60일수익자동"
                elif td >= max_hold:
                    exit_reason = "최대보유초과"
            if exit_reason:
                trades.append({"ret": rp, "days": td, "reason": exit_reason, "exit_i": i})
                holding = False; ef_wait = 0; cooldown = 2
            continue
        if cooldown > 0:
            cooldown -= 1; continue
        if not entries[i]:
            continue
        if respect_block:
            block = 18 if bool(rec_a[i]) else 9
            if float(prem_a[i]) > block:
                continue
        holding = True; ep = c[i]; ei = i; ef_wait = 0
    return trades


def equity_mdd(trades):
    if not trades:
        return 0.0
    eq = peak = 1.0; mdd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_i"]):
        eq *= (1 + t["ret"] * 0.1); peak = max(peak, eq); mdd = min(mdd, eq/peak - 1)
    return mdd * 100


def summ(name, trades):
    if not trades:
        return {"시나리오": name, "거래": 0}
    r = np.array([t["ret"] for t in trades])
    pf_n = r[r > 0].sum(); pf_d = -r[r < 0].sum()
    return {
        "시나리오": name, "거래": len(trades), "승률%": round((r > 0).mean()*100, 1),
        "평균%": round(r.mean()*100, 2), "중앙%": round(np.median(r)*100, 2),
        "합%": round(r.sum()*100, 0), "PF": round(pf_n/pf_d, 2) if pf_d > 0 else 99,
        "손절%": round(sum(1 for t in trades if t["reason"] == "손절")/len(trades)*100, 1),
        "곡선MDD%": round(equity_mdd(trades), 1), "평균일": round(r.size and np.mean([t["days"] for t in trades]), 1),
    }


def main():
    qqq = bt.dl("QQQ")
    qstate = bt.build_qqq_state(qqq)
    print(f"유니버스 {len(bt.UNIVERSE)}종목 / {qstate.index[0].date()}~{qstate.index[-1].date()}")

    prepared = []
    for t in bt.UNIVERSE:
        df = bt.dl(t)
        if df is None or len(df) < 300:
            continue
        d = add_indicators(df).join(qstate, how="inner").dropna(subset=["premium"])
        if len(d) < 250:
            continue
        try:
            entries = build_entries(d)
        except Exception as e:
            print(f"  ! {t}: {e}"); continue
        mh = macd_hist(d["Close"]).to_numpy()
        prepared.append((d, entries, mh, d["premium"].to_numpy(), d["recovery"].to_numpy()))
    total_sig = sum(int(e.sum()) for _, e, _, _, _ in prepared)
    print(f"백테스트 종목 {len(prepared)}개 / 진입 트리거 총 {total_sig:,}회\n")

    out = []
    for mode_name, respect in [("차단무시(현행알림)", False), ("상단차단준수", True)]:
        for ex_name, cfg in EXITS.items():
            allt = []
            for d, entries, mh, prem_a, rec_a in prepared:
                allt += simulate(d, entries, mh, prem_a, rec_a, respect_block=respect, exitcfg=cfg)
            out.append(summ(f"[{mode_name}] {ex_name}", allt))

    res = pd.DataFrame(out)
    pd.set_option("display.width", 240); pd.set_option("display.max_columns", 30)
    print("=" * 150)
    print("BB 상단 눌림 = '전략 H' 가정 · 청산 프리셋별 성과 (2010~2026, 주요 종목)")
    print("=" * 150)
    print(res.to_string(index=False))
    res.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_bb_pullback_summary.csv"), index=False)


if __name__ == "__main__":
    main()
