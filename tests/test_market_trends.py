import importlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape
from unittest.mock import MagicMock, patch


class MarketTrendsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = importlib.import_module("calculator.pipeline")
        self.news = [{"title": f"News {i}", "url": f"https://example.com/{i}", "source": "https://example.com/feed", "publishedAt": "2026-10-12T00:00:00+00:00"} for i in range(1, 11)]

    def analysis_payload(self):
        return {"ranks": [{"sector": f"테마 {i}", "keywords": ["키워드A", "키워드B", "키워드C"], "headlineIds": [i]} for i in range(1, 11)], "summary": "시장 요약입니다."}

    def api_response(self, payload):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}]}).encode()
        return response

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

    def test_market_trend_summary_normalizes_noun_mood_endings(self) -> None:
        summary = (
            "인공지능과 데이터센터 인프라가 주도하며 전력·전기·네트워크 부문이 가속화되는 가운데, "
            "전통적 성장산업은 상대적으로 둔화된 분위기."
        )

        normalized = self.pipeline.normalize_market_trend_summary(summary)

        self.assertTrue(normalized.endswith("둔화된 분위기입니다."))

    def test_market_trend_summary_closes_truncated_rise_phrase(self) -> None:
        summary = (
            "주식 시장은 인공지능과 데이터센터, 로봇·자동화 등 고성장 기술 섹터에 자금이 집중되며, "
            "전력·우주·광통신 등 인프라 부문도 견고한 상승세를."
        )

        normalized = self.pipeline.normalize_market_trend_summary(summary)

        self.assertEqual(
            "주식 시장은 인공지능과 데이터센터, 로봇·자동화 등 고성장 기술 섹터에 자금이 집중되며, "
            "전력·우주·광통신 등 인프라 부문도 견고한 상승세입니다.",
            normalized,
        )

    def test_clip_market_trend_summary_keeps_one_short_sentence(self) -> None:
        summary = (
            "이번 주 전체 시장 분위기는 기술과 금융 분야에서 새로운 동향과 발전이 나타남에 따라 "
            "투자자들의 관심이 집중되는 가운데, 이란 전쟁과 경제적 불안정성으로 인해 시장의 불확실성이 커지고 있습니다."
        )

        clipped = self.pipeline.clip_market_trend_summary(summary)

        self.assertLessEqual(len(clipped), 80)
        self.assertEqual(
            "이번 주 전체 시장 분위기는 기술과 금융 분야에서 새로운 동향과 발전이 나타남에 따라 투자자들의 관심이 집중됩니다.",
            clipped,
        )

    def test_parse_market_trend_json_clips_long_summary(self) -> None:
        payload = {
            "ranks": [f"테마 {index} | 키워드A, 키워드B, 키워드C" for index in range(1, 11)],
            "summary": (
                "이번 주 전체 시장 분위기는 기술과 금융 분야에서 새로운 동향과 발전이 나타남에 따라 "
                "투자자들의 관심이 집중되는 가운데, 이란 전쟁과 경제적 불안정성으로 인해 시장의 불확실성이 커지고 있습니다."
            ),
        }

        parsed = self.pipeline.parse_market_trend_json(payload)

        self.assertLessEqual(len(parsed["summary"]), 80)

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
        self.assertEqual(sanitized[0]["ranks"], ["B | b"])
        self.assertEqual(sanitized[-1]["ranks"], ["C | c"])

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

    def test_parse_market_trend_json_rejects_duplicate_sector_names(self) -> None:
        payload = {
            "ranks": [
                "AI 반도체 | GPU, HBM, ASIC",
                "AI반도체 | 첨단패키징, 파운드리, 메모리",
                *[f"테마 {index} | 키워드A, 키워드B" for index in range(3, 11)],
            ],
            "summary": "시장 요약입니다.",
        }

        with self.assertRaisesRegex(ValueError, "중복"):
            self.pipeline.parse_market_trend_json(payload)

    def test_groq_analysis_retries_invalid_output_with_structured_response(self) -> None:
        invalid = MagicMock()
        invalid.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": "순위 목록"}}],
        }).encode()
        valid = MagicMock()
        valid.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps(self.analysis_payload())}}],
        }).encode()

        with patch("calculator.pipeline.urllib.request.urlopen", side_effect=[invalid, valid]) as urlopen:
            result = self.pipeline.analyze_market_trends_with_groq(json.dumps(self.news), "test-key")

        self.assertEqual(2, urlopen.call_count)
        self.assertEqual(10, len(result["ranks"]))
        request_payload = json.loads(urlopen.call_args_list[0].args[0].data.decode())
        self.assertEqual("openai/gpt-oss-20b", request_payload["model"])
        self.assertEqual(4096, request_payload["max_completion_tokens"])
        self.assertNotIn("max_tokens", request_payload)
        self.assertFalse(request_payload["include_reasoning"])
        self.assertTrue(request_payload["response_format"]["json_schema"]["strict"])

    def test_groq_analysis_retries_json_validation_error_without_weakening_schema(self) -> None:
        failed_body = io.BytesIO(json.dumps({
            "error": {
                "message": "Failed to validate JSON.",
                "code": "json_validate_failed",
                "failed_generation": "",
            },
        }).encode())
        validation_error = self.pipeline.urllib.error.HTTPError(
            self.pipeline.GROQ_CHAT_COMPLETIONS_URL,
            400,
            "Bad Request",
            {},
            failed_body,
        )
        valid = MagicMock()
        valid.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps(self.analysis_payload())}}],
        }).encode()

        with patch("calculator.pipeline.urllib.request.urlopen", side_effect=[validation_error, valid]) as urlopen, patch("calculator.pipeline.sleep"):
            result = self.pipeline.analyze_market_trends_with_groq(json.dumps(self.news), "test-key")

        self.assertEqual(10, len(result["ranks"]))
        retry_payload = json.loads(urlopen.call_args_list[1].args[0].data.decode())
        self.assertTrue(retry_payload["response_format"]["json_schema"]["strict"])
        self.assertIn("json_validate_failed", retry_payload["messages"][-1]["content"])

    def test_market_trend_failure_keeps_groq_error_detail_in_metadata(self) -> None:
        failed_body = io.BytesIO(json.dumps({
            "error": {
                "message": "Failed to validate JSON.",
                "code": "json_validate_failed",
            },
        }).encode())
        validation_error = self.pipeline.urllib.error.HTTPError(
            self.pipeline.GROQ_CHAT_COMPLETIONS_URL,
            400,
            "Bad Request",
            {},
            failed_body,
        )
        signal_rows = [{
            "rankText": "AI 반도체 | GPU, HBM, ASIC",
            "score": 10.0,
            "stockCount": 2,
            "stockNames": ["NVIDIA", "Broadcom"],
        }]

        with (
            patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}),
            patch.object(self.pipeline, "read_cache", return_value={"meta": {"lastSuccessfulRun": "previous-success"}, "rows": [{"date": "2026.10.05", "ranks": ["AI 반도체 | GPU, HBM, ASIC"], "summary": "기존 시장 요약입니다."}]}),
            patch.object(self.pipeline, "build_market_trend_signal_rows", return_value=signal_rows),
            patch.object(self.pipeline, "fetch_market_trend_news", return_value="뉴스"),
            patch.object(self.pipeline, "analyze_market_trends_with_groq", side_effect=validation_error),
        ):
            result = self.pipeline.build_market_trends_cache()

        self.assertIn("json_validate_failed", result["meta"]["failedReason"])
        self.assertEqual("2026.10.05", result["rows"][-1]["date"])
        self.assertEqual("previous-success", result["meta"]["lastSuccessfulRun"])
        self.assertEqual("failed", result["meta"]["analysisStatus"])
        self.assertNotIn("json_validate_failed", result["rows"][-1]["summary"])

    def test_market_trend_model_ignores_retired_or_unsupported_override(self) -> None:
        with patch.dict("os.environ", {"GROQ_MARKET_TREND_MODEL": "llama-3.3-70b-versatile"}):
            self.assertEqual("openai/gpt-oss-20b", self.pipeline.market_trend_model())


    def test_structured_news_analysis_formats_locally_and_keeps_source_evidence(self):
        result = self.pipeline.parse_market_trend_json(self.analysis_payload(), self.news)
        self.assertEqual("테마 1 | 키워드A, 키워드B, 키워드C", result["ranks"][0])
        self.assertEqual(self.news[0], result["newsEvidence"][0]["articles"][0])

    def test_structured_analysis_rejects_invalid_fields_and_fake_news_ids(self):
        for replacement in ["테마 | 키워드", {"sector": "English sector", "keywords": ["A", "B", "C"], "headlineIds": [1]}, {"sector": "테마", "keywords": ["A", "A", "C"], "headlineIds": [1]}, {"sector": "테마", "keywords": ["하나"], "headlineIds": [1]},
                            {"sector": "테마", "keywords": ["A", "B", "C"], "headlineIds": [11]},
                            {"sector": "테마", "keywords": ["A", "B", "C"], "headlineIds": [True]},
                            {"sector": "테마", "keywords": ["A", "B", "C"], "headlineIds": []}]:
            with self.subTest(replacement=replacement):
                payload = self.analysis_payload()
                payload["ranks"][0] = replacement
                with self.assertRaises(ValueError):
                    self.pipeline.parse_market_trend_json(payload, self.news)

    def test_structured_analysis_rejects_duplicate_sector_after_normalization(self):
        payload = self.analysis_payload()
        payload["ranks"][0]["sector"] = "AI 반도체"
        payload["ranks"][1]["sector"] = "AI반도체"
        with self.assertRaisesRegex(ValueError, "중복"):
            self.pipeline.parse_market_trend_json(payload, self.news)

    def test_retry_receives_validation_feedback_and_uses_second_model(self):
        invalid = self.analysis_payload()
        invalid["ranks"][0]["headlineIds"] = [100]
        with patch("calculator.pipeline.urllib.request.urlopen", side_effect=[self.api_response(invalid), self.api_response(invalid), self.api_response(self.analysis_payload())]) as request:
            result = self.pipeline.analyze_market_trends_with_groq(json.dumps(self.news), "test-key")
        self.assertEqual("news-verified", result["analysis"]["status"])
        self.assertEqual(3, result["analysis"]["attempts"])
        last = json.loads(request.call_args.args[0].data)
        self.assertEqual("openai/gpt-oss-120b", last["model"])
        self.assertIn("headlineIds", last["messages"][-1]["content"])
        self.assertTrue(last["response_format"]["json_schema"]["strict"])
        self.assertEqual("object", last["response_format"]["json_schema"]["schema"]["properties"]["ranks"]["items"]["type"])

    def test_truncated_or_missing_api_choices_are_repaired(self):
        for envelope in [{"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": json.dumps(self.analysis_payload())}}]}]:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(envelope).encode()
            with self.subTest(envelope=envelope), patch("calculator.pipeline.urllib.request.urlopen", side_effect=[response, self.api_response(self.analysis_payload())]):
                result = self.pipeline.analyze_market_trends_with_groq(json.dumps(self.news), "test-key")
            self.assertEqual(2, result["analysis"]["attempts"])
            self.assertEqual(1, len(result["analysis"]["recoveryErrors"]))

    def test_transient_rate_limit_is_retried(self):
        error = self.pipeline.urllib.error.HTTPError("https://api.groq.com", 429, "rate limited", {}, io.BytesIO(b"rate limited"))
        with patch("calculator.pipeline.urllib.request.urlopen", side_effect=[error, self.api_response(self.analysis_payload())]), patch("calculator.pipeline.sleep"):
            result = self.pipeline.analyze_market_trends_with_groq(json.dumps(self.news), "test-key")
        self.assertEqual(2, result["analysis"]["attempts"])

    def test_authentication_error_does_not_retry(self):
        error = self.pipeline.urllib.error.HTTPError("https://api.groq.com", 401, "unauthorized", {}, io.BytesIO(b"unauthorized"))
        with patch("calculator.pipeline.urllib.request.urlopen", side_effect=error) as request:
            with self.assertRaises(self.pipeline.urllib.error.HTTPError):
                self.pipeline.analyze_market_trends_with_groq(json.dumps(self.news), "test-key")
        self.assertEqual(1, request.call_count)

    def test_private_signals_never_leave_in_news_api_request(self):
        signals = [{"rankText": "PRIVATE_SIGNAL | PRIVATE_KEYWORD", "score": 999, "stockCount": 1, "stockNames": ["PRIVATE_HOLDING"]}]
        with patch("calculator.pipeline.urllib.request.urlopen", return_value=self.api_response(self.analysis_payload())) as request:
            result = self.pipeline.analyze_market_trends_with_groq(json.dumps(self.news), "test-key", signals)
        sent_body = request.call_args.args[0].data.decode()
        self.assertNotIn("PRIVATE_", sent_body)
        self.assertIn("PRIVATE_SIGNAL", result["ranks"][0])

    def test_exhausted_validation_attempts_raise_instead_of_returning_internal_ranks(self):
        with patch("calculator.pipeline.urllib.request.urlopen", return_value=self.api_response({"ranks": [], "summary": "시장 요약입니다."})) as request:
            with self.assertRaisesRegex(RuntimeError, "3회"):
                self.pipeline.analyze_market_trends_with_groq(json.dumps(self.news), "test-key")
        self.assertEqual(3, request.call_count)

    def test_rss_collection_filters_old_future_and_duplicate_items_and_keeps_links(self):
        now = datetime.now(timezone.utc)
        def item(title, published):
            return f"<item><title>{escape(title)}</title><link>https://example.com/article</link><pubDate>{format_datetime(published)}</pubDate></item>"
        items = [item(f"News {i} &amp; finance", now - timedelta(hours=1)) for i in range(10)]
        items += [item("Old", now - timedelta(days=8)), item("Future", now + timedelta(days=1)), items[0], "<item><title>Missing date</title></item>"]
        feed = "<rss><channel><title>Feed title</title>" + "".join(items) + "</channel></rss>"
        with patch.object(self.pipeline, "NEWS_SOURCES", ["https://example.com/feed"]), patch.object(self.pipeline, "fetch_text_retry", return_value=feed):
            result = json.loads(self.pipeline.fetch_market_trend_news())
        self.assertEqual(10, len(result))
        self.assertEqual("https://example.com/article", result[0]["url"])
        self.assertEqual("https://example.com/feed", result[0]["source"])

    def test_empty_news_collection_fails_explicitly(self):
        with patch.object(self.pipeline, "NEWS_SOURCES", ["https://example.com/feed"]), patch.object(self.pipeline, "fetch_text_retry", return_value="<rss/>"):
            with self.assertRaisesRegex(RuntimeError, "최소 10건"):
                self.pipeline.fetch_market_trend_news()

    def test_missing_api_key_preserves_previous_success_and_does_not_create_new_report(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": ""}), patch.object(self.pipeline, "read_cache", return_value={"meta": {"lastSuccessfulRun": "previous"}, "rows": []}):
            result = self.pipeline.build_market_trends_cache()
        self.assertEqual([], result["rows"])
        self.assertEqual("previous", result["meta"]["lastSuccessfulRun"])
        self.assertEqual("failed", result["meta"]["analysisStatus"])

    def test_successful_cache_contains_news_provenance(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}), patch.object(self.pipeline, "read_cache", return_value={"rows": []}), patch.object(self.pipeline, "build_market_trend_signal_rows", return_value=[]), patch.object(self.pipeline, "fetch_market_trend_news", return_value=json.dumps(self.news)), patch("calculator.pipeline.urllib.request.urlopen", return_value=self.api_response(self.analysis_payload())):
            result = self.pipeline.build_market_trends_cache()
        self.assertEqual("news-verified", result["meta"]["analysisStatus"])
        self.assertIsNone(result["meta"]["failedReason"])
        self.assertEqual(10, len(result["rows"][-1]["newsEvidence"]))
        self.assertEqual(10, result["rows"][-1]["analysis"]["newsCount"])


if __name__ == "__main__":
    unittest.main()
