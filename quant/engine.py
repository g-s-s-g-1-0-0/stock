"""Fill model, exit simulation and the trade ledger.

The ledger is the single source of truth. Every summary statistic in this
package is derived from it, so any reported number can be traced back to the
individual trades that produced it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config
from quant.config import Barriers

ENTRY_MODES = ("nextOpen", "limitPullback")


def _slippage(atr_pct: float) -> float:
    scaled = config.SLIPPAGE_ATR_FRACTION * atr_pct * 10_000.0
    return max(config.SLIPPAGE_MIN_BPS, scaled) / 10_000.0


def _resolve_entry(
    arrays: dict[str, np.ndarray],
    signal_index: int,
    atr_pct: float,
    mode: str,
) -> tuple[int | None, float]:
    """Return the entry bar and executed price, or ``None`` when unfilled."""
    entry_index = signal_index + 1
    if entry_index >= len(arrays["open"]):
        return None, np.nan

    if mode == "nextOpen":
        price = arrays["open"][entry_index] * (1 + _slippage(atr_pct))
        return entry_index, price

    limit = arrays["close"][signal_index] * (1 - 0.5 * atr_pct)
    if arrays["low"][entry_index] > limit:
        return None, np.nan
    return entry_index, min(arrays["open"][entry_index], limit)


def _net(entry_price: float, exit_price: float) -> float:
    fee = config.FEE_BPS / 10_000.0
    return (exit_price * (1 - fee)) / (entry_price * (1 + fee)) - 1.0


def _result(
    entry_price: float,
    exit_index: int,
    entry_index: int,
    exit_price: float,
    reason: str,
    ambiguous: bool,
    run_high: float,
    run_low: float,
    net_override: float | None = None,
) -> dict[str, object]:
    net = _net(entry_price, exit_price) if net_override is None else net_override
    return {
        "reason": reason,
        "exitIndex": exit_index,
        "exitPrice": exit_price,
        "retGross": exit_price / entry_price - 1.0,
        "retNet": net,
        "ambiguous": ambiguous,
        "daysHeld": exit_index - entry_index + 1,
        "mfeToExit": run_high / entry_price - 1.0,
        "maeToExit": run_low / entry_price - 1.0,
    }


def _simulate(
    arrays: dict[str, np.ndarray],
    entry_index: int,
    entry_price: float,
    atr_pct: float,
    bar: Barriers,
    tie: str,
    policy: config.ExitPolicy,
) -> dict[str, object]:
    """Walk bars forward until the exit policy closes the trade.

    ``tie`` decides the outcome when one daily bar touches both a target and a
    stop. That order is unknowable from daily data, so both branches are run
    and reported instead of silently picking the pessimistic one.
    """
    high, low, close = arrays["high"], arrays["low"], arrays["close"]
    last_index = entry_index + bar.max_hold - 1
    if last_index >= len(close):
        return {"reason": "censored"}

    slip = _slippage(atr_pct)
    atr_price = entry_price if bar.absolute else entry_price * atr_pct
    stop_price = entry_price - bar.stop_atr * atr_price
    target_price = entry_price + bar.target_atr * atr_price
    partial_price = entry_price + policy.partial_at_atr * atr_price

    run_high, run_low = -np.inf, np.inf
    ambiguous = False
    activated = False
    partial_done = False
    partial_net = 0.0

    for j in range(entry_index, last_index + 1):
        hit_stop = low[j] <= stop_price
        hit_target = high[j] >= target_price
        hit_partial = high[j] >= partial_price

        if policy.kind == "barrier":
            if hit_stop and hit_target:
                ambiguous = True
                take_stop = tie == "stop"
            elif hit_stop or hit_target:
                take_stop = hit_stop
            else:
                run_high, run_low = max(run_high, high[j]), min(run_low, low[j])
                continue
            run_high, run_low = max(run_high, high[j]), min(run_low, low[j])
            price = stop_price * (1 - slip) if take_stop else target_price
            return _result(
                entry_price, j, entry_index, price,
                "stop" if take_stop else "target", ambiguous, run_high, run_low,
            )

        if policy.kind == "trail":
            if hit_stop:
                run_high, run_low = max(run_high, high[j]), min(run_low, low[j])
                return _result(
                    entry_price, j, entry_index, stop_price * (1 - slip),
                    "trail" if activated else "stop", False, run_high, run_low,
                )
            run_high, run_low = max(run_high, high[j]), min(run_low, low[j])
            if run_high >= entry_price + policy.activate_atr * atr_price:
                activated = True
            if activated:
                stop_price = max(stop_price, run_high - policy.trail_atr * atr_price)
            continue

        if policy.kind == "partial":
            if not partial_done:
                if hit_stop and hit_partial:
                    ambiguous = True
                    take_stop = tie == "stop"
                elif hit_stop or hit_partial:
                    take_stop = hit_stop
                else:
                    run_high, run_low = max(run_high, high[j]), min(run_low, low[j])
                    continue
                run_high, run_low = max(run_high, high[j]), min(run_low, low[j])
                if take_stop:
                    return _result(
                        entry_price, j, entry_index, stop_price * (1 - slip),
                        "stop", ambiguous, run_high, run_low,
                    )
                partial_done = True
                partial_net = policy.partial_fraction * _net(entry_price, partial_price)
                stop_price = entry_price
                activated = True
                stop_price = max(stop_price, run_high - policy.trail_atr * atr_price)
                continue

            if hit_stop:
                run_high, run_low = max(run_high, high[j]), min(run_low, low[j])
                rest = (1 - policy.partial_fraction) * _net(entry_price, stop_price * (1 - slip))
                return _result(
                    entry_price, j, entry_index, stop_price * (1 - slip),
                    "partialThenTrail", ambiguous, run_high, run_low,
                    net_override=partial_net + rest,
                )
            run_high, run_low = max(run_high, high[j]), min(run_low, low[j])
            stop_price = max(stop_price, run_high - policy.trail_atr * atr_price)
            continue

        run_high, run_low = max(run_high, high[j]), min(run_low, low[j])

    final_price = close[last_index] * (1 - slip)
    if policy.kind == "partial" and partial_done:
        rest = (1 - policy.partial_fraction) * _net(entry_price, final_price)
        return _result(
            entry_price, last_index, entry_index, final_price, "partialThenTime",
            ambiguous, run_high, run_low, net_override=partial_net + rest,
        )
    return _result(
        entry_price, last_index, entry_index, final_price, "time",
        ambiguous, run_high, run_low,
    )


def _hold_window(
    arrays: dict[str, np.ndarray], entry_index: int, entry_price: float, bar: Barriers
) -> dict[str, float]:
    """Buy-and-hold reference over the same window, ignoring barriers.

    This is the number a discretionary trader remembers seeing on screen, so
    it must be reported next to the realized return rather than buried.
    """
    last_index = min(entry_index + bar.max_hold - 1, len(arrays["close"]) - 1)
    window = slice(entry_index, last_index + 1)
    return {
        "mfeHold": arrays["high"][window].max() / entry_price - 1.0,
        "maeHold": arrays["low"][window].min() / entry_price - 1.0,
        "mfeHoldDay": int(np.argmax(arrays["high"][window])) + 1,
        "retHoldEnd": arrays["close"][last_index] / entry_price - 1.0,
    }


def build_ledger(
    panels: dict[str, pd.DataFrame],
    signals: dict[str, pd.DataFrame],
    bar: Barriers,
    strategy: str,
    entry_mode: str = "nextOpen",
    exit_policy: str = "barrier",
    universe_growth=None,
    context_columns: tuple[str, ...] = (
        "rsi14",
        "adx14",
        "atrPct",
        "bbWidth",
        "distHigh52",
        "volRatio20",
        "qqqPremium",
        "vix",
    ),
) -> pd.DataFrame:
    """Turn per-ticker signal masks into one row per trade.

    ``signals[ticker]`` must contain a boolean ``signal`` column and a numeric
    ``strength`` column. Signals are de-duplicated into episodes so a single
    ticker never holds two overlapping positions.
    """
    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"unknown entry mode: {entry_mode}")
    policy = config.EXIT_POLICIES[exit_policy]

    rows: list[dict[str, object]] = []
    for ticker, panel in panels.items():
        table = signals.get(ticker)
        if table is None or not table["signal"].any():
            continue

        arrays = {
            "open": panel["Open"].to_numpy(float),
            "high": panel["High"].to_numpy(float),
            "low": panel["Low"].to_numpy(float),
            "close": panel["Close"].to_numpy(float),
        }
        atr_pct_all = panel["atrPct"].to_numpy(float)
        positions = np.flatnonzero(table["signal"].to_numpy(bool))
        strength_all = table["strength"].to_numpy(float)
        blocked_until = -1

        for signal_index in positions:
            atr_pct = atr_pct_all[signal_index]
            if not np.isfinite(atr_pct) or atr_pct <= 0:
                continue

            entry_index, entry_price = _resolve_entry(arrays, signal_index, atr_pct, entry_mode)
            if entry_index is None or not np.isfinite(entry_price) or entry_price <= 0:
                rows.append(
                    {
                        "strategy": strategy,
                        "ticker": ticker,
                        "signalDate": panel.index[signal_index],
                        "entryMode": entry_mode,
                        "filled": False,
                        "strength": strength_all[signal_index],
                    }
                )
                continue

            pessimistic = _simulate(
                arrays, entry_index, entry_price, atr_pct, bar, "stop", policy
            )
            if pessimistic["reason"] == "censored":
                rows.append(
                    {
                        "strategy": strategy,
                        "ticker": ticker,
                        "signalDate": panel.index[signal_index],
                        "entryMode": entry_mode,
                        "filled": True,
                        "censored": True,
                        "strength": strength_all[signal_index],
                    }
                )
                continue
            optimistic = _simulate(
                arrays, entry_index, entry_price, atr_pct, bar, "target", policy
            )

            dedup_kept = signal_index > blocked_until
            if dedup_kept:
                blocked_until = int(pessimistic["exitIndex"])

            row: dict[str, object] = {
                "strategy": strategy,
                "ticker": ticker,
                "signalDate": panel.index[signal_index],
                "entryDate": panel.index[entry_index],
                "entryPrice": entry_price,
                "entryMode": entry_mode,
                "exitPolicy": exit_policy,
                "filled": True,
                "censored": False,
                "exitDate": panel.index[int(pessimistic["exitIndex"])],
                "exitPrice": pessimistic["exitPrice"],
                "exitReason": pessimistic["reason"],
                "daysHeld": pessimistic["daysHeld"],
                "retGross": pessimistic["retGross"],
                "retNet": pessimistic["retNet"],
                "retPessimistic": pessimistic["retNet"],
                "retOptimistic": optimistic["retNet"],
                "barrierAmbiguous": bool(pessimistic["ambiguous"] or optimistic["ambiguous"]),
                "ambigResolvedBy": "unresolved" if pessimistic["ambiguous"] else "daily",
                "mfeToExit": pessimistic["mfeToExit"],
                "maeToExit": pessimistic["maeToExit"],
                "atrPctAtEntry": atr_pct,
                "targetPct": bar.target_atr * atr_pct,
                "stopPct": bar.stop_atr * atr_pct,
                "strength": strength_all[signal_index],
                "dedupKept": dedup_kept,
                "horizon": bar.label,
            }
            row.update(_hold_window(arrays, entry_index, entry_price, bar))

            fee = config.FEE_BPS / 10_000.0
            for step in config.CHECKPOINTS:
                index = entry_index + step - 1
                row[f"retN{step}"] = (
                    (arrays["close"][index] * (1 - fee)) / (entry_price * (1 + fee)) - 1.0
                    if index < len(arrays["close"])
                    else np.nan
                )

            for column in context_columns:
                if column in panel.columns:
                    row[column] = panel[column].iat[signal_index]

            if universe_growth is not None:
                row["universeRet"] = universe_growth.between(row["entryDate"], row["exitDate"])
                row["excessRet"] = row["retNet"] - row["universeRet"]
            rows.append(row)

    ledger = pd.DataFrame(rows)
    if not ledger.empty:
        ledger = ledger.sort_values(["signalDate", "ticker"]).reset_index(drop=True)
        ledger["year"] = pd.to_datetime(ledger["signalDate"]).dt.year
    return ledger


def attach_context(panels: dict[str, pd.DataFrame], market: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Broadcast market regime columns onto each ticker panel."""
    out = {}
    for ticker, panel in panels.items():
        merged = panel.copy()
        for column in ("qqqPremium", "qqqMa200Rising", "qqqRsi14", "vix"):
            merged[column] = (
                market[column].astype(float).reindex(merged.index).ffill(limit=5)
            )
        out[ticker] = merged
    return out
