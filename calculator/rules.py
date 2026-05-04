"""Strategy rules ported from updateInvestmentOpinion.gs.

The goal of this module is to keep the web batch worker and the existing sheet
logic aligned around one explicit Python representation of the A-F conditions.
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
    "TARGET_PCT_A": 0.20,
    "CIRCUIT_PCT_A": 0.30,
    "GOLDEN_CROSS_PCTB_MIN": 80,
    "GOLDEN_CROSS_RSI_MIN": 70,
    "TARGET_PCT_B": 0.20,
    "CIRCUIT_PCT_B": 0.30,
    "TARGET_PCT_C": 0.20,
    "CIRCUIT_PCT_C": 0.30,
    "C_SQUEEZE_RATIO": 0.45,
    "BB_EXPAND_RATIO": 1.00,
    "SQUEEZE_BREAKOUT_VOL_RATIO": 1.5,
    "SQUEEZE_BREAKOUT_PCTB_MIN": 55,
    "TARGET_PCT_D": 0.12,
    "CIRCUIT_PCT_D": 0.25,
    "ADX_MIN": 30,
    "ADX_PCTB_MIN": 30,
    "ADX_PCTB_MAX": 75,
    "D_NASDAQ_DIST_MAX": 13,
    "TARGET_PCT_E": 0.20,
    "CIRCUIT_PCT_E": 0.30,
    "SQUEEZE_RATIO": 0.5,
    "SQUEEZE_PCT_B_MAX": 50,
    "TARGET_PCT_F": 0.20,
    "CIRCUIT_PCT_F": 0.30,
    "BB_PCT_B_LOW_MAX": 3,
    "HALF_EXIT_DAYS": 60,
    "MAX_HOLD_DAYS": 120,
    "MAX_HOLD_DAYS_D": 30,
    "REENTRY_DAYS": 10,
    "NASDAQ_BUY_BLOCK_MAX": 9,
    "NASDAQ_DIST_UPPER": -3,
    "NASDAQ_DIST_LOWER": -12,
    "NASDAQ_DIST_RELEASE": -2.5,
    "UPPER_EXIT_MAX_WAIT_DAYS": 5,
}

STRATEGY_LABELS = {
    "A": "200일선 상방 & 모멘텀 재가속",
    "B": "200일선 하방 & 공황 저점",
    "C": "200일선 상방 & 스퀴즈 거래량 돌파",
    "D": "200일선 상방 & 상승 흐름 강화",
    "E": "200일선 상방 & 스퀴즈 저점",
    "F": "200일선 상방 & BB 극단 저점",
}


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
    bb_width: float | None = None
    bb_width_d1: float | None = None
    bb_width_avg60: float | None = None
    vol_ratio: float | None = None
    plus_di: float | None = None
    minus_di: float | None = None
    adx: float | None = None
    adx_d1: float | None = None
    lr_slope: float | None = None
    lr_trendline: float | None = None
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


def _between(value: float | None, low: float, high: float) -> bool:
    return value is not None and low <= value <= high


def strategy_display_name(strategy: str | None) -> str:
    if not strategy:
        return "-"
    return f"{strategy}. {STRATEGY_LABELS.get(strategy, strategy)}"


def compute_nasdaq_filter_active(ixic_dist: float | None, was_active: bool = False) -> bool:
    """Pure version of the GAS hysteresis filter."""

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


def evaluate_buy_condition(
    ind: IndicatorRow,
    vix: float | None,
    ixic_dist: float | None,
    ixic_filter_active: bool,
    *,
    is_holding: bool = False,
    holding_strategy_type: str | None = None,
) -> dict[str, Any]:
    """Evaluate A-F entry/hold conditions in the same priority as the sheet."""

    s = STRATEGY_RULES
    vix_threshold = float(s["VIX_RELEASE"] if is_holding else s["VIX_MIN"])
    nasdaq_below_buy_block = ixic_dist is not None and ixic_dist <= float(s["NASDAQ_BUY_BLOCK_MAX"])
    nasdaq_strict = (
        nasdaq_below_buy_block
        and not ixic_filter_active
        and ixic_dist is not None
        and ixic_dist >= float(s["NASDAQ_DIST_UPPER"])
    )
    nasdaq_bottom = nasdaq_below_buy_block and not ixic_filter_active

    a_cond1 = _gt(ind.current_price, ind.ma200)
    a_cond2 = ind.macd_hist_d1 is not None and ind.macd_hist_d1 <= 0 and _gt(ind.macd_hist, 0)
    a_cond3 = _gt(ind.pct_b, float(s["GOLDEN_CROSS_PCTB_MIN"]))
    a_cond4 = _gt(ind.rsi, float(s["GOLDEN_CROSS_RSI_MIN"]))
    entry_a = a_cond1 and a_cond2 and a_cond3 and a_cond4 and nasdaq_strict

    rsi_ok = _lt(ind.rsi, float(s["RSI_MAX"]))
    cci_ok = _lt(ind.cci, float(s["CCI_MIN"]))
    b_cond1 = _lt(ind.current_price, ind.ma200)
    b_cond2 = vix is not None and vix >= vix_threshold
    b_cond3 = rsi_ok or cci_ok
    b_cond4 = _gt(ind.lr_slope, 0)
    b_cond5 = (
        ind.lr_trendline is not None
        and ind.lr_trendline > 0
        and ind.candle_low is not None
        and ind.candle_low <= ind.lr_trendline * float(s["LR_TOUCH_RATIO"])
    )
    entry_b = b_cond1 and b_cond2 and b_cond3 and b_cond4 and b_cond5 and nasdaq_below_buy_block

    bb_pair_ok = ind.bb_width is not None and ind.bb_width_avg60 is not None and ind.bb_width_avg60 > 0
    c_cond1 = _gt(ind.current_price, ind.ma200)
    c_cond2 = bb_pair_ok and ind.bb_width_d1 is not None and (ind.bb_width_d1 / ind.bb_width_avg60) < float(s["C_SQUEEZE_RATIO"])
    c_cond3 = bb_pair_ok and ind.bb_width_d1 is not None and ind.bb_width is not None and ind.bb_width > ind.bb_width_d1 * float(s["BB_EXPAND_RATIO"])
    c_cond4 = ind.vol_ratio is not None and ind.vol_ratio >= float(s["SQUEEZE_BREAKOUT_VOL_RATIO"])
    c_cond5 = _gt(ind.pct_b, float(s["SQUEEZE_BREAKOUT_PCTB_MIN"]))
    c_cond6 = _gt(ind.macd_hist, 0)
    entry_c = not entry_a and not entry_b and c_cond1 and c_cond2 and c_cond3 and c_cond4 and c_cond5 and c_cond6 and nasdaq_strict

    d_cond1 = _gt(ind.current_price, ind.ma200)
    d_cond2 = ind.plus_di is not None and ind.minus_di is not None and ind.plus_di > ind.minus_di
    d_cond3 = _gt(ind.adx, float(s["ADX_MIN"]))
    d_cond4 = ind.adx is not None and ind.adx_d1 is not None and ind.adx > ind.adx_d1
    d_cond5 = _gt(ind.macd_hist, 0)
    d_cond6 = _between(ind.pct_b, float(s["ADX_PCTB_MIN"]), float(s["ADX_PCTB_MAX"]))
    d_cond7 = ixic_dist is not None and ixic_dist <= float(s["D_NASDAQ_DIST_MAX"])
    entry_d = not entry_a and not entry_b and not entry_c and d_cond1 and d_cond2 and d_cond3 and d_cond4 and d_cond5 and d_cond6 and d_cond7 and nasdaq_strict

    e_cond1 = _gt(ind.current_price, ind.ma200)
    e_cond2 = bb_pair_ok and ind.bb_width is not None and (ind.bb_width / ind.bb_width_avg60) < float(s["SQUEEZE_RATIO"])
    e_cond3 = ind.pct_b_low is not None and ind.pct_b_low <= float(s["SQUEEZE_PCT_B_MAX"])
    entry_e = not entry_a and not entry_b and not entry_c and not entry_d and e_cond1 and e_cond2 and e_cond3 and nasdaq_bottom

    f_cond1 = _gt(ind.current_price, ind.ma200)
    f_cond2 = ind.pct_b_low is not None and ind.pct_b_low <= float(s["BB_PCT_B_LOW_MAX"])
    entry_f = not entry_a and not entry_b and not entry_c and not entry_d and not entry_e and f_cond1 and f_cond2 and nasdaq_bottom

    entry_strategy = (
        "A" if entry_a else "B" if entry_b else "C" if entry_c else "D" if entry_d else "E" if entry_e else "F" if entry_f else None
    )
    triggered = entry_strategy is not None

    if is_holding and holding_strategy_type:
        if holding_strategy_type == "A":
            triggered = a_cond1 and not ixic_filter_active and nasdaq_below_buy_block and ixic_dist is not None and ixic_dist >= float(s["NASDAQ_DIST_UPPER"]) and _gt(ind.macd_hist, 0)
        elif holding_strategy_type == "B":
            triggered = b_cond1 and b_cond2 and b_cond3 and b_cond4 and nasdaq_below_buy_block
        elif holding_strategy_type == "C":
            triggered = c_cond1 and not ixic_filter_active and nasdaq_below_buy_block and ixic_dist is not None and ixic_dist >= float(s["NASDAQ_DIST_UPPER"]) and _gt(ind.macd_hist, 0)
        elif holding_strategy_type == "D":
            triggered = d_cond1 and not ixic_filter_active and nasdaq_below_buy_block and ixic_dist is not None and ixic_dist >= float(s["NASDAQ_DIST_UPPER"]) and d_cond2 and _gt(ind.macd_hist, 0)
        elif holding_strategy_type == "E":
            triggered = e_cond1 and not ixic_filter_active and nasdaq_below_buy_block and bb_pair_ok and e_cond2 and e_cond3
        elif holding_strategy_type == "F":
            triggered = f_cond1 and not ixic_filter_active and nasdaq_below_buy_block and f_cond2

    return {
        "triggered": triggered,
        "strategyType": entry_strategy,
        "strategyName": strategy_display_name(entry_strategy),
        "entryTriggered": entry_strategy is not None,
        "conditions": {
            "A": [a_cond1, a_cond2, a_cond3, a_cond4, nasdaq_strict],
            "B": [b_cond1, b_cond2, b_cond3, b_cond4, b_cond5, nasdaq_below_buy_block],
            "C": [c_cond1, c_cond2, c_cond3, c_cond4, c_cond5, c_cond6, nasdaq_strict],
            "D": [d_cond1, d_cond2, d_cond3, d_cond4, d_cond5, d_cond6, d_cond7, nasdaq_strict],
            "E": [e_cond1, e_cond2, e_cond3, nasdaq_bottom],
            "F": [f_cond1, f_cond2, nasdaq_bottom],
        },
    }


def macd_hist_turn(ind: IndicatorRow) -> bool:
    if ind.macd_hist is None or ind.macd_hist_d1 is None or ind.macd_hist_d2 is None:
        return False
    return (ind.macd_hist - ind.macd_hist_d1) < (ind.macd_hist_d1 - ind.macd_hist_d2)


def evaluate_exit_condition(
    ind: IndicatorRow,
    *,
    strategy_type: str = "A",
    nasdaq_peak_alert: bool = False,
    trading_days: int = 0,
    upper_exit_wait_days: int | None = None,
) -> dict[str, Any]:
    if not ind.entry_price or ind.entry_price <= 0:
        return {"shouldExit": False, "reason": None}
    if nasdaq_peak_alert:
        return {"shouldExit": True, "reason": "나스닥 고점 청산/강제매도"}

    s = STRATEGY_RULES
    target_pct = float(s.get(f"TARGET_PCT_{strategy_type}", s["TARGET_PCT_F"]))
    circuit_pct = float(s.get(f"CIRCUIT_PCT_{strategy_type}", s["CIRCUIT_PCT_F"]))
    max_hold_days = int(s["MAX_HOLD_DAYS_D"] if strategy_type == "D" else s["MAX_HOLD_DAYS"])
    return_pct = (ind.current_price - ind.entry_price) / ind.entry_price
    is_ef_strategy = strategy_type in {"E", "F"}

    if is_ef_strategy and return_pct >= target_pct:
        if macd_hist_turn(ind):
            return {"shouldExit": True, "reason": "목표 수익 구간 + MACD 히스토그램 둔화전환 매도"}
        if upper_exit_wait_days is not None and upper_exit_wait_days >= int(s["UPPER_EXIT_MAX_WAIT_DAYS"]):
            return {"shouldExit": True, "reason": "목표 수익 도달 후 대기 만료 매도"}
    elif return_pct >= target_pct:
        return {"shouldExit": True, "reason": "목표 수익 달성 즉시 매도"}

    if return_pct <= -circuit_pct:
        return {"shouldExit": True, "reason": "손절 기준 도달"}
    if trading_days >= int(s["HALF_EXIT_DAYS"]) and return_pct > 0:
        return {"shouldExit": True, "reason": "60거래일 경과 + 수익 중 자동 매도"}
    if trading_days >= max_hold_days:
        return {"shouldExit": True, "reason": "최대 보유 기간 초과 자동 매도"}
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
        bb_width=_num(values.get("bbWidth")),
        bb_width_d1=_num(values.get("bbWidthD1")),
        bb_width_avg60=_num(values.get("bbWidthAvg60")),
        vol_ratio=_num(values.get("volRatio")),
        plus_di=_num(values.get("plusDI")),
        minus_di=_num(values.get("minusDI")),
        adx=_num(values.get("adx")),
        adx_d1=_num(values.get("adxD1")),
        lr_slope=_num(values.get("lrSlope")),
        lr_trendline=_num(values.get("lrTrendline")),
        candle_low=_num(values.get("candleLow")),
        entry_price=_num(values.get("entryPrice")),
    )
