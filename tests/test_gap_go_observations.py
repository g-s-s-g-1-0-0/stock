from __future__ import annotations

import importlib
import unittest
from datetime import datetime, timezone


class GapGoObservationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = importlib.import_module("scripts.record_gap_go_observations")
        self.now = datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc)

    def test_scheduled_slot_survives_github_delay(self) -> None:
        self.assertEqual(
            "premarket",
            self.module.observation_stage(self.now, "20,25,30 13,14 * * 1-5"),
        )
        self.assertEqual(
            "ten_am",
            self.module.observation_stage(self.now, "0,5,10 14,15 * * 1-5"),
        )
        self.assertEqual(
            "close",
            self.module.observation_stage(self.now, "5,10,15 20,21 * * 1-5"),
        )

    def test_manual_run_still_uses_the_local_time_window(self) -> None:
        self.assertIsNone(self.module.observation_stage(self.now))


if __name__ == "__main__":
    unittest.main()
