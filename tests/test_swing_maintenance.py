from pathlib import Path
from unittest import mock
from scripts import web_refresh_notifications as notifications


def test_swing_delivery_stops_but_other_notifications_remain():
    swing = notifications.Recipient('u', 'x@example.com', True, {'opinionChangeEmail': True}, investment_type='swing')
    value = notifications.Recipient('u', 'x@example.com', False, {'opinionChangeEmail': True}, investment_type='long_term')
    with mock.patch.object(notifications, 'SWING_MAINTENANCE', True):
        assert not notifications.enabled(swing, 'opinionChangeEmail')
        assert notifications.enabled(value, 'opinionChangeEmail')
        assert notifications.enabled(swing, 'earningsDayBefore')
        with mock.patch.object(notifications, 'send_notification') as send:
            assert notifications.send_trade_exit_notifications(Path('missing'), Path('missing')) == 0
            send.assert_not_called()
    with mock.patch.object(notifications, 'SWING_MAINTENANCE', False):
        assert notifications.enabled(swing, 'opinionChangeEmail')


def test_maintenance_does_not_exempt_admins():
    for admin in (False, True):
        recipient = notifications.Recipient('u', 'x@example.com', admin, {'opinionChangeEmail': True}, investment_type='swing')
        with mock.patch.object(notifications, 'SWING_MAINTENANCE', True):
            assert not notifications.enabled(recipient, 'opinionChangeEmail')


def test_existing_swing_preferences_resolve_to_value_during_maintenance():
    with mock.patch.object(notifications, 'SWING_MAINTENANCE', True):
        assert notifications.normalize_investment_type('swing') == 'long_term'
    with mock.patch.object(notifications, 'SWING_MAINTENANCE', False):
        assert notifications.normalize_investment_type('swing') == 'swing'
