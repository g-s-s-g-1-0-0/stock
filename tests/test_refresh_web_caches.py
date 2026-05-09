import importlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class RefreshWebCachesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.refresh = importlib.import_module("scripts.refresh_web_caches")

    def test_refresh_tickers_includes_open_trades(self) -> None:
        original_load_watchlist_tickers = self.refresh.load_watchlist_tickers
        original_trade_log_paths = self.refresh.TRADE_LOG_PATHS

        try:
            with TemporaryDirectory() as temp_dir:
                trade_logs = Path(temp_dir) / "trade-logs.json"
                trade_logs.write_text(
                    json.dumps({
                        "rows": [
                            {"ticker": "MP", "status": "보유 중"},
                            {"ticker": "NVDA", "status": "익절"},
                        ]
                    }),
                    encoding="utf-8",
                )
                self.refresh.load_watchlist_tickers = lambda: ["AAPL"]
                self.refresh.TRADE_LOG_PATHS = [trade_logs]

                self.assertEqual(["AAPL", "MP"], self.refresh.refresh_tickers())
        finally:
            self.refresh.load_watchlist_tickers = original_load_watchlist_tickers
            self.refresh.TRADE_LOG_PATHS = original_trade_log_paths


if __name__ == "__main__":
    unittest.main()
