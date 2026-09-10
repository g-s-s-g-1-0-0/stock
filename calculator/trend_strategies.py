"""Causal chart signals for strategies 5 and 6; levels are fixed on the signal bar."""
from __future__ import annotations

from math import isfinite
from typing import Any


def _prior_extrema(rows: list[dict[str, Any]], index: int) -> tuple[float, int, float, int]:
    start = index - 20
    support_i = min(range(start, index), key=lambda j: float(rows[j]['low']))
    resistance_i = max(range(start, index), key=lambda j: float(rows[j]['high']))
    return float(rows[support_i]['low']), support_i, float(rows[resistance_i]['high']), resistance_i


def resolve_chart_levels(rows: list[dict[str, Any]], end_index: int) -> tuple[float, int, float, int, bool, bool]:
    start = max(20, end_index - 39)
    support, support_i, resistance, resistance_i = _prior_extrema(rows, start)
    res_broken = False
    sup_broken = False
    res_break_i = 0
    sup_break_i = 0
    for i in range(start, end_index + 1):
        close = float(rows[i]['close'])
        roll_s, roll_si, roll_r, roll_ri = _prior_extrema(rows, i)
        if res_broken and (close < resistance * .97 or i - res_break_i > 20):
            res_broken = False
        if sup_broken and (close > support * 1.03 or i - sup_break_i > 20):
            sup_broken = False
        if not res_broken:
            resistance, resistance_i = roll_r, roll_ri
        if not sup_broken:
            support, support_i = roll_s, roll_si
        if not res_broken and close > resistance:
            res_broken = True
            res_break_i = i
        if not sup_broken and close < support:
            sup_broken = True
            sup_break_i = i
    return support, support_i, resistance, resistance_i, sup_broken, res_broken


def chart_phase(
    rows: list[dict[str, Any]],
    index: int,
    support: float | None = None,
    resistance: float | None = None,
) -> tuple[str, float, float]:
    window = rows[max(0, index - 59):index + 1]
    closes = [float(row['close']) for row in window]
    mean_x = (len(closes) - 1) / 2
    mean_y = sum(closes) / len(closes)
    denominator = sum((i - mean_x) ** 2 for i in range(len(closes)))
    slope = sum((i - mean_x) * (c - mean_y) for i, c in enumerate(closes)) / denominator
    line = mean_y + slope * mean_x
    if support is None or resistance is None:
        support, _, resistance, _ = _prior_extrema(rows, index)
    close = closes[-1]
    change = close / float(rows[index - 19]['close']) - 1
    if slope < 0 and close > resistance * 1.005 and change > 0:
        phase = '상승 전환 초입'
    elif slope < 0 and close > line and change >= .05:
        phase = '상승 전환 대기'
    elif slope < 0 and close > line:
        phase = '하락 추세 이탈 시도'
    elif slope >= 0 and (close < support * .995 or (close < line and change < 0)):
        phase = '하락 전환 초입'
    elif slope >= 0 and close >= line:
        phase = '상승 추세 유지'
    else:
        phase = '하락 추세 유지'
    return phase, support, resistance


def build_trend_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(rows) < 30:
        return None
    end = len(rows) - 1
    support, support_i, resistance, resistance_i, support_frozen, resistance_frozen = resolve_chart_levels(rows, end)
    phase, _, _ = chart_phase(rows, end, support, resistance)
    return {
        'phase': phase,
        'support': support,
        'resistance': resistance,
        'supportIndex': support_i,
        'resistanceIndex': resistance_i,
        'supportFrozen': support_frozen,
        'resistanceFrozen': resistance_frozen,
        'candles': [{key: row[key] for key in ('date', 'open', 'high', 'low', 'close')} for row in rows],
    }


def build_trend_signal(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 82:
        return {}
    if any(not isfinite(float(row[key])) or float(row[key]) <= 0
           for row in rows[-80:] for key in ('open', 'high', 'low', 'close')):
        return {}
    active = None
    previous = chart_phase(rows, len(rows) - 22)[0]
    result: dict[str, Any] = {}
    for i in range(len(rows) - 21, len(rows)):
        phase, support, resistance = chart_phase(rows, i)
        row = rows[i]
        close, low, open_price = (float(row[k]) for k in ('close', 'low', 'open'))
        retest = False
        breakout_level = None
        if active is not None:
            seed, level = active
            if i - seed > 10 or close < level * .97:
                active = None
            elif i > seed and level * .97 <= low <= level * 1.01 and level <= close <= level * 1.03 and close >= open_price * .995:
                retest = True
                breakout_level = level
                active = None
        if active is None and phase == '상승 전환 초입' and previous != phase:
            active = (i, resistance)
        result = {
            'phase': phase,
            'retest': retest,
            'attempt': phase == '하락 추세 이탈 시도' and previous != phase,
            'support': support,
            'resistance': breakout_level,
            'stopPrice': support * .97,
            'signalClose': close,
            'signalDate': row.get('date'),
        }
        previous = phase
    return result


def trend_market_blocked(rows: list[dict[str, Any]]) -> bool:
    if len(rows) < 200:
        return True
    blocked = False
    for i in range(199, len(rows)):
        closes = [float(row['close']) for row in rows[i - 199:i + 1]]
        distance = (closes[-1] / (sum(closes) / 200) - 1) * 100
        if distance < -3:
            blocked = True
        elif distance >= -2.5:
            blocked = False
    return blocked
