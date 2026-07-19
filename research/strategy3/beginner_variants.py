"""전략 1/2(초보자·저리스크) 맥락에 맞춘 '조용한 모멘텀 눌림' 변형 비교.

변형 축:
  V0  원안: RSI>=59 & DI차<=4.5 & 음봉, +20/-15/40일
  V1  +QQQ 매수차단선 게이트 (스냅샷 qqqPremium <= qqqBuyBlockMax)
  V2  +ATR 필터: 신호일 ATR(14)% <= 6 (고변동 종목 제외 → 갭 손절 방지)
  V3  +MA20 터치형: 저가가 MA20 근접(전략 2와 같은 터치 문법) — 음봉 조건 대체
  V4  V2 + 보수 청산 (+12% / -10% / 25일) — 승률·MDD 우선
  V5  V2 + 전략2식 청산 실험: 목표 없이 -10% 손절 + 20일선 2일 연속 이탈 시 전량매도
"""
import pickle
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
panel = pd.read_pickle(ROOT / 'analysis_tmp/panel.pkl')
prices = pickle.load(open(ROOT / 'analysis_tmp/prices.pkl', 'rb'))

px = {}
for t, d in prices.items():
    def col(name):
        c = d[name]
        return c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
    df = pd.DataFrame({'open': col('Open').values, 'high': col('High').values,
                       'low': col('Low').values, 'close': col('Close').values},
                      index=pd.to_datetime(d.index))
    # ATR(14)% (EMA), MA20: 신호일 필터/청산용
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs(),
    ], axis=1).max(axis=1)
    df['atrPct'] = tr.ewm(span=14, adjust=False).mean() / df['close'] * 100
    df['ma20'] = df['close'].rolling(20).mean()
    px[t] = df

ALL_DATES = sorted(set().union(*[set(p.index) for p in px.values()]))
ALL_DATES = [d for d in ALL_DATES if d >= pd.Timestamp('2026-05-12')]

BASE = (panel['rsi'] >= 59) & (panel['diSpread'] <= 4.5)

def atr_at(t, date):
    p = px.get(t)
    if p is None: return np.nan
    idx = p.index[p.index <= date]
    return p.loc[idx[-1], 'atrPct'] if len(idx) else np.nan

def sig_variant(kind):
    m = BASE.copy()
    if kind in ('V0', 'V1', 'V2', 'V4', 'V5'):
        m &= (panel['candleUp'] == 0)
    if kind in ('V1', 'V2', 'V4', 'V5'):
        m &= (panel['qqqPremium'] <= panel['qqqBuyBlockMax'])
    if kind == 'V3':
        # 음봉 대신 전략 2 문법의 MA20 터치+회복
        m &= (panel['candleLow'] <= panel['ma20'] * 1.003) & (panel['price'] >= panel['ma20'] * 0.995)
        m &= (panel['qqqPremium'] <= panel['qqqBuyBlockMax'])
    sig = panel[m].copy()
    if kind in ('V2', 'V4', 'V5'):
        sig['atrSig'] = [atr_at(t, d) for t, d in zip(sig['ticker'], sig['date'])]
        sig = sig[sig['atrSig'] <= 6]
    return sig

def run(sig, tp, sl, max_hold, max_slots=5, fee=0.001, ma20_exit=False):
    sig = sig.sort_values(['date', 'rsi'], ascending=[True, False])
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
            trades.append(dict(ticker=t, entry=pos['entry_date'], exit=today, ret=r * 100,
                               days=pos['days'], reason=pos['reason']))
        pend_out = []
        for t, _ in pend_in:
            if t in positions or len(positions) >= max_slots: continue
            p = px.get(t)
            if p is None or today not in p.index: continue
            alloc = cash / (max_slots - len(positions))
            cash -= alloc
            positions[t] = dict(entry=p.loc[today, 'open'] * (1 + fee), entry_date=today,
                                alloc=alloc, days=0, reason=None, belowMA=0)
        pend_in = []
        for t, pos in list(positions.items()):
            p = px[t]
            if today not in p.index: continue
            pos['days'] += 1
            c = p.loc[today, 'close']
            r = c / pos['entry'] - 1
            reason = None
            if tp is not None and r >= tp: reason = 'target'
            elif r <= sl: reason = 'stop'
            elif ma20_exit:
                ma = p.loc[today, 'ma20']
                pos['belowMA'] = pos['belowMA'] + 1 if (ma == ma and c < ma) else 0
                if pos['belowMA'] >= 2: reason = 'ma20_break'
            if reason is None and max_hold is not None and pos['days'] >= max_hold:
                reason = 'time'
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
                           ret=(p['close'].iloc[-1] / pos['entry'] - 1) * 100,
                           days=pos['days'], reason='open_end'))
    return pd.Series(dict(equity)).sort_index(), pd.DataFrame(trades)

def summarize(name, eq, tr):
    daily = eq.pct_change().dropna()
    worst = tr['ret'].min() if len(tr) else np.nan
    return dict(name=name, total=round((eq.iloc[-1] - 1) * 100, 2),
                MDD=round(((eq / eq.cummax()) - 1).min() * 100, 2),
                sharpe=round(daily.mean() / daily.std() * np.sqrt(252), 2) if daily.std() > 0 else np.nan,
                trades=len(tr), win=round((tr['ret'] > 0).mean() * 100, 1) if len(tr) else np.nan,
                avg=round(tr['ret'].mean(), 2) if len(tr) else np.nan,
                worst=round(worst, 2))

res = []
specs = [
    ('V0 원안 (+20/-15/40)',               'V0', dict(tp=0.20, sl=-0.15, max_hold=40)),
    ('V1 +QQQ차단선 (+20/-15/40)',          'V1', dict(tp=0.20, sl=-0.15, max_hold=40)),
    ('V2 +ATR<=6 (+20/-15/40)',            'V2', dict(tp=0.20, sl=-0.15, max_hold=40)),
    ('V2 +ATR<=6 (+20/-10/40)',            'V2', dict(tp=0.20, sl=-0.10, max_hold=40)),
    ('V3 MA20터치형 (+20/-10/40)',          'V3', dict(tp=0.20, sl=-0.10, max_hold=40)),
    ('V4 보수청산 (+12/-10/25)',            'V4', dict(tp=0.12, sl=-0.10, max_hold=25)),
    ('V5 20일선 2일이탈 청산 (-10 손절)',     'V5', dict(tp=None, sl=-0.10, max_hold=60, ma20_exit=True)),
]
trades_map = {}
for name, kind, kw in specs:
    sig = sig_variant(kind)
    eq, tr = run(sig, **kw)
    r = summarize(name, eq, tr)
    r['signals'] = len(sig)
    res.append(r)
    trades_map[name] = (eq, tr)

out = pd.DataFrame(res)
print(out.to_string(index=False))

print('\n=== V2 (+20/-10/40) 트레이드 ===')
eq, tr = trades_map['V2 +ATR<=6 (+20/-10/40)']
tr2 = tr.copy(); tr2['entry'] = tr2['entry'].dt.date; tr2['exit'] = tr2['exit'].dt.date
print(tr2.sort_values('entry').round(2).to_string(index=False))

print('\n=== V5 트레이드 ===')
eq5, tr5 = trades_map['V5 20일선 2일이탈 청산 (-10 손절)']
tr5 = tr5.copy(); tr5['entry'] = tr5['entry'].dt.date; tr5['exit'] = tr5['exit'].dt.date
print(tr5.sort_values('entry').round(2).to_string(index=False))

print('\n=== V4 트레이드 ===')
eq4, tr4 = trades_map['V4 보수청산 (+12/-10/25)']
tr4 = tr4.copy(); tr4['entry'] = tr4['entry'].dt.date; tr4['exit'] = tr4['exit'].dt.date
print(tr4.sort_values('entry').round(2).to_string(index=False))
