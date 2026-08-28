"""Run strategies through the shared engine and print the full report set."""

from __future__ import annotations

import argparse
import os
import time

import pandas as pd

from quant import config, data, engine, features, metrics, strategies

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
BARRIERS = {
    "SW3_washout": config.SWING,
    "SW1_momentum": config.SWING,
    "SW2_squeeze": config.SWING,
    "DT1_oversold": config.DAY,
    "DT2_gap": config.DAY,
    "DT3_gap_continuation_proxy": config.DAY,
}


def prepare() -> tuple[dict[str, pd.DataFrame], data.UniverseGrowth]:
    started = time.time()
    bars = data.load_bars()
    print(f"loaded {len(bars)} US tickers from .bt_cache in {time.time() - started:.1f}s")
    growth = data.UniverseGrowth(data.universe_mean_return(bars))

    started = time.time()
    panels = features.build_panels(bars)
    panels = engine.attach_context(panels, features.market_features())
    print(f"built feature panels in {time.time() - started:.1f}s")

    spans = [(f.index[0], f.index[-1]) for f in bars.values()]
    print(f"coverage {min(s for s, _ in spans).date()} .. {max(e for _, e in spans).date()}")
    return panels, growth


def _show(title: str, frame) -> None:
    print(f"\n--- {title} ---")
    if isinstance(frame, pd.Series):
        print(frame.round(2).to_string())
    elif frame is None or len(frame) == 0:
        print("(empty)")
    else:
        print(frame.round(2).to_string())


def run_strategy(
    name: str,
    panels: dict[str, pd.DataFrame],
    growth: data.UniverseGrowth,
    exit_policy: str = "barrier",
    entry_modes: tuple[str, ...] = ("nextOpen", "limitPullback"),
) -> dict[str, pd.DataFrame]:
    signals = strategies.REGISTRY[name](panels)
    total = sum(int(table["signal"].sum()) for table in signals.values())
    print(f"\n{'=' * 78}\n{name} / exit={exit_policy}: {total} raw signals\n{'=' * 78}")

    ledgers = {}
    for mode in entry_modes:
        ledger = engine.build_ledger(
            panels,
            signals,
            BARRIERS[name],
            name,
            entry_mode=mode,
            exit_policy=exit_policy,
            universe_growth=growth,
        )
        ledgers[mode] = ledger
        os.makedirs(OUT_DIR, exist_ok=True)
        ledger.to_csv(os.path.join(OUT_DIR, f"ledger_{name}_{exit_policy}_{mode}.csv"), index=False)
        _show(f"{name} / {mode} / headline", metrics.headline(ledger))

    primary = ledgers[entry_modes[0]]
    _show("strength quintile", metrics.by_strength_decile(primary))
    _show("era split", metrics.by_era(primary))
    _show("realized distribution", metrics.distribution(primary))
    _show("top tickers by contribution", metrics.concentration(primary))
    print(f"\nbarrier ambiguity: {metrics.ambiguity_verdict(primary)}")
    return ledgers


def compare_exits(
    name: str, panels: dict[str, pd.DataFrame], growth: data.UniverseGrowth
) -> pd.DataFrame:
    """Same signals and same entries, different ways of getting out.

    Isolates how much of the available excursion each exit policy converts
    into realized profit.
    """
    signals = strategies.REGISTRY[name](panels)
    rows = {}
    for policy in config.EXIT_POLICIES:
        ledger = engine.build_ledger(
            panels,
            signals,
            BARRIERS[name],
            name,
            entry_mode="nextOpen",
            exit_policy=policy,
            universe_growth=growth,
        )
        summary = metrics.headline(ledger)
        rows[policy] = summary
        ledger.to_csv(os.path.join(OUT_DIR, f"ledger_{name}_exit_{policy}.csv"), index=False)

    table = pd.DataFrame(rows).T
    keep = [
        "trades", "realizedMean%", "realizedMedian%", "mfeHoldMean%", "winRate%",
        "payoff", "stopHit%", "daysHeldMean", "realizedP10%", "worst%",
        "universeMean%", "excessMean%",
    ]
    table = table[[column for column in keep if column in table.columns]]
    table["captureOfMfe%"] = table["realizedMean%"] / table["mfeHoldMean%"] * 100
    return table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategies", nargs="*", default=list(strategies.REGISTRY))
    parser.add_argument("--compare-exits", action="store_true")
    parser.add_argument("--exit-policy", default="barrier", choices=list(config.EXIT_POLICIES))
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    panels, growth = prepare()
    for name in args.strategies:
        if args.compare_exits:
            print(f"\n{'=' * 78}\n{name}: exit policy comparison\n{'=' * 78}")
            _show("exit policies (identical signals and entries)", compare_exits(name, panels, growth))
        else:
            run_strategy(name, panels, growth, exit_policy=args.exit_policy)
    print(f"\nledgers written to {OUT_DIR}")


if __name__ == "__main__":
    main()
