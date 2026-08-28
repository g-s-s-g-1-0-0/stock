"""Time-based bounce confirmation instead of a price stop.

The washout entry claims the name bounces from here. Give it N sessions to get
back to the entry price. Fail that and the claim was wrong -- exit, then let the
existing re-entry gate decide when to try again. Pass it and there is no profit
target: hold until the market-level exit fires, as Strategy 1 and 2 do.

Unlike a -3% stop this does not depend on the name's volatility, so a quiet
name and a wild one get the same test.

  recover:N:pure     confirmation window N, then recovery-end / peak / -30%
  recover:N:regime   the same plus 횡보장 고점 종가 청산 after confirmation
"""

from __future__ import annotations

import pandas as pd

from quant import config, legacy_backtest, legacy_run, sp500_data, strategy3_exit

WINDOWS = (2, 3, 5, 10)
OUT = f"{config.__file__.rsplit('/', 1)[0]}/out"


def _row(label: str, ledger: pd.DataFrame) -> dict:
    summary = strategy3_exit.summarize(ledger, label)
    book = strategy3_exit.portfolio(ledger)
    closed = ledger[~ledger["censored"]]
    failed = closed["exitReason"].eq("noBounce")
    rets = closed["retNet"].sort_values(ascending=False)
    total = rets.sum()
    return {
        "policy": label,
        "trades": summary["trades"],
        "mean%": summary["mean%"],
        "median%": summary["median%"],
        "win%": summary["win%"],
        "hold": summary["hold"],
        "worst%": summary["worst%"],
        "excess%": summary.get("excess%"),
        "미반등청산%": failed.mean() * 100,
        "미반등평균%": closed.loc[failed, "retNet"].mean() * 100,
        "반등평균%": closed.loc[~failed, "retNet"].mean() * 100,
        "top5%비중": rets.head(max(1, len(rets) // 20)).sum() / total * 100 if total else float("nan"),
        "taken": book.get("taken"),
        "total%": book.get("total%"),
        "CAGR%": book.get("CAGR%"),
        "MDD%": book.get("MDD%"),
    }


def main() -> None:
    panels, growth = sp500_data.build()
    state = legacy_run.build_state()
    signals = strategy3_exit.build_signals(panels, state)
    print(f"signals: {sum(int(s.sum()) for s in signals[0].values())}")

    rows = [
        _row(
            "기준: 현행 +12/-12/20일/횡보장고점",
            strategy3_exit.build_ledger(panels, state, "native", growth, signals=signals),
        ),
        _row(
            "참고: -3% 손절 + 횡보장고점",
            strategy3_exit.build_ledger(panels, state, "tightreg:0.03", growth, signals=signals),
        ),
    ]
    keep: dict[str, pd.DataFrame] = {}
    for window in WINDOWS:
        for kind, label in (
            ("pure", "1·2식 시장청산만"),
            ("regime", "+횡보장고점"),
            ("regimestop", "+횡보장고점+-12%손절"),
        ):
            ledger = strategy3_exit.build_ledger(
                panels, state, f"recover:{window}:{kind}", growth, signals=signals
            )
            if ledger.empty:
                continue
            name = f"{window}거래일 내 진입가 회복 · {label}"
            rows.append(_row(name, ledger))
            keep[name] = ledger

    print("\n" + "=" * 132)
    print("Strategy 3: 진입가 회복 확인 청산 / point-in-time S&P 500")
    print("=" * 132)
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    for name in ("3거래일 내 진입가 회복 · +횡보장고점", "3거래일 내 진입가 회복 · 1·2식 시장청산만"):
        if name not in keep:
            continue
        ledger = keep[name]
        slug = "regime" if "횡보장" in name else "pure"
        ledger.to_csv(f"{OUT}/ledger_s3_recover3_{slug}.csv", index=False)
        closed = ledger[~ledger["censored"]]
        print(f"\n--- {name}: 청산 사유 ---")
        for reason, count in closed["exitReason"].value_counts().items():
            window = closed[closed["exitReason"] == reason]
            print(
                f"  {reason:<13} {count:>6} ({count / len(closed) * 100:4.1f}%)  "
                f"mean {window['retNet'].mean() * 100:7.2f}%  hold {window['daysHeld'].mean():6.1f}"
            )
        print("\n--- 시대별 ---")
        print(legacy_backtest.eras(ledger).round(2).to_string(index=False))

    print(f"\nledger: {OUT}/ledger_s3_recover3_<variant>.csv")


if __name__ == "__main__":
    main()
