"""Causal chart signals for strategies 5 and 6; levels are fixed on the signal bar."""
from __future__ import annotations

from math import isfinite
from typing import Any


def _prior_extrema(rows: list[dict[str, Any]], index: int) -> tuple[float, int, float, int]:
    start = index - 20
    support_i = min(range(start, index), key=lambda j: float(rows[j]['low']))
    resistance_i = max(range(start, index), key=lambda j: float(rows[j]['high']))
    return float(rows[support_i]['low']), support_i, float(rows[resistance_i]['high']), resistance_i


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


CHART_BARS = 120
PIVOT_SPAN = 5
LINE_TOLERANCE = .012
LINE_TOUCH = .015
# The line's value at the last bar must stay this close to the close to be worth drawing.
LINE_RANGE = {'high': (.97, 1.35), 'low': (.65, 1.03)}


def _moving_averages(closes: list[float], period: int, start: int) -> list[float | None]:
    return [
        round(sum(closes[i + 1 - period:i + 1]) / period, 4) if i + 1 >= period else None
        for i in range(start, len(closes))
    ]


def _swing_pivots(values: list[float], kind: str) -> list[int]:
    found = []
    for i in range(PIVOT_SPAN, len(values) - PIVOT_SPAN):
        around = values[i - PIVOT_SPAN:i] + values[i + 1:i + PIVOT_SPAN + 1]
        if (kind == 'high' and values[i] > max(around)) or (kind == 'low' and values[i] < min(around)):
            found.append(i)
    return found


def _swing_line(values: list[float], close: float, kind: str) -> dict[str, float | int] | None:
    """Join two confirmed swing points, preferring the window extreme, then more touches, then recency."""
    points = _swing_pivots(values, kind)
    if not points:
        return None
    extreme = (max if kind == 'high' else min)(values[p] for p in points)
    low_bound, high_bound = LINE_RANGE[kind]
    last = len(values) - 1
    best = None
    for a, i in enumerate(points):
        for j in points[a + 1:]:
            if j - i < PIVOT_SPAN:
                continue
            slope = (values[j] - values[i]) / (j - i)
            if not close * low_bound <= values[i] + slope * (last - i) <= close * high_bound:
                continue
            misses = 0
            for k in range(i, len(values)):
                level = values[i] + slope * (k - i)
                if (kind == 'high' and values[k] > level * (1 + LINE_TOLERANCE)) or (
                    kind == 'low' and values[k] < level * (1 - LINE_TOLERANCE)
                ):
                    misses += 1
            if misses > 4:
                continue
            touches = sum(1 for k in points if k >= i and abs(values[k] - (values[i] + slope * (k - i))) <= values[k] * LINE_TOUCH)
            score = (values[i] == extreme, touches, j)
            if best is None or score > best[0]:
                best = (score, i, slope)
    if best is None:
        return None
    _, i, slope = best
    return {
        'startIndex': i,
        'startPrice': round(values[i], 4),
        'endIndex': last,
        'endPrice': round(values[i] + slope * (last - i), 4),
    }


def build_trend_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(rows) < 30:
        return None
    offset = max(0, len(rows) - CHART_BARS)
    visible = rows[offset:]
    closes = [float(row['close']) for row in rows]
    return {
        'candles': [{key: row[key] for key in ('date', 'open', 'high', 'low', 'close', 'volume')} for row in visible],
        'ma20': _moving_averages(closes, 20, offset),
        'ma50': _moving_averages(closes, 50, offset),
        'ma200': _moving_averages(closes, 200, offset),
        'resistanceLine': _swing_line([float(row['high']) for row in visible], closes[-1], 'high'),
        'supportLine': _swing_line([float(row['low']) for row in visible], closes[-1], 'low'),
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
