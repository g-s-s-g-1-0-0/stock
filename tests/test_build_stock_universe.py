import unittest

from calculator import build_stock_universe


class BuildStockUniverseTest(unittest.TestCase):
    def test_load_us_stocks_skips_file_creation_time_rows(self) -> None:
        original_fetch_text = build_stock_universe.fetch_text

        def fake_fetch_text(url: str) -> str:
            if url == build_stock_universe.NASDAQ_LISTED_URL:
                return "\n".join([
                    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
                    "SPCX|Space Exploration Technologies Corp. - Common Stock|Q|N|N|100|N|N",
                    "File Creation Time: 0612202621:31|||||||",
                ])
            return "\n".join([
                "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol",
                "BNY|The Bank of New York Mellon Corporation Common Stock|N|BNY|N|100|N|BNY",
                "File Creation Time: 0612202621:31|||||||",
            ])

        try:
            build_stock_universe.fetch_text = fake_fetch_text
            tickers = {row["ticker"] for row in build_stock_universe.load_us_stocks()}
        finally:
            build_stock_universe.fetch_text = original_fetch_text

        self.assertIn("SPCX", tickers)
        self.assertIn("BNY", tickers)
        self.assertFalse(any(ticker.startswith("File Creation Time") for ticker in tickers))


if __name__ == "__main__":
    unittest.main()
