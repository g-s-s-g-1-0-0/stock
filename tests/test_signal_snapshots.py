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
        original_stocks_path = self.snapshots.STOCKS_CACHE_PATH
        original_history_dir = self.snapshots.HISTORY_DIR
        original_snapshot_date = os.environ.get("SIGNAL_SNAPSHOT_DATE")

        try:
            with TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                technical_path = root / "technical.json"
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
                stocks_path.write_text(
                    json.dumps({"rows": [{"ticker": "MU", "name": "Micron", "market": "US"}]}),
                    encoding="utf-8",
                )

                self.snapshots.TECHNICAL_CACHE_PATH = technical_path
                self.snapshots.STOCKS_CACHE_PATH = stocks_path
                self.snapshots.HISTORY_DIR = history_dir
                os.environ["SIGNAL_SNAPSHOT_DATE"] = "2026-05-12"

                self.assertEqual(1, self.snapshots.record_daily_signal_snapshots())
                self.assertEqual(1, self.snapshots.record_daily_signal_snapshots())

                lines = (history_dir / "daily-signal-snapshots-2026-05.jsonl").read_text(encoding="utf-8").splitlines()
                self.assertEqual(1, len(lines))
                row = json.loads(lines[0])
                self.assertEqual("MU", row["ticker"])
                self.assertEqual(111.63, row["pctB"])
                self.assertEqual(1.68, row["volumeRatio20"])
                self.assertIs(row["hBreakoutCandidate"], True)
        finally:
            self.snapshots.TECHNICAL_CACHE_PATH = original_technical_path
            self.snapshots.STOCKS_CACHE_PATH = original_stocks_path
            self.snapshots.HISTORY_DIR = original_history_dir
            if original_snapshot_date is None:
                os.environ.pop("SIGNAL_SNAPSHOT_DATE", None)
            else:
                os.environ["SIGNAL_SNAPSHOT_DATE"] = original_snapshot_date


if __name__ == "__main__":
    unittest.main()
