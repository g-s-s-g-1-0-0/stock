"""전략 4 후보: 200일선 하방 + MACD 골든크로스.

진입 신호: 종가 < MA200 이면서 MACD선이 시그널선을 상향 돌파(MACD_Hist가 0 이하 → 0 초과).

검증 축:
1) QQQ 시장 국면(회복장/정상장/하락장/횡보장 고점)별 그리드
2) 국면 × 청산조건(목표/손절/최대보유) 그리드
3) 기존 A~H, 전략 1, 전략 2와의 신호 중복

데이터: backtest_qqq_block_v2.py와 동일한 .bt_cache 장기 일봉(2009~2026).
지표/국면 계산은 calculator/* 재사용, A~H 판정은 legacy_rules_ah.py(1b9bc899^ 스냅샷) 사용.
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calculator.indicators import add_indicators
from calculator import market_regime as mr
from calculator import rules as live_rules
import legacy_rules_ah as ah_rules
from backtest_qqq_block_v2 import UNIVERSE, weekly_rsi

OUT_DIR = os.path.join(ROOT, "analysis_tmp")
PANEL_PATH = os.path.join(OUT_DIR, "s4_panel.pkl")
# backtest_qqq_block_v2의 .bt_cache는 2009~2026-05로 고정돼 있어 닷컴/금융위기가
# 빠진다. 국면 표본을 늘리려고 QQQ 상장(1999-03) 이후 전 구간을 별도로 받는다.
CACHE = os.path.join(ROOT, ".bt_cache")
START = "1999-01-01"
END = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
FWD_HORIZONS = (5, 10, 20, 40, 60)
REGIME_ORDER = ["회복장", "정상장", "하락장", "횡보장 고점"]
FEE = 0.001


def dl(ticker: str) -> pd.DataFrame | None:
    fp = os.path.join(CACHE, f"s4_{ticker.replace('^', '_')}.pkl")
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
        print(f"  ! {ticker} 다운로드 실패: {e}")
        return None


def _v(x):
    try:
        f = float(x)
        return f if f == f else None
    except Exception:
        return None


def build_qqq_state() -> pd.DataFrame:
    qqq = dl("QQQ")
    q = add_indicators(qqq)
    q["wrsi"] = weekly_rsi(qqq["Close"])
    closes = q["Close"].to_numpy()
    ma200 = q["MA200"].to_numpy()
    prem, rec, peak = [], [], []
    for i in range(len(q)):
        if i < 200 or np.isnan(ma200[i]):
            prem.append(np.nan); rec.append(False); peak.append(False)
            continue
        lo = max(0, i - 59)
        dists = [(closes[j] / ma200[j] - 1) * 100 for j in range(lo, i + 1)
                 if ma200[j] and ma200[j] > 0]
        row = {"close": closes[i], "ma200": ma200[i],
               "rsi": q["RSI"].iloc[i], "rsiD1": q["RSI_D1"].iloc[i],
               "macdHist": q["MACD_Hist"].iloc[i],
               "macdHistD1": q["MACD_Hist_D1"].iloc[i],
               "macdHistD2": q["MACD_Hist_D2"].iloc[i]}
        st = mr.build_qqq_market_state(row, recent_min_dist=min(dists) if dists else None,
                                       weekly_rsi=q["wrsi"].iloc[i])
        prem.append(st["premiumPercent"]); rec.append(st["isRecoveryMarket"]); peak.append(st["peakTriggered"])
    state = pd.DataFrame({"premium": prem, "recovery": rec, "peak": peak}, index=q.index)
    state["regime"] = [mr.qqq_regime_label(p, r) for p, r in zip(state["premium"], state["recovery"])]
    return state.dropna(subset=["premium"])


def supplement(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    df["MA20"] = c.rolling(20).mean()
    df["MA60"] = c.rolling(60).mean()
    df["MA144"] = c.rolling(144).mean()
    df["MA20_D1"] = df["MA20"].shift(1)
    df["MA20_PREV5"] = df["MA20"].shift(5)
    df["CLOSE_D1"] = c.shift(1)
    df["VolRatio20"] = df["Volume"] / df["Volume"].rolling(20).mean().replace(0, np.nan)
    return df


def make_row(arr, i, kind):
    """kind='live'면 현행 rules, 'ah'면 레거시 rules의 IndicatorRow를 만든다."""
    common = dict(
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
        candle_open=_v(arr["Open"][i]), candle_low=_v(arr["Low"][i]),
    )
    if kind == "live":
        return live_rules.IndicatorRow(ma60=_v(arr["MA60"][i]), ma144=_v(arr["MA144"][i]), **common)
    return ah_rules.IndicatorRow(**common)


def build_panel() -> pd.DataFrame:
    qstate = build_qqq_state()
    vix = dl("^VIX")["Close"].reindex(qstate.index, method="ffill")
    print(f"QQQ 국면 산출: {qstate.index[0].date()} ~ {qstate.index[-1].date()}")
    print(qstate["regime"].value_counts().to_string())

    cols = ["Open", "High", "Low", "Close", "MA200", "MA20", "MA60", "MA144",
            "MA20_D1", "MA20_PREV5", "CLOSE_D1", "RSI", "CCI", "MACD_Hist",
            "MACD_Hist_D1", "MACD_Hist_D2", "PctB", "PctB_Low", "BB_Width",
            "BB_Width_D1", "BB_Width60", "VolRatio", "VolRatio20",
            "PlusDI", "MinusDI", "ADX", "ADX_D1", "LR_Slope", "LR_Trendline"]

    frames = []
    for n, t in enumerate(UNIVERSE, 1):
        raw = dl(t)
        if raw is None or len(raw) < 400:
            continue
        d = supplement(add_indicators(raw)).join(qstate, how="inner").dropna(subset=["premium"])
        if len(d) < 100:
            continue
        arr = {c: d[c].to_numpy(dtype=float) for c in cols}
        vixarr = vix.reindex(d.index, method="ffill").to_numpy(dtype=float)
        prem = d["premium"].to_numpy(dtype=float)
        recov = d["recovery"].to_numpy(dtype=bool)
        n_rows = len(d)

        ah_codes, live_codes = [], []
        for i in range(n_rows):
            if np.isnan(arr["MA200"][i]) or np.isnan(arr["Close"][i]):
                ah_codes.append(None); live_codes.append(None); continue
            block = mr.qqq_buy_block_max(bool(recov[i]))
            ah_codes.append(ah_rules.evaluate_buy_condition(
                make_row(arr, i, "ah"), vixarr[i], prem[i], False,
                nasdaq_buy_block_max=block, is_recovery_market=bool(recov[i])
            )["strategyType"])
            # 전략 2는 시즌 게이트가 상태값이라 백테스트에서는 항상 열림으로 두고
            # 최대 잠재 신호(완화판)를 본다. strategy123_compare.py와 동일한 취급.
            live_codes.append(live_rules.evaluate_buy_condition(
                make_row(arr, i, "live"), vixarr[i], prem[i], False,
                nasdaq_buy_block_max=block, is_recovery_market=bool(recov[i]),
                season_open=True
            )["strategyType"])

        op = arr["Open"]; cl = arr["Close"]
        entry = np.full(n_rows, np.nan)
        entry[:-1] = op[1:]
        out = pd.DataFrame({
            "ticker": t,
            "date": d.index,
            "regime": d["regime"].to_numpy(),
            "premium": prem,
            "close": cl,
            "ma200": arr["MA200"],
            "entryPrice": entry,
            "belowMA200": cl < arr["MA200"],
            "macdGolden": (arr["MACD_Hist_D1"] <= 0) & (arr["MACD_Hist"] > 0),
            "rsi": arr["RSI"],
            "ahCode": ah_codes,
            "liveCode": live_codes,
        })
        for h in FWD_HORIZONS:
            fut = np.full(n_rows, np.nan)
            fut[: n_rows - h] = cl[h:]
            out[f"fwd{h}"] = (fut / entry - 1) * 100
        frames.append(out)
        if n % 20 == 0:
            print(f"  ... {n}/{len(UNIVERSE)} 처리")

    panel = pd.concat(frames, ignore_index=True)
    panel["signal"] = panel["belowMA200"] & panel["macdGolden"]
    return panel


def fwd_table(panel: pd.DataFrame) -> pd.DataFrame:
    """국면 × 모집단별 선행수익 그리드."""
    pops = {
        "전략4 신호(MA200↓ & MACD골든)": panel["signal"],
        "비교군: MA200 아래 전체": panel["belowMA200"],
        "비교군: MACD골든 전체": panel["macdGolden"],
        "비교군: 전체 종목·전체일": pd.Series(True, index=panel.index),
    }
    rows = []
    for regime in REGIME_ORDER + ["전체"]:
        rmask = pd.Series(True, index=panel.index) if regime == "전체" else (panel["regime"] == regime)
        for name, pmask in pops.items():
            sub = panel[rmask & pmask]
            if sub.empty:
                continue
            rec = {"국면": regime, "모집단": name, "신호수": len(sub),
                   "종목수": sub["ticker"].nunique()}
            for h in FWD_HORIZONS:
                col = sub[f"fwd{h}"].dropna()
                rec[f"fwd{h}평균%"] = round(col.mean(), 2) if len(col) else np.nan
                rec[f"fwd{h}승률%"] = round((col > 0).mean() * 100, 1) if len(col) else np.nan
            rows.append(rec)
    return pd.DataFrame(rows)


def excess_table(panel: pd.DataFrame) -> pd.DataFrame:
    """같은 날 유니버스 평균 대비 초과수익.

    MACD 골든크로스가 실제로 기여하는지 보려면 'MA200 아래 종목들의 그날 평균'과
    비교해야 한다. 시장 전체가 오른 날 효과와 종목 약세 효과를 모두 제거한다.
    """
    p = panel.copy()
    for h in FWD_HORIZONS:
        col = f"fwd{h}"
        p[f"exAll{h}"] = p[col] - p.groupby("date")[col].transform("mean")
        below = p[col].where(p["belowMA200"])
        p[f"exBelow{h}"] = p[col] - below.groupby(p["date"]).transform("mean")
    rows = []
    for regime in REGIME_ORDER + ["전체"]:
        rmask = pd.Series(True, index=p.index) if regime == "전체" else (p["regime"] == regime)
        sub = p[rmask & p["signal"]]
        if sub.empty:
            continue
        rec = {"국면": regime, "신호수": len(sub)}
        for h in FWD_HORIZONS:
            rec[f"vs전체{h}"] = round(sub[f"exAll{h}"].mean(), 2)
            rec[f"vsMA200↓{h}"] = round(sub[f"exBelow{h}"].mean(), 2)
            rec[f"vsMA200↓{h}승률%"] = round((sub[f"exBelow{h}"] > 0).mean() * 100, 1)
        rows.append(rec)
    return pd.DataFrame(rows)


ERAS = [
    ("2000-2002 닷컴붕괴", "2000-01-01", "2002-12-31"),
    ("2003-2007 회복·확장", "2003-01-01", "2007-12-31"),
    ("2008-2009 금융위기", "2008-01-01", "2009-12-31"),
    ("2010-2019 장기강세", "2010-01-01", "2019-12-31"),
    ("2020 코로나", "2020-01-01", "2020-12-31"),
    ("2021-2026 최근", "2021-01-01", "2099-12-31"),
]


def era_table(panel: pd.DataFrame) -> pd.DataFrame:
    """구간별로 신호가 살아있는지 — 강세장 한 국면에만 기댄 결과인지 가른다."""
    rows = []
    for name, lo, hi in ERAS:
        m = (panel["date"] >= lo) & (panel["date"] <= hi)
        sub = panel[m & panel["signal"]]
        base = panel[m & panel["belowMA200"]]
        if sub.empty:
            continue
        rows.append({
            "구간": name, "신호": len(sub), "종목": sub["ticker"].nunique(),
            "fwd20평균%": round(sub["fwd20"].mean(), 2),
            "fwd20승률%": round((sub["fwd20"] > 0).mean() * 100, 1),
            "fwd60평균%": round(sub["fwd60"].mean(), 2),
            "MA200↓기저fwd20%": round(base["fwd20"].mean(), 2),
            "차이%p": round(sub["fwd20"].mean() - base["fwd20"].mean(), 2),
        })
    return pd.DataFrame(rows)


def simulate_trades(panel: pd.DataFrame, prices: dict, tp, sl, max_hold) -> pd.DataFrame:
    """신호별 독립 트레이드. 다음날 시가 진입, 조건 충족일 종가 청산."""
    trades = []
    sig = panel[panel["signal"] & panel["entryPrice"].notna()]
    for t, grp in sig.groupby("ticker"):
        px = prices[t]
        idx = px.index
        op = px["Open"].to_numpy(); cl = px["Close"].to_numpy()
        pos = {d: i for i, d in enumerate(idx)}
        for _, r in grp.iterrows():
            i0 = pos.get(r["date"])
            if i0 is None or i0 + 1 >= len(idx):
                continue
            ep = op[i0 + 1] * (1 + FEE)
            if not np.isfinite(ep) or ep <= 0:
                continue
            ret, days, reason = None, 0, "open_end"
            for j in range(i0 + 1, min(i0 + 1 + max_hold, len(idx))):
                days = j - i0
                cur = cl[j] * (1 - FEE) / ep - 1
                if cur >= tp:
                    ret, reason = cur, "target"; break
                if cur <= sl:
                    ret, reason = cur, "stop"; break
                if days >= max_hold:
                    ret, reason = cur, "time"; break
            if ret is None:
                ret = cl[min(i0 + max_hold, len(idx) - 1)] * (1 - FEE) / ep - 1
            trades.append({"ticker": t, "date": r["date"], "regime": r["regime"],
                           "ret": ret * 100, "days": days, "reason": reason})
    return pd.DataFrame(trades)


def summarize_trades(tr: pd.DataFrame, label: str) -> dict:
    if tr.empty:
        return {"구분": label, "거래": 0}
    r = tr["ret"].to_numpy()
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {"구분": label, "거래": len(tr), "승률%": round((r > 0).mean() * 100, 1),
            "평균%": round(r.mean(), 2), "중앙%": round(np.median(r), 2),
            "PF": round(gains / losses, 2) if losses > 0 else np.inf,
            "손절%": round((tr["reason"] == "stop").mean() * 100, 1),
            "목표%": round((tr["reason"] == "target").mean() * 100, 1),
            "평균일": round(tr["days"].mean(), 1)}


def overlap_report(panel: pd.DataFrame) -> None:
    sig = panel[panel["signal"]]
    keys4 = set(zip(sig["ticker"], sig["date"]))
    print(f"\n전략4 신호 총 {len(keys4):,}건 / {sig['ticker'].nunique()}종목")

    print("\n[같은 종목·같은 날 중복]")
    rows = []
    for code in list("ABCDEFGH"):
        other = panel[panel["ahCode"] == code]
        ko = set(zip(other["ticker"], other["date"]))
        inter = keys4 & ko
        rows.append({"상대전략": f"{code}. {ah_rules.STRATEGY_LABELS[code]}",
                     "상대신호": len(ko), "중복": len(inter),
                     "전략4대비%": round(len(inter) / len(keys4) * 100, 2) if keys4 else 0,
                     "상대대비%": round(len(inter) / len(ko) * 100, 2) if ko else 0})
    for code in ("1", "2"):
        other = panel[panel["liveCode"] == code]
        ko = set(zip(other["ticker"], other["date"]))
        inter = keys4 & ko
        note = " (시즌 항상열림 가정)" if code == "2" else ""
        rows.append({"상대전략": f"{code}. {live_rules.STRATEGY_LABELS[code]}{note}",
                     "상대신호": len(ko), "중복": len(inter),
                     "전략4대비%": round(len(inter) / len(keys4) * 100, 2) if keys4 else 0,
                     "상대대비%": round(len(inter) / len(ko) * 100, 2) if ko else 0})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n[±5거래일 이내 근접 중복 — 사실상 같은 자리에 들어가는지]")
    panel_sorted = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    panel_sorted["seq"] = panel_sorted.groupby("ticker").cumcount()
    seq4 = set(zip(panel_sorted.loc[panel_sorted["signal"], "ticker"],
                   panel_sorted.loc[panel_sorted["signal"], "seq"]))
    near_rows = []
    for label, mask in ([(f"{c}", panel_sorted["ahCode"] == c) for c in "ABCDEFGH"]
                        + [(f"전략{c}", panel_sorted["liveCode"] == c) for c in ("1", "2")]):
        other = panel_sorted[mask]
        seq_other = set(zip(other["ticker"], other["seq"]))
        hit_other = sum(1 for tk, sq in seq_other
                        if any((tk, sq + off) in seq4 for off in range(-5, 6)))
        hit_s4 = sum(1 for tk, sq in seq4
                     if any((tk, sq + off) in seq_other for off in range(-5, 6)))
        near_rows.append({"상대전략": label, "상대신호": len(other),
                          "상대→전략4근접": hit_other,
                          "상대대비%": round(hit_other / len(other) * 100, 2) if len(other) else 0,
                          "전략4→상대근접": hit_s4,
                          "전략4대비%": round(hit_s4 / len(seq4) * 100, 2) if seq4 else 0})
    print(pd.DataFrame(near_rows).to_string(index=False))

    print("\n[전략4 신호일에 다른 전략도 동시 발동한 비율]")
    both_ah = sig["ahCode"].notna().mean() * 100
    both_live = sig["liveCode"].notna().mean() * 100
    print(f"  A~H 중 하나라도 동시 발동: {both_ah:.2f}%")
    print(f"  전략1/2 중 하나라도 동시 발동: {both_live:.2f}%")
    if sig["ahCode"].notna().any():
        print("  동시 발동 A~H 내역:")
        print(sig["ahCode"].value_counts().to_string())
    if sig["liveCode"].notna().any():
        print("  동시 발동 전략1/2 내역:")
        print(sig["liveCode"].value_counts().to_string())


def main():
    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 40)
    os.makedirs(OUT_DIR, exist_ok=True)

    if os.path.exists(PANEL_PATH) and "--rebuild" not in sys.argv:
        panel = pd.read_pickle(PANEL_PATH)
        print(f"패널 캐시 로드: {PANEL_PATH} ({len(panel):,}행)")
    else:
        panel = build_panel()
        panel.to_pickle(PANEL_PATH)
        print(f"패널 저장: {PANEL_PATH} ({len(panel):,}행)")

    print(f"\n기간 {panel['date'].min().date()} ~ {panel['date'].max().date()} / "
          f"{panel['ticker'].nunique()}종목 / {len(panel):,} 종목·일")

    print("\n" + "=" * 150)
    print("1) 국면 × 모집단 선행수익 그리드 (신호 다음날 시가 진입, N거래일 뒤 종가)")
    print("=" * 150)
    ft = fwd_table(panel)
    print(ft.to_string(index=False))
    ft.to_csv(os.path.join(OUT_DIR, "s4_fwd_grid.csv"), index=False)

    print("\n" + "=" * 150)
    print("1-b) 같은 날 대비 초과수익 — MACD 골든크로스가 MA200 하방 위에 얹어주는 몫")
    print("=" * 150)
    et = excess_table(panel)
    print(et.to_string(index=False))
    et.to_csv(os.path.join(OUT_DIR, "s4_excess_grid.csv"), index=False)

    print("\n" + "=" * 150)
    print("1-c) 시장 구간별 — 특정 장세에만 통하는 신호인지")
    print("=" * 150)
    er = era_table(panel)
    print(er.to_string(index=False))
    er.to_csv(os.path.join(OUT_DIR, "s4_era_grid.csv"), index=False)

    print("\n" + "=" * 150)
    print("1-d) 최근 90일 발생 신호")
    print("=" * 150)
    cutoff = panel["date"].max() - pd.Timedelta(days=90)
    recent = panel[panel["signal"] & (panel["date"] >= cutoff)].sort_values("date")
    if recent.empty:
        print("  없음")
    else:
        show = recent[["date", "ticker", "regime", "premium", "close", "ma200"] +
                      [f"fwd{h}" for h in FWD_HORIZONS]].copy()
        show["date"] = show["date"].dt.date
        show["MA200이격%"] = ((show["close"] / show["ma200"] - 1) * 100).round(1)
        print(show.drop(columns=["ma200"]).round(2).to_string(index=False))
        print(f"\n  최근 90일 신호 {len(recent)}건 / {recent['ticker'].nunique()}종목 "
              f"(fwd 값이 NaN이면 아직 관측 기간이 안 지난 것)")
        recent.to_csv(os.path.join(OUT_DIR, "s4_recent_signals.csv"), index=False)

    prices = {t: dl(t) for t in panel["ticker"].unique()}

    print("\n" + "=" * 150)
    print("2) 국면 × 청산조건 그리드 (목표/손절/최대보유)")
    print("=" * 150)
    grid_rows = []
    for tp in (0.10, 0.15, 0.20):
        for sl in (-0.07, -0.10, -0.15):
            for hold in (20, 40, 60):
                tr = simulate_trades(panel, prices, tp, sl, hold)
                if tr.empty:
                    continue
                base = {"목표": f"+{tp:.0%}", "손절": f"{sl:.0%}", "보유": hold}
                overall = summarize_trades(tr, "전체")
                grid_rows.append({**base, "국면": "전체", **{k: v for k, v in overall.items() if k != "구분"}})
                for regime in REGIME_ORDER:
                    sub = tr[tr["regime"] == regime]
                    if sub.empty:
                        continue
                    s = summarize_trades(sub, regime)
                    grid_rows.append({**base, "국면": regime, **{k: v for k, v in s.items() if k != "구분"}})
    grid = pd.DataFrame(grid_rows)
    grid.to_csv(os.path.join(OUT_DIR, "s4_exit_grid.csv"), index=False)
    print("\n-- 전체 국면 요약 --")
    print(grid[grid["국면"] == "전체"].to_string(index=False))
    print("\n-- 국면별 (목표+20% / 손절-15% / 보유40일 기준) --")
    print(grid[(grid["목표"] == "+20%") & (grid["손절"] == "-15%") & (grid["보유"] == 40)].to_string(index=False))
    print("\n-- 국면별 최고 평균수익 조합 --")
    best = grid[grid["국면"] != "전체"].sort_values("평균%", ascending=False).groupby("국면").head(3)
    print(best.sort_values(["국면", "평균%"], ascending=[True, False]).to_string(index=False))

    print("\n" + "=" * 150)
    print("3) 기존 전략과의 신호 중복")
    print("=" * 150)
    overlap_report(panel)


if __name__ == "__main__":
    main()
