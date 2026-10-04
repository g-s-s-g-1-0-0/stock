"""Independent paired entry refinements; never writes operating state."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts import record_swing_research as sr

HISTORY = sr.HISTORY / "strategy-refinements-v1"
PAIRS = {
    "s1_ma200_rising": ("refine_s1_base", "refine_s1_ma200_rising"),
    "s2_volume": ("refine_s2_base", "refine_s2_volume"),
    "s4_ma200_rising": ("refine_s4_base", "refine_s4_ma200_rising"),
    "s6_ma50_above200": ("refine_s6_base", "refine_s6_ma50_above200"),
}
PROTOCOL = {
    "version": "strategy-refinements-v1",
    "startSession": "2026-10-05",
    "earliestReviewKST": "2026-12-08",
    "minimumCalendarMonths": 2,
    "minimumClosedFilteredTrades": None,
    "minimumFilteredEntryDates": None,
    "reviewArm": "refine_s2_volume",
    "arms": [arm for pair in PAIRS.values() for arm in pair],
    "pairs": {name: list(pair) for name, pair in PAIRS.items()},
    "entry": "D completed close predicates, next QQQ regular session open; no priority or account slots",
    "s1": "below MA200; VIX>=22; RSI<35 or CCI<-150; LR120 low slope>0; low<=LR*1.05; QQQ premium<-3; filter MA200>MA200[D-20]",
    "s2": "recorded season open; recovery; premium<=14; low<=MA*1.003 and close>=MA*.995 for MA20/60/144/200; filter volume>=1.2 prior20 mean",
    "s4": "below MA200 but distance>=-25%; MACD histogram crosses above0; QQQ nonrecovery premium<=9; filter MA200>MA200[D-20]",
    "s6": "causal downtrend escape attempt; market allowed; signal and next-open support risk<=8%; next-open gap<=3%; filter MA50>MA200",
    "exit": "paired common research exit: close -8%/+12%/20 sessions, QQQ peak or recovery end twice; next open; NOT operating exit replication",
    "recoveryBuyCap": 14.0,
    "recoveryExit": 18.0,
    "normalBuyCap": 9.0,
    "roundTripCost": 0.004,
    "pairedCoverage": "both arms require available filter values; rejected base signals retained",
    "season": "freeze raw strategySeason; known only when updated on signal NY date and no later than capture; missing/stale blocks S2, never assume season open",
    "events": "all pairs require known no-event state; market exceptions for S1 and S4 retained",
    "review": "calendar checkpoint only; no automatic sufficiency threshold; S1/S6 lower priority",
    "excludedKnownETFs": sorted(sr.ETF),
    "purpose": "private paper only, independent pairs, no orders or alerts; existing paper protocols unchanged",
}


def load_season():
    path = sr.ROOT / "data/cache/web-notification-state.json"
    try:
        value = json.loads(path.read_text()).get("strategySeason")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, dict) else None


def season_features(season, day, captured):
    known = False
    if isinstance(season, dict) and isinstance(season.get("open"), bool):
        try:
            stamp = datetime.fromisoformat(str(season.get("updatedAt", "")).replace("Z", "+00:00"))
            known = stamp.tzinfo is not None and stamp <= captured and stamp.astimezone(sr.NY).date().isoformat() == day
        except ValueError:
            pass
    return {"seasonKnown": bool(known), "seasonOpen": season.get("open") if known else None,
            "seasonSnapshot": season, "seasonSource": "data/cache/web-notification-state.json:strategySeason"}


def refinement_features(frame):
    from calculator.indicators import add_indicators
    from calculator.trend_strategies import build_trend_signal
    f = add_indicators(frame.copy())
    r = f.iloc[-1]
    ma = f.Close.rolling(200).mean()
    volume = sr.number(f.Volume.iloc[-21:-1].mean())
    rows = frame.iloc[-82:].reset_index().rename(columns={frame.index.name or "index": "date"})
    rows = rows.rename(columns={k: k.lower() for k in ("Open", "High", "Low", "Close", "Volume")})
    trend = build_trend_signal(rows.to_dict("records"))
    return {"ma200Prior20": sr.number(ma.iloc[-21]) if len(ma) >= 220 else None,
            "ma50": sr.number(f.Close.tail(50).mean()),
            "s2MovingAverages": {str(n): sr.number(f.Close.tail(n).mean()) for n in (20, 60, 144, 200)},
            "volumePriorRatio": sr.number(r.Volume / volume) if volume and volume > 0 else None,
            "rsi": sr.number(r.RSI), "cci": sr.number(r.CCI),
            "lrSlope": sr.number(r.LR_Slope), "lrTrendline": sr.number(r.LR_Trendline),
            "hist": sr.number(r.MACD_Hist), "histPrior": sr.number(r.MACD_Hist_D1),
            "trendAttempt": bool(trend.get("attempt")), "supportStop": sr.number(trend.get("stopPrice"))}


def refinement_flags(f, m, eligible=True):
    result = dict.fromkeys(PROTOCOL["arms"], False)
    if not eligible or m.get("event") != "당분간 없음" or m.get("peak"):
        return result
    c, low, ma = f["close"], f["low"], f["ma200"]
    prior_ma = f.get("ma200Prior20")
    known_s1 = all(f.get(k) is not None for k in ("vix", "rsi", "cci", "lrSlope", "lrTrendline", "ma200Prior20"))
    s1 = bool(known_s1 and c < ma and f["vix"] >= 22 and (f["rsi"] < 35 or f["cci"] < -150)
              and f["lrSlope"] > 0 and low <= f["lrTrendline"] * 1.05 and m["premium"] < -3)
    s2_core = bool(m["recovery"] and 0 <= m["premium"] <= 14 and any(
        line is not None and low <= line * 1.003 and c >= line * .995 for line in f["s2MovingAverages"].values()))
    s2 = bool(s2_core and f.get("seasonKnown") and f.get("seasonOpen") and f.get("volumePriorRatio") is not None)
    s4 = bool(prior_ma is not None and c < ma and c / ma >= .75 and not m["recovery"] and m["premium"] <= 9
              and f.get("histPrior") is not None and f.get("hist") is not None and f["histPrior"] <= 0 < f["hist"])
    support = f.get("supportStop")
    s6 = bool(m["buyAllowed"] and f["trendAttempt"] and support is not None
              and 0 < (c - support) / c <= .08 and f.get("ma50") is not None)
    result.update(refine_s1_base=s1, refine_s1_ma200_rising=bool(s1 and ma > prior_ma),
                  refine_s2_base=s2, refine_s2_volume=bool(s2 and f["volumePriorRatio"] >= 1.2),
                  refine_s4_base=s4, refine_s4_ma200_rising=bool(s4 and ma > prior_ma),
                  refine_s6_base=s6, refine_s6_ma50_above200=bool(s6 and f["ma50"] > ma))
    return result


def collect_refinements(daily, tickers, now=None, history=HISTORY, event_payload=None, names=None, season=None):
    captured = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    vix = sr.extract_frames(daily, ["^VIX"]).get("^VIX")
    def enrich(frame):
        day = frame.index[-1]
        value = sr.number(vix.loc[day, "Close"]) if vix is not None and day in vix.index else None
        return {**refinement_features(frame), "vix": value, **season_features(season, day, captured)}
    summary = sr.collect(daily, tickers, captured, history, event_payload, names,
                         protocol=PROTOCOL, flags=refinement_flags, feature_enricher=enrich)
    trades = sr.read_lines(history / "paper-trades.jsonl")
    observations = sr.read_lines(history / "observations.jsonl")
    pairs = {}
    for name, (base, filtered) in PAIRS.items():
        pairs[name] = {arm: {"closed": sum(t["arm"] == arm and t["status"] == "closed" for t in trades),
                             "entryDates": len({t["entry"] for t in trades if t["arm"] == arm and t["status"] == "closed"}),
                             "signals": summary["signalCounts"][arm]} for arm in (base, filtered)}
    sr.write_json(history / "pair-summary.json", {"pairs": pairs, "seasonUnknownObservations": sum(not r["features"]["seasonKnown"] for r in observations),
                                                  "review": PROTOCOL["earliestReviewKST"]})
    return summary
