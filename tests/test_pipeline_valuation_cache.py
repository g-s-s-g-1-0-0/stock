import importlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from calculator.sheet_sources import fetch_us_valuation, stockanalysis_financials


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
                self.assertTrue(old_row["earningsDate"].startswith("2026-05-20"))
                self.assertEqual("50.00%", old_row["ruleOf40"])
                self.assertEqual("-", new_row["marketCap"])
                self.assertEqual("신규 산업", new_row["industry"])
                self.assertEqual(1, payload["meta"]["successfulRows"])
                self.assertEqual("unavailable", new_row["dataStatus"])
                self.assertEqual("NEW", payload["errors"][0]["ticker"])
        finally:
            self.pipeline.CACHE_DIR = original_cache_dir
            self.pipeline.WEB_PUBLIC_API_DIR = original_web_public_api_dir
            self.pipeline.fetch_valuation = original_fetch_valuation
            self.pipeline.now_iso = original_now_iso

    def test_financial_fallback_reads_ttm_column_and_preserves_primary_values(self) -> None:
        html = '''<script type="application/ld+json">{"tickerSymbol":"SPCX"}</script><h1>SpaceX Financials Overview</h1>Millions USD
        <table><tr><th>Fiscal Year</th><th>FY 2025</th><th>TTM</th></tr>
        <tr><td><span id="revenue">Revenue</span></td><td>18,674</td><td>23,044</td></tr>
        <tr><td><span id="epsdil">Earnings Per Share</span></td><td>-1.69</td><td>-2.27</td></tr>
        <tr><td><span id="revenueGrowth">Revenue Growth</span></td><td>33.24%</td><td>121.85%</td></tr></table>'''
        self.assertEqual({1: "23.044B", 16: "-2.27", 3: "121.85%"}, stockanalysis_financials(html, "SPCX"))
        with self.assertRaises(ValueError):
            stockanalysis_financials(html, "OTHER")
        self.assertEqual({}, stockanalysis_financials(html.replace("TTM", "FY 2024"), "SPCX"))
        with patch("calculator.sheet_sources.fetch_text", side_effect=["primary", html]), patch("calculator.sheet_sources.snapshot_value", side_effect=lambda _, label: "99B" if label == "Sales" else "-"):
            values = fetch_us_valuation("SPCX")
        self.assertEqual("$ 99B", values[1])
        self.assertEqual("$ -2.27", values[16])
        self.assertEqual("121.85%", values[3])

    def test_fallback_failure_preserves_primary_and_etfs_do_not_fetch_company_financials(self) -> None:
        with patch("calculator.sheet_sources.fetch_text", side_effect=["primary", OSError("offline")]), patch("calculator.sheet_sources.snapshot_value", return_value="-"):
            self.assertEqual("-", fetch_us_valuation("SPCX")[16])
        fund_html = '<a href="screener?v=111&f=ind_exchangetradedfund">Exchange Traded Fund</a>'
        with patch("calculator.sheet_sources.fetch_text", return_value=fund_html) as fetch, patch("calculator.sheet_sources.snapshot_value", return_value="-"):
            fetch_us_valuation("SOXL")
            self.assertEqual(1, fetch.call_count)

    def test_publish_iso_uses_scheduled_publish_time(self) -> None:
        original_value = os.environ.get("WEB_REFRESH_PUBLISH_AT")
        os.environ["WEB_REFRESH_PUBLISH_AT"] = "2026-05-14T15:00:00Z"
        try:
            self.assertEqual("2026-05-14T15:00:00+00:00", self.pipeline.publish_iso())
        finally:
            if original_value is None:
                os.environ.pop("WEB_REFRESH_PUBLISH_AT", None)
            else:
                os.environ["WEB_REFRESH_PUBLISH_AT"] = original_value

    def test_valuation_publish_iso_uses_scheduled_kst_midnight(self) -> None:
        original_value = os.environ.get("WEB_REFRESH_PUBLISH_AT")
        os.environ["WEB_REFRESH_PUBLISH_AT"] = "2026-05-14T15:00:00Z"
        try:
            self.assertEqual("2026-05-14T15:00:00+00:00", self.pipeline.valuation_publish_iso())
        finally:
            if original_value is None:
                os.environ.pop("WEB_REFRESH_PUBLISH_AT", None)
            else:
                os.environ["WEB_REFRESH_PUBLISH_AT"] = original_value


if __name__ == "__main__":
    unittest.main()
