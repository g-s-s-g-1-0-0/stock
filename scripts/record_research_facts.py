"""Immutable research inputs, independent of orders and existing paper definitions."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import subprocess

from scripts import record_swing_research as sr

BENCHMARKS = ('SPY', 'IWM', 'SMH', 'RSP', 'HYG', 'IEF', 'TLT')
HISTORY = sr.HISTORY / 'facts-v1'
PROTOCOL = {
    'version': 'facts-v1', 'startSession': '2026-10-05', 'earliestReviewKST': '2026-12-08',
    'purpose': 'freeze original inputs for the data-first audit; no orders, no new paper fills, no alteration of the existing69 arms',
    'availability': 'verified matching Git revision commit and source timestamps; otherwise actual capture; never infer prior availability from a source timestamp alone',
    'financialCutoff': 'strictly before signal D close, source snapshot age<=7 calendar days; preserved vendor values may be older than the snapshot',
    'technicalCutoff': 'complete D candle saved before D+1 open; preserve original values separately from reconstructed daily indicators',
    'intradayCutoff': 'source and independently evidenced availability before D close; first source at/before11:00 and last at/after14:00 NY, >=2 distinct prices',
    'fundamentalSource': 'archived vendor snapshot, not audited SEC event data; SalesQ/Q and EPSQ/Q mean latest-quarter year-over-year for US stocks',
    'forecastFieldsExcludedFromFactTests': ['peg', 'epsNextYear'],
    'calendar': 'earningsDate is a stored calendar string, not a verified announcement timestamp or surprise',
    'marketPrices': 'completed unadjusted Yahoo/yfinance daily ETF price history, split-adjusted price returns, cash dividends excluded; HYG/IEF is a price proxy, not a credit spread',
    'benchmarks': list(BENCHMARKS),
    'missing': 'unknown is retained; failed/missing source never becomes a failing strategy condition',
}
TECH_KEYS = (
    'ticker', 'market', 'updatedAt', 'dailyPriceDate', 'currentPrice', 'marketEvent',
    'conditionSummary', 'entrySignalCodes', 'trendSignal', 'tradingDates',
    'RSI (D)', 'RSI (D-1)', 'CCI (D)', 'CCI (D-1)', 'MACD Histogram (D)', 'M - H (D-1)',
    'ADX (14, D)', 'ADX (14, D-1)', '+DI (DMI, 14)', '-DI (DMI, 14)',
    'Candle Open', 'C - High', 'C - Low', 'C - Close', 'C - Volume',
    '20일 평균 대비 거래량 (D)', '볼린저밴드 %B (종가)', '볼린저밴드 %B (저가)',
    '볼린저밴드 폭 (D)', '볼린저밴드 폭 (D-1)', '지난 60일 볼린저밴드 폭 평균',
    '현재가', '20일 이동평균선', '50일 이동평균선', '60일 이동평균선', '120일 이동평균선',
    '144일 이동평균선', '200일 이동평균선', 'MA20 5일 기울기', '120일 저가 회귀 추세선',
    'ATR (14, %)', '52주 신고가 대비', '52주 신고가 후 경과일', 'QQQ 대비 상대강도 (20일)',
    'OBV 누적강도 (20일)', 'Williams %R (14)',
)


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def source_snapshot(root, kind, tickers, current):
    path = root / 'data/cache' / f'{kind}.json'
    if not path.exists():
        return {'kind': kind, 'status': 'missing'}
    raw = path.read_bytes()
    payload = json.loads(raw)
    revision, committed = None, None
    try:
        relative = path.relative_to(root).as_posix()
        log = subprocess.check_output(['git', 'log', '-1', '--format=%H %cI', '--', relative], cwd=root, stderr=subprocess.DEVNULL, timeout=10).decode().strip()
        if log:
            candidate, when = log.split(' ', 1)
            archived = subprocess.check_output(['git', 'show', f'{candidate}:{relative}'], cwd=root, stderr=subprocess.DEVNULL, timeout=10)
            if archived == raw:
                revision, committed = candidate, stamp(when)
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    updated = stamp(payload.get('meta', {}).get('updatedAt'))
    evidence = committed if committed is not None else current
    available = max(t for t in [evidence, updated] if t is not None)
    rows = payload.get('rows', {})
    selected = {}
    for ticker in tickers:
        r = rows.get(ticker)
        if not isinstance(r, dict):
            continue
        row_updated = stamp(r.get('updatedAt'))
        row_available = max(available, row_updated) if row_updated else available
        data = {k: r[k] for k in TECH_KEYS if k in r} if kind == 'technical' else r
        selected[ticker] = {'availableAt': iso(row_available), 'sourceUpdatedAt': iso(row_updated or updated) if row_updated or updated else None,
                            'futureTimestamp': row_available > current, 'data': data}
    return {'kind': kind, 'status': 'recorded', 'sourceSha256': hashlib.sha256(raw).hexdigest(),
            'availableAt': iso(available), 'sourceUpdatedAt': iso(updated) if updated else None,
            'revision': revision, 'revisionCommittedAt': iso(committed) if committed else None,
            'availabilityEvidence': 'matching_git_revision' if committed else 'capture_only',
            'meta': payload.get('meta', {}), 'rows': selected,
            **({'qqqMarketState': payload.get('qqqMarketState'), 'marketSnapshot': payload.get('marketSnapshot')} if kind == 'technical' else {})}


def collect_facts(daily, tickers, now=None, history=HISTORY, root=sr.ROOT):
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    history, root = Path(history), Path(root)
    sr.write_json(history / 'protocol.json', PROTOCOL)
    index = sr.read_lines(history / 'sources.jsonl')
    known = {r['artifactHash'] for r in index}
    refs, missing = {}, []
    for kind in ['technical', 'valuation']:
        snapshot = source_snapshot(root, kind, tickers, current)
        if snapshot['status'] != 'recorded':
            missing.append(kind)
            continue
        key = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        refs[kind] = key
        if key not in known:
            sr.write_json(history / 'sources' / f'{kind}-{key}.json', snapshot)
            index.append({'kind': kind, 'artifactHash': key, 'sourceSha256': snapshot['sourceSha256'],
                          'availableAt': snapshot['availableAt'], 'firstCapturedAt': iso(current)})
            known.add(key)
    sr.write_lines(history / 'sources.jsonl', index)
    members = sr.read_lines(history / 'membership.jsonl')
    membership = {'capturedAt': iso(current), 'tickers': sorted(set(tickers)-sr.ETF), 'sources': refs}
    if membership not in members:
        members.append(membership)
    sr.write_lines(history / 'membership.jsonl', members)
    frames = sr.extract_frames(daily, ['QQQ', *BENCHMARKS])
    local = current.astimezone(sr.NY)
    context = sr.read_lines(history / 'market-context.jsonl')
    previous = {(r['ticker'],r['session']) for r in context}
    for ticker in ['QQQ', *BENCHMARKS]:
        frame = frames.get(ticker)
        if frame is None or frame.empty:
            missing.append(ticker)
            continue
        complete = frame[[d < local.date().isoformat() or d == local.date().isoformat() and (local.hour, local.minute) >= (16,5) for d in frame.index]]
        if complete.empty:
            continue
        day = complete.index[-1]
        if day < PROTOCOL['startSession'] or (ticker,day) in previous:
            continue
        close = complete.Close
        record = {'ticker':ticker,'session':day,'firstCapturedAt':iso(current),
                  'bar':{c.lower():sr.number(complete[c].iloc[-1]) for c in ['Open','High','Low','Close','Volume']},
                  'ma20':sr.number(close.tail(20).mean()) if len(close)>=20 else None,
                  'return5':sr.number((close.iloc[-1]/close.iloc[-6]-1)*100) if len(close)>=6 else None,
                  'return20':sr.number((close.iloc[-1]/close.iloc[-21]-1)*100) if len(close)>=21 else None,
                  'source':'yfinance.download auto_adjust=False interval=1d'}
        if record['bar']['close'] is None:
            missing.append(ticker)
            continue
        context.append(record)
    sr.write_lines(history / 'market-context.jsonl', sorted(context,key=lambda r:(r['session'],r['ticker'])))
    summary = {'version':PROTOCOL['version'],'capturedAt':iso(current),'sourceArtifacts':len(index),'membershipCaptures':len(members),
               'marketRows':len(context),'missingSources':missing,'status':'recording_inputs' if refs else 'missing_inputs',
               'newPaperArms':0,'liveChanges':False}
    sr.write_json(history/'summary.json', summary)
    return summary
