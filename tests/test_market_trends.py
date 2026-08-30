import importlib
import json
import unittest
from unittest.mock import MagicMock, patch


class MarketTrendsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = importlib.import_module("calculator.pipeline")

    def test_market_trend_signals_promote_theme_from_price_momentum(self) -> None:
        stocks = [
            {"ticker": "RKLB", "name": "Rocket Lab", "industry": "우주 산업, 소형 발사체, 위성 배포"},
            {"ticker": "ASTS", "name": "AST SpaceMobile", "industry": "우주 산업, 위성통신, LEO 위성, D2D 통신"},
            {"ticker": "PL", "name": "Planet Labs", "industry": "우주 산업, 위성 지구관측 데이터, 위성 이미지"},
            {"ticker": "SLOW", "name": "Slow Software", "industry": "소프트웨어, 클라우드"},
        ]
        technical_rows = {
            "RKLB": {
                "현재가": "$134.15",
                "20일 이동평균선": "$104.87",
                "200일 이동평균선": "$67.09",
                "MA20 5일 기울기": "+11.93%",
                "볼린저밴드 %B (종가)": "83.19",
                "RSI (D)": "74.84",
                "ADX (14, D)": "54.25",
                "+DI (DMI, 14)": "38.86",
                "-DI (DMI, 14)": "9.87",
                "MACD Histogram (D)": "2.38",
                "20일 평균 대비 거래량 (D)": "118%",
            },
            "ASTS": {
                "현재가": "$105.60",
                "20일 이동평균선": "$76.71",
                "200일 이동평균선": "$58.80",
                "MA20 5일 기울기": "+4.37%",
                "볼린저밴드 %B (종가)": "114.90",
                "RSI (D)": "74.50",
                "ADX (14, D)": "45.00",
                "+DI (DMI, 14)": "33.00",
                "-DI (DMI, 14)": "12.00",
                "MACD Histogram (D)": "1.40",
                "20일 평균 대비 거래량 (D)": "132%",
            },
            "PL": {
                "현재가": "$44.56",
                "20일 이동평균선": "$37.20",
                "200일 이동평균선": "$28.10",
                "MA20 5일 기울기": "+3.13%",
                "볼린저밴드 %B (종가)": "90.92",
                "RSI (D)": "62.57",
                "ADX (14, D)": "31.00",
                "+DI (DMI, 14)": "26.00",
                "-DI (DMI, 14)": "18.00",
                "MACD Histogram (D)": "0.70",
                "20일 평균 대비 거래량 (D)": "109%",
            },
            "SLOW": {
                "현재가": "$10.00",
                "20일 이동평균선": "$12.00",
                "200일 이동평균선": "$15.00",
                "MA20 5일 기울기": "-2.00%",
                "볼린저밴드 %B (종가)": "20.00",
                "RSI (D)": "42.00",
            },
        }

        rows = self.pipeline.build_market_trend_signal_rows(stocks, technical_rows)

        self.assertTrue(rows)
        self.assertEqual("우주항공", rows[0]["rankText"].split("|", 1)[0].strip())
        self.assertIn("위성", rows[0]["rankText"])
        self.assertIn("발사체", rows[0]["rankText"])
        self.assertNotIn("RKLB", rows[0]["rankText"])
        self.assertNotIn("ASTS", rows[0]["rankText"])
        self.assertIn("Rocket Lab", rows[0]["stockNames"])
        self.assertIn("AST SpaceMobile", rows[0]["stockNames"])

    def test_merge_market_trend_ranks_keeps_strong_internal_signals_in_top10(self) -> None:
        ranks = [
            "AI 인프라 | 데이터센터, 광통신, 전력",
            "반도체 | AI칩, GPU, HBM",
            "클라우드 컴퓨팅 | 마이크로소프트, 아마존, 구글",
        ]
        signal_rows = [
            {"rankText": "우주항공 | 위성, 발사체, SpaceX", "score": 36.0, "stockCount": 3, "stockNames": ["Rocket Lab", "AST SpaceMobile", "Planet Labs"]},
        ]

        merged = self.pipeline.merge_market_trend_ranks(ranks, signal_rows)

        self.assertEqual("우주항공 | 위성, 발사체, SpaceX", merged[0])
        self.assertIn("AI 인프라 | 데이터센터, 광통신, 전력", merged)

    def test_market_trend_summary_uses_polite_style(self) -> None:
        summary = "이번 주 전체 시장 분위기는 우주항공과 로봇·자동화 분야도 주목을 받고 있다."

        normalized = self.pipeline.normalize_market_trend_summary(summary)

        self.assertEqual("이번 주 전체 시장 분위기는 우주항공과 로봇·자동화 분야도 주목을 받고 있습니다.", normalized)

    def test_market_trend_week_date_normalizes_to_monday(self) -> None:
        self.assertEqual(self.pipeline.market_trend_week_date("2026.07.15"), "2026.07.13")
        # UTC 일요일 라벨은 cron(KST 월요일 00:00) 주차인 다음 월요일로 올린다.
        self.assertEqual(self.pipeline.market_trend_week_date("2026.07.19"), "2026.07.20")
        self.assertEqual(self.pipeline.market_trend_week_date("2026.05.25"), "2026.05.25")

    def test_sanitize_market_trend_rows_keeps_latest_row_per_week(self) -> None:
        rows = [
            {"date": "2026.07.12", "ranks": ["A | a"], "summary": "old sunday"},
            {"date": "2026.07.15", "ranks": ["B | b"], "summary": "mid week"},
            {"date": "2026.07.19", "ranks": ["C | c"], "summary": "latest sunday"},
        ]

        sanitized = self.pipeline.sanitize_market_trend_rows(rows)

        self.assertEqual([row["date"] for row in sanitized], ["2026.07.13", "2026.07.20"])
        self.assertEqual(sanitized[0]["summary"], "mid week")
        self.assertEqual(sanitized[-1]["summary"], "latest sunday")

    def test_parse_market_trend_json_requires_exactly_ten_ranked_items(self) -> None:
        payload = {
            "ranks": [f"테마 {index} | 키워드A, 키워드B, 키워드C" for index in range(1, 11)],
            "summary": "시장 분위기는 선택적 위험선호가 이어지고 있습니다.",
        }

        parsed = self.pipeline.parse_market_trend_json(payload)

        self.assertEqual(10, len(parsed["ranks"]))
        self.assertEqual("테마 1 | 키워드A, 키워드B, 키워드C", parsed["ranks"][0])
        self.assertEqual(payload["summary"], parsed["summary"])

    def test_parse_market_trend_json_rejects_incomplete_rankings(self) -> None:
        payload = {
            "ranks": [f"테마 {index} | 키워드A, 키워드B" for index in range(1, 10)],
            "summary": "시장 요약입니다.",
        }

        with self.assertRaisesRegex(ValueError, "10개"):
            self.pipeline.parse_market_trend_json(payload)

    def test_groq_analysis_retries_invalid_output_with_structured_response(self) -> None:
        invalid = MagicMock()
        invalid.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": "순위 목록"}}],
        }).encode()
        valid = MagicMock()
        valid.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({
                "ranks": [f"테마 {index} | 키워드A, 키워드B" for index in range(1, 11)],
                "summary": "시장 요약입니다.",
            })}}],
        }).encode()

        with patch("calculator.pipeline.urllib.request.urlopen", side_effect=[invalid, valid]) as urlopen:
            result = self.pipeline.analyze_market_trends_with_groq("뉴스", "test-key")

        self.assertEqual(2, urlopen.call_count)
        self.assertEqual(10, len(result["ranks"]))
        request_payload = json.loads(urlopen.call_args_list[0].args[0].data.decode())
        self.assertFalse(request_payload["include_reasoning"])
        self.assertTrue(request_payload["response_format"]["json_schema"]["strict"])


if __name__ == "__main__":
    unittest.main()
