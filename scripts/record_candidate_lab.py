"""Private candidate registry and prospective comparisons, separate from live strategies."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from scripts import record_swing_research as sr
from scripts import record_strategy_refinements as rf
from scripts.swing_candidate_features import ALL_PATTERNS, FILTERS, feature_frame, watchlist_context, contextual_flags

HISTORY = sr.HISTORY / "candidate-lab-v1"
PAPER_PATTERNS = ["rsi2_pullback", "pocket_pivot", "strong_flag", "volume_climax_recovery", "anchored_vwap_reclaim",
                  "higher_low_breakout", "breakout_acceptance", "obv_leads_price", "inside3_breakout", "dry_pullback", "vcp_breakout"]
EXTRA_FILTERS = {
    "S1": ["ma50_above200", "volume_confirm"],
    "S2": ["rs20_positive", "efficient_trend"],
    "S3": ["atr_limited", "rs20_positive", "down_day_resilience"],
    "S4": ["ma50_above200", "qqq_ma20_rising"],
    "S6": ["ma200_rising", "qqq_ma20_rising", "rs_vs_watchlist"],
    "S7": ["rs20_positive", "rs_vs_watchlist", "both_relative_strength", "efficient_trend", "down_day_resilience", "ma_cross_first_pullback"],
}
ARMS = {f"lab_p_{p}": {"source": p, "filter": None, "mode": "common"} for p in PAPER_PATTERNS}
for strategy in ["S3", "S5", "S7"]:
    ARMS[f"lab_{strategy.lower()}_base"] = {"source": strategy, "filter": None, "mode": "common"}
for strategy, filters in EXTRA_FILTERS.items():
    for filt in filters:
        ARMS[f"lab_{strategy.lower()}_{filt}"] = {"source": strategy, "filter": filt, "mode": "common"}
for source, mode in [("S3", "half_at6"), ("S7", "half_at6"), ("rsi2_pullback", "half_at6"),
                     ("S4", "atr_2r"), ("rsi2_pullback", "atr_2r"), ("S4", "signal_low_failure")]:
    ARMS[f"lab_{source.lower()}_exit_{mode}"] = {"source": source, "filter": None, "mode": mode}
ARM_RULES = {arm: {"stop": .08, "target": .12, "days": 20, "mode": cfg["mode"],
                   "entryStrategy": cfg["source"][1:] if cfg["source"] in {"S5", "S6"} else None}
             for arm, cfg in ARMS.items()}
ARMS["lab_s3_entry_delay1"] = {"source": "S3", "filter": None, "mode": "common"}
ARM_RULES["lab_s3_entry_delay1"] = {"stop": .08, "target": .12, "days": 20, "mode": "common", "entryDelaySessions": 1}
ARMS["lab_s4_exit_time10"] = {"source": "S4", "filter": None, "mode": "common"}
ARM_RULES["lab_s4_exit_time10"] = {"stop": .08, "target": .12, "days": 10, "mode": "common"}
PROTOCOL = {
    "version": "candidate-lab-v1", "startSession": "2026-10-05", "earliestReviewKST": "2026-12-08",
    "minimumCalendarMonths": 2, "minimumClosedFilteredTrades": None, "minimumFilteredEntryDates": None,
    "reviewArm": "lab_p_rsi2_pullback", "arms": list(ARMS), "registry": ARMS, "armRules": ARM_RULES,
    "diagnosticPatterns": ALL_PATTERNS, "newDiagnosticFilters": FILTERS,
    "legacyDiagnosticFilters": ["rs20_positive", "rs60_positive", "ma50_above200", "ma200_rising", "volume_confirm", "volume_not_extreme", "strong_close", "not_extended", "atr_limited", "qqq_above20", "qqq_ma20_rising", "macd_improving"],
    "entry": "completed D close, D+1 regular open; independent predicates, no priority/account slots; S5/6 gap and S6 support checks at entry",
    "delayedEntry": "S3 delay1 freezes D signal and enters D+2 open without a new signal or intervening market/event recheck; diagnostic comparison only; all forward-outcomes remain D+1 reference paths",
    "exit": "common close -8/+12/20 plus market, next open; separate explicit exit variants; no operating-exit replication",
    "exitVariants": {"half_at6": "half next open after+6% close; remaining original exits; total proportional roundtrip cost .4%",
                     "atr_2r": "initial stop=2*signal ATR/entry clipped4..12%; target twice stop;20-day and market exits remain",
                     "signal_low_failure": "common plus two consecutive closes below frozen signal low; next open"},
    "reentry": "signal must be strictly later than prior exit session; no signal from exit day reused",
    "recoveryBuyCap": 14., "recoveryExit": 18., "normalBuyCap": 9., "roundTripCost": .004,
    "season": rf.PROTOCOL["season"],
    "watchlist": "exclude known ETFs; same current observed members on D and D-5; >=10 names required; watchlist is not whole market",
    "comparisonControls": "S1/2/4/6 bases in strategy-refinements-v1; S3/5/7 common-exit bases here; legacy S7 has different exits",
    "missingFilters": "null means unknown; paired evaluation must restrict BOTH arms to known feature dates",
    "diagnostics": "all30 pattern and20 single-filter pass/fail values frozen; five/ten/twenty-session paths for diagnostic signals, even blocked ones, labelled diagnosticOnly; no implied fill",
    "review": "first review date only, not automatic adoption; evaluate dates/regimes, open trades, costs, concentration and incremental value; inadequate evidence means extend",
    "purpose": "private history only, no UI, public API, alerts, orders or operating strategy edits",
}


def excluded(ticker, names):
    return ticker in sr.ETF or any(w in names.get(ticker, "").upper() for w in ("ETF", "DIREXION", "PROSHARES", "LEVERAGED", "2X", "3X"))


def lab_flags(f, m, eligible=True):
    refinement = rf.refinement_flags(f, m, eligible)
    allowed = bool(eligible and m.get("event") == "당분간 없음" and not m["peak"])
    c, ma = f["close"], f["ma200"]
    base = {"S1": refinement["refine_s1_base"], "S2": refinement["refine_s2_base"],
            "S4": refinement["refine_s4_base"], "S6": refinement["refine_s6_base"]}
    base["S3"] = bool(allowed and not m["recovery"] and -3 <= m["premium"] <= 7 and c > ma
                      and f.get("pctBLow") is not None and f["pctBLow"] <= 10 and f.get("rsi") is not None and f["rsi"] <= 45)
    base["S5"] = bool(allowed and m["buyAllowed"] and f["trendRetest"])
    base["S7"] = bool(allowed and sr.signal_flags(f, m, eligible)["s7_base"])
    # Freeze the unfiltered predicates as well as the chosen paper variants.
    f["baseStrategyFlags"] = base
    sources = {**base, **{p: bool(allowed and m["buyAllowed"] and flag) for p, flag in f["patternFlags"].items()}}
    return {arm: bool(sources[cfg["source"]] and (cfg["filter"] is None or f["filterFlags"].get(cfg["filter"]) is True))
            for arm, cfg in ARMS.items()}


def collect_lab(daily, tickers, now=None, history=HISTORY, event_payload=None, names=None, season=None,
                *, protocol=PROTOCOL, flags=lab_flags, arm_rules=ARM_RULES, prepare=feature_frame, extra_observation=None):
    from calculator.trend_strategies import build_trend_signal
    names = names or {}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    frames = sr.extract_frames(daily, sorted(set(tickers) | {"QQQ", "^VIX"}))
    qqq = frames.get("QQQ")
    if qqq is None or qqq.empty:
        raise RuntimeError("candidate lab: missing QQQ bars")
    local = current.astimezone(sr.NY)
    complete = [d for d in qqq.index if (d < local.date().isoformat() or d == local.date().isoformat() and local.hour >= 16 and (local.hour > 16 or local.minute >= 5)) and d >= protocol["startSession"]]
    day = complete[-1] if complete else None
    prepared = {t: prepare(b.loc[:day], qqq.loc[:day]) for t, b in frames.items()
                if day and t not in {"QQQ", "^VIX"} and day in b.index and len(b.loc[:day]) >= 200}
    members = [t for t in tickers if t in prepared and not excluded(t, names)]
    ctx = watchlist_context(prepared, members, day, qqq.index[qqq.index.get_loc(day)-5]) if day else None
    def enrich(ticker, frame):
        r = prepared[ticker].loc[frame.index[-1]]
        rows = frame.iloc[-82:].reset_index().rename(columns={frame.index.name or "index": "date"})
        rows = rows.rename(columns={k: k.lower() for k in ("Open", "High", "Low", "Close", "Volume")})
        trend = build_trend_signal(rows.to_dict("records"))
        patterns = {p: bool(r[p]) for p in ALL_PATTERNS}
        contextual = contextual_flags(r, ctx)
        patterns["breadth_followthrough"] = contextual["breadth_followthrough"]
        numeric = {key: sr.number(r[key]) for key in ("atr14", "rsi2", "volumePriorRatio", "ma20", "ma50", "ma200Prior20", "rs20", "rs60", "return20", "efficiency20", "vwap20", "trueRangeRatio", "upDownVolumeRatio5", "resilience20", "priorHigh60", "closeLocation", "anchorVWAP", "regressionZ", "confirmedPivotHigh", "confirmedPivotLow")}
        def known(value, condition):
            return None if value is None else bool(condition)
        filters = {k: bool(r[k]) for k in FILTERS}
        filters.update(broad_participation=known(ctx['breadth20'], contextual['broad_participation']),
                       rs_vs_watchlist=known(ctx['medianReturn20'], contextual['rs_vs_watchlist']),
                       down_day_resilience=known(numeric['resilience20'], r.down_day_resilience))
        filters.update(rs20_positive=known(numeric['rs20'], r.rs20>0), rs60_positive=known(numeric['rs60'], r.rs60>0),
                       ma50_above200=bool(r.ma50>r.MA200), ma200_rising=known(numeric['ma200Prior20'], r.MA200>r.ma200Prior20),
                       volume_confirm=known(numeric['volumePriorRatio'], r.volumePriorRatio>=1.2),
                       volume_not_extreme=known(numeric['volumePriorRatio'], r.volumePriorRatio<=2),
                       strong_close=known(numeric['closeLocation'], r.closeLocation>=.7), not_extended=bool(r.Close/r.ma20-1<=.08),
                       atr_limited=known(numeric['atr14'], r.atr14/r.Close<=.05), qqq_above20=bool(r.qqqAbove20),
                       qqq_ma20_rising=bool(r.qqqMA20Rising), macd_improving=bool(r.MACD_Hist>r.MACD_Hist_D1),
                       ma_cross_first_pullback=patterns['ma_cross_first_pullback'])
        filters['both_relative_strength'] = None if filters['rs20_positive'] is None or filters['rs_vs_watchlist'] is None else filters['rs20_positive'] and filters['rs_vs_watchlist']
        vix = frames.get('^VIX')
        result = {**numeric, 'patternFlags':patterns, 'filterFlags':filters, 'watchlistContext':ctx,
                'diagnosticSignal':bool(any(patterns.values()) and not excluded(ticker,names)),
                'rsi':sr.number(r.RSI),'cci':sr.number(r.CCI),'lrSlope':sr.number(r.LR_Slope),'lrTrendline':sr.number(r.LR_Trendline),
                'hist':sr.number(r.MACD_Hist),'histPrior':sr.number(r.MACD_Hist_D1),'pctBLow':sr.number(r.PctB_Low),
                's2MovingAverages':{str(n):sr.number(frame.Close.tail(n).mean()) for n in (20,60,144,200)},
                'trendAttempt':bool(trend.get('attempt')),'trendRetest':bool(trend.get('retest')),'supportStop':sr.number(trend.get('stopPrice')),
                'vix':sr.number(vix.loc[day,'Close']) if vix is not None and day in vix.index else None,
                **rf.season_features(season,day,current)}
        if extra_observation is not None:
            result.update(extra_observation(r))
            result['diagnosticSignal'] = bool((result['diagnosticSignal'] or result.get('extraDiagnosticSignal')) and not excluded(ticker,names))
        return result
    summary = sr.collect(daily,tickers,current,history,event_payload,names,protocol=protocol,flags=flags,
                         context_enricher=enrich,arm_rules=arm_rules,store_ma20=True)
    summary['candidateCodeHash'] = hashlib.sha256(Path(__file__).read_bytes()+(sr.ROOT/'scripts/swing_candidate_features.py').read_bytes()).hexdigest()
    sr.write_json(history/'summary.json',summary)
    return summary
