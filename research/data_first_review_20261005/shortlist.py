"""Follow-up diagnostics of disclosed exploratory selections; no new fitted thresholds."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from research.data_first_review_20261005.analyze import apply, definitions, compare, independent, metrics
from research.final_review_20261004.run import simulate, metrics as trade_metrics
from scripts.record_swing_research import market_rows

CANDIDATES = {
    'S3_ma200_distance25': ('S3', ['premium_le_25']),
    'S3_rsi35': ('S3', ['rsi_le_35']),
    'S3_size100b': ('S3', ['fund_market_cap_le_100000000000.0']),
    'S3_intraday_positive': ('S3', ['intraday_recovery_gt_0']),
    'S4_debt1': ('S4', ['fund_debtToEquity_le_1']),
    'S4_eps_growth': ('S4', ['fund_epsQoq_gt_0']),
    'S7_obv_positive': ('S7', ['obv20_gt_0']),
    'S7_high52_drawdown30': ('S7', ['high52_distance_le_-30']),
    'S7_volume_ratio_falling5': ('S7', ['observed_vol20_change5_le_0']),
    'S7_quality': ('S7', ['fund_debtToEquity_le_1', 'fund_operatingMargin_gt_0']),
    'N_expanded_below200': ('allowed', ['squeeze_gt_1.25', 'premium_le_0']),
    'N_rsi_ahead_macd': ('allowed', ['rsi_gt_50', 'hist_le_0']),
    'N_expanded_profitable_roe': ('allowed', ['squeeze_gt_1.25', 'fund_roe_gt_0']),
    'N_value_laggard': ('allowed', ['fund_pbr_le_5', 'peer_rs20_le_0']),
}


def main():
    p=pd.read_csv(OUT/'panel.csv.gz')
    b=pd.read_csv(OUT/'bars.csv.gz')
    bars={t:g.set_index('session').sort_index() for t,g in b.groupby('ticker')}
    q=bars['QQQ']
    states=market_rows(q.rename(columns=str.title))
    days=[d for d in q.index if '2026-05-01'<=d<='2026-10-02']
    arrays={t:g.reindex(days)[['open','high','low','close']].to_numpy() for t,g in bars.items()}
    st=[states[d] for d in days]
    p['allowed']=p.session.map(lambda d:states[d]['buyAllowed']) & p.event.eq('당분간 없음')
    for k in range(1,8):p[f'S{k}']=p[f'replay_s{k}'].eq(True) & p.allowed
    p['any_base']=p[[f'S{k}' for k in range(1,8)]].any(axis=1)
    p['recovery']=p.session.map(lambda d:states[d]['recovery'])
    labels=pd.read_csv(OUT/'outcomes.csv.gz')
    e=p.merge(labels,on=['ticker','session'])
    rules={r['id']:r for r in definitions()}
    holdings=[]; fixed=[]; months=[]; alltrades=[]; checks=[]
    for name,(base,ids) in CANDIDATES.items():
        g=p[p[base]].copy()
        mask=np.logical_and.reduce([apply(g,rules[i])[0] for i in ids])
        known=np.logical_and.reduce([apply(g,rules[i])[1] for i in ids])
        base_t=simulate(g[known],days,st,arrays)
        selected_t=simulate(g[mask],days,st,arrays)
        closed=base_t[base_t.status.eq('closed')]
        selected_keys=set(zip(g.loc[mask,'ticker'],g.loc[mask,'session']))
        paired=closed[[tuple(r) in selected_keys for r in closed[['ticker','session']].to_numpy()]]
        holdings.append({'candidate':name,'base':base,'conditions':' & '.join(ids),
                         **{f'base_{k}':v for k,v in trade_metrics(base_t).items()},
                         **{f'filter_{k}':v for k,v in trade_metrics(selected_t).items()},
                         **{f'paired_{k}':v for k,v in trade_metrics(paired).items()}})
        alltrades.append(selected_t.assign(candidate=name))
        for h in [5,10,20]:
            z=e[e.h.eq(h)&e[base]]
            m=np.logical_and.reduce([apply(z,rules[i])[0] for i in ids])
            k=np.logical_and.reduce([apply(z,rules[i])[1] for i in ids])
            fixed.append({'candidate':name,'h':h,**compare(z,m,k)})
            if h==10:
                trades=independent(z[m])
                for month,t in trades.groupby(trades.entry.str[:7]):months.append({'candidate':name,'month':month,**metrics(t)})
                explicit=z[~z.date_inferred]
                em=np.logical_and.reduce([apply(explicit,rules[i])[0] for i in ids])
                checks.append({'candidate':name,'sensitivity':'explicit_candle_date_only',**metrics(independent(explicit[em]))})
                diff=z[m].groupby('entry').net.mean()-z[k].groupby('entry').net.mean()
                diff=diff.dropna().to_numpy()
                checks.append({'candidate':name,'sensitivity':'matched_date_difference_descriptive_NOT_selection_adjusted','n':len(diff),'mean':diff.mean() if len(diff) else np.nan})
    pd.DataFrame(holdings).to_csv(OUT/'shortlist_common_exits.csv',index=False)
    pd.DataFrame(fixed).to_csv(OUT/'shortlist_horizons.csv',index=False)
    pd.DataFrame(months).to_csv(OUT/'shortlist_months.csv',index=False)
    pd.DataFrame(checks).to_csv(OUT/'shortlist_sensitivity.csv',index=False)
    pd.concat(alltrades).to_csv(OUT/'shortlist_common_trades.csv.gz',index=False)
    (OUT/'shortlist_definitions.json').write_text(json.dumps(CANDIDATES,ensure_ascii=False,indent=2))
    print(pd.DataFrame(holdings)[['candidate','base_n','base_mean','filter_n','filter_dates','filter_mean','filter_worst','paired_n','paired_mean']].round(4).to_string(index=False))


if __name__=='__main__':main()
