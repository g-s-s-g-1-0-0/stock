from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
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
        self.stock = {"market": "US", "opinion": "관망", "currentPrice": "$100"}
        self.snapshot = {"VIX (변동성지수)": "20", "CNN 공포·탐욕지수": "50"}
        self.trades = []
        self.sessions = tuple(date(2026, 11, day) for day in range(1, 31)
                              if date(2026, 11, day).weekday() < 5)
        recipient = notifications.Recipient("owner", "example@example.invalid", False, {})
        stack = ExitStack()
        self.addCleanup(stack.close)
        directory = stack.enter_context(TemporaryDirectory())
        self.state_path = Path(directory) / "state.json"
        stack.enter_context(patch.multiple(notifications, **{
            "NOTIFICATION_STATE": self.state_path,
            "load_recipients": lambda: [recipient],
            "supabase_request": lambda _: [{
                "contribution_settings": self.settings, "personal_trade_logs": self.trades,
            }],
            "search_universe_rows_by_ticker": lambda _: {},
            "stock_rows_by_ticker": lambda _: {"VOO": self.stock},
            "technical_rows_by_ticker": lambda: {},
            "market_snapshot_map": lambda: self.snapshot,
            "append_notification_footer": lambda body, *_: body,
        }))
        stack.enter_context(patch.object(collecting, "monthly_sessions", return_value=self.sessions))
        self.send = stack.enter_context(patch.object(notifications, "send_notification"))

    def test_scheduled_and_optional_strategies_share_one_account_card(self):
        self.stock.update(opinion="매수", strategies=["1.", "2."])
        self.assertEqual(collecting.send_collecting_notifications(self.now), 1)
        body = self.send.call_args.args[2]
        self.assertEqual(body.count(">VOO</div>"), 1)
        self.assertIn(">모으기</h2>", body)
        self.assertIn("350,000원", body)
        self.assertIn("VIX 20 이상", body)
        self.assertIn("120일 저가 회귀선", body)
        self.assertIn("20·60·144·200일선", body)
        self.assertNotIn("시장 트렌드", body)
        self.assertEqual(collecting.send_collecting_notifications(self.now), 0)

    def test_release_and_reactivation_require_time_and_price(self):
        self.settings["accounts"][0]["buyTiming"] = "중순"
        self.assertEqual(collecting.send_collecting_notifications(self.now), 1)
        self.snapshot["VIX (변동성지수)"] = "19"
        self.assertEqual(collecting.send_collecting_notifications(self.now + timedelta(hours=2)), 1)
        self.assertIn("매수 조건 해제", self.send.call_args.args[2])
        self.snapshot["VIX (변동성지수)"] = "20"
        self.stock["currentPrice"] = "$97"
        self.assertEqual(collecting.send_collecting_notifications(self.now + timedelta(hours=4)), 0)
        self.stock["currentPrice"] = "$98"
        self.assertEqual(collecting.send_collecting_notifications(self.now + timedelta(days=2)), 0)
        self.stock["currentPrice"] = "$97"
        self.assertEqual(collecting.send_collecting_notifications(self.now + timedelta(days=2, hours=1)), 1)
        self.assertEqual(collecting.send_collecting_notifications(self.now + timedelta(days=2, hours=2)), 0)

    def test_actual_fill_blocks_optional_strategies_only_for_its_account(self):
        self.settings["accounts"][0]["buyTiming"] = "중순"
        self.settings["accounts"].append({**self.settings["accounts"][0], "id": "isa", "nickname": "ISA"})
        self.trades.append({
            "collectingEntry": True, "collectingRecordedAt": self.now.isoformat(), "slotId": "actual",
            "ticker": "VOO", "buyPrice": "$100", "investmentAmount": 350000, "strategy": "월 정기매수",
        })
        self.assertEqual(collecting.send_collecting_notifications(self.now), 1)
        body = self.send.call_args.args[2]
        self.assertIn("매수 기록 저장", body)
        self.assertEqual(body.count("전략 2 간편 공포 매수"), 1)
        self.assertIn(">ISA</h2>", body)
        self.assertEqual(collecting.send_collecting_notifications(self.now), 0)
        sent = notifications.read_sent_keys("collecting")
        self.assertTrue(all("owner" not in key and "VOO" not in key for key in sent))

    def test_old_alerts_without_reference_price_still_observe_the_window(self):
        self.settings["accounts"][0]["buyTiming"] = "중순"
        key = collecting.private_key(self.now.isoformat(), "signal", "owner", "2026-11-02:default:VOO:2")
        notifications.record_sent_keys("collecting", {key})
        self.assertEqual(collecting.send_collecting_notifications(self.now + timedelta(hours=3)), 0)
        self.assertFalse(collecting.repeat_buy_allowed((self.now, None), 97, "US", self.now + timedelta(days=14)))
        self.assertTrue(collecting.repeat_buy_allowed((self.now, None), 97, "US", self.now + timedelta(days=15)))

    def test_failed_delivery_does_not_consume_the_signal(self):
        self.send.side_effect = RuntimeError("delivery failed")
        with self.assertRaises(RuntimeError):
            collecting.send_collecting_notifications(self.now)
        self.assertFalse(self.state_path.exists())
        self.send.side_effect = None
        self.assertEqual(collecting.send_collecting_notifications(self.now), 1)
