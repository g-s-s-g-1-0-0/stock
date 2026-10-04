from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import numpy as np
import pandas as pd

from scripts.swing_final_features import PATTERNS, FILTERS, final_feature_frame
from scripts import record_final_candidates as final
from scripts import record_candidate_lab as lab
from scripts import record_swing_research as sr
from research.final_review_20261004.run import portfolio


class FinalFeaturesTest(unittest.TestCase):
    def test_supplement_freezes_all_flags_without_changing_prior_protocol(self):
        days = pd.bdate_range(end="2026-10-05", periods=260)
        parts = {}
        for ticker, price in [("AAA", 100), ("QQQ", 100), ("^VIX", 25)]:
            c = price+np.sin(np.arange(260))
            parts[ticker] = pd.DataFrame({"Open": c-.1, "High": c+1, "Low": c-1, "Close": c, "Volume": 100., "Stock Splits": 0.}, index=days)
        daily = pd.concat(parts, axis=1).swaplevel(0, 1, axis=1)
        now = datetime(2026, 10, 5, 16, 10, tzinfo=sr.NY)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sr.initialize(root/"candidate-lab-v1", lab.PROTOCOL)
            target = root/"candidate-final-v1"
            final.collect_final(daily, ["AAA"], now, target, {"groups": []}, season={})
            record = sr.read_lines(target/"observations.jsonl")[0]
            self.assertEqual(set(PATTERNS), set(record["features"]["finalPatternFlags"]))
            self.assertEqual(set(FILTERS), set(record["features"]["finalFilterFlags"]))
            self.assertEqual(set(final.ARMS), set(record["signals"]))
            self.assertEqual(15, len(record["signals"]))
            self.assertFalse(any(v for k, v in record["signals"].items() if k.startswith("final_s2_")))
            self.assertEqual(lab.PROTOCOL, json.loads((root/"candidate-lab-v1/protocol.json").read_text()))

    def test_midweek_and_confirmed_patterns_do_not_use_future_bars(self):
        index = pd.bdate_range(end="2026-10-02", periods=280).strftime("%Y-%m-%d")
        c = 100 + np.arange(280)*.05 + np.sin(np.arange(280))*3
        b = pd.DataFrame({"Open": c-.3, "High": c+1, "Low": c-1, "Close": c, "Volume": 100.}, index=index)
        full = final_feature_frame(b, b)
        for cut in [267, 277, 278, 279]:
            prefix = final_feature_frame(b.iloc[:cut], b.iloc[:cut])
            self.assertTrue(prefix[[*PATTERNS, *FILTERS]].iloc[-1].equals(full[[*PATTERNS, *FILTERS]].loc[prefix.index[-1]]))

    def test_breakout_retest_uses_frozen_level_and_only_first_touch(self):
        index = pd.bdate_range(end="2026-10-02", periods=255).strftime("%Y-%m-%d")
        b = pd.DataFrame({"Open": 108., "High": 110., "Low": 107., "Close": 109., "Volume": 100.}, index=index)
        b.iloc[250] = [113, 116, 112, 115, 200]
        b.iloc[251] = [115, 117, 114, 116, 100]
        b.iloc[252] = [111, 114, 109.8, 113, 100]
        b.iloc[253] = [111, 114, 109.8, 113, 100]
        f = final_feature_frame(b, b)
        self.assertTrue(f.breakout_first_retest.iloc[252])
        self.assertEqual(110, f.recentBreakoutLevel.iloc[252])
        self.assertFalse(f.breakout_first_retest.iloc[253])


class PortfolioTest(unittest.TestCase):
    def test_cost_cash_limit_next_open_exit_and_no_immediate_reentry(self):
        days = ["2026-10-06", "2026-10-07", "2026-10-08"]
        state = [{"recovery": False, "peak": False} for _ in days]
        arrays = {t: np.array([[100, 115, 99, 114], [120, 121, 119, 120], [120, 121, 119, 120]], float) for t in ["AAA", "BBB"]}
        signals = pd.DataFrame([{"ticker": t, "session": "2026-10-05", "entry": days[0], "recovery": False} for t in arrays]
                              + [{"ticker": t, "session": "2026-10-06", "entry": days[1], "recovery": False} for t in arrays])
        result, curve, fills = portfolio(signals, days, state, arrays, slots=1)
        self.assertEqual("ok", result["status"])
        # A different name can enter after the first exit, but the exited name cannot.
        self.assertEqual(1, len(fills))
        self.assertEqual(days[1], fills[0]["exit"])
        self.assertTrue(all(r["positions"] <= 1 and r["cash"] >= -1e-10 for r in curve))
        expected_first_close = (1/1.002)*1.14*.998
        self.assertAlmostEqual(expected_first_close, curve[0]["equity"])
        same = portfolio(signals, days, state, arrays, slots=1)
        self.assertEqual(result, same[0])

    def test_portfolio_prefix_is_unchanged_by_future_prices(self):
        days = ["2026-10-06", "2026-10-07", "2026-10-08"]
        state = [{"recovery": False, "peak": False} for _ in days]
        arrays = {"AAA": np.array([[100, 101, 99, 100], [100, 101, 99, 100], [100, 151, 99, 150]], float)}
        s = pd.DataFrame([{"ticker": "AAA", "session": "2026-10-05", "entry": days[0], "recovery": False}])
        _, full, _ = portfolio(s, days, state, arrays)
        _, prefix, _ = portfolio(s, days[:2], state[:2], {"AAA": arrays["AAA"][:2]})
        self.assertEqual(full[:2], prefix)


if __name__ == "__main__":
    unittest.main()
