import importlib
import unittest


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


if __name__ == "__main__":
    unittest.main()
