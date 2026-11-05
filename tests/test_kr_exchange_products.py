import json
from unittest import mock
import pytest
from calculator import build_stock_universe as universe
from calculator.sheet_sources import resolve_market, fetch_ohlcv


def listing(kind, *items):
    return {'resultCode':'success','result':{kind+'ItemList':list(items)}}


def test_fund_list_preserves_korean_names_codes_and_type():
    rows=universe.parse_kr_exchange_products(listing('etf',
        {'itemcode':'418660','itemname':'TIGER 미국나스닥100레버리지(합성)'},
        {'itemcode':'360750','itemname':'TIGER 미국S&P500'},
        {'itemcode':'0043B0','itemname':'신규 ETF'},
        {'itemcode':'wrong','itemname':'invalid'}),'etf')
    assert {r['ticker'] for r in rows}=={'418660','360750','0043B0'}
    assert all(r['market']=='KR' and r['etfFlag'] and r['instrumentType']=='ETF' for r in rows)
    shell=universe.stock_shell(rows[0],'2026-11-06')
    assert shell['instrumentType']=='ETF' and shell['etfFlag']


def test_failed_or_empty_listing_is_not_accepted():
    for value in [{'resultCode':'error'},listing('etf'),listing('etf',{'itemcode':'bad','itemname':'bad'})]:
        with pytest.raises(ValueError):universe.parse_kr_exchange_products(value,'etf')


def test_product_fetch_handles_korean_encoding_and_merges_equities(monkeypatch):
    def fetch(url):
        kind='etn' if '/etnItemList' in url else 'etf'
        code='530107' if kind=='etn' else '418660'
        return json.dumps(listing(kind,{'itemcode':code,'itemname':'한국 '+kind}),ensure_ascii=False).encode('euc-kr')
    monkeypatch.setattr(universe,'fetch_bytes',fetch)
    monkeypatch.setattr(universe,'load_kr_equities',lambda:[{'ticker':'005930','name':'삼성전자','market':'KR'}])
    assert {r['ticker'] for r in universe.load_kr_stocks()}=={'005930','418660','530107'}


def test_source_outage_preserves_previously_published_products(monkeypatch,tmp_path):
    p=tmp_path/'universe.json'
    p.write_text(json.dumps({'rows':[
        {'ticker':'418660','name':'TIGER','market':'KR','instrumentType':'ETF'},
        {'ticker':'530107','name':'삼성 ETN','market':'KR','instrumentType':'ETN'},
        {'ticker':'005930','name':'삼성전자','market':'KR'}]}))
    monkeypatch.setattr(universe,'OUTPUT_PATH',p)
    def failed(url):raise OSError('temporary outage')
    monkeypatch.setattr(universe,'fetch_bytes',failed)
    assert {r['ticker'] for r in universe.load_kr_exchange_products()}=={'418660','530107'}
    p.unlink()
    with pytest.raises(RuntimeError):universe.load_kr_exchange_products()


def test_new_alphanumeric_krx_codes_use_korean_price_provider():
    assert resolve_market('0043B0')=='KR'
    assert resolve_market('360750')=='KR'
    assert resolve_market('GOOGL')=='US'
    assert resolve_market('BRK-B')=='US'
    with mock.patch('calculator.sheet_sources.fetch_kr_ohlcv',return_value=[{'close':100}]) as kr:
        assert fetch_ohlcv('0043B0',count=20)==[{'close':100}]
        kr.assert_called_once_with('0043B0',count=20)
