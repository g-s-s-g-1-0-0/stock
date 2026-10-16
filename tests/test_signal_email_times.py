import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest import mock

from scripts import web_refresh_notifications as notifications


class SignalEmailTimesTest(TestCase):
    def test_only_successful_email_delivery_records_a_timestamp(self):
        recipient = notifications.Recipient("test-owner", "test@example.com", True, {"opinionChangeEmail": True}, investment_type="swing")
        change = {"ticker": "NBIS", "from": "관망", "to": "매수"}
        replacements = {
            "runtime_reset_state": lambda: {},
            "trade_exit_changes": lambda *args: [],
            "trade_rows": lambda *args: [],
            "opinion_changes": lambda *args: [change],
            "load_personal_exit_changes_by_owner": lambda: {},
            "load_recipients": lambda: [recipient],
            "load_watchlists": lambda: {},
            "load_personal_open_trades_by_owner": lambda: {},
            "watchlist_tickers_for_recipient": lambda *args, **kwargs: {"NBIS"},
            "stock_rows_by_ticker": lambda *args: {},
            "technical_rows_by_ticker": lambda *args: {},
            "read_sent_keys": lambda *args: set(),
            "record_sent_keys": lambda *args, **kwargs: None,
            "consume_personal_exit_events": lambda: None,
            "enrich_swing_change_risk": lambda change, *args: change,
            "opinion_groups_for_tickers": lambda *args: ([], [], []),
            "opinion_email_body": lambda *args, **kwargs: "body",
            "append_notification_footer": lambda body, *args: body,
            "opinion_notification_key": lambda *args: "test-key",
        }
        with mock.patch.multiple(notifications, **replacements), mock.patch.object(notifications, "record_signal_email_times") as record:
            for channel in ["email", "slack"]:
                record.reset_mock()
                with mock.patch.object(notifications, "send_notification", return_value=channel):
                    notifications.send_opinion_notifications(Path("missing-previous"), Path("missing-current"), Path("missing-trades-before"), Path("missing-trades"))
                self.assertEqual(record.call_count, 1 if channel == "email" else 0)
            record.reset_mock()
            with mock.patch.object(notifications, "send_notification", side_effect=RuntimeError("delivery failed")):
                with self.assertRaises(RuntimeError):
                    notifications.send_opinion_notifications(Path("missing-previous"), Path("missing-current"), Path("missing-trades-before"), Path("missing-trades"))
            record.assert_not_called()

    def test_entries_and_exits_stamp_only_the_notified_profile_and_event(self):
        old = {"slotId": "old", "ticker": "VST", "investmentType": "swing", "strategy": "7", "buyDate": "2026.10.15", "sellDate": "-", "status": "보유 중"}
        fresh = {**old, "slotId": "new", "ticker": "NBIS", "buyDate": "2026.10.16"}
        deferred = {**fresh, "slotId": "deferred", "ticker": "039030", "status": "매수 보류"}
        sold = {**old, "status": "익절", "sellDate": "2026.10.16"}
        other_profile = {**fresh, "slotId": "long", "investmentType": "long_term"}
        untouched = {**old, "slotId": "untouched", "ticker": "AMD"}
        sent_at = "2026-10-16T15:00:00.123456+09:00"
        with TemporaryDirectory() as directory:
            previous, current = Path(directory) / "previous.json", Path(directory) / "current.json"
            previous.write_text(json.dumps({"rows": [old, untouched]}))
            current.write_text(json.dumps({"rows": [sold, fresh, deferred, other_profile, untouched]}))
            changes = [{"ticker": "VST", "to": "매도"}, {"ticker": "NBIS", "to": "매수"}, {"ticker": "039030", "to": "매수"}]
            notifications.record_signal_email_times(previous, current, changes, "swing", sent_at)
            payload = json.loads(current.read_text())
            for row in payload["rows"][:3]:
                self.assertEqual(row["lastSignalEmailSentAt"], sent_at)
                self.assertEqual(row["lastSignalEmailDate"], "2026.10.16")
            for row in payload["rows"][3:]:
                self.assertNotIn("lastSignalEmailSentAt", row)
            self.assertEqual(payload["meta"]["updatedAt"], sent_at)

    def test_existing_holdings_are_not_retimestamped_by_unrelated_buy_opinions(self):
        row = {"slotId": "existing", "ticker": "NBIS", "buyDate": "2026.10.15", "status": "보유 중", "investmentType": "swing"}
        with TemporaryDirectory() as directory:
            previous, current = Path(directory) / "previous.json", Path(directory) / "current.json"
            for path in [previous, current]:
                path.write_text(json.dumps({"rows": [row]}))
            notifications.record_signal_email_times(previous, current, [{"ticker": "NBIS", "to": "매수"}], "swing", "2026-10-16T15:00:00+09:00")
            self.assertNotIn("lastSignalEmailSentAt", json.loads(current.read_text())["rows"][0])
