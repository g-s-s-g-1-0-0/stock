from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calculator import pipeline, sheet_sources
from calculator.rules import IndicatorRow, evaluate_buy_condition, evaluate_exit_condition
from calculator.trend_strategies import build_trend_signal, chart_phase, trend_market_blocked
from scripts import record_web_api_logs as logs
from scripts import web_refresh_notifications as notifications


def bars():
    closes = [150 - .25 * i for i in range(280)]
    return [dict(date=f'2025-{i:03}', open=c, high=c + .2, low=c - .2, close=c, volume=1000000) for i, c in enumerate(closes)]


def buy(signal, **kwargs):
    return evaluate_buy_condition(
        IndicatorRow(stock_name='TEST', current_price=100, ma200=90, rsi=50),
        vix=15, ixic_dist=kwargs.pop('ixic_dist', -2.5), ixic_filter_active=False,
        trend_market_allowed=kwargs.pop('trend_market_allowed', True),
        trend_signal={'signalClose': 100, 'stopPrice': 94, **signal}, **kwargs)


def test_retest_is_after_breakout_and_consumed_once():
    data = bars()
    resistance = max(r['high'] for r in data[-20:])
    data.append(dict(date='breakout', open=resistance*1.006, low=resistance*1.004, high=resistance*1.02, close=resistance*1.01, volume=1000000))
    assert chart_phase(data, len(data)-1)[0] == '상승 전환 초입'
    assert not build_trend_signal(data)['retest']
    data.append(dict(date='retest', open=resistance*1.005, low=resistance, high=resistance*1.01, close=resistance*1.005, volume=1000000))
    result = build_trend_signal(data)
    assert result['retest']
    assert result['resistance'] == resistance
    data.append({**data[-1], 'date': 'later'})
    assert not build_trend_signal(data)['retest']


@pytest.mark.parametrize('cancel', ['break', 'timeout'])
def test_retest_cancelled_after_support_break_or_ten_sessions(cancel):
    data = bars()
    resistance = max(r['high'] for r in data[-20:])
    data.append(dict(date='breakout', open=resistance*1.006, low=resistance*1.004, high=resistance*1.02, close=resistance*1.01, volume=1000000))
    if cancel == 'break':
        data.append(dict(date='failed', open=resistance*.96, low=resistance*.95, high=resistance*.97, close=resistance*.96, volume=1000000))
    else:
        data.extend(dict(date=str(i), open=resistance*1.04, low=resistance*1.02, high=resistance*1.05, close=resistance*1.04, volume=1000000) for i in range(10))
    data.append(dict(date='late', open=resistance*1.005, low=resistance, high=resistance*1.01, close=resistance*1.005, volume=1000000))
    assert not build_trend_signal(data)['retest']


def test_attempt_is_fresh_phase_and_no_future_bar_is_required():
    data = bars()
    data.append(dict(date='attempt', open=81, low=80, high=82, close=81, volume=1000000))
    result = build_trend_signal(data)
    assert result['attempt']
    assert result['stopPrice'] == min(r['low'] for r in data[-21:-1])*.97
    data.append({**data[-1], 'date': 'next'})
    assert not build_trend_signal(data)['attempt']
    assert build_trend_signal(data[:-1]) == result


def test_market_hysteresis_does_not_release_in_deep_crash():
    data = [dict(close=100.) for _ in range(220)]
    data.append(dict(close=85.))
    assert trend_market_blocked(data)
    data.append(dict(close=97.))
    assert trend_market_blocked(data)
    data.append(dict(close=98.))
    assert not trend_market_blocked(data)
    assert trend_market_blocked([])


@pytest.mark.parametrize('signal,expected', [({'retest':True},'5'), ({'attempt':True},'6'), ({'retest':True,'attempt':True},'5')])
def test_new_strategy_priority(signal, expected):
    assert buy(signal)['strategyType'] == expected


@pytest.mark.parametrize('kwargs', [{'ixic_dist':-3.01}, {'ixic_dist':9.01}, {'trend_market_allowed':False}, {'is_holding':True,'holding_strategy_type':'1'}])
def test_new_entry_market_and_holding_blocks(kwargs):
    assert buy({'attempt':True}, **kwargs)['strategyType'] is None


def test_recovery_upper_bound_and_entry_risk_boundaries():
    assert buy({'attempt':True}, ixic_dist=18, is_recovery_market=True, nasdaq_buy_block_max=18)['strategyType'] == '6'
    assert buy({'attempt':True}, ixic_dist=18.01, is_recovery_market=True, nasdaq_buy_block_max=18)['strategyType'] is None
    assert buy({'attempt':True,'stopPrice':92})['strategyType'] == '6'
    assert buy({'attempt':True,'stopPrice':91.99})['strategyType'] is None
    assert buy({'retest':True,'candidatePrice':103.01})['strategyType'] is None


def test_existing_strategy_wins_over_both_new_signals():
    row=IndicatorRow(stock_name='TEST',current_price=100,ma200=110,macd_hist_d1=-1,macd_hist=1)
    result=evaluate_buy_condition(row,vix=15,ixic_dist=-2.5,ixic_filter_active=False,trend_market_allowed=True,
                                  trend_signal={'retest':True,'attempt':True,'signalClose':100,'stopPrice':94})
    assert result['strategyType']=='4'
    assert logs.entry_signal_codes({'entrySignalCodes':'6,5,1'}) == ['1']


@pytest.mark.parametrize('code,price,days,peak,recovery,expected', [
    ('5',112,0,False,False,None), ('5',92,0,False,False,'손절'),
    ('6',112,0,False,False,'익절'), ('6',94,0,False,False,'손절'),
    ('6',94.01,0,False,False,None), ('5',100,60,False,False,'보유기간'),
    ('6',100,59,False,False,None), ('5',100,0,True,False,'나스닥'),
    ('6',100,0,False,True,'회복장'),
])
def test_new_exit_rules(code,price,days,peak,recovery,expected):
    result=evaluate_exit_condition(IndicatorRow(stock_name='TEST',current_price=price,entry_price=100,support_stop_price=94),
                                   strategy_type=code,trading_days=days,nasdaq_peak_alert=peak,recovery_ended=recovery)
    assert result['shouldExit'] == (expected is not None)
    if expected: assert expected in result['reason']


def engine(trades, row, price=100, **kwargs):
    stock=dict(ticker='TEST',name='Test',market='US',currentPrice=f'${price:.2f}',opinion='매수')
    return logs.run_trade_engine(trades, {'swing':['TEST'],'long_term':['TEST']},
        stocks=[stock],stocks_by_symbol={'TEST':stock},previous_stocks={},technical={'TEST':row},previous_technical={},
        season={},deferred_tickers=set(),nasdaq_peak_alert=kwargs.get('peak',False),recovery_ended=False,
        seed_after_reset=False,now=datetime(2026,9,10,15,tzinfo=timezone.utc),today='2026.09.10',
        today_date=date(2026,9,10),mutate_public_state=False)


def test_log_entry_freezes_stop_and_live_exit_uses_it():
    row={'entrySignalCodes':'6','dailyPriceDate':'2026-09-10','trendSignal':{'signalClose':100,'stopPrice':94,'signalDate':'2026-09-10'}}
    result=engine([],row)
    assert result['appended']==1
    trade=result['trades'][0]
    assert trade['investmentType']=='swing'
    assert trade['supportStopPrice']==94
    row['trendSignal']['stopPrice']=80
    exited=engine([trade],row,price=93)
    assert exited['closed']==1
    assert exited['trades'][0]['supportStopPrice']==94
    assert exited['trades'][0]['status']=='손절'
    assert exited['appended']==0


def test_no_duplicate_add_or_strategy_switch_with_new_holdings():
    row={'entrySignalCodes':'5','dailyPriceDate':'2026-09-10','trendSignal':{'signalClose':100,'signalDate':'2026-09-10'}}
    trade=engine([],row)['trades'][0]
    for code in ['1','3','5','6']:
        result=engine([deepcopy(trade)],{**row,'entrySignalCodes':code})
        swing=[t for t in result['trades'] if t.get('investmentType')=='swing']
        assert len(swing)==1
        assert swing[0]['strategy']=='5. 저항선 돌파 후 눌림'


def test_new_entry_gap_risk_missing_data_and_peak_block():
    row={'entrySignalCodes':'6','trendSignal':{'signalClose':100,'stopPrice':94,'signalDate':'2026-09-10'}}
    assert engine([],row,price=104)['appended']==0
    assert engine([],row,price=103)['appended']==0
    assert engine([],{'entrySignalCodes':'6'})['appended']==0
    assert engine([],row,peak=True)['appended']==0


def test_holding_session_counter_ignores_holidays_and_repeated_refreshes():
    trade={'buyDate':'2026.09.04'}
    row={'tradingDates':['2026-09-04','2026-09-08','2026-09-09']}
    assert logs.trend_held_sessions(trade,row)==2
    assert logs.trend_held_sessions(trade,row)==2
    assert logs.trend_held_sessions(trade,{})==2


def test_new_strategy_respects_same_ticker_cooldown_after_other_strategy_exit():
    old=dict(ticker='TEST',investmentType='swing',strategy='1',buyDate='2026.08.01',buyPrice='$90.00',
             sellDate='2026.09.10',sellPrice='$100.00',returnPct=11.11,status='익절')
    row={'entrySignalCodes':'6','trendSignal':{'signalClose':100,'stopPrice':94,'signalDate':'2026-09-10'}}
    assert engine([old],row)['appended']==0


def test_pipeline_exposes_new_strategy_to_stocks_and_notifications(monkeypatch):
    monkeypatch.setattr(sheet_sources,'fetch_ohlcv',lambda ticker:bars())
    monkeypatch.setattr(sheet_sources,'qqq_return_pct',lambda days:0)
    raw=sheet_sources.calc_technical_row('TEST')
    raw.update(close=100,ma200=90,rsi=50,pctBLow=50,
               trendSignal={'retest':True,'signalClose':100,'signalDate':'2026-09-10'})
    monkeypatch.setattr(pipeline,'calc_technical_row',lambda ticker:raw)
    monkeypatch.setattr(pipeline,'fetch_us_extended_price',lambda ticker:100)
    result=pipeline.latest_technical_row({'ticker':'TEST','name':'Test','market':'US'},
        qqq_market_state={'premiumPercent':-2.5,'buyBlockMax':9,'trendEntryBlocked':False},vix=15)
    assert result['entrySignalCodes']=='5'
    assert result['opinion']=='매수'
    assert pipeline.stock_strategies_from_technical(result)==['5. 저항선 돌파 후 눌림']
    assert '전략5' in result['decisionLog']
    assert '눌림' in notifications.buy_reason({},result)
    assert logs.target_return_pct('5')==0
    assert logs.target_return_pct('6')==12
