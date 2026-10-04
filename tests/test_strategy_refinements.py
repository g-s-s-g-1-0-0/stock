from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import numpy as np
import pandas as pd

from scripts import record_strategy_refinements as rf
from scripts import record_swing_research as sr
from tests.test_swing_research import obs, session


def features(**changes):
    return {"close": 90., "low": 89., "ma200": 100., "ma200Prior20": 99., "ma50": 110.,
            "vix": 25., "rsi": 30., "cci": -160., "lrSlope": 1., "lrTrendline": 90.,
            "s2MovingAverages": {"20": 90.}, "volumePriorRatio": 1.2,
            "seasonKnown": True, "seasonOpen": True, "histPrior": -.1, "hist": .1,
            "trendAttempt": True, "supportStop": 85., **changes}


def market(**changes):
    return {"event": "당분간 없음", "peak": False, "premium": 5., "recovery": False,
            "buyAllowed": True, **changes}


class RefinementTest(unittest.TestCase):
    def test_s1_preserves_downmarket_exception_and_paired_filter(self):
        m = market(premium=-4, buyAllowed=False)
        result = rf.refinement_flags(features(), m)
        self.assertTrue(result["refine_s1_base"])
        self.assertTrue(result["refine_s1_ma200_rising"])
        result = rf.refinement_flags(features(ma200Prior20=100), m)
        self.assertTrue(result["refine_s1_base"])
        self.assertFalse(result["refine_s1_ma200_rising"])
        for change in ({"vix": None}, {"ma200Prior20": None}, {"vix": 21.99}):
            self.assertFalse(rf.refinement_flags(features(**change), m)["refine_s1_base"])

    def test_s2_requires_known_open_season_and_prior_volume(self):
        m = market(recovery=True, premium=12)
        self.assertTrue(rf.refinement_flags(features(), m)["refine_s2_volume"])
        f = rf.refinement_flags(features(volumePriorRatio=1.19), m)
        self.assertTrue(f["refine_s2_base"])
        self.assertFalse(f["refine_s2_volume"])
        for change in ({"seasonKnown": False}, {"seasonOpen": False}, {"volumePriorRatio": None}):
            self.assertFalse(rf.refinement_flags(features(**change), m)["refine_s2_base"])

    def test_s4_keeps_bearish_market_but_excludes_recovery_and_deep_drawdown(self):
        self.assertTrue(rf.refinement_flags(features(), market(premium=-4, buyAllowed=False))["refine_s4_base"])
        self.assertFalse(rf.refinement_flags(features(), market(recovery=True))["refine_s4_base"])
        self.assertFalse(rf.refinement_flags(features(close=74.9), market())["refine_s4_base"])
        f = rf.refinement_flags(features(ma200Prior20=101), market())
        self.assertTrue(f["refine_s4_base"])
        self.assertFalse(f["refine_s4_ma200_rising"])

    def test_s6_base_and_ma50_filter(self):
        f = rf.refinement_flags(features(ma50=100), market())
        self.assertTrue(f["refine_s6_base"])
        self.assertFalse(f["refine_s6_ma50_above200"])
        self.assertFalse(rf.refinement_flags(features(supportStop=80), market())["refine_s6_base"])
        self.assertFalse(rf.refinement_flags(features(), market(buyAllowed=False))["refine_s6_base"])

    def test_all_pairs_respect_event_peak_and_etf(self):
        for m in [market(event="unknown"), market(event="CPI"), market(peak=True)]:
            self.assertFalse(any(rf.refinement_flags(features(), m).values()))
        self.assertFalse(any(rf.refinement_flags(features(), market(), eligible=False).values()))

    def test_season_snapshot_requires_same_session_and_no_future_timestamp(self):
        now = datetime(2026, 10, 5, 20, 10, tzinfo=sr.timezone.utc)
        season = {"open": True, "updatedAt": "2026-10-05T20:00:00Z"}
        self.assertTrue(rf.season_features(season, "2026-10-05", now)["seasonKnown"])
        for stamp in ["2026-10-04T20:00:00Z", "2026-10-05T21:00:00Z", "invalid", "2026-10-05T20:00:00"]:
            s = rf.season_features({**season, "updatedAt": stamp}, "2026-10-05", now)
            self.assertFalse(s["seasonKnown"])
            self.assertIsNone(s["seasonOpen"])
        self.assertFalse(rf.season_features(None, "2026-10-05", now)["seasonKnown"])

    def test_features_are_causal_and_volume_excludes_signal_day(self):
        c = np.arange(250.) + 100
        frame = pd.DataFrame({"Open": c, "High": c+2, "Low": c-2, "Close": c, "Volume": 100.},
                             index=pd.bdate_range(end="2026-10-05", periods=250).strftime("%Y-%m-%d"))
        f = rf.refinement_features(frame)
        self.assertEqual(frame.Close.iloc[-220:-20].mean(), f["ma200Prior20"])
        frame.iloc[-1, frame.columns.get_loc("Volume")] = 120.
        g = rf.refinement_features(frame)
        self.assertEqual(1.2, g["volumePriorRatio"])
        self.assertEqual(f["ma200Prior20"], g["ma200Prior20"])

    def test_s6_next_open_guard_is_split_adjusted_and_both_arms_skip(self):
        o = obs(features={"close": 100., "supportStop": 93., "rs20": None},
                signals={"refine_s6_base": True, "refine_s6_ma50_above200": True})
        for open_, reason in [(104, "entry_gap_above_3"), (102, "entry_support_risk_above_8")]:
            t, _ = sr.replay([o], {"2026-10-06": session(open_, open_)})
            self.assertEqual(2, len(t))
            self.assertTrue(all(x["status"] == "skipped" and x["reason"] == reason for x in t))
        t, _ = sr.replay([o], {"2026-10-06": session(50, 50, split=2)})
        self.assertTrue(all(x["status"] == "open" for x in t))

    def test_all_refinement_arms_use_common_twelve_percent_exit_and_time_cap(self):
        arms = {a: True for a in rf.PROTOCOL["arms"]}
        o = obs(features={"close": 100., "supportStop": 94., "rs20": None}, signals=arms)
        sessions = {"2026-10-06": session(100, 111), "2026-10-07": session(111, 113), "2026-10-08": session(114, 114)}
        trades, _ = sr.replay([o], sessions)
        self.assertEqual(8, len(trades))
        self.assertTrue(all(t["exit"] == "2026-10-08" and t["reason"] == "target_close" for t in trades))
        days = pd.bdate_range("2026-10-06", periods=21).strftime("%Y-%m-%d")
        trades, _ = sr.replay([o], {d: session() for d in days})
        self.assertTrue(all(t["exit"] == days[20] and t["reason"] == "time_20" for t in trades))

    def test_collection_freezes_season_and_vix_and_is_isolated(self):
        days = pd.bdate_range(end="2026-10-06", periods=250)
        fields = ["Open", "High", "Low", "Close", "Volume", "Stock Splits"]
        parts = {}
        for ticker, price in [("AAA", 100.), ("QQQ", 100.), ("^VIX", 25.)]:
            parts[ticker] = pd.DataFrame({"Open": price, "High": price+1, "Low": price-1,
                                         "Close": price, "Volume": 100., "Stock Splits": 0.}, index=days)
        frame = pd.concat(parts, axis=1).swaplevel(0, 1, axis=1)
        now = datetime(2026, 10, 5, 16, 10, tzinfo=sr.NY)
        season = {"open": True, "updatedAt": "2026-10-05T20:00:00Z"}
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            sr.initialize(path)
            target = path / "strategy-refinements-v1"
            rf.collect_refinements(frame, ["AAA"], now, target, {"groups": []}, season=season)
            first = (target / "observations.jsonl").read_text()
            record = json.loads(first)
            self.assertEqual(25., record["features"]["vix"])
            self.assertTrue(record["features"]["seasonOpen"])
            rf.collect_refinements(frame, ["AAA"], now, target, {"groups": []}, season={**season, "open": False})
            self.assertEqual(first, (target / "observations.jsonl").read_text())
            self.assertEqual(sr.PROTOCOL, json.loads((path / "protocol.json").read_text()))
            self.assertEqual(4, len(json.loads((target / "pair-summary.json").read_text())["pairs"]))


if __name__ == "__main__":
    unittest.main()
