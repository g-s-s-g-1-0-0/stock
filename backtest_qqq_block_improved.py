"""
backtest_qqq_block_improved.py
==============================
목적
- 사용자 체감("QQQ 이격도 18% 넘어 매수가 차단되는데도 관심종목은 계속 오른다")을
  관심종목 표본으로 직접 검증한다.
- 회복장 공통 상단 차단선(현행 +18%)을 18/20/22/무제한으로 바꿔보고,
  추가로 '종목 모멘텀 예외(override)' 시나리오를 비교한다.

설계 원칙
- 전략/지표는 프로젝트 자체 코드를 그대로 재사용한다.
  - calculator/indicators.py : add_indicators (GAS와 동일 산식)
  - calculator/rules.py      : evaluate_buy_condition / evaluate_exit_condition
  - calculator/market_regime : QQQ 회복장/차단/고점청산 판정
- 시나리오마다 동일 지표를 쓰므로, 절대 수익률보다 '시나리오 간 상대 비교'가 핵심이다.

주의(편향)
- 관심종목은 2026년 시점에 잘 나간 종목 위주라 생존편향이 있다.
  → 절대 수치는 과대평가될 수 있으나, 차단선 변경에 따른 '상대' 효과 비교에는 영향이 적다.
"""

from __future__ import annotations

import os
import sys
import warnings
from datetime import date

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calculator.indicators import add_indicators
from calculator import market_regime as mr
from calculator import rules

START = "2019-06-01"   # 워밍업(200일+) 포함
END = "2026-05-30"
EVAL_START = pd.Timestamp("2020-06-01")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bt_cache")
os.makedirs(CACHE, exist_ok=True)

# 현재 관심종목 중 미국 티커 (QQQ 레짐과 직접 연동, yfinance 신뢰도 높음)
US_TICKERS = [
    "NVDA", "AVGO", "GOOGL", "AMD", "MU", "INTC", "TSLA",
    "CRDO", "AEHR", "ACLS", "ASX", "STX", "SNDK", "LITE", "LPTH",
    "RKLB", "ASTS", "PL", "IONQ", "IREN", "NBIS", "WULF", "CIFR",
    "BE", "ETN", "VST", "TE", "SGML", "MP", "SOXL",
]


def dl(ticker: str) -> pd.DataFrame | None:
    fp = os.path.join(CACHE, f"{ticker.replace('^','_')}.pkl")
    if os.path.exists(fp):
        try:
            df = pd.read_pickle(fp)
            if len(df) > 50:
                return df
        except Exception:
            pass
    try:
        df = yf.download(ticker, start=START, end=END, auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df.to_pickle(fp)
        return df
    except Exception as e:
        print(f"  ! {ticker} download fail: {e}")
        return None


def weekly_rsi(close: pd.Series) -> pd.Series:
    wk = close.resample("W-FRI").last().dropna()
    delta = wk.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    al = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).reindex(close.index, method="ffill")


def supplement(df: pd.DataFrame) -> pd.DataFrame:
    """rules.py가 요구하는 ma20 계열/closeD1/volRatio20 추가."""
    df = df.copy()
    c = df["Close"]
    df["MA20"] = c.rolling(20).mean()
    df["MA20_D1"] = df["MA20"].shift(1)
    df["MA20_PREV5"] = df["MA20"].shift(5)
    df["CLOSE_D1"] = c.shift(1)
    df["VolRatio20"] = df["Volume"] / df["Volume"].rolling(20).mean().replace(0, np.nan)
    return df


def build_qqq_state(qqq: pd.DataFrame) -> pd.DataFrame:
    """일자별 QQQ 레짐(회복장/프리미엄/고점청산/차단선) 테이블."""
    q = add_indicators(qqq)
    q["wrsi"] = weekly_rsi(qqq["Close"])
    closes = q["Close"].tolist()
    idx = q.index
    out = []
    for i in range(len(q)):
        if i < 200 or pd.isna(q["MA200"].iloc[i]):
            out.append(None)
            continue
        # 최근 60거래일 200일선 최저 이격도
        lo = max(0, i - 59)
        dists = []
        for j in range(lo, i + 1):
            ma = q["MA200"].iloc[j]
            if ma and ma > 0:
                dists.append((closes[j] / ma - 1) * 100)
        recent_min = min(dists) if dists else None
        row = {
            "close": q["Close"].iloc[i],
            "ma200": q["MA200"].iloc[i],
            "rsi": q["RSI"].iloc[i],
            "rsiD1": q["RSI_D1"].iloc[i],
            "macdHist": q["MACD_Hist"].iloc[i],
            "macdHistD1": q["MACD_Hist_D1"].iloc[i],
            "macdHistD2": q["MACD_Hist_D2"].iloc[i],
        }
        st = mr.build_qqq_market_state(row, recent_min_dist=recent_min, weekly_rsi=q["wrsi"].iloc[i])
        out.append(st)
    res = pd.DataFrame(index=idx)
    res["premium"] = [s["premiumPercent"] if s else np.nan for s in out]
    res["recovery"] = [s["isRecoveryMarket"] if s else False for s in out]
    res["peak"] = [s["peakTriggered"] if s else False for s in out]
    return res


def make_row(df: pd.DataFrame, i: int, entry_price=None) -> rules.IndicatorRow:
    g = df.iloc
    return rules.IndicatorRow(
        stock_name="x",
        current_price=float(g[i]["Close"]),
        ma200=_v(g[i]["MA200"]),
        rsi=_v(g[i]["RSI"]),
        cci=_v(g[i]["CCI"]),
        macd_hist=_v(g[i]["MACD_Hist"]),
        macd_hist_d1=_v(g[i]["MACD_Hist_D1"]),
        macd_hist_d2=_v(g[i]["MACD_Hist_D2"]),
        pct_b=_v(g[i]["PctB"]),
        pct_b_low=_v(g[i]["PctB_Low"]),
        ma20=_v(g[i]["MA20"]),
        ma20_d1=_v(g[i]["MA20_D1"]),
        ma20_prev5=_v(g[i]["MA20_PREV5"]),
        close_d1=_v(g[i]["CLOSE_D1"]),
        bb_width=_v(g[i]["BB_Width"]),
        bb_width_d1=_v(g[i]["BB_Width_D1"]),
        bb_width_avg60=_v(g[i]["BB_Width60"]),
        vol_ratio=_v(g[i]["VolRatio"]),
        vol_ratio20=_v(g[i]["VolRatio20"]),
        plus_di=_v(g[i]["PlusDI"]),
        minus_di=_v(g[i]["MinusDI"]),
        adx=_v(g[i]["ADX"]),
        adx_d1=_v(g[i]["ADX_D1"]),
        lr_slope=_v(g[i]["LR_Slope"]),
        lr_trendline=_v(g[i]["LR_Trendline"]),
        candle_low=_v(g[i]["Low"]),
        entry_price=entry_price,
    )


def _v(x):
    try:
        f = float(x)
        return f if f == f else None
    except Exception:
        return None


def simulate(df: pd.DataFrame, qstate: pd.DataFrame, vix: pd.Series,
             *, recovery_block: float, normal_block: float,
             momentum_override: bool, stock_cap: float = 0.60):
    """단일 종목 트레이드 시뮬레이션. 동시 1포지션."""
    df = df.join(qstate, how="inner")
    df = df.join(vix.rename("VIX"), how="left")
    df["VIX"] = df["VIX"].ffill()
    n = len(df)
    trades = []
    holding = False
    entry_price = entry_i = strat = None
    ef_wait = 0
    cooldown = 0

    for i in range(n):
        ts = df.index[i]
        if ts < EVAL_START:
            continue
        prem = _v(df["premium"].iloc[i])
        if prem is None:
            continue
        recovery = bool(df["recovery"].iloc[i])
        peak = bool(df["peak"].iloc[i])
        block_max = recovery_block if recovery else normal_block
        ixic_dist = prem  # 종목 진입 게이트에 QQQ 이격도를 그대로 사용

        if holding:
            row = make_row(df, i, entry_price=entry_price)
            tdays = i - entry_i
            peak_alert = peak  # B/D만 강제청산 대상 (rules에서 처리)
            res = rules.evaluate_exit_condition(
                row, strategy_type=strat, nasdaq_peak_alert=peak_alert,
                trading_days=tdays, upper_exit_wait_days=ef_wait if strat in ("E", "F") else None,
            )
            # E/F 목표수익 대기 카운터
            if strat in ("E", "F"):
                rp = (row.current_price - entry_price) / entry_price
                tgt = float(rules.STRATEGY_RULES[f"TARGET_PCT_{strat}"])
                ef_wait = ef_wait + 1 if rp >= tgt else 0
            if res["shouldExit"]:
                ret = (df["Close"].iloc[i] - entry_price) / entry_price
                trades.append({"strat": strat, "ret": ret, "days": tdays,
                               "exit": res["reason"], "entry_date": df.index[entry_i],
                               "entry_prem": _v(df["premium"].iloc[entry_i])})
                holding = False
                entry_price = entry_i = strat = None
                ef_wait = 0
                cooldown = 2
            continue

        if cooldown > 0:
            cooldown -= 1
            continue

        # 진입 평가 (시나리오 차단선)
        row = make_row(df, i)
        ev = rules.evaluate_buy_condition(
            row, _v(df["VIX"].iloc[i]), ixic_dist, False,
            nasdaq_buy_block_max=block_max, is_recovery_market=recovery,
        )
        allow = ev["entryTriggered"]
        chosen = ev["strategyType"]

        # 종목 모멘텀 예외: 차단 구간이라 막혔지만, 같은 신호가 무제한 차단선에서는
        # A/C/D로 잡히고, 종목 자체가 과열(>stock_cap)이 아니면 허용
        if momentum_override and not allow and prem is not None and prem > block_max:
            ev2 = rules.evaluate_buy_condition(
                row, _v(df["VIX"].iloc[i]), ixic_dist, False,
                nasdaq_buy_block_max=999.0, is_recovery_market=recovery,
            )
            if ev2["strategyType"] in ("A", "C", "D"):
                ma200 = row.ma200
                stock_dist = (row.current_price / ma200 - 1) if ma200 else 9
                rsi_ok = row.rsi is not None and row.rsi <= 82
                if stock_dist <= stock_cap and rsi_ok:
                    allow = True
                    chosen = ev2["strategyType"]

        if allow and chosen:
            holding = True
            entry_price = df["Close"].iloc[i]
            entry_i = i
            strat = chosen
            ef_wait = 0

    return trades


def summarize(name: str, trades: list[dict]):
    if not trades:
        return {"scenario": name, "trades": 0}
    rets = np.array([t["ret"] for t in trades])
    wins = rets > 0
    pf_num = rets[rets > 0].sum()
    pf_den = -rets[rets < 0].sum()
    blocked_zone = [t for t in trades if t["entry_prem"] is not None and t["entry_prem"] > 18.0]
    bz_rets = np.array([t["ret"] for t in blocked_zone]) if blocked_zone else np.array([])
    return {
        "scenario": name,
        "trades": len(trades),
        "win%": round(wins.mean() * 100, 1),
        "avg%": round(rets.mean() * 100, 2),
        "med%": round(np.median(rets) * 100, 2),
        "sum%": round(rets.sum() * 100, 1),
        "PF": round(pf_num / pf_den, 2) if pf_den > 0 else float("inf"),
        "avgDays": round(np.mean([t["days"] for t in trades]), 1),
        ">18%_n": len(blocked_zone),
        ">18%_win%": round((bz_rets > 0).mean() * 100, 1) if len(bz_rets) else None,
        ">18%_avg%": round(bz_rets.mean() * 100, 2) if len(bz_rets) else None,
    }


def main():
    print("데이터 다운로드 중...")
    qqq = dl("QQQ")
    vixdf = dl("^VIX")
    vix = vixdf["Close"]
    qstate = build_qqq_state(qqq)
    print(f"QQQ 레짐 테이블 {len(qstate)}일, 회복장 비중 "
          f"{qstate['recovery'].mean()*100:.0f}%, 차단(회복장>18%) 비중 "
          f"{((qstate['recovery'])&(qstate['premium']>18)).mean()*100:.1f}%")

    stocks = {}
    for t in US_TICKERS:
        df = dl(t)
        if df is None or len(df) < 260:
            print(f"  skip {t} (history 부족)")
            continue
        stocks[t] = supplement(add_indicators(df))
    print(f"백테스트 종목 {len(stocks)}개\n")

    scenarios = [
        ("기준(회복18/비회복9)", dict(recovery_block=18, normal_block=9, momentum_override=False)),
        ("회복20", dict(recovery_block=20, normal_block=9, momentum_override=False)),
        ("회복22", dict(recovery_block=22, normal_block=9, momentum_override=False)),
        ("회복 무제한", dict(recovery_block=999, normal_block=9, momentum_override=False)),
        ("회복18+모멘텀예외(캡60%)", dict(recovery_block=18, normal_block=9, momentum_override=True, stock_cap=0.60)),
        ("회복18+모멘텀예외(캡40%)", dict(recovery_block=18, normal_block=9, momentum_override=True, stock_cap=0.40)),
        ("회복22+비회복12", dict(recovery_block=22, normal_block=12, momentum_override=False)),
    ]

    rows = []
    all_trades_by_scn = {}
    for name, kw in scenarios:
        all_t = []
        for t, df in stocks.items():
            all_t += simulate(df, qstate, vix, **kw)
        all_trades_by_scn[name] = all_t
        rows.append(summarize(name, all_t))

    res = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    print("=" * 110)
    print("시나리오 비교 (관심종목 미국 티커, 회복장 차단선/모멘텀예외 변화)")
    print("=" * 110)
    print(res.to_string(index=False))
    res.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "backtest_qqq_block_improved_summary.csv"), index=False)

    # 차단존(>18%) 진입 트레이드만 그룹별로
    print("\n" + "=" * 110)
    print("회복장 차단존(QQQ>18%)에서만 진입한 트레이드 — '무제한' 시나리오 기준 그룹별")
    print("=" * 110)
    bz = [t for t in all_trades_by_scn["회복 무제한"]
          if t["entry_prem"] is not None and t["entry_prem"] > 18.0]
    if bz:
        from collections import defaultdict
        byg = defaultdict(list)
        for t in bz:
            byg[t["strat"]].append(t["ret"])
        for g in sorted(byg):
            r = np.array(byg[g])
            print(f"  {g}그룹: {len(r):3}건 | 승률 {(r>0).mean()*100:5.1f}% | 평균 {r.mean()*100:+6.2f}% | 중앙 {np.median(r)*100:+6.2f}%")
        allr = np.array([t["ret"] for t in bz])
        print(f"  -----\n  전체: {len(allr)}건 | 승률 {(allr>0).mean()*100:.1f}% | 평균 {allr.mean()*100:+.2f}% | 합 {allr.sum()*100:+.1f}%")
    else:
        print("  (표본 없음)")


if __name__ == "__main__":
    main()
