"""후보 α'의 순증분 확인 + 관심종목 실전 적용.

α'는 기존 E/F와 35.6% 겹친다. 겹치는 부분을 빼고도 초과수익이 남는지,
그리고 사용자 관심종목 57개에서 실제로 얼마나 자주 발동하는지 본다.
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

from condition_scan import HORIZON, build, features
from ma200_macd_golden import CACHE, PANEL_PATH, REGIME_ORDER, build_qqq_state, dl

ALPHA = lambda p: (p["ret60"] > 0.30) & (p["CCI"] < -100)
BETA = lambda p: (p["dd252"] < -0.50) & (p["RSI"] < 25)


def incremental(p: pd.DataFrame) -> None:
    base = pd.read_pickle(PANEL_PATH)[["ticker", "date", "ahCode", "liveCode"]]
    q = p.merge(base, on=["ticker", "date"], how="left")
    for label, fn in [("α' (60일+30% & CCI<-100)", ALPHA),
                      ("β (52주고점-50%↓ & RSI<25)", BETA)]:
        m = fn(q)
        fresh = m & q["ahCode"].isna() & q["liveCode"].isna()
        dup = m & (q["ahCode"].notna() | q["liveCode"].notna())
        print(f"\n{label}")
        print(f"  전체       {int(m.sum()):>6,}건  초과 {q.loc[m, 'ex'].mean():+.2f}%")
        print(f"  기존룰 중복 {int(dup.sum()):>6,}건  초과 {q.loc[dup, 'ex'].mean():+.2f}%")
        print(f"  순수 신규  {int(fresh.sum()):>6,}건  초과 {q.loc[fresh, 'ex'].mean():+.2f}%"
              f"   ← 이게 추가로 얻는 부분")
        yr = q[fresh].groupby(q.loc[fresh, "date"].dt.year)["ex"].agg(["size", "mean"])
        yr = yr[yr["size"] >= 5]
        print(f"  순수 신규 연도별: {len(yr)}년 중 {(yr['mean'] > 0).sum()}년 플러스")


def watchlist(qstate: pd.DataFrame) -> None:
    map_fp = os.path.join(CACHE, "s4_watchlist_map.json")
    mapping = json.load(open(map_fp))
    rows, live = [], []
    for name, sym in mapping.items():
        raw = dl(sym)
        if raw is None or len(raw) < 400:
            continue
        d = features(raw).join(qstate, how="inner").dropna(subset=["premium"])
        d = d.dropna(subset=["MA200", "RSI", "CCI", "ret60", "dd252"])
        if len(d) < 300:
            continue
        cl = d["Close"].to_numpy()
        n = len(d)
        entry = np.full(n, np.nan)
        entry[:-1] = d["Open"].to_numpy()[1:]
        fut = np.full(n, np.nan)
        fut[: n - HORIZON] = cl[HORIZON:]
        d = d.assign(ticker=name, fwd=(fut / entry - 1) * 100)
        for label, fn in [("α'", ALPHA), ("β", BETA)]:
            m = fn(d)
            sub = d[m]
            if len(sub) >= 10:
                rows.append({"후보": label, "종목": name, "신호": len(sub),
                             "20일평균%": round(sub["fwd"].mean(), 2),
                             "승률%": round((sub["fwd"] > 0).mean() * 100, 1)})
            recent = d[m & (d.index >= d.index.max() - pd.Timedelta(days=45))]
            for dt in recent.index:
                live.append({"후보": label, "종목": name, "일자": dt.date(),
                             "RSI": round(d.loc[dt, "RSI"], 1),
                             "CCI": round(d.loc[dt, "CCI"], 0),
                             "60일%": round(d.loc[dt, "ret60"] * 100, 1),
                             "52주고점대비%": round(d.loc[dt, "dd252"] * 100, 1),
                             "국면": d.loc[dt, "regime"]})
    t = pd.DataFrame(rows)
    print("\n[관심종목 57개 · 후보별 종목 성적 (신호 10건 이상)]")
    for label in ("α'", "β"):
        s = t[t["후보"] == label].sort_values("20일평균%", ascending=False)
        if s.empty:
            continue
        print(f"\n {label}: {len(s)}종목 / 전체 신호 {s['신호'].sum()}건 / "
              f"가중평균 20일 {np.average(s['20일평균%'], weights=s['신호']):+.2f}% / "
              f"플러스 종목 {(s['20일평균%'] > 0).sum()}/{len(s)}")
        print(s.head(10).to_string(index=False))
    lv = pd.DataFrame(live).sort_values("일자")
    print(f"\n[최근 45일 발동 내역 — 관심종목]")
    print(lv.to_string(index=False) if not lv.empty else " 없음")


def main():
    pd.set_option("display.width", 320)
    p = build()
    print("[기존 A~H·전략1/2를 제외한 순증분]")
    incremental(p)
    watchlist(build_qqq_state())


if __name__ == "__main__":
    main()
