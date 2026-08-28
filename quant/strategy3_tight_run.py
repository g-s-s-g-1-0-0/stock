"""Tight stop plus the Strategy 1·2 market exit, with re-entry in between.

The premise: the washout entry is a bet on tomorrow's bounce. If the name keeps
falling instead, the bet was wrong now -- cut it small and wait. The existing
re-entry gate (two settlement bars, then 3% below the last sell inside ten
sessions, plus a fresh Strategy 3 signal) decides when to try again. When a try
does bounce, nothing takes profit: the position rides until the market-level
exit fires, as in Strategy 1 and 2.

Two market-exit flavours, because Strategy 3 lives in 정상장 where the season
latch rarely closes:
  tight     recovery-end / peak alert only          (literally Strategy 1·2)
  tightreg  the same plus 횡보장 고점 종가 청산      (Strategy 3's own regime exit)
"""

from __future__ import annotations

import pandas as pd

from quant import config, legacy_run, sp500_data, strategy3_exit

STOPS = (0.02, 0.03, 0.04, 0.05, 0.08)
OUT = f"{config.__file__.rsplit('/', 1)[0]}/out"


def _row(label: str, ledger: pd.DataFrame) -> dict:
    summary = strategy3_exit.summarize(ledger, label)
    speed = strategy3_exit.annualized(ledger)
    book = strategy3_exit.portfolio(ledger)
    closed = ledger[~ledger["censored"]]
    stopped = closed["exitReason"].eq("tightStop")
    return {
        "policy": label,
        "trades": summary["trades"],
        "mean%": summary["mean%"],
        "win%": summary["win%"],
        "hold": summary["hold"],
        "worst%": summary["worst%"],
        "excess%": summary.get("excess%"),
        "손절비중%": stopped.mean() * 100,
        "손절외평균%": closed.loc[~stopped, "retNet"].mean() * 100,
        "excess/session bps": speed.get("excess/session bps"),
        "taken": book.get("taken"),
        "total%": book.get("total%"),
        "CAGR%": book.get("CAGR%"),
        "MDD%": book.get("MDD%"),
    }


def _reentry_stats(ledger: pd.DataFrame) -> pd.Series:
    """How often a name is re-tried after being stopped out."""
    closed = ledger[~ledger["censored"]].sort_values(["ticker", "entryDate"])
    counts = closed.groupby("ticker").size()
    return pd.Series(
        {
            "names traded": len(counts),
            "trades per name": counts.mean(),
            "max trades on one name": counts.max(),
        }
    )


def main() -> None:
    panels, growth = sp500_data.build()
    state = legacy_run.build_state()
    signals = strategy3_exit.build_signals(panels, state)
    print(f"signals: {sum(int(s.sum()) for s in signals[0].values())}")

    rows = [
        _row(
            "기준: 현행 +12/-12/20일/횡보장고점",
            strategy3_exit.build_ledger(panels, state, "native", growth, signals=signals),
        )
    ]
    keep: dict[str, pd.DataFrame] = {}
    for stop in STOPS:
        for kind, label in (("tight", "1·2식 시장청산만"), ("tightreg", "+횡보장고점")):
            ledger = strategy3_exit.build_ledger(
                panels, state, f"{kind}:{stop}", growth, signals=signals
            )
            if ledger.empty:
                continue
            name = f"손절 -{stop * 100:.0f}% · {label}"
            rows.append(_row(name, ledger))
            keep[name] = ledger

    print("\n" + "=" * 122)
    print("Strategy 3: 타이트 손절 + 시장청산 / point-in-time S&P 500")
    print("=" * 122)
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n--- 수익 집중도: 상위 트레이드가 전체 합계 손익에서 차지하는 비중 ---")
    conc = []
    for name in ("손절 -3% · 1·2식 시장청산만", "손절 -3% · +횡보장고점"):
        if name not in keep:
            continue
        rets = keep[name][~keep[name]["censored"]]["retNet"].sort_values(ascending=False)
        total = rets.sum()
        conc.append(
            {
                "policy": name,
                "trades": len(rets),
                "median%": rets.median() * 100,
                "top1% share": rets.head(max(1, len(rets) // 100)).sum() / total * 100,
                "top5% share": rets.head(max(1, len(rets) // 20)).sum() / total * 100,
                "손실 트레이드 비중%": rets.lt(0).mean() * 100,
            }
        )
    base = rows[0]
    print(pd.DataFrame(conc).round(1).to_string(index=False))
    print(f"  (기준 현행 청산: 승률 {base['win%']:.1f}%, 평균 {base['mean%']:.2f}%)")

    for name in ("손절 -3% · 1·2식 시장청산만", "손절 -3% · +횡보장고점"):
        if name in keep:
            slug = "pure" if "1·2" in name else "regime"
            keep[name].to_csv(f"{OUT}/ledger_s3_tight3_{slug}.csv", index=False)

    best = "손절 -3% · +횡보장고점"
    if best in keep:
        ledger = keep[best]
        ledger.to_csv(f"{OUT}/ledger_s3_tight3_regime.csv", index=False)
        print(f"\n--- {best}: 청산 사유 ---")
        closed = ledger[~ledger["censored"]]
        for reason, count in closed["exitReason"].value_counts().items():
            window = closed[closed["exitReason"] == reason]
            print(
                f"  {reason:<13} {count:>6} ({count / len(closed) * 100:4.1f}%)  "
                f"mean {window['retNet'].mean() * 100:7.2f}%  hold {window['daysHeld'].mean():6.1f}"
            )
        print("\n--- 재진입 빈도 ---")
        print(_reentry_stats(ledger).round(2).to_string())
        print("\n--- 시대별 ---")
        from quant import legacy_backtest

        print(legacy_backtest.eras(ledger).round(2).to_string(index=False))

    print(f"\nledger: {OUT}/ledger_s3_tight3_regime.csv")


if __name__ == "__main__":
    main()
