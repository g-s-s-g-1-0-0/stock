"""전 지표 조건 전수 그리드 탐색 (단일 / 2중 / 3중)."""
import itertools, pickle
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
df = pd.read_pickle(ROOT / 'analysis_tmp/panel.pkl')

# 평가 대상 행: fwd10 존재
df = df[df['fwd10'].notna()].reset_index(drop=True)
N = len(df)
print('eval rows:', N)

y10 = df['fwd10'].values
y5 = df['fwd5'].values
y20 = df['fwd20'].values
e10 = df['ex10'].values
e20 = df['ex20'].values
tick = df['ticker'].values
dates = df['entryDate'].values

# ---------------- 조건 라이브러리 ----------------
# 수치형 피처: 분위수 기반 + 도메인 임계값 양방향
NUM_FEATS = [
    # 기술
    'rsi', 'rsiSlope', 'rsiSig', 'cci', 'cciSlope', 'adx', 'adxSlope', 'diSpread',
    'pctB', 'pctBLow', 'bbWidth', 'bbSqueeze', 'bbPeak',
    'macdHistNorm', 'macdHistAccel', 'volumeRatio', 'volumeRatio20', 'volPct',
    'disp200', 'disp144', 'disp60', 'disp20', 'disp5', 'ma20slope5', 'lrGap',
    'bodyRatio', 'lowerWickRatio', 'upperWickRatio', 'daysSinceEarnings',
    # 가치
    'per', 'pbr', 'peg', 'roe', 'ruleOf40', 'epsQoq', 'salesQoq', 'salesYoyTtm',
    'grossMargin', 'opMargin', 'debtToEquity', 'currentRatio', 'pfcf', 'psr',
    'marketCap', 'fwdEpsGrowth', 'earningsYield',
    # 공통(시장)
    'qqqPremium',
]
BOOL_FEATS = [
    'aboveMA200', 'aboveMA20', 'ma20_above_ma60', 'ma20_above_ma200',
    'adxRising', 'macdHistRising', 'macdHistUp1', 'macdHistPos', 'macdGolden',
    'bbExpanding', 'rsiRising', 'cciRising', 'candleUp',
    'qqqRecovery', 'qqqPeak', 'eventSoon', 'hBreakout',
]

conds = []  # (name, mask)
for f in NUM_FEATS:
    v = df[f].values.astype(float)
    ok = ~np.isnan(v)
    if ok.sum() < 200:
        continue
    qs = np.nanpercentile(v, [20, 35, 50, 65, 80])
    seen = set()
    for q, lab in zip(qs, ['p20', 'p35', 'p50', 'p65', 'p80']):
        key = round(q, 6)
        if key in seen:
            continue
        seen.add(key)
        conds.append((f'{f}>= {q:.3g} ({lab})', ok & (v >= q)))
        conds.append((f'{f}<= {q:.3g} ({lab})', ok & (v <= q)))
for f in BOOL_FEATS:
    v = df[f].values.astype(float)
    ok = ~np.isnan(v)
    conds.append((f'{f}=1', ok & (v == 1)))
    conds.append((f'{f}=0', ok & (v == 0)))

# market 조건
conds.append(('market=US', (df['market'] == 'US').values))
conds.append(('market=KR', (df['market'] == 'KR').values))

names = [c[0] for c in conds]
M = np.array([c[1] for c in conds], dtype=bool)
print('conditions:', len(conds))

MIN_N = 40
MIN_TICK = 8
MIN_DATES = 10

def evaluate(mask):
    n = mask.sum()
    if n < MIN_N:
        return None
    ut = len(set(tick[mask]))
    ud = len(set(dates[mask]))
    if ut < MIN_TICK or ud < MIN_DATES:
        return None
    r10 = np.nanmean(y10[mask])
    ex = np.nanmean(e10[mask])
    win = np.nanmean(y10[mask] > 0) * 100
    r20m = y20[mask]; r20m = r20m[~np.isnan(r20m)]
    r20 = r20m.mean() if len(r20m) else np.nan
    ex20m = e20[mask]; ex20m = ex20m[~np.isnan(ex20m)]
    x20 = ex20m.mean() if len(ex20m) else np.nan
    r5 = np.nanmean(y5[mask])
    return dict(n=int(n), tickers=ut, dates=ud, fwd5=r5, fwd10=r10, fwd20=r20,
                ex10=ex, ex20=x20, win10=win)

# ---------------- 단일 ----------------
singles = []
for i, nm in enumerate(names):
    r = evaluate(M[i])
    if r:
        singles.append((nm, r))
s1 = pd.DataFrame([dict(cond=nm, **r) for nm, r in singles])
s1.sort_values('ex10', ascending=False).to_csv(ROOT / 'analysis_tmp/grid_singles.csv', index=False)
print('single results:', len(s1))
print(s1.sort_values('ex10', ascending=False).head(20).to_string())

# ---------------- 2중 ----------------
pairs = []
K = len(conds)
for i in range(K):
    mi = M[i]
    if mi.sum() < MIN_N:
        continue
    for j in range(i + 1, K):
        m = mi & M[j]
        r = evaluate(m)
        if r:
            pairs.append((f'{names[i]} & {names[j]}', r))
p2 = pd.DataFrame([dict(cond=nm, **r) for nm, r in pairs])
p2 = p2.sort_values('ex10', ascending=False)
p2.head(3000).to_csv(ROOT / 'analysis_tmp/grid_pairs.csv', index=False)
print('pair results:', len(p2))
print(p2.head(25).to_string())

pickle.dump(dict(names=names, M=M), open(ROOT / 'analysis_tmp/cond_matrix.pkl', 'wb'))
