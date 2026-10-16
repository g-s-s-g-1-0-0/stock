from datetime import datetime, timezone
import json
from calculator.account_allocation import reconcile_account_trades, load_allocation_accounts
from scripts import record_web_api_logs as logs
from scripts import web_refresh_notifications as notifications


def holding(ticker='QQQ', **fields):
    return dict(slotId=ticker, ticker=ticker, investmentType='swing', strategy='3. 정상장 볼린저 워시아웃',
                buyDate='2026.10.01', buyPrice='$100', currentPrice='$100', status='보유 중',
                sellDate='보유 중', riskGroup='나스닥100 지수 ETF', **fields)


def test_python_uses_browser_engine_and_repairs_zero_amount_holdings():
    settings = {'initialCapital': 0, 'amount': 0}
    rows = reconcile_account_trades([holding()], [], settings)
    assert rows[0]['status'] == '매수 보류'
    assert rows[0]['investmentAmount'] == 0
    assert '현금' in rows[0]['allocationReason']
    assert reconcile_account_trades(rows, [], settings) == rows


def test_settings_are_per_account_and_operator_uses_admin():
    def request(path):
        return ([{'owner_id':'a','contribution_settings':{'initialCapital':123}},
                 {'owner_id':'b','contribution_settings':{'initialCapital':456}}]
                if 'user_settings' in path else [{'id':'b','is_admin':True}])
    accounts, operator = load_allocation_accounts(request)
    assert accounts['a']['initialCapital'] == 123
    assert operator['initialCapital'] == 456


def test_authoritative_deferred_guidance_is_used_in_email_and_is_not_an_exit(tmp_path):
    row = reconcile_account_trades([holding()], [], {'initialCapital':0,'amount':0})[0]
    enriched = notifications.enrich_swing_change_risk({'ticker':'QQQ','to':'매수'}, {}, {}, [row], {})
    assert enriched['actionLabel'] == '매수 보류'
    assert enriched['allocationReason'] == row['allocationReason']
    old, new = tmp_path/'old.json', tmp_path/'new.json'
    old.write_text(json.dumps({'rows':[holding()]}))
    new.write_text(json.dumps({'rows':[row]}))
    assert notifications.trade_exit_changes(old, new) == []


def test_valid_reentry_is_recorded_as_deferred_when_same_ticker_slot_is_blocked(monkeypatch):
    monkeypatch.setattr(logs, 'should_defer_market_signal', lambda *args: False)
    monkeypatch.setattr(logs, 'evaluate_exit_condition', lambda *args, **kwargs: {'shouldExit':False,'reason':None})
    now = datetime(2026,10,16,14,tzinfo=timezone.utc)
    row = holding(restoreWatchDate='2026.10.01')
    stock = {'ticker':'QQQ','name':'QQQ','market':'US','currentPrice':'$90','opinion':'매수'}
    technical = {'QQQ':{'opinion':'매수','entrySignalCodes':'3','현재가':'$90'}}
    result = logs.run_trade_engine([row], {'swing':['QQQ'],'long_term':[]}, stocks=[stock],
        stocks_by_symbol={'QQQ':stock}, previous_stocks={'QQQ':{'opinion':'관망'}}, technical=technical,
        previous_technical={}, season={}, deferred_tickers=set(), nasdaq_peak_alert=False,
        recovery_ended=False, seed_after_reset=False, now=now,today='2026.10.16',today_date=now.date(),mutate_public_state=True)
    assert result['appended'] == 1
    assert result['trades'][-1]['status'] == '매수 보류'
    assert stock['opinion'] == '매수'
    assert row.get('restoreWatchDate') is None
