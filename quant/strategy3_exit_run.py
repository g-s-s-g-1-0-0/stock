"""Price the Strategy 3 exit swap on the point-in-time S&P 500.

Same entries, same fills, four exit policies:
  native            +12% / -12% / 20 sessions / 횡보장 고점   (shipped)
  market            recovery-end / peak alert / -30% circuit  (Strategy 1·2 style)
  market_keep_stop  Strategy 1·2 exits but keeps the -12% stop
  market_regime     Strategy 1·2 exits plus the 횡보장 고점 close
"""

from __future__ import annotations

import pandas as pd

from quant import config, legacy_backtest, legacy_run, sp500_data, strategy3_exit

POLICIES = {
    "native": "현행 +12/-12/20일/횡보장고점",
    "no_target": "익절만 제거 (-12% 손절·20일·횡보장고점 유지)",
    "no_target_no_cap": "익절·시간청산 제거 (-12% 손절·횡보장고점·회복장종료)",
    "market": "전략1·2식 시장청산 (회복장종료·peak·-30%)",
    "market_keep_stop": "시장청산 + -12% 손절 유지",
    "market_regime": "시장청산 + 횡보장 고점 청산",
}

OUT = f"{config.__file__.rsplit('/', 1)[0]}/out"


def _exit_mix(ledger: pd.DataFrame) -> None:
    closed = ledger[~ledger["censored"]]
    if closed.empty:
        return
    counts = closed["exitReason"].value_counts()
    for reason, count in counts.items():
        window = closed[closed["exitReason"] == reason]
        print(
            f"    {reason:<13} {count:>5} ({count / len(closed) * 100:4.1f}%)  "
            f"mean {window['retNet'].mean() * 100:6.2f}%  "
            f"hold {window['daysHeld'].mean():6.1f}"
        )


def main() -> None:
    panels, growth = sp500_data.build()
    state = legacy_run.build_state()
    labels = strategy3_exit.regime_labels(state)
    print(f"market state: {state.index[0].date()} .. {state.index[-1].date()}")
    print("regime days: " + ", ".join(f"{k} {v}" for k, v in labels.value_counts().items()))

    signals = strategy3_exit.build_signals(panels, state)
    entries, _ = signals
    total = int(sum(int(s.sum()) for s in entries.values()))
    print(f"strategy 3 signals: {total} across {sum(1 for s in entries.values() if s.any())} names")

    rows, annual, book, ledgers = [], [], [], {}
    for policy, label in POLICIES.items():
        ledger = strategy3_exit.build_ledger(panels, state, policy, growth, signals=signals)
        if ledger.empty:
            print(f"\n{policy}: no trades")
            continue
        ledgers[policy] = ledger
        ledger.to_csv(f"{OUT}/ledger_s3_{policy}.csv", index=False)
        rows.append(strategy3_exit.summarize(ledger, label))
        annual.append({"policy": label, **strategy3_exit.annualized(ledger)})
        book.append({"policy": label, **strategy3_exit.portfolio(ledger)})

    print("\n" + "=" * 100)
    print("Strategy 3 exit policies / point-in-time S&P 500")
    print("=" * 100)
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n--- capital speed (per held session) ---")
    print(pd.DataFrame(annual).round(2).to_string(index=False))

    print("\n--- 5-slot portfolio (capacity-constrained, realized-trade equity) ---")
    print(pd.DataFrame(book).round(2).to_string(index=False))

    print("\n--- stop-loss sweep (익절·시간청산 없음, 횡보장고점·회복장종료 유지) ---")
    sweep = []
    for stop in (0.12, 0.15, 0.18, 0.20, 0.25, 0.30):
        led = strategy3_exit.build_ledger(
            panels, state, f"stop:{stop}", growth, signals=signals
        )
        if led.empty:
            continue
        sweep.append(
            {
                "stop%": -stop * 100,
                **{
                    k: v
                    for k, v in strategy3_exit.summarize(led, f"-{stop * 100:.0f}%").items()
                    if k in ("trades", "mean%", "win%", "hold", "excess%")
                },
                **strategy3_exit.annualized(led),
                **{
                    k: v
                    for k, v in strategy3_exit.portfolio(led).items()
                    if k in ("total%", "CAGR%", "MDD%")
                },
            }
        )
    print(pd.DataFrame(sweep).round(2).to_string(index=False))

    span = pd.concat([led[~led["censored"]] for led in ledgers.values()])
    start, end = span["entryDate"].min(), span["exitDate"].max()
    held = growth.between(start, end)
    years = (end - start).days / 365.25
    print(
        f"\nbuy-and-hold equal-weight universe {start.date()}..{end.date()}: "
        f"total {held * 100:.2f}%  CAGR {((1 + held) ** (1 / years) - 1) * 100:.2f}%"
    )

    for policy, ledger in ledgers.items():
        print(f"\n--- exit mix: {POLICIES[policy]} ---")
        _exit_mix(ledger)

    print("\n--- by era (mean net / excess) ---")
    frames = []
    for policy, ledger in ledgers.items():
        era = legacy_backtest.eras(ledger)
        if era.empty:
            continue
        era.insert(0, "policy", POLICIES[policy])
        frames.append(era[["policy", "era", "trades", "meanRet%", "winRate%", "meanHold", "excess%"]])
    if frames:
        print(pd.concat(frames).round(2).to_string(index=False))

    print(f"\nledgers: {OUT}/ledger_s3_<policy>.csv")


if __name__ == "__main__":
    main()
