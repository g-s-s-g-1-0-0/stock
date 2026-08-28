"""Fair comparison of two exit policies: placebo matched on holding length.

The ledger's `excessRet` is measured against a daily-rebalanced equal-weight
basket, and that basket's rebalancing premium grows with the holding period. So
a policy that holds twice as long is charged twice the bias, and two policies
with the same reported excess are not equally good.

This replaces the basket with the only control that scales cleanly: on each
trade's own signal date, buy a random eligible single name and hold it for
exactly the same number of sessions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config, legacy_run, sp500_data, strategy3_exit

DRAWS = 3
SEED = 20260818
POLICIES = {
    "현행 +12/-12/20일/횡보장고점": "native",
    "3거래일 회복확인 + 횡보장고점": "recover:3:regime",
    "5거래일 회복확인 + 횡보장고점": "recover:5:regime",
    "-3% 손절 + 횡보장고점": "tightreg:0.03",
}


def _arrays(panels: dict[str, pd.DataFrame]) -> dict:
    fee = config.FEE_BPS / 10_000.0
    packed = {}
    for ticker, panel in panels.items():
        atr = panel["atrPct"].to_numpy(float)
        slip = np.maximum(
            config.SLIPPAGE_MIN_BPS, config.SLIPPAGE_ATR_FRACTION * atr * 10_000.0
        ) / 10_000.0
        packed[ticker] = {
            "index": {stamp: i for i, stamp in enumerate(panel.index)},
            "open": panel["Open"].to_numpy(float),
            "close": panel["Close"].to_numpy(float),
            "slip": slip,
            "eligible": panel["eligible"].to_numpy(bool),
        }
    return {"packed": packed, "fee": fee}


def _hold_return(pack: dict, fee: float, position: int, sessions: int) -> float:
    entry_index = position + 1
    exit_index = entry_index + sessions - 1
    if exit_index >= len(pack["close"]):
        return np.nan
    slip = pack["slip"][position]
    entry = pack["open"][entry_index] * (1 + slip)
    exit_ = pack["close"][exit_index] * (1 - slip)
    if not np.isfinite(entry) or entry <= 0 or not np.isfinite(exit_):
        return np.nan
    return exit_ / entry - 1.0 - 2 * fee


def matched_gap(ledger: pd.DataFrame, bundle: dict, draws: int = DRAWS) -> dict:
    """Mean trade return minus mean of same-date, same-length random holds."""
    rng = np.random.default_rng(SEED)
    packed, fee = bundle["packed"], bundle["fee"]
    pool: dict[pd.Timestamp, list[str]] = {}
    for ticker, pack in packed.items():
        for stamp, position in pack["index"].items():
            if pack["eligible"][position]:
                pool.setdefault(stamp, []).append(ticker)

    closed = ledger[~ledger["censored"]]
    signal, control = [], []
    for row in closed.itertuples():
        names = pool.get(row.signalDate)
        if not names:
            continue
        signal.append(row.retNet)
        for ticker in rng.choice(names, size=draws, replace=True):
            pack = packed[ticker]
            control.append(_hold_return(pack, fee, pack["index"][row.signalDate], row.daysHeld))

    signal_series = pd.Series(signal).dropna()
    control_series = pd.Series(control).dropna()
    gap = (signal_series.mean() - control_series.mean()) * 100
    pooled = np.sqrt(
        signal_series.var() / len(signal_series) + control_series.var() / len(control_series)
    ) * 100
    return {
        "trades": len(signal_series),
        "hold": closed["daysHeld"].mean(),
        "signal mean%": signal_series.mean() * 100,
        "matched placebo%": control_series.mean() * 100,
        "EW basket%": closed["universeRet"].mean() * 100,
        "gap vs placebo%p": gap,
        "t": gap / pooled if pooled > 0 else np.nan,
        "EW가 과대계상한 폭%p": (closed["universeRet"].mean() * 100) - control_series.mean() * 100,
    }


def main() -> None:
    panels, growth = sp500_data.build()
    state = legacy_run.build_state()
    signals = strategy3_exit.build_signals(panels, state)
    bundle = _arrays(panels)

    rows = []
    for label, policy in POLICIES.items():
        ledger = strategy3_exit.build_ledger(panels, state, policy, growth, signals=signals)
        if ledger.empty:
            continue
        rows.append({"policy": label, **matched_gap(ledger, bundle)})

    print("\n" + "=" * 124)
    print("보유기간을 맞춘 플라시보 대비 실제 초과수익")
    print("=" * 124)
    print(pd.DataFrame(rows).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
