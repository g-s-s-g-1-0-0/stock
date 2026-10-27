"""Replay the 13-item historical notification without changing live state."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import record_web_api_logs as logs
from scripts import web_refresh_notifications as mail

SNAPSHOT = '49a8743d'
TICKERS = {'AMD', 'ASX', 'BE', 'CRDO', 'STX', 'TER', 'VST', 'GNRC', 'QQQ', 'QLD', 'USD', 'ARM', 'COHU'}


def snapshot(ref, name):
    return json.loads(subprocess.check_output(['git', 'show', f'{ref}:web/public/api/{name}.json']))


class HistoricalClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = datetime(2026, 10, 26, 9, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


def build_preview():
    previous = snapshot(SNAPSHOT + '^', 'stocks')
    current = snapshot(SNAPSHOT, 'stocks')
    technical = snapshot(SNAPSHOT, 'technical')
    previous_trades = snapshot(SNAPSHOT + '^', 'trade-logs')
    current_trades = snapshot(SNAPSHOT, 'trade-logs')
    rows = technical['rows']
    if isinstance(rows, list):
        rows = {row['ticker']: row for row in rows}
    with patch.object(logs, 'datetime', HistoricalClock):
        logs.repair_unqualified_buy_opinions(current['rows'], rows, current_trades['rows'], HistoricalClock.now().date())
    technical['rows'] = rows
    with TemporaryDirectory() as temp:
        paths = {}
        for name, payload in [('previous', previous), ('current', current), ('technical', technical),
                              ('previous_trades', previous_trades), ('current_trades', current_trades)]:
            paths[name] = Path(temp) / (name + '.json')
            paths[name].write_text(json.dumps(payload, ensure_ascii=False))
        with patch.object(mail, 'runtime_reset_state', return_value={}):
            changes = mail.opinion_changes(paths['previous'], paths['current'], paths['technical'],
                                          paths['previous_trades'], paths['current_trades'])
    changes = [change for change in changes if change['ticker'] in TICKERS]
    assert len(changes) == 12 and {c['ticker'] for c in changes} == TICKERS - {'QLD'}
    assert all(c['to'] == '관망' for c in changes)
    assert all('entryNote' not in c for c in changes)
    stocks = {r['ticker']: r for r in current['rows']}
    buy, watch, sell = mail.opinion_groups_for_tickers(stocks, TICKERS, set())
    # Candidate QLD was never funded; exclude it from the actual sell summary.
    sell = []
    with patch.object(mail, 'now_labels', return_value=('2026-10-26 18:00 (당시 기준)', '2026-10-26 05:00 (당시 기준)')):
        body = mail.opinion_email_body(changes, buy, watch, sell)
    body = '<p style="font-size:13px;color:#666">[임시 확인용] 2026년 10월 26일 18시의 13개 항목을 수정된 기준으로 재구성했습니다. 현재 매매 안내가 아닙니다.</p>' + body
    assert '신규 진입' not in body and '권장 매도가:' not in body
    return changes, body


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--output', default='/tmp/opinion-email-preview.html')
    args = parser.parse_args()
    changes, body = build_preview()
    Path(args.output).write_text(body, encoding='utf-8')
    for change in changes:
        print(change['ticker'], change['from'], '→', change['to'], change['reason'])
    if args.send:
        recipients = [r for r in mail.load_recipients() if r.is_admin and r.investment_type == 'swing']
        if len(recipients) != 1 or not recipients[0].email:
            raise RuntimeError('Expected exactly one swing administrator email recipient')
        recipient = recipients[0]
        result = mail.send_email(recipient.email, '[임시 확인용] 투자의견 변경 12개 항목 · 10/26 18시 기준', body)
        print('Preview email accepted:', mail.masked_email(recipient.email), result)
