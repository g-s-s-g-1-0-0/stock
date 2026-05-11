import importlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class PipelineValuationCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = importlib.import_module("calculator.pipeline")

    def test_valuation_refresh_preserves_existing_values_when_fetch_returns_empty_fields(self) -> None:
        original_cache_dir = self.pipeline.CACHE_DIR
        original_web_public_api_dir = self.pipeline.WEB_PUBLIC_API_DIR
        original_fetch_valuation = self.pipeline.fetch_valuation
        original_now_iso = self.pipeline.now_iso

        columns = [
            "marketCap", "sales", "salesQoq", "salesYoyTtm", "salesPastYears",
            "currentRatio", "debtToEquity", "priceToFreeCashFlow", "priceToSales",
            "per", "pbr", "roe", "peg", "sharesOutstanding", "grossMargin",
            "operatingMargin", "epsTtm", "epsNextYear", "epsQoq", "earningsDate", "industry",
        ]

        try:
            with TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                self.pipeline.CACHE_DIR = root / "data" / "cache"
                self.pipeline.WEB_PUBLIC_API_DIR = root / "web" / "public" / "api"
                self.pipeline.CACHE_DIR.mkdir(parents=True)
                self.pipeline.WEB_PUBLIC_API_DIR.mkdir(parents=True)
                self.pipeline.now_iso = lambda: "2026-05-11T00:00:00+00:00"

                (self.pipeline.CACHE_DIR / "valuation.json").write_text(
                    json.dumps({
                        "meta": {"kind": "valuation", "lastSuccessfulRun": "previous"},
                        "rows": {
                            "OLD": {
                                "marketCap": "100B",
                                "sales": "50B",
                                "salesQoq": "10.00%",
                                "salesYoyTtm": "20.00%",
                                "operatingMargin": "30.00%",
                                "earningsDate": "2026-05-20",
                                "industry": "기존 산업",
                            }
                        },
                    }),
                    encoding="utf-8",
                )

                def fetch_valuation(ticker: str) -> list[str]:
                    if ticker == "OLD":
                        values = ["-"] * len(columns)
                        values[2] = "11.00%"
                        return values
                    return ["-"] * len(columns)

                self.pipeline.fetch_valuation = fetch_valuation

                payload = self.pipeline.build_valuation_cache([
                    {"ticker": "OLD", "name": "Old", "market": "US", "industry": "기존 산업"},
                    {"ticker": "NEW", "name": "New", "market": "US", "industry": "신규 산업"},
                ])

                old_row = payload["rows"]["OLD"]
                new_row = payload["rows"]["NEW"]

                self.assertEqual("100B", old_row["marketCap"])
                self.assertEqual("50B", old_row["sales"])
                self.assertEqual("11.00%", old_row["salesQoq"])
                self.assertEqual("2026-05-20", old_row["earningsDate"])
                self.assertEqual("50.00%", old_row["ruleOf40"])
                self.assertEqual("-", new_row["marketCap"])
                self.assertEqual("신규 산업", new_row["industry"])
        finally:
            self.pipeline.CACHE_DIR = original_cache_dir
            self.pipeline.WEB_PUBLIC_API_DIR = original_web_public_api_dir
            self.pipeline.fetch_valuation = original_fetch_valuation
            self.pipeline.now_iso = original_now_iso


if __name__ == "__main__":
    unittest.main()
