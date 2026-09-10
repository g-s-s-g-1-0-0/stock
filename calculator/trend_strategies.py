"""Causal chart signals for strategies 5 and 6; levels are fixed on the signal bar."""
from __future__ import annotations

from math import isfinite
from typing import Any


def chart_phase(rows: list[dict[str, Any]], index: int) -> tuple[str, float, float]:
    window = rows[max(0, index - 59):index + 1]
    closes = [float(row['close']) for row in window]
    mean_x = (len(closes) - 1) / 2
    mean_y = sum(closes) / len(closes)
    denominator = sum((i - mean_x) ** 2 for i in range(len(closes)))
    slope = sum((i - mean_x) * (c - mean_y) for i, c in enumerate(closes)) / denominator
    line = mean_y + slope * mean_x
    prior = rows[index - 20:index]
    support = min(float(row['low']) for row in prior)
    resistance = max(float(row['high']) for row in prior)
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
