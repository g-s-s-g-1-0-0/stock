"""최종 전략 포트폴리오 백테스트: '조용한 모멘텀 눌림' (Quiet Momentum Pullback)

신호 (스냅샷 지표 기준, 당일 종가 확정 후):
  - RSI(14) >= 59
  - (+DI - -DI) <= 4.5   (모멘텀은 강하지만 DMI 방향성 과열 아님 = 눌림/횡보 소화 중)
  - 당일 음봉 (종가 < 시가)  [변형: 없음/있음 비교]
진입: 다음 거래일 시가
청산: 목표익절 / 손절 / 시간청산 그리드 비교. 청산은 종가 기준 판정, 다음날 시가 체결.
포지션: 동일비중, 최대 동시 보유 슬롯 제한, 종목당 1포지션, 신호 복수면 RSI 높은 순.
벤치마크: QQQ 매수후보유, 유니버스 균등 데일리, 기존 시스템 opinion=='매수' 신호.
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
    o = d['Open'];  c = d['Close']
    if isinstance(o, pd.DataFrame): o = o.iloc[:, 0]
    if isinstance(c, pd.DataFrame): c = c.iloc[:, 0]
    px[t] = pd.DataFrame({'open': o.values, 'close': c.values}, index=pd.to_datetime(d.index))

import yfinance as yf
qqq = yf.download('QQQ', start='2026-05-01', progress=False, auto_adjust=False)
qqq_c = qqq['Close']
if isinstance(qqq_c, pd.DataFrame): qqq_c = qqq_c.iloc[:, 0]

# ---------------- 신호 정의 ----------------
def make_signals(with_red_candle=True):
    m = (panel['rsi'] >= 59) & (panel['diSpread'] <= 4.5)
    if with_red_candle:
        m &= (panel['candleUp'] == 0)
    sig = panel[m].copy()
    return sig

def system_buy_signals():
    return panel[panel['opinion'] == '매수'].copy()

# ---------------- 시뮬레이터 ----------------
ALL_DATES = sorted(set().union(*[set(p.index) for p in px.values()]))
ALL_DATES = [d for d in ALL_DATES if d >= pd.Timestamp('2026-05-12')]

def run(sig, tp=0.20, sl=-0.10, max_hold=25, max_slots=5, fee=0.001):
    """fee: 편도 수수료+슬리피지."""
    sig = sig.sort_values(['date', 'rsi'], ascending=[True, False])
    sig_by_date = {d: g for d, g in sig.groupby('date')}
    cash = 1.0
    positions = {}  # ticker -> dict(entry, entry_date, shares_frac)
    equity = []
    trades = []
    pending_entry = []   # (ticker, signal_date)
    pending_exit = []    # ticker list to close at open
    for today in ALL_DATES:
        # 1) 시가: 예약된 청산 체결
        for t in pending_exit:
            if t not in positions: continue
            p = px[t]
            if today not in p.index: continue
            pos = positions.pop(t)
            exit_px = p.loc[today, 'open'] * (1 - fee)
            ret = exit_px / pos['entry'] - 1
            cash += pos['alloc'] * (1 + ret)
            trades.append(dict(ticker=t, entry_date=pos['entry_date'], exit_date=today,
                               ret=ret * 100, days=pos['days'], reason=pos['reason']))
        pending_exit = []
        # 2) 시가: 예약된 진입 체결
        for t, sd in pending_entry:
            if t in positions or len(positions) >= max_slots: continue
            p = px.get(t)
            if p is None or today not in p.index: continue
            alloc = cash / (max_slots - len(positions))
            entry_px = p.loc[today, 'open'] * (1 + fee)
            cash -= alloc
            positions[t] = dict(entry=entry_px, entry_date=today, alloc=alloc, days=0, reason=None)
        pending_entry = []
        # 3) 종가: 청산 판정
        for t, pos in list(positions.items()):
            p = px[t]
            if today not in p.index: continue
            pos['days'] += 1
            c = p.loc[today, 'close']
            r = c / pos['entry'] - 1
            reason = None
            if r >= tp: reason = 'target'
            elif r <= sl: reason = 'stop'
            elif pos['days'] >= max_hold: reason = 'time'
            if reason:
                pos['reason'] = reason
                pending_exit.append(t)
        # 4) 종가: 신규 신호 예약
        if today in sig_by_date and len(positions) < max_slots:
            for _, row in sig_by_date[today].iterrows():
                t = row['ticker']
                if t in positions or any(t == q[0] for q in pending_entry): continue
                if len(positions) + len(pending_entry) - len(pending_exit) >= max_slots: break
                pending_entry.append((t, today))
        # 5) 평가
        val = cash
        for t, pos in positions.items():
            p = px[t]
            idx = p.index[p.index <= today]
            if len(idx) == 0: continue
            c = p.loc[idx[-1], 'close']
            val += pos['alloc'] * (c / pos['entry'])
        equity.append((today, val))
    # 잔여 포지션 마지막 종가 청산 기록
    for t, pos in positions.items():
        p = px[t]
        c = p['close'].iloc[-1]
        trades.append(dict(ticker=t, entry_date=pos['entry_date'], exit_date=p.index[-1],
                           ret=(c / pos['entry'] - 1) * 100, days=pos['days'], reason='open_end'))
    eq = pd.Series(dict(equity)).sort_index()
    tr = pd.DataFrame(trades)
    return eq, tr

def summarize(name, eq, tr):
    total = (eq.iloc[-1] - 1) * 100
    dd = ((eq / eq.cummax()) - 1).min() * 100
    daily = eq.pct_change().dropna()
    sharpe = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else np.nan
    n = len(tr)
    win = (tr['ret'] > 0).mean() * 100 if n else np.nan
    avg = tr['ret'].mean() if n else np.nan
    closed = tr[tr['reason'] != 'open_end']
    return dict(strategy=name, totalRet=round(total, 2), MDD=round(dd, 2), sharpe=round(sharpe, 2),
                trades=n, winRate=round(win, 1), avgTrade=round(avg, 2),
                avgHold=round(tr['days'].mean(), 1) if n else np.nan,
                targetN=int((closed['reason'] == 'target').sum()),
                stopN=int((closed['reason'] == 'stop').sum()),
                timeN=int((closed['reason'] == 'time').sum()))

rows = []
sig_red = make_signals(True)
sig_nored = make_signals(False)
sig_sys = system_buy_signals()
print('signal counts: red-candle', len(sig_red), '| no-filter', len(sig_nored), '| system-buy', len(sig_sys))

# 청산 그리드
for tp in [0.12, 0.20, 0.30]:
    for sl in [-0.07, -0.10, -0.15]:
        for mh in [15, 25, 40]:
            eq, tr = run(sig_red, tp=tp, sl=sl, max_hold=mh)
            rows.append(dict(**summarize(f'QMP-red tp{int(tp*100)} sl{int(sl*100)} h{mh}', eq, tr)))
grid = pd.DataFrame(rows).sort_values('totalRet', ascending=False)
print('\n=== 청산 그리드 (음봉 필터 포함) ===')
print(grid.to_string(index=False))

# 최적 설정으로 변형 비교
best = grid.iloc[0]
import re
m = re.search(r'tp(\d+) sl(-?\d+) h(\d+)', best['strategy'])
TP, SL, MH = int(m.group(1))/100, int(m.group(2))/100, int(m.group(3))

comp = []
eq_red, tr_red = run(sig_red, tp=TP, sl=SL, max_hold=MH)
comp.append(summarize('최종: RSI>=59 & DIspread<=4.5 & 음봉', eq_red, tr_red))
eq_nr, tr_nr = run(sig_nored, tp=TP, sl=SL, max_hold=MH)
comp.append(summarize('변형: 음봉 필터 제외', eq_nr, tr_nr))
eq_sys, tr_sys = run(sig_sys, tp=TP, sl=SL, max_hold=MH)
comp.append(summarize('벤치: 기존 시스템 매수신호(동일 청산)', eq_sys, tr_sys))

qs = qqq_c[qqq_c.index >= pd.Timestamp('2026-05-12')]
qqq_ret = (qs.iloc[-1] / qs.iloc[0] - 1) * 100
qdd = ((qs / qs.cummax()) - 1).min() * 100
comp.append(dict(strategy='벤치: QQQ 보유', totalRet=round(qqq_ret, 2), MDD=round(qdd, 2),
                 sharpe=np.nan, trades=np.nan, winRate=np.nan, avgTrade=np.nan, avgHold=np.nan,
                 targetN=np.nan, stopN=np.nan, timeN=np.nan))
print('\n=== 최종 비교 ===')
print(pd.DataFrame(comp).to_string(index=False))

print('\n=== 최종 전략 트레이드 로그 ===')
tr_red['entry_date'] = tr_red['entry_date'].dt.date
tr_red['exit_date'] = tr_red['exit_date'].dt.date
print(tr_red.sort_values('entry_date').round(2).to_string(index=False))

eq_red.to_csv(ROOT / 'analysis_tmp/final_equity.csv')
tr_red.to_csv(ROOT / 'analysis_tmp/final_trades.csv', index=False)
grid.to_csv(ROOT / 'analysis_tmp/final_exit_grid.csv', index=False)
