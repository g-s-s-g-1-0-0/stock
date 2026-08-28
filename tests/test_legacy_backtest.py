"""Exit precedence and the re-entry cooldown decide most legacy trades.

Strategies 1 and 2 have no profit target, so a position is closed only by a
market-level event or the -30% circuit. Those branches are rare in real data
and would go unchecked in a full run, so they are driven directly here on
synthetic bars where the expected outcome is known by construction.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import legacy_backtest, legacy_strategies

BARS = 40
ATR_PCT = 0.0002
"""Small enough that slippage sits on its 2bp floor, keeping arithmetic exact."""


def _panel(closes: list[float]) -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=len(closes))
    close = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "atrPct": ATR_PCT,
            "eligible": True,
        },
        index=index,
    )


def _flat(index: pd.Index, **overrides) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "peakTriggered": False,
            "recoveryEnded": False,
            "blockNewEntries": False,
        },
        index=index,
    )
    for column, value in overrides.items():
        frame[column] = value
    return frame


def _entries(index: pd.Index, days: list[int], column: str = "entry1") -> pd.DataFrame:
    frame = pd.DataFrame({"entry1": False, "entry2": False}, index=index)
    frame.loc[index[days], column] = True
    return frame


def _run(panel, entries, market) -> list[dict]:
    return legacy_backtest.simulate_ticker("TEST", panel, entries, market)


def test_entry_fills_at_next_open():
    panel = _panel([100.0] * BARS)
    trades = _run(panel, _entries(panel.index, [5]), _flat(panel.index))
    assert len(trades) == 1
    assert trades[0]["signalDate"] == panel.index[5]
    assert trades[0]["entryDate"] == panel.index[6]


def test_no_profit_target_keeps_a_winner_open():
    """A +50% run must not close the trade; these rules have no target."""
    closes = [100.0] * 10 + [150.0] * (BARS - 10)
    panel = _panel(closes)
    trades = _run(panel, _entries(panel.index, [5]), _flat(panel.index))
    assert trades[0]["censored"] is True


def test_circuit_stop_exits_at_thirty_percent_loss():
    closes = [100.0] * 10 + [69.0] * (BARS - 10)
    panel = _panel(closes)
    trades = _run(panel, _entries(panel.index, [5]), _flat(panel.index))
    assert trades[0]["exitReason"] == "circuit"
    assert trades[0]["exitDate"] == panel.index[11]


def test_a_loss_short_of_the_circuit_stays_open():
    closes = [100.0] * 10 + [71.0] * (BARS - 10)
    panel = _panel(closes)
    trades = _run(panel, _entries(panel.index, [5]), _flat(panel.index))
    assert trades[0]["censored"] is True


def test_recovery_end_sells_a_profitable_position():
    panel = _panel([100.0] * 10 + [130.0] * (BARS - 10))
    market = _flat(panel.index)
    market.loc[panel.index[20], "recoveryEnded"] = True
    trades = _run(panel, _entries(panel.index, [5]), market)
    assert trades[0]["exitReason"] == "recoveryEnd"
    assert trades[0]["exitDate"] == panel.index[21]
    assert trades[0]["retNet"] > 0


def test_peak_alert_sells_the_position():
    panel = _panel([100.0] * BARS)
    market = _flat(panel.index)
    market.loc[panel.index[15], "peakTriggered"] = True
    trades = _run(panel, _entries(panel.index, [5]), market)
    assert trades[0]["exitReason"] == "peakAlert"
    assert trades[0]["exitDate"] == panel.index[16]


def test_recovery_end_outranks_the_peak_alert():
    """Both fire on the same bar; the service sells for the recovery end."""
    panel = _panel([100.0] * BARS)
    market = _flat(panel.index)
    market.loc[panel.index[15], ["recoveryEnded", "peakTriggered"]] = True
    trades = _run(panel, _entries(panel.index, [5]), market)
    assert trades[0]["exitReason"] == "recoveryEnd"


def test_peak_alert_blocks_a_new_entry():
    panel = _panel([100.0] * BARS)
    market = _flat(panel.index, peakTriggered=True)
    assert _run(panel, _entries(panel.index, [5]), market) == []


def test_upper_band_blocks_a_new_entry():
    panel = _panel([100.0] * BARS)
    market = _flat(panel.index, blockNewEntries=True)
    assert _run(panel, _entries(panel.index, [5]), market) == []


def test_reentry_within_cooldown_needs_a_three_percent_drop():
    """Sold at 100, signalling again at 99 inside the window: still blocked."""
    closes = [100.0] * 10 + [69.0] * 2 + [99.0] * (BARS - 12)
    panel = _panel(closes)
    entries = _entries(panel.index, [5, 15])
    trades = _run(panel, entries, _flat(panel.index))
    assert len(trades) == 1


def test_reentry_within_cooldown_allowed_after_a_three_percent_drop():
    closes = [100.0] * 10 + [69.0] * 2 + [66.0] * (BARS - 12)
    panel = _panel(closes)
    entries = _entries(panel.index, [5, 15])
    trades = _run(panel, entries, _flat(panel.index))
    assert len(trades) == 2
    assert trades[1]["entryDate"] == panel.index[16]


def test_cooldown_fully_releases_after_ten_trading_days():
    closes = [100.0] * 10 + [69.0] * 2 + [99.0] * (BARS - 12)
    panel = _panel(closes)
    entries = _entries(panel.index, [5, 25])
    trades = _run(panel, entries, _flat(panel.index))
    assert len(trades) == 2


def test_reentry_waits_two_days_after_the_sell():
    """The service waits 48 hours after a sell before it will buy again.

    The sell executes on bar 11, so bars 11 and 12 are inside the wait and the
    first signal that can be acted on is bar 13.
    """
    closes = [100.0] * 10 + [69.0] * 2 + [60.0] * (BARS - 12)
    panel = _panel(closes)
    entries = _entries(panel.index, list(range(11, 21)))
    entries.loc[panel.index[5], "entry1"] = True
    trades = _run(panel, entries, _flat(panel.index))
    assert len(trades) == 2
    assert trades[1]["signalDate"] == panel.index[13]


def test_strategy_two_entries_are_labelled():
    panel = _panel([100.0] * BARS)
    trades = _run(panel, _entries(panel.index, [5], column="entry2"), _flat(panel.index))
    assert trades[0]["strategy"] == "2"


def test_ineligible_bars_cannot_open_a_trade():
    panel = _panel([100.0] * BARS)
    panel["eligible"] = False
    assert _run(panel, _entries(panel.index, [5]), _flat(panel.index)) == []


def test_net_return_charges_both_sides():
    panel = _panel([100.0] * BARS)
    market = _flat(panel.index)
    market.loc[panel.index[15], "peakTriggered"] = True
    trades = _run(panel, _entries(panel.index, [5]), market)
    assert trades[0]["retGross"] == pytest.approx(-0.0004, abs=1e-6)
    assert trades[0]["retNet"] == pytest.approx(-0.0014, abs=1e-5)


def test_excursions_are_measured_from_the_entry_price():
    closes = [100.0] * 8 + [120.0, 80.0] + [100.0] * (BARS - 10)
    panel = _panel(closes)
    market = _flat(panel.index)
    market.loc[panel.index[15], "peakTriggered"] = True
    trades = _run(panel, _entries(panel.index, [5]), market)
    assert trades[0]["mfeToExit"] == pytest.approx(0.2, abs=1e-3)
    assert trades[0]["maeToExit"] == pytest.approx(-0.2, abs=1e-3)


def test_season_opens_on_the_first_strategy_one_signal():
    index = pd.bdate_range("2020-01-01", periods=10)
    state = pd.DataFrame({"isRecoveryMarket": False}, index=index)
    triggers = pd.Series(False, index=index)
    triggers.iloc[3] = True
    timeline = legacy_strategies.season_timeline(state, triggers)
    assert not timeline["seasonOpen"].iloc[3]
    assert timeline["seasonOpen"].iloc[4]


def test_season_closes_after_two_non_recovery_days():
    index = pd.bdate_range("2020-01-01", periods=10)
    recovery = np.array([False, False, True, True, True, False, False, False, False, False])
    state = pd.DataFrame({"isRecoveryMarket": recovery}, index=index)
    triggers = pd.Series(False, index=index)
    triggers.iloc[0] = True
    timeline = legacy_strategies.season_timeline(state, triggers)
    assert timeline["recoveryEnded"].iloc[6]
    assert not timeline["seasonOpen"].iloc[7]


def test_season_stays_open_when_recovery_never_arrives():
    index = pd.bdate_range("2020-01-01", periods=10)
    state = pd.DataFrame({"isRecoveryMarket": False}, index=index)
    triggers = pd.Series(False, index=index)
    triggers.iloc[0] = True
    timeline = legacy_strategies.season_timeline(state, triggers)
    assert timeline["seasonOpen"].iloc[-1]
    assert not timeline["recoveryEnded"].any()
