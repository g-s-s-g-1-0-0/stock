import importlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class RefreshWebCachesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.refresh = importlib.import_module("scripts.refresh_web_caches")

    def test_load_watchlist_tickers_includes_all_investment_types(self) -> None:
        original_supabase_request = self.refresh.supabase_request

        try:
            self.refresh.supabase_request = lambda path: [{
                "tickers": ["AAPL"],
                "tickers_by_type": {
                    "long_term": ["MSFT", "AAPL"],
                    "swing": ["NVDA"],
                },
            }]

            self.assertEqual(["AAPL", "MSFT", "NVDA"], self.refresh.load_watchlist_tickers())
        finally:
            self.refresh.supabase_request = original_supabase_request

    def test_refresh_tickers_includes_trade_log_tickers(self) -> None:
        original_load_watchlist_tickers = self.refresh.load_watchlist_tickers
        original_trade_log_paths = self.refresh.TRADE_LOG_PATHS
        original_refresh_tickers = os.environ.get("REFRESH_TICKERS")

        try:
            with TemporaryDirectory() as temp_dir:
                trade_logs = Path(temp_dir) / "trade-logs.json"
                trade_logs.write_text(
                    json.dumps({
                        "rows": [
                            {"ticker": "MP", "status": "보유 중"},
                            {"ticker": "079550", "status": "익절"},
                        ]
                    }),
                    encoding="utf-8",
                )
                self.refresh.load_watchlist_tickers = lambda: ["AAPL"]
                self.refresh.TRADE_LOG_PATHS = [trade_logs]
                os.environ["REFRESH_TICKERS"] = "LRCX, aapl"

                self.assertEqual(["AAPL", "LRCX", "MP", "079550"], self.refresh.refresh_tickers())
        finally:
            self.refresh.load_watchlist_tickers = original_load_watchlist_tickers
            self.refresh.TRADE_LOG_PATHS = original_trade_log_paths
            if original_refresh_tickers is None:
                os.environ.pop("REFRESH_TICKERS", None)
            else:
                os.environ["REFRESH_TICKERS"] = original_refresh_tickers

    def test_stock_universe_task_can_run_without_full_stock_refresh(self) -> None:
        self.assertEqual(["stock-universe", "stocks"], self.refresh.parse_tasks(["stock-universe"]))


if __name__ == "__main__":
    unittest.main()
