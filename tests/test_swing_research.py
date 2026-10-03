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


if __name__ == "__main__":
    unittest.main()
