"""Restore recorded features with availability timestamps; add dated market prices."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
import urllib.request

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = ROOT / 'research/observed_signals_20261003'
sys.path.insert(0, str(ROOT))
from scripts.record_swing_research import ETF

FUND = ['salesQoq', 'salesYoyTtm', 'currentRatio', 'debtToEquity',
        'priceToFreeCashFlow', 'priceToSales', 'per', 'pbr', 'roe',
        'grossMargin', 'operatingMargin', 'epsTtm', 'epsQoq', 'ruleOf40']
EXTRA = {'high52_distance': '52주 신고가 대비', 'high52_age': '52주 신고가 후 경과일',
         'williams': 'Williams %R (14)', 'rsi_prior': 'RSI (D-1)', 'cci_prior': 'CCI (D-1)'}


def num(x):
    if x is None:
        return np.nan
    try:
        return float(re.sub(r'[^0-9.+-]', '', str(x)))
    except ValueError:
        return np.nan


def money(x):
    text = str(x).strip().upper().replace(',', '')
    match = re.search(r'([0-9.]+)\s*([BMT]?)$', text)
    if not match or ('₩' in text):
        return np.nan
    return float(match[1]) * {'': 1, 'M': 1e6, 'B': 1e9, 'T': 1e12}[match[2]]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recover_values():
    path = OUT / 'valuation_history.csv.gz'
    if path.exists():
        saved = pd.read_csv(path, parse_dates=['fund_available', 'fund_updated'])
        if 'market_cap_raw' in saved:
            return saved
    versions = pd.read_csv(OLD / 'results/valuation_versions.csv')
    rows = []
    for r in versions.itertuples():
        payload = json.loads(subprocess.check_output(['git', 'show', f'{r.commit}:data/cache/valuation.json'], cwd=ROOT))
        meta = pd.to_datetime(payload.get('meta', {}).get('updatedAt'), utc=True, errors='coerce')
        ct = pd.Timestamp(r.committed)
        for ticker, x in payload.get('rows', {}).items():
            if ticker.isdigit():
                continue
            rt = pd.to_datetime(x.get('updatedAt'), utc=True, errors='coerce')
            updated = rt if pd.notna(rt) else meta
            available = max(t for t in [updated, meta, ct] if pd.notna(t))
            rows.append({'ticker': ticker, 'fund_available': available, 'fund_updated': updated,
                         'fund_commit': r.commit, 'fund_hash': hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest(),
                         **{f'fund_{k}': num(x.get(k)) for k in FUND},
                         'fund_market_cap': money(x.get('marketCap')), 'fund_sales': money(x.get('sales')),
                         'market_cap_raw': x.get('marketCap'), 'sales_raw': x.get('sales'),
                         'earnings_calendar': x.get('earningsDate'), 'industry_recorded': x.get('industry')})
    v = pd.DataFrame(rows).sort_values('fund_available').drop_duplicates(['ticker', 'fund_available'], keep='last')
    v.to_csv(path, index=False)
    return v


def fetch(ticker):
    raw = OUT / 'sources'
    raw.mkdir(exist_ok=True)
    path = raw / f'{ticker}.json'
    start = int(pd.Timestamp('2025-01-01', tz='UTC').timestamp())
    end = int(pd.Timestamp('2026-10-03', tz='UTC').timestamp())
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={start}&period2={end}&interval=1d&events=div%2Csplit'
    if not path.exists():
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        path.write_bytes(urllib.request.urlopen(req, timeout=40).read())
    obj = json.loads(path.read_bytes())['chart']['result'][0]
    quote = obj['indicators']['quote'][0]
    rows = []
    for i, t in enumerate(obj['timestamp']):
        day = pd.Timestamp(t, unit='s', tz='UTC').tz_convert('America/New_York').strftime('%Y-%m-%d')
        if day <= '2026-10-02' and all(quote[c][i] is not None for c in ['open', 'high', 'low', 'close']):
            rows.append({'ticker': ticker, 'session': day, **{c: quote[c][i] for c in ['open', 'high', 'low', 'close', 'volume']}})
    return pd.DataFrame(rows), {'ticker': ticker, 'url': url, 'sha256': digest(path), 'rows': len(rows)}


def main():
    p = pd.read_pickle(OLD / 'phase2/results/panel.pkl')
    p = p[p.market.eq('US') & ~p.ticker.isin(ETF)].copy()
    audit = {'initial_stock_rows': len(p), 'excluded_symbols': sorted(ETF), 'exclusion_note': 'five ETFs and HOOG (existing duplicate share-class convention)'}
    incomplete = (p.source_updated < p.close_time) | (p.available < p.close_time)
    p[incomplete].to_csv(OUT / 'excluded_incomplete_candles.csv', index=False)
    p = p[~incomplete].copy()
    audit['excluded_incomplete'] = int(incomplete.sum())
    extra = pd.read_pickle(OLD / 'phase2/results/extra_inputs.pkl')
    extra = extra[['ticker', 'entry', 'raw_technical']]
    p = p.merge(extra, on=['ticker', 'entry'], validate='one_to_one')
    for col, key in EXTRA.items():
        p[col] = p.raw_technical.map(lambda x: num(x.get(key)))
    p = p.drop(columns=['raw_technical', 'source_summary'])
    v = recover_values()
    for col in ['close_time', 'available', 'source_updated', 'decision']:
        p[col] = pd.to_datetime(p[col], utc=True).astype('datetime64[ns, UTC]')
    for col in ['fund_available', 'fund_updated']:
        v[col] = pd.to_datetime(v[col], utc=True).astype('datetime64[ns, UTC]')
    merged = []
    for ticker, g in p.groupby('ticker'):
        sub = v[v.ticker.eq(ticker)].drop(columns='ticker').sort_values('fund_available')
        j = pd.merge_asof(g.sort_values('close_time'), sub, left_on='close_time', right_on='fund_available', direction='backward', allow_exact_matches=False)
        merged.append(j)
    p = pd.concat(merged, ignore_index=True)
    p['fund_age_days'] = (p.close_time - p.fund_updated).dt.total_seconds() / 86400
    stale = ~p.fund_age_days.between(0, 7)
    for col in [c for c in p if c.startswith('fund_') and c not in ['fund_available', 'fund_updated', 'fund_commit', 'fund_hash', 'fund_age_days']]:
        p.loc[stale, col] = np.nan
    p.loc[stale, ['earnings_calendar', 'industry_recorded']] = None
    dates = pd.to_datetime(p.earnings_calendar.str.extract(r'(20\d\d-\d\d-\d\d)', expand=False), errors='coerce')
    p['earnings_days'] = (dates - pd.to_datetime(p.session)).dt.days
    # Calendar snapshots are not proof of the actual announcement date/time.
    p['earnings_upcoming10'] = p.earnings_days.where(p.earnings_days.between(-90, 120)).between(0, 10).astype(float)
    p.loc[dates.isna() | ~p.earnings_days.between(-90, 120), 'earnings_upcoming10'] = np.nan
    p['fund_semiconductor'] = p.industry_recorded.str.contains('반도체|semiconductor', case=False, na=False).astype(float)
    p.loc[p.industry_recorded.isna(), 'fund_semiconductor'] = np.nan

    warm = pd.read_pickle(OLD / 'phase2/results/warmup_bars.pkl')
    warm = warm[warm.market.eq('US')].drop(columns='market')
    context, manifest = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for b, meta in ex.map(fetch, ['SPY', 'IWM', 'SMH', 'RSP', 'HYG', 'IEF', 'TLT']):
            context.append(b)
            manifest.append(meta)
    bars = pd.concat([warm, *context], ignore_index=True).drop_duplicates(['ticker', 'session']).sort_values(['ticker', 'session'])
    bars.to_csv(OUT / 'bars.csv.gz', index=False)
    series = {t: g.set_index('session').sort_index() for t, g in bars.groupby('ticker')}
    q = series['QQQ']
    features = pd.DataFrame(index=q.index)
    for ticker in ['QQQ', 'SPY', 'IWM', 'SMH', 'RSP', 'HYG', 'IEF', 'TLT', '^VIX']:
        c = series[ticker].close.reindex(q.index)
        prefix = ticker.replace('^', '').lower()
        for lag in [5, 20]:
            features[f'ctx_{prefix}_return{lag}'] = 100 * c.pct_change(lag, fill_method=None)
        features[f'ctx_{prefix}_above20'] = (c > c.rolling(20).mean()).where(c.rolling(20).mean().notna()).astype(float)
        features[f'ctx_{prefix}_close'] = c
    for a, b in [('SMH', 'QQQ'), ('IWM', 'QQQ'), ('RSP', 'SPY'), ('HYG', 'IEF')]:
        ratio = series[a].close / series[b].close
        features[f'ctx_{a.lower()}_{b.lower()}_rs20'] = 100 * ratio.pct_change(20, fill_method=None)
    # VIX close timing is not aligned with 16:00 equity signals: use prior session.
    vixcols = [c for c in features if c.startswith('ctx_vix')]
    features[vixcols] = features[vixcols].shift(1)
    p = p.merge(features, left_on='session', right_index=True, validate='many_to_one')
    prices = []
    for ticker, g in p.groupby('ticker'):
        b = series[ticker].copy()
        z = pd.DataFrame(index=b.index)
        for lag in [1, 3, 5, 20, 60]:
            z[f'price_return{lag}'] = 100 * b.close.pct_change(lag, fill_method=None)
        z['price_rs_smh20'] = 100 * (b.close / series['SMH'].close).pct_change(20, fill_method=None)
        z['price_dollar_volume20'] = (b.close * b.volume).rolling(20).mean()
        z['price_realized_vol20'] = b.close.pct_change(fill_method=None).rolling(20).std() * 100
        z['price_gap'] = 100 * (b.open / b.close.shift() - 1)
        prices.append(g.merge(z, left_on='session', right_index=True, validate='one_to_one'))
    p = pd.concat(prices, ignore_index=True)
    p['premium'] = 100 * (p.close / p.ma200 - 1)
    p['close_location'] = ((p.close - p.low) / (p.high - p.low)).where(p.high > p.low)
    p['lower_wick'] = ((p[['open', 'close']].min(axis=1) - p.low) / (p.high - p.low)).where(p.high > p.low)
    p['rsi_change'] = p.rsi - p.rsi_prior
    p['cci_change'] = p.cci - p.cci_prior
    p['recorded_above20'] = (p.close > p.ma20).astype(float)
    p['recorded_above200'] = (p.close > p.ma200).astype(float)
    # Cross-sections use actual observed members on the given date, excluding self.
    for col, out in [('recorded_above20', 'peer_breadth20'), ('recorded_above200', 'peer_breadth200')]:
        grouped = p.groupby('session')[col]
        p[out] = ((grouped.transform('sum') - p[col]) / (grouped.transform('count') - 1)).where(grouped.transform('count') >= 10)
    p['peer_rs20'] = (p.price_return20 - p.groupby('session').price_return20.transform('median')).where(p.groupby('session').price_return20.transform('count') >= 10)
    calidx = {d: i for i, d in enumerate(q.index)}
    p['session_index'] = p.session.map(calidx)
    p = p.sort_values(['ticker', 'session'])
    for lag in [1, 5]:
        g = p.groupby('ticker')
        contiguous = p.session_index - g.session_index.shift(lag) == lag
        for col in ['rsi', 'slope', 'vol20', 'squeeze', 'peer_breadth20']:
            p[f'observed_{col}_change{lag}'] = (p[col] - g[col].shift(lag)).where(contiguous)

    raw = pd.read_pickle(OLD / 'results/technical_observations.pkl')
    raw = raw[raw.market.eq('US') & raw.ticker.isin(p.ticker.unique())].copy()
    local = raw.source_updated.dt.tz_convert('America/New_York')
    raw['session'] = local.dt.strftime('%Y-%m-%d')
    raw['hour'] = local.dt.hour + local.dt.minute / 60
    close = pd.to_datetime(raw.session + ' 16:00').dt.tz_localize('America/New_York').dt.tz_convert('UTC')
    raw = raw[raw.hour.between(9.5, 16, inclusive='left') & (raw.available <= close)]
    raw = raw.sort_values('available').drop_duplicates(['ticker', 'source_updated'], keep='first')
    intra = []
    for (ticker, session), g in raw.groupby(['ticker', 'session']):
        g = g.sort_values('source_updated')
        good = len(g) >= 2 and g.price.nunique() >= 2 and g.hour.iloc[0] <= 11 and g.hour.iloc[-1] >= 14
        intra.append({'ticker': ticker, 'session': session, 'intraday_snapshots': len(g),
                      'intraday_distinct_prices': g.price.nunique(),
                      'intraday_recovery': 100 * (g.price.iloc[-1] / g.price.iloc[0] - 1) if good else np.nan,
                      'intraday_last_from_low': 100 * (g.price.iloc[-1] / g.price.min() - 1) if good else np.nan})
    p = p.merge(pd.DataFrame(intra), on=['ticker', 'session'], how='left', validate='one_to_one')

    outcomes = []
    for r in p.to_dict('records'):
        b = series[r['ticker']].reindex(q.index)
        i = calidx[r['entry']]
        for h in [5, 10, 20]:
            if i + h > len(q):
                continue
            window = b.iloc[i:i+h]
            if window[['open', 'high', 'low', 'close']].isna().any().any():
                continue
            ep = window.open.iloc[0]
            gross = window.close.iloc[-1] / ep - 1
            bench = q.close.iloc[i+h-1] / q.open.iloc[i] - 1
            outcomes.append({'ticker': r['ticker'], 'session': r['session'], 'h': h,
                             'exit': window.index[-1], 'entry_price': ep, 'gross': gross,
                             'net': gross - .004, 'excess': gross - .004 - bench,
                             'mae': window.low.min()/ep-1, 'mfe': window.high.max()/ep-1})
    p.to_csv(OUT / 'panel.csv.gz', index=False)
    pd.DataFrame(outcomes).to_csv(OUT / 'outcomes.csv.gz', index=False)
    audit.update(rows=len(p), tickers=p.ticker.nunique(), dates=p.session.nunique(), first=p.session.min(), last=p.session.max(),
                 valuation_known=int(p.fund_salesYoyTtm.notna().sum()), technical_commits=p.commit.nunique(),
                 intraday_price_rows=int(p.intraday_recovery.notna().sum()), season_unknown=int((~p.season_known).sum()),
                 inferred_candle_dates=int(p.date_inferred.sum()),
                 inputs={str(x.relative_to(ROOT)): digest(x) for x in [OLD/'phase2/results/panel.pkl', OLD/'phase2/results/extra_inputs.pkl', OLD/'phase2/results/warmup_bars.pkl', OLD/'results/technical_observations.pkl', OLD/'results/valuation_versions.csv']},
                 supplements=manifest)
    (OUT / 'audit.json').write_text(json.dumps(audit, indent=2, ensure_ascii=False))
    print(json.dumps({k:v for k,v in audit.items() if k not in ['inputs', 'supplements']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
