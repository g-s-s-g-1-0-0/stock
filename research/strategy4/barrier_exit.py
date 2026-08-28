"""전략 4를 '목표 수익 달성 즉시 매도' 방식으로 재측정.

고정 20일/60일 수익률 대신 매수 후 일봉 경로를 따라가며 +10%/+20% 선에
먼저 닿는지를 본다. 다만 손절과 보유 한도가 없으면 '언젠가는 오른다'라서
도달률이 무조건 높게 나온다. 그래서 세 가지를 같이 잰다.

  1) 목표에 닿기까지 걸린 일수 (자본이 묶이는 시간)
  2) 목표에 닿기 전 최대 평가손실 (MAE) — 10% 먹기 전에 얼마나 물리는지
  3) 같은 잣대로 잰 비교군 (MA200 아래 종목 아무 날이나 매수)

같은 날 시가가 아니라 신호 다음날 시가 진입, 장중 고가/저가로 터치 판정,
손절과 목표가 같은 날 겹치면 손절이 먼저 났다고 본다(보수적).
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

BASE_SAMPLE = 60_000
SEED = 7


def prep(t: str) -> pd.DataFrame | None:
    raw = dl(t)
    if raw is None or len(raw) < 400:
        return None
    d = add_indicators(raw).dropna(subset=["MA200", "MACD_Hist", "MACD_Hist_D1",
                                           "MACD_Hist_D2"])
    if len(d) < 300:
        return None
    cl = d["Close"].to_numpy()
    h0, h1, h2 = (d["MACD_Hist"].to_numpy(), d["MACD_Hist_D1"].to_numpy(),
                  d["MACD_Hist_D2"].to_numpy())
    ret60 = d["Close"].pct_change(60).to_numpy()
    dd252 = (cl / d["Close"].rolling(252).max().to_numpy() - 1)
    d = d.assign(
        below200=cl < d["MA200"].to_numpy(),
        golden=(h1 <= 0) & (h0 > 0),
        histUp2=(h0 > h1) & (h1 > h2),
        histUpNeg=(h0 < 0) & (h0 > h1),
        alpha=(ret60 > 0.30) & (d["CCI"].to_numpy() < -100),
        beta=(dd252 < -0.50) & (d["RSI"].to_numpy() < 25),
    )
    return d


def walk(px: pd.DataFrame, entries: np.ndarray, tp: float, sl: float | None,
         maxhold: int) -> list[tuple[float, int, int, float]]:
    """(수익률%, 보유일, 결과코드, 목표도달 전 최대평가손실%) 목록.

    결과코드: 1=목표도달, -1=손절, 0=기간만료
    """
    op, hi, lo, cl = (px["Open"].to_numpy(), px["High"].to_numpy(),
                      px["Low"].to_numpy(), px["Close"].to_numpy())
    n = len(px)
    out = []
    for i in entries:
        j0 = i + 1
        if j0 >= n:
            continue
        ep = op[j0] * (1 + FEE)
        if not np.isfinite(ep) or ep <= 0:
            continue
        end = min(j0 + maxhold, n)
        seg_hi, seg_lo = hi[j0:end], lo[j0:end]
        if len(seg_hi) == 0:
            continue
        tp_px = ep * (1 + tp)
        hit_tp = seg_hi >= tp_px
        k_tp = int(np.argmax(hit_tp)) if hit_tp.any() else -1
        k_sl = -1
        if sl is not None:
            hit_sl = seg_lo <= ep * (1 - sl)
            k_sl = int(np.argmax(hit_sl)) if hit_sl.any() else -1

        if k_sl >= 0 and (k_tp < 0 or k_sl <= k_tp):
            k, code, exit_px = k_sl, -1, ep * (1 - sl)
        elif k_tp >= 0:
            k, code, exit_px = k_tp, 1, tp_px
        else:
            k, code, exit_px = len(seg_hi) - 1, 0, cl[j0 + len(seg_hi) - 1]
        mae = (seg_lo[: k + 1].min() / ep - 1) * 100
        out.append(((exit_px * (1 - FEE) / ep - 1) * 100, k + 1, code, mae))
    return out


def summarize(rows: list, label: str, cfg: str) -> dict:
    if not rows:
        return {}
    r = np.array([x[0] for x in rows])
    d = np.array([x[1] for x in rows], dtype=float)
    c = np.array([x[2] for x in rows])
    mae = np.array([x[3] for x in rows])
    win, stop, timeout = c == 1, c == -1, c == 0
    rec = {
        "설정": cfg, "대상": label, "건수": len(r),
        "목표도달%": round(win.mean() * 100, 1),
        "손절%": round(stop.mean() * 100, 1),
        "만료%": round(timeout.mean() * 100, 1),
        "도달소요일": round(d[win].mean(), 0) if win.any() else np.nan,
        "만료시수익%": round(r[timeout].mean(), 2) if timeout.any() else np.nan,
        "평균수익%": round(r.mean(), 2),
        "평균보유일": round(d.mean(), 0),
        "연환산%": round(r.mean() / d.mean() * 252, 1),
        "평균MAE%": round(mae.mean(), 1),
        "도달건MAE%": round(mae[win].mean(), 1) if win.any() else np.nan,
    }
    return rec


SIGNALS = {
    "① 골든크로스": lambda d: d["below200"] & d["golden"],
    "③ 히스토 2일상승": lambda d: d["below200"] & d["histUp2"],
    "④ 음수인데 상승": lambda d: d["below200"] & d["histUpNeg"],
    "비교군 MA200아래": lambda d: d["below200"],
    "α 강세 눌림목": lambda d: d["alpha"],
    "β 급락 과매도": lambda d: d["beta"],
    "비교군 전체": lambda d: pd.Series(True, index=d.index),
}

CONFIGS = [
    ("+10% 익절 / 손절없음 / 60일", 0.10, None, 60),
    ("+10% 익절 / 손절없음 / 250일", 0.10, None, 250),
    ("+10% 익절 / -10% 손절 / 60일", 0.10, 0.10, 60),
    ("+10% 익절 / -10% 손절 / 250일", 0.10, 0.10, 250),
    ("+20% 익절 / -10% 손절 / 250일", 0.20, 0.10, 250),
    ("+20% 익절 / 손절없음 / 250일", 0.20, None, 250),
]


def main():
    pd.set_option("display.width", 340)
    pd.set_option("display.max_columns", 40)
    rng = np.random.default_rng(SEED)

    data = {}
    for t in UNIVERSE:
        d = prep(t)
        if d is not None:
            data[t] = d
    print(f"종목 {len(data)}개 로드")

    idx = {}
    for name, fn in SIGNALS.items():
        per = {}
        for t, d in data.items():
            e = np.flatnonzero(fn(d).to_numpy())
            if name.startswith("비교군") and len(e) > BASE_SAMPLE / len(data):
                e = rng.choice(e, size=int(BASE_SAMPLE / len(data)), replace=False)
            per[t] = np.sort(e)
        idx[name] = per

    rows = []
    for cfg, tp, sl, hold in CONFIGS:
        for name, per in idx.items():
            acc = []
            for t, e in per.items():
                if len(e):
                    acc.extend(walk(data[t], e, tp, sl, hold))
            rec = summarize(acc, name, cfg)
            if rec:
                rows.append(rec)
    t = pd.DataFrame(rows)
    t.to_csv(os.path.join(OUT_DIR, "barrier_exit.csv"), index=False)

    for cfg, *_ in CONFIGS:
        print(f"\n[{cfg}]")
        sub = t[t["설정"] == cfg].drop(columns=["설정"])
        print(sub.to_string(index=False))

    print("\n[핵심 비교 — 신호 vs 비교군 차이]")
    base_of = {n: ("비교군 전체" if n in ("α 강세 눌림목", "β 급락 과매도")
                   else "비교군 MA200아래") for n in SIGNALS}
    piv = []
    for cfg, *_ in CONFIGS:
        s = t[t["설정"] == cfg].set_index("대상")
        for name in SIGNALS:
            if name.startswith("비교군") or name not in s.index:
                continue
            b, r = s.loc[base_of[name]], s.loc[name]
            piv.append({
                "설정": cfg, "신호": name,
                "도달률차%p": round(r["목표도달%"] - b["목표도달%"], 1),
                "소요일차": round(r["도달소요일"] - b["도달소요일"], 0),
                "연환산차%p": round(r["연환산%"] - b["연환산%"], 1),
                "MAE차%p": round(r["평균MAE%"] - b["평균MAE%"], 1),
            })
    print(pd.DataFrame(piv).to_string(index=False))


if __name__ == "__main__":
    main()
