"""전략 4 재검토 — MA200 아래에서 MACD 골든크로스 '또는 기울기 상승'.

앞선 검증(ma200_macd_golden.py)은 골든크로스만 봤다. 여기서는 '기울기가 오를 때'
까지 조건을 넓혀 다시 본다. MACD 기울기는 해석이 갈려서 히스토그램 기울기와
MACD 선 기울기를 나눠서 전부 돌린다.

판정 기준은 절대 수익률이 아니라 '같은 날 MA200 아래 종목 평균 대비 초과수익'.
MA200 아래 종목은 같이 빠지고 같이 튀어서, 절대 수익률로는 MACD가 기여했는지
아니면 그냥 그날 시장이 반등한 건지 구분할 수 없다.
"""
from __future__ import annotations

import json
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
from ma200_macd_golden import (CACHE, FEE, OUT_DIR, PANEL_PATH, REGIME_ORDER,
                               build_qqq_state, dl)
from backtest_qqq_block_v2 import UNIVERSE

HORIZONS = [1, 3, 5, 10, 20, 60]
CASE = ["TE", "COHR"]


def build(symbols: dict[str, str], qstate: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    frames, prices = [], {}
    for name, sym in symbols.items():
        raw = dl(sym)
        if raw is None or len(raw) < 400:
            continue
        d = add_indicators(raw).join(qstate, how="inner").dropna(subset=["premium"])
        d = d.dropna(subset=["MA200", "MACD_Hist", "MACD_Hist_D1", "MACD_Hist_D2", "MACD"])
        if len(d) < 250:
            continue
        prices[name] = d
        cl = d["Close"].to_numpy()
        n = len(d)
        entry = np.full(n, np.nan)
        entry[:-1] = d["Open"].to_numpy()[1:]
        h0, h1, h2 = (d["MACD_Hist"].to_numpy(), d["MACD_Hist_D1"].to_numpy(),
                      d["MACD_Hist_D2"].to_numpy())
        macd = d["MACD"].to_numpy()
        macd_d1 = np.concatenate([[np.nan], macd[:-1]])
        out = pd.DataFrame({
            "ticker": name, "date": d.index, "regime": d["regime"].to_numpy(),
            "close": cl, "entryPrice": entry,
            "below200": cl < d["MA200"].to_numpy(),
            "golden": (h1 <= 0) & (h0 > 0),
            "histUp": h0 > h1,
            "histUp2": (h0 > h1) & (h1 > h2),
            "histUpNeg": (h0 < 0) & (h0 > h1),
            "macdUp": macd > macd_d1,
            "hist": h0,
        })
        for h in HORIZONS:
            fut = np.full(n, np.nan)
            fut[: n - h] = cl[h:]
            out[f"fwd{h}"] = (fut / entry - 1) * 100
        frames.append(out)
    p = pd.concat(frames, ignore_index=True)
    for h in HORIZONS:
        col = f"fwd{h}"
        below = p[col].where(p["below200"])
        p[f"ex{h}"] = p[col] - below.groupby(p["date"]).transform("mean")
    return p, prices


VARIANTS = {
    "① MA200↓ + MACD 골든크로스": ["below200", "golden"],
    "② MA200↓ + 히스토그램 상승": ["below200", "histUp"],
    "③ MA200↓ + 히스토그램 2일 연속 상승": ["below200", "histUp2"],
    "④ MA200↓ + 히스토그램 음수인데 상승 (바닥 반등)": ["below200", "histUpNeg"],
    "⑤ MA200↓ + MACD 선 상승": ["below200", "macdUp"],
    "⑥ MA200↓ + (골든크로스 or 히스토 상승)": ["below200", "goldenOrUp"],
    "비교군: MA200 아래 전체": ["below200"],
    "비교군: 전체": [],
}


def mask_of(p: pd.DataFrame, conds: list[str]) -> pd.Series:
    m = pd.Series(True, index=p.index)
    for c in conds:
        m &= (p["golden"] | p["histUp"]) if c == "goldenOrUp" else p[c]
    return m


def overview(p: pd.DataFrame, label: str) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for name, conds in VARIANTS.items():
        sub = p[mask_of(p, conds)]
        if sub.empty:
            continue
        rec = {"조건": name, "신호수": len(sub), "종목": sub["ticker"].nunique()}
        for h in (1, 5, 20, 60):
            rec[f"{h}일%"] = round(sub[f"fwd{h}"].mean(), 2)
        rec["20일승률%"] = round((sub["fwd20"] > 0).mean() * 100, 1)
        for h in (5, 20):
            rec[f"초과{h}%p"] = round(sub[f"ex{h}"].mean(), 3)
        e = sub[["date", "ex20"]].dropna()
        daily = e.groupby("date")["ex20"].mean().to_numpy()
        if len(daily) > 30:
            boot = np.array([rng.choice(daily, len(daily), replace=True).mean()
                             for _ in range(3000)])
            lo, hi = np.percentile(boot, [2.5, 97.5])
            rec["20일 95%CI"] = f"{lo:+.2f}~{hi:+.2f}"
            rec["유의"] = "O" if (lo > 0 or hi < 0) else "-"
        rows.append(rec)
    t = pd.DataFrame(rows)
    t.to_csv(os.path.join(OUT_DIR, f"slope_overview_{label}.csv"), index=False)
    return t


def regime_grid(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, conds in VARIANTS.items():
        sub = p[mask_of(p, conds)]
        rec = {"조건": name}
        for regime in REGIME_ORDER:
            s = sub[sub["regime"] == regime]
            rec[regime] = (f"{s['fwd20'].mean():+.2f} ({s['ex20'].mean():+.2f})"
                           if len(s) >= 30 else "-")
        rows.append(rec)
    return pd.DataFrame(rows)


def yearly(p: pd.DataFrame, conds: list[str]) -> pd.DataFrame:
    sub = p[mask_of(p, conds)]
    g = sub.groupby(sub["date"].dt.year)
    t = pd.DataFrame({"신호": g.size(), "20일%": g["fwd20"].mean().round(2),
                      "초과%p": g["ex20"].mean().round(2)})
    return t[t["신호"] >= 10]


def simulate(p: pd.DataFrame, conds: list[str], prices: dict,
             tp: float, sl: float, hold: int) -> dict:
    trades = []
    for t, grp in p[mask_of(p, conds) & p["entryPrice"].notna()].groupby("ticker"):
        px = prices.get(t)
        if px is None:
            continue
        idx, op, cl = px.index, px["Open"].to_numpy(), px["Close"].to_numpy()
        pos = {d: i for i, d in enumerate(idx)}
        busy = -1
        for d in grp["date"].sort_values():
            i0 = pos.get(d)
            if i0 is None or i0 <= busy or i0 + 1 >= len(idx):
                continue
            ep = op[i0 + 1] * (1 + FEE)
            if not np.isfinite(ep) or ep <= 0:
                continue
            ret, days = None, 0
            for j in range(i0 + 1, min(i0 + 1 + hold, len(idx))):
                days = j - i0
                r = cl[j] * (1 - FEE) / ep - 1
                if r >= tp or r <= -sl or days >= hold:
                    ret = r
                    break
            if ret is None:
                ret = cl[min(i0 + hold, len(idx) - 1)] * (1 - FEE) / ep - 1
            busy = i0 + days
            trades.append((ret * 100, days))
    if not trades:
        return {}
    r = np.array([x[0] for x in trades])
    dd = np.array([x[1] for x in trades])
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {"거래": len(r), "승률%": round((r > 0).mean() * 100, 1),
            "평균%": round(r.mean(), 2), "PF": round(gains / losses, 2) if losses else np.inf,
            "최악%": round(r.min(), 1), "평균일": round(dd.mean(), 1)}


def episode_compare(p: pd.DataFrame) -> pd.DataFrame:
    """신호일이 붙어 있으면 한 사건으로 묶어 비교군과 같은 잣대로 잰다.

    TE처럼 한 번의 반등에서 신호가 13일 연속 나오면, 행 단위 평균은 그 사건
    하나를 13번 센다. 사건 단위로 세면 표본이 확 줄고 평균도 달라진다.
    """
    rows = []
    for name, conds in VARIANTS.items():
        m = mask_of(p, conds)
        sub = p[m].sort_values(["ticker", "date"])
        if sub.empty:
            continue
        ep_ret, ep_ex = [], []
        for t, grp in sub.groupby("ticker"):
            dates = grp["date"].to_numpy()
            gap = np.concatenate([[True], np.diff(dates).astype("timedelta64[D]")
                                  .astype(int) > 7])
            first = grp[gap]
            ep_ret.append(first["fwd20"].to_numpy())
            ep_ex.append(first["ex20"].to_numpy())
        r = np.concatenate(ep_ret)
        e = np.concatenate(ep_ex)
        r, e = r[np.isfinite(r)], e[np.isfinite(e)]
        rows.append({"조건": name, "행 기준": int(m.sum()), "사건 기준": len(r),
                     "사건당 20일%": round(r.mean(), 2),
                     "승률%": round((r > 0).mean() * 100, 1),
                     "중앙%": round(np.median(r), 2),
                     "초과%p": round(e.mean(), 3)})
    return pd.DataFrame(rows)


def case_study(p: pd.DataFrame) -> None:
    for t in CASE:
        sub = p[p["ticker"] == t]
        if sub.empty:
            print(f"\n{t}: 패널에 없음")
            continue
        cutoff = sub["date"].max() - pd.Timedelta(days=400)
        recent = sub[(sub["date"] >= cutoff) & sub["below200"] &
                     (sub["golden"] | sub["histUp2"])]
        print(f"\n▸ {t} — 최근 400일 중 'MA200 아래 + (골든크로스 or 히스토 2일 상승)' "
              f"{len(recent)}건")
        if recent.empty:
            continue
        show = recent[["date", "regime", "golden", "histUp2", "close",
                       "fwd5", "fwd20", "fwd60", "ex20"]].copy()
        show["date"] = show["date"].dt.date
        show["신호종류"] = np.where(show["golden"], "골든크로스", "히스토 상승")
        show = show.drop(columns=["golden", "histUp2"])
        show.columns = ["일자", "국면", "종가", "5일%", "20일%", "60일%", "20일초과%p", "신호종류"]
        print(show.round(2).to_string(index=False))
        done = recent["fwd20"].dropna()
        if len(done):
            print(f"   → 20일 수익률 평균 {done.mean():+.2f}% / "
                  f"플러스 {int((done > 0).sum())}건 / 마이너스 {int((done <= 0).sum())}건 / "
                  f"초과수익 평균 {recent['ex20'].mean():+.2f}%p")

        allsig = sub[sub["below200"] & (sub["golden"] | sub["histUp2"])]
        v = allsig["fwd20"].dropna()
        print(f"   {t} 전체 기간({sub['date'].min().date()}~) 같은 신호 {len(allsig)}건 · "
              f"20일 평균 {v.mean():+.2f}% · 승률 {(v > 0).mean() * 100:.1f}% · "
              f"초과 {allsig['ex20'].mean():+.2f}%p")


def overlap(p: pd.DataFrame, conds: list[str]) -> None:
    if not os.path.exists(PANEL_PATH):
        return
    base = pd.read_pickle(PANEL_PATH)[["ticker", "date", "ahCode", "liveCode"]]
    m = p[mask_of(p, conds)][["ticker", "date"]].merge(base, on=["ticker", "date"], how="left")
    n = len(m)
    parts = []
    for code in list("ABCDEFGH"):
        k = int((m["ahCode"] == code).sum())
        if k / n > 0.005:
            parts.append(f"{code} {k / n * 100:.1f}%")
    for code in ("1", "2"):
        k = int((m["liveCode"] == code).sum())
        if k / n > 0.005:
            parts.append(f"전략{code} {k / n * 100:.1f}%")
    hit = m["ahCode"].notna().sum() + m["liveCode"].notna().sum()
    print(f"  기존 A~H·전략1/2와 동시 발동 {hit / n * 100:.1f}% "
          f"({', '.join(parts) or '유의미한 겹침 없음'})")


def main():
    pd.set_option("display.width", 340)
    pd.set_option("display.max_columns", 40)
    os.makedirs(OUT_DIR, exist_ok=True)
    qstate = build_qqq_state()

    print("#" * 150)
    print("# 미국 주요 137종목 (1999~2026) — 통계 판정용")
    print("#" * 150)
    p, prices = build({t: t for t in UNIVERSE}, qstate)
    print(f"패널 {p['date'].min().date()} ~ {p['date'].max().date()} / "
          f"{p['ticker'].nunique()}종목 / {len(p):,} 종목·일")
    print("\n[조건별 성적 — 괄호 없는 값은 절대 수익률, 초과는 같은 날 MA200 아래 종목 평균 대비]")
    print(overview(p, "us137").to_string(index=False))

    print("\n[국면 × 조건 — 20일 절대수익 (초과수익)]")
    print(regime_grid(p).to_string(index=False))

    print("\n[신호 군집 제거 — 연속 신호를 한 사건으로 묶은 뒤 비교]")
    print(episode_compare(p).to_string(index=False))

    for name in ("① MA200↓ + MACD 골든크로스", "③ MA200↓ + 히스토그램 2일 연속 상승"):
        print(f"\n[{name} · 거래 시뮬레이션]")
        rows = []
        for tp, sl, hold in [(0.10, 0.07, 20), (0.15, 0.10, 40), (0.08, 0.05, 15)]:
            s = simulate(p, VARIANTS[name], prices, tp, sl, hold)
            if s:
                rows.append({"TP/SL/보유": f"{tp:.0%}/{sl:.0%}/{hold}일", **s})
        print(pd.DataFrame(rows).to_string(index=False))
        overlap(p, VARIANTS[name])

    print("\n[③ 히스토그램 2일 연속 상승 · 연도별]")
    print(yearly(p, VARIANTS["③ MA200↓ + 히스토그램 2일 연속 상승"]).to_string())

    print("\n" + "#" * 150)
    print("# 관심종목 57개 — TE · COHR 확인용")
    print("#" * 150)
    mapping = json.load(open(os.path.join(CACHE, "s4_watchlist_map.json")))
    w, _ = build(mapping, qstate)
    print(f"패널 {w['date'].min().date()} ~ {w['date'].max().date()} / "
          f"{w['ticker'].nunique()}종목 / {len(w):,} 종목·일")
    print("\n[조건별 성적 — 관심종목 기준]")
    print(overview(w, "watchlist").to_string(index=False))
    case_study(w)


if __name__ == "__main__":
    main()
