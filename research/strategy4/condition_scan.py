"""추가할 만한 전략 후보 탐색.

스냅샷 3개월(1,891행)로 조건을 고르면 과최적화가 불가피해서, 1999~2026 전체
기간 137종목 패널(약 74만 종목·일)에서 탐색한다.

평가 기준은 절대 수익률이 아니라 '같은 날 유니버스 평균 대비 초과수익'이다.
절대 수익률은 시장 방향에 지배당해서 조건의 기여도를 못 가른다.

다중검정 방어: 전반기(~2012)에서 발굴하고 후반기(2013~)에서 확인한다.
양쪽 부호가 같고 크기가 유지되는 조건만 후보로 인정한다.
"""
from __future__ import annotations

import itertools
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
from ma200_macd_golden import CACHE, OUT_DIR, REGIME_ORDER, build_qqq_state, dl
from backtest_qqq_block_v2 import UNIVERSE

PANEL = os.path.join(CACHE, "s4_scan_panel.pkl")
SPLIT = pd.Timestamp("2013-01-01")
MIN_SIGNALS = 400
MIN_DAYS = 150
HORIZON = 20


def features(raw: pd.DataFrame) -> pd.DataFrame:
    d = add_indicators(raw)
    c = d["Close"]
    d["distMA200"] = c / d["MA200"] - 1
    d["distLR"] = c / d["LR_Trendline"] - 1
    d["slopeN"] = d["LR_Slope"] / c
    d["squeeze"] = d["BB_Width"] / d["BB_Width60"]
    d["ret5"] = c.pct_change(5)
    d["ret20"] = c.pct_change(20)
    d["ret60"] = c.pct_change(60)
    d["dd252"] = c / c.rolling(252).max() - 1
    d["up252"] = c / c.rolling(252).min() - 1
    d["diDiff"] = d["PlusDI"] - d["MinusDI"]
    d["histN"] = d["MACD_Hist"] / c
    return d


NEED = ["MA200", "RSI", "CCI", "ADX", "PctB", "BB_Width60", "LR_Trendline",
        "VolRatio", "dd252", "ret60"]


def build() -> pd.DataFrame:
    if os.path.exists(PANEL):
        return pd.read_pickle(PANEL)
    qstate = build_qqq_state()
    frames = []
    for i, t in enumerate(UNIVERSE, 1):
        raw = dl(t)
        if raw is None or len(raw) < 500:
            continue
        d = features(raw).join(qstate, how="inner").dropna(subset=["premium"])
        d = d.dropna(subset=NEED)
        if len(d) < 300:
            continue
        cl = d["Close"].to_numpy()
        n = len(d)
        entry = np.full(n, np.nan)
        entry[:-1] = d["Open"].to_numpy()[1:]
        fut = np.full(n, np.nan)
        fut[: n - HORIZON] = cl[HORIZON:]
        keep = ["distMA200", "distLR", "slopeN", "squeeze", "ret5", "ret20", "ret60",
                "dd252", "up252", "diDiff", "histN", "RSI", "RSI_D1", "CCI", "CCI_D1",
                "ADX", "ADX_D1", "PctB", "VolRatio", "MACD_Hist", "MACD_Hist_D1"]
        out = d[keep].copy()
        out.insert(0, "ticker", t)
        out["date"] = d.index
        out["regime"] = d["regime"].to_numpy()
        out["fwd"] = (fut / entry - 1) * 100
        frames.append(out.reset_index(drop=True))
        if i % 25 == 0:
            print(f"  {i}/{len(UNIVERSE)}", flush=True)
    p = pd.concat(frames, ignore_index=True).dropna(subset=["fwd"])
    p["ex"] = p["fwd"] - p.groupby("date")["fwd"].transform("mean")
    p.to_pickle(PANEL)
    return p


def conditions(p: pd.DataFrame) -> dict[str, np.ndarray]:
    """고정된 상식적 임계값만 사용. 임계값을 데이터에 맞춰 튜닝하지 않는다."""
    c = {}
    c["RSI<25"] = p["RSI"] < 25
    c["RSI<30"] = p["RSI"] < 30
    c["RSI 30~50"] = (p["RSI"] >= 30) & (p["RSI"] < 50)
    c["RSI>70"] = p["RSI"] > 70
    c["RSI 반등(D1>0)"] = p["RSI_D1"] > 0
    c["CCI<-100"] = p["CCI"] < -100
    c["CCI<-200"] = p["CCI"] < -200
    c["CCI>100"] = p["CCI"] > 100
    c["CCI 반등(D1>0)"] = p["CCI_D1"] > 0
    c["%B<0"] = p["PctB"] < 0
    c["%B<0.2"] = p["PctB"] < 0.2
    c["%B>1"] = p["PctB"] > 1
    c["볼밴 스퀴즈(<0.7)"] = p["squeeze"] < 0.7
    c["볼밴 확장(>1.3)"] = p["squeeze"] > 1.3
    c["ADX>25"] = p["ADX"] > 25
    c["ADX<20"] = p["ADX"] < 20
    c["ADX 상승"] = p["ADX_D1"] > 0
    c["DI+ > DI-"] = p["diDiff"] > 0
    c["MACD>0"] = p["MACD_Hist"] > 0
    c["MACD 골든크로스"] = (p["MACD_Hist"] > 0) & (p["MACD_Hist_D1"] <= 0)
    c["MACD 히스트 상승"] = p["MACD_Hist"] > p["MACD_Hist_D1"]
    c["MA200 위"] = p["distMA200"] > 0
    c["MA200 아래"] = p["distMA200"] < 0
    c["MA200 +10% 이상"] = p["distMA200"] > 0.10
    c["MA200 -15% 이하"] = p["distMA200"] < -0.15
    c["추세선 -5% 이하"] = p["distLR"] < -0.05
    c["추세선 -10% 이하"] = p["distLR"] < -0.10
    c["추세선 +5% 이상"] = p["distLR"] > 0.05
    c["추세선 기울기 +"] = p["slopeN"] > 0
    c["거래량 2배"] = p["VolRatio"] > 2
    c["거래량 3배"] = p["VolRatio"] > 3
    c["거래량 부진(<0.7)"] = p["VolRatio"] < 0.7
    c["5일 -7% 이하"] = p["ret5"] < -0.07
    c["5일 +7% 이상"] = p["ret5"] > 0.07
    c["20일 -15% 이하"] = p["ret20"] < -0.15
    c["20일 +15% 이상"] = p["ret20"] > 0.15
    c["60일 +30% 이상"] = p["ret60"] > 0.30
    c["60일 -20% 이하"] = p["ret60"] < -0.20
    c["52주 고점 -30% 이하"] = p["dd252"] < -0.30
    c["52주 고점 -50% 이하"] = p["dd252"] < -0.50
    c["52주 신고가 근처"] = p["dd252"] > -0.02
    c["52주 저점 +10% 이내"] = p["up252"] < 0.10
    return {k: v.to_numpy() for k, v in c.items()}


def evaluate(ex: np.ndarray, daycode: np.ndarray, mask: np.ndarray,
             ndays: int) -> tuple[int, float, float]:
    n = int(mask.sum())
    if n == 0:
        return 0, np.nan, 0
    sel = ex[mask]
    days = len(np.unique(daycode[mask]))
    return n, float(sel.mean()), days


def main():
    pd.set_option("display.width", 320)
    pd.set_option("display.max_columns", 40)
    os.makedirs(OUT_DIR, exist_ok=True)

    p = build()
    print(f"패널 {p['date'].min().date()} ~ {p['date'].max().date()} / "
          f"{p['ticker'].nunique()}종목 / {len(p):,} 종목·일")

    conds = conditions(p)
    ex = p["ex"].to_numpy()
    daycode = p["date"].to_numpy().astype("datetime64[D]").astype(int)
    early = (p["date"] < SPLIT).to_numpy()
    late = ~early
    nday = len(np.unique(daycode))
    print(f"조건 {len(conds)}개 / 전반기 {early.sum():,}행 · 후반기 {late.sum():,}행")

    rows = []
    names = list(conds)
    combos = [(n,) for n in names] + list(itertools.combinations(names, 2))
    for combo in combos:
        m = conds[combo[0]]
        for extra in combo[1:]:
            m = m & conds[extra]
        n = int(m.sum())
        if n < MIN_SIGNALS:
            continue
        me = m & early
        ml = m & late
        if me.sum() < MIN_SIGNALS // 3 or ml.sum() < MIN_SIGNALS // 3:
            continue
        ndays = len(np.unique(daycode[m]))
        if ndays < MIN_DAYS:
            continue
        a, b = ex[me].mean(), ex[ml].mean()
        rows.append({"조건": " + ".join(combo), "개수": len(combo), "신호수": n,
                     "신호일": ndays, "전체초과%": round(ex[m].mean(), 3),
                     "전반기%": round(a, 3), "후반기%": round(b, 3),
                     "일관": bool(np.sign(a) == np.sign(b) and min(abs(a), abs(b)) > 0.2)})
    res = pd.DataFrame(rows).sort_values("전체초과%", ascending=False)
    res.to_csv(os.path.join(OUT_DIR, "scan_all.csv"), index=False)
    print(f"평가 대상 조합 {len(res):,}개 (신호 {MIN_SIGNALS}건·{MIN_DAYS}일 이상)")

    print("\n[단일 조건 상위 15 — 20일 초과수익]")
    single = res[res["개수"] == 1]
    print(single.head(15).drop(columns="개수").to_string(index=False))
    print("\n[단일 조건 하위 8 — 피해야 할 조건]")
    print(single.tail(8).drop(columns="개수").to_string(index=False))

    print("\n[2개 조합 상위 20 — 전·후반기 부호가 같은 것만]")
    pair = res[(res["개수"] == 2) & res["일관"]]
    print(pair.head(20).drop(columns=["개수", "일관"]).to_string(index=False))

    print("\n[상위 후보 정밀 검증]")
    rng = np.random.default_rng(0)
    regimes = p["regime"].to_numpy()
    top = pd.concat([single[single["일관"]].head(5), pair.head(8)])
    detail = []
    for _, r in top.iterrows():
        m = np.ones(len(p), dtype=bool)
        for part in r["조건"].split(" + "):
            m &= conds[part]
        dfd = pd.DataFrame({"d": daycode[m], "e": ex[m]}).groupby("d")["e"].mean().to_numpy()
        boot = np.array([rng.choice(dfd, len(dfd), replace=True).mean() for _ in range(3000)])
        lo, hi = np.percentile(boot, [2.5, 97.5])
        rec = {"조건": r["조건"], "신호수": r["신호수"], "초과%": r["전체초과%"],
               "95%CI": f"{lo:+.2f}~{hi:+.2f}", "유의": "O" if lo > 0 else "-",
               "승률%": round((ex[m] > 0).mean() * 100, 1)}
        for reg in REGIME_ORDER:
            sub = m & (regimes == reg)
            rec[reg] = round(ex[sub].mean(), 2) if sub.sum() >= 50 else None
        detail.append(rec)
    dt = pd.DataFrame(detail)
    print(dt.to_string(index=False))
    dt.to_csv(os.path.join(OUT_DIR, "scan_top.csv"), index=False)


if __name__ == "__main__":
    main()
