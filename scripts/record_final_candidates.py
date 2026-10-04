"""Private final research supplement; no live strategy changes."""
import hashlib
from pathlib import Path

from scripts import record_candidate_lab as lab
from scripts import record_swing_research as sr
from scripts.swing_final_features import PATTERNS, FILTERS, final_feature_frame

HISTORY = sr.HISTORY / "candidate-final-v1"
PAIRS = {
    "S1": ["few_distribution_days"],
    "S2": ["fresh_ma_support", "intraday_supported_trend", "weekly_uptrend"],
    "S3": ["intraday_supported_trend", "nearby_price_support"],
    "S4": ["few_distribution_days"],
    "S6": ["few_distribution_days"],
    "S7": ["intraday_supported_trend"],
}
ARMS = {f"final_p_{name}": {"source": name, "filter": None} for name in PATTERNS}
for strategy, filters in PAIRS.items():
    for filt in filters:
        ARMS[f"final_{strategy.lower()}_{filt}"] = {"source": strategy, "filter": filt}
ARM_RULES = {arm: {"stop": .08, "target": .12, "days": 20, "mode": "common",
                   "entryStrategy": "6" if cfg["source"] == "S6" else None} for arm, cfg in ARMS.items()}
PROTOCOL = {
    "version": "candidate-final-v1", "startSession": "2026-10-05", "earliestReviewKST": "2026-12-08",
    "minimumClosedFilteredTrades": None, "minimumFilteredEntryDates": None, "minimumCalendarMonths": 2,
    "reviewArm": "final_s3_nearby_price_support", "arms": list(ARMS), "registry": ARMS, "armRules": ARM_RULES,
    "patterns": PATTERNS, "filters": FILTERS,
    "entry": "D completed close, D+1 regular open; market/events and actual S2 season required; S6 gap/support rechecked at open",
    "exit": "common close -8/+12/20 +market confirmed, next open; .4% cost; no operating exit replication",
    "reentry": "signal strictly after prior exit session",
    "recoveryBuyCap": 14., "recoveryExit": 18., "normalBuyCap": 9., "roundTripCost": .004,
    "controls": "S1/2/4/6 in strategy-refinements-v1; S3/5/7 common controls in candidate-lab-v1",
    "diagnostics": "all six new patterns and six filters plus existing30 patterns/20 single filters and1..7 predicates; rejected and unknown values retained; paths are diagnostics, not necessarily fills",
    "ranking": "all six patterns recorded, including sparse/weak cases; no strategy numbering or live priority assigned",
    "freeze": "keep definitions fixed through first Dec8 review; inadequate dates/regimes means continue observing, not automatic adoption",
    "scope": "private history; no UI/API/alerts/orders; same daily price downloads",
}


def final_observation(row):
    patterns = {k: bool(row[k]) for k in PATTERNS}
    filters = {k: bool(row[k]) for k in FILTERS}
    return {"finalPatternFlags": patterns, "finalFilterFlags": filters,
            "extraDiagnosticSignal": any(patterns.values()),
            "finalNumeric": {k: sr.number(row[k]) for k in ["recentBreakoutLevel", "distributionCount10", "intradayLog20", "overnightLog20", "supportDistance5",
                "gapAnchorLow", "gapAnchorHigh", "shockAnchorLow", "shockAnchorHigh", "divergenceOldLow", "divergenceNewLow", "divergenceOldRSI", "divergenceNewRSI",
                "untouchedCount20", "untouchedCount50", "untouchedCount120", "untouchedCount200", "weeklyClose", "weeklyMA10", "weeklyMA10Prior4"]}}


def final_flags(features, market, eligible=True):
    lab.lab_flags(features, market, eligible)
    allowed = bool(eligible and market.get("event") == "당분간 없음" and not market["peak"] and market["buyAllowed"])
    sources = {**features["baseStrategyFlags"], **{k: allowed and flag for k, flag in features["finalPatternFlags"].items()}}
    return {arm: bool(sources[cfg["source"]] and (cfg["filter"] is None or features["finalFilterFlags"].get(cfg["filter"]) is True))
            for arm, cfg in ARMS.items()}


def collect_final(daily, tickers, now=None, history=HISTORY, event_payload=None, names=None, season=None):
    summary = lab.collect_lab(daily, tickers, now, history, event_payload, names, season,
                              protocol=PROTOCOL, flags=final_flags, arm_rules=ARM_RULES,
                              prepare=final_feature_frame, extra_observation=final_observation)
    summary["finalCodeHash"] = hashlib.sha256(Path(__file__).read_bytes()+(sr.ROOT/"scripts/swing_final_features.py").read_bytes()).hexdigest()
    sr.write_json(history/"summary.json", summary)
    return summary
