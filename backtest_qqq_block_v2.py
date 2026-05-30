"""
backtest_qqq_block_v2.py
========================
사용자 피드백 반영판:
- 관심종목 한정 X → 나스닥100 + S&P 메가캡 등 '주요 종목' 넓은 유니버스
- 기간 2010~2026 (약 16년)
- 회복장(18%) vs 비회복장(9%) 차단선을 각각 별도로 스윕
- 비회복장 완화 시 '휩소' 정량화: 손절률, 반등미달 청산률, 자본곡선 MDD, 연속손실
- 휩소 대응(청산/재진입 조정) 결합 시나리오 비교

전략/지표는 프로젝트 자체 코드(calculator/*) 재사용.
"""
from __future__ import annotations
import os, sys, warnings, dataclasses
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calculator.indicators import add_indicators
from calculator import market_regime as mr
from calculator import rules

START = "2009-01-01"
END = "2026-05-30"
EVAL_START = pd.Timestamp("2010-06-01")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bt_cache")
os.makedirs(CACHE, exist_ok=True)

# 나스닥100(2024 기준) + S&P 메가캡/대표 섹터주. '주요 종목' 일반화 목적.
NASDAQ100 = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","COST",
    "NFLX","ASML","AZN","TMUS","AMD","PEP","QCOM","INTU","CSCO","TXN",
    "ISRG","AMGN","AMAT","MU","BKNG","PANW","ADI","VRTX","GILD","REGN",
    "MELI","KDP","LRCX","SNPS","CDNS","CTAS","SBUX","KLAC","PYPL","MDLZ",
    "CHTR","CEG","NXPI","ORLY","WDAY","ABNB","MAR","TEAM","PCAR","CRWD",
    "ROST","ADSK","MCHP","CSX","DXCM","IDXX","ADP","FTNT","MNST","FAST",
    "PAYX","ODFL","EA","KHC","CTSH","BIIB","ZS","GEHC","VRSK","CSGP",
    "ON","DDOG","ROP","TTD","ANSS","CPRT","MRNA","XEL","DLTR","FANG",
    "CDW","EBAY","WBD","TTWO","GFS","MDB","SIRI","ILMN","ZM","RIVN",
    "LCID","SMCI","MRVL","INTC","PLTR","HOOD","ARM",
]
SP_MEGA = [
    "JPM","V","MA","UNH","HD","PG","JNJ","XOM","CVX","KO","BAC","WMT",
    "DIS","CRM","ABBV","MRK","LLY","ORCL","ACN","NKE","PFE","TMO","WFC",
    "MS","GS","CAT","BA","GE","HON","UPS","COP","T","VZ","IBM","NOW",
    "UBER","SHOP","SQ","COIN","PANW","NEE","DE","LMT","RTX",
]
UNIVERSE = sorted(set(NASDAQ100 + SP_MEGA))


def dl(ticker: str) -> pd.DataFrame | None:
    fp = os.path.join(CACHE, f"v2_{ticker.replace('^','_')}.pkl")
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
        print(f"  ! {ticker} fail: {e}")
        return None


def _v(x):
    try:
        f = float(x)
        return f if f == f else None
    except Exception:
        return None


def weekly_rsi(close):
    wk = close.resample("W-FRI").last().dropna()
    d = wk.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    al = l.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = ag/al.replace(0, np.nan)
    return (100-100/(1+rs)).reindex(close.index, method="ffill")


def supplement(df):
    df = df.copy(); c = df["Close"]
    df["MA20"] = c.rolling(20).mean()
    df["MA20_D1"] = df["MA20"].shift(1)
    df["MA20_PREV5"] = df["MA20"].shift(5)
    df["CLOSE_D1"] = c.shift(1)
    df["VolRatio20"] = df["Volume"]/df["Volume"].rolling(20).mean().replace(0, np.nan)
    return df


def build_qqq_state(qqq):
    q = add_indicators(qqq); q["wrsi"] = weekly_rsi(qqq["Close"])
    closes = q["Close"].tolist(); idx = q.index
    prem = []; rec = []; peak = []
    for i in range(len(q)):
        if i < 200 or pd.isna(q["MA200"].iloc[i]):
            prem.append(np.nan); rec.append(False); peak.append(False); continue
        lo = max(0, i-59); dists = []
        for j in range(lo, i+1):
            ma = q["MA200"].iloc[j]
            if ma and ma > 0:
                dists.append((closes[j]/ma-1)*100)
        rmin = min(dists) if dists else None
        row = {"close": q["Close"].iloc[i], "ma200": q["MA200"].iloc[i],
               "rsi": q["RSI"].iloc[i], "rsiD1": q["RSI_D1"].iloc[i],
               "macdHist": q["MACD_Hist"].iloc[i], "macdHistD1": q["MACD_Hist_D1"].iloc[i],
               "macdHistD2": q["MACD_Hist_D2"].iloc[i]}
        st = mr.build_qqq_market_state(row, recent_min_dist=rmin, weekly_rsi=q["wrsi"].iloc[i])
        prem.append(st["premiumPercent"]); rec.append(st["isRecoveryMarket"]); peak.append(st["peakTriggered"])
    res = pd.DataFrame(index=idx)
    res["premium"] = prem; res["recovery"] = rec; res["peak"] = peak
    return res


def prebuild_rows(df):
    rows = []
    g = df
    cols = ["Close","MA200","RSI","CCI","MACD_Hist","MACD_Hist_D1","MACD_Hist_D2",
            "PctB","PctB_Low","MA20","MA20_D1","MA20_PREV5","CLOSE_D1","BB_Width",
            "BB_Width_D1","BB_Width60","VolRatio","VolRatio20","PlusDI","MinusDI",
            "ADX","ADX_D1","LR_Slope","LR_Trendline","Low"]
    arr = {c: g[c].to_numpy() for c in cols}
    n = len(g)
    for i in range(n):
        if np.isnan(arr["MA200"][i]) or np.isnan(arr["Close"][i]):
            rows.append(None); continue
        rows.append(rules.IndicatorRow(
            stock_name="x", current_price=float(arr["Close"][i]),
            ma200=_v(arr["MA200"][i]), rsi=_v(arr["RSI"][i]), cci=_v(arr["CCI"][i]),
            macd_hist=_v(arr["MACD_Hist"][i]), macd_hist_d1=_v(arr["MACD_Hist_D1"][i]),
            macd_hist_d2=_v(arr["MACD_Hist_D2"][i]), pct_b=_v(arr["PctB"][i]),
            pct_b_low=_v(arr["PctB_Low"][i]), ma20=_v(arr["MA20"][i]),
            ma20_d1=_v(arr["MA20_D1"][i]), ma20_prev5=_v(arr["MA20_PREV5"][i]),
            close_d1=_v(arr["CLOSE_D1"][i]), bb_width=_v(arr["BB_Width"][i]),
            bb_width_d1=_v(arr["BB_Width_D1"][i]), bb_width_avg60=_v(arr["BB_Width60"][i]),
            vol_ratio=_v(arr["VolRatio"][i]), vol_ratio20=_v(arr["VolRatio20"][i]),
            plus_di=_v(arr["PlusDI"][i]), minus_di=_v(arr["MinusDI"][i]),
            adx=_v(arr["ADX"][i]), adx_d1=_v(arr["ADX_D1"][i]),
            lr_slope=_v(arr["LR_Slope"][i]), lr_trendline=_v(arr["LR_Trendline"][i]),
            candle_low=_v(arr["Low"][i]), entry_price=None))
    return rows


def simulate(df, rows, vixarr, *, recovery_block, normal_block,
             momentum_override=False, stock_cap=0.60,
             stalled_days=15, reentry_drop=0.03):
    n = len(df)
    prem_a = df["premium"].to_numpy(); rec_a = df["recovery"].to_numpy()
    peak_a = df["peak"].to_numpy(); close_a = df["Close"].to_numpy()
    dates = df.index
    trades = []
    holding = False; ep = ei = strat = None; ef_wait = 0; cooldown = 0
    last_exit_price = None; last_exit_i = -10**9
    # rules에 stalled_days를 주입(시나리오별)
    orig_stalled = rules.STRATEGY_RULES["STALLED_EXIT_DAYS"]
    rules.STRATEGY_RULES["STALLED_EXIT_DAYS"] = stalled_days
    try:
        for i in range(n):
            if dates[i] < EVAL_START:
                continue
            r = rows[i]
            if r is None or np.isnan(prem_a[i]):
                continue
            prem = float(prem_a[i]); recovery = bool(rec_a[i]); peak = bool(peak_a[i])
            block_max = recovery_block if recovery else normal_block
            if holding:
                row = dataclasses.replace(r, entry_price=ep)
                tdays = i - ei
                res = rules.evaluate_exit_condition(
                    row, strategy_type=strat, nasdaq_peak_alert=peak,
                    trading_days=tdays,
                    upper_exit_wait_days=ef_wait if strat in ("E","F") else None)
                if strat in ("E","F"):
                    rp = (row.current_price-ep)/ep
                    tgt = float(rules.STRATEGY_RULES[f"TARGET_PCT_{strat}"])
                    ef_wait = ef_wait+1 if rp >= tgt else 0
                if res["shouldExit"]:
                    ret = (close_a[i]-ep)/ep
                    reason = res["reason"] or ""
                    trades.append({"strat": strat, "ret": ret, "days": tdays,
                                   "reason": reason, "entry_prem": float(prem_a[ei]),
                                   "entry_rec": bool(rec_a[ei]), "exit_i": i})
                    holding = False; ep = ei = strat = None; ef_wait = 0; cooldown = 2
                    last_exit_price = close_a[i]; last_exit_i = i
                continue
            if cooldown > 0:
                cooldown -= 1; continue
            # 재진입 제한: 매도 10거래일 이내면 직전 매도가 대비 -reentry_drop 이상 하락 필요
            if last_exit_price is not None and (i-last_exit_i) <= rules.STRATEGY_RULES["REENTRY_DAYS"]:
                if close_a[i] > last_exit_price*(1-reentry_drop):
                    continue
            ev = rules.evaluate_buy_condition(
                r, vixarr[i], prem, False,
                nasdaq_buy_block_max=block_max, is_recovery_market=recovery)
            allow = ev["entryTriggered"]; chosen = ev["strategyType"]
            if momentum_override and not allow and prem > block_max:
                ev2 = rules.evaluate_buy_condition(
                    r, vixarr[i], prem, False,
                    nasdaq_buy_block_max=999.0, is_recovery_market=recovery)
                if ev2["strategyType"] in ("A","C","D"):
                    sd = (r.current_price/r.ma200-1) if r.ma200 else 9
                    if sd <= stock_cap and (r.rsi is not None and r.rsi <= 82):
                        allow = True; chosen = ev2["strategyType"]
            if allow and chosen:
                holding = True; ep = close_a[i]; ei = i; strat = chosen; ef_wait = 0
    finally:
        rules.STRATEGY_RULES["STALLED_EXIT_DAYS"] = orig_stalled
    return trades


def equity_mdd(trades):
    """체결 순서(청산 i) 기준 누적수익 곡선의 최대낙폭(근사, 균등배분 가정)."""
    if not trades:
        return 0.0
    ts = sorted(trades, key=lambda t: t["exit_i"])
    eq = 1.0; peak = 1.0; mdd = 0.0
    for t in ts:
        eq *= (1 + t["ret"]*0.1)  # 트레이드당 10% 배분 근사
        peak = max(peak, eq)
        mdd = min(mdd, eq/peak-1)
    return mdd*100


def summ(name, trades):
    if not trades:
        return {"시나리오": name, "거래": 0}
    r = np.array([t["ret"] for t in trades])
    stop = sum(1 for t in trades if "손절" in t["reason"])
    stalled = sum(1 for t in trades if "반등 미달" in t["reason"])
    pf_n = r[r>0].sum(); pf_d = -r[r<0].sum()
    # 최대 연속 손실
    streak = mx = 0
    for t in sorted(trades, key=lambda x: x["exit_i"]):
        if t["ret"] <= 0:
            streak += 1; mx = max(mx, streak)
        else:
            streak = 0
    return {"시나리오": name, "거래": len(trades), "승률%": round((r>0).mean()*100,1),
            "평균%": round(r.mean()*100,2), "합%": round(r.sum()*100,0),
            "PF": round(pf_n/pf_d,2) if pf_d>0 else 99,
            "손절%": round(stop/len(trades)*100,1),
            "반등미달%": round(stalled/len(trades)*100,1),
            "최대연속손실": mx, "곡선MDD%": round(equity_mdd(trades),1),
            "평균일": round(np.mean([t["days"] for t in trades]),1)}


def main():
    print("QQQ/VIX 다운로드...")
    qqq = dl("QQQ"); vixdf = dl("^VIX")
    qstate = build_qqq_state(qqq)
    vix = vixdf["Close"].reindex(qstate.index, method="ffill")
    recblock = ((qstate["recovery"]) & (qstate["premium"]>18)).mean()*100
    normblock = ((~qstate["recovery"]) & (qstate["premium"]>9)).mean()*100
    print(f"기간 {qstate.index[0].date()}~{qstate.index[-1].date()}, "
          f"회복장비중 {qstate['recovery'].mean()*100:.0f}% | "
          f"회복장&>18% {recblock:.1f}% | 비회복&>9% {normblock:.1f}%")

    print(f"유니버스 {len(UNIVERSE)}종목 다운로드/지표계산...")
    stocks = {}
    for t in UNIVERSE:
        df = dl(t)
        if df is None or len(df) < 300:
            continue
        d = supplement(add_indicators(df)).join(qstate, how="inner")
        d = d.dropna(subset=["premium"])
        if len(d) < 200:
            continue
        vixarr = vix.reindex(d.index, method="ffill").to_numpy()
        stocks[t] = (d, prebuild_rows(d), vixarr)
    print(f"백테스트 종목 {len(stocks)}개\n")

    scenarios = [
        ("AS-IS 기준(회복18/비회복9)", dict(recovery_block=18, normal_block=9)),
        ("비회복 9→12", dict(recovery_block=18, normal_block=12)),
        ("비회복 9→12 +반등미달15→10", dict(recovery_block=18, normal_block=12, stalled_days=10)),
        ("비회복 9→12 +반등미달15→10 +재진입-3→-5%", dict(recovery_block=18, normal_block=12, stalled_days=10, reentry_drop=0.05)),
        ("비회복 9→14", dict(recovery_block=18, normal_block=14)),
        ("회복 18→22", dict(recovery_block=22, normal_block=9)),
        ("모멘텀예외(회복18, 캡60%)", dict(recovery_block=18, normal_block=9, momentum_override=True, stock_cap=0.60)),
        ("종합(비회복12+반등10+재진입5%+모멘텀예외)", dict(recovery_block=18, normal_block=12, stalled_days=10, reentry_drop=0.05, momentum_override=True, stock_cap=0.60)),
    ]
    rows = []
    for name, kw in scenarios:
        allt = []
        for t,(d,rws,va) in stocks.items():
            allt += simulate(d, rws, va, **kw)
        rows.append(summ(name, allt))
    res = pd.DataFrame(rows)
    pd.set_option("display.width", 240); pd.set_option("display.max_columns", 30)
    print("="*140)
    print("시나리오 비교 — 주요 종목 넓은 유니버스 / 2010~2026")
    print("="*140)
    print(res.to_string(index=False))
    res.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
               "backtest_qqq_block_v2_summary.csv"), index=False)


if __name__ == "__main__":
    main()
