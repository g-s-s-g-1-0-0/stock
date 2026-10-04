"""Final fixed research hypotheses from completed daily bars only."""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.swing_candidate_features import feature_frame

PATTERNS = {
    "breakout_first_retest": "volume>=1.3 first20-high breakout2..10 sessions ago; first low retest within -3..+1% of frozen level, intervening closes hold it; bullish close above level and MA200",
    "failed_breakout_reclaim": "same breakout anchor within10; first failure within3 sessions, no reclaim before today; close now reclaims frozen level above MA200, volume>=1.2",
    "outside_reversal": "prior3-session return<0; today's low<prior low and close>prior high/open/MA200",
    "gap_first_retest": "bullish gap>=3%,volume>=2 anchor2..10 sessions ago; first retest anchor low within -3..+1%; intervening closes hold low; close>anchor midpoint/open/MA200",
    "shock_high_rebreak": "bullish >=4% day2..5 sessions ago,TR>=2 priorATR,volume>=1.5; later lows hold its low and closes stay below its high; close now>anchor high/MA200,volume>=1.2",
    "confirmed_rsi_divergence": "two latest confirmed2+2 lows within40 sessions: lower price by<=10%,RSI improves>=5 from<35; first close above newer pivot high after confirmation, aboveMA200",
}
FILTERS = {
    "fresh_ma_support": "current bullish bounce at MA20/50/120/200 with previous10 lows all above that MA*1.003",
    "no_recent_failed_breakout": "no prior20-high volume1.3 breakout closing below frozen level within3 sessions in last10 sessions through D",
    "few_distribution_days": "prior10 sessions have at most1 day with return<=-1% and volume>=1.2 prior20 mean",
    "intraday_supported_trend": "last20 cumulative log(close/open)>0 and >= cumulative log(open/prior close)",
    "nearby_price_support": "distance from close to prior5-session low is >0 and <=5%; this is a signal filter, not a5% stop",
    "weekly_uptrend": "last completed Friday week close>10-week MA and that MA>four weeks earlier; conservative Friday labels",
}


def final_feature_frame(frame, benchmark):
    f = feature_frame(frame, benchmark).copy()
    c, o, h, l, v = (f[k] for k in ("Close", "Open", "High", "Low", "Volume"))
    level = h.shift().rolling(20).max()
    breakout = (c > level) & (c.shift() <= level.shift()) & (f.volumePriorRatio >= 1.3)
    gap = (o / c.shift() - 1 >= .03) & (c > o) & (f.volumePriorRatio >= 2)
    shock = (c / c.shift() - 1 >= .04) & (c > o) & (f.trueRangeRatio >= 2) & (f.volumePriorRatio >= 1.5)
    for key in PATTERNS:
        f[key] = False
    f["outside_reversal"] = (c.shift() / c.shift(4) < 1) & (l < l.shift()) & (c > h.shift()) & (c > o) & (c > f.MA200)
    anchors = {key: np.flatnonzero(flags.to_numpy()) for key, flags in [("break", breakout), ("gap", gap), ("shock", shock)]}
    failures = np.zeros(len(f), dtype=bool)
    last_lows = []
    va = {key: f[key].to_numpy() for key in ["Close", "Open", "High", "Low", "MA200", "RSI", "volumePriorRatio"]}
    out = {key: f[key].to_numpy(copy=True) for key in PATTERNS}
    frozen_level = np.full(len(f), np.nan)
    anchor_values = {key: np.full(len(f), np.nan) for key in ["gapAnchorLow", "gapAnchorHigh", "shockAnchorLow", "shockAnchorHigh", "divergenceOldLow", "divergenceNewLow", "divergenceOldRSI", "divergenceNewRSI"]}
    for i in range(22, len(f)):
        for j in anchors["break"][(anchors["break"] >= i-3) & (anchors["break"] < i)]:
            failures[i] |= va["Close"][i] < level.iloc[j]
        pivot = i - 2
        if va["Low"][pivot] < min(va["Low"][pivot-2:pivot]) and va["Low"][pivot] < min(va["Low"][pivot+1:i+1]):
            last_lows.append(pivot)
        if va["Close"][i] <= va["MA200"][i] or not np.isfinite(va["MA200"][i]):
            continue
        for kind, lookback in [("break", 10), ("gap", 10), ("shock", 5)]:
            candidates = anchors[kind][(anchors[kind] >= i-lookback) & (anchors[kind] <= i-2)]
            if not len(candidates):
                continue
            j = candidates[-1]
            if kind == "break":
                a = level.iloc[j]
                frozen_level[i] = a
                held = (va["Close"][j+1:i] >= a).all()
                untouched = (va["Low"][j+1:i] > a*1.01).all()
                out["breakout_first_retest"][i] = held and untouched and a*.97 <= va["Low"][i] <= a*1.01 and va["Close"][i] > max(a, va["Open"][i])
                broken = np.flatnonzero(va["Close"][j+1:i] < a)
                if len(broken) and broken[0] < 3:
                    k = j+1+broken[0]
                    out["failed_breakout_reclaim"][i] = (va["Close"][k:i] <= a).all() and va["Close"][i] > a and va["volumePriorRatio"][i] >= 1.2
            elif kind == "gap":
                a = va["Low"][j]
                anchor_values["gapAnchorLow"][i], anchor_values["gapAnchorHigh"][i] = a, va["High"][j]
                held = (va["Close"][j+1:i] >= a).all()
                untouched = (va["Low"][j+1:i] > a*1.01).all()
                out["gap_first_retest"][i] = held and untouched and a*.97 <= va["Low"][i] <= a*1.01 and va["Close"][i] > max(va["Open"][i], (va["High"][j]+a)/2)
            else:
                anchor_values["shockAnchorLow"][i], anchor_values["shockAnchorHigh"][i] = va["Low"][j], va["High"][j]
                out["shock_high_rebreak"][i] = (va["Low"][j+1:i] >= va["Low"][j]).all() and (va["Close"][j+1:i] <= va["High"][j]).all() and va["Close"][i] > va["High"][j] and va["volumePriorRatio"][i] >= 1.2
        if len(last_lows) >= 2:
            a, b = last_lows[-2:]
            for key, value in [("divergenceOldLow", va["Low"][a]), ("divergenceNewLow", va["Low"][b]), ("divergenceOldRSI", va["RSI"][a]), ("divergenceNewRSI", va["RSI"][b])]:
                anchor_values[key][i] = value
            if b-a <= 40 and .9 <= va["Low"][b]/va["Low"][a] < 1 and va["RSI"][a] < 35 and va["RSI"][b] >= va["RSI"][a]+5:
                # The newer pivot becomes usable only at b+2; crossing earlier is not reused.
                out["confirmed_rsi_divergence"][i] = va["Close"][i] > va["High"][b] and (va["Close"][b+2:i] <= va["High"][b]).all()
    for key, values in out.items():
        f[key] = values
    f["recentBreakoutLevel"] = frozen_level
    f = pd.concat([f, pd.DataFrame(anchor_values, index=f.index)], axis=1).copy()
    fresh = pd.Series(False, index=f.index)
    for n in [20, 50, 120, 200]:
        ma = c.rolling(n).mean()
        f[f"untouchedCount{n}"] = (l > ma*1.003).shift().rolling(10).sum()
        untouched = f[f"untouchedCount{n}"] == 10
        fresh |= untouched & (l <= ma*1.003) & (c > ma) & (c > o) & (c > c.shift())
    f["fresh_ma_support"] = fresh
    f["no_recent_failed_breakout"] = pd.Series(failures, index=f.index).rolling(10).sum() == 0
    f["distributionCount10"] = ((c.pct_change() <= -.01) & (f.volumePriorRatio >= 1.2)).shift().rolling(10).sum()
    f["few_distribution_days"] = f.distributionCount10 <= 1
    f["intradayLog20"] = np.log(c/o).rolling(20).sum()
    f["overnightLog20"] = np.log(o/c.shift()).rolling(20).sum()
    f["intraday_supported_trend"] = (f.intradayLog20 > 0) & (f.intradayLog20 >= f.overnightLog20)
    f["supportDistance5"] = (c-l.shift().rolling(5).min())/c
    f["nearby_price_support"] = (f.supportDistance5 > 0) & (f.supportDistance5 <= .05)
    weekly = pd.Series(c.to_numpy(), index=pd.to_datetime(f.index)).resample("W-FRI").last()
    average = weekly.rolling(10).mean()
    weekly_flag = (weekly > average) & (average > average.shift(4))
    for key, values in [("weeklyClose", weekly), ("weeklyMA10", average), ("weeklyMA10Prior4", average.shift(4))]:
        f[key] = values.reindex(pd.to_datetime(f.index), method="ffill").to_numpy()
    f["weekly_uptrend"] = weekly_flag.reindex(pd.to_datetime(f.index), method="ffill").astype("boolean").fillna(False).to_numpy(dtype=bool)
    return f
