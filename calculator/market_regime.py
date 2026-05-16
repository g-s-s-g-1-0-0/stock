"""Shared QQQ market-regime thresholds for web signals and notifications."""

from __future__ import annotations

from typing import Any

QQQ_RECOVERY_LOOKBACK_DAYS = 60
QQQ_RECOVERY_MIN_DIST = -5.0
QQQ_NORMAL_BUY_BLOCK_MAX = 9.0
QQQ_RECOVERY_BUY_BLOCK_MAX = 18.0
QQQ_NORMAL_PEAK_DIRECT_DIST = 16.0
QQQ_NORMAL_PEAK_CONFIRM_DIST = 14.0
QQQ_RECOVERY_PEAK_DIRECT_DIST = 22.0
QQQ_RECOVERY_PEAK_CONFIRM_DIST = 18.0
QQQ_PEAK_RSI_THRESHOLD = 65.0


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def qqq_ma200_distance(price: Any, ma200: Any) -> float | None:
    current_price = _num(price)
    ma200_value = _num(ma200)
    if current_price is None or ma200_value is None or ma200_value <= 0:
        return None
    return (current_price / ma200_value - 1) * 100


def qqq_recent_ma200_min_distance(rows: list[dict[str, float]], lookback: int = QQQ_RECOVERY_LOOKBACK_DAYS) -> float | None:
    """Return the lowest QQQ close-vs-MA200 distance in the recent lookback window."""

    closes = [_num(row.get("close")) for row in rows]
    valid_closes = [close for close in closes if close is not None]
    if len(valid_closes) < 200:
        return None

    distances: list[float] = []
    for index in range(199, len(valid_closes)):
        ma200 = sum(valid_closes[index - 199 : index + 1]) / 200
        if ma200 > 0:
            distances.append((valid_closes[index] / ma200 - 1) * 100)
    if not distances:
        return None
    return min(distances[-lookback:])


def qqq_is_recovery_market(current_dist: Any, recent_min_dist: Any) -> bool:
    dist = _num(current_dist)
    min_dist = _num(recent_min_dist)
    return min_dist is not None and min_dist <= QQQ_RECOVERY_MIN_DIST and dist is not None and dist >= 0


def qqq_buy_block_max(is_recovery_market: bool) -> float:
    return QQQ_RECOVERY_BUY_BLOCK_MAX if is_recovery_market else QQQ_NORMAL_BUY_BLOCK_MAX


def qqq_peak_distances(is_recovery_market: bool) -> dict[str, float]:
    if is_recovery_market:
        return {
            "direct": QQQ_RECOVERY_PEAK_DIRECT_DIST,
            "confirm": QQQ_RECOVERY_PEAK_CONFIRM_DIST,
        }
    return {
        "direct": QQQ_NORMAL_PEAK_DIRECT_DIST,
        "confirm": QQQ_NORMAL_PEAK_CONFIRM_DIST,
    }


def qqq_macd_hist_slowing(row: dict[str, Any]) -> bool:
    current = _num(row.get("macdHist"))
    prev = _num(row.get("macdHistD1"))
    prev2 = _num(row.get("macdHistD2"))
    return current is not None and prev is not None and prev2 is not None and current < prev < prev2


def qqq_rsi_hot_and_falling(row: dict[str, Any], weekly_rsi: Any) -> bool:
    weekly = _num(weekly_rsi)
    daily = _num(row.get("rsi"))
    daily_prev = _num(row.get("rsiD1"))
    return (
        weekly is not None
        and daily is not None
        and daily_prev is not None
        and weekly >= QQQ_PEAK_RSI_THRESHOLD
        and daily >= QQQ_PEAK_RSI_THRESHOLD
        and daily < daily_prev
    )


def build_qqq_market_state(
    qqq_row: dict[str, Any],
    *,
    recent_min_dist: Any,
    weekly_rsi: Any | None = None,
) -> dict[str, Any]:
    current_price = _num(qqq_row.get("close"))
    ma200 = _num(qqq_row.get("ma200"))
    current_dist = qqq_ma200_distance(current_price, ma200)
    is_recovery = qqq_is_recovery_market(current_dist, recent_min_dist)
    peak_dist = qqq_peak_distances(is_recovery)
    rsi_hot = qqq_rsi_hot_and_falling(qqq_row, weekly_rsi)
    macd_slowing = qqq_macd_hist_slowing(qqq_row)

    if is_recovery:
        peak_triggered = (
            current_dist is not None
            and current_dist > peak_dist["direct"]
        )
    else:
        peak_triggered = (
            current_dist is not None
            and rsi_hot
            and (
                current_dist > peak_dist["direct"]
                or (current_dist > peak_dist["confirm"] and macd_slowing)
            )
        )

    return {
        "currentPrice": current_price,
        "ma200": ma200,
        "premiumPercent": current_dist,
        "recent60MinPremiumPercent": _num(recent_min_dist),
        "isRecoveryMarket": is_recovery,
        "regimeLabel": "급락 후 회복장" if is_recovery else "비회복장/고점 횡보장",
        "buyBlockMax": qqq_buy_block_max(is_recovery),
        "peakDirectDist": peak_dist["direct"],
        "peakConfirmDist": peak_dist["confirm"],
        "peakResetDist": peak_dist["direct"] if is_recovery else peak_dist["confirm"],
        "weeklyRsi": _num(weekly_rsi),
        "dailyRsi": _num(qqq_row.get("rsi")),
        "dailyRsiPrev": _num(qqq_row.get("rsiD1")),
        "macdHist": _num(qqq_row.get("macdHist")),
        "macdHistD1": _num(qqq_row.get("macdHistD1")),
        "macdHistD2": _num(qqq_row.get("macdHistD2")),
        "rsiHotAndFalling": rsi_hot,
        "macdHistSlowing": macd_slowing,
        "peakTriggered": peak_triggered,
    }
