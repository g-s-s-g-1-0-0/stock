from __future__ import annotations

import json
import unittest
import urllib.error
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from calculator import pipeline

KST = ZoneInfo("Asia/Seoul")


class MarketEventsTest(unittest.TestCase):
    def test_market_event_verification_auto_updates_only_confirmed_values(self) -> None:
        payload = {
            "meta": {"yearLabel": "2099"},
            "groups": [
                {
                    "title": "CPI 발표",
                    "entries": [
                        {"month": "6월", "date": "2099. 6. 10", "time": "21:30", "dday": "-"},
                    ],
                },
            ],
        }

        sources = {"CPI 발표": {6: {"date": "2099. 6. 11", "time": "21:30"}}}
        with patch("calculator.pipeline.official_market_event_sources", return_value=(sources, [])):
            updated, changes, issues = pipeline.apply_market_event_verification(payload)

        entry = updated["groups"][0]["entries"][0]
        self.assertEqual(entry["date"], "2099. 6. 11")
        self.assertEqual(entry["time"], "21:30")
        self.assertEqual(issues, [])
        self.assertEqual(changes, ["CPI 발표 6월: 2099. 6. 10 21:30 -> 2099. 6. 11 21:30"])

    def test_market_event_verification_keeps_cache_when_source_is_ambiguous(self) -> None:
        payload = {
            "meta": {"yearLabel": "2099"},
            "groups": [
                {
                    "title": "CPI 발표",
                    "entries": [
                        {"month": "6월", "date": "2099. 6. 10", "time": "21:30", "dday": "-"},
                    ],
                },
            ],
        }

        with patch(
            "calculator.pipeline.official_market_event_sources",
            return_value=({"CPI 발표": {}}, ["BLS CPI 공식 일정 조회 실패"]),
        ):
            updated, changes, issues = pipeline.apply_market_event_verification(payload)

        entry = updated["groups"][0]["entries"][0]
        self.assertEqual(entry["date"], "2099. 6. 10")
        self.assertEqual(entry["time"], "21:30")
        self.assertEqual(changes, [])
        self.assertEqual(issues, ["BLS CPI 공식 일정 조회 실패"])

    def test_fomc_schedule_converts_official_et_statement_time_to_kst(self) -> None:
        html = """
        <html><body>
        For 2026:
        Tuesday, January 27, and Wednesday, January 28
        Tuesday, March 17, and Wednesday, March 18
        Tuesday, January 26, and Wednesday, January 27, 2027
        The Committee releases a policy statement at 2 p.m. Eastern Time.
        </body></html>
        """
        issues: list[str] = []
        with patch("calculator.pipeline.fetch_text", return_value=html):
            result = pipeline.fetch_fomc_market_events(2026, issues)

        self.assertEqual(result[1], {"date": "2026. 1. 29", "time": "4:00"})
        self.assertEqual(result[3], {"date": "2026. 3. 19", "time": "3:00"})
        self.assertEqual(issues, [])

    def test_bls_reads_current_official_schedule_after_standard_http_403(self) -> None:
        html = "<table><tr><td>September 2026</td><td>Oct. 15, 2026</td><td>08:30 AM</td></tr></table>"
        forbidden = urllib.error.HTTPError("https://www.bls.gov/schedule", 403, "Forbidden", None, None)
        issues: list[str] = []
        with patch("calculator.pipeline.fetch_text", side_effect=forbidden), patch(
            "calculator.pipeline.fetch_bls_browser_text", return_value=html
        ) as browser, patch("calculator.pipeline.wayback_snapshot_urls") as archive:
            result = pipeline.fetch_bls_market_events("PPI 발표", pipeline.BLS_RELEASE_SCHEDULE_URLS["PPI 발표"], 2026, issues)
        self.assertEqual(result[10], {"date": "2026. 10. 15", "time": "21:30"})
        self.assertEqual(issues, [])
        browser.assert_called_once()
        archive.assert_not_called()

    def test_bls_valid_standard_response_does_not_use_fallback(self) -> None:
        html = "<table><tr><td>September 2026</td><td>Oct. 15, 2026</td><td>08:30 AM</td></tr></table>"
        with patch("calculator.pipeline.fetch_text", return_value=html), patch(
            "calculator.pipeline.fetch_bls_browser_text"
        ) as browser:
            self.assertEqual(pipeline.fetch_bls_schedule_html("https://www.bls.gov/schedule", 2026), (html, "bls-live"))
        browser.assert_not_called()

    def test_bls_empty_or_stale_200_response_tries_current_live_fallback(self) -> None:
        html = "<table><tr><td>September 2026</td><td>Oct. 15, 2026</td><td>08:30 AM</td></tr></table>"
        for invalid in ("<html>Access denied</html>", html.replace("2026", "2025"), html.replace("08:30 AM", "TBD")):
            with self.subTest(invalid=invalid), patch("calculator.pipeline.fetch_text", return_value=invalid), patch(
                "calculator.pipeline.fetch_bls_browser_text", return_value=html
            ):
                self.assertEqual(pipeline.fetch_bls_schedule_html("https://www.bls.gov/schedule", 2026), (html, "bls-live-browser-http"))

    def test_bls_browser_timeout_retries_then_reads_current_schedule(self) -> None:
        html = "<table><tr><td>September 2026</td><td>Oct. 15, 2026</td><td>08:30 AM</td></tr></table>"
        forbidden = urllib.error.HTTPError("https://www.bls.gov/schedule", 403, "Forbidden", None, None)
        with patch("calculator.pipeline.fetch_text", side_effect=forbidden), patch(
            "calculator.pipeline.fetch_bls_browser_text", side_effect=[TimeoutError("timed out"), html]
        ) as browser, patch("calculator.pipeline.sleep"):
            _, source = pipeline.fetch_bls_schedule_html("https://www.bls.gov/schedule", 2026)
        self.assertEqual(source, "bls-live-browser-http")
        self.assertEqual(browser.call_count, 2)

    def test_bls_all_current_sources_unavailable_require_manual_review(self) -> None:
        forbidden = urllib.error.HTTPError("https://www.bls.gov/schedule", 403, "Forbidden", None, None)
        issues: list[str] = []
        with patch("calculator.pipeline.fetch_text", side_effect=forbidden), patch(
            "calculator.pipeline.fetch_bls_browser_text", side_effect=TimeoutError("timed out")
        ), patch("calculator.pipeline.sleep"), patch("calculator.pipeline.wayback_snapshot_urls") as archive:
            result = pipeline.fetch_bls_market_events("PPI 발표", pipeline.BLS_RELEASE_SCHEDULE_URLS["PPI 발표"], 2026, issues)
        self.assertEqual(result, {})
        self.assertEqual(len(issues), 1)
        self.assertIn("bls-live-browser-http=timed out", issues[0])
        archive.assert_not_called()

    def test_bls_browser_http_rejects_error_and_offsite_redirect(self) -> None:
        from unittest.mock import Mock
        for response in (Mock(status_code=403), Mock(status_code=200, url="https://other.example/schedule")):
            with self.subTest(response=response), patch("curl_cffi.requests.get", return_value=response):
                with self.assertRaises((urllib.error.HTTPError, RuntimeError)):
                    pipeline.fetch_bls_browser_text(pipeline.BLS_RELEASE_SCHEDULE_URLS["PPI 발표"])

    def test_browser_live_schedule_change_is_automatically_applied(self) -> None:
        html = "<table><tr><td>September 2099</td><td>Oct. 16, 2099</td><td>09:00 AM</td></tr></table>"
        payload = {"meta": {"yearLabel": "2099"}, "groups": [{"title": "PPI 발표", "entries": [
            {"month": "10월", "date": "2099. 10. 15", "time": "21:30"}
        ]}]}
        forbidden = urllib.error.HTTPError("https://www.bls.gov/schedule", 403, "Forbidden", None, None)
        with patch("calculator.pipeline.fetch_text", side_effect=forbidden), patch(
            "calculator.pipeline.fetch_bls_browser_text", return_value=html
        ), patch("calculator.pipeline.fetch_fomc_market_events", return_value={}), patch(
            "calculator.pipeline.fetch_pce_market_events", return_value={}
        ):
            updated, changes, issues = pipeline.apply_market_event_verification(payload)
        self.assertEqual(updated["groups"][0]["entries"][0]["date"], "2099. 10. 16")
        self.assertEqual(updated["groups"][0]["entries"][0]["time"], "22:00")
        self.assertEqual(len(changes), 1)
        self.assertEqual(issues, [])

    def test_bls_prefers_later_release_when_month_has_two_official_dates(self) -> None:
        html = """
        <table>
          <tr><th>Reference Month</th><th>Release Date</th><th>Release Time</th></tr>
          <tr><td>November 2025</td><td>Jan. 14, 2026</td><td>08:30 AM</td></tr>
          <tr><td>December 2025</td><td>Jan. 30, 2026</td><td>08:30 AM</td></tr>
        </table>
        """
        issues: list[str] = []
        with patch("calculator.pipeline.fetch_bls_schedule_html", return_value=(html, "test")):
            result = pipeline.fetch_bls_market_events(
                "PPI 발표",
                "https://www.bls.gov/schedule/news_release/ppi.htm",
                2026,
                issues,
            )

        self.assertEqual(issues, [])
        self.assertEqual(result[1]["date"], "2026. 1. 30")

    def test_current_market_event_label_is_active_before_release_time(self) -> None:
        payload = {
            "groups": [
                {
                    "title": "PCE 발표",
                    "entries": [{"date": "2026. 5. 28", "time": "21:30"}],
                },
            ],
        }
        before = datetime(2026, 5, 28, 21, 0, tzinfo=KST)
        after = datetime(2026, 5, 28, 22, 0, tzinfo=KST)

        self.assertEqual("개인소비지출물가지수 발표 (PCE)", pipeline.current_market_event_label(payload, now=before))
        self.assertEqual("당분간 없음", pipeline.current_market_event_label(payload, now=after))

    def test_current_market_event_label_keeps_same_day_fallback_without_time(self) -> None:
        payload = {
            "groups": [
                {
                    "title": "PPI 발표",
                    "entries": [{"date": "2026. 5. 13"}],
                },
            ],
        }
        noon = datetime(2026, 5, 13, 12, 0, tzinfo=KST)

        self.assertEqual("생산자물가지수 발표 (PPI)", pipeline.current_market_event_label(payload, now=noon))

    def test_current_market_event_label_ignores_nasdaq_100_rebalancing(self) -> None:
        payload = {
            "groups": [
                {
                    "title": "나스닥 100 리밸런싱",
                    "entries": [{"date": "2026. 6. 22", "time": "22:30"}],
                },
            ],
        }
        before = datetime(2026, 6, 22, 13, 0, tzinfo=KST)

        self.assertEqual("당분간 없음", pipeline.current_market_event_label(payload, now=before))

    def test_market_event_verification_removes_ignored_rebalancing_group(self) -> None:
        payload = {
            "meta": {"yearLabel": "2026"},
            "groups": [
                {"title": "나스닥 100 리밸런싱", "entries": [{"month": "6월", "date": "2026. 6. 22", "dday": "0", "time": "22:30"}]},
                {"title": "네마녀의 날", "entries": [{"month": "6월", "date": "2026. 6. 19", "dday": "-3", "time": "5:00"}]},
            ],
        }

        with patch("calculator.pipeline.official_market_event_sources", return_value=({}, [])):
            updated, _, _ = pipeline.apply_market_event_verification(payload)

        self.assertEqual(["네마녀의 날"], [group["title"] for group in updated["groups"]])


if __name__ == "__main__":
    unittest.main()
