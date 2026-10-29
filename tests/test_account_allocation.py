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
    assert enriched['actionLabel'] == '매수'
    assert '매수 보류로 기록된 종목' in enriched['allocationNote']
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


def test_deferred_reason_never_claims_actual_holdings():
    from calculator.opinion_reasons import build_held_watch_opinion_reason
    row = holding()
    row['status'] = '매수 보류'
    reason = build_held_watch_opinion_reason('3', trade=row, additional_buy_blocked=True)
    assert '신호 추적 유지' in reason
    assert '보유 유지' not in reason
    stock = {'ticker':'QQQ','opinionReason':'매수 조건 해제 · 보유 유지'}
    row['allocationSource'] = 'account'
    technical = {'QQQ': dict(stock)}
    assert logs.sync_account_allocation_guidance([stock],technical,[row])
    assert stock['opinionReason'] == technical['QQQ']['opinionReason'] == '매수 조건 해제 · 보유 유지'


def test_cohu_correction_applies_to_new_holdings_without_rewriting_closed_classification():
    import subprocess
    from calculator.account_allocation import ROOT
    script = """
      import {calculateAccountPortfolio} from './web/src/accountAllocation.mjs';
      const trade={slotId:'cohu',ticker:'COHU',investmentType:'swing',strategy:'3. test',buyDate:'2026.10.15',buyPrice:'$100',currentPrice:'$100',status:'보유 중',riskGroup:'산업재·건설'};
      const settings={initialCapital:10000000,amount:0,swingMegaTrendOnly:false};
      const stock={ticker:'COHU',industry:'산업재, 장비·제조, 자동화'};
      const open=calculateAccountPortfolio([trade],[stock],[],settings,'swing').trades[0];
      const closed=calculateAccountPortfolio([{...trade,status:'손절',sellDate:'2026.10.23',sellPrice:'$90',returnPct:-10}],[stock],[],settings,'swing').trades[0];
      const limited={...settings,allocationByInvestmentType:{swing:{slotCount:2,slotPercents:[15,10]}}};
      const amd={...trade,slotId:'amd',ticker:'AMD',buyDate:'2026.10.14',riskGroup:'반도체·AI 인프라'};
      const capped=calculateAccountPortfolio([amd,trade],[stock],[],limited,'swing').trades[1];
      console.log(JSON.stringify({open:open.riskGroup,closed:closed.riskGroup,capped:capped.investmentAmount,reason:capped.allocationReason}));
    """
    result = subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,text=True,capture_output=True,check=True)
    assert json.loads(result.stdout) == {'open':'반도체·AI 인프라','closed':'산업재·건설',
                                       'capped':0,'reason':'반도체·AI 인프라 산업 비중 20% 한도 초과'}


def test_deferred_opinion_lifecycle_keeps_sell_and_bottom_note(monkeypatch, tmp_path):
    monkeypatch.setattr(notifications, 'runtime_reset_state', lambda: {})
    paths = {name: tmp_path / (name + '.json') for name in ('before', 'after', 'technical', 'old_trades', 'new_trades')}
    trade = holding()
    trade.update(status='매수 보류', allocationStatus='매수 보류', allocationSource='account',
                 allocationReason='투자 가능 현금 부족', investmentAmount=0)
    paths['technical'].write_text(json.dumps({'rows': {'QQQ': {'opinion': '관망'}}}))
    for old, new in [('관망', '매수'), ('매수', '관망'), ('관망', '매도')]:
        paths['before'].write_text(json.dumps({'rows': [{'ticker': 'QQQ', 'opinion': old}]}))
        paths['after'].write_text(json.dumps({'rows': [{'ticker': 'QQQ', 'opinion': new}]}))
        paths['old_trades'].write_text(json.dumps({'rows': [trade]}))
        current = dict(trade)
        if new == '매도':
            current.update(status='익절', sellPrice='$112', returnPct=12, exitReason='익절 기준 도달 +12%')
        paths['new_trades'].write_text(json.dumps({'rows': [current]}))
        changes = notifications.opinion_changes(paths['before'], paths['after'], paths['technical'],
                                               paths['old_trades'], paths['new_trades'])
        assert len(changes) == 1
        assert (changes[0]['from'], changes[0]['to']) == (old, new)
        enriched = notifications.enrich_swing_change_risk(changes[0], {}, {}, [trade] if new != '매도' else [], {})
        body = notifications.opinion_email_body([enriched])
        assert '※ 이 신호는 자금 배분 기준상 매수 보류로 기록된 종목입니다.' in body
        assert '권장 행동: <strong>매수 보류' not in body
        assert body.index('※ 이 신호') > body.index('이유:')


def test_deferred_profit_and_stop_exits_are_not_suppressed(tmp_path):
    old, new = tmp_path / 'before.json', tmp_path / 'after.json'
    trade = holding()
    trade.update(status='매수 보류')
    old.write_text(json.dumps({'rows': [trade]}))
    for status, result in [('익절', 12), ('손절', -25)]:
        closed = dict(trade, status=status, returnPct=result, sellPrice='$112' if result > 0 else '$75')
        new.write_text(json.dumps({'rows': [closed]}))
        changes = notifications.trade_exit_changes(old, new)
        assert len(changes) == 1
        assert changes[0]['to'] == '매도'
        assert changes[0]['status'] == status
        assert '매수 보류로 기록된 종목' in changes[0]['allocationNote']
        assert notifications.trade_exit_changes(new, new) == []


def test_personal_deferred_exit_is_exported_even_without_watchlist(monkeypatch):
    import copy
    trade = holding()
    trade.update(status='매수 보류', allocationStatus='매수 보류')
    captured = []
    monkeypatch.setattr(logs, 'supabase_url', lambda: 'test')
    monkeypatch.setattr(logs, 'service_key', lambda: 'test')
    monkeypatch.setattr(logs, 'load_personal_trade_log_rows', lambda: {'user': [trade]})
    monkeypatch.setattr(logs, 'run_trade_engine', lambda rows, *args, **kwargs:
                        {'trades': [dict(rows[0], status='손절', returnPct=-25)]})
    monkeypatch.setattr(logs, 'merge_personal_engine_result', lambda owner, before, rows: rows)
    monkeypatch.setattr(logs, 'supabase_request', lambda *args, **kwargs: [])
    monkeypatch.setattr(logs, 'write_personal_trade_exits', lambda events: captured.extend(copy.deepcopy(events)))
    logs.process_personal_trade_logs({}, season={}, engine_kwargs={})
    assert captured[0]['ownerId'] == 'user'
    assert captured[0]['trades'][0]['status'] == '손절'


def test_deferred_exit_email_sent_once_for_operator_and_personal_account(monkeypatch, tmp_path):
    monkeypatch.setattr(notifications, 'runtime_reset_state', lambda: {})
    monkeypatch.setattr(notifications, 'NOTIFICATION_STATE', tmp_path / 'state.json')
    monkeypatch.setattr(notifications, 'consume_personal_exit_events', lambda: None)
    monkeypatch.setattr(notifications, 'load_watchlists', lambda: {})
    monkeypatch.setattr(notifications, 'load_personal_open_trades_by_owner', lambda: {})
    monkeypatch.setattr(notifications, 'load_recipients', lambda: [
        notifications.Recipient('admin', 'admin@example.com', True, {'opinionChangeEmail': True}, investment_type='swing'),
        notifications.Recipient('personal', 'personal@example.com', False, {'opinionChangeEmail': True}, investment_type='swing'),
    ])
    captured = []
    def send(recipient, subject, body):
        captured.append((recipient.owner_id, body))
        return 'email'
    monkeypatch.setattr(notifications, 'send_notification', send)
    previous, current = tmp_path / 'stocks-old.json', tmp_path / 'stocks-new.json'
    previous.write_text(json.dumps({'rows': [{'ticker': 'QQQ', 'opinion': '관망'}]}))
    current.write_text(json.dumps({'rows': [{'ticker': 'QQQ', 'opinion': '매도'}]}))
    before, after = tmp_path / 'trades-old.json', tmp_path / 'trades-new.json'
    trade = holding()
    trade.update(status='매수 보류', allocationStatus='매수 보류')
    before.write_text(json.dumps({'rows': [trade]}))
    closed = dict(trade)
    logs.close_trade(closed, sell_price='$112', today='2026.10.29', reason='익절 기준 도달 +12%')
    after.write_text(json.dumps({'rows': [closed]}))
    monkeypatch.setattr(notifications, 'load_personal_exit_changes_by_owner',
                        lambda: {'personal': [notifications.exit_change_from_trade(closed)]})
    assert notifications.send_opinion_notifications(previous, current, before, after) == 2
    assert {owner for owner, _ in captured} == {'admin', 'personal'}
    for _, body in captured:
        assert '매도' in body and '익절 기준 도달' in body
        assert '※ 이 신호는 자금 배분 기준상 매수 보류로 기록된 종목입니다.' in body
    assert 'lastSignalEmailSentAt' in json.loads(after.read_text())['rows'][0]
    assert notifications.send_opinion_notifications(previous, current, before, after) == 0
