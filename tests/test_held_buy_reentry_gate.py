from datetime import datetime, timezone
import pytest
from scripts import record_web_api_logs as logs
from scripts import web_refresh_notifications as notifications


@pytest.mark.parametrize('status', ['보유 중', '매수 보류'])
@pytest.mark.parametrize('previous,reason,watch', [
    ('관망', '', None),
    ('관망', '이벤트 기간 관망 (금리 발표)', None),
    ('매수', '', '2026.10.16'),
])
def test_maintenance_recovery_does_not_publish_buy(monkeypatch, tmp_path, status, previous, reason, watch):
    monkeypatch.setattr(logs, 'should_defer_market_signal', lambda *args: False)
    now = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)
    trade = dict(slotId='QQQ_swing_3_20261015_1', ticker='QQQ', investmentType='swing',
                 strategy='3. 정상장 볼린저 워시아웃', buyDate='2026.10.15', buyPrice='$718.28',
                 status=status, sellDate='보유 중' if status == '보유 중' else '-')
    if watch:
        trade['restoreWatchDate'] = watch
    stock = dict(ticker='QQQ', market='US', currentPrice='$720.51', opinion='매수', strategies=[trade['strategy']])
    technical = {'QQQ': dict(opinion='매수', entrySignalCodes='3', entryStrategy=trade['strategy'])}
    before = {'QQQ': dict(stock, opinion=previous, opinionReason=reason)}
    result = logs.run_trade_engine(
        [trade], {'swing': ['QQQ'], 'long_term': []}, stocks=[stock], stocks_by_symbol={'QQQ': stock},
        previous_stocks=before, technical=technical, previous_technical={}, season={},
        deferred_tickers=set(), nasdaq_peak_alert=False, recovery_ended=False, seed_after_reset=False,
        now=now, today='2026.10.16', today_date=now.date(), mutate_public_state=True,
    )
    assert result['appended'] == 0
    assert len(result['trades']) == 1
    assert trade['status'] == status
    assert stock['opinion'] == technical['QQQ']['opinion'] == '관망'
    assert technical['QQQ']['entrySignalCodes'] == ''
    assert trade['restoreWatchDate'] == '2026.10.16'
    # The notification detector must not emit another buy transition.
    import json
    old, new, tech = [tmp_path / name for name in ['old.json', 'new.json', 'tech.json']]
    old.write_text(json.dumps({'rows': list(before.values())}))
    new.write_text(json.dumps({'rows': [stock]}))
    tech.write_text(json.dumps(technical))
    monkeypatch.setattr(notifications, 'runtime_reset_state', lambda: {})
    assert not any(c['to'] == '매수' for c in notifications.opinion_changes(old, new, tech))


def test_reentry_requires_both_drop_and_elapsed_trading_days():
    trade = {'buyPrice': '$100', 'restoreWatchDate': '2026.10.01'}
    assert logs.hold_restore_allowed(trade, 90, datetime(2026, 10, 16).date())
    assert not logs.hold_restore_allowed(trade, 91, datetime(2026, 10, 16).date())
    assert not logs.hold_restore_allowed(trade, 90, datetime(2026, 10, 2).date())
