from __future__ import annotations

import importlib
import json
import os
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT_DIR = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT_DIR / ".github" / "workflows" / "web-data-refresh.yml"


class WebRefreshWorkflowTest(unittest.TestCase):
    def test_workflow_preserves_previous_snapshot_outside_commit_paths(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn('"$RUNNER_TEMP/stocks.before-refresh.json"', workflow)
        self.assertIn('"$RUNNER_TEMP/technical.before-refresh.json"', workflow)
        self.assertIn('"$RUNNER_TEMP/trade-logs.before-refresh.json"', workflow)
        self.assertIn('"$RUNNER_TEMP/search-universe.before-refresh.json"', workflow)
        self.assertIn(
            'python scripts/web_refresh_notifications.py opinion --previous "$RUNNER_TEMP/stocks.before-refresh.json" --previous-trade-logs "$RUNNER_TEMP/trade-logs.before-refresh.json"',
            workflow,
        )
        self.assertNotIn("python scripts/web_refresh_notifications.py trade-exit", workflow)
        self.assertIn(
            "PREVIOUS_STOCKS_PATH: ${{ runner.temp }}/stocks.before-refresh.json",
            workflow,
        )
        self.assertIn(
            "PREVIOUS_TECHNICAL_PATH: ${{ runner.temp }}/technical.before-refresh.json",
            workflow,
        )
        self.assertNotIn("data/cache/stocks.before-refresh.json", workflow)

    def test_workflow_sends_emails_before_committing_refreshed_state(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        update_trade_logs_index = workflow.index("- name: Update trade logs")
        wait_index = workflow.index("- name: Wait until scheduled publish time")
        send_opinion_index = workflow.index("- name: Send opinion change emails")
        send_peak_index = workflow.index("- name: Send Nasdaq peak emails")
        send_weekly_trend_index = workflow.index("- name: Send weekly trend report emails")
        send_stock_universe_index = workflow.index("- name: Send stock universe update email")
        commit_state_index = workflow.index("- name: Commit refreshed caches and notification state")
        record_logs_index = workflow.index("- name: Record stock-level operation logs")
        verify_auth_index = workflow.index("- name: Verify production auth config")
        failure_index = workflow.index("- name: Notify admins on failure")

        self.assertLess(update_trade_logs_index, wait_index)
        self.assertLess(wait_index, send_opinion_index)
        self.assertLess(send_opinion_index, commit_state_index)
        self.assertLess(send_peak_index, commit_state_index)
        self.assertLess(wait_index, send_weekly_trend_index)
        self.assertLess(send_weekly_trend_index, commit_state_index)
        self.assertLess(wait_index, send_stock_universe_index)
        self.assertLess(send_stock_universe_index, commit_state_index)
        self.assertLess(commit_state_index, record_logs_index)
        self.assertLess(record_logs_index, verify_auth_index)
        self.assertLess(commit_state_index, failure_index)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn('  schedule:', workflow)
        self.assertIn('- cron: "0 15 * * *"', workflow)
        self.assertIn('- cron: "0 15 * * 0"', workflow)
        self.assertNotIn('- cron: "0,10,20,30,40,50 23 * * 0-4"', workflow)
        self.assertNotIn('- cron: "30,40,50 0 * * 1-5"', workflow)
        self.assertIn('if [ "${{ github.event.schedule }}" = "0 15 * * 0" ]; then', workflow)
        self.assertIn("- name: Send earnings D-1 emails", workflow)
        self.assertIn("python scripts/web_refresh_notifications.py earnings", workflow)
        self.assertIn('cancel-in-progress: false', workflow)
        self.assertIn("scheduled_publish_at:", workflow)
        self.assertIn("refresh_tickers:", workflow)
        self.assertNotIn("ma_support_scan_slot:", workflow)
        self.assertIn('RAW_PUBLISH_AT="${{ inputs.scheduled_publish_at || \'\' }}"', workflow)
        self.assertIn('if [ "$RAW_PUBLISH_AT" = "immediate" ]; then', workflow)
        self.assertIn("if now.minute >= 50 else", workflow)
        self.assertIn("WEB_REFRESH_PUBLISH_AT=$PUBLISH_AT", workflow)
        self.assertIn("FORCE_REFRESH=$FORCE_REFRESH", workflow)
        self.assertNotIn("MA_SUPPORT_SCAN", workflow)
        self.assertIn("REFRESH_TICKERS=${{ inputs.refresh_tickers || '' }}", workflow)
        self.assertIn('market-trends) TASKS="stock-universe market-trends" ;;', workflow)
        self.assertIn("python scripts/record_web_api_logs.py --trade-logs-only $REFRESH_TASKS", workflow)
        self.assertIn("python scripts/web_refresh_notifications.py weekly-trend", workflow)
        self.assertIn('python scripts/web_refresh_notifications.py stock-universe-report --previous "$RUNNER_TEMP/search-universe.before-refresh.json"', workflow)
        self.assertNotIn("python scripts/web_refresh_notifications.py bb-pullback", workflow)
        self.assertNotIn("python scripts/web_refresh_notifications.py ma-support", workflow)
        self.assertIn("python scripts/record_web_api_logs.py --skip-trade-log-update $REFRESH_TASKS", workflow)
        self.assertIn("git diff --cached --quiet -- data/cache data/history data/search_universe.json web/public/api", workflow)
        self.assertIn("git add data/cache data/history data/search_universe.json web/public/api", workflow)
        self.assertIn('git commit -m "Update scheduled web data caches"', workflow)
        self.assertIn("python scripts/verify_web_auth_config.py", workflow)
        self.assertIn("프로덕션 웹 번들에 Supabase 로그인 설정이 없습니다.", workflow)
        self.assertNotIn("npx --yes vercel@latest deploy --prod", workflow)
        self.assertNotIn("- name: Deploy refreshed web", workflow)

class WebRefreshNotificationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.notifications = importlib.import_module("scripts.web_refresh_notifications")

    def test_opinion_changes_detects_buy_signal_with_explicit_previous_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"

            previous.write_text(
                json.dumps({"rows": [{"ticker": "MP", "name": "MP", "opinion": "관망"}]}),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps({"rows": [{"ticker": "MP", "name": "MP", "opinion": "매수"}]}),
                encoding="utf-8",
            )
            technical.write_text(json.dumps({"rows": {"MP": {"conditionSummary": "buy"}}}), encoding="utf-8")

            changes = self.notifications.opinion_changes(previous, current, technical)

        self.assertEqual(1, len(changes))
        self.assertEqual("MP", changes[0]["ticker"])
        self.assertEqual("관망", changes[0]["from"])
        self.assertEqual("매수", changes[0]["to"])
        self.assertEqual("신규 진입", changes[0]["entryNote"])

    def test_opinion_changes_treats_new_buy_signal_as_watch_to_buy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"

            previous.write_text(json.dumps({"rows": []}), encoding="utf-8")
            current.write_text(
                json.dumps({
                    "rows": [
                        {
                            "ticker": "012450",
                            "name": "한화에어로스페이스",
                            "opinion": "매수",
                            "currentPrice": "₩1,307,000",
                            "strategies": ["2. 상승 추세 이평선 눌림목"],
                        },
                        {"ticker": "WATCH", "name": "New Watch", "opinion": "관망"},
                    ]
                }),
                encoding="utf-8",
            )
            technical.write_text(
                json.dumps({"rows": {"012450": {"entrySignalCodes": "F", "저가%B": "2.50"}}}),
                encoding="utf-8",
            )

            changes = self.notifications.opinion_changes(previous, current, technical)

        self.assertEqual(1, len(changes))
        self.assertEqual("012450", changes[0]["ticker"])
        self.assertEqual("관망", changes[0]["from"])
        self.assertEqual("매수", changes[0]["to"])
        self.assertEqual("신규 진입", changes[0]["entryNote"])

    def test_opinion_email_body_labels_additional_buy(self) -> None:
        body = self.notifications.opinion_email_body([
            {
                "ticker": "375500",
                "name": "DL이앤씨",
                "from": "매수",
                "to": "매수",
                "price": "₩92,300",
                "reason": "2. 상승 추세 이평선 눌림목",
                "recommendedSellPrice": "₩110,760",
                "entryNote": "재진입 1회차 — 최초 진입가 ₩95,400",
            }
        ])

        self.assertIn("매수(보유중)", body)
        self.assertIn("추가 매수", body)
        self.assertNotIn("'매수'</span>", body)
        self.assertNotIn(">매수</strong><br>", body)
        self.assertIn("권장 매도가", body)
        self.assertIn("₩110,760", body)
        self.assertIn("매크로 참고", body)

    def test_opinion_email_body_can_hide_recommended_sell_price(self) -> None:
        body = self.notifications.opinion_email_body([
            {
                "ticker": "375500",
                "name": "DL이앤씨",
                "from": "관망",
                "to": "매수",
                "price": "₩92,300",
                "reason": "2. 상승 추세 이평선 눌림목",
                "recommendedSellPrice": "₩110,760",
                "entryNote": "신규 진입",
            }
        ], include_recommended_sell_price=False)

        self.assertNotIn("권장 매도가", body)
        self.assertNotIn("₩110,760", body)

    def test_strategy2_buy_reason_uses_email_format_without_fixed_target_price(self) -> None:
        trade = {
            "ticker": "SOXL",
            "strategy": "2. 상승 추세 이평선 눌림목",
            "buyPrice": "$100.00",
        }
        stock = {
            "ticker": "SOXL",
            "name": "Direxion Daily Semiconductor Bull 3X ETF",
            "currentPrice": "$100.00",
            "strategies": ["2. 상승 추세 이평선 눌림목"],
        }
        technical = {
            "entrySignalCodes": "2",
            "20일 이동평균선": "$98.00",
            "60일 이동평균선": "$95.00",
            "200일 이동평균선": "$90.00",
            "RSI (D)": "58.20",
        }

        # 청산은 회복장 종료 시점에 판단하므로 고정 목표가를 제시하지 않는다.
        self.assertEqual("-", self.notifications.recommended_sell_price_for_trade(trade, stock, technical))
        reason = self.notifications.buy_reason_for_trade(trade, stock, technical)

        self.assertIn("2. 상승 추세 이평선 눌림목", reason)
        self.assertIn("MA20 $98.00", reason)
        self.assertIn("MA60 $95.00", reason)
        self.assertIn("MA200 $90.00", reason)
        self.assertIn("RSI 58.20", reason)

    def test_opinion_email_body_includes_trade_exit_in_sell_summary(self) -> None:
        body = self.notifications.opinion_email_body([
            {
                "ticker": "WULF",
                "name": "TeraWulf",
                "from": "보유 중",
                "to": "매도",
                "price": "$25.84",
                "reason": "목표 수익 달성 즉시 매도 +13.13% [급락 후 회복장 20일선 눌림 기준 +12%]",
                "entryNote": "진입가 $22.84 (2026.05.23) · 수익률 +13.13%",
            }
        ], sell_opinions=[])

        self.assertIn("현재 매도 의견 종목", body)
        self.assertIn("TeraWulf (WULF)", body)
        self.assertNotIn("현재 매도 의견/청산 종목:</strong> 없음", body)

    def test_stock_universe_report_email_body_lists_changes(self) -> None:
        body = self.notifications.stock_universe_report_email_body(
            {
                "previousCount": 100,
                "currentCount": 101,
                "added": [{"ticker": "SPCX", "name": "Space Exploration Technologies", "market": "US", "industry": "우주 산업"}],
                "removed": [{"ticker": "OLD", "name": "Old Corp", "market": "US", "industry": "상장폐지"}],
            },
        )

        self.assertIn("상장사 검색 목록 업데이트", body)
        self.assertIn("추가 1개", body)
        self.assertIn("제거 1개", body)
        self.assertIn("SPCX", body)
        self.assertIn("Old Corp", body)

    def test_stock_universe_changes_compares_previous_and_current_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            previous.write_text(
                json.dumps({"rows": [
                    {"ticker": "OLD", "name": "Old Corp", "market": "US"},
                    {"ticker": "KEEP", "name": "Keep Corp", "market": "US"},
                ]}),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps({"rows": [
                    {"ticker": "KEEP", "name": "Keep Corp", "market": "US"},
                    {"ticker": "SPCX", "name": "Space Exploration Technologies", "market": "US"},
                ]}),
                encoding="utf-8",
            )

            changes = self.notifications.stock_universe_changes(previous, current)

        self.assertEqual(2, changes["previousCount"])
        self.assertEqual(2, changes["currentCount"])
        self.assertEqual(["SPCX"], [row["ticker"] for row in changes["added"]])
        self.assertEqual(["OLD"], [row["ticker"] for row in changes["removed"]])

    def test_stock_universe_report_skips_email_when_unchanged(self) -> None:
        original_window = self.notifications.is_weekly_report_window
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            payload = {"rows": [{"ticker": "KEEP", "name": "Keep Corp", "market": "US"}]}
            previous.write_text(json.dumps(payload), encoding="utf-8")
            current.write_text(json.dumps(payload), encoding="utf-8")

            try:
                self.notifications.is_weekly_report_window = lambda: True
                sent = self.notifications.send_stock_universe_report_notifications(previous, current)
            finally:
                self.notifications.is_weekly_report_window = original_window

        self.assertEqual(0, sent)

    def test_weekly_trend_report_sends_to_all_enabled_recipients(self) -> None:
        sent_messages: list[tuple[str, str, str]] = []
        original_latest_market_trend = self.notifications.latest_market_trend
        original_load_recipients = self.notifications.load_recipients
        original_send_notification = self.notifications.send_notification
        original_window = self.notifications.is_weekly_report_window
        original_state_path = self.notifications.NOTIFICATION_STATE

        try:
            with TemporaryDirectory() as temp_dir:
                self.notifications.NOTIFICATION_STATE = Path(temp_dir) / "state.json"
                self.notifications.is_weekly_report_window = lambda: True
                self.notifications.latest_market_trend = lambda: {
                    "date": "2026.06.15",
                    "summary": "요약",
                    "ranks": ["우주항공 | SpaceX"],
                }
                self.notifications.load_recipients = lambda: [
                    self.notifications.Recipient(
                        owner_id="admin",
                        email="admin@example.com",
                        is_admin=True,
                        preferences={"weeklyTrendReport": True},
                    ),
                    self.notifications.Recipient(
                        owner_id="user",
                        email="user@example.com",
                        is_admin=False,
                        preferences={"weeklyTrendReport": True},
                    ),
                ]
                self.notifications.send_notification = (
                    lambda recipient, subject, body: sent_messages.append((recipient.email, subject, body)) or "email"
                )

                sent = self.notifications.send_weekly_trend_notifications()
        finally:
            self.notifications.latest_market_trend = original_latest_market_trend
            self.notifications.load_recipients = original_load_recipients
            self.notifications.send_notification = original_send_notification
            self.notifications.is_weekly_report_window = original_window
            self.notifications.NOTIFICATION_STATE = original_state_path

        self.assertEqual(2, sent)
        self.assertEqual(["admin@example.com", "user@example.com"], [message[0] for message in sent_messages])

    def test_weekly_trend_report_sends_once_per_report_date(self) -> None:
        sent_messages: list[tuple[str, str, str]] = []
        original_latest_market_trend = self.notifications.latest_market_trend
        original_load_recipients = self.notifications.load_recipients
        original_send_notification = self.notifications.send_notification
        original_window = self.notifications.is_weekly_report_window
        original_state_path = self.notifications.NOTIFICATION_STATE

        try:
            with TemporaryDirectory() as temp_dir:
                self.notifications.NOTIFICATION_STATE = Path(temp_dir) / "state.json"
                self.notifications.is_weekly_report_window = lambda: True
                self.notifications.latest_market_trend = lambda: {
                    "date": "2026.07.27",
                    "summary": "요약",
                    "ranks": ["우주항공 | SpaceX"],
                }
                self.notifications.load_recipients = lambda: [
                    self.notifications.Recipient(
                        owner_id="admin",
                        email="admin@example.com",
                        is_admin=True,
                        preferences={"weeklyTrendReport": True},
                    ),
                ]
                self.notifications.send_notification = (
                    lambda recipient, subject, body: sent_messages.append((recipient.email, subject, body)) or "email"
                )

                first_sent = self.notifications.send_weekly_trend_notifications()
                second_sent = self.notifications.send_weekly_trend_notifications()
        finally:
            self.notifications.latest_market_trend = original_latest_market_trend
            self.notifications.load_recipients = original_load_recipients
            self.notifications.send_notification = original_send_notification
            self.notifications.is_weekly_report_window = original_window
            self.notifications.NOTIFICATION_STATE = original_state_path

        self.assertEqual(1, first_sent)
        self.assertEqual(0, second_sent)
        self.assertEqual(1, len(sent_messages))

    def test_stock_universe_report_sends_only_to_admins(self) -> None:
        sent_messages: list[tuple[str, str, str]] = []
        original_load_recipients = self.notifications.load_recipients
        original_send_notification = self.notifications.send_notification
        original_window = self.notifications.is_weekly_report_window

        try:
            self.notifications.is_weekly_report_window = lambda: True
            with TemporaryDirectory() as temp_dir:
                previous = Path(temp_dir) / "previous.json"
                current = Path(temp_dir) / "current.json"
                previous.write_text(json.dumps({"rows": []}), encoding="utf-8")
                current.write_text(
                    json.dumps({"rows": [{"ticker": "SPCX", "name": "Space Exploration Technologies", "market": "US"}]}),
                    encoding="utf-8",
                )
                self.notifications.load_recipients = lambda: [
                    self.notifications.Recipient(
                        owner_id="admin",
                        email="admin@example.com",
                        is_admin=True,
                        preferences={"weeklyTrendReport": True},
                    ),
                    self.notifications.Recipient(
                        owner_id="user",
                        email="user@example.com",
                        is_admin=False,
                        preferences={"weeklyTrendReport": True},
                    ),
                ]
                self.notifications.send_notification = (
                    lambda recipient, subject, body: sent_messages.append((recipient.email, subject, body)) or "email"
                )

                sent = self.notifications.send_stock_universe_report_notifications(previous, current)
        finally:
            self.notifications.load_recipients = original_load_recipients
            self.notifications.send_notification = original_send_notification
            self.notifications.is_weekly_report_window = original_window

        self.assertEqual(1, sent)
        self.assertEqual(["admin@example.com"], [message[0] for message in sent_messages])

    def test_earnings_notifications_send_once_per_kst_day_for_same_candidates(self) -> None:
        sent_messages: list[tuple[str, str, str]] = []
        original_load_recipients = self.notifications.load_recipients
        original_load_watchlists = self.notifications.load_watchlists
        original_send_notification = self.notifications.send_notification
        original_state_path = self.notifications.NOTIFICATION_STATE

        try:
            with TemporaryDirectory() as temp_dir:
                current = Path(temp_dir) / "stocks.json"
                valuation = Path(temp_dir) / "valuation.json"
                current.write_text(
                    json.dumps({"rows": [{"ticker": "BE", "name": "Bloom Energy", "opinion": "관망"}]}),
                    encoding="utf-8",
                )
                valuation.write_text(
                    json.dumps({"rows": {"BE": {"earningsDate": "2026-07-29 (D-1)"}}}),
                    encoding="utf-8",
                )
                self.notifications.NOTIFICATION_STATE = Path(temp_dir) / "state.json"
                self.notifications.load_recipients = lambda: [
                    self.notifications.Recipient(
                        owner_id="admin-1",
                        email="admin@example.com",
                        is_admin=True,
                        preferences={"earningsDayBefore": True},
                    ),
                ]
                self.notifications.load_watchlists = lambda: {"": {"BE"}}
                self.notifications.send_notification = (
                    lambda recipient, subject, body: sent_messages.append((recipient.email, subject, body)) or "email"
                )

                first_sent = self.notifications.send_earnings_notifications(current, valuation)
                second_sent = self.notifications.send_earnings_notifications(current, valuation)
        finally:
            self.notifications.load_recipients = original_load_recipients
            self.notifications.load_watchlists = original_load_watchlists
            self.notifications.send_notification = original_send_notification
            self.notifications.NOTIFICATION_STATE = original_state_path

        self.assertEqual(1, first_sent)
        self.assertEqual(0, second_sent)
        self.assertEqual(1, len(sent_messages))
        self.assertIn("[실적발표 D-1] BE", sent_messages[0][1])

    def test_earnings_notifications_resend_when_candidates_change(self) -> None:
        sent_messages: list[tuple[str, str, str]] = []
        original_load_recipients = self.notifications.load_recipients
        original_load_watchlists = self.notifications.load_watchlists
        original_send_notification = self.notifications.send_notification
        original_state_path = self.notifications.NOTIFICATION_STATE

        try:
            with TemporaryDirectory() as temp_dir:
                current = Path(temp_dir) / "stocks.json"
                valuation = Path(temp_dir) / "valuation.json"
                current.write_text(
                    json.dumps({
                        "rows": [
                            {"ticker": "BE", "name": "Bloom Energy", "opinion": "관망"},
                            {"ticker": "STX", "name": "Seagate", "opinion": "관망"},
                        ]
                    }),
                    encoding="utf-8",
                )
                valuation.write_text(
                    json.dumps({"rows": {"BE": {"earningsDate": "2026-07-29 (D-1)"}}}),
                    encoding="utf-8",
                )
                self.notifications.NOTIFICATION_STATE = Path(temp_dir) / "state.json"
                self.notifications.load_recipients = lambda: [
                    self.notifications.Recipient(
                        owner_id="admin-1",
                        email="admin@example.com",
                        is_admin=True,
                        preferences={"earningsDayBefore": True},
                    ),
                ]
                self.notifications.load_watchlists = lambda: {"": {"BE", "STX"}}
                self.notifications.send_notification = (
                    lambda recipient, subject, body: sent_messages.append((recipient.email, subject, body)) or "email"
                )

                first_sent = self.notifications.send_earnings_notifications(current, valuation)
                valuation.write_text(
                    json.dumps({
                        "rows": {
                            "BE": {"earningsDate": "2026-07-29 (D-1)"},
                            "STX": {"earningsDate": "2026-07-29 (D-1)"},
                        }
                    }),
                    encoding="utf-8",
                )
                second_sent = self.notifications.send_earnings_notifications(current, valuation)
        finally:
            self.notifications.load_recipients = original_load_recipients
            self.notifications.load_watchlists = original_load_watchlists
            self.notifications.send_notification = original_send_notification
            self.notifications.NOTIFICATION_STATE = original_state_path

        self.assertEqual(1, first_sent)
        self.assertEqual(1, second_sent)
        self.assertIn("[실적발표 D-1] BE, STX", sent_messages[1][1])

    def test_weekly_reports_skip_outside_monday_midnight_window(self) -> None:
        kst = ZoneInfo("Asia/Seoul")

        self.assertTrue(self.notifications.is_weekly_report_window(datetime(2026, 7, 6, 0, 30, tzinfo=kst)))
        # GitHub Actions 지연을 감안해 같은 월요일 03:00까지 허용한다.
        self.assertTrue(self.notifications.is_weekly_report_window(datetime(2026, 7, 6, 2, 59, tzinfo=kst)))
        self.assertFalse(self.notifications.is_weekly_report_window(datetime(2026, 7, 6, 3, 0, tzinfo=kst)))
        self.assertFalse(self.notifications.is_weekly_report_window(datetime(2026, 6, 30, 20, 5, tzinfo=kst)))

    def test_opinion_changes_labels_watch_to_buy_with_added_trade_as_additional_buy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"
            previous_trades = Path(temp_dir) / "trade-logs.before-refresh.json"
            current_trades = Path(temp_dir) / "trade-logs.json"

            previous.write_text(
                json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "opinion": "관망"}]}),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "opinion": "매수", "currentPrice": "$90.00"}]}),
                encoding="utf-8",
            )
            technical.write_text(
                json.dumps({"rows": {"MP": {"entrySignalCodes": "D", "현재가": "$90.00"}}}),
                encoding="utf-8",
            )
            previous_trades.write_text(
                json.dumps({"rows": [
                    {"slotId": "MP_D_20260501_1", "ticker": "MP", "strategy": "1. 시장 공포 저점 진입", "buyDate": "2026.05.01", "buyPrice": "$100.00", "status": "보유 중"}
                ]}),
                encoding="utf-8",
            )
            current_trades.write_text(
                json.dumps({"rows": [
                    {"slotId": "MP_D_20260501_1", "ticker": "MP", "strategy": "1. 시장 공포 저점 진입", "buyDate": "2026.05.01", "buyPrice": "$100.00", "status": "보유 중"},
                    {"slotId": "MP_D_20260519_1", "ticker": "MP", "strategy": "1. 시장 공포 저점 진입", "buyDate": "2026.05.19", "buyPrice": "$90.00", "status": "보유 중"},
                ]}),
                encoding="utf-8",
            )

            changes = self.notifications.opinion_changes(previous, current, technical, previous_trades, current_trades)

        self.assertEqual(1, len(changes))
        self.assertEqual("매수(보유중)", changes[0]["fromLabel"])
        self.assertEqual("추가 매수", changes[0]["toLabel"])
        self.assertEqual("재진입 1회차 — 최초 진입가 $100.00", changes[0]["entryNote"])
        # 전략 1/2는 고정 목표 수익률이 없어 권장 매도가를 계산하지 않는다.
        self.assertEqual("-", changes[0]["recommendedSellPrice"])

    def test_opinion_changes_skips_held_buy_signal_without_added_trade(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"
            previous_trades = Path(temp_dir) / "trade-logs.before-refresh.json"
            current_trades = Path(temp_dir) / "trade-logs.json"

            previous.write_text(
                json.dumps({"rows": [{"ticker": "278470", "name": "에이피알", "opinion": "관망"}]}),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps({"rows": [{"ticker": "278470", "name": "에이피알", "opinion": "매수", "currentPrice": "₩399,500"}]}),
                encoding="utf-8",
            )
            technical.write_text(
                json.dumps({"rows": {"278470": {"entrySignalCodes": "F", "현재가": "₩399,500", "저가%B": "1.95"}}}),
                encoding="utf-8",
            )
            open_trade = {
                "slotId": "278470_F_20260501_1",
                "ticker": "278470",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.05.01",
                "buyPrice": "₩410,000",
                "status": "보유 중",
            }
            previous_trades.write_text(json.dumps({"rows": [open_trade]}), encoding="utf-8")
            current_trades.write_text(json.dumps({"rows": [open_trade]}), encoding="utf-8")

            changes = self.notifications.opinion_changes(previous, current, technical, previous_trades, current_trades)

        self.assertEqual([], changes)

    def test_send_notification_uses_slack_when_selected_and_connected(self) -> None:
        sent_slack: list[tuple[str, str, str]] = []
        sent_email: list[tuple[str, str, str]] = []
        original_send_slack = self.notifications.send_slack_message
        original_send_email = self.notifications.send_email
        self.notifications.send_slack_message = lambda webhook, subject, body: sent_slack.append((webhook, subject, body))
        self.notifications.send_email = lambda email, subject, body: sent_email.append((email, subject, body))

        try:
            channel = self.notifications.send_notification(
                self.notifications.Recipient(
                    owner_id="user-1",
                    email="user@example.com",
                    is_admin=False,
                    preferences={"notificationChannel": "slack", "slackConnected": True},
                    slack_webhook_url="https://hooks.slack.test/abc",
                ),
                "테스트",
                "<p>본문<br>내용</p>",
            )
        finally:
            self.notifications.send_slack_message = original_send_slack
            self.notifications.send_email = original_send_email

        self.assertEqual("slack", channel)
        self.assertEqual([("https://hooks.slack.test/abc", "테스트", "<p>본문<br>내용</p>")], sent_slack)
        self.assertEqual([], sent_email)

    def test_send_notification_falls_back_to_email_without_slack_webhook(self) -> None:
        sent_email: list[tuple[str, str, str]] = []
        original_send_email = self.notifications.send_email
        self.notifications.send_email = lambda email, subject, body: sent_email.append((email, subject, body))

        try:
            channel = self.notifications.send_notification(
                self.notifications.Recipient(
                    owner_id="user-1",
                    email="user@example.com",
                    is_admin=False,
                    preferences={"notificationChannel": "slack", "slackConnected": True},
                ),
                "테스트",
                "<p>본문</p>",
            )
        finally:
            self.notifications.send_email = original_send_email

        self.assertEqual("email", channel)
        self.assertEqual([("user@example.com", "테스트", "<p>본문</p>")], sent_email)

    def test_opinion_changes_marks_sell_to_buy_without_open_slot_as_new_entry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"
            previous_trades = Path(temp_dir) / "trade-logs.before-refresh.json"
            current_trades = Path(temp_dir) / "trade-logs.json"

            previous.write_text(
                json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "opinion": "매도"}]}),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "opinion": "매수", "currentPrice": "$60.00"}]}),
                encoding="utf-8",
            )
            technical.write_text(json.dumps({"rows": {"MP": {"entrySignalCodes": "D", "현재가": "$60.00"}}}), encoding="utf-8")
            previous_trades.write_text(
                json.dumps({"rows": [{"ticker": "MP", "strategy": "1. 시장 공포 저점 진입", "buyDate": "2026.05.01", "buyPrice": "$67.43", "sellDate": "2026.05.05", "sellPrice": "$70.00", "status": "익절"}]}),
                encoding="utf-8",
            )
            current_trades.write_text(
                json.dumps({"rows": [
                    {"ticker": "MP", "strategy": "1. 시장 공포 저점 진입", "buyDate": "2026.05.01", "buyPrice": "$67.43", "sellDate": "2026.05.05", "sellPrice": "$70.00", "status": "익절"},
                    {"slotId": "MP_D_20260510_1", "ticker": "MP", "strategy": "1. 시장 공포 저점 진입", "buyDate": "2026.05.10", "buyPrice": "$60.00", "status": "보유 중"},
                ]}),
                encoding="utf-8",
            )

            changes = self.notifications.opinion_changes(previous, current, technical, previous_trades, current_trades)

        self.assertEqual(1, len(changes))
        self.assertEqual("신규 진입", changes[0]["entryNote"])

    def test_opinion_changes_detects_additional_buy_from_new_open_trade(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"
            previous_trades = Path(temp_dir) / "trade-logs.before-refresh.json"
            current_trades = Path(temp_dir) / "trade-logs.json"

            stock = {"ticker": "DL", "name": "DL", "opinion": "매수", "currentPrice": "$97.00", "industry": "건설"}
            previous.write_text(json.dumps({"rows": [stock]}), encoding="utf-8")
            current.write_text(json.dumps({"rows": [stock]}), encoding="utf-8")
            technical.write_text(
                json.dumps({"rows": {"DL": {"entrySignalCodes": "F", "현재가": "$97.00", "저가%B": "-3.45"}}}),
                encoding="utf-8",
            )
            previous_trades.write_text(
                json.dumps({"rows": [{"slotId": "DL_E_20260501_1", "ticker": "DL", "strategy": "2. 상승 추세 이평선 눌림목", "buyDate": "2026.05.01", "buyPrice": "$100.00", "status": "보유 중"}]}),
                encoding="utf-8",
            )
            current_trades.write_text(
                json.dumps({"rows": [
                    {"slotId": "DL_E_20260501_1", "ticker": "DL", "strategy": "2. 상승 추세 이평선 눌림목", "buyDate": "2026.05.01", "buyPrice": "$100.00", "status": "보유 중"},
                    {"slotId": "DL_F_20260510_1", "ticker": "DL", "strategy": "2. 상승 추세 이평선 눌림목", "buyDate": "2026.05.10", "buyPrice": "$97.00", "status": "보유 중"},
                ]}),
                encoding="utf-8",
            )

            changes = self.notifications.opinion_changes(previous, current, technical, previous_trades, current_trades)

        self.assertEqual(1, len(changes))
        self.assertEqual("매수(보유중)", changes[0]["fromLabel"])
        self.assertEqual("추가 매수", changes[0]["toLabel"])
        self.assertEqual("재진입 1회차 — 최초 진입가 $100.00", changes[0]["entryNote"])
        self.assertIn("2. 상승 추세 이평선 눌림목", changes[0]["reason"])

    def test_opinion_changes_no_email_when_held_buy_signal_persists(self) -> None:
        # 보유 중인 종목이 매수 신호를 계속 유지하면(추가매수 조건만 미충족) 의견은 '매수'로 남는다.
        # 이 경우 '매수→관망' 전환도, 추가매수 알림도 발생해서는 안 된다(이전 매수 → 현재 매수, 변동 없음).
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"
            previous_trades = Path(temp_dir) / "trade-logs.before-refresh.json"
            current_trades = Path(temp_dir) / "trade-logs.json"

            previous.write_text(
                json.dumps({"rows": [{"ticker": "GOOGL", "name": "Alphabet", "opinion": "매수"}]}),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps({"rows": [{
                    "ticker": "GOOGL",
                    "name": "Alphabet",
                    "opinion": "매수",
                    "currentPrice": "$389.26",
                }]}),
                encoding="utf-8",
            )
            technical.write_text(
                json.dumps({"rows": {"GOOGL": {"entrySignalCodes": "G", "진입 전략": "2. 상승 추세 이평선 눌림목", "현재가": "$389.26"}}}),
                encoding="utf-8",
            )
            held_trade = [
                {"slotId": "GOOGL_G_20260522_1", "ticker": "GOOGL", "strategy": "2. 상승 추세 이평선 눌림목", "buyDate": "2026.05.22", "buyPrice": "$388.55", "status": "보유 중"}
            ]
            previous_trades.write_text(json.dumps({"rows": held_trade}), encoding="utf-8")
            current_trades.write_text(json.dumps({"rows": held_trade}), encoding="utf-8")

            changes = self.notifications.opinion_changes(previous, current, technical, previous_trades, current_trades)

        self.assertEqual([], changes)

    def test_opinion_changes_detects_all_valid_transitions(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"

            previous.write_text(
                json.dumps({
                    "rows": [
                        {"ticker": "BW", "name": "Buy To Watch", "opinion": "매수"},
                        {"ticker": "BS", "name": "Buy To Sell", "opinion": "매수"},
                        {"ticker": "WB", "name": "Watch To Buy", "opinion": "관망"},
                        {"ticker": "WS", "name": "Watch To Sell", "opinion": "관망"},
                        {"ticker": "SB", "name": "Sell To Buy", "opinion": "매도"},
                        {"ticker": "SW", "name": "Sell To Watch", "opinion": "매도"},
                    ]
                }),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps({
                    "rows": [
                        {"ticker": "BW", "name": "Buy To Watch", "opinion": "관망"},
                        {"ticker": "BS", "name": "Buy To Sell", "opinion": "매도"},
                        {"ticker": "WB", "name": "Watch To Buy", "opinion": "매수"},
                        {"ticker": "WS", "name": "Watch To Sell", "opinion": "매도"},
                        {"ticker": "SB", "name": "Sell To Buy", "opinion": "매수"},
                        {"ticker": "SW", "name": "Sell To Watch", "opinion": "관망"},
                    ]
                }),
                encoding="utf-8",
            )
            technical.write_text(json.dumps({"rows": {}}), encoding="utf-8")

            changes = self.notifications.opinion_changes(previous, current, technical)

        transitions = {(change["from"], change["to"]) for change in changes}
        self.assertEqual(
            {
                ("매수", "관망"),
                ("매수", "매도"),
                ("관망", "매수"),
                ("관망", "매도"),
                ("매도", "매수"),
                ("매도", "관망"),
            },
            transitions,
        )

    def test_opinion_changes_prefers_event_watch_reason(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"

            previous.write_text(
                json.dumps({"rows": [{"ticker": "042660", "name": "한화오션", "opinion": "매수"}]}),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps({
                    "rows": [
                        {
                            "ticker": "042660",
                            "name": "한화오션",
                            "opinion": "관망",
                            "opinionReason": "이벤트 기간 관망 (PPI 발표)",
                        }
                    ]
                }),
                encoding="utf-8",
            )
            technical.write_text(json.dumps({"rows": {}}), encoding="utf-8")

            changes = self.notifications.opinion_changes(previous, current, technical)

        self.assertEqual(1, len(changes))
        self.assertEqual("매수", changes[0]["from"])
        self.assertEqual("관망", changes[0]["to"])
        self.assertEqual("이벤트 기간 관망 (PPI 발표)", changes[0]["reason"])

    def test_opinion_changes_explains_watch_transition_with_core_metrics(self) -> None:
        with TemporaryDirectory() as temp_dir:
            previous = Path(temp_dir) / "previous.json"
            current = Path(temp_dir) / "current.json"
            technical = Path(temp_dir) / "technical.json"

            previous.write_text(
                json.dumps({
                    "rows": [
                        {
                            "ticker": "MP",
                            "name": "MP Materials",
                            "opinion": "매수",
                            "strategies": ["2. 상승 추세 이평선 눌림목"],
                        }
                    ]
                }),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "opinion": "관망", "currentPrice": "$75.00"}]}),
                encoding="utf-8",
            )
            technical.write_text(
                json.dumps({
                    "rows": {
                        "MP": {
                            "200일 이동평균선": "$60.00",
                            "20일 이동평균선": "$80.00",
                            "decisionLog": "MP 최종 판단: 관망\n시장 국면: 급락 후 회복장 / QQQ 이격도 +7.20% / 이벤트: 당분간 없음",
                        }
                    }
                }),
                encoding="utf-8",
            )

            changes = self.notifications.opinion_changes(previous, current, technical)

        self.assertEqual(1, len(changes))
        self.assertIn("매수 조건 해제", changes[0]["reason"])
        self.assertIn("2. 상승 추세 이평선 눌림목", changes[0]["reason"])
        # 전략 2는 이평선 눌림목이므로 해제 사유도 이평선 기준으로 설명한다.
        self.assertIn("이평선 회복 실패", changes[0]["reason"])
        self.assertIn("MA20 $80.00", changes[0]["reason"])
        self.assertNotIn("시장 국면:", changes[0]["reason"])

    def test_refresh_to_opinion_change_sends_email_end_to_end(self) -> None:
        sent_messages: list[tuple[str, str, str]] = []
        original_load_recipients = self.notifications.load_recipients
        original_load_watchlists = self.notifications.load_watchlists
        original_send_email = self.notifications.send_email
        self.notifications.load_recipients = lambda: [
            self.notifications.Recipient(
                owner_id="user-1",
                email="user@example.com",
                is_admin=False,
                preferences={"opinionChangeEmail": True},
            )
        ]
        self.notifications.load_watchlists = lambda: {"user-1": {"MP"}}
        self.notifications.send_email = lambda email, subject, body: sent_messages.append((email, subject, body))

        try:
            with TemporaryDirectory() as temp_dir:
                previous = Path(temp_dir) / "stocks.before-refresh.json"
                current = Path(temp_dir) / "stocks.json"

                # This mirrors the workflow: snapshot first, then refresh writes a changed current cache.
                previous.write_text(
                    json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "opinion": "관망"}]}),
                    encoding="utf-8",
                )
                current.write_text(
                    json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "opinion": "매수"}]}),
                    encoding="utf-8",
                )

                sent = self.notifications.send_opinion_notifications(previous, current)
        finally:
            self.notifications.load_recipients = original_load_recipients
            self.notifications.load_watchlists = original_load_watchlists
            self.notifications.send_email = original_send_email

        self.assertEqual(1, sent)
        self.assertEqual("user@example.com", sent_messages[0][0])
        self.assertEqual("투자의견 변경 알림 (MP)", sent_messages[0][1])
        self.assertIn("MP Materials", sent_messages[0][2])
        self.assertIn("관망", sent_messages[0][2])
        self.assertIn("매수", sent_messages[0][2])
        self.assertIn("이유:", sent_messages[0][2])
        self.assertIn("현재 매수 의견 종목:", sent_messages[0][2])
        self.assertIn("발송 시각 (한국):", sent_messages[0][2])
        self.assertIn("발송 시각 (미 동부):", sent_messages[0][2])

    def test_opinion_notification_combines_trade_exit_changes(self) -> None:
        sent_messages: list[tuple[str, str, str]] = []
        original_load_recipients = self.notifications.load_recipients
        original_load_watchlists = self.notifications.load_watchlists
        original_send_email = self.notifications.send_email
        # 시스템 거래 로그 기반 청산은 어드민 계정으로만 전달된다.
        self.notifications.load_recipients = lambda: [
            self.notifications.Recipient(
                owner_id="admin-1",
                email="user@example.com",
                is_admin=True,
                preferences={"opinionChangeEmail": True},
                investment_type="swing",
            )
        ]
        self.notifications.load_watchlists = lambda: {"": {"ACLS", "039030"}}
        self.notifications.send_email = lambda email, subject, body: sent_messages.append((email, subject, body))

        try:
            with TemporaryDirectory() as temp_dir:
                previous = Path(temp_dir) / "stocks.before-refresh.json"
                current = Path(temp_dir) / "stocks.json"
                previous_trades = Path(temp_dir) / "trade-logs.before-refresh.json"
                current_trades = Path(temp_dir) / "trade-logs.json"

                previous.write_text(
                    json.dumps({"rows": [{"ticker": "ACLS", "name": "Axcelis Technologies", "opinion": "관망"}]}),
                    encoding="utf-8",
                )
                current.write_text(
                    json.dumps({"rows": [
                        {"ticker": "ACLS", "name": "Axcelis Technologies", "opinion": "매수"},
                        {"ticker": "039030", "name": "이오테크닉스", "opinion": "매도"},
                    ]}),
                    encoding="utf-8",
                )
                previous_trades.write_text(
                    json.dumps({"rows": [{"ticker": "039030", "name": "이오테크닉스", "strategy": "2. 상승 추세 이평선 눌림목", "buyDate": "2026.05.18", "buyPrice": "₩482,500", "status": "보유 중"}]}),
                    encoding="utf-8",
                )
                current_trades.write_text(
                    json.dumps({"rows": [{"ticker": "039030", "name": "이오테크닉스", "strategy": "2. 상승 추세 이평선 눌림목", "buyDate": "2026.05.18", "buyPrice": "₩482,500", "sellPrice": "₩580,000", "returnPct": 20.21, "status": "익절", "exitReason": "목표 수익 구간 + MACD 히스토그램 둔화전환 매도"}]}),
                    encoding="utf-8",
                )

                sent = self.notifications.send_opinion_notifications(
                    previous,
                    current,
                    previous_trades,
                    current_trades,
                )
        finally:
            self.notifications.load_recipients = original_load_recipients
            self.notifications.load_watchlists = original_load_watchlists
            self.notifications.send_email = original_send_email

        self.assertEqual(1, sent)
        self.assertEqual(1, len(sent_messages))
        self.assertEqual("투자의견 변경 알림 (ACLS, 039030)", sent_messages[0][1])
        self.assertIn("Axcelis Technologies", sent_messages[0][2])
        self.assertIn("이오테크닉스", sent_messages[0][2])
        self.assertEqual(1, sent_messages[0][2].count("2. <strong>이오테크닉스"))
        self.assertIn("매수", sent_messages[0][2])
        self.assertIn("매도", sent_messages[0][2])
        self.assertIn("목표 수익 구간 + MACD 히스토그램 둔화전환 매도", sent_messages[0][2])
        self.assertIn("현재 매도 의견 종목:</strong> 이오테크닉스 (039030)", sent_messages[0][2])

    def test_opinion_notification_branches_by_investment_type(self) -> None:
        sent_messages: list[tuple[str, str, str]] = []
        original_load_recipients = self.notifications.load_recipients
        original_load_watchlists = self.notifications.load_watchlists
        original_send_email = self.notifications.send_email
        self.notifications.load_recipients = lambda: [
            self.notifications.Recipient(
                owner_id="swing-user",
                email="swing@example.com",
                is_admin=False,
                preferences={"opinionChangeEmail": True},
                investment_type="swing",
            ),
            self.notifications.Recipient(
                owner_id="value-user",
                email="value@example.com",
                is_admin=False,
                preferences={"opinionChangeEmail": True},
                investment_type="long_term",
            ),
        ]
        self.notifications.load_watchlists = lambda: {
            "swing-user": {"ACLS", "039030", "TSLA"},
            "value-user": {"ACLS", "039030", "TSLA"},
        }
        self.notifications.send_email = lambda email, subject, body: sent_messages.append((email, subject, body))

        try:
            with TemporaryDirectory() as temp_dir:
                previous = Path(temp_dir) / "stocks.before-refresh.json"
                current = Path(temp_dir) / "stocks.json"
                previous_trades = Path(temp_dir) / "trade-logs.before-refresh.json"
                current_trades = Path(temp_dir) / "trade-logs.json"

                previous.write_text(
                    json.dumps({"rows": [
                        {"ticker": "ACLS", "name": "Axcelis Technologies", "opinion": "관망"},
                        {"ticker": "TSLA", "name": "Tesla", "opinion": "매수"},
                    ]}),
                    encoding="utf-8",
                )
                current.write_text(
                    json.dumps({"rows": [
                        {"ticker": "ACLS", "name": "Axcelis Technologies", "opinion": "매수"},
                        {"ticker": "039030", "name": "이오테크닉스", "opinion": "매도"},
                        {"ticker": "TSLA", "name": "Tesla", "opinion": "관망"},
                    ]}),
                    encoding="utf-8",
                )
                previous_trades.write_text(
                    json.dumps({"rows": [{"ticker": "039030", "name": "이오테크닉스", "strategy": "2. 상승 추세 이평선 눌림목", "buyDate": "2026.05.18", "buyPrice": "₩482,500", "status": "보유 중"}]}),
                    encoding="utf-8",
                )
                current_trades.write_text(
                    json.dumps({"rows": [{"ticker": "039030", "name": "이오테크닉스", "strategy": "2. 상승 추세 이평선 눌림목", "buyDate": "2026.05.18", "buyPrice": "₩482,500", "sellPrice": "₩580,000", "returnPct": 20.21, "status": "익절", "exitReason": "목표 수익 구간 + MACD 히스토그램 둔화전환 매도"}]}),
                    encoding="utf-8",
                )

                sent = self.notifications.send_opinion_notifications(
                    previous,
                    current,
                    previous_trades,
                    current_trades,
                )
        finally:
            self.notifications.load_recipients = original_load_recipients
            self.notifications.load_watchlists = original_load_watchlists
            self.notifications.send_email = original_send_email

        self.assertEqual(2, sent)
        by_email = {message[0]: message for message in sent_messages}
        self.assertIn("swing@example.com", by_email)
        self.assertIn("value@example.com", by_email)

        swing_body = by_email["swing@example.com"][2]
        self.assertIn("이오테크닉스", swing_body)
        self.assertIn("현재 매도 의견 종목:", swing_body)

        value_subject, value_body = by_email["value@example.com"][1], by_email["value@example.com"][2]
        # 가치투자: 매수(ACLS)와 매수→관망(TSLA)은 포함, 매도 전환(039030)과 청산은 제외
        self.assertEqual("투자의견 변경 알림 (ACLS, TSLA)", value_subject)
        self.assertIn("Axcelis Technologies", value_body)
        self.assertIn("Tesla", value_body)
        self.assertNotIn("이오테크닉스", value_body)
        self.assertNotIn("현재 매도 의견 종목:", value_body)

    def test_trade_exit_change_sends_sell_email_end_to_end(self) -> None:
        sent_messages: list[tuple[str, str, str]] = []
        original_load_recipients = self.notifications.load_recipients
        original_send_email = self.notifications.send_email
        self.notifications.load_recipients = lambda: [
            self.notifications.Recipient(
                owner_id="user-1",
                email="user@example.com",
                is_admin=False,
                preferences={"opinionChangeEmail": True},
            )
        ]
        self.notifications.send_email = lambda email, subject, body: sent_messages.append((email, subject, body))

        try:
            with TemporaryDirectory() as temp_dir:
                previous = Path(temp_dir) / "trade-logs.before-refresh.json"
                current = Path(temp_dir) / "trade-logs.json"

                previous.write_text(
                    json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "strategy": "1. 시장 공포 저점 진입", "buyDate": "2026.05.09", "buyPrice": "$67.43", "status": "보유 중"}]}),
                    encoding="utf-8",
                )
                current.write_text(
                    json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "strategy": "1. 시장 공포 저점 진입", "buyDate": "2026.05.09", "buyPrice": "$67.43", "sellPrice": "$75.00", "returnPct": 11.23, "status": "익절", "exitReason": "회복장 종료 전량매도"}]}),
                    encoding="utf-8",
                )

                sent = self.notifications.send_trade_exit_notifications(previous, current)
        finally:
            self.notifications.load_recipients = original_load_recipients
            self.notifications.send_email = original_send_email

        self.assertEqual(1, sent)
        self.assertEqual("user@example.com", sent_messages[0][0])
        self.assertEqual("투자의견 변경 알림 (MP)", sent_messages[0][1])
        self.assertIn("MP Materials", sent_messages[0][2])
        self.assertIn("매도", sent_messages[0][2])
        self.assertIn("회복장 종료 전량매도 +11.23%", sent_messages[0][2])
        self.assertIn("이유:", sent_messages[0][2])
        self.assertIn("현재 매도 의견 종목:</strong> MP Materials (MP)", sent_messages[0][2])
        self.assertNotIn("매도 사유", sent_messages[0][2])


    def test_nasdaq_peak_reset_writes_unsent_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "web-notification-state.json"
            state_path.write_text(json.dumps({"nasdaqPeak": {"sent": True}}), encoding="utf-8")
            original_state_path = self.notifications.NOTIFICATION_STATE
            original_snapshot = self.notifications.qqq_peak_snapshot
            self.notifications.NOTIFICATION_STATE = state_path
            self.notifications.qqq_peak_snapshot = lambda: {
                "currentPrice": 90,
                "resetThreshold": 100,
                "triggered": False,
            }
            try:
                sent = self.notifications.send_nasdaq_peak_notifications()
                state = json.loads(state_path.read_text(encoding="utf-8"))
            finally:
                self.notifications.NOTIFICATION_STATE = original_state_path
                self.notifications.qqq_peak_snapshot = original_snapshot

        self.assertEqual(0, sent)
        self.assertIs(state["nasdaqPeak"]["sent"], False)

    def test_nasdaq_peak_sends_after_reset_state(self) -> None:
        sent_messages: list[tuple[str, str]] = []
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "web-notification-state.json"
            state_path.write_text(json.dumps({"nasdaqPeak": {"sent": False}}), encoding="utf-8")
            original_state_path = self.notifications.NOTIFICATION_STATE
            original_snapshot = self.notifications.qqq_peak_snapshot
            original_load_recipients = self.notifications.load_recipients
            original_send_email = self.notifications.send_email
            self.notifications.NOTIFICATION_STATE = state_path
            self.notifications.qqq_peak_snapshot = lambda: {
                "currentPrice": 120.0,
                "ma200": 100.0,
                "premiumPercent": 20.0,
                "recent60MinPremiumPercent": -5.0,
                "regimeLabel": "test",
                "peakDirectDist": 14.0,
                "peakConfirmDist": 18.0,
                "directThreshold": 114.0,
                "confirmThreshold": 118.0,
                "weeklyRsi": 70.0,
                "dailyRsi": 66.0,
                "dailyRsiPrev": 68.0,
                "macdHist": 1.0,
                "macdHistD1": 1.2,
                "macdHistD2": 1.4,
                "isRecoveryMarket": False,
                "resetThreshold": 100.0,
                "triggered": True,
            }
            self.notifications.load_recipients = lambda: [
                self.notifications.Recipient(
                    owner_id="user-1",
                    email="user@example.com",
                    is_admin=False,
                    preferences={"nasdaqPeakEmail": True},
                )
            ]
            self.notifications.send_email = lambda email, subject, body: sent_messages.append((email, subject))
            try:
                sent = self.notifications.send_nasdaq_peak_notifications()
                state = json.loads(state_path.read_text(encoding="utf-8"))
            finally:
                self.notifications.NOTIFICATION_STATE = original_state_path
                self.notifications.qqq_peak_snapshot = original_snapshot
                self.notifications.load_recipients = original_load_recipients
                self.notifications.send_email = original_send_email

        self.assertEqual(1, sent)
        self.assertEqual([("user@example.com", "나스닥 과열 청산 조건 알림")], sent_messages)
        self.assertIs(state["nasdaqPeak"]["sent"], True)

    def test_nasdaq_peak_defers_email_while_us_market_is_closed(self) -> None:
        original_env = dict()
        for key in ("DEFER_CLOSED_MARKET_SIGNALS", "GITHUB_WORKFLOW"):
            if key in self.notifications.os.environ:
                original_env[key] = self.notifications.os.environ[key]
        original_snapshot = self.notifications.qqq_peak_snapshot
        original_is_open = self.notifications.is_us_market_open
        self.notifications.os.environ["DEFER_CLOSED_MARKET_SIGNALS"] = "true"
        self.notifications.qqq_peak_snapshot = lambda: (_ for _ in ()).throw(AssertionError("snapshot should be deferred"))
        self.notifications.is_us_market_open = lambda now=None: False

        try:
            sent = self.notifications.send_nasdaq_peak_notifications()
        finally:
            self.notifications.qqq_peak_snapshot = original_snapshot
            self.notifications.is_us_market_open = original_is_open
            self.notifications.os.environ.pop("DEFER_CLOSED_MARKET_SIGNALS", None)
            self.notifications.os.environ.pop("GITHUB_WORKFLOW", None)
            self.notifications.os.environ.update(original_env)

        self.assertEqual(0, sent)

    def test_us_market_open_includes_premarket_and_aftermarket(self) -> None:
        et = ZoneInfo("America/New_York")

        self.assertTrue(self.notifications.is_us_market_open(datetime(2026, 6, 26, 4, 0, tzinfo=et)))
        self.assertTrue(self.notifications.is_us_market_open(datetime(2026, 6, 26, 19, 59, tzinfo=et)))
        self.assertFalse(self.notifications.is_us_market_open(datetime(2026, 6, 26, 20, 0, tzinfo=et)))
        self.assertFalse(self.notifications.is_us_market_open(datetime(2026, 6, 27, 12, 0, tzinfo=et)))

    def test_nasdaq_warn_does_not_reset_until_deeper_pullback(self) -> None:
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "web-notification-state.json"
            state_path.write_text(json.dumps({"nasdaqWarn": {"sent": True}}), encoding="utf-8")
            original_state_path = self.notifications.NOTIFICATION_STATE
            original_snapshot = self.notifications.qqq_peak_snapshot
            self.notifications.NOTIFICATION_STATE = state_path
            self.notifications.qqq_peak_snapshot = lambda: {
                "currentPrice": 112.0,
                "ma200": 100.0,
                "premiumPercent": 12.0,
                "recent60MinPremiumPercent": -2.0,
                "regimeLabel": "test",
                "peakDirectDist": 16.0,
                "peakConfirmDist": 14.0,
                "peakWarnDist": 13.0,
                "peakWarnResetDist": 5.0,
                "warnThreshold": 113.0,
                "warnResetThreshold": 105.0,
                "directThreshold": 116.0,
                "isRecoveryMarket": False,
                "warnTriggered": False,
            }
            try:
                sent = self.notifications.send_nasdaq_warn_notifications()
                state = json.loads(state_path.read_text(encoding="utf-8"))
            finally:
                self.notifications.NOTIFICATION_STATE = original_state_path
                self.notifications.qqq_peak_snapshot = original_snapshot

        self.assertEqual(0, sent)
        self.assertIs(state["nasdaqWarn"]["sent"], True)

    def test_nasdaq_warn_resets_after_deeper_pullback(self) -> None:
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "web-notification-state.json"
            state_path.write_text(json.dumps({"nasdaqWarn": {"sent": True}}), encoding="utf-8")
            original_state_path = self.notifications.NOTIFICATION_STATE
            original_snapshot = self.notifications.qqq_peak_snapshot
            self.notifications.NOTIFICATION_STATE = state_path
            self.notifications.qqq_peak_snapshot = lambda: {
                "currentPrice": 104.0,
                "warnThreshold": 113.0,
                "warnResetThreshold": 105.0,
                "warnTriggered": False,
            }
            try:
                sent = self.notifications.send_nasdaq_warn_notifications()
                state = json.loads(state_path.read_text(encoding="utf-8"))
            finally:
                self.notifications.NOTIFICATION_STATE = original_state_path
                self.notifications.qqq_peak_snapshot = original_snapshot

        self.assertEqual(0, sent)
        self.assertIs(state["nasdaqWarn"]["sent"], False)


class WebMarketEventPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = importlib.import_module("calculator.pipeline")

    def test_current_market_event_label_detects_today_kst_event(self) -> None:
        payload = {
            "groups": [
                {
                    "title": "CPI 발표",
                    "entries": [{"date": "2026. 5. 12"}],
                },
                {
                    "title": "PPI 발표",
                    "entries": [{"date": "2026. 5. 13"}],
                },
            ]
        }

        label = self.pipeline.current_market_event_label(payload, today=date(2026, 5, 13))

        self.assertEqual("PPI 발표", label)

    def test_current_market_event_label_clears_after_release_time(self) -> None:
        payload = {
            "groups": [
                {
                    "title": "PCE 발표",
                    "entries": [{"date": "2026. 5. 28", "time": "9:30"}],
                },
            ],
        }
        kst = ZoneInfo("Asia/Seoul")
        before = datetime(2026, 5, 28, 9, 0, tzinfo=kst)
        after = datetime(2026, 5, 28, 10, 0, tzinfo=kst)

        self.assertEqual("PCE 발표", self.pipeline.current_market_event_label(payload, now=before))
        self.assertEqual("당분간 없음", self.pipeline.current_market_event_label(payload, now=after))


if __name__ == "__main__":
    unittest.main()
