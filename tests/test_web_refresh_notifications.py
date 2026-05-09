from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT_DIR = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT_DIR / ".github" / "workflows" / "web-data-refresh.yml"


class WebRefreshWorkflowTest(unittest.TestCase):
    def test_workflow_preserves_previous_snapshot_outside_commit_paths(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn('"$RUNNER_TEMP/stocks.before-refresh.json"', workflow)
        self.assertIn(
            'python scripts/web_refresh_notifications.py opinion --previous "$RUNNER_TEMP/stocks.before-refresh.json"',
            workflow,
        )
        self.assertNotIn("data/cache/stocks.before-refresh.json", workflow)

    def test_workflow_sends_emails_before_committing_refreshed_state(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        send_opinion_index = workflow.index("- name: Send opinion change emails")
        send_peak_index = workflow.index("- name: Send Nasdaq peak emails")
        commit_state_index = workflow.index("- name: Commit refreshed caches and notification state")
        deploy_index = workflow.index("- name: Deploy refreshed web")
        failure_index = workflow.index("- name: Notify admins on failure")

        self.assertLess(send_opinion_index, commit_state_index)
        self.assertLess(send_peak_index, commit_state_index)
        self.assertLess(commit_state_index, deploy_index)
        self.assertLess(commit_state_index, failure_index)
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
        self.assertEqual([("user@example.com", "나스닥 고점 구간 알림 (매도 시그널)")], sent_messages)
        self.assertIs(state["nasdaqPeak"]["sent"], True)


if __name__ == "__main__":
    unittest.main()
