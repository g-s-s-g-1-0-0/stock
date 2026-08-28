"""2026-07-29에 화면에서 볼 수 있었던 값만으로 규칙을 만들고 27년 백테스트.

그날 네 종목의 공통점은 MACD가 아니라 '항복성 급락 + 과매도 + 깊은 낙폭'이었고,
시장 쪽에서는 QQQ RSI 32 · VIX 20.66 급등 · 60일 고점 -40% 종목 비율 6.6%였다.

여기서는 그날 종가에 확정된 값만 쓴다(미래 정보 없음). 진입은 다음날 시가.
각 규칙이 2026-07-29에 실제로 발동했는지 먼저 확인하고, 같은 규칙을
1999년 이후 전 구간에 적용한다.
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calculator.indicators import add_indicators
from ma200_macd_golden import FEE, OUT_DIR, dl
from backtest_qqq_block_v2 import UNIVERSE

BOTTOM = pd.Timestamp("2026-07-29")
CHECK = ["COHR", "TE", "RKLB", "IONQ"]
HORIZONS = [1, 3, 5, 10, 20]


def market_frame() -> pd.DataFrame:
    q = add_indicators(dl("QQQ")).dropna(subset=["MA200", "RSI"])
    m = pd.DataFrame({
        "qqqRSI": q["RSI"],
        "qqqDD60": (q["Close"] / q["Close"].rolling(60).max() - 1) * 100,
        "qqqRet1": q["Close"].pct_change() * 100,
    })
    vix = dl("^VIX")
    if vix is not None:
        v = vix["Close"]
        m["vix"] = v
        m["vixVsMA20"] = v / v.rolling(20).mean()
    return m.dropna()


def build(mkt: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    frames, prices = [], {}
    for t in UNIVERSE:
        raw = dl(t)
        if raw is None or len(raw) < 400:
            continue
        d = add_indicators(raw).dropna(subset=["MA200", "RSI", "CCI", "MACD_Hist",
                                               "MACD_Hist_D1"])
        d = d.join(mkt, how="inner").dropna(subset=["qqqRSI"])
        if len(d) < 300:
            continue
        prices[t] = d
        cl = d["Close"].to_numpy()
        n = len(d)
        entry = np.full(n, np.nan)
        entry[:-1] = d["Open"].to_numpy()[1:]
        h0 = d["MACD_Hist"].to_numpy()
        h1 = d["MACD_Hist_D1"].to_numpy()
        out = pd.DataFrame({
            "ticker": t, "date": d.index, "entry": entry,
            "ret1": d["Close"].pct_change().to_numpy() * 100,
            "ret5": d["Close"].pct_change(5).to_numpy() * 100,
            "RSI": d["RSI"].to_numpy(), "CCI": d["CCI"].to_numpy(),
            "PctB": d["PctB"].to_numpy(),
            "dd60": (cl / d["Close"].rolling(60).max().to_numpy() - 1) * 100,
            "dd252": (cl / d["Close"].rolling(252).max().to_numpy() - 1) * 100,
            "volRatio": (d["Volume"] / d["Volume"].rolling(20).mean()).to_numpy(),
            "distMA200": (cl / d["MA200"].to_numpy() - 1) * 100,
            "golden": (h1 <= 0) & (h0 > 0),
            "below200": cl < d["MA200"].to_numpy(),
            "qqqRSI": d["qqqRSI"].to_numpy(),
            "vixVsMA20": d["vixVsMA20"].to_numpy() if "vixVsMA20" in d else np.nan,
        })
        for h in HORIZONS:
            fut = np.full(n, np.nan)
            fut[: n - h] = cl[h:]
            out[f"fwd{h}"] = (fut / entry - 1) * 100
        frames.append(out)
    p = pd.concat(frames, ignore_index=True)
    for h in HORIZONS:
        p[f"ex{h}"] = p[f"fwd{h}"] - p.groupby("date")[f"fwd{h}"].transform("mean")
    return p, prices


RULES = {
    "R1 항복일 (하루 -5%↓ & RSI<30)":
        lambda p: (p["ret1"] < -5) & (p["RSI"] < 30),
    "R2 과매도+깊은낙폭 (RSI<30 & 60일고점-45%↓)":
        lambda p: (p["RSI"] < 30) & (p["dd60"] < -45),
    "R3 CCI극단+낙폭 (CCI<-150 & 60일고점-40%↓)":
        lambda p: (p["CCI"] < -150) & (p["dd60"] < -40),
    "R4 밴드이탈+낙폭 (%B<5 & 60일고점-40%↓)":
        lambda p: (p["PctB"] < 5) & (p["dd60"] < -40),
    "R5 R2 + 시장과매도 (QQQ RSI<40)":
        lambda p: (p["RSI"] < 30) & (p["dd60"] < -45) & (p["qqqRSI"] < 40),
    "R6 R2 + VIX급등 (VIX>20일평균×1.15)":
        lambda p: (p["RSI"] < 30) & (p["dd60"] < -45) & (p["vixVsMA20"] > 1.15),
    "R7 항복+낙폭+거래량 (하루-5%↓ & 60일-45%↓ & 거래량1.2배↑)":
        lambda p: (p["ret1"] < -5) & (p["dd60"] < -45) & (p["volRatio"] > 1.2),
    "[비교] MACD 골든크로스 & MA200 아래":
        lambda p: p["below200"] & p["golden"],
    "[비교] 후보 β (52주-50%↓ & RSI<25)":
        lambda p: (p["dd252"] < -50) & (p["RSI"] < 25),
}


def fired_on_bottom(mkt: pd.DataFrame) -> pd.DataFrame:
    """규칙이 2026-07-29에 네 종목에서 실제로 발동했는지."""
    rows = []
    for t in CHECK:
        d = add_indicators(dl(t)).join(mkt, how="inner")
        if BOTTOM not in d.index:
            continue
        cl = d["Close"]
        row = pd.DataFrame({
            "ret1": cl.pct_change() * 100, "ret5": cl.pct_change(5) * 100,
            "RSI": d["RSI"], "CCI": d["CCI"], "PctB": d["PctB"],
            "dd60": (cl / cl.rolling(60).max() - 1) * 100,
            "dd252": (cl / cl.rolling(252).max() - 1) * 100,
            "volRatio": d["Volume"] / d["Volume"].rolling(20).mean(),
            "distMA200": (cl / d["MA200"] - 1) * 100,
            "below200": cl < d["MA200"],
            "golden": (d["MACD_Hist_D1"] <= 0) & (d["MACD_Hist"] > 0),
            "qqqRSI": d["qqqRSI"], "vixVsMA20": d["vixVsMA20"],
        }).loc[[BOTTOM]]
        rec = {"종목": t}
        for k, (name, fn) in enumerate(RULES.items()):
            tag = name.split(" ")[0]
            rec[f"{tag}{k}" if tag == "[비교]" else tag] = (
                "O" if bool(fn(row).iloc[0]) else "-")
        # 실제 결과
        i = d.index.get_loc(BOTTOM)
        for h in (1, 3, 5):
            rec[f"이후{h}일%"] = round((cl.iloc[i + h] / cl.iloc[i] - 1) * 100, 1)
        rec["현재까지%"] = round((cl.iloc[-1] / cl.iloc[i] - 1) * 100, 1)
        rows.append(rec)
    return pd.DataFrame(rows)


def evaluate(p: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    rows = []
    for name, fn in RULES.items():
        m = fn(p).fillna(False)
        s = p[m]
        if len(s) < 100:
            rows.append({"규칙": name, "신호수": int(m.sum()), "비고": "표본부족"})
            continue
        rec = {"규칙": name, "신호수": len(s), "종목": s["ticker"].nunique(),
               "연평균": round(len(s) / 27, 0)}
        for h in (1, 3, 5, 10, 20):
            rec[f"{h}일%"] = round(s[f"fwd{h}"].mean(), 2)
        rec["5일승률%"] = round((s["fwd5"] > 0).mean() * 100, 1)
        rec["20일승률%"] = round((s["fwd20"] > 0).mean() * 100, 1)
        rec["초과5%p"] = round(s["ex5"].mean(), 2)
        rec["초과20%p"] = round(s["ex20"].mean(), 2)
        e = s[["date", "ex20"]].dropna()
        daily = e.groupby("date")["ex20"].mean().to_numpy()
        if len(daily) > 30:
            boot = np.array([rng.choice(daily, len(daily), replace=True).mean()
                             for _ in range(3000)])
            lo, hi = np.percentile(boot, [2.5, 97.5])
            rec["초과20 CI"] = f"{lo:+.2f}~{hi:+.2f}"
            rec["유의"] = "O" if lo > 0 else ("역" if hi < 0 else "-")
        rows.append(rec)
    return pd.DataFrame(rows)


def barrier(p: pd.DataFrame, prices: dict, fn, tp: float, sl: float,
            maxhold: int) -> dict:
    m = fn(p).fillna(False)
    res = []
    for t, grp in p[m].groupby("ticker"):
        px = prices.get(t)
        if px is None:
            continue
        pos = {d: i for i, d in enumerate(px.index)}
        op, hi, lo, cl = (px["Open"].to_numpy(), px["High"].to_numpy(),
                          px["Low"].to_numpy(), px["Close"].to_numpy())
        for d in grp["date"]:
            i = pos.get(d)
            if i is None or i + 1 >= len(cl):
                continue
            ep = op[i + 1] * (1 + FEE)
            if not np.isfinite(ep) or ep <= 0:
                continue
            end = min(i + 1 + maxhold, len(cl))
            sh, sl_ = hi[i + 1:end], lo[i + 1:end]
            if len(sh) == 0:
                continue
            ht = sh >= ep * (1 + tp)
            hs = sl_ <= ep * (1 - sl)
            k_tp = int(np.argmax(ht)) if ht.any() else -1
            k_sl = int(np.argmax(hs)) if hs.any() else -1
            if k_sl >= 0 and (k_tp < 0 or k_sl <= k_tp):
                k, r = k_sl, -sl
            elif k_tp >= 0:
                k, r = k_tp, tp
            else:
                k = len(sh) - 1
                r = cl[i + 1 + k] / ep - 1
            res.append(((r - FEE) * 100, k + 1))
    if not res:
        return {}
    r = np.array([x[0] for x in res])
    dd = np.array([x[1] for x in res])
    return {"거래": len(r), "승률%": round((r > 0).mean() * 100, 1),
            "평균%": round(r.mean(), 2), "평균일": round(dd.mean(), 1),
            "연환산%": round(r.mean() / dd.mean() * 252, 1)}


def main():
    pd.set_option("display.width", 400)
    pd.set_option("display.max_columns", 50)
    mkt = market_frame()

    print("=" * 150)
    print("1차 확인 — 각 규칙이 2026-07-29에 실제로 발동했는가")
    print("=" * 150)
    print(fired_on_bottom(mkt).to_string(index=False))

    p, prices = build(mkt)
    print(f"\n패널 {p['date'].min().date()} ~ {p['date'].max().date()} / "
          f"{p['ticker'].nunique()}종목 / {len(p):,} 종목·일")

    print("\n" + "=" * 150)
    print("2차 — 같은 규칙을 27년 전체에 적용 (진입 다음날 시가, 초과는 같은 날 전체 평균 대비)")
    print("=" * 150)
    t = evaluate(p)
    t.to_csv(os.path.join(OUT_DIR, "washout_rules.csv"), index=False)
    print(t.to_string(index=False))

    print("\n" + "=" * 150)
    print("3차 — '+10% 익절 / -10% 손절 / 최대 60일' 실전 시뮬레이션")
    print("=" * 150)
    rows = []
    for name, fn in RULES.items():
        s = barrier(p, prices, fn, 0.10, 0.10, 60)
        if s:
            rows.append({"규칙": name, **s})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
