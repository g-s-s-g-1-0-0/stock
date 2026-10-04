from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

import pandas as pd

from scripts import record_research_facts as facts
from scripts import record_swing_research as sr


class ResearchFactsTest(unittest.TestCase):
    def write_source(self, root, price=100, updated='2026-10-05T18:00:00Z'):
        path=root/'data/cache'
        path.mkdir(parents=True,exist_ok=True)
        data={'meta':{'updatedAt':updated},'rows':{'AAA':{'ticker':'AAA','market':'US','currentPrice':price,'updatedAt':updated,'dailyPriceDate':'2026-10-05'}}}
        raw=json.dumps(data).encode()
        (path/'technical.json').write_bytes(raw)
        (path/'valuation.json').write_text(json.dumps({'meta':{'updatedAt':updated},'rows':{'AAA':{'roe':'15%','earningsDate':'2026-10-20','epsNextYear':'20'}}}))
        return raw

    def prices(self, last=101):
        days=pd.bdate_range(end='2026-10-05',periods=30)
        frames={}
        for ticker in ['QQQ',*facts.BENCHMARKS]:
            close=[100.]*29+[float(last)]
            frames[ticker]=pd.DataFrame({'Open':100.,'High':max(102.,last),'Low':99.,'Close':close,'Volume':1000.},index=days)
        return pd.concat(frames,axis=1).swaplevel(0,1,axis=1)

    def test_matching_git_revision_proves_availability_but_changed_file_does_not(self):
        now=datetime(2026,10,5,20,10,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);raw=self.write_source(root)
            log=b'abcdef 2026-10-05T18:02:00+00:00'
            with patch.object(facts.subprocess,'check_output',side_effect=[log,raw]):
                recorded=facts.source_snapshot(root,'technical',['AAA'],now)
            self.assertEqual('matching_git_revision',recorded['availabilityEvidence'])
            self.assertEqual('2026-10-05T18:02:00Z',recorded['rows']['AAA']['availableAt'])
            with patch.object(facts.subprocess,'check_output',side_effect=[log,b'old bytes']):
                changed=facts.source_snapshot(root,'technical',['AAA'],now)
            self.assertEqual('capture_only',changed['availabilityEvidence'])
            self.assertEqual(facts.iso(now),changed['rows']['AAA']['availableAt'])

    def test_future_timestamp_is_retained_as_ineligible_evidence(self):
        now=datetime(2026,10,5,20,10,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);self.write_source(root,updated='2026-10-06T00:00:00Z')
            with patch.object(facts.subprocess,'check_output',return_value=b''):
                item=facts.source_snapshot(root,'technical',['AAA'],now)
            self.assertTrue(item['rows']['AAA']['futureTimestamp'])
            self.assertGreater(facts.stamp(item['rows']['AAA']['availableAt']),now)

    def test_completed_market_record_and_sources_are_immutable(self):
        now=datetime(2026,10,5,16,10,tzinfo=sr.NY)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);self.write_source(root);history=root/'facts'
            with patch.object(facts.subprocess,'check_output',return_value=b''):
                facts.collect_facts(self.prices(),['AAA'],now,history,root)
                original=sr.read_lines(history/'sources.jsonl')
                oldsource=(history/'sources'/f"technical-{original[0]['artifactHash']}.json").read_bytes()
                oldcontext=(history/'market-context.jsonl').read_bytes()
                self.write_source(root,price=120)
                result=facts.collect_facts(self.prices(last=120),['AAA'],now,history,root)
            self.assertEqual(oldsource,(history/'sources'/f"technical-{original[0]['artifactHash']}.json").read_bytes())
            self.assertEqual(oldcontext,(history/'market-context.jsonl').read_bytes())
            self.assertEqual(3,result['sourceArtifacts'])
            self.assertEqual(0,result['newPaperArms'])
            self.assertEqual(8,result['marketRows'])

    def test_current_intraday_bar_never_becomes_a_completed_signal(self):
        now=datetime(2026,10,5,15,59,tzinfo=sr.NY)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);self.write_source(root)
            with patch.object(facts.subprocess,'check_output',return_value=b''):
                result=facts.collect_facts(self.prices(),['AAA'],now,root/'facts',root)
            self.assertEqual(0,result['marketRows'])


if __name__=='__main__':unittest.main()
