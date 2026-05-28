from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()
