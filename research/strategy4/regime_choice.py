"""'정상장에서도 먹히는 전략 하나'를 고르기 위한 국면별 비교.

전략 1·2만 쓰면 대기 기간이 길다는 게 출발점이다. 그러면 판단 기준은
'전체 성적'이 아니라 두 가지여야 한다.

  (1) 정상장에서 신호가 얼마나 자주 나오는가 (대기 기간)
  (2) 정상장에서만 잘라도 성적이 유지되는가

전체 성적 1위가 정상장 1위가 아닐 수 있다. R2는 하락장 신호가 대부분이라
정상장 공백을 메우지 못할 가능성이 크다. 그걸 숫자로 확인한다.
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

from ma200_macd_golden import OUT_DIR, REGIME_ORDER, build_qqq_state
from washout_rules import build, market_frame
from strategy_compare import attach, masks, trades

TP, SL, MAXHOLD = 0.10, 0.10, 60


def with_regime(p: pd.DataFrame, qstate: pd.DataFrame) -> pd.DataFrame:
    q = qstate.rename_axis("date").reset_index()[["date", "regime"]]
    return p.merge(q, on="date", how="left")


def regime_days(qstate: pd.DataFrame) -> pd.Series:
    """국면별 총 거래일 수."""
    return qstate["regime"].value_counts()


def wait_table(p: pd.DataFrame, ms: dict, days: pd.Series) -> pd.DataFrame:
    """국면별로 '신호가 뜨는 날'이 얼마나 자주 오는지 = 대기 기간."""
    rows = []
    for name, m in ms.items():
        sub = p[m.fillna(False)]
        rec = {"전략": name}
        for r in REGIME_ORDER:
            sig_days = sub.loc[sub["regime"] == r, "date"].nunique()
            total = int(days.get(r, 0))
            if total == 0:
                rec[r] = "-"
                continue
            rate = sig_days / total
            rec[r] = f"{rate * 100:.1f}% ({1 / rate:.0f}일마다)" if rate > 0 else "없음"
        rows.append(rec)
    return pd.DataFrame(rows)


def regime_perf(p: pd.DataFrame, prices: dict, ms: dict,
                target: str) -> pd.DataFrame:
    rows = []
    for name, m in ms.items():
        mm = m.fillna(False) & (p["regime"] == target)
        tr = trades(p, prices, mm, TP, SL, MAXHOLD)
        if len(tr) < 40:
            continue
        win = tr["code"] == 1
        rows.append({
            "전략": name, "거래": len(tr),
            "달성률%": round(win.mean() * 100, 1),
            "손절률%": round((tr["code"] == -1).mean() * 100, 1),
            "달성중앙일": int(np.median(tr.loc[win, "days"])) if win.any() else np.nan,
            "평균보유일": round(tr["days"].mean(), 1),
            "평균손익%": round(tr["ret"].mean(), 2),
            "연환산%": round(tr["ret"].mean() / tr["days"].mean() * 252, 1),
            "신호일수": tr["date"].nunique(),
        })
    return pd.DataFrame(rows).sort_values("연환산%", ascending=False)


def gap_distribution(p: pd.DataFrame, ms: dict, qstate: pd.DataFrame) -> pd.DataFrame:
    """전략별로 신호와 신호 사이 공백이 실제로 얼마나 길었는지."""
    cal = qstate.index
    rows = []
    for name, m in ms.items():
        d = np.sort(p.loc[m.fillna(False), "date"].unique())
        if len(d) < 20:
            continue
        pos = pd.Series(np.arange(len(cal)), index=cal)
        idx = pos.reindex(pd.DatetimeIndex(d)).dropna().to_numpy()
        gaps = np.diff(np.unique(idx))
        rows.append({"전략": name, "신호일수": len(np.unique(idx)),
                     "평균공백일": round(gaps.mean(), 1),
                     "중앙공백": int(np.median(gaps)),
                     "90%공백": int(np.percentile(gaps, 90)),
                     "최장공백": int(gaps.max())})
    return pd.DataFrame(rows).sort_values("평균공백일")


def main():
    pd.set_option("display.width", 400)
    pd.set_option("display.max_columns", 50)
    qstate = build_qqq_state()
    p, prices = build(market_frame())
    p = with_regime(attach(p), qstate)
    ms = masks(p)
    days = regime_days(qstate)

    print("국면별 거래일 수:", dict(days))

    print("\n" + "=" * 150)
    print("국면별 신호 발생 빈도 — 얼마나 기다려야 하는가")
    print("=" * 150)
    print(wait_table(p, ms, days).to_string(index=False))

    print("\n" + "=" * 150)
    print("신호 공백 분포 (전 구간, 137종목 중 하나라도 뜨면 대기 종료)")
    print("=" * 150)
    print(gap_distribution(p, ms, qstate).to_string(index=False))

    for target in ("정상장", "횡보장 고점", "하락장", "회복장"):
        print("\n" + "=" * 150)
        print(f"[{target}] 성적 — +{TP:.0%} 익절 / -{SL:.0%} 손절 / 최대 {MAXHOLD}일")
        print("=" * 150)
        t = regime_perf(p, prices, ms, target)
        print(t.to_string(index=False))
        t.to_csv(os.path.join(OUT_DIR, f"regime_{target}.csv"), index=False)


if __name__ == "__main__":
    main()
