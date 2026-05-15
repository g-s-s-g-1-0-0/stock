from __future__ import annotations

import importlib
import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT_DIR = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT_DIR / ".github" / "workflows" / "web-data-refresh.yml"


class WebRefreshWorkflowTest(unittest.TestCase):
    def test_workflow_preserves_previous_snapshot_outside_commit_paths(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn('"$RUNNER_TEMP/stocks.before-refresh.json"', workflow)
        self.assertIn('"$RUNNER_TEMP/trade-logs.before-refresh.json"', workflow)
        self.assertIn(
            'python scripts/web_refresh_notifications.py opinion --previous "$RUNNER_TEMP/stocks.before-refresh.json"',
            workflow,
        )
        self.assertIn(
            'python scripts/web_refresh_notifications.py trade-exit --previous "$RUNNER_TEMP/trade-logs.before-refresh.json"',
            workflow,
        )
        self.assertIn(
            "PREVIOUS_STOCKS_PATH: ${{ runner.temp }}/stocks.before-refresh.json",
            workflow,
        )
        self.assertNotIn("data/cache/stocks.before-refresh.json", workflow)

    def test_workflow_sends_emails_before_committing_refreshed_state(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        wait_index = workflow.index("- name: Wait until scheduled publish time")
        send_opinion_index = workflow.index("- name: Send opinion change emails")
        send_peak_index = workflow.index("- name: Send Nasdaq peak emails")
        commit_state_index = workflow.index("- name: Commit refreshed caches and notification state")
        deploy_index = workflow.index("- name: Deploy refreshed web")
        failure_index = workflow.index("- name: Notify admins on failure")

        self.assertLess(wait_index, send_opinion_index)
        self.assertLess(send_opinion_index, commit_state_index)
        self.assertLess(send_peak_index, commit_state_index)
        self.assertLess(commit_state_index, deploy_index)
        self.assertLess(commit_state_index, failure_index)
        self.assertIn('cron: "55 0-22/2 * * *"', workflow)
        self.assertIn("scheduled_publish_at:", workflow)
        self.assertIn('RAW_PUBLISH_AT="${{ inputs.scheduled_publish_at || \'\' }}"', workflow)
        self.assertIn('if [ "$RAW_PUBLISH_AT" = "immediate" ]; then', workflow)
        self.assertIn("if now.minute >= 50 else", workflow)
        self.assertIn("WEB_REFRESH_PUBLISH_AT=$PUBLISH_AT", workflow)
        self.assertIn("git add data/cache web/public/api", workflow)
        self.assertIn('git commit -m "Update scheduled web data caches"', workflow)

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
                            "strategies": ["F. 200일선 상방 & BB 극단 저점"],
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
                "reason": "F. 200일선 상방 & BB 극단 저점",
                "entryNote": "재진입 1회차 — 최초 진입가 ₩95,400",
            }
        ])

        self.assertIn("매수(보유중)", body)
        self.assertIn("추가 매수", body)
        self.assertNotIn("'매수'</span>", body)
        self.assertNotIn(">매수</strong><br>", body)

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

    def test_opinion_changes_marks_sell_to_buy_as_reentry_with_entry_price(self) -> None:
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
                json.dumps({"rows": [{"ticker": "MP", "strategy": "D. 200일선 상방 & 상승 흐름 강화", "buyDate": "2026.05.01", "buyPrice": "$67.43", "sellDate": "2026.05.05", "sellPrice": "$70.00", "status": "익절"}]}),
                encoding="utf-8",
            )
            current_trades.write_text(
                json.dumps({"rows": [
                    {"ticker": "MP", "strategy": "D. 200일선 상방 & 상승 흐름 강화", "buyDate": "2026.05.01", "buyPrice": "$67.43", "sellDate": "2026.05.05", "sellPrice": "$70.00", "status": "익절"},
                    {"slotId": "MP_D_20260510_1", "ticker": "MP", "strategy": "D. 200일선 상방 & 상승 흐름 강화", "buyDate": "2026.05.10", "buyPrice": "$60.00", "status": "보유 중"},
                ]}),
                encoding="utf-8",
            )

            changes = self.notifications.opinion_changes(previous, current, technical, previous_trades, current_trades)

        self.assertEqual(1, len(changes))
        self.assertEqual("재진입 1회차 — 최초 진입가 $60.00", changes[0]["entryNote"])

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
                json.dumps({"rows": [{"slotId": "DL_E_20260501_1", "ticker": "DL", "strategy": "E. 200일선 상방 & 스퀴즈 저점", "buyDate": "2026.05.01", "buyPrice": "$100.00", "status": "보유 중"}]}),
                encoding="utf-8",
            )
            current_trades.write_text(
                json.dumps({"rows": [
                    {"slotId": "DL_E_20260501_1", "ticker": "DL", "strategy": "E. 200일선 상방 & 스퀴즈 저점", "buyDate": "2026.05.01", "buyPrice": "$100.00", "status": "보유 중"},
                    {"slotId": "DL_F_20260510_1", "ticker": "DL", "strategy": "F. 200일선 상방 & BB 극단 저점", "buyDate": "2026.05.10", "buyPrice": "$97.00", "status": "보유 중"},
                ]}),
                encoding="utf-8",
            )

            changes = self.notifications.opinion_changes(previous, current, technical, previous_trades, current_trades)

        self.assertEqual(1, len(changes))
        self.assertEqual("매수(보유중)", changes[0]["fromLabel"])
        self.assertEqual("추가 매수", changes[0]["toLabel"])
        self.assertEqual("재진입 1회차 — 최초 진입가 $100.00", changes[0]["entryNote"])
        self.assertIn("F. 200일선 상방 & BB 극단 저점", changes[0]["reason"])

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
                            "strategies": ["F. 200일선 상방 & BB 극단 저점"],
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
                            "볼린저밴드 %B (저가)": "8.40",
                            "decisionLog": "MP 최종 판단: 관망\n시장 국면: 급락 후 회복장 / QQQ 이격도 +7.20% / 이벤트: 당분간 없음",
                        }
                    }
                }),
                encoding="utf-8",
            )

            changes = self.notifications.opinion_changes(previous, current, technical)

        self.assertEqual(1, len(changes))
        self.assertIn("매수 조건 해제", changes[0]["reason"])
        self.assertIn("F. 200일선 상방 & BB 극단 저점", changes[0]["reason"])
        self.assertIn("BB 하단 눌림 해소", changes[0]["reason"])
        self.assertIn("저가 %B 8.40", changes[0]["reason"])
        self.assertIn("시장 국면: 급락 후 회복장", changes[0]["reason"])

    def test_refresh_to_opinion_change_sends_email_end_to_end(self) -> None:
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
                    json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "strategy": "D. 200일선 상방 & 상승 흐름 강화", "buyDate": "2026.05.09", "buyPrice": "$67.43", "status": "보유 중"}]}),
                    encoding="utf-8",
                )
                current.write_text(
                    json.dumps({"rows": [{"ticker": "MP", "name": "MP Materials", "strategy": "D. 200일선 상방 & 상승 흐름 강화", "buyDate": "2026.05.09", "buyPrice": "$67.43", "sellPrice": "$75.00", "returnPct": 11.23, "status": "익절", "exitReason": "목표 수익 달성 즉시 매도"}]}),
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
        self.assertIn("목표 수익 달성 즉시 매도", sent_messages[0][2])
        self.assertIn("이유:", sent_messages[0][2])
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


if __name__ == "__main__":
    unittest.main()
