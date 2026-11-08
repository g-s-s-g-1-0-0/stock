from datetime import date, datetime
from unittest import TestCase
from unittest.mock import patch

from scripts import collecting_notifications as collecting
from scripts import web_refresh_notifications as notifications


class CollectingNotificationsTest(TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-11-02T09:00:00-05:00")
        self.settings = {
            "collectingSince": "2026-11-01T00:00:00+00:00", "frequency": "monthly", "amount": 500000,
            "accounts": [{"id": "default", "nickname": "모으기", "buyTiming": "월초",
                          "collecting": [{"ticker": "VOO", "percent": 70}]}],
        }

    def test_scheduled_and_optional_strategies_on_trading_day(self):
        with patch.object(collecting, "monthly_sessions", return_value=(date(2026, 11, 2), date(2026, 11, 16))):
            rows = list(collecting.buy_signals(
                self.settings, {"VOO": {"market": "US", "opinion": "매수", "strategies": ["1.", "2."]}}, {},
                {"VIX (변동성지수)": "19 / 17", "CNN 공포·탐욕지수": "44 / 46"}, self.now,
            ))
            self.assertEqual([key.rsplit(":", 1)[1] for key, _ in rows], ["1", "2", "3", "4"])
            self.assertIn("350,000원", rows[0][1])
            self.assertEqual(list(collecting.buy_signals(
                self.settings, {"VOO": {"market": "US"}}, {}, {}, self.now.replace(day=3),
            )), [])

    def test_signal_and_record_are_separate_and_deduplicated(self):
        recipient = notifications.Recipient("owner", "example@example.invalid", False, {})
        trade = {
            "collectingEntry": True, "collectingRecordedAt": self.now.isoformat(), "slotId": "actual",
            "ticker": "VOO", "investmentAmount": 350000, "strategy": "월 정기매수",
        }
        sent = set()
        with patch.multiple(notifications, **{
            "load_recipients": lambda: [recipient],
            "supabase_request": lambda _: [{"contribution_settings": self.settings, "personal_trade_logs": [trade]}],
            "search_universe_rows_by_ticker": lambda _: {},
            "stock_rows_by_ticker": lambda _: {},
            "technical_rows_by_ticker": lambda: {},
            "market_snapshot_map": lambda: {},
            "read_sent_keys": lambda _: set(sent),
            "record_sent_keys": lambda _, keys, **__: sent.update(keys),
            "append_notification_footer": lambda body, *_: body,
        }), patch.object(collecting, "buy_signals", return_value=[("2026-11-02:default:VOO:1", "계좌 · VOO")]),                 patch.object(notifications, "send_notification") as send:
            self.assertEqual(collecting.send_collecting_notifications(self.now), 1)
            self.assertEqual(collecting.send_collecting_notifications(self.now), 0)
            self.assertEqual([call.args[1] for call in send.call_args_list], ["가치투자 계좌별 투자 알림"])
            self.assertTrue(all("owner" not in key and "VOO" not in key for key in sent))

    def test_conditions_send_once_then_release_with_account_labels(self):
        recipient = notifications.Recipient("owner", "example@example.invalid", False, {})
        state = {}
        stock = {"VOO": {"market": "US", "opinion": "관망"}}
        snapshot = {"VIX (변동성지수)": "20", "CNN 공포·탐욕지수": "50"}
        def write(_, value):
            state.clear()
            state.update(value)
        with patch.multiple(notifications, **{
            "load_recipients": lambda: [recipient],
            "supabase_request": lambda _: [{"contribution_settings": self.settings}],
            "search_universe_rows_by_ticker": lambda _: {},
            "stock_rows_by_ticker": lambda _: stock,
            "technical_rows_by_ticker": lambda: {},
            "market_snapshot_map": lambda: snapshot,
            "read_sent_keys": lambda _: set(),
            "record_sent_keys": lambda *_, **__: None,
            "read_json": lambda _: dict(state),
            "write_json": write,
            "append_notification_footer": lambda body, *_: body,
        }), patch.object(collecting, "monthly_sessions", return_value=(date(2026, 11, 2), date(2026, 11, 16))),                 patch.object(notifications, "send_notification") as send:
            # Mid-month date avoids the monthly scheduled signal.
            self.settings["accounts"][0]["buyTiming"] = "중순"
            self.assertEqual(collecting.send_collecting_notifications(self.now), 1)
            self.assertEqual(collecting.send_collecting_notifications(self.now), 0)
            snapshot["VIX (변동성지수)"] = "19"
            self.assertEqual(collecting.send_collecting_notifications(self.now), 1)
            self.assertIn("매수 조건 해제", send.call_args.args[2])
            self.assertIn("모으기 · VOO", send.call_args.args[2])
