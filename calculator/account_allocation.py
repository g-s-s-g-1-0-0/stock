"""Run the same account allocation engine used by the browser; no duplicated rules."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def reconcile_account_trades(trades: list[dict[str, Any]], stocks: list[dict[str, Any]],
                             settings: dict[str, Any], trends: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    payload = {"trades": trades, "stocks": stocks, "settings": settings, "trends": trends or []}
    result = subprocess.run(
        ["node", str(ROOT / "scripts/account_allocation.mjs")],
        input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)


def load_allocation_accounts(request):
    rows = request('/rest/v1/user_settings?select=owner_id,contribution_settings')
    settings = {r['owner_id']: r.get('contribution_settings') or {} for r in rows or [] if r.get('owner_id')}
    profiles = request('/rest/v1/profiles?select=id,is_admin')
    admins = sorted(r['id'] for r in profiles or [] if r.get('is_admin') and r.get('id'))
    # The public operator portfolio has one owner; use the first configured admin deterministically.
    operator = next((settings[owner] for owner in admins if settings.get(owner)), {})
    return settings, operator
