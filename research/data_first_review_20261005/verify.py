from pathlib import Path
import hashlib
import json
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from research.data_first_review_20261005.prepare import num
from research.data_first_review_20261005.analyze import definitions, apply
from research.data_first_review_20261005.shortlist import CANDIDATES
from scripts.record_swing_research import replay, market_rows

p=pd.read_csv(OUT/'panel.csv.gz')
b=pd.read_csv(OUT/'bars.csv.gz')
labels=pd.read_csv(OUT/'outcomes.csv.gz')
assert len(p)==2887 and not p.duplicated(['ticker','session']).any()
for c in ['available','source_updated','close_time','decision','fund_available']:
    p[c]=pd.to_datetime(p[c],utc=True)
assert (p.available<p.decision).all()
assert (p.source_updated>=p.close_time).all()
known=p.fund_salesYoyTtm.notna()
assert (p.loc[known,'fund_available']<p.loc[known,'close_time']).all()
assert p.loc[known,'fund_age_days'].between(0,7).all()
checked=0
for commit,g in p.sample(60,random_state=20261005).groupby('commit'):
    source=json.loads(subprocess.check_output(['git','show',f'{commit}:data/cache/technical.json'],cwd=ROOT))
    for r in g.itertuples():
        row=source['rows'][r.ticker]
        for field,key in [('rsi','RSI (D)'),('ma200','200일 이동평균선'),('squeeze',None),('close','C - Close')]:
            if key is None:
                continue
            value=num(row.get(key))
            assert np.isclose(value,getattr(r,field),equal_nan=True),(r.ticker,r.session,field)
        checked+=1
lookup=b.set_index(['ticker','session'])
entry_gate_checks=0
for k in [5,6]:
    for r in p[p[f'replay_s{k}'].eq(True)].itertuples():
        entry_open=lookup.loc[(r.ticker,r.entry),'open']*r.price_unit_factor
        assert entry_open<=r.signal_close*1.03
        if k==6:assert 0<(entry_open-r.support_stop)/entry_open<=.08
        entry_gate_checks+=1
for r in labels.itertuples():
    entry=p.loc[(p.ticker==r.ticker)&(p.session==r.session),'entry'].iloc[0]
    opening=lookup.loc[(r.ticker,entry),'open'];closing=lookup.loc[(r.ticker,r.exit),'close']
    assert np.isclose(r.net,closing/opening-1-.004)
bars={t:g.set_index('session').sort_index() for t,g in b.groupby('ticker')}
q=bars['QQQ'];states=market_rows(q.rename(columns=str.title))
days=[d for d in q.index if '2026-05-01'<=d<='2026-10-02']
sessions={d:{'market':states[d],'bars':{t:{'open':float(row.open),'high':float(row.high),'low':float(row.low),'close':float(row.close),'split':1.}
                                    for t,g in bars.items() if d in g.index for row in [g.loc[d]]}}
          for d in days}
p['allowed']=p.session.map(lambda d:states[d]['buyAllowed']) & p.event.eq('당분간 없음')
for k in range(1,8):p[f'S{k}']=p[f'replay_s{k}'].eq(True)&p.allowed
rules={r['id']:r for r in definitions()}
expected=pd.read_csv(OUT/'shortlist_common_trades.csv.gz')
checks=[]
for arm,(base,ids) in CANDIDATES.items():
    g=p[p[base]]
    mask=np.logical_and.reduce([apply(g,rules[i])[0] for i in ids])
    selected=g[mask]
    observations=[{'ticker':r.ticker,'session':r.session,'forwardEligible':True,'market':{'recovery':states[r.session]['recovery']},
                   'features':{'close':r.close,'low':r.low,'rs20':0.,'supportStop':r.support_stop},'signals':{arm:True}} for r in selected.itertuples()]
    actual,_=replay(observations,sessions,{arm:{'stop':.08,'target':.12,'days':20,'mode':'common','entryStrategy':None}})
    target=expected[expected.candidate.eq(arm)]
    assert len(actual)==len(target),(arm,len(actual),len(target))
    if actual:
        a=pd.DataFrame(actual)
        if 'net' not in a:a['net']=np.nan
        if 'exit' not in a:a['exit']=None
        m=target.merge(a,left_on=['ticker','session'],right_on=['ticker','signal'],suffixes=('_analysis','_recorder'),validate='one_to_one')
        assert (m.status_analysis==m.status_recorder).all()
        closed=m[m.status_analysis.eq('closed')]
        assert np.allclose(closed.net_analysis,closed.net_recorder)
        assert (closed.exit_analysis==closed.exit_recorder).all()
    checks.append({'candidate':arm,'trades':len(actual),'matches_existing_recorder':True})
result={'panel_rows':len(p),'point_in_time_checks':True,'git_source_sample_matches':checked,'s5_s6_entry_gates_checked':entry_gate_checks,'outcomes_recomputed':len(labels),'candidate_exits':checks,
        'inputs':{x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in [OUT/'panel.csv.gz',OUT/'bars.csv.gz',OUT/'outcomes.csv.gz',OUT/'protocol.json']}}
(OUT/'verification.json').write_text(json.dumps(result,indent=2))
print('verified',checked,'source rows;',len(labels),'outcomes;',len(checks),'candidate simulations')
