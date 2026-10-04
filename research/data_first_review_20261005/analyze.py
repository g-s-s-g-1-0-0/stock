"""Bounded one/two-condition audit on recorded observations, not today's universe."""
from pathlib import Path
import itertools
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from scripts.record_swing_research import market_rows


def definitions():
    rules = []
    def add(family, col, op, a, b=None):
        rules.append({'id': f'{col}_{op}_{a}' + (f'_{b}' if b is not None else ''),
                      'family': family, 'col': col, 'op': op, 'a': a, 'b': b})
    for col, family, cuts in [
        ('rsi', 'rsi', [35, 50, 65]), ('pctB', 'bb_position', [10, 35, 70]),
        ('squeeze', 'bb_width', [.75, 1.25]), ('vol20', 'volume', [.8, 1.5, 2]),
        ('premium', 'ma200', [0, 25, 75]), ('adx', 'adx', [25]),
        ('atr', 'atr', [5]), ('ma20dist', 'ma20', [0, 5]),
        ('high52_distance', 'high52', [-30, -10]), ('high52_age', 'high52_age', [20]),
        ('close_location', 'candle', [.5, .7]), ('lower_wick', 'wick', [.3]),
        ('fund_salesYoyTtm', 'growth', [0, 20]), ('fund_salesQoq', 'recent_growth', [0, 20]),
        ('fund_operatingMargin', 'margin', [0, 20]), ('fund_grossMargin', 'gross_margin', [30]),
        ('fund_roe', 'roe', [0, 10]), ('fund_debtToEquity', 'debt', [1]),
        ('fund_currentRatio', 'liquidity', [1]), ('fund_priceToSales', 'sales_value', [10]),
        ('fund_market_cap', 'size', [10e9, 100e9]), ('fund_epsQoq', 'eps_growth', [0]),
        ('fund_pbr', 'book_value', [5]), ('fund_epsTtm', 'earnings_profit', [0]),
        ('fund_ruleOf40', 'growth_margin', [40]), ('fund_sales', 'sales_size', [1e9]),
        ('earnings_days', 'earnings', [0, 10]), ('peer_breadth20', 'breadth', [.5]),
        ('price_dollar_volume20', 'turnover', [100e6]), ('ctx_vix_close', 'vix', [22]),
    ]:
        for cut in cuts:
            add(family, col, 'gt', cut)
            add(family, col, 'le', cut)
    for col, family in [
        ('slope', 'slope'), ('hist', 'macd'), ('hist_change', 'macd_change'),
        ('width_change', 'bb_change'), ('di_spread', 'di'), ('rs20', 'rs'), ('obv20', 'obv'),
        ('rsi_change', 'rsi_change'), ('cci_change', 'cci_change'),
        ('observed_rsi_change5', 'rsi_persistence'), ('observed_slope_change5', 'slope_persistence'),
        ('observed_vol20_change5', 'volume_persistence'), ('observed_squeeze_change5', 'width_persistence'),
        ('intraday_recovery', 'intraday'), ('peer_rs20', 'peer_rs'),
        ('price_rs_smh20', 'semiconductor_rs'), ('price_return3', 'short_return'),
        ('price_return20', 'medium_return'), ('ctx_smh_qqq_rs20', 'semiconductor_market'),
        ('ctx_iwm_qqq_rs20', 'small_market'), ('ctx_rsp_spy_rs20', 'equalweight_market'),
        ('ctx_hyg_ief_rs20', 'credit_proxy'), ('ctx_tlt_return20', 'bond_market'),
        ('ctx_qqq_return5', 'market_short'), ('ctx_qqq_return20', 'market_medium'),
    ]:
        add(family, col, 'gt', 0)
        add(family, col, 'le', 0)
    for col, family, a, b in [('fund_per', 'per', 0, 30), ('fund_priceToFreeCashFlow', 'fcf_value', 0, 40),
                               ('earnings_days', 'earnings_window', 0, 10), ('earnings_days', 'post_earnings', -10, -1),
                               ('rsi', 'rsi', 35, 55), ('ma20dist', 'ma20', -5, 3)]:
        add(family, col, 'between', a, b)
    return rules


def apply(frame, rule):
    x = pd.to_numeric(frame[rule['col']], errors='coerce')
    known = x.notna()
    if rule['col']=='fund_pbr':
        known &= x>0
    elif rule['col']=='fund_debtToEquity':
        known &= x>=0
    op, a, b = rule['op'], rule['a'], rule['b']
    selected = x.gt(a) if op == 'gt' else x.le(a) if op == 'le' else x.between(a, b)
    return selected.to_numpy() & known.to_numpy(), known.to_numpy()


def independent(g):
    chosen, last = [], {}
    for i, r in g.sort_values(['entry', 'ticker']).iterrows():
        if r.session > last.get(r.ticker, ''):
            chosen.append(i)
            last[r.ticker] = r.exit
    return g.loc[chosen]


def metrics(g):
    if g.empty:
        return {'n': 0, 'dates': 0, 'tickers': 0}
    daily = g.groupby('entry').net.mean()
    bymonth = g.groupby(g.entry.str[:7]).net.mean()
    return {'n': len(g), 'dates': g.entry.nunique(), 'tickers': g.ticker.nunique(),
            'mean': g.net.mean(), 'median': g.net.median(), 'win': g.net.gt(0).mean(),
            'date_mean': daily.mean(), 'excess': g.excess.mean(), 'worst': g.net.min(),
            'mae_mean': g.mae.mean(), 'loss10': g.net.le(-.10).mean(),
            'months': len(bymonth), 'positive_months': int(bymonth.gt(0).sum()),
            'worst_month': bymonth.min(), 'cost1_mean': g.net.mean()-.006,
            'no_best_name_mean': min(g.loc[g.ticker.ne(t), 'net'].mean() for t in g.ticker.unique()) if g.ticker.nunique()>1 else np.nan}


def compare(g, selected, known):
    base = g[known]
    picked = g[selected]
    excluded = g[known & ~selected]
    b, f = independent(base), independent(picked)
    cohort = b[b.index.isin(picked.index)]
    rejected_cohort = b[~b.index.isin(picked.index)]
    result = {**{f'base_{k}': v for k,v in metrics(b).items()}, **{f'filter_{k}':v for k,v in metrics(f).items()},
              **{f'paired_{k}': v for k,v in metrics(cohort).items()},
              'paired_delta':cohort.net.mean()-b.net.mean(), 'paired_rejected_mean':rejected_cohort.net.mean(),
              'raw_base': len(base), 'raw_selected':len(picked), 'raw_excluded':len(excluded)}
    if f.empty or b.empty:
        return result
    result['mean_delta'] = f.net.mean()-b.net.mean()
    same_date = picked.groupby('entry').net.mean()-base.groupby('entry').net.mean()
    result['matched_date_delta'] = same_date.mean()
    result['reject_mean'] = excluded.net.mean()
    result['passed_mean_raw'] = picked.net.mean()
    month_delta = picked.groupby(picked.entry.str[:7]).net.mean()-base.groupby(base.entry.str[:7]).net.mean()
    month_delta = month_delta.dropna()
    result['delta_months'] = len(month_delta)
    result['positive_delta_months'] = int(month_delta.gt(0).sum())
    result['monthly_delta'] = json.dumps(month_delta.to_dict())
    result['early_mean'] = independent(picked[picked.entry<'2026-08-01']).net.mean()
    result['late_mean'] = independent(picked[picked.entry>='2026-08-01']).net.mean()
    return result


def scan(g, rules, min_n=30, min_dates=12):
    g = g.reset_index(drop=True)
    passes, knows = zip(*(apply(g, r) for r in rules))
    y = g.net.to_numpy()
    _, dc = np.unique(g.entry, return_inverse=True)
    _, tc = np.unique(g.ticker, return_inverse=True)
    rows, seen = [], set()
    for size in [1, 2]:
        for ids in itertools.combinations(range(len(rules)), size):
            if len({rules[i]['family'] for i in ids}) < size:
                continue
            selected = np.logical_and.reduce([passes[i] for i in ids])
            known = np.logical_and.reduce([knows[i] for i in ids])
            n = int(selected.sum())
            if n < min_n or np.unique(dc[selected]).size < min_dates or np.unique(tc[selected]).size < 6:
                continue
            key = (np.packbits(selected).tobytes(), np.packbits(known).tobytes())
            if key in seen:
                continue
            seen.add(key)
            cc = np.bincount(dc[selected], minlength=dc.max()+1)
            bc = np.bincount(dc[known], minlength=dc.max()+1)
            selected_daily = np.divide(np.bincount(dc[selected], weights=y[selected], minlength=len(cc)), cc, out=np.full(len(cc), np.nan), where=cc>0)
            base_daily = np.divide(np.bincount(dc[known], weights=y[known], minlength=len(cc)), bc, out=np.full(len(cc), np.nan), where=bc>0)
            diff = selected_daily-base_daily
            improvement = np.nanmean(diff)
            score = improvement-.25*np.nanstd(diff)-.0005*size
            rows.append({'ids': ids, 'conditions': ' & '.join(rules[i]['id'] for i in ids),
                         'raw_n': n, 'dates': int((cc>0).sum()), 'tickers': np.unique(tc[selected]).size,
                         'date_net': np.nanmean(selected_daily), 'matched_delta': improvement,
                         'mean': y[selected].mean(), 'score':score})
    return sorted(rows, key=lambda x:x['score'], reverse=True)


def choose(scan_rows, g, rules, limit=3):
    result, masks = [], []
    for r in scan_rows:
        if r['matched_delta']<=0 or r['date_net']<=0:
            continue
        mask = np.logical_and.reduce([apply(g, rules[i])[0] for i in r['ids']])
        if any((mask & other).sum()/max((mask | other).sum(), 1)>.65 for other in masks):
            continue
        masks.append(mask)
        result.append(r)
        if len(result)==limit:
            break
    return result


def main():
    p = pd.read_csv(OUT/'panel.csv.gz')
    labels = pd.read_csv(OUT/'outcomes.csv.gz')
    bars = pd.read_csv(OUT/'bars.csv.gz')
    q = bars[bars.ticker.eq('QQQ')].set_index('session').rename(columns=str.title)
    states = market_rows(q)
    p['buy_allowed'] = p.session.map(lambda d:states[d]['buyAllowed']) & p.event.eq('당분간 없음')
    for k in range(1,8):
        p[f'base_s{k}'] = p[f'replay_s{k}'].eq(True) & p.buy_allowed
    p['any_base'] = p[[f'base_s{k}' for k in range(1,8)]].any(axis=1)
    previous = pd.read_csv(OUT/'prior_pattern_flags.csv.gz')
    p = p.merge(previous[['ticker','session','any_prior_pattern']],on=['ticker','session'],validate='one_to_one')
    e = p.merge(labels, on=['ticker', 'session'], validate='one_to_many')
    rules = definitions()
    protocol = {'version':'data-first-audit-v1', 'primary':'10-session next-open to close price return minus 0.4% costs',
                'sensitivity_horizons':[5,20], 'coverage':'actual observed 48 stocks; not historical current-survivor backtest',
                'features':'saved technical values, archived financial values available before D close, recorded intraday snapshots available by D close; dated supplemental prices',
                'market_gate':'QQQ14/18 recovery and9 nonrecovery research settings, archived no-event label',
                'strategy_flags':'prior replay of present 1..7 logic, not actual historical orders; S2 unknown excluded',
                'search':'all one/two-atom combinations across different families; full-period descriptive and purged monthly chronological fits',
                'minimum_search_rows':30,'minimum_search_dates':12,'minimum_search_tickers':6,
                'selection':'matched-date net improvement minus .25 daily dispersion minus .0005 per condition; top3 with Jaccard<=.65',
                'leakage_note':'all these months were viewed in earlier analyses: chronological results are diagnostics, NOT untouched out-of-sample evidence',
                'rules':rules}
    (OUT/'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2))
    columns = sorted({r['col'] for r in rules})
    coverage, updown = [], []
    h10 = e[e.h.eq(10)].copy()
    for col in columns:
        g = p[p[col].notna()]
        coverage.append({'feature':col,'rows':len(g),'dates':g.session.nunique(),'tickers':g.ticker.nunique(),
                         'first':g.session.min() if len(g) else '', 'last':g.session.max() if len(g) else ''})
        for period, sub in [('all',h10),('May_July',h10[h10.entry<'2026-08-01']),('Aug_Oct',h10[h10.entry>='2026-08-01'])]:
            for label, mask in [('up5',sub.gross.ge(.05)),('down5',sub.gross.le(-.05))]:
                x = sub[mask & sub[col].notna()]
                updown.append({'feature':col,'period':period,'outcome':label,'rows':len(x), 'dates':x.entry.nunique(),'median':x[col].median()})
    pd.DataFrame(coverage).to_csv(OUT/'coverage.csv',index=False)
    pd.DataFrame(updown).to_csv(OUT/'up_down_commonalities.csv',index=False)
    summaries, filters, monthly = [], [], []
    for h in [5,10,20]:
        z = e[e.h.eq(h)].copy()
        for name, mask in [('universe',np.ones(len(z),dtype=bool)),('allowed',z.buy_allowed), *[(f'S{k}',z[f'base_s{k}']) for k in range(1,8)]]:
            g = z[mask]
            summaries.append({'h':h,'base':name,**metrics(independent(g))})
            for rule in rules:
                passed, known = apply(g, rule)
                filters.append({'h':h,'base':name,'condition':rule['id'],'family':rule['family'],**compare(g,passed,known)})
        if h==10:
            for name, mask in [('allowed',z.buy_allowed), *[(f'S{k}',z[f'base_s{k}']) for k in range(1,8)]]:
                for month,g in z[mask].groupby(z.loc[mask,'entry'].str[:7]):
                    monthly.append({'base':name,'month':month,**metrics(independent(g))})
    pd.DataFrame(summaries).to_csv(OUT/'bases.csv',index=False)
    pd.DataFrame(filters).to_csv(OUT/'all_single_filters.csv',index=False)
    pd.DataFrame(monthly).to_csv(OUT/'base_months.csv',index=False)

    pool = h10[h10.buy_allowed].copy()
    full = scan(pool,rules)
    pd.DataFrame(full).to_csv(OUT/'all_combinations.csv',index=False)
    universe_scan = scan(h10,rules)
    pd.DataFrame(universe_scan).to_csv(OUT/'universe_all_combinations.csv',index=False)
    selected = choose(full,pool,rules,10)
    report, details = [], []
    for rank,r in enumerate(selected,1):
        for h in [5,10,20]:
            g = e[e.h.eq(h)&e.buy_allowed]
            chosen = np.logical_and.reduce([apply(g,rules[i])[0] for i in r['ids']])
            known = np.logical_and.reduce([apply(g,rules[i])[1] for i in r['ids']])
            selected_g = g[chosen]
            unique = independent(selected_g[~selected_g.any_base])
            unique_all = independent(selected_g[~selected_g.any_base & ~selected_g.any_prior_pattern])
            record = {'rank':rank,'h':h,**r,**compare(g,chosen,known),**{f'new_only_{k}':v for k,v in metrics(unique).items()}}
            record.update({f'new_vs36_{k}':v for k,v in metrics(unique_all).items()})
            report.append(record)
            if h==10:
                t=independent(selected_g)
                details.append(t.assign(candidate=r['conditions'],rank=rank))
    pd.DataFrame(report).to_csv(OUT/'descriptive_shortlist.csv',index=False)
    if details:
        pd.concat(details).to_csv(OUT/'descriptive_trades.csv.gz',index=False)
    locks, forwards = [], []
    for month,end in [('2026-07','2026-07-31'),('2026-08','2026-08-31'),('2026-09','2026-10-02')]:
        start=month+'-01'
        train=pool[pool.exit<start].copy()
        test=pool[pool.entry.between(start,end)].copy()
        search=scan(train,rules)
        locked=choose(search,train,rules,3)
        locks.append({'test_start':start,'test_end':end,'train_rows':len(train),'train_last_exit':train.exit.max(), 'tested_unique_eligible':len(search),'chosen':locked})
        for rank,r in enumerate(locked,1):
            passed=np.logical_and.reduce([apply(test,rules[i])[0] for i in r['ids']])
            t=independent(test[passed]).assign(fold=month,rank=rank,candidate=r['conditions'])
            forwards.append(t)
    (OUT/'chronological_locks.json').write_text(json.dumps(locks,indent=2,default=lambda x:float(x)))
    if forwards:
        f=pd.concat(forwards,ignore_index=True)
        f.to_csv(OUT/'chronological_trades.csv.gz',index=False)
        pd.DataFrame([{'fold':fold,'rank':rank,**metrics(g)} for (fold,rank),g in f.groupby(['fold','rank'])]).to_csv(OUT/'chronological_results.csv',index=False)
    universe_locks, universe_forward = [], []
    for month,end in [('2026-07','2026-07-31'),('2026-08','2026-08-31'),('2026-09','2026-10-02')]:
        train=h10[h10.exit<month+'-01']
        test=h10[h10.entry.between(month+'-01',end)]
        fitted=scan(train,rules)
        chosen=choose(fitted,train,rules,3)
        universe_locks.append({'test_start':month+'-01','train_last_exit':train.exit.max(),'tested_unique_eligible':len(fitted),'chosen':chosen})
        for rank,r in enumerate(chosen,1):
            mask=np.logical_and.reduce([apply(test,rules[i])[0] for i in r['ids']])
            universe_forward.append(independent(test[mask]).assign(fold=month,rank=rank,candidate=r['conditions']))
    (OUT/'universe_chronological_locks.json').write_text(json.dumps(universe_locks,indent=2,default=lambda x:float(x)))
    if universe_forward:
        f=pd.concat(universe_forward,ignore_index=True)
        f.to_csv(OUT/'universe_chronological_trades.csv.gz',index=False)
        pd.DataFrame([{'fold':fold,'rank':rank,**metrics(g)} for (fold,rank),g in f.groupby(['fold','rank'])]).to_csv(OUT/'universe_chronological_results.csv',index=False)
    print(json.dumps({'rules':len(rules),'features':len(columns),'eligible_combinations':len(full),'rows':len(p),'h10':len(h10),'allowed_h10':len(pool)},indent=2))
    print(pd.DataFrame(summaries).query('h==10').to_string(index=False))
    print(pd.DataFrame(report).query('h==10')[['rank','conditions','filter_n','filter_dates','filter_mean','mean_delta','matched_date_delta','positive_delta_months','delta_months','late_mean','new_only_n']].to_string(index=False))


if __name__=='__main__':
    main()
