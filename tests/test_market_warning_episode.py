from datetime import datetime
from unittest import mock
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import web_refresh_notifications as notifications


def test_warning_episode_and_recovery(tmp_path):
    state = tmp_path / 'state.json'
    technical = tmp_path / 'technical.json'
    recipient = notifications.Recipient('admin', 'admin@example.com', True, {})
    duplicate = notifications.Recipient('other-account', 'ADMIN@example.com', True, {})
    day = [23]

    def refresh(parts):
        signals = dict(zip(('breadth', 'treasury', 'credit'), ({'status': x} for x in parts)))
        signals['status'] = notifications.aggregate_market_signal_status(parts)
        notifications.write_json(technical, {'marketSignals': signals})
        with mock.patch.object(notifications, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, day[0], 12, tzinfo=ZoneInfo('America/New_York'))
            return notifications.send_market_signal_notifications()

    with mock.patch.multiple(notifications, NOTIFICATION_STATE=state, DEFAULT_TECHNICAL=technical), \
         mock.patch.object(notifications, 'load_recipients', return_value=[recipient, duplicate]), \
         mock.patch.object(notifications, 'market_signal_email_body', return_value='warning'), \
         mock.patch.object(notifications, 'send_email') as send:
        assert refresh(['주의', '정상', '주의']) == 1
        assert refresh(['주의', '정상', '주의']) == 0
        before = state.read_text()
        assert refresh(['주의', '정상', '판단 불가']) == 0
        assert state.read_text() == before
        assert refresh(['주의', '정상', '주의']) == 0
        assert refresh(['정상', '정상', '정상']) == 0
        assert refresh(['정상', '정상', '정상']) == 0
        assert refresh(['주의', '정상', '주의']) == 0
        day[0] = 26
        assert refresh(['정상', '정상', '정상']) == 0
        day[0] = 27
        assert refresh(['정상', '정상', '정상']) == 0
        assert refresh(['주의', '정상', '주의']) == 1
        assert send.call_count == 2


def test_existing_warning_is_not_resent_after_upgrade(tmp_path):
    state = tmp_path / 'state.json'
    technical = tmp_path / 'technical.json'
    notifications.write_json(state, {'marketHighSignalStatus': '경고', 'marketHighSignalsSentAt': '2026-10-22T15:00:09+00:00'})
    notifications.write_json(technical, {'marketSignals': {
        'status': '경고', 'breadth': {'status': '주의'},
        'treasury': {'status': '정상'}, 'credit': {'status': '주의'},
    }})
    with mock.patch.multiple(notifications, NOTIFICATION_STATE=state, DEFAULT_TECHNICAL=technical), \
         mock.patch.object(notifications, 'send_email') as send:
        assert notifications.send_market_signal_notifications() == 0
        send.assert_not_called()


class MarketWarningEpisodeTest(unittest.TestCase):
    def test_episode(self):
        with TemporaryDirectory() as folder:
            test_warning_episode_and_recovery(Path(folder))

    def test_migration(self):
        with TemporaryDirectory() as folder:
            test_existing_warning_is_not_resent_after_upgrade(Path(folder))

    def test_workflow_saves_state_after_later_failure(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/web-data-refresh.yml').read_text()
        step = workflow.split('- name: Commit notification send state', 1)[1].split('- name:', 1)[0]
        self.assertIn("always()", step)

    def test_partial_send_retry_skips_successful_address(self):
        with TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            technical = Path(folder) / 'technical.json'
            notifications.write_json(technical, {'marketSignals': {
                'status': '경고', 'breadth': {'status': '주의'},
                'treasury': {'status': '정상'}, 'credit': {'status': '주의'},
            }})
            recipients = [notifications.Recipient(str(i), f'admin{i}@example.com', True, {}) for i in range(2)]
            with mock.patch.multiple(notifications, NOTIFICATION_STATE=state, DEFAULT_TECHNICAL=technical), \
                 mock.patch.object(notifications, 'load_recipients', return_value=recipients), \
                 mock.patch.object(notifications, 'market_signal_email_body', return_value='warning'), \
                 mock.patch.object(notifications, 'send_email', side_effect=[None, RuntimeError('delivery failed')]) as send:
                with self.assertRaises(RuntimeError):
                    notifications.send_market_signal_notifications()
                self.assertEqual(send.call_count, 2)
            with mock.patch.multiple(notifications, NOTIFICATION_STATE=state, DEFAULT_TECHNICAL=technical), \
                 mock.patch.object(notifications, 'load_recipients', return_value=recipients), \
                 mock.patch.object(notifications, 'market_signal_email_body', return_value='warning'), \
                 mock.patch.object(notifications, 'send_email') as send:
                self.assertEqual(notifications.send_market_signal_notifications(), 1)
                self.assertEqual(send.call_args.args[0], 'admin1@example.com')
