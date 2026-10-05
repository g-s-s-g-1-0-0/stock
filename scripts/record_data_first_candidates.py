"""Paper trades from archived observations and dated factual inputs."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import record_swing_research as sr
from scripts import record_research_facts as facts

HISTORY = sr.HISTORY / 'data-first-paper-v1'
CANDIDATES = {
    'S3_ma200_distance25': {'base': 'S3', 'label': '3번: MA200 이격 25% 이하', 'priority': 'low'},
    'S3_rsi35': {'base': 'S3', 'label': '3번: RSI 35 이하', 'priority': 'primary'},
    'S3_intraday_positive': {'base': 'S3', 'label': '3번: 오전 대비 오후 관찰가격 회복', 'priority': 'secondary'},
    'S4_debt1': {'base': 'S4', 'label': '4번: 부채/자본 0~1배', 'priority': 'secondary'},
    'S4_eps_growth': {'base': 'S4', 'label': '4번: 최근 분기 EPS 전년 동기 대비 증가', 'priority': 'low'},
    'S7_high52_drawdown30': {'base': 'S7', 'label': '7번: 52주 고점 대비 30% 이상 하락', 'priority': 'primary'},
    'N_expanded_below200': {'base': 'allowed', 'label': '장기선 아래 변동 확대', 'priority': 'primary'},
    'N_rsi_ahead_macd': {'base': 'allowed', 'label': 'RSI 회복·MACD 지연', 'priority': 'primary'},
    'N_value_laggard': {'base': 'allowed', 'label': 'PBR 제한·관심종목 대비 상대적 부진', 'priority': 'low'},
}
RETIRED = {
    'S3_size100b': '공통 청산에서 원형보다 낮은 성과',
    'S7_obv_positive': '공통 청산에서 성과 악화',
    'S7_volume_ratio_falling5': '공통 청산에서 성과 악화',
    'S7_quality': '흑자·낮은 부채를 함께 붙여도 개선되지 않음',
    'N_expanded_profitable_roe': '변동 확대 후보와 중복되고 추가 가치 불명확',
}
PAIRS = {key: [f'data_{key}_base', f'data_{key}_filtered'] for key in CANDIDATES}
ARM_RULES = {arm: {'stop': .08, 'target': .12, 'days': 20, 'mode': 'common'} for pair in PAIRS.values() for arm in pair}
PROTOCOL = {
    'version': 'data-first-paper-v1', 'startSession': '2026-10-05', 'earliestReviewKST': '2026-12-08',
    'minimumCalendarMonths': 2, 'minimumClosedFilteredTrades': None, 'minimumFilteredEntryDates': None,
    'reviewArm': PAIRS['S3_rsi35'][1], 'arms': list(ARM_RULES), 'armRules': ARM_RULES,
    'candidates': CANDIDATES, 'pairs': PAIRS, 'retired': RETIRED,
    'entry': 'complete archived D candle; D+1 open; unknown source waits until the conservative next-weekday09:30NY cutoff, then remains ineligible',
    'holidayCutoff': 'next weekday ignores holidays conservatively; no late backfill to compensate',
    'exit': 'close -8/+12/20 plus market peak/recovery-end2, next open; .4% cost; no operating strategy change',
    'recoveryBuyCap': 14., 'recoveryExit': 18., 'normalBuyCap': 9., 'roundTripCost': .004,
    'technical': 'latest archived completed D candle available by capture before entry; raw close reconciles to D daily close within0.2%; RSI/MACD/BB/MA200/high52 never backfilled with new indicators',
    'ma50': 'use saved MA50 when present; otherwise calculate D-only daily MA50 and label reconstructed',
    'financial': 'latest available source strictly before D16:00NY, age0..7days; missing or negative-equity ratio unknown',
    'intraday': 'first regular-session saved quote<=11NY and last>=14NY, >=2 distinct prices; source and evidenced availability before D close',
    'peer': 'D20-return minus median of current observed members with a completed archived D candle; >=10 non-ETF stocks',
    'pairedCoverage': 'each candidate has its own base arm on the exact same known-input dates; false and unknown are distinguished',
    'reviewChecklist': 'review after Dec8; initially seek30 closed filtered trades,15 entry dates,10 tickers; these are practical checkpoints, not proof; inspect concentration, open PnL, costs and paired outcomes',
    'definitions': {
        'S3_ma200_distance25': 'S3 and100*(close/MA200-1)<=25', 'S3_rsi35': 'S3 and RSI<=35',
        'S3_intraday_positive': 'S3 and(last_intraday_price/first_intraday_price-1)>0',
        'S4_debt1': 'S4 and0<=Debt/Equity<=1', 'S4_eps_growth': 'S4 and EPSQ/Q>0 (latest quarter year-over-year)',
        'S7_high52_drawdown30': 'S7 and saved52week-high distance<=-30%',
        'N_expanded_below200': 'market allowed and close<=MA200 and BBwidth/BBwidth60mean>1.25',
        'N_rsi_ahead_macd': 'market allowed and RSI>50 and MACDhist<=0',
        'N_value_laggard': 'market allowed and0<PBR<=5 and20-return<=observed-watchlist median',
    },
    'scope': 'private paper only; no live orders, UI or alerts; preserve old69 arms; retire five diagnostic hypotheses',
}


def numeric(value):
    if value is None:
        return None
    if isinstance(value,(int,float)):
        return sr.number(value)
    try:
        return sr.number(float(re.sub(r'[^0-9.+-]', '', str(value))))
    except ValueError:
        return None


def deadline(day):
    date = datetime.fromisoformat(day).date() + timedelta(days=1)
    while date.weekday() >= 5:
        date += timedelta(days=1)
    return datetime.combine(date, datetime.min.time(), sr.NY).replace(hour=9, minute=30)


def forward_eligible(day, now):
    return now < deadline(day)


def ready(features, day, now):
    return features.get('sourceReady', False) or not forward_eligible(day, now)


def source_records(history, current):
    records = {'technical': {}, 'valuation': {}}
    for item in sr.read_lines(Path(history)/'sources.jsonl'):
        kind = item['kind']
        captured = facts.stamp(item.get('firstCapturedAt'))
        if kind not in records or captured is None or captured > current:
            continue
        payload = json.loads((Path(history)/'sources'/f"{kind}-{item['artifactHash']}.json").read_text())
        for ticker, row in payload.get('rows', {}).items():
            available = facts.stamp(row.get('availableAt'))
            updated = facts.stamp(row.get('sourceUpdatedAt'))
            if available is None or updated is None or available > current or updated > current:
                continue
            records[kind].setdefault(ticker, []).append({**row, 'available': available, 'updated': updated,
                                                        'artifactHash': item['artifactHash'], 'firstCapturedAt': item['firstCapturedAt']})
    for group in records.values():
        for rows in group.values():
            rows.sort(key=lambda r: (r['available'], r['updated']))
    return records


def completed_source(rows, day, daily_close, current):
    close_time = datetime.fromisoformat(day).replace(hour=16, tzinfo=sr.NY)
    eligible = []
    for row in rows:
        x = row['data']
        close = numeric(x.get('C - Close'))
        if x.get('dailyPriceDate') != day or row['updated'] < close_time or row['available'] >= deadline(day):
            continue
        if row['available'] > current or close is None or daily_close is None or daily_close <= 0:
            continue
        if abs(close/daily_close-1) <= .002:
            eligible.append(row)
    return eligible[-1] if eligible else None


def financial_source(rows, day):
    close_time = datetime.fromisoformat(day).replace(hour=16, tzinfo=sr.NY)
    eligible = [r for r in rows if r['available'] < close_time and 0 <= (close_time-r['updated']).total_seconds() <= 7*86400]
    return eligible[-1] if eligible else None


def intraday_features(rows, day):
    close_time = datetime.fromisoformat(day).replace(hour=16, tzinfo=sr.NY)
    observations = {}
    for r in rows:
        local = r['updated'].astimezone(sr.NY)
        hour = local.hour+local.minute/60
        value = numeric(r['data'].get('현재가', r['data'].get('currentPrice')))
        if local.date().isoformat() == day and 9.5 <= hour < 16 and r['available'] <= close_time and value is not None and value > 0:
            observations.setdefault(r['updated'], (hour, value, r['artifactHash']))
    quotes = [observations[t] for t in sorted(observations)]
    valid = len(quotes) >= 2 and len({q[1] for q in quotes}) >= 2 and quotes[0][0] <= 11 and quotes[-1][0] >= 14
    return {'intradayRecovery': (quotes[-1][1]/quotes[0][1]-1)*100 if valid else None,
            'intradayQuotes': [{'hourNY':h,'price':p,'artifactHash':a} for h,p,a in quotes]}


def pair_conditions(f):
    def test(keys, fn):
        return None if any(f.get(k) is None for k in keys) else bool(fn())
    return {
        'S3_ma200_distance25': test(['close','ma200'], lambda:100*(f['close']/f['ma200']-1)<=25),
        'S3_rsi35': test(['rsi'], lambda:f['rsi']<=35),
        'S3_intraday_positive': test(['intradayRecovery'], lambda:f['intradayRecovery']>0),
        'S4_debt1': test(['debtEquity'], lambda:0<=f['debtEquity']<=1),
        'S4_eps_growth': test(['epsGrowth'], lambda:f['epsGrowth']>0),
        'S7_high52_drawdown30': test(['high52Distance'], lambda:f['high52Distance']<=-30),
        'N_expanded_below200': test(['close','ma200','bbRatio'], lambda:f['close']<=f['ma200'] and f['bbRatio']>1.25),
        'N_rsi_ahead_macd': test(['rsi','hist'], lambda:f['rsi']>50 and f['hist']<=0),
        'N_value_laggard': test(['pbr','peerRelative20'], lambda:0<f['pbr']<=5 and f['peerRelative20']<=0),
    }


def flags(f, m, eligible=True):
    result = dict.fromkeys(ARM_RULES, False)
    conditions = pair_conditions(f)
    f['candidateConditions'] = conditions
    common = bool(eligible and f.get('sourceReady') and m.get('event') == '당분간 없음' and not m.get('peak'))
    def has(*keys):
        return all(f.get(k) is not None for k in keys)
    s3 = common and has('close','ma200','pctBLow','rsi') and not m['recovery'] and -3<=m['premium']<=7 and f['close']>f['ma200'] and f['pctBLow']<=10 and f['rsi']<=45
    s4 = common and has('close','ma200','hist','histPrior') and not m['recovery'] and m['premium']<=9 and .75<=f['close']/f['ma200']<1 and f['histPrior']<=0<f['hist']
    s7 = common and m['buyAllowed'] and has('close','low','open','previousClose') and f['close']>f['open'] and f['close']>f['previousClose'] and any(
        v is not None and f['low']<=v*1.003 and f['close']>v for v in f['movingAverages'].values())
    bases = {'S3':bool(s3),'S4':bool(s4),'S7':bool(s7),'allowed':bool(common and m['buyAllowed'])}
    f['baseStrategyFlags'] = bases
    for key, cfg in CANDIDATES.items():
        base, selected = PAIRS[key]
        result[base] = bool(bases[cfg['base']] and conditions[key] is not None)
        result[selected] = bool(result[base] and conditions[key])
    return result


def collect_data_first(daily, tickers, now=None, history=HISTORY, event_payload=None, names=None, facts_history=facts.HISTORY):
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    records = source_records(facts_history, current)
    frames = sr.extract_frames(daily, sorted(set(tickers)|{'QQQ'}))
    def enrich(ticker, frame):
        day = frame.index[-1]
        source = completed_source(records['technical'].get(ticker, []), day, sr.number(frame.Close.iloc[-1]), current)
        x = source['data'] if source else {}
        f = {'sourceReady':source is not None,'technicalArtifact':source['artifactHash'] if source else None,
             'technicalAvailableAt':facts.iso(source['available']) if source else None,
             'close':numeric(x.get('C - Close')),'open':numeric(x.get('Candle Open')),'low':numeric(x.get('C - Low')),
             'ma200':numeric(x.get('200일 이동평균선')),'rsi':numeric(x.get('RSI (D)')),
             'hist':numeric(x.get('MACD Histogram (D)')),'histPrior':numeric(x.get('M - H (D-1)')),
             'pctBLow':numeric(x.get('볼린저밴드 %B (저가)')),'high52Distance':numeric(x.get('52주 신고가 대비'))}
        if f['ma200'] is not None and f['ma200']<=0:
            f['ma200'] = None
        averages = {str(n):numeric(x.get(f'{n}일 이동평균선')) for n in (20,50,120,200)}
        f['ma50Source'] = 'saved'
        if averages['50'] is None and len(frame)>=50:
            averages['50'] = sr.number(frame.Close.tail(50).mean())
            f['ma50Source'] = 'reconstructed_daily_prefix'
        f['movingAverages'] = averages
        width, mean = numeric(x.get('볼린저밴드 폭 (D)')), numeric(x.get('지난 60일 볼린저밴드 폭 평균'))
        f['bbRatio'] = width/mean if width is not None and mean is not None and mean>0 else None
        financial = financial_source(records['valuation'].get(ticker, []), day)
        v = financial['data'] if financial else {}
        debt, pbr = numeric(v.get('debtToEquity')), numeric(v.get('pbr'))
        f.update(debtEquity=debt if debt is not None and debt>=0 else None,pbr=pbr if pbr is not None and pbr>0 else None,
                 epsGrowth=numeric(v.get('epsQoq')),financialArtifact=financial['artifactHash'] if financial else None,
                 financialAvailableAt=facts.iso(financial['available']) if financial else None,
                 financialSnapshot=v,**intraday_features(records['technical'].get(ticker,[]),day))
        peers = []
        for member in sorted(set(tickers)-sr.ETF):
            if any(w in (names or {}).get(member,'').upper() for w in ('ETF','DIREXION','PROSHARES','LEVERAGED','2X','3X')):
                continue
            b = frames.get(member)
            if b is None or day not in b.index:
                continue
            b = b.loc[:day]
            if len(b)>=21 and completed_source(records['technical'].get(member,[]),day,sr.number(b.Close.iloc[-1]),current):
                peers.append({'ticker':member,'return20':float((b.Close.iloc[-1]/b.Close.iloc[-21]-1)*100)})
        import statistics
        median = statistics.median(r['return20'] for r in peers) if len(peers)>=10 else None
        own_return = float((frame.Close.iloc[-1]/frame.Close.iloc[-21]-1)*100) if len(frame)>=21 else None
        f.update(peerCount=len(peers),peerMembers=peers,peerMedian20=median,
                 peerRelative20=own_return-median if own_return is not None and median is not None else None)
        return f
    summary = sr.collect(daily,tickers,current,history,event_payload,names,protocol=PROTOCOL,flags=flags,
                         context_enricher=enrich,arm_rules=ARM_RULES,observation_ready=ready,
                         forward_eligibility=forward_eligible,observation_source='Archived technical/valuation observations + completed daily prices')
    observations = sr.read_lines(Path(history)/'observations.jsonl')
    trades = sr.read_lines(Path(history)/'paper-trades.jsonl')
    summary['pairs'] = {key:{'knownObservations':sum(r['features'].get('candidateConditions',{}).get(key) is not None for r in observations),
                            'unknownObservations':sum(r['features'].get('candidateConditions',{}).get(key) is None for r in observations),
                            **{arm:{'closed':sum(t['arm']==arm and t['status']=='closed' for t in trades),
                                    'entryDates':len({t['entry'] for t in trades if t['arm']==arm and t['status']=='closed'})} for arm in pair}}
                        for key,pair in PAIRS.items()}
    summary['waitingForSource'] = len(set(tickers)-{'QQQ'}-{r['ticker'] for r in observations if r['session']==summary['lastSession']}) if summary['lastSession'] else 0
    sr.write_json(Path(history)/'summary.json',summary)
    return summary


def main():
    import yfinance as yf
    stocks = json.loads((ROOT/'data/cache/stocks.json').read_text())['rows']
    names = {r['ticker']:r.get('name','') for r in stocks if r.get('market')=='US'}
    symbols = sorted(set(names)|set(sr.tracked_tickers(HISTORY))|{'QQQ',*facts.BENCHMARKS})
    daily = yf.download(symbols,period='2y',interval='1d',auto_adjust=False,actions=True,progress=False,threads=True)
    events_path = ROOT/'data/cache/market-events.json'
    events = json.loads(events_path.read_text()) if events_path.exists() else None
    current = datetime.now(timezone.utc)
    facts.collect_facts(daily,list(names),now=current)
    collect_data_first(daily,list(names),now=current,event_payload=events,names=names)


if __name__=='__main__':
    main()
