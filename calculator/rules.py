"""Conservative Strategy 1/2 rules for the web service.

Strategy 1: panic bottom (former B entry).
Strategy 2: MA pullback buys while the season is open and the market is in recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


STRATEGY_RULES: dict[str, float | int] = {
    "VIX_MIN": 30,
    "VIX_RELEASE": 23,
    "RSI_MAX": 35,
    "CCI_MIN": -150,
    "LR_TOUCH_RATIO": 1.05,
    "CIRCUIT_PCT_1": 0.30,
    "CIRCUIT_PCT_2": 0.30,
    # Success/fail is judged at recovery-end exit; no profit target.
    "TARGET_PCT_1": 0.0,
    "TARGET_PCT_2": 0.0,
    "MA_TOUCH_RATIO": 1.003,
    "MA_RECLAIM_RATIO": 0.995,
    "RECOVERY_EXIT_CONFIRM_DAYS": 2,
    "NASDAQ_BUY_BLOCK_MAX": 9,
    "NASDAQ_DIST_UPPER": -3,
    "NASDAQ_DIST_LOWER": -12,
    "NASDAQ_DIST_RELEASE": -2.5,
    "REENTRY_DAYS": 10,
}

STRATEGY_LABELS = {
    "1": "공황 저점",
    "2": "이평선 눌림",
}

# Legacy A–H codes map to nothing active; B maps to 1 for migration.
LEGACY_STRATEGY_MAP = {
    "B": "1",
}

ACTIVE_STRATEGY_CODES = ("1", "2")
NASDAQ_PEAK_EXIT_EXEMPT_STRATEGIES: set[str] = set()


@dataclass(frozen=True)
class IndicatorRow:
    stock_name: str
    current_price: float
    ma200: float | None = None
    rsi: float | None = None
    cci: float | None = None
    macd_hist: float | None = None
    macd_hist_d1: float | None = None
    macd_hist_d2: float | None = None
    pct_b: float | None = None
    pct_b_low: float | None = None
    ma20: float | None = None
    ma20_d1: float | None = None
    ma20_prev5: float | None = None
    ma60: float | None = None
    ma144: float | None = None
    close_d1: float | None = None
    bb_width: float | None = None
    bb_width_d1: float | None = None
    bb_width_avg60: float | None = None
    vol_ratio: float | None = None
    vol_ratio20: float | None = None
    plus_di: float | None = None
    minus_di: float | None = None
    adx: float | None = None
    adx_d1: float | None = None
    lr_slope: float | None = None
    lr_trendline: float | None = None
    candle_open: float | None = None
    candle_low: float | None = None
    entry_price: float | None = None
    entry_date: date | None = None


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _gt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left > right


def _lt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left < right


def normalize_strategy_code(strategy: str | None) -> str | None:
    raw = str(strategy or "").strip()
    if not raw:
        return None
    first = raw.split(".", 1)[0].strip().upper()
    if first in ACTIVE_STRATEGY_CODES:
        return first
    if first in LEGACY_STRATEGY_MAP:
        return LEGACY_STRATEGY_MAP[first]
    return None


def strategy_display_name(strategy: str | None) -> str:
    code = normalize_strategy_code(strategy) or str(strategy or "").strip()
    if not code:
        return "-"
    if code in STRATEGY_LABELS:
        return f"{code}. {STRATEGY_LABELS[code]}"
    return f"{code}. {STRATEGY_LABELS.get(code, code)}"


def nasdaq_peak_exit_applies(strategy_type: str | None) -> bool:
    code = normalize_strategy_code(strategy_type) or (strategy_type or "").upper()
    return code not in NASDAQ_PEAK_EXIT_EXEMPT_STRATEGIES


def compute_nasdaq_filter_active(ixic_dist: float | None, was_active: bool = False) -> bool:
    """Kept for pipeline compatibility; Strategy 1/2 do not use the A/C filter."""

    if ixic_dist is None:
        return was_active
    lower = float(STRATEGY_RULES["NASDAQ_DIST_LOWER"])
    upper = float(STRATEGY_RULES["NASDAQ_DIST_UPPER"])
    release = float(STRATEGY_RULES["NASDAQ_DIST_RELEASE"])
    in_death = lower < ixic_dist < upper
    bottom = ixic_dist <= lower
    cleared = ixic_dist >= release

    if bottom or cleared:
        return False
    if in_death:
        return True
    return was_active


def _ma_touch(candle_low: float | None, current_price: float | None, ma: float | None) -> bool:
    if candle_low is None or current_price is None or ma is None or ma <= 0:
        return False
    touch = float(STRATEGY_RULES["MA_TOUCH_RATIO"])
    reclaim = float(STRATEGY_RULES["MA_RECLAIM_RATIO"])
    return candle_low <= ma * touch and current_price >= ma * reclaim


def evaluate_buy_condition(
    ind: IndicatorRow,
    vix: float | None,
    ixic_dist: float | None,
    ixic_filter_active: bool,
    *,
    is_holding: bool = False,
    holding_strategy_type: str | None = None,
    nasdaq_buy_block_max: float | None = None,
    is_recovery_market: bool = False,
    recovery_momentum_exception: bool = False,
    season_open: bool = False,
    warn_triggered: bool = False,
) -> dict[str, Any]:
    """Evaluate Strategy 1/2 entry and hold conditions.

    recovery_momentum_exception, ixic_filter_active, and warn_triggered are unused by
    1/2 entry but kept so existing call sites do not break. Warn-line gating was
    removed because the QQQ buy-block already covers the same overheat zone.
    """

    del recovery_momentum_exception, ixic_filter_active, warn_triggered

    s = STRATEGY_RULES
    vix_threshold = float(s["VIX_RELEASE"] if is_holding else s["VIX_MIN"])
    buy_block_max = float(nasdaq_buy_block_max if nasdaq_buy_block_max is not None else s["NASDAQ_BUY_BLOCK_MAX"])
    nasdaq_below_buy_block = ixic_dist is not None and ixic_dist <= buy_block_max
    nasdaq_downtrend = ixic_dist is not None and ixic_dist < float(s["NASDAQ_DIST_UPPER"])

    rsi_ok = _lt(ind.rsi, float(s["RSI_MAX"]))
    cci_ok = _lt(ind.cci, float(s["CCI_MIN"]))
    s1_cond1 = _lt(ind.current_price, ind.ma200)
    s1_cond2 = vix is not None and vix >= vix_threshold
    s1_cond3 = rsi_ok or cci_ok
    s1_cond4 = _gt(ind.lr_slope, 0)
    s1_cond5 = (
        ind.lr_trendline is not None
        and ind.lr_trendline > 0
        and ind.candle_low is not None
        and ind.candle_low <= ind.lr_trendline * float(s["LR_TOUCH_RATIO"])
    )
    s1_cond6 = nasdaq_downtrend
    entry_1 = s1_cond1 and s1_cond2 and s1_cond3 and s1_cond4 and s1_cond5 and s1_cond6

    touch_20 = _ma_touch(ind.candle_low, ind.current_price, ind.ma20)
    touch_60 = _ma_touch(ind.candle_low, ind.current_price, ind.ma60)
    touch_144 = _ma_touch(ind.candle_low, ind.current_price, ind.ma144)
    touch_200 = _ma_touch(ind.candle_low, ind.current_price, ind.ma200)
    s2_cond1 = season_open
    s2_cond2 = is_recovery_market
    s2_cond3 = nasdaq_below_buy_block
    s2_cond4 = touch_20 or touch_60 or touch_144 or touch_200
    entry_2 = s2_cond1 and s2_cond2 and s2_cond3 and s2_cond4 and not entry_1

    entry_strategy = "1" if entry_1 else "2" if entry_2 else None
    triggered = entry_strategy is not None

    holding_code = normalize_strategy_code(holding_strategy_type)
    if is_holding and holding_code:
        if holding_code == "1":
            triggered = s1_cond1 and s1_cond2 and s1_cond3 and s1_cond4 and s1_cond5 and s1_cond6
        elif holding_code == "2":
            triggered = s2_cond1 and s2_cond2 and s2_cond3

    return {
        "triggered": triggered,
        "strategyType": entry_strategy,
        "strategyName": strategy_display_name(entry_strategy),
        "entryTriggered": entry_strategy is not None,
        "recoveryException": False,
        "conditions": {
            "1": [s1_cond1, s1_cond2, s1_cond3, s1_cond4, s1_cond5, s1_cond6],
            "2": [s2_cond1, s2_cond2, s2_cond3, s2_cond4],
        },
        "maTouches": {
            "20": touch_20,
            "60": touch_60,
            "144": touch_144,
            "200": touch_200,
        },
    }


def format_return_pct(return_pct: float, *, signed: bool = True) -> str:
    value = return_pct * 100
    if signed:
        return f"{value:+.2f}%"
    return f"{value:.2f}%"


def strategy_target_criterion_label(strategy_type: str) -> str:
    code = normalize_strategy_code(strategy_type) or strategy_type
    base = STRATEGY_LABELS.get(code, code)
    return f"{base} 기준 회복장 종료 청산"


def strategy_stop_criterion_label(strategy_type: str) -> str:
    code = normalize_strategy_code(strategy_type) or strategy_type
    circuit_pct = float(STRATEGY_RULES.get(f"CIRCUIT_PCT_{code}", STRATEGY_RULES["CIRCUIT_PCT_1"]))
    base = STRATEGY_LABELS.get(code, code)
    stop_display = int(round(circuit_pct * 100))
    return f"{base} 기준 -{stop_display}%"


def enrich_profit_exit_reason(
    reason: str,
    strategy_type: str,
    return_pct: float | None = None,
    *,
    return_pct_is_percent: bool = True,
) -> str:
    text = str(reason or "").strip()
    if not text or "기준 +" in text or "기준 -" in text:
        return text or "시스템 매도"
    code = normalize_strategy_code(strategy_type)
    if code is None and strategy_type not in STRATEGY_LABELS:
        return text

    stop_label = strategy_stop_criterion_label(strategy_type)
    return_ratio = (
        return_pct / 100
        if return_pct is not None and return_pct_is_percent
        else return_pct
    )
    signed = format_return_pct(return_ratio) if return_ratio is not None else ""

    if text == "손절 기준 도달":
        return f"손절 기준 도달 {signed} [{stop_label}]".strip()
    if "회복장 종료" in text:
        return text if "[" in text else f"{text} {signed}".strip()
    return text


def evaluate_exit_condition(
    ind: IndicatorRow,
    *,
    strategy_type: str = "1",
    nasdaq_peak_alert: bool = False,
    trading_days: int = 0,
    upper_exit_wait_days: int | None = None,
    recovery_ended: bool = False,
) -> dict[str, Any]:
    del trading_days, upper_exit_wait_days

    if not ind.entry_price or ind.entry_price <= 0:
        return {"shouldExit": False, "reason": None}

    code = normalize_strategy_code(strategy_type) or strategy_type
    return_pct = (ind.current_price - ind.entry_price) / ind.entry_price
    return_signed = format_return_pct(return_pct)
    stop_label = strategy_stop_criterion_label(code)

    if recovery_ended:
        outcome = "성공" if return_pct > 0 else "실패"
        return {
            "shouldExit": True,
            "reason": f"회복장 종료 전량매도 {return_signed} [{outcome}]",
        }

    if nasdaq_peak_alert and nasdaq_peak_exit_applies(code):
        return {"shouldExit": True, "reason": "나스닥 고점 청산/강제매도"}

    circuit_pct = float(STRATEGY_RULES.get(f"CIRCUIT_PCT_{code}", STRATEGY_RULES["CIRCUIT_PCT_1"]))
    if return_pct <= -circuit_pct:
        return {"shouldExit": True, "reason": f"손절 기준 도달 {return_signed} [{stop_label}]"}

    return {"shouldExit": False, "reason": None}


def indicator_from_mapping(values: dict[str, Any]) -> IndicatorRow:
    return IndicatorRow(
        stock_name=str(values.get("stockName") or values.get("ticker") or ""),
        current_price=_num(values.get("currentPrice")) or 0,
        ma200=_num(values.get("ma200")),
        rsi=_num(values.get("rsi")),
        cci=_num(values.get("cci")),
        macd_hist=_num(values.get("macdHist")),
        macd_hist_d1=_num(values.get("macdHistD1")),
        macd_hist_d2=_num(values.get("macdHistD2")),
        pct_b=_num(values.get("pctB")),
        pct_b_low=_num(values.get("pctBLow")),
        ma20=_num(values.get("ma20")),
        ma20_d1=_num(values.get("ma20D1")),
        ma20_prev5=_num(values.get("ma20Prev5")),
        ma60=_num(values.get("ma60")),
        ma144=_num(values.get("ma144")),
        close_d1=_num(values.get("closeD1")),
        bb_width=_num(values.get("bbWidth")),
        bb_width_d1=_num(values.get("bbWidthD1")),
        bb_width_avg60=_num(values.get("bbWidthAvg60")),
        vol_ratio=_num(values.get("volRatio")),
        vol_ratio20=_num(values.get("volRatio20")),
        plus_di=_num(values.get("plusDI")),
        minus_di=_num(values.get("minusDI")),
        adx=_num(values.get("adx")),
        adx_d1=_num(values.get("adxD1")),
        lr_slope=_num(values.get("lrSlope")),
        lr_trendline=_num(values.get("lrTrendline")),
        candle_open=_num(values.get("candleOpen")),
        candle_low=_num(values.get("candleLow")),
        entry_price=_num(values.get("entryPrice")),
    )
