import unittest
from datetime import datetime, timezone

from calculator.industry_classification import classify_stock
from calculator.industry_review import (
    apply_industry_reviews,
    parse_industry_reviews,
    preserve_reviewed_industries,
    review_universe_industries,
    reviewed_industry_is_fresh,
)
from calculator.pipeline import stock_industry
from calculator import build_stock_universe


class IndustryReviewTest(unittest.TestCase):
    def test_reviewed_industry_expires_after_ten_days(self) -> None:
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)
        fresh = {
            "industry": "데이터센터 전력, 백업발전기",
            "industryReviewedAt": "2026-09-14T15:00:00+00:00",
        }
        stale = {
            "industry": "데이터센터 전력, 백업발전기",
            "industryReviewedAt": "2026-09-01T15:00:00+00:00",
        }
        self.assertTrue(reviewed_industry_is_fresh(fresh, now))
        self.assertFalse(reviewed_industry_is_fresh(stale, now))

    def test_preserve_reviewed_industries_keeps_watchlist_overrides(self) -> None:
        previous = {
            "rows": [{
                "ticker": "GNRC",
                "industry": "데이터센터 전력, 백업발전기, 산업재",
                "category": "성장주",
                "industryReviewedAt": "2026-09-14T15:00:00+00:00",
            }]
        }
        payload = {
            "rows": [{
                "ticker": "GNRC",
                "name": "Generac",
                "industry": "산업재, 장비·제조, 자동화",
                "category": "혼합주",
            }]
        }
        preserved = preserve_reviewed_industries(
            payload,
            previous,
            now=datetime(2026, 9, 17, tzinfo=timezone.utc),
        )
        row = preserved["rows"][0]
        self.assertEqual("데이터센터 전력, 백업발전기, 산업재", row["industry"])
        self.assertEqual("성장주", row["category"])
        self.assertEqual("2026-09-14T15:00:00+00:00", row["industryReviewedAt"])

    def test_parse_industry_reviews_keeps_expected_tickers_only(self) -> None:
        reviews = parse_industry_reviews(
            {
                "reviews": [
                    {"ticker": "GNRC", "industry": "데이터센터 전력, 백업발전기", "category": "성장주"},
                    {"ticker": "AAPL", "industry": "스마트폰", "category": "혼합주"},
                    {"ticker": "gnrc", "industry": "중복", "category": "성장주"},
                ]
            },
            {"GNRC"},
        )
        self.assertEqual(
            [{"ticker": "GNRC", "industry": "데이터센터 전력, 백업발전기", "category": "성장주"}],
            reviews,
        )

    def test_review_universe_updates_non_curated_watchlist_rows(self) -> None:
        payload = {
            "meta": {"kind": "search-universe"},
            "rows": [
                {
                    "ticker": "GNRC",
                    "name": "Generac",
                    "industry": "산업재, 장비·제조, 자동화",
                    "category": "혼합주",
                    "rawIndustry": "Industrials | Industrial Machinery",
                },
                {
                    "ticker": "NVDA",
                    "name": "NVIDIA",
                    "industry": "반도체, AI GPU, 데이터센터, CUDA",
                    "category": "성장주",
                },
            ],
        }

        def fake_request(rows, trend_text):
            self.assertEqual(["GNRC"], [row["ticker"] for row in rows])
            self.assertIn("AI 인프라", trend_text)
            return [{"ticker": "GNRC", "industry": "데이터센터 전력, 백업발전기, 산업재", "category": "성장주"}]

        reviewed, changed = review_universe_industries(
            payload,
            ["GNRC", "NVDA"],
            trend_text="AI 인프라 | 데이터센터 전력",
            api_key="test-key",
            now=datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc),
            request_reviews=fake_request,
        )
        rows = {row["ticker"]: row for row in reviewed["rows"]}
        self.assertEqual(1, changed)
        self.assertEqual("데이터센터 전력, 백업발전기, 산업재", rows["GNRC"]["industry"])
        self.assertEqual("성장주", rows["GNRC"]["category"])
        self.assertEqual("2026-09-14T15:00:00+00:00", rows["GNRC"]["industryReviewedAt"])
        self.assertNotIn("industryReviewedAt", rows["NVDA"])

    def test_apply_industry_reviews_stamps_only_matched_rows(self) -> None:
        payload, changed = apply_industry_reviews(
            {"rows": [{"ticker": "GNRC", "industry": "-"}, {"ticker": "AAPL", "industry": "스마트폰"}]},
            [{"ticker": "GNRC", "industry": "데이터센터 전력, 백업발전기"}],
            "2026-09-14T15:00:00+00:00",
        )
        self.assertEqual(1, changed)
        self.assertEqual("데이터센터 전력, 백업발전기", payload["rows"][0]["industry"])
        self.assertEqual("스마트폰", payload["rows"][1]["industry"])

    def test_stock_industry_prefers_fresh_review_over_finviz_keyword(self) -> None:
        finviz_row = {
            "ticker": "GNRC",
            "name": "Generac",
            "market": "US",
            "rawIndustry": "Industrials | Industrial Machinery",
        }
        reviewed_row = {
            **finviz_row,
            "industry": "데이터센터 전력, 백업발전기, 산업재",
            "industryReviewedAt": "2026-09-14T15:00:00+00:00",
        }
        self.assertEqual("산업재, 장비·제조, 자동화", classify_stock(finviz_row)["industry"])
        self.assertEqual("데이터센터 전력, 백업발전기, 산업재", stock_industry(reviewed_row))

    def test_stock_industry_keeps_curated_label(self) -> None:
        stock = {
            "ticker": "NVDA",
            "name": "NVIDIA",
            "industry": "잘못된 라벨",
            "industryReviewedAt": "2026-09-14T15:00:00+00:00",
        }
        self.assertEqual("반도체, AI GPU, 데이터센터, CUDA", stock_industry(stock))

    def test_enrich_preserves_fresh_reviewed_industry(self) -> None:
        original_fetch_valuation = build_stock_universe.fetch_valuation
        try:
            build_stock_universe.fetch_valuation = lambda ticker: ["-"] * 20 + ["Industrials | Industrial Machinery"]
            payload, changed = build_stock_universe.enrich_industries(
                {
                    "rows": [{
                        "ticker": "GNRC",
                        "name": "Generac",
                        "market": "US",
                        "industry": "데이터센터 전력, 백업발전기, 산업재",
                        "category": "성장주",
                        "industryReviewedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    }],
                },
                ["GNRC"],
            )
        finally:
            build_stock_universe.fetch_valuation = original_fetch_valuation

        row = payload["rows"][0]
        self.assertEqual(1, changed)
        self.assertEqual("Industrials | Industrial Machinery", row["rawIndustry"])
        self.assertEqual("데이터센터 전력, 백업발전기, 산업재", row["industry"])
        self.assertEqual("성장주", row["category"])


if __name__ == "__main__":
    unittest.main()
