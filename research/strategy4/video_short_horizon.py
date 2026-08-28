"""일봉에서도 단기 구간(1~5일)으로 영상 조건을 다시 본다.

앞선 검증은 20일 기준이었다. 영상이 단타라 보유기간을 짧게 잡으면 결과가
달라지는지 확인한다. 판정 기준은 동일하게 '같은 날 MA200 위 종목 평균 대비
초과수익'이다.
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

import ma200_macd_golden as base

base.FWD_HORIZONS = [1, 2, 3, 5, 10, 20]

import video_allinone as v  # noqa: E402

v.FWD_HORIZONS = base.FWD_HORIZONS

from backtest_qqq_block_v2 import UNIVERSE  # noqa: E402

FULL = v.VARIANTS[list(v.VARIANTS)[0]]


def main():
    pd.set_option("display.width", 300)
    qstate = base.build_qqq_state()
    panel, _ = v.build_panel({t: t for t in UNIVERSE}, qstate)
    p = v.add_excess(panel)
    print(f"패널 {p['date'].min().date()} ~ {p['date'].max().date()} / "
          f"{p['ticker'].nunique()}종목 / {len(p):,} 종목·일")

    sig = p[v.mask_of(p, FULL)]
    above = p[p["above200"]]
    print(f"\n영상 조건 신호 {len(sig):,}건 — 보유기간별 성적")
    rng = np.random.default_rng(0)
    rows = []
    for h in base.FWD_HORIZONS:
        s = sig[f"fwd{h}"].dropna()
        b = above[f"fwd{h}"].dropna()
        e = sig[["date", f"exAbove{h}"]].dropna()
        daily = e.groupby("date")[f"exAbove{h}"].mean().to_numpy()
        boot = np.array([rng.choice(daily, len(daily), replace=True).mean()
                         for _ in range(3000)])
        lo, hi = np.percentile(boot, [2.5, 97.5])
        rows.append({
            "보유": f"{h}일", "신호": len(s),
            "평균%": round(s.mean(), 3), "승률%": round((s > 0).mean() * 100, 1),
            "MA200위 평균%": round(b.mean(), 3),
            "초과%p": round(s.mean() - b.mean(), 3),
            "95%CI": f"{lo:+.2f}~{hi:+.2f}",
            "유의": "O" if (lo > 0 or hi < 0) else "-",
        })
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n[국면별 1일 / 3일 초과수익]")
    out = []
    for regime in base.REGIME_ORDER:
        s = sig[sig["regime"] == regime]
        if len(s) < 30:
            continue
        out.append({"국면": regime, "신호": len(s),
                    "1일 초과%p": round(s["exAbove1"].mean(), 3),
                    "3일 초과%p": round(s["exAbove3"].mean(), 3),
                    "5일 초과%p": round(s["exAbove5"].mean(), 3)})
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    main()
