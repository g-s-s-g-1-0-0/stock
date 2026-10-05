from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import pandas as pd

from scripts import record_data_first_candidates as df
from scripts import record_swing_research as sr
from tests.test_swing_research import obs, session


def feature(**changes):
    return {'sourceReady':True,'close':100.,'open':98.,'previousClose':99.,'low':94.,
            'ma200':90.,'movingAverages':{'20':95.},'rsi':35.,'pctBLow':5.,
            'hist':-.1,'histPrior':-.2,'high52Distance':-35.,'bbRatio':1.5,
            'debtEquity':None,'epsGrowth':None,'pbr':None,'peerRelative20':None,
            'intradayRecovery':1.,**changes}


def market(**changes):
    return {'event':'당분간 없음','peak':False,'recovery':False,'premium':5.,'buyAllowed':True,**changes}


def row(updated, available=None, **data):
    return {'updated':df.facts.stamp(updated),'available':df.facts.stamp(available or updated),
            'artifactHash':updated,'data':data}


class DataFirstTest(unittest.TestCase):
    def source(self, root, key, updated, captured, values, kind='technical'):
        (root/'sources').mkdir(parents=True,exist_ok=True)
        payload={'rows':{t:{'sourceUpdatedAt':updated,'availableAt':captured,'data':v} for t,v in values.items()}}
        sr.write_json(root/'sources'/f'{kind}-{key}.json',payload)
        items=sr.read_lines(root/'sources.jsonl')
        items.append({'kind':kind,'artifactHash':key,'firstCapturedAt':captured})
        sr.write_lines(root/'sources.jsonl',items)

    def prices(self, tickers=('AAA',), end='2026-10-05'):
        days=pd.bdate_range(end=end,periods=260)
        frame=pd.DataFrame({'Open':98.,'High':102.,'Low':94.,'Close':100.,'Volume':1000.},index=days)
        return pd.concat({t:frame.copy() for t in (*tickers,'QQQ')},axis=1).swaplevel(0,1,axis=1)

    def technical(self, **changes):
        return {'dailyPriceDate':'2026-10-05','C - Close':100.,'Candle Open':98.,'C - Low':94.,
                '200일 이동평균선':90.,'20일 이동평균선':95.,'RSI (D)':35.,'볼린저밴드 %B (저가)':5.,
                'MACD Histogram (D)':-.1,'M - H (D-1)':-.2,'52주 신고가 대비':-35.,
                '볼린저밴드 폭 (D)':15.,'지난 60일 볼린저밴드 폭 평균':10.,**changes}

    def test_registry_is_serializable_and_retired_candidates_have_no_arms(self):
        self.assertEqual(9,len(df.CANDIDATES))
        self.assertEqual(5,len(df.RETIRED))
        self.assertEqual(18,len(df.ARM_RULES))
        self.assertFalse(set(df.CANDIDATES)&set(df.RETIRED))
        with TemporaryDirectory() as tmp:
            sr.initialize(Path(tmp),df.PROTOCOL)
            sr.initialize(Path(tmp),df.PROTOCOL)

    def test_unknown_false_and_true_have_different_paired_coverage(self):
        base,filtered=df.PAIRS['S4_debt1']
        f=feature(close=85.,ma200=100.,hist=.1)
        for debt,expected in [(None,(False,False)),(2.,(True,False)),(.5,(True,True))]:
            flags=df.flags({**f,'debtEquity':debt},market())
            self.assertEqual(expected,(flags[base],flags[filtered]))
        base,filtered=df.PAIRS['S3_rsi35']
        flags=df.flags(feature(rsi=40.),market())
        self.assertTrue(flags[base]);self.assertFalse(flags[filtered])
        for m in [market(event='unknown'),market(event='CPI'),market(peak=True)]:
            self.assertFalse(any(df.flags(feature(),m).values()))
        self.assertFalse(any(df.flags(feature(),market(),eligible=False).values()))

    def test_sources_require_completed_matching_day_and_preentry_availability(self):
        now=df.facts.stamp('2026-10-06T13:00:00Z')
        valid=row('2026-10-05T21:00:00Z',**self.technical())
        for r in [row('2026-10-05T19:00:00Z',**self.technical()),
                  row('2026-10-05T21:00:00Z','2026-10-06T13:30:00Z',**self.technical()),
                  row('2026-10-05T21:00:00Z',**self.technical(dailyPriceDate='2026-10-02'))]:
            self.assertIsNone(df.completed_source([r],'2026-10-05',100.,now))
        self.assertIs(valid,df.completed_source([valid],'2026-10-05',100.,now))
        self.assertIsNone(df.completed_source([valid],'2026-10-05',105.,now))

    def test_financial_data_after_close_and_stale_snapshots_are_not_known(self):
        old=row('2026-09-20T18:00:00Z',debtToEquity=.1)
        known=row('2026-10-05T18:00:00Z',debtToEquity=.5)
        future=row('2026-10-05T20:01:00Z',debtToEquity=.2)
        self.assertIs(known,df.financial_source([old,known,future],'2026-10-05'))
        self.assertIsNone(df.financial_source([old,future],'2026-10-05'))

    def test_intraday_uses_two_real_timely_quotes(self):
        early=row('2026-10-05T14:00:00Z',currentPrice=100.)
        late=row('2026-10-05T19:00:00Z',currentPrice=101.)
        result=df.intraday_features([early,late],'2026-10-05')
        self.assertAlmostEqual(1.,result['intradayRecovery'])
        for rows in [[late],[early,{**late,'data':{'currentPrice':100.}}],
                     [early,{**late,'available':df.facts.stamp('2026-10-05T20:01:00Z')}]]:
            self.assertIsNone(df.intraday_features(rows,'2026-10-05')['intradayRecovery'])

    def test_waits_for_completed_archive_then_freezes_original_values(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);facts=root/'facts';history=root/'paper'
            self.source(facts,'early','2026-10-05T19:00:00Z','2026-10-05T19:05:00Z',{'AAA':self.technical()})
            args=dict(history=history,facts_history=facts,event_payload={'groups':[]})
            first=df.collect_data_first(self.prices(),['AAA'],df.facts.stamp('2026-10-05T20:10:00Z'),**args)
            self.assertEqual(0,first['observations'])
            self.source(facts,'complete','2026-10-05T21:00:00Z','2026-10-05T21:05:00Z',{'AAA':self.technical()})
            df.collect_data_first(self.prices(),['AAA'],df.facts.stamp('2026-10-05T22:00:00Z'),**args)
            observations=sr.read_lines(history/'observations.jsonl')
            self.assertEqual(1,len(observations))
            self.assertEqual(35.,observations[0]['features']['rsi'])
            self.assertTrue(observations[0]['signals'][df.PAIRS['S3_rsi35'][1]])
            self.assertTrue(observations[0]['forwardEligible'])
            self.source(facts,'revised','2026-10-05T22:01:00Z','2026-10-05T22:05:00Z',{'AAA':self.technical(**{'RSI (D)':70.})})
            df.collect_data_first(self.prices(),['AAA'],df.facts.stamp('2026-10-05T23:00:00Z'),**args)
            self.assertEqual(observations,sr.read_lines(history/'observations.jsonl'))

    def test_late_capture_does_not_backfill_and_future_capture_cannot_leak(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);facts=root/'facts';history=root/'paper'
            self.source(facts,'late','2026-10-05T21:00:00Z','2026-10-06T14:00:00Z',{'AAA':self.technical()})
            self.assertFalse(df.source_records(facts,df.facts.stamp('2026-10-05T22:00:00Z'))['technical'])
            df.collect_data_first(self.prices(),['AAA'],df.facts.stamp('2026-10-06T14:05:00Z'),
                                  history=history,facts_history=facts,event_payload={'groups':[]})
            observation=sr.read_lines(history/'observations.jsonl')[0]
            self.assertFalse(observation['forwardEligible'])
            self.assertFalse(observation['features']['sourceReady'])
            self.assertFalse(any(observation['signals'].values()))
        self.assertTrue(df.forward_eligible('2026-10-05',df.facts.stamp('2026-10-06T13:29:00Z')))
        self.assertFalse(df.forward_eligible('2026-10-05',df.facts.stamp('2026-10-06T13:30:00Z')))

    def test_peer_comparison_requires_ten_archived_non_etf_members(self):
        tickers=[f'A{i}' for i in range(10)]+['XYZ']
        with TemporaryDirectory() as tmp:
            root=Path(tmp);facts=root/'facts'
            self.source(facts,'closed','2026-10-05T21:00:00Z','2026-10-05T21:05:00Z',{t:self.technical() for t in tickers})
            self.source(facts,'fund','2026-10-05T18:00:00Z','2026-10-05T18:05:00Z',{t:{'pbr':3.} for t in tickers},'valuation')
            for n in [9,10]:
                members=tickers[:n]+['XYZ'];history=root/f'paper{n}'
                df.collect_data_first(self.prices(tickers),members,df.facts.stamp('2026-10-05T22:00:00Z'),
                                      history=history,facts_history=facts,event_payload={'groups':[]},names={'XYZ':'2X ETF'})
                record=next(r for r in sr.read_lines(history/'observations.jsonl') if r['ticker']=='A0')
                self.assertEqual(n,record['features']['peerCount'])
                self.assertEqual(n==10,record['signals'][df.PAIRS['N_value_laggard'][1]])

    def test_all_new_arms_use_next_open_and_common_twelve_percent_target(self):
        signal=obs(signals=dict.fromkeys(df.ARM_RULES,True))
        sessions={'2026-10-06':session(100,111),'2026-10-07':session(111,113),'2026-10-08':session(114,114)}
        trades,_=sr.replay([signal],sessions,df.ARM_RULES)
        self.assertEqual(18,len(trades))
        self.assertTrue(all(t['entry']=='2026-10-06' and t['exit']=='2026-10-08' for t in trades))
        self.assertTrue(all(abs(t['net']-.136)<1e-9 for t in trades))


if __name__=='__main__':
    unittest.main()
