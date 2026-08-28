"""Shared assumptions for every quant backtest.

Every module imports costs and barrier settings from here. Modules must not
define their own fee constants -- mismatched fee assumptions across research
scripts are what made previous results impossible to compare.
"""

from __future__ import annotations

from dataclasses import dataclass

FEE_BPS = 5.0
"""One-way commission in basis points."""

SLIPPAGE_MIN_BPS = 2.0
"""Floor for market-order slippage in basis points."""

SLIPPAGE_ATR_FRACTION = 0.05
"""Slippage scales with volatility: this fraction of entry-day ATR%."""

MIN_DOLLAR_VOLUME = 20_000_000.0
MIN_PRICE = 5.0
MIN_BARS = 250

ERAS: tuple[tuple[str, str, str], ...] = (
    ("1999-2007", "1999-01-01", "2007-12-31"),
    ("2008-2012", "2008-01-01", "2012-12-31"),
    ("2013-2019", "2013-01-01", "2019-12-31"),
    ("2020-2022", "2020-01-01", "2022-12-31"),
    ("2023-now", "2023-01-01", "2100-01-01"),
)


@dataclass(frozen=True)
class Barriers:
    """Exit geometry expressed in ATR multiples, never fixed percentages.

    Fixed percentage targets are unreachable for low-volatility names and
    trivial for high-volatility names, so averaging both into one number is
    meaningless.

    Set ``absolute`` to read the two multiples as plain return fractions
    instead. That is only for replaying rules that were authored in fixed
    percentages, so their real cost can be measured on their own terms.
    """

    target_atr: float
    stop_atr: float
    max_hold: int
    label: str
    absolute: bool = False


SWING = Barriers(target_atr=4.0, stop_atr=2.0, max_hold=40, label="swing")
DAY = Barriers(target_atr=2.0, stop_atr=1.0, max_hold=5, label="day")
SCALP = Barriers(target_atr=1.0, stop_atr=0.7, max_hold=1, label="scalp")

@dataclass(frozen=True)
class ExitPolicy:
    """How a position is closed once it is open.

    Fixed barriers realize only a fraction of the excursion a position offers,
    so the alternatives that try to capture it are first-class options rather
    than afterthoughts.
    """

    name: str
    kind: str
    trail_atr: float = 1.5
    activate_atr: float = 1.0
    partial_at_atr: float = 2.0
    partial_fraction: float = 0.5


EXIT_POLICIES: dict[str, ExitPolicy] = {
    "barrier": ExitPolicy("barrier", "barrier"),
    "time": ExitPolicy("time", "time"),
    "trail": ExitPolicy("trail", "trail", trail_atr=1.5, activate_atr=1.0),
    "trailWide": ExitPolicy("trailWide", "trail", trail_atr=2.5, activate_atr=1.0),
    "partial": ExitPolicy("partial", "partial", partial_at_atr=2.0, partial_fraction=0.5),
}

CHECKPOINTS: tuple[int, ...] = (1, 5, 20, 40)

AMBIGUITY_LIMIT = 0.15
"""If more than this share of trades hit both barriers on one bar, daily data
cannot decide the outcome and the configuration must not be concluded on."""
