import importlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class SignalSnapshotsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshots = importlib.import_module("scripts.record_signal_snapshots")

    def test_record_daily_signal_snapshots_replaces_same_day_rows(self) -> None:
        original_technical_path = self.snapshots.TECHNICAL_CACHE_PATH
        original_valuation_path = self.snapshots.VALUATION_CACHE_PATH
        original_stocks_path = self.snapshots.STOCKS_CACHE_PATH
        original_history_dir = self.snapshots.HISTORY_DIR
        original_snapshot_date = os.environ.get("SIGNAL_SNAPSHOT_DATE")

        try:
            with TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                technical_path = root / "technical.json"
                valuation_path = root / "valuation.json"
                stocks_path = root / "stocks.json"
                history_dir = root / "history"
                technical_path.write_text(
                    json.dumps({
                        "qqqMarketState": {
                            "premiumPercent": 17.1,
                            "buyBlockMax": 18,
                            "regimeLabel": "급락 후 회복장",
                            "peakTriggered": False,
                        },
                        "rows": {
                            "MU": {
                                "ticker": "MU",
                                "name": "Micron",
                                "market": "US",
                                "opinion": "관망",
                                "entrySignalCodes": "",
                                "entryStrategy": "-",
                                "현재가": "$100.00",
                                "200일 이동평균선": "$80.00",
                                "볼린저밴드 %B (종가)": "111.63",
                                "볼린저밴드 %B (저가)": "106.82",
                                "RSI (D)": "89.08",
                                "MACD Histogram (D)": "26.11",
                                "M - H (D-1)": "21.97",
                                "M - H (D-2)": "17.04",
                                "+DI (DMI, 14)": "61.38",
                                "-DI (DMI, 14)": "3.19",
                                "ADX (14, D)": "64.55",
                                "ADX (14, D-1)": "60.61",
                                "20일 평균 대비 거래량 (D)": "168%",
                                "conditionSummary": "D그룹 6/7",
                            }
                        },
                    }),
                    encoding="utf-8",
                )
                valuation_path.write_text(
                    json.dumps({
                        "rows": {
                            "MU": {
                                "per": "45.17",
                                "pbr": "34.21",
                                "roe": "101.49%",
                            }
                        }
                    }),
                    encoding="utf-8",
                )
                stocks_path.write_text(
                    json.dumps({"rows": [{"ticker": "MU", "name": "Micron", "market": "US"}]}),
                    encoding="utf-8",
                )

                self.snapshots.TECHNICAL_CACHE_PATH = technical_path
                self.snapshots.VALUATION_CACHE_PATH = valuation_path
                self.snapshots.STOCKS_CACHE_PATH = stocks_path
                self.snapshots.HISTORY_DIR = history_dir
                os.environ["SIGNAL_SNAPSHOT_DATE"] = "2026-05-12"

                self.assertEqual(1, self.snapshots.record_daily_signal_snapshots())
                self.assertEqual(1, self.snapshots.record_daily_signal_snapshots())

                lines = (history_dir / "daily-signal-snapshots-2026-05-12.jsonl").read_text(encoding="utf-8").splitlines()
                self.assertEqual(1, len(lines))
                row = json.loads(lines[0])
                self.assertEqual("MU", row["ticker"])
                self.assertEqual(111.63, row["pctB"])
                self.assertEqual(1.68, row["volumeRatio20"])
                self.assertIs(row["hBreakoutCandidate"], True)
                self.assertEqual("111.63", row["technicalIndicators"]["볼린저밴드 %B (종가)"])
                self.assertEqual("45.17", row["valuationIndicators"]["per"])
        finally:
            self.snapshots.TECHNICAL_CACHE_PATH = original_technical_path
            self.snapshots.VALUATION_CACHE_PATH = original_valuation_path
            self.snapshots.STOCKS_CACHE_PATH = original_stocks_path
            self.snapshots.HISTORY_DIR = original_history_dir
            if original_snapshot_date is None:
                os.environ.pop("SIGNAL_SNAPSHOT_DATE", None)
            else:
                os.environ["SIGNAL_SNAPSHOT_DATE"] = original_snapshot_date


class SignalEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshots = importlib.import_module("scripts.record_signal_snapshots")

    def test_signal_events_are_logged_only_when_the_signal_changes(self) -> None:
        originals = (
            self.snapshots.TECHNICAL_CACHE_PATH,
            self.snapshots.VALUATION_CACHE_PATH,
            self.snapshots.STOCKS_CACHE_PATH,
            self.snapshots.HISTORY_DIR,
        )
        original_snapshot_date = os.environ.get("SIGNAL_SNAPSHOT_DATE")

        def technical_payload(opinion: str, entry_strategy: str) -> str:
            return json.dumps({
                "qqqMarketState": {"regimeLabel": "정상장", "peakTriggered": False},
                "rows": {
                    "MU": {
                        "ticker": "MU",
                        "name": "Micron",
                        "market": "US",
                        "opinion": opinion,
                        "entrySignalCodes": "",
                        "entryStrategy": entry_strategy,
                        "현재가": "$100.00",
                    }
                },
            })

        try:
            with TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                technical_path = root / "technical.json"
                history_dir = root / "history"
                (root / "valuation.json").write_text(json.dumps({"rows": {}}), encoding="utf-8")
                (root / "stocks.json").write_text(json.dumps({"rows": []}), encoding="utf-8")

                self.snapshots.TECHNICAL_CACHE_PATH = technical_path
                self.snapshots.VALUATION_CACHE_PATH = root / "valuation.json"
                self.snapshots.STOCKS_CACHE_PATH = root / "stocks.json"
                self.snapshots.HISTORY_DIR = history_dir
                os.environ["SIGNAL_SNAPSHOT_DATE"] = "2026-05-12"
                events_file = history_dir / "events" / "signal-events-2026-05-12.jsonl"

                technical_path.write_text(technical_payload("관망", "-"), encoding="utf-8")
                self.snapshots.record_daily_signal_snapshots()
                self.assertFalse(events_file.exists(), "첫 기록은 비교 대상이 없어 이벤트가 없어야 한다")

                self.snapshots.record_daily_signal_snapshots()
                self.assertFalse(events_file.exists(), "변화가 없으면 이벤트를 남기지 않아야 한다")

                technical_path.write_text(technical_payload("매수", "V1"), encoding="utf-8")
                self.snapshots.record_daily_signal_snapshots()

                lines = events_file.read_text(encoding="utf-8").splitlines()
                self.assertEqual(1, len(lines))
                event = json.loads(lines[0])
                self.assertEqual("MU", event["ticker"])
                self.assertEqual(["entryStrategy", "opinion"], event["changed"])
                self.assertEqual("관망", event["previous"]["opinion"])
                self.assertEqual("매수", event["current"]["opinion"])

                # 스냅샷은 여전히 하루 한 줄만 유지한다.
                snapshot_lines = (history_dir / "daily-signal-snapshots-2026-05-12.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
                self.assertEqual(1, len(snapshot_lines))
        finally:
            (
                self.snapshots.TECHNICAL_CACHE_PATH,
                self.snapshots.VALUATION_CACHE_PATH,
                self.snapshots.STOCKS_CACHE_PATH,
                self.snapshots.HISTORY_DIR,
            ) = originals
            if original_snapshot_date is None:
                os.environ.pop("SIGNAL_SNAPSHOT_DATE", None)
            else:
                os.environ["SIGNAL_SNAPSHOT_DATE"] = original_snapshot_date


if __name__ == "__main__":
    unittest.main()
