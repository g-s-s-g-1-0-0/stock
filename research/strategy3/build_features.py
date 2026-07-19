"""스냅샷 JSONL -> 수치형 피처 패널 + 선행수익률 구축."""
import json, pickle, re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

def parse_num(s):
    """'₩1,464,030', '$149.44', '116%', '46.86', '-' 등 문자열을 float로."""
    if s is None:
        return np.nan
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if s in ('-', '', 'N/A', 'nan', 'None'):
        return np.nan
    neg = s.startswith('-')
    s2 = s.replace('₩', '').replace('$', '').replace(',', '').replace('%', '').strip()
    # 조/억 (KR marketCap)
    m = re.match(r'^(-?[\d.]+)조(?:\s*([\d.]+)억)?$', s2)
    if m:
        v = float(m.group(1)) * 1e12
        if m.group(2):
            v += float(m.group(2)) * 1e8
        return v
    m = re.match(r'^(-?[\d.]+)억$', s2)
    if m:
        return float(m.group(1)) * 1e8
    # US marketCap suffix
    m = re.match(r'^(-?[\d.]+)([TBMK])$', s2, re.I)
    if m:
        mult = {'T': 1e12, 'B': 1e9, 'M': 1e6, 'K': 1e3}[m.group(2).upper()]
        return float(m.group(1)) * mult
    try:
        return float(s2)
    except ValueError:
        return np.nan

def parse_earnings(s, snap_date):
    """'2026-04-29 (D+21)' -> (경과일 양수 = 발표 후, 음수 = 발표 전)."""
    if not s or not isinstance(s, str):
        return np.nan
    m = re.search(r'\(D([+-])(\d+)\)', s)
    if m:
        v = int(m.group(2))
        return v if m.group(1) == '+' else -v
    return np.nan

rows = []
for f in sorted((ROOT / 'data/history').glob('*.jsonl')):
    for line in open(f):
        line = line.strip()
        if line:
            rows.append(json.loads(line))

recs = []
for r in rows:
    ti = r.get('technicalIndicators') or {}
    vi = r.get('valuationIndicators') or {}
    g = lambda k: parse_num(ti.get(k))
    price = r.get('currentPrice')
    rec = dict(
        ticker=r['ticker'], name=r['name'], market=r['market'],
        date=r['snapshotDate'], opinion=r.get('opinion'),
        entryStrategy=r.get('entryStrategy'),
        hBreakout=bool(r.get('hBreakoutCandidate')),
        # ---- 공통(시장) 지표 ----
        qqqPremium=r.get('qqqPremium'),
        qqqBuyBlockMax=r.get('qqqBuyBlockMax'),
        qqqRecovery=1.0 if r.get('qqqRegime') == '급락 후 회복장' else 0.0,
        qqqPeak=1.0 if r.get('qqqPeakTriggered') else 0.0,
        eventSoon=0.0 if ti.get('marketEvent') in (None, '당분간 없음') else 1.0,
        # ---- 개별 기술 지표 (top-level 수치) ----
        adx=r.get('adx'), adxD1=r.get('adxD1'),
        bbWidth=r.get('bbWidth'), bbWidthD1=r.get('bbWidthD1'),
        bbWidthAvg60=r.get('bbWidthAvg60'),
        macdHist=r.get('macdHist'), macdHistD1=r.get('macdHistD1'), macdHistD2=r.get('macdHistD2'),
        plusDI=r.get('plusDI'), minusDI=r.get('minusDI'),
        pctB=r.get('pctB'), pctBLow=r.get('pctBLow'),
        rsi=r.get('rsi'),
        volumeRatio=r.get('volumeRatio'), volumeRatio20=r.get('volumeRatio20'),
        price=price, ma200=r.get('ma200'),
        # ---- technicalIndicators 파싱 ----
        ma5=g('5일 이동평균선'), ma20=g('20일 이동평균선'), ma60=g('60일 이동평균선'),
        ma144=g('144일 이동평균선'),
        ma20d1=g('20일 이동평균선 (D-1)'), ma20d5=g('20일 이동평균선 (D-5)'),
        ma20slope5=g('MA20 5일 기울기'),
        lrTrend=g('120일 저가 회귀 추세선'),
        rsiD1=g('RSI (D-1)'), rsiSig=g('RSI Signal'), rsiSlope=g('RSI 기울기'),
        cci=g('CCI (D)'), cciD1=g('CCI (D-1)'), cciSig=g('CCI Signal'), cciSlope=g('CCI 기울기'),
        macd=g('MACD (12, 26, D)'), macdD1=g('MACD (12, 26, D-1)'),
        macdSig=g('MACD Signal'), macdSlope=g('MACD 기울기'),
        adxSlope=g('ADX 기울기'),
        bbPeak=g('볼린저밴드 Peak (D)'), bbPeakD1=g('볼린저밴드 Peak (D-1)'),
        candleOpen=g('Candle Open'), candleHigh=g('C - High'), candleLow=g('C - Low'),
        candleClose=g('C - Close'),
        body=g('몸통 길이'), upperWick=g('위꼬리 길이'), lowerWick=g('아래꼬리 길이'),
        volPct=g('거래량 (D)'), volPctD1=g('거래량 (D-1)'),
        daysSinceEarnings=parse_earnings(ti.get('실적발표일 (한국 시간 기준)'), r['snapshotDate']),
        # ---- 가치 지표 ----
        per=parse_num(vi.get('per')), pbr=parse_num(vi.get('pbr')), peg=parse_num(vi.get('peg')),
        roe=parse_num(vi.get('roe')), ruleOf40=parse_num(vi.get('ruleOf40')),
        epsQoq=parse_num(vi.get('epsQoq')), salesQoq=parse_num(vi.get('salesQoq')),
        salesYoyTtm=parse_num(vi.get('salesYoyTtm')),
        grossMargin=parse_num(vi.get('grossMargin')), opMargin=parse_num(vi.get('operatingMargin')),
        debtToEquity=parse_num(vi.get('debtToEquity')), currentRatio=parse_num(vi.get('currentRatio')),
        pfcf=parse_num(vi.get('priceToFreeCashFlow')), psr=parse_num(vi.get('priceToSales')),
        marketCap=parse_num(vi.get('marketCap')),
        epsTtm=parse_num(vi.get('epsTtm')), epsNextYear=parse_num(vi.get('epsNextYear')),
        salesPastYears=parse_num(vi.get('salesPastYears')),
    )
    recs.append(rec)

df = pd.DataFrame(recs)
df['date'] = pd.to_datetime(df['date'])

# ---- 파생 피처 ----
def cmp_bool(a, b):
    """a > b, 결측이면 NaN 유지."""
    out = (a > b).astype(float)
    out[a.isna() | b.isna()] = np.nan
    return out

df['disp200'] = (df['price'] / df['ma200'] - 1) * 100
df['disp144'] = (df['price'] / df['ma144'] - 1) * 100
df['disp60'] = (df['price'] / df['ma60'] - 1) * 100
df['disp20'] = (df['price'] / df['ma20'] - 1) * 100
df['disp5'] = (df['price'] / df['ma5'] - 1) * 100
df['ma20_above_ma60'] = cmp_bool(df['ma20'], df['ma60'])
df['ma20_above_ma200'] = cmp_bool(df['ma20'], df['ma200'])
df['aboveMA200'] = cmp_bool(df['price'], df['ma200'])
df['aboveMA20'] = cmp_bool(df['price'], df['ma20'])
df['diSpread'] = df['plusDI'] - df['minusDI']
df['adxRising'] = cmp_bool(df['adx'], df['adxD1'])
_r = cmp_bool(df['macdHist'], df['macdHistD1'])
_r2 = cmp_bool(df['macdHistD1'], df['macdHistD2'])
df['macdHistRising'] = _r * _r2
df['macdHistRising'][_r.isna() | _r2.isna()] = np.nan
df['macdHistUp1'] = _r
df['macdHistPos'] = cmp_bool(df['macdHist'], pd.Series(0.0, index=df.index))
df['macdGolden'] = cmp_bool(df['macd'], df['macdSig'])
df['macdHistNorm'] = df['macdHist'] / df['price'] * 100          # 가격 정규화
df['macdHistAccel'] = (df['macdHist'] - df['macdHistD1']) / df['price'] * 100
df['bbSqueeze'] = df['bbWidth'] / df['bbWidthAvg60']
df['bbExpanding'] = (df['bbWidth'] > df['bbWidthD1']).astype(float)
df['rsiRising'] = (df['rsi'] > df['rsiD1']).astype(float)
df['cciRising'] = (df['cci'] > df['cciD1']).astype(float)
df['lrGap'] = (df['price'] / df['lrTrend'] - 1) * 100
rng = (df['candleHigh'] - df['candleLow']).replace(0, np.nan)
df['bodyRatio'] = df['body'] / rng
df['lowerWickRatio'] = df['lowerWick'] / rng
df['upperWickRatio'] = df['upperWick'] / rng
df['candleUp'] = (df['candleClose'] > df['candleOpen']).astype(float)
df['fwdEpsGrowth'] = np.where((df['epsTtm'].abs() > 0), (df['epsNextYear'] - df['epsTtm']) / df['epsTtm'].abs() * 100, np.nan)
df['earningsYield'] = np.where(df['per'] > 0, 100 / df['per'], np.nan)

# ---- 선행수익률: yfinance 일봉 기준 ----
prices = pickle.load(open(ROOT / 'analysis_tmp/prices.pkl', 'rb'))
px = {}
for t, d in prices.items():
    c = d['Close']
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    o = d['Open']
    if isinstance(o, pd.DataFrame):
        o = o.iloc[:, 0]
    px[t] = pd.DataFrame({'open': o.values, 'close': c.values}, index=pd.to_datetime(d.index))

HORIZONS = [3, 5, 10, 15, 20]
fwd_cols = {f'fwd{h}': [] for h in HORIZONS}
entry_dates, entry_opens = [], []
for _, row in df.iterrows():
    t = row['ticker']
    p = px.get(t)
    if p is None:
        entry_dates.append(pd.NaT); entry_opens.append(np.nan)
        for h in HORIZONS: fwd_cols[f'fwd{h}'].append(np.nan)
        continue
    idx = p.index
    # 스냅샷 다음 거래일 시가 진입
    pos = idx.searchsorted(row['date'], side='right')
    if pos >= len(idx):
        entry_dates.append(pd.NaT); entry_opens.append(np.nan)
        for h in HORIZONS: fwd_cols[f'fwd{h}'].append(np.nan)
        continue
    e_date = idx[pos]; e_open = p['open'].iloc[pos]
    entry_dates.append(e_date); entry_opens.append(e_open)
    for h in HORIZONS:
        j = pos + h
        if j < len(idx) and e_open > 0:
            fwd_cols[f'fwd{h}'].append((p['close'].iloc[j] / e_open - 1) * 100)
        else:
            fwd_cols[f'fwd{h}'].append(np.nan)

df['entryDate'] = entry_dates
df['entryOpen'] = entry_opens
for h in HORIZONS:
    df[f'fwd{h}'] = fwd_cols[f'fwd{h}']

# 주말/휴일 스냅샷 중복 제거: (ticker, entryDate) 첫 스냅샷만
df = df.sort_values(['ticker', 'date'])
before = len(df)
df = df[df['entryDate'].notna()]
df = df.drop_duplicates(subset=['ticker', 'entryDate'], keep='first').reset_index(drop=True)
print(f'rows: {before} -> dedup {len(df)}')

# 같은 진입일 유니버스 평균 대비 초과수익 (시장 드리프트 통제)
for h in HORIZONS:
    base = df.groupby('entryDate')[f'fwd{h}'].transform('mean')
    df[f'ex{h}'] = df[f'fwd{h}'] - base

df.to_pickle(ROOT / 'analysis_tmp/panel.pkl')
print(df.shape)
print('fwd10 non-null:', df['fwd10'].notna().sum(), '| fwd20 non-null:', df['fwd20'].notna().sum())
print('date range:', df['date'].min(), df['date'].max())
print('baseline mean fwd10:', df['fwd10'].mean().round(3), 'fwd20:', df['fwd20'].mean().round(3))
