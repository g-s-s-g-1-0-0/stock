from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import numpy as np
import pandas as pd

from scripts import record_swing_research as sr
from scripts import record_candidate_lab as lab
from scripts.swing_candidate_features import ALL_PATTERNS, feature_frame, watchlist_context
from tests.test_swing_research import obs, session


class CandidateLabTest(unittest.TestCase):
    def test_delayed_entry_uses_second_open_and_preserves_first_open_reference(self):
        o=obs(signals={'lab_test':True})
        days={d:session(50,50) for d in pd.bdate_range('2026-10-06',periods=6).strftime('%Y-%m-%d')}
        days['2026-10-06']=session(100,100)
        days['2026-10-07']=session(50,50,split=2)
        t,labels=sr.replay([o],days,{'lab_test':{'entryDelaySessions':1,'target':.12,'days':20}})
        self.assertEqual('2026-10-07',t[0]['entry'])
        self.assertAlmostEqual(0,t[0]['entryGap'])
        self.assertEqual(5,t[0]['holdingSessions'])
        self.assertEqual('2026-10-06',labels[0]['entry'])
        self.assertAlmostEqual(-.004,t[0]['markNet'])

    def test_delayed_entry_does_not_fill_early_or_skip_missing_intervening_bar(self):
        o=obs(signals={'lab_test':True})
        rule={'lab_test':{'entryDelaySessions':1}}
        self.assertFalse(sr.replay([o],{'2026-10-06':session()},rule)[0])
        missing=session();missing['bars']={}
        t,_=sr.replay([o],{'2026-10-06':missing,'2026-10-07':session()},rule)
        self.assertEqual('invalid',t[0]['status'])
        self.assertEqual('missing_delayed_entry_bar',t[0]['reason'])

    def test_half_profit_executes_next_open_and_remaining_exit(self):
        o=obs(signals={'lab_test':True})
        days={'2026-10-06':session(100,107),'2026-10-07':session(108,113),'2026-10-08':session(112,112)}
        t,_=sr.replay([o],days,{'lab_test':{'stop':.08,'target':.12,'days':20,'mode':'half_at6'}})
        self.assertAlmostEqual(.096,t[0]['net'])
        self.assertEqual('2026-10-07',t[0]['partialFill']['session'])
        self.assertEqual('2026-10-08',t[0]['exit'])
        self.assertEqual(.5,t[0]['remainingWeight'])

    def test_full_target_does_not_also_create_partial_fill(self):
        t,_=sr.replay([obs(signals={'lab_test':True})],{'2026-10-06':session(100,125),'2026-10-07':session(123,123)},
                      {'lab_test':{'target':.12,'days':20,'mode':'half_at6'}})
        self.assertNotIn('partialFill',t[0])
        self.assertAlmostEqual(.226,t[0]['net'])

    def test_atr_two_r_target_and_signal_split_units(self):
        o=obs(features={'close':100.,'low':98.,'rs20':1.,'atr14':10.},signals={'lab_test':True})
        t,_=sr.replay([o],{'2026-10-06':session(50,57,split=2),'2026-10-07':session(57,63),'2026-10-08':session(62,62)},
                      {'lab_test':{'mode':'atr_2r','days':20}})
        self.assertEqual('2026-10-08',t[0]['exit'])
        self.assertAlmostEqual(.236,t[0]['net'])

    def test_signal_low_needs_two_closes_and_next_open(self):
        o=obs(features={'close':100.,'low':95.,'rs20':1.},signals={'lab_test':True})
        t,_=sr.replay([o],{'2026-10-06':session(100,94),'2026-10-07':session(94,94),'2026-10-08':session(91,91)},
                      {'lab_test':{'mode':'signal_low_failure','target':.12,'days':20}})
        self.assertEqual('signal_low_failure',t[0]['reason'])
        self.assertAlmostEqual(-.094,t[0]['net'])

    def test_ma20_exit_requires_arm_and_two_failed_closes(self):
        o=obs(features={'close':100.,'low':95.,'rs20':1.,'ma20':101.},signals={'lab_test':True})
        days={}
        for day,c,ma in [('2026-10-06',99,101),('2026-10-07',102,101),('2026-10-08',100,101),('2026-10-09',99,100),('2026-10-12',98,100)]:
            days[day]=session(100 if not days else c,c);days[day]['bars']['AAA']['ma20']=ma
        t,_=sr.replay([o],days,{'lab_test':{'mode':'ma20_failure','target':.12,'days':20}})
        self.assertEqual('2026-10-12',t[0]['exit'])
        self.assertEqual('ma20_failure',t[0]['reason'])

    def test_diagnostics_get_paths_but_no_paper_trade(self):
        o=obs(features={'close':100.,'low':95.,'rs20':1.,'diagnosticSignal':True},signals={'lab_test':False})
        days={d:session() for d in pd.bdate_range('2026-10-06',periods=6).strftime('%Y-%m-%d')}
        t,labels=sr.replay([o],days)
        self.assertFalse(t)
        self.assertEqual(1,len(labels))
        self.assertTrue(labels[0]['diagnosticOnly'])

    def test_pattern_features_are_causal_and_pivots_confirmed(self):
        index=pd.bdate_range(end='2026-10-05',periods=280).strftime('%Y-%m-%d')
        c=100+np.arange(280)*.1+np.sin(np.arange(280))
        f=pd.DataFrame({'Open':c-.2,'High':c+1,'Low':c-1,'Close':c,'Volume':100+np.arange(280)%23},index=index)
        full=feature_frame(f,f)
        prefix=feature_frame(f.iloc[:-12],f.iloc[:-12])
        self.assertTrue(prefix[list(ALL_PATTERNS)].iloc[-1].equals(full[list(ALL_PATTERNS)].loc[prefix.index[-1]]))
        self.assertEqual(30,len(ALL_PATTERNS))
        # A high in the two still-unconfirmed rightmost bars cannot become the confirmed pivot.
        changed=f.copy();changed.iloc[-1,changed.columns.get_loc('High')]=1000
        latest=feature_frame(changed,changed)
        self.assertNotEqual(1000,latest.confirmedPivotHigh.iloc[-1])

    def test_small_watchlist_is_unknown_not_negative(self):
        r=pd.DataFrame({'Close':[100,101],'ma20':[99,100],'return20':[.1,.11]},index=['a','b'])
        ctx=watchlist_context({'AAA':r},['AAA'],'b','a')
        self.assertIsNone(ctx['breadth20'])
        self.assertIsNone(ctx['medianReturn20'])

    def test_full_collector_freezes_diagnostics_and_does_not_modify_prior_protocol(self):
        days=pd.bdate_range(end='2026-10-06',periods=250)
        parts={}
        for ticker,price in [('AAA',100),('QQQ',100),('^VIX',25)]:
            c=price+np.sin(np.arange(250))
            parts[ticker]=pd.DataFrame({'Open':c-.1,'High':c+1,'Low':c-1,'Close':c,'Volume':100.,'Stock Splits':0.},index=days)
        frame=pd.concat(parts,axis=1).swaplevel(0,1,axis=1)
        now=datetime(2026,10,5,16,10,tzinfo=sr.NY)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);sr.initialize(root)
            target=root/'candidate-lab-v1'
            lab.collect_lab(frame,['AAA'],now,target,{'groups':[]},season={'open':False,'updatedAt':'2026-10-05T20:00:00Z'})
            first=(target/'observations.jsonl').read_text();record=json.loads(first)
            self.assertEqual(30,len(record['features']['patternFlags']))
            self.assertEqual(7,len(record['features']['baseStrategyFlags']))
            self.assertIsNone(record['features']['filterFlags']['rs_vs_watchlist'])
            self.assertEqual(set(lab.ARMS),set(record['signals']))
            lab.collect_lab(frame,['AAA'],now,target,{'groups':[]},season={'open':True,'updatedAt':'2026-10-05T20:00:00Z'})
            self.assertEqual(first,(target/'observations.jsonl').read_text())
            self.assertEqual(sr.PROTOCOL,json.loads((root/'protocol.json').read_text()))
            self.assertIn('ma20',sr.read_lines(target/'sessions.jsonl')[0]['bars']['AAA'])


if __name__=='__main__':unittest.main()
