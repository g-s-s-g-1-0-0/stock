from datetime import date
from unittest.mock import patch

from scripts import record_web_api_logs as logs
from scripts import web_refresh_notifications as mail
from scripts.preview_opinion_email import build_preview


def test_reentry_block_repairs_only_unopened_buy():
    stocks = [{'ticker': t, 'opinion': '매수', 'currentPrice': '$100', 'strategies': ['3']} for t in ['BLOCK', 'OPEN', 'ALLOW']]
    technical = {s['ticker']: {'entrySignalCodes': '3'} for s in stocks}
    trades = [{'ticker': t, 'investmentType': 'swing', 'status': '손절', 'sellDate': '2026.10.23', 'sellPrice': '$100'} for t in ['BLOCK', 'OPEN', 'ALLOW']]
    trades.append({'ticker': 'OPEN', 'investmentType': 'swing', 'status': '보유 중', 'strategy': '3'})
    with patch.object(logs, 'sell_reentry_allowed', side_effect=lambda closed, *_: closed['ticker'] == 'ALLOW'):
        assert logs.repair_unqualified_buy_opinions(stocks, technical, trades, date(2026, 10, 26))
    assert [s['opinion'] for s in stocks] == ['관망', '매수', '매수']
    assert technical['BLOCK']['entrySignalCodes'] == ''


def test_post_sell_watch_reason_is_short_even_with_market_details():
    assert mail.concise_opinion_reason('매도', '관망', {}, {'opinionReason': 'QQQ 과열(+11% > 차단선 +9%)'}, {}) == '48시간 대기 종료 · 매수 조건 미충족'


def test_historical_13_preview_has_no_false_entry_or_actual_sell():
    changes, body = build_preview()
    assert len(changes) == 12
    assert all(c['to'] == '관망' for c in changes)
    assert not any(c['ticker'] == 'QLD' for c in changes)
    assert '매수 후보 종료' not in body
    assert '신규 진입' not in body and '수익률' not in body


def test_strategy4_repairs_false_recovery_watch_without_new_trade():
    from datetime import datetime, timezone
    stock = {'ticker': '000660', 'market': 'KR', 'opinion': '매수', 'currentPrice': '1487000'}
    trade = {'ticker': '000660', 'market': 'KR', 'investmentType': 'swing',
             'strategy': '4. 장기선 아래 반등 초입', 'status': '보유 중',
             'buyDate': '2026.10.28', 'buyPrice': '1465000', 'restoreWatchDate': '2026.10.28'}
    technical = {'000660': {'현재가': '1487000', 'entrySignalCodes': '4'}}
    with patch.object(logs, 'save_strategy_season_state'), patch.object(logs, 'should_defer_market_signal', return_value=False):
        result = logs.run_trade_engine(
            [trade], {'swing': ['000660']}, stocks=[stock], stocks_by_symbol={'000660': stock},
            previous_stocks={'000660': {'opinion': '관망', 'opinionReason': '매수 조건 해제 — 200일선 위 회복'}},
            technical=technical, previous_technical={}, season={}, deferred_tickers=set(),
            nasdaq_peak_alert=False, recovery_ended=False, seed_after_reset=False,
            now=datetime(2026, 10, 28, 7, tzinfo=timezone.utc), today='2026.10.28',
            today_date=date(2026, 10, 28), mutate_public_state=True)
    assert stock['opinion'] == '매수'
    assert len(result['trades']) == 1 and result['appended'] == 0
    assert 'restoreWatchDate' not in trade
