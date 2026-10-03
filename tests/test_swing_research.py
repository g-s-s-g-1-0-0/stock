from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import pandas as pd

from scripts import record_swing_research as sr


def features(rs=1):
    return {"close": 100., "open": 99., "previousClose": 98., "low": 95.,
            "ma200": 90., "movingAverages": {"20": 96., "200": 90.},
            "rs20": rs, "histChange": 1.}


def market(**kwargs):
    return {"buyAllowed": True, "premium": 5., "recovery": False, "peak": False, **kwargs}


def obs(day="2026-10-05", **kwargs):
    return {"session": day, "ticker": "AAA", "forwardEligible": True, "features": features(),
            "signals": {"s7_base": True, "s7_rs_positive": True, "laggard_rebound": False}, **kwargs}


def session(open_=100., close=100., split=1., **kwargs):
    return {"market": market(**kwargs), "bars": {"AAA": {"open": open_, "close": close,
            "low": min(open_, close), "high": max(open_, close), "split": split}}}


class SwingResearchTest(unittest.TestCase):
    def test_nr7_boundaries_and_independent_predicate(self):
        f = {**features(None), "low": 99., "movingAverages": {}, "priorRange": 2.,
             "priorMinRange7": 2., "priorHigh": 99., "volumePriorRatio": 1.3}
        self.assertTrue(sr.nr7_flags(f, market())["s8_nr7_breakout"])
        for change in ({"priorRange": 2.01}, {"priorHigh": 100.}, {"ma200": 100.},
                       {"volumePriorRatio": 1.29}, {"priorMinRange7": None}):
            self.assertFalse(sr.nr7_flags({**f, **change}, market())["s8_nr7_breakout"])
        self.assertFalse(sr.nr7_flags(f, market(buyAllowed=False))["s8_nr7_breakout"])
        self.assertFalse(sr.nr7_flags(f, market(), eligible=False)["s8_nr7_breakout"])

    def test_nr7_reference_windows_exclude_signal_day(self):
        frame = pd.DataFrame({"High": [110.] * 21, "Low": [100.] * 21, "Volume": [100.] * 21})
        frame.loc[12, "Low"] = 109.
        frame.loc[19, "Low"] = 108.
        frame.loc[20] = [200., 200., 130.]
        f = sr.nr7_features(frame)
        self.assertEqual(2., f["priorMinRange7"])
        self.assertEqual(2., f["priorRange"])
        self.assertEqual(110., f["priorHigh"])
        self.assertEqual(1.3, f["volumePriorRatio"])
        self.assertIsNone(sr.nr7_features(frame.tail(7))["priorMinRange7"])

    def test_nr7_uses_twelve_percent_and_twenty_sessions(self):
        signal = obs(signals={"s8_nr7_breakout": True})
        sessions = {"2026-10-06": session(100, 111), "2026-10-07": session(111, 113),
                    "2026-10-08": session(114, 114)}
        trades, _ = sr.replay([signal], sessions)
        self.assertEqual("2026-10-08", trades[0]["exit"])
        self.assertAlmostEqual(.136, trades[0]["net"])
        days = pd.bdate_range("2026-10-06", periods=21).strftime("%Y-%m-%d")
        sessions = {day: session() for day in days}
        trades, _ = sr.replay([signal], sessions)
        self.assertEqual(days[20], trades[0]["exit"])
        self.assertEqual("time_20", trades[0]["reason"])
        sessions[days[0]]["market"]["peak"] = True
        trades, _ = sr.replay([signal], sessions)
        self.assertEqual(days[1], trades[0]["exit"])
        self.assertEqual("market_peak", trades[0]["reason"])

    def test_bb_breakout_requires_prior_compression_and_fresh_high(self):
        f = {**features(None), "priorSqueeze": .7, "priorHigh20": 99., "volumePriorRatio": 1.2}
        self.assertTrue(sr.bb_flags(f, market())["bb_squeeze_breakout"])
        for change in ({"priorSqueeze": .75}, {"priorHigh20": 100.}, {"volumePriorRatio": 1.19}, {"priorSqueeze": None}):
            self.assertFalse(sr.bb_flags({**f, **change}, market())["bb_squeeze_breakout"])
        self.assertFalse(sr.bb_flags(f, market(buyAllowed=False))["bb_squeeze_breakout"])

    def test_bb_features_exclude_signal_day_from_reference_windows(self):
        f = pd.DataFrame({"Close": [100 + i % 7 for i in range(200)], "High": [108.] * 200,
                          "Volume": [100.] * 200})
        baseline = sr.bb_features(f)
        f.loc[199] = [200, 210, 120]
        changed = sr.bb_features(f)
        self.assertEqual(baseline["priorSqueeze"], changed["priorSqueeze"])
        self.assertEqual(108, changed["priorHigh20"])
        self.assertEqual(1.2, changed["volumePriorRatio"])

    def test_bb_target_is_twelve_percent_not_s7_ten(self):
        sessions = {"2026-10-06": session(100, 111), "2026-10-07": session(111, 113),
                    "2026-10-08": session(114, 114)}
        trades, _ = sr.replay([obs(signals={"bb_squeeze_breakout": True})], sessions)
        self.assertEqual("2026-10-08", trades[0]["exit"])
        self.assertAlmostEqual(.136, trades[0]["net"])

    def test_bb_twenty_day_cap_and_market_exit(self):
        days = pd.bdate_range("2026-10-06", periods=21).strftime("%Y-%m-%d")
        sessions = {day: session() for day in days}
        signal = obs(signals={"bb_squeeze_breakout": True})
        trades, _ = sr.replay([signal], sessions)
        self.assertEqual(days[20], trades[0]["exit"])
        self.assertEqual("time_20", trades[0]["reason"])
        sessions[days[0]]["market"]["peak"] = True
        trades, _ = sr.replay([signal], sessions)
        self.assertEqual(days[1], trades[0]["exit"])
        self.assertEqual("market_peak", trades[0]["reason"])

    def test_relative_strength_is_only_paired_difference(self):
        self.assertEqual(sr.signal_flags(features(), market()),
                         {"s7_base": True, "s7_rs_positive": True, "laggard_rebound": False})
        self.assertTrue(sr.signal_flags(features(0), market())["s7_base"])
        self.assertFalse(sr.signal_flags(features(0), market())["s7_rs_positive"])
        self.assertFalse(any(sr.signal_flags(features(None), market()).values()))

    def test_laggard_observes_blocked_market_without_overriding_s7(self):
        f = {**features(), "ma200": 110.}
        flags = sr.signal_flags(f, market(premium=15, buyAllowed=False))
        self.assertEqual(flags, {"s7_base": False, "s7_rs_positive": False, "laggard_rebound": True})
        self.assertFalse(any(sr.signal_flags(f, market(premium=15), eligible=False).values()))

    def test_next_open_and_same_exit_for_both_arms(self):
        sessions = {"2026-10-05": session(90, 100), "2026-10-06": session(101, 113),
                    "2026-10-07": session(109, 90)}
        trades, _ = sr.replay([obs()], sessions)
        self.assertEqual(2, len(trades))
        for trade in trades:
            self.assertEqual("2026-10-06", trade["entry"])
            self.assertEqual("2026-10-07", trade["exit"])
            self.assertEqual(101, trade["entryPrice"])
            self.assertAlmostEqual(109 / 101 - 1 - .004, trade["net"])
            self.assertEqual("target_close", trade["reason"])

    def test_stop_gap_is_not_filled_at_threshold(self):
        trades, _ = sr.replay([obs()], {"2026-10-06": session(100, 90), "2026-10-07": session(80, 80)})
        self.assertAlmostEqual(-.204, trades[0]["net"])

    def test_missing_next_open_does_not_move_entry_later(self):
        sessions = {"2026-10-06": {"market": market(), "bars": {}}, "2026-10-07": session()}
        trades, _ = sr.replay([obs()], sessions)
        self.assertEqual("invalid", trades[0]["status"])
        self.assertEqual("missing_next_session_open", trades[0]["reason"])

    def test_split_does_not_create_false_stop(self):
        sessions = {"2026-10-06": session(), "2026-10-07": session(50, 51, split=2)}
        trades, _ = sr.replay([obs()], sessions)
        self.assertEqual("open", trades[0]["status"])
        self.assertIsNone(trades[0]["pendingExit"])
        self.assertAlmostEqual(.016, trades[0]["markNet"])

    def test_duplicate_signals_do_not_overlap_and_late_signals_do_not_trade(self):
        sessions = {"2026-10-06": session(), "2026-10-07": session(), "2026-10-08": session()}
        trades, _ = sr.replay([obs(), obs("2026-10-06"), obs("2026-10-07", forwardEligible=False)], sessions)
        self.assertEqual(2, len(trades))

    def test_recovery_end_requires_two_closes(self):
        sessions = {"2026-10-06": session(recovery=True), "2026-10-07": session(),
                    "2026-10-08": session(), "2026-10-09": session(102, 105)}
        trades, _ = sr.replay([obs()], sessions)
        self.assertEqual("2026-10-09", trades[0]["exit"])
        self.assertEqual("recovery_end_2", trades[0]["reason"])

    def test_horizon_labels_survive_early_paper_exit(self):
        days = pd.bdate_range("2026-10-06", periods=20).strftime("%Y-%m-%d")
        sessions = {day: session(100, 111) for day in days}
        _, labels = sr.replay([obs()], sessions)
        self.assertEqual([5, 10, 20], [r["horizon"] for r in labels])

    def test_completed_bars_only_and_idempotent_frozen_observations(self):
        days = pd.bdate_range(end="2026-10-06", periods=280)
        columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume", "Stock Splits"], ["AAA", "QQQ"]])
        data = [[100, 100, 102, 102, 98, 98, 101, 101, 1000, 1000, 0, 0] for _ in days]
        frame = pd.DataFrame(data, index=days, columns=columns)
        with TemporaryDirectory() as tmp:
            history = Path(tmp)
            now = datetime(2026, 10, 5, 16, 10, tzinfo=sr.NY)
            sr.collect(frame, ["AAA"], now, history, {"groups": []})
            before = (history / "observations.jsonl").read_text()
            self.assertEqual("2026-10-05", json.loads(before)["session"])
            sr.collect(frame, ["AAA"], now, history, {"groups": []})
            self.assertEqual(before, (history / "observations.jsonl").read_text())
            summary = json.loads((history / "summary.json").read_text())
            self.assertEqual("2026-10-05", summary["lastSession"])
            self.assertFalse(summary["sampleReady"])
            bb_history = history / "bb-breakout-v1"
            sr.collect_bb(frame, ["AAA"], now, bb_history, {"groups": []})
            bb_obs = sr.read_lines(bb_history / "observations.jsonl")[0]
            self.assertEqual({"bb_squeeze_breakout": False}, bb_obs["signals"])
            self.assertIn("priorSqueeze", bb_obs["features"])
            self.assertEqual(sr.PROTOCOL, json.loads((history / "protocol.json").read_text()))
            self.assertEqual(sr.BB_PROTOCOL, json.loads((bb_history / "protocol.json").read_text()))
            nr7_history = history / "nr7-breakout-v1"
            result = sr.collect_nr7(frame, ["AAA"], now, nr7_history, {"groups": []})
            nr7_obs = sr.read_lines(nr7_history / "observations.jsonl")[0]
            self.assertEqual({"s8_nr7_breakout": False}, nr7_obs["signals"])
            self.assertIn("priorMinRange7", nr7_obs["features"])
            self.assertIsNone(result["sampleReady"])
            self.assertEqual(sr.NR7_PROTOCOL, json.loads((nr7_history / "protocol.json").read_text()))
            self.assertEqual(before, (history / "observations.jsonl").read_text())



if __name__ == "__main__":
    unittest.main()
