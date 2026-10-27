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
    assert len(changes) == 13
    assert all(c['to'] == '관망' for c in changes)
    qld = next(c for c in changes if c['ticker'] == 'QLD')
    assert qld['fromLabel'] == '매수 보류' and qld['toLabel'] == '매수 후보 종료'
    assert '신규 진입' not in body and '수익률' not in body
