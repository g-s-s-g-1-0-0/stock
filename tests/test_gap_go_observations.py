from __future__ import annotations

import importlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _frame(rows: list[dict], ticker: str = "AAA") -> pd.DataFrame:
    index = pd.DatetimeIndex([row["time"] for row in rows])
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], [ticker]])
    data = []
    for row in rows:
        data.append([row["open"], row["high"], row["low"], row["close"], row["volume"]])
    return pd.DataFrame(data, index=index, columns=columns)


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

    def test_previous_close_ignores_the_session_bar_and_blank_premarket_volume(self) -> None:
        ny = self.module.NEW_YORK
        session = datetime(2026, 9, 30, 16, 10, tzinfo=ny)
        daily = _frame([
            {"time": pd.Timestamp("2026-09-28"), "open": 90, "high": 91, "low": 89, "close": 90, "volume": 1},
            {"time": pd.Timestamp("2026-09-29"), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"time": pd.Timestamp("2026-09-30"), "open": 110, "high": 112, "low": 108, "close": 111, "volume": 1},
        ])
        minute_rows = []
        for stamp, price, volume in (
            ("2026-09-30 08:00", 106, 0),
            ("2026-09-30 08:30", 107, 0),
            ("2026-09-30 09:30", 108, 10),
            ("2026-09-30 10:00", 109, 12),
            ("2026-09-30 15:59", 104, 20),
        ):
            minute_rows.append({
                "time": pd.Timestamp(stamp, tz=ny),
                "open": price - 1,
                "high": price + 2,
                "low": price - 3,
                "close": price,
                "volume": volume,
            })
        snapshot = self.module._snapshot(minute=_frame(minute_rows), daily=daily, ticker="AAA", today=session)

        self.assertEqual(100, snapshot["previousClose"])
        self.assertEqual("2026-09-29", snapshot["previousCloseDate"])
        self.assertIsNone(snapshot["premarketVolume"])
        self.assertFalse(snapshot["premarketVolumeKnown"])
        self.assertEqual(101, snapshot["dayLow"])
        self.assertEqual(101, snapshot["lowAfterTen"])
        self.assertEqual(111, snapshot["highAfterTen"])
        self.assertEqual(107, snapshot["regularOpen"])
        self.assertAlmostEqual(0.07, snapshot["gapPct"])
        self.assertTrue(snapshot["gapScreen"])
        self.assertEqual(101, snapshot["previousHigh"])
        self.assertTrue(snapshot["closeAbovePriorHigh"])
        self.assertIsNone(snapshot["ma200"])
        self.assertIsNone(snapshot["elevatedVolume"])

    def test_setup_filters_use_the_200_day_average_and_20_day_volume(self) -> None:
        rows = []
        day = pd.Timestamp("2025-01-02")
        while len(rows) < 210:
            if day.dayofweek < 5:
                rows.append({
                    "time": day,
                    "open": 100,
                    "high": 110,
                    "low": 90,
                    "close": 100,
                    "volume": 100,
                })
            day += pd.Timedelta(days=1)
        rows[-1]["close"] = 130
        rows[-1]["high"] = 140
        rows[-1]["volume"] = 400
        session = rows[-1]["time"].to_pydatetime().replace(tzinfo=self.module.NEW_YORK)
        prior_high = rows[-2]["high"]
        snapshot = self.module._snapshot(
            minute=_frame([{
                "time": pd.Timestamp(session.date().isoformat() + " 15:59", tz=self.module.NEW_YORK),
                "open": 120,
                "high": 135,
                "low": 115,
                "close": 130,
                "volume": 50,
            }]),
            daily=_frame(rows),
            ticker="AAA",
            today=session,
        )
        self.assertEqual(prior_high, snapshot["previousHigh"])
        self.assertTrue(snapshot["aboveMa200"])
        self.assertTrue(snapshot["closeAbovePriorHigh"])
        self.assertAlmostEqual(400 / ((100 * 19 + 400) / 20), snapshot["volRatio20"])
        self.assertTrue(snapshot["elevatedVolume"])

    def test_session_files_keep_the_first_bar_and_the_next_open_separate(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp)
            obs = history / "gap-go-observations-2026-09-30.jsonl"
            obs.write_text(json.dumps({
                "ticker": "AAA",
                "stage": "close",
                "dataAvailable": True,
            }) + "\n", encoding="utf-8")
            first = _frame([
                {"time": pd.Timestamp("2026-09-30"), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 5},
                {"time": pd.Timestamp("2026-10-01"), "open": 13, "high": 14, "low": 12, "close": 14, "volume": 6},
            ])
            written = self.module.ensure_session_files(first, history)
            self.assertEqual(1, len(written))
            revised = _frame([
                {"time": pd.Timestamp("2026-09-30"), "open": 99, "high": 99, "low": 99, "close": 99, "volume": 99},
            ])
            self.assertEqual([], self.module.ensure_session_files(revised, history))
            stored = json.loads((history / "sessions" / "gap-go-session-2026-09-30.jsonl").read_text().splitlines()[0])
            self.assertEqual(10, stored["open"])
            self.assertEqual(9, stored["low"])

            next_obs = history / "gap-go-observations-2026-10-01.jsonl"
            next_obs.write_text(json.dumps({
                "ticker": "AAA",
                "stage": "close",
                "dataAvailable": True,
            }) + "\n", encoding="utf-8")
            self.module.ensure_session_files(first, history)
            nxt = json.loads((history / "sessions" / "gap-go-session-2026-10-01.jsonl").read_text().splitlines()[0])
            self.assertEqual(13, nxt["open"])

    def test_market_context_uses_the_session_bar_not_a_later_one(self) -> None:
        rows = []
        price = 100.0
        day = pd.Timestamp("2025-01-02")
        while len(rows) < 220:
            if day.dayofweek < 5:
                price += 0.8 if len(rows) % 3 else -0.4
                rows.append({
                    "time": day,
                    "open": price - 0.1,
                    "high": price + 0.5,
                    "low": price - 0.5,
                    "close": price,
                    "volume": 1000,
                })
            day += pd.Timedelta(days=1)
        later = dict(rows[-1])
        later["time"] = rows[-1]["time"] + pd.Timedelta(days=1)
        later["close"] = 999
        qqq = _frame(rows + [later], "QQQ")
        vix_rows = []
        for row in rows:
            vix_rows.append({**row, "close": 18, "open": 18, "high": 19, "low": 17})
        vix = _frame(vix_rows, "^VIX")
        daily = pd.concat([qqq, vix], axis=1)
        session = date_of(rows[-1]["time"])
        context = self.module.market_context(daily, session, {
            "breadthPct": 26.2,
            "breadthCount": 2800,
            "breadthStatus": "경고",
            "breadthAsOf": "2026-09-29T21:00:00Z",
        })
        self.assertEqual(session.isoformat(), context["marketBarDate"])
        self.assertNotEqual(999, context["qqqClose"])
        self.assertIsNotNone(context["qqqMa200Dist"])
        self.assertIsNotNone(context["qqqRegime"])
        self.assertIsNotNone(context["qqqRsi"])
        self.assertIsNotNone(context["qqqMacdHist"])
        self.assertEqual(18, context["vix"])
        self.assertEqual(26.2, context["breadthPct"])

    def test_paper_trade_stops_before_the_target_and_keeps_the_first_result(self) -> None:
        import tempfile
        ny = self.module.NEW_YORK
        row = {
            "ticker": "AAA",
            "observationDate": "2026-10-01",
            "gapScreen": True,
            "tenAmBreakout": True,
            "tenAmPrice": 12,
            "tenAmLow": 11.2,
        }
        stopped = self.module.paper_trade(_frame([
            {"time": pd.Timestamp("2026-10-01 10:05", tz=ny), "open": 12, "high": 14, "low": 11.0, "close": 11.1, "volume": 1},
            {"time": pd.Timestamp("2026-10-01 11:00", tz=ny), "open": 11, "high": 11, "low": 11, "close": 11, "volume": 1},
        ]), row)
        self.assertEqual("손절", stopped["outcome"])
        self.assertFalse(stopped["success"])
        self.assertEqual(-1, stopped["rMultiple"])

        held = self.module.paper_trade(_frame([
            {"time": pd.Timestamp("2026-10-01 10:05", tz=ny), "open": 12, "high": 14, "low": 11.5, "close": 13.8, "volume": 1},
            {"time": pd.Timestamp("2026-10-01 11:00", tz=ny), "open": 14, "high": 14.2, "low": 13.8, "close": 14, "volume": 1},
        ]), row)
        self.assertEqual("익절 후 11시 정리", held["outcome"])
        self.assertTrue(held["success"])
        self.assertAlmostEqual(2.25, held["rMultiple"])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gap-go-paper-trades.jsonl"
            self.assertTrue(self.module.merge_paper_trades([stopped], path))
            self.assertFalse(self.module.merge_paper_trades([held], path))
            stored = json.loads(path.read_text().splitlines()[0])
            self.assertEqual("손절", stored["outcome"])


def date_of(value: pd.Timestamp):
    return value.date()


if __name__ == "__main__":
    unittest.main()
