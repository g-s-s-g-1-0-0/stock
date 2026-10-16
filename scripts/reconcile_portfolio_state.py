"""Repair allocation/status and stale buy opinions without fetching prices or sending mail."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import record_web_api_logs as logs
from calculator.account_allocation import load_allocation_accounts, reconcile_account_trades


def main():
    if not logs.supabase_url() or not logs.service_key():
        raise RuntimeError('Account settings access is required for live reconciliation')
    settings, operator = load_allocation_accounts(logs.supabase_request)
    stock_payload = logs.load_json(logs.STOCK_PUBLIC_PATH, {})
    technical_payload = logs.load_json(logs.TECHNICAL_PUBLIC_PATH, {})
    stocks = stock_payload.get('rows', [])
    technical = technical_payload.get('rows', {})
    trends = logs.account_trend_rows()
    payload = logs.load_json(logs.TRADE_LOG_PUBLIC_PATH, {'rows': []})
    payload['rows'] = reconcile_account_trades(payload['rows'], stocks, operator, trends)
    today = datetime.now(timezone.utc).astimezone(logs.KST).date()
    changed = logs.repair_unqualified_buy_opinions(stocks, technical, payload['rows'], today)
    changed = logs.sync_account_allocation_guidance(stocks, technical, payload['rows']) or changed
    logs.write_trade_logs(payload)
    if changed:
        for path in [logs.STOCK_CACHE_PATH, logs.STOCK_PUBLIC_PATH]:
            path.write_text(json.dumps(stock_payload, ensure_ascii=False, indent=2) + '\n')
        for path in [logs.TECHNICAL_CACHE_PATH, logs.TECHNICAL_PUBLIC_PATH]:
            path.write_text(json.dumps(technical_payload, ensure_ascii=False, indent=2) + '\n')
    updated = 0
    for owner, trades in logs.load_personal_trade_log_rows().items():
        if owner not in settings:
            continue
        next_trades = reconcile_account_trades(trades, stocks, settings[owner], trends)
        if next_trades == trades:
            continue
        before = {logs.trade_key(t): logs.serialize_trade(t) for t in trades}
        merged = logs.merge_personal_engine_result(owner, before, next_trades)
        logs.supabase_request(f'/rest/v1/user_settings?owner_id=eq.{owner}', method='PATCH',
                              payload={'personal_trade_logs': merged})
        updated += 1
    # Only aggregate operational evidence; no account identifiers in workflow logs.
    print(f'Reconciled public rows={len(payload["rows"])} personal portfolios={updated} repaired opinions={changed}')
    for row in payload['rows']:
        if row.get('ticker') in {'QQQ', 'QLD', 'UBER'}:
            print(row['ticker'], row['status'], row.get('investmentAmount'), row.get('allocationReason'))


if __name__ == '__main__':
    main()
