"""최종 강건성 스코어링: LOO(최악 종목 제외) 포함.

score = min(ex10, bal10, exH1, exH2, looEx10)  — 전부 양수여야 채택
absScore = min(fwd10, looFwd10) 도 병기 (절대수익 관점)
1/2중 전체 + 3중(시드 확대: 가치·기술·시장 균형) 탐색.
"""
import pickle
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
df = pd.read_pickle(ROOT / 'analysis_tmp/panel.pkl')
df = df[df['fwd10'].notna()].reset_index(drop=True)

y10 = df['fwd10'].values
e10 = df['ex10'].values
y20 = df['fwd20'].values
e20 = df['ex20'].values
half = (df['entryDate'] >= pd.Timestamp('2026-06-15')).values
dates = df['entryDate'].values
tick = df['ticker'].values
uniq_t = pd.unique(tick)
tidx = {t: i for i, t in enumerate(uniq_t)}
tcode = np.array([tidx[t] for t in tick])
NT = len(uniq_t)

cm = pickle.load(open(ROOT / 'analysis_tmp/cond_matrix.pkl', 'rb'))
names, M = cm['names'], cm['M']
K = len(names)

MIN_N, MIN_TICK, MIN_DATES = 40, 8, 10

def evaluate(mask):
    n = int(mask.sum())
    if n < MIN_N:
        return None
    tc = tcode[mask]
    uts = np.unique(tc)
    if len(uts) < MIN_TICK:
        return None
    if len(np.unique(dates[mask])) < MIN_DATES:
        return None
    ex = e10[mask]; ret = y10[mask]
    sums_e = np.bincount(tc, weights=ex, minlength=NT)
    sums_r = np.bincount(tc, weights=ret, minlength=NT)
    cnts = np.bincount(tc, minlength=NT)
    nz = cnts > 0
    per_e = sums_e[nz] / cnts[nz]
    bal = per_e.mean()
    tot_e = ex.sum(); tot_r = ret.sum(); tot_n = n
    # LOO: 각 종목 제외 시 평균
    loo_e = (tot_e - sums_e[nz]) / (tot_n - cnts[nz])
    loo_r = (tot_r - sums_r[nz]) / (tot_n - cnts[nz])
    looEx = loo_e.min(); looRet = loo_r.min()
    h1 = mask & ~half; h2 = mask & half
    if h1.sum() < 10 or h2.sum() < 10:
        return None
    exH1 = e10[h1].mean(); exH2 = e10[h2].mean()
    r = dict(n=n, tickers=len(uts), dates=len(np.unique(dates[mask])),
             fwd10=float(ret.mean()), ex10=float(ex.mean()), bal10=float(bal),
             looEx10=float(looEx), looFwd10=float(looRet),
             exH1=float(exH1), exH2=float(exH2),
             win10=float((ret > 0).mean() * 100))
    m20 = ~np.isnan(y20) & mask
    r['fwd20'] = float(y20[m20].mean()) if m20.sum() >= 20 else np.nan
    r['ex20'] = float(e20[m20].mean()) if m20.sum() >= 20 else np.nan
    r['score'] = min(r['ex10'], r['bal10'], r['exH1'], r['exH2'], r['looEx10'])
    r['absScore'] = min(r['fwd10'], r['looFwd10'])
    return r

results = []
for i in range(K):
    r = evaluate(M[i])
    if r:
        results.append((names[i], (i,), r))
for i in range(K):
    mi = M[i]
    if mi.sum() < MIN_N:
        continue
    for j in range(i + 1, K):
        m = mi & M[j]
        if m.sum() < MIN_N:
            continue
        r = evaluate(m)
        if r:
            results.append((f'{names[i]} & {names[j]}', (i, j), r))

res12 = sorted(results, key=lambda x: -x[2]['score'])
print('=== TOP 1-2 cond by robust score ===')
df12 = pd.DataFrame([dict(cond=nm, **r) for nm, ix, r in res12[:40]])
print(df12[['cond','n','tickers','fwd10','ex10','bal10','looEx10','looFwd10','exH1','exH2','win10','fwd20','score','absScore']].round(2).to_string())

# 3중: 시드 = 상위 600 페어(스코어 기준)
seed = [ix for nm, ix, r in res12 if len(ix) == 2][:600]
tri = []
seen = set()
for (i, j) in seed:
    mij = M[i] & M[j]
    for k in range(K):
        if k in (i, j):
            continue
        key = tuple(sorted((i, j, k)))
        if key in seen:
            continue
        seen.add(key)
        m = mij & M[k]
        if m.sum() < MIN_N:
            continue
        r = evaluate(m)
        if r:
            tri.append((f'{names[i]} & {names[j]} & {names[k]}', key, r))
tri = sorted(tri, key=lambda x: -x[2]['score'])
print('\n=== TOP 3-cond by robust score ===')
df3 = pd.DataFrame([dict(cond=nm, **r) for nm, ix, r in tri[:40]])
print(df3[['cond','n','tickers','fwd10','ex10','bal10','looEx10','looFwd10','exH1','exH2','win10','fwd20','score','absScore']].round(2).to_string())

all_res = [(nm, r) for nm, ix, r in res12] + [(nm, r) for nm, ix, r in tri]
big = pd.DataFrame([dict(cond=nm, **r) for nm, r in all_res])
big.sort_values('score', ascending=False).head(8000).to_csv(ROOT / 'analysis_tmp/grid_final.csv', index=False)

print('\n=== TOP by ABS score (절대수익 강건) ===')
absr = big.sort_values('absScore', ascending=False).head(30)
print(absr[['cond','n','tickers','fwd10','looFwd10','ex10','looEx10','exH1','exH2','win10','fwd20','score','absScore']].round(2).to_string())
