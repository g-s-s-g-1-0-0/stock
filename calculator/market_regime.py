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
QQQ_PEAK_WARN_MARGIN = 3.0
QQQ_PEAK_ALERT_RESET_DIST = 5.0
QQQ_DOWNTREND_DIST = -3.0


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


def qqq_regime_label(current_dist: Any, is_recovery_market: bool) -> str:
    dist = _num(current_dist)
    if is_recovery_market:
        return "회복장"
    if dist is None:
        return "판단 불가"
    if dist < QQQ_DOWNTREND_DIST:
        return "하락장"
    if dist <= QQQ_NORMAL_BUY_BLOCK_MAX:
        return "정상장"
    return "횡보장 고점"


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

    # 직접 청산선보다 한 단계 앞선 "조기 경고선". 별도 동작은 없고 경고 메일만
    # 보낸다. 이미 청산 조건이 켜진 경우(peak_triggered)에는 경고를 생략해
    # 청산 알림과 중복으로 나가지 않게 한다.
    warn_dist = peak_dist["direct"] - QQQ_PEAK_WARN_MARGIN
    warn_triggered = (
        current_dist is not None
        and current_dist >= warn_dist - 1e-9
        and not peak_triggered
    )

    return {
        "currentPrice": current_price,
        "ma200": ma200,
        "premiumPercent": current_dist,
        "recent60MinPremiumPercent": _num(recent_min_dist),
        "isRecoveryMarket": is_recovery,
        "regimeLabel": qqq_regime_label(current_dist, is_recovery),
        "buyBlockMax": qqq_buy_block_max(is_recovery),
        "peakDirectDist": peak_dist["direct"],
        "peakConfirmDist": peak_dist["confirm"],
        "peakWarnDist": warn_dist,
        "peakWarnResetDist": QQQ_PEAK_ALERT_RESET_DIST,
        "peakResetDist": QQQ_PEAK_ALERT_RESET_DIST,
        "weeklyRsi": _num(weekly_rsi),
        "dailyRsi": _num(qqq_row.get("rsi")),
        "dailyRsiPrev": _num(qqq_row.get("rsiD1")),
        "macdHist": _num(qqq_row.get("macdHist")),
        "macdHistD1": _num(qqq_row.get("macdHistD1")),
        "macdHistD2": _num(qqq_row.get("macdHistD2")),
        "rsiHotAndFalling": rsi_hot,
        "macdHistSlowing": macd_slowing,
        "peakTriggered": peak_triggered,
        "warnTriggered": warn_triggered,
    }
