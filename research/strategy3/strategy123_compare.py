"""전략 1 / 2 / 3 동일 프레임 비교 백테스트 + 신호 중복 분석.

전략 1 (공황 저점, rules.py 그대로): price<MA200, VIX>=22, RSI<35|CCI<-150,
  LR기울기>0, 저가<=LR추세선*1.05, QQQ이격도<-3
전략 2 (이평선 눌림): [native] 시즌 오픈 필요(전략1이 열어야 함) + 회복장 + 매수차단선 이하
  + MA20/60/144/200 터치(저가<=MA*1.003, 종가>=MA*0.995)
  [완화판] 시즌 게이트 무시하고 나머지 조건만 — 잠재 성능 측정용
전략 3 (조용한 모멘텀 눌림): RSI>=59, DI차<=4.5, 음봉, QQQ이격도<=매수차단선
청산:
  1/2 native: -30% 손절 + 회복장 종료 2일 확인 전량매도 (목표 없음)
  3: +20% / -15% / 40거래일
  동일조건 비교용: 셋 다 +20/-15/40도 병기
"""
import pickle
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
panel = pd.read_pickle(ROOT / 'analysis_tmp/panel.pkl')
prices = pickle.load(open(ROOT / 'analysis_tmp/prices.pkl', 'rb'))

px = {}
for t, d in prices.items():
    def col(name):
        c = d[name]
        return c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
    px[t] = pd.DataFrame({'open': col('Open').values, 'close': col('Close').values},
                         index=pd.to_datetime(d.index))

ALL_DATES = sorted(set().union(*[set(p.index) for p in px.values()]))
ALL_DATES = [d for d in ALL_DATES if d >= pd.Timestamp('2026-05-12')]

# ---- VIX (전략 1 조건) ----
vix_raw = yf.download('^VIX', start='2026-05-01', end='2026-07-19', progress=False, auto_adjust=False)['Close']
if isinstance(vix_raw, pd.DataFrame): vix_raw = vix_raw.iloc[:, 0]
vix_by_date = vix_raw.to_dict()
def vix_at(date):
    prior = [d for d in vix_by_date if d <= date]
    return vix_by_date[max(prior)] if prior else np.nan
panel = panel.copy()
panel['vix'] = [vix_at(d) for d in panel['date']]
print('VIX 범위:', round(panel['vix'].min(),1), '~', round(panel['vix'].max(),1), '| VIX>=22 스냅샷일:', panel[panel['vix']>=22]['date'].nunique())

# ---- LR 기울기 근사: 종목별 lrTrend의 직전 스냅샷 대비 변화 ----
panel = panel.sort_values(['ticker', 'date'])
panel['lrSlopeApprox'] = panel.groupby('ticker')['lrTrend'].diff()

# ---- 전략별 신호 ----
def ma_touch(low, price, ma):
    return (low <= ma * 1.003) & (price >= ma * 0.995) & ma.notna()

s1 = (
    (panel['price'] < panel['ma200'])
    & (panel['vix'] >= 22)
    & ((panel['rsi'] < 35) | (panel['cci'] < -150))
    & (panel['lrSlopeApprox'] > 0)
    & (panel['candleLow'] <= panel['lrTrend'] * 1.05)
    & (panel['qqqPremium'] < -3)
)
touch_any = (
    ma_touch(panel['candleLow'], panel['price'], panel['ma20'])
    | ma_touch(panel['candleLow'], panel['price'], panel['ma60'])
    | ma_touch(panel['candleLow'], panel['price'], panel['ma144'])
    | ma_touch(panel['candleLow'], panel['price'], panel['ma200'])
)
s2_relaxed = (
    (panel['qqqRecovery'] == 1)
    & (panel['qqqPremium'] <= panel['qqqBuyBlockMax'])
    & touch_any
)
s3 = (
    (panel['rsi'] >= 59)
    & (panel['diSpread'] <= 4.5)
    & (panel['candleUp'] == 0)
    & (panel['qqqPremium'] <= panel['qqqBuyBlockMax'])
)
print(f'신호 수: 전략1={s1.sum()} | 전략2(native, 시즌닫힘)=0 | 전략2(완화)={s2_relaxed.sum()} | 전략3={s3.sum()}')

# ---- 신호 중복 분석 ----
k2 = set(zip(panel.loc[s2_relaxed,'ticker'], panel.loc[s2_relaxed,'date']))
k3 = set(zip(panel.loc[s3,'ticker'], panel.loc[s3,'date']))
both = k2 & k3
print(f'중복(같은 종목·같은 날): {len(both)}건 / 전략2 {len(k2)}건, 전략3 {len(k3)}건')
t2 = set(panel.loc[s2_relaxed,'ticker']); t3 = set(panel.loc[s3,'ticker'])
print(f'종목 겹침: {len(t2 & t3)}개 (전략2 {len(t2)}종목, 전략3 {len(t3)}종목)')

# ---- 회복장 종료 시퀀스 (전략 1/2 native 청산) ----
regime = panel.groupby('date')['qqqRecovery'].mean().sort_index()
non_rec_streak = 0
recovery_end_date = None
for d, v in regime.items():
    non_rec_streak = non_rec_streak + 1 if v < 0.5 else 0
    if non_rec_streak >= 2 and recovery_end_date is None:
        recovery_end_date = d
print('회복장 종료 2일 확인일:', recovery_end_date)

# ---- 시뮬레이터 ----
def run(sig_mask, tp, sl, max_hold, recovery_exit=False, max_slots=5, fee=0.001):
    sig = panel[sig_mask].sort_values(['date', 'rsi'], ascending=[True, False])
    by_date = {d: g for d, g in sig.groupby('date')}
    cash, positions, equity, trades = 1.0, {}, [], []
    pend_in, pend_out = [], []
    for today in ALL_DATES:
        for t in pend_out:
            if t not in positions: continue
            p = px[t]
            if today not in p.index: continue
            pos = positions.pop(t)
            r = p.loc[today, 'open'] * (1 - fee) / pos['entry'] - 1
            cash += pos['alloc'] * (1 + r)
            trades.append(dict(ticker=t, entry=pos['entry_date'], exit=today, ret=r*100,
                               days=pos['days'], reason=pos['reason']))
        pend_out = []
        for t, _ in pend_in:
            if t in positions or len(positions) >= max_slots: continue
            p = px.get(t)
            if p is None or today not in p.index: continue
            alloc = cash / (max_slots - len(positions))
            cash -= alloc
            positions[t] = dict(entry=p.loc[today, 'open']*(1+fee), entry_date=today, alloc=alloc, days=0, reason=None)
        pend_in = []
        for t, pos in list(positions.items()):
            p = px[t]
            if today not in p.index: continue
            pos['days'] += 1
            r = p.loc[today, 'close'] / pos['entry'] - 1
            reason = None
            if recovery_exit and recovery_end_date is not None and today >= recovery_end_date:
                reason = 'recovery_end'
            elif tp is not None and r >= tp: reason = 'target'
            elif r <= sl: reason = 'stop'
            elif max_hold is not None and pos['days'] >= max_hold: reason = 'time'
            if reason:
                pos['reason'] = reason
                pend_out.append(t)
        if today in by_date and len(positions) < max_slots:
            for _, row in by_date[today].iterrows():
                t = row['ticker']
                if t in positions or any(t == q[0] for q in pend_in): continue
                if len(positions) + len(pend_in) - len(pend_out) >= max_slots: break
                pend_in.append((t, today))
        val = cash
        for t, pos in positions.items():
            p = px[t]
            idx = p.index[p.index <= today]
            if len(idx): val += pos['alloc'] * (p.loc[idx[-1], 'close'] / pos['entry'])
        equity.append((today, val))
    for t, pos in positions.items():
        p = px[t]
        trades.append(dict(ticker=t, entry=pos['entry_date'], exit=p.index[-1],
                           ret=(p['close'].iloc[-1]/pos['entry']-1)*100, days=pos['days'], reason='open_end'))
    return pd.Series(dict(equity)).sort_index(), pd.DataFrame(trades)

def summarize(name, eq, tr):
    daily = eq.pct_change().dropna()
    return dict(name=name, total=round((eq.iloc[-1]-1)*100,2),
                MDD=round(((eq/eq.cummax())-1).min()*100,2),
                sharpe=round(daily.mean()/daily.std()*np.sqrt(252),2) if daily.std()>0 else np.nan,
                trades=len(tr), win=round((tr['ret']>0).mean()*100,1) if len(tr) else np.nan,
                avg=round(tr['ret'].mean(),2) if len(tr) else np.nan,
                worst=round(tr['ret'].min(),2) if len(tr) else np.nan,
                avgHold=round(tr['days'].mean(),1) if len(tr) else np.nan)

res = []
# 전략 1: 신호 0이면 스킵 표기
if s1.sum() > 0:
    eq, tr = run(s1, tp=None, sl=-0.30, max_hold=None, recovery_exit=True)
    res.append(summarize('전략1 native', eq, tr))
else:
    res.append(dict(name='전략1 (공황 저점) — 이 기간 신호 0건', total=0, MDD=0, sharpe=np.nan, trades=0, win=np.nan, avg=np.nan, worst=np.nan, avgHold=np.nan))

eq, tr2n = run(s2_relaxed, tp=None, sl=-0.30, max_hold=None, recovery_exit=True)
res.append(summarize('전략2 완화판 · native청산(-30%/회복장종료)', eq, tr2n))
eq2s, tr2s = run(s2_relaxed, tp=0.20, sl=-0.15, max_hold=40)
res.append(summarize('전략2 완화판 · 동일청산(+20/-15/40)', eq2s, tr2s))
eq3, tr3 = run(s3, tp=0.20, sl=-0.15, max_hold=40)
res.append(summarize('전략3 · 자체청산(+20/-15/40)', eq3, tr3))
eq3n, tr3n = run(s3, tp=None, sl=-0.30, max_hold=None, recovery_exit=True)
res.append(summarize('전략3 · native청산 적용시(-30%/회복장종료)', eq3n, tr3n))

print()
print(pd.DataFrame(res).to_string(index=False))

print('\n=== 전략2 완화판(native청산) 트레이드 ===')
t = tr2n.copy(); t['entry']=t['entry'].dt.date; t['exit']=t['exit'].dt.date
print(t.sort_values('entry').round(2).to_string(index=False))

# 신호 레벨 선행수익 비교 (포트폴리오 제약 없이)
print('\n=== 신호 레벨 fwd10/fwd20 비교 ===')
for nm, m in [('전략2 완화', s2_relaxed), ('전략3', s3)]:
    sub = panel[m & panel['fwd10'].notna()]
    sub20 = panel[m & panel['fwd20'].notna()]
    print(f"{nm}: n={len(sub)} fwd10={sub['fwd10'].mean():.2f}% win10={(sub['fwd10']>0).mean()*100:.0f}%"
          f" | n20={len(sub20)} fwd20={sub20['fwd20'].mean():.2f}%")
