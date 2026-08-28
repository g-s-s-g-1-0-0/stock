"""MA200 아래를 '이탈 신선도'와 'MA200 기울기'로 쪼개서 다시 본다.

앞선 검증은 MA200 아래를 한 덩어리로 봤다. 그런데 거기에는 두 가지가 섞여 있다.

  (A) MA200이 우상향하는데 가격이 잠깐 아래로 빠진 눌림목  (TE·RKLB·IONQ 유형)
  (B) MA200 자체가 우하향하는 장기 하락 추세

(A)와 (B)를 평균 내면 서로 상쇄돼서 아무 신호도 안 남는다. 여기서는
  - MA200 기울기 (20일 전 대비 상승/하락)
  - 이탈 후 경과일 (내려온 지 며칠 됐는지)
두 축으로 갈라서 각각 잰다.
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

CASE = ["TE", "RKLB", "IONQ", "COHR"]
FRESH_BINS = [(1, 3), (4, 10), (11, 20), (21, 60), (61, 10_000)]


def prep(t: str) -> pd.DataFrame | None:
    raw = dl(t)
    if raw is None or len(raw) < 300:
        return None
    d = add_indicators(raw).dropna(subset=["MA200", "MACD_Hist", "MACD_Hist_D1",
                                           "MACD_Hist_D2"])
    if len(d) < 250:
        return None
    cl, ma = d["Close"].to_numpy(), d["MA200"].to_numpy()
    below = cl < ma

    # MA200 아래로 내려온 뒤 며칠째인지 (위에 있으면 0)
    days = np.zeros(len(d), dtype=int)
    run = 0
    for i, b in enumerate(below):
        run = run + 1 if b else 0
        days[i] = run

    h0, h1, h2 = (d["MACD_Hist"].to_numpy(), d["MACD_Hist_D1"].to_numpy(),
                  d["MACD_Hist_D2"].to_numpy())
    ma_prev = np.concatenate([np.full(20, np.nan), ma[:-20]])
    return d.assign(
        below200=below, daysBelow=days,
        ma200Up=ma > ma_prev,
        ma200Slope=(ma / ma_prev - 1) * 100,
        golden=(h1 <= 0) & (h0 > 0),
        histUp2=(h0 > h1) & (h1 > h2),
        signal=((h1 <= 0) & (h0 > 0)) | ((h0 > h1) & (h1 > h2)),
    )


def panel(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for t, d in data.items():
        cl, n = d["Close"].to_numpy(), len(d)
        entry = np.full(n, np.nan)
        entry[:-1] = d["Open"].to_numpy()[1:]
        out = pd.DataFrame({
            "ticker": t, "date": d.index, "below200": d["below200"].to_numpy(),
            "daysBelow": d["daysBelow"].to_numpy(), "ma200Up": d["ma200Up"].to_numpy(),
            "golden": d["golden"].to_numpy(), "histUp2": d["histUp2"].to_numpy(),
            "signal": d["signal"].to_numpy(),
        })
        for h in (1, 3, 5, 10, 20, 60):
            fut = np.full(n, np.nan)
            fut[: n - h] = cl[h:]
            out[f"fwd{h}"] = (fut / entry - 1) * 100
        frames.append(out)
    p = pd.concat(frames, ignore_index=True)
    for h in (1, 5, 20):
        p[f"ex{h}"] = p[f"fwd{h}"] - p.groupby("date")[f"fwd{h}"].transform("mean")
    return p


def slope_split(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for up in (True, False):
        base = p[p["below200"] & (p["ma200Up"] == up)]
        tag = "MA200 우상향" if up else "MA200 우하향"
        for name, m in (("조건없음 (아래 전체)", pd.Series(True, index=base.index)),
                        ("+ 골든크로스", base["golden"]),
                        ("+ 히스토 2일상승", base["histUp2"]),
                        ("+ 골든 or 히스토상승", base["signal"])):
            s = base[m]
            if len(s) < 200:
                continue
            rows.append({
                "MA200 기울기": tag, "조건": name, "신호수": len(s),
                "1일%": round(s["fwd1"].mean(), 3),
                "5일%": round(s["fwd5"].mean(), 2),
                "20일%": round(s["fwd20"].mean(), 2),
                "60일%": round(s["fwd60"].mean(), 2),
                "20일승률%": round((s["fwd20"] > 0).mean() * 100, 1),
                "초과20%p": round(s["ex20"].mean(), 2),
            })
    return pd.DataFrame(rows)


def freshness(p: pd.DataFrame, require_signal: bool) -> pd.DataFrame:
    rows = []
    for up in (True, False):
        for lo, hi in FRESH_BINS:
            m = (p["below200"] & (p["ma200Up"] == up) &
                 p["daysBelow"].between(lo, hi))
            if require_signal:
                m &= p["signal"]
            s = p[m]
            if len(s) < 100:
                continue
            rows.append({
                "MA200": "우상향" if up else "우하향",
                "이탈 후": f"{lo}~{hi}일" if hi < 1000 else f"{lo}일+",
                "신호수": len(s),
                "3일%": round(s["fwd3"].mean(), 2),
                "10일%": round(s["fwd10"].mean(), 2),
                "1일%": round(s["fwd1"].mean(), 3),
                "5일%": round(s["fwd5"].mean(), 2),
                "20일%": round(s["fwd20"].mean(), 2),
                "60일%": round(s["fwd60"].mean(), 2),
                "20일승률%": round((s["fwd20"] > 0).mean() * 100, 1),
                "초과20%p": round(s["ex20"].mean(), 2),
            })
    return pd.DataFrame(rows)


def spells(d: pd.DataFrame, t: str) -> None:
    """MA200 아래로 내려간 구간별로 이후 흐름."""
    below = d["below200"].to_numpy()
    cl = d["Close"].to_numpy()
    starts = np.flatnonzero(below & ~np.concatenate([[False], below[:-1]]))
    rows = []
    for i in starts:
        end = i
        while end + 1 < len(below) and below[end + 1]:
            end += 1
        rec = {"이탈일": d.index[i].date(), "머문일수": end - i + 1,
               "MA200기울기": "↑" if d["ma200Up"].iloc[i] else "↓"}
        for h in (1, 5, 20):
            rec[f"{h}일%"] = round((cl[i + h] / cl[i] - 1) * 100, 1) if i + h < len(cl) else np.nan
        sig = d.iloc[i:end + 1]
        first = sig[sig["signal"].to_numpy()]
        if len(first):
            j = d.index.get_loc(first.index[0])
            rec["첫신호"] = first.index[0].date()
            rec["신호후1일%"] = round((cl[j + 1] / cl[j] - 1) * 100, 1) if j + 1 < len(cl) else np.nan
            rec["신호후20일%"] = round((cl[j + 20] / cl[j] - 1) * 100, 1) if j + 20 < len(cl) else np.nan
        rows.append(rec)
    print(f"\n▸ {t} — MA200 이탈 구간 {len(rows)}개 (최근 10개)")
    if rows:
        print(pd.DataFrame(rows).tail(10).to_string(index=False))


def main():
    pd.set_option("display.width", 340)
    pd.set_option("display.max_columns", 40)

    print("=" * 130)
    print("사용자 반례 종목 — MA200 이탈 구간별 실제 흐름")
    print("=" * 130)
    for t in CASE:
        d = prep(t)
        if d is None:
            print(f"\n{t}: 데이터 부족")
            continue
        print(f"\n{t}: {d.index.min().date()} ~ {d.index.max().date()}")
        spells(d, t)

    print("\n" + "=" * 130)
    print("미국 137종목 — MA200 기울기로 쪼갠 결과")
    print("=" * 130)
    data = {}
    for t in UNIVERSE:
        d = prep(t)
        if d is not None:
            data[t] = d
    p = panel(data)
    print(f"패널 {p['date'].min().date()} ~ {p['date'].max().date()} / {len(p):,} 종목·일")
    print("\n[MA200 기울기 × 조건 — 초과는 같은 날 전체 종목 평균 대비]")
    t1 = slope_split(p)
    print(t1.to_string(index=False))
    t1.to_csv(os.path.join(OUT_DIR, "fresh_slope_split.csv"), index=False)

    print("\n[MA200 기울기 × 이탈 후 경과일 — MACD 조건 없이 그냥 매수]")
    t2 = freshness(p, require_signal=False)
    print(t2.to_string(index=False))
    t2.to_csv(os.path.join(OUT_DIR, "fresh_days_below_nosig.csv"), index=False)

    print("\n[같은 칸에 MACD 신호(골든 or 히스토상승)를 추가로 요구하면]")
    t3 = freshness(p, require_signal=True)
    print(t3.to_string(index=False))
    t3.to_csv(os.path.join(OUT_DIR, "fresh_days_below.csv"), index=False)

    print("\n[MACD 요구의 순효과 — 신호 있을 때 빼기 조건없음]")
    key = ["MA200", "이탈 후"]
    d = t3.merge(t2, on=key, suffixes=("_신호", "_전체"))
    for c in ("3일%", "10일%", "20일%", "초과20%p"):
        d[f"Δ{c}"] = (d[f"{c}_신호"] - d[f"{c}_전체"]).round(2)
    print(d[key + ["신호수_신호", "신호수_전체"] +
            [f"Δ{c}" for c in ("3일%", "10일%", "20일%", "초과20%p")]].to_string(index=False))


if __name__ == "__main__":
    main()
