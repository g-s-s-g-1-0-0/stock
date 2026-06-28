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

    def test_enrich_industries_updates_target_us_rows_from_valuation_source(self) -> None:
        original_fetch_valuation = build_stock_universe.fetch_valuation

        try:
            build_stock_universe.fetch_valuation = lambda ticker: ["-"] * 20 + ["Technology | Semiconductors"]
            payload, changed = build_stock_universe.enrich_industries(
                {
                    "meta": {"kind": "search-universe"},
                    "rows": [
                        {"ticker": "ALAB", "name": "Astera Labs", "market": "US", "industry": "-"},
                        {"ticker": "AAPL", "name": "Apple", "market": "US", "industry": "-"},
                    ],
                },
                ["ALAB"],
            )
        finally:
            build_stock_universe.fetch_valuation = original_fetch_valuation

        rows = {row["ticker"]: row for row in payload["rows"]}
        self.assertEqual(1, changed)
        self.assertEqual("Technology | Semiconductors", rows["ALAB"]["rawIndustry"])
        self.assertNotEqual("-", rows["ALAB"]["industry"])
        self.assertEqual("-", rows["AAPL"]["industry"])


if __name__ == "__main__":
    unittest.main()
