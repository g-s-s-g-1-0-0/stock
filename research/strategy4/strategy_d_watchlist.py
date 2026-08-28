"""전략 D의 진입 조건을 분해하고 관심종목 57개에 돌려본다.

D는 '200일선 위 & 상승 흐름 강화'다. 조건 여섯 개가 전부 추세가 살아 있고
아직 과열되지 않았다는 걸 확인하는 장치라, 전략 1(하락장 저점)·2(회복장)와
겹칠 일이 구조적으로 없다.

패널 산출은 ma200_macd_golden.build_panel과 같은 경로를 쓴다. 조건 판정을
직접 다시 구현하면 나스닥 필터 히스테리시스에서 어긋나기 때문이다.
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
from calculator import market_regime as mr
from ma200_macd_golden import (CACHE, FEE, OUT_DIR, build_qqq_state, dl,
                               make_row, supplement)
import research.strategy4.legacy_rules_ah as ah_rules

TP, SL, MAXHOLD = 0.10, 0.10, 30
RECENT_DAYS = 120

COLS = ["Open", "High", "Low", "Close", "MA200", "MA20", "MA60", "MA144",
        "MA20_D1", "MA20_PREV5", "CLOSE_D1", "RSI", "CCI", "MACD_Hist",
        "MACD_Hist_D1", "MACD_Hist_D2", "PctB", "PctB_Low", "BB_Width",
        "BB_Width_D1", "BB_Width60", "VolRatio", "VolRatio20",
        "PlusDI", "MinusDI", "ADX", "ADX_D1", "LR_Slope", "LR_Trendline"]

D_CONDS = [
    ("종가 > 200일선", lambda d: d["Close"] > d["MA200"]),
    ("+DI > -DI", lambda d: d["PlusDI"] > d["MinusDI"]),
    ("ADX > 30", lambda d: d["ADX"] > 30),
    ("ADX 상승", lambda d: d["ADX"] > d["ADX_D1"]),
    ("MACD 히스토그램 > 0", lambda d: d["MACD_Hist"] > 0),
    ("%B 30~75", lambda d: d["PctB"].between(30, 75)),
]


def prep(sym: str, qstate: pd.DataFrame, vix: pd.Series) -> pd.DataFrame | None:
    raw = dl(sym)
    if raw is None or len(raw) < 400:
        return None
    d = supplement(add_indicators(raw)).join(qstate, how="inner").dropna(subset=["premium"])
    if len(d) < 250:
        return None
    arr = {c: d[c].to_numpy(dtype=float) for c in COLS}
    vixarr = vix.reindex(d.index, method="ffill").to_numpy(dtype=float)
    prem = d["premium"].to_numpy(dtype=float)
    recov = d["recovery"].to_numpy(dtype=bool)

    codes = []
    for i in range(len(d)):
        if np.isnan(arr["MA200"][i]) or np.isnan(arr["Close"][i]):
            codes.append(None)
            continue
        codes.append(ah_rules.evaluate_buy_condition(
            make_row(arr, i, "ah"), vixarr[i], prem[i], False,
            nasdaq_buy_block_max=mr.qqq_buy_block_max(bool(recov[i])),
            is_recovery_market=bool(recov[i]),
        )["strategyType"])
    return d.assign(ahCode=codes)


def outcome(d: pd.DataFrame, i: int) -> dict:
    op, hi, lo, cl = (d["Open"].to_numpy(), d["High"].to_numpy(),
                      d["Low"].to_numpy(), d["Close"].to_numpy())
    n = len(d)
    if i + 1 >= n:
        return {"결과": "진입 전", "소요일": np.nan, "손익%": np.nan}
    ep = op[i + 1] * (1 + FEE)
    end = min(i + 1 + MAXHOLD, n)
    sh, sll = hi[i + 1:end], lo[i + 1:end]
    ht, hs = sh >= ep * (1 + TP), sll <= ep * (1 - SL)
    k_tp = int(np.argmax(ht)) if ht.any() else -1
    k_sl = int(np.argmax(hs)) if hs.any() else -1
    if k_sl >= 0 and (k_tp < 0 or k_sl <= k_tp):
        return {"결과": "손절", "소요일": k_sl + 1, "손익%": round(-SL * 100 - FEE * 100, 1)}
    if k_tp >= 0:
        return {"결과": "달성", "소요일": k_tp + 1, "손익%": round(TP * 100 - FEE * 100, 1)}
    cur = round((cl[end - 1] * (1 - FEE) / ep - 1) * 100, 1)
    tag = "진행중" if end < i + 1 + MAXHOLD else "기간만료"
    return {"결과": tag, "소요일": len(sh), "손익%": cur}


def funnel(data: dict) -> pd.DataFrame:
    """조건을 하나씩 쌓으며 후보가 얼마나 걸러지는지 본다."""
    all_d = pd.concat(data.values())
    total = len(all_d)
    acc = pd.Series(True, index=all_d.index)
    rows = []
    for label, fn in D_CONDS:
        c = fn(all_d).fillna(False)
        acc = acc & c
        rows.append({"조건": label,
                     "단독 통과%": round(c.mean() * 100, 1),
                     "누적 통과": int(acc.sum()),
                     "누적 통과%": round(acc.sum() / total * 100, 2)})
    fired = (all_d["ahCode"] == "D").sum()
    rows.append({"조건": "+ 나스닥 게이트 & A·B·C 미발동",
                 "단독 통과%": np.nan, "누적 통과": int(fired),
                 "누적 통과%": round(fired / total * 100, 2)})
    return pd.DataFrame(rows)


def main():
    pd.set_option("display.width", 320)
    qstate = build_qqq_state()
    vix = dl("^VIX")["Close"].reindex(qstate.index, method="ffill")
    mapping = json.load(open(os.path.join(CACHE, "s4_watchlist_map.json")))

    data = {}
    for name, sym in mapping.items():
        d = prep(sym, qstate, vix)
        if d is not None:
            data[name] = d
    last = max(d.index.max() for d in data.values())
    print(f"관심종목 {len(data)}개 로드 (데이터 종료 {last.date()})")

    print("\n" + "=" * 120)
    print("전략 D 진입 조건 — 관심종목 전체 거래일 기준 통과율")
    print("=" * 120)
    print(funnel(data).to_string(index=False))

    stats, recent, live = [], [], []
    for name, d in data.items():
        rows = np.flatnonzero((d["ahCode"] == "D").to_numpy())
        res = [outcome(d, i) for i in rows]
        done = [r for r in res if r["결과"] in ("달성", "손절", "기간만료")]
        if len(done) >= 5:
            hit = [r for r in done if r["결과"] == "달성"]
            stats.append({
                "종목": name, "과거 신호": len(done),
                "달성률%": round(len(hit) / len(done) * 100, 1),
                "손절률%": round(np.mean([r["결과"] == "손절" for r in done]) * 100, 1),
                "달성 중앙일": int(np.median([r["소요일"] for r in hit])) if hit else np.nan,
                "평균 손익%": round(np.mean([r["손익%"] for r in done]), 2),
            })
        cutoff = d.index.max() - pd.Timedelta(days=RECENT_DAYS)
        for i, r in zip(rows, res):
            if d.index[i] >= cutoff:
                recent.append({"종목": name, "신호일": d.index[i].date(),
                               "종가": round(d["Close"].iloc[i], 2),
                               "ADX": round(d["ADX"].iloc[i], 1),
                               "%B": round(d["PctB"].iloc[i], 1),
                               "MA200이격%": round((d["Close"].iloc[i] / d["MA200"].iloc[i] - 1) * 100, 1),
                               **r})
        if d["ahCode"].iloc[-1] == "D":
            live.append({"종목": name, "일자": d.index[-1].date(),
                         "종가": round(d["Close"].iloc[-1], 2),
                         "ADX": round(d["ADX"].iloc[-1], 1),
                         "%B": round(d["PctB"].iloc[-1], 1)})

    print("\n" + "=" * 120)
    print(f"최근 {RECENT_DAYS}일 D 발동 이력 (+{TP:.0%} 익절 / -{SL:.0%} 손절 / 최대 {MAXHOLD}일)")
    print("=" * 120)
    if recent:
        rt = pd.DataFrame(recent).sort_values("신호일")
        print(rt.to_string(index=False))
        done = rt[rt["결과"].isin(["달성", "손절", "기간만료"])]
        if len(done):
            hit = int((done["결과"] == "달성").sum())
            print(f"\n  종결 {len(done)}건 중 달성 {hit}건 ({hit / len(done) * 100:.0f}%) · "
                  f"평균 손익 {done['손익%'].mean():+.2f}%")
    else:
        print("  발동 없음")

    print("\n" + "=" * 120)
    print("현재 발동 중 (마지막 거래일 기준)")
    print("=" * 120)
    print(pd.DataFrame(live).to_string(index=False) if live else "  없음")

    print("\n" + "=" * 120)
    print("관심종목별 D 과거 성적 (신호 5건 이상, 달성률 순)")
    print("=" * 120)
    st = pd.DataFrame(stats).sort_values("달성률%", ascending=False)
    print(st.to_string(index=False))
    n = st["과거 신호"].sum()
    print(f"\n  합계 {int(n):,}건 · 가중 달성률 {(st['달성률%'] * st['과거 신호']).sum() / n:.1f}% · "
          f"가중 손절률 {(st['손절률%'] * st['과거 신호']).sum() / n:.1f}% · "
          f"평균 손익 {(st['평균 손익%'] * st['과거 신호']).sum() / n:+.2f}%")
    st.to_csv(os.path.join(OUT_DIR, "d_watchlist.csv"), index=False)


if __name__ == "__main__":
    main()
