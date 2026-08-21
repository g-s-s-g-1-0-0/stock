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

    def test_bls_schedule_falls_back_to_wayback_when_live_forbidden(self) -> None:
        html = """
        <table>
          <tr><th>Reference Month</th><th>Release Date</th><th>Release Time</th></tr>
          <tr><td>July 2026</td><td>Aug. 07, 2026</td><td>08:30 AM</td></tr>
          <tr><td>August 2026</td><td>Sep. 04, 2026</td><td>08:30 AM</td></tr>
        </table>
        """
        issues: list[str] = []

        def fake_fetch(url: str, *args: object, **kwargs: object) -> str:
            if "bls.gov/schedule" in url and "web.archive.org" not in url:
                raise urllib.error.HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)  # type: ignore[arg-type]
            if "archive.org/wayback/available" in url:
                return json.dumps({
                    "archived_snapshots": {
                        "closest": {
                            "available": True,
                            "url": "https://web.archive.org/web/20260819054954/https://www.bls.gov/schedule/news_release/empsit.htm",
                        }
                    }
                })
            if "web.archive.org/web/" in url:
                return html
            raise AssertionError(url)

        with patch("calculator.pipeline.fetch_text", side_effect=fake_fetch):
            result = pipeline.fetch_bls_market_events(
                "고용보고서 발표",
                "https://www.bls.gov/schedule/news_release/empsit.htm",
                2026,
                issues,
            )

        self.assertEqual(issues, [])
        self.assertIn(8, result)
        self.assertIn(9, result)
        self.assertEqual(result[8]["date"], "2026. 8. 7")
        self.assertEqual(result[9]["date"], "2026. 9. 4")

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

        self.assertEqual("PCE 발표", pipeline.current_market_event_label(payload, now=before))
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

        self.assertEqual("PPI 발표", pipeline.current_market_event_label(payload, now=noon))

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
