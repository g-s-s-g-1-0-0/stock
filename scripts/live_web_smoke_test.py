"""Live smoke test for web trade-log and notification flows.

This script is safe to run from GitHub Actions: it uses real environment
variables and the real email provider, but all cache/trade-log writes go to a
temporary directory instead of production files.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import record_web_api_logs as logs
from scripts import web_refresh_notifications as notifications


def fail(message: str) -> None:
    raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        fail(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value: Any, label: str) -> None:
    if not value:
        fail(f"{label}: expected truthy value, got {value!r}")


def trade_date(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc).astimezone(logs.KST).date() - timedelta(days=days_ago)).strftime("%Y.%m.%d")


def iso_days_ago(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(logs.json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_trade_case(name: str, initial_rows: list[dict[str, Any]], callback: Callable[[dict[str, Any]], None]) -> None:
    with tempfile.TemporaryDirectory(prefix=f"web-smoke-{name}-") as temp_dir:
        temp_path = Path(temp_dir)
        original_cache = logs.TRADE_LOG_CACHE_PATH
        original_public = logs.TRADE_LOG_PUBLIC_PATH
        logs.TRADE_LOG_CACHE_PATH = temp_path / "data" / "cache" / "trade-logs.json"
        logs.TRADE_LOG_PUBLIC_PATH = temp_path / "web" / "public" / "api" / "trade-logs.json"
        try:
            write_json(logs.TRADE_LOG_PUBLIC_PATH, {"rows": initial_rows})
            callback(logs.load_json(logs.TRADE_LOG_CACHE_PATH, {}))
        finally:
            logs.TRADE_LOG_CACHE_PATH = original_cache
            logs.TRADE_LOG_PUBLIC_PATH = original_public


def refresh_trade_logs(stocks: list[dict[str, Any]], technical: dict[str, Any], qqq_state: dict[str, Any] | None = None) -> dict[str, Any]:
    logs.update_trade_logs(stocks, {}, technical, qqq_state or {"peakTriggered": False})
    return logs.load_json(logs.TRADE_LOG_CACHE_PATH, {})


def check_new_buy_slots() -> None:
    def scenario(_: dict[str, Any]) -> None:
        updated = refresh_trade_logs(
            [{"ticker": "SMOKEBUY", "name": "Smoke Buy", "market": "US", "currentPrice": "$100.00", "opinion": "매수"}],
            {"SMOKEBUY": {"entrySignalCodes": "A,D", "현재가": "$100.00"}},
        )
        rows = updated["rows"]
        assert_equal(len(rows), 2, "new buy creates two strategy slots")
        assert_equal(updated["meta"]["appendedOpenTrades"], 2, "new buy appended count")

    run_trade_case("new-buy", [], scenario)


def check_same_signal_does_not_duplicate() -> None:
    def scenario(_: dict[str, Any]) -> None:
        updated = refresh_trade_logs(
            [{"ticker": "SMOKEDUP", "name": "Smoke Duplicate", "market": "US", "currentPrice": "$101.00", "opinion": "매수"}],
            {"SMOKEDUP": {"entrySignalCodes": "D", "현재가": "$101.00"}},
        )
        open_rows = [row for row in updated["rows"] if row.get("status") == "보유 중"]
        assert_equal(len(open_rows), 1, "same ongoing signal does not duplicate")
        assert_equal(updated["meta"]["appendedOpenTrades"], 0, "duplicate appended count")

    run_trade_case("no-duplicate", [{
        "ticker": "SMOKEDUP",
        "strategy": "D. 200일선 상방 & 상승 흐름 강화",
        "buyDate": trade_date(7),
        "buyPrice": "$100.00",
        "currentPrice": "$101.00",
        "sellDate": "보유 중",
        "sellPrice": "-",
        "returnPct": 0,
        "holdingDays": "-",
        "status": "보유 중",
    }], scenario)


def check_same_strategy_restore_reentry() -> None:
    def scenario(_: dict[str, Any]) -> None:
        updated = refresh_trade_logs(
            [{"ticker": "SMOKERE", "name": "Smoke Reentry", "market": "US", "currentPrice": "$97.00", "opinion": "매수"}],
            {"SMOKERE": {"entrySignalCodes": "D", "현재가": "$97.00"}},
        )
        open_rows = [row for row in updated["rows"] if row.get("status") == "보유 중"]
        assert_equal(len(open_rows), 2, "same strategy restore opens an additional slot")
        assert_true(open_rows[-1].get("slotId"), "restored slot has slotId")
        assert_equal(updated["meta"]["appendedOpenTrades"], 1, "restore appended count")

    run_trade_case("restore-reentry", [{
        "ticker": "SMOKERE",
        "strategy": "D. 200일선 상방 & 상승 흐름 강화",
        "buyDate": trade_date(8),
        "buyPrice": "$100.00",
        "currentPrice": "$97.00",
        "restoreWatchDate": trade_date(5),
        "sellDate": "보유 중",
        "sellPrice": "-",
        "returnPct": 0,
        "holdingDays": "-",
        "status": "보유 중",
    }], scenario)


def check_exit_and_same_run_cooldown() -> None:
    def scenario(_: dict[str, Any]) -> None:
        updated = refresh_trade_logs(
            [{"ticker": "SMOKESELL", "name": "Smoke Sell", "market": "US", "currentPrice": "$130.00", "opinion": "매수"}],
            {"SMOKESELL": {"entrySignalCodes": "D", "현재가": "$130.00"}},
        )
        rows = updated["rows"]
        assert_equal(len(rows), 1, "same-run sell does not reopen")
        assert_equal(rows[0]["status"], "익절", "target exit closes trade")
        assert_true(rows[0].get("sellTimestamp"), "closed trade has sell timestamp")
        assert_equal(updated["meta"]["closedTrades"], 1, "closed count")
        assert_equal(updated["meta"]["appendedOpenTrades"], 0, "same-run reentry blocked")

    run_trade_case("exit-cooldown", [{
        "ticker": "SMOKESELL",
        "strategy": "D. 200일선 상방 & 상승 흐름 강화",
        "buyDate": trade_date(8),
        "buyPrice": "$100.00",
        "currentPrice": "$130.00",
        "sellDate": "보유 중",
        "sellPrice": "-",
        "returnPct": 0,
        "holdingDays": "-",
        "status": "보유 중",
    }], scenario)


def check_closed_reentry_filters() -> None:
    def scenario(_: dict[str, Any]) -> None:
        blocked = refresh_trade_logs(
            [{"ticker": "SMOKECOOL", "name": "Smoke Cooldown", "market": "US", "currentPrice": "$99.00", "opinion": "매수"}],
            {"SMOKECOOL": {"entrySignalCodes": "D", "현재가": "$99.00"}},
        )
        assert_equal(blocked["meta"]["appendedOpenTrades"], 0, "48-hour cooldown blocks reentry")

    run_trade_case("cooldown-block", [{
        "ticker": "SMOKECOOL",
        "strategy": "D. 200일선 상방 & 상승 흐름 강화",
        "buyDate": trade_date(8),
        "buyPrice": "$100.00",
        "sellDate": trade_date(1),
        "sellTimestamp": iso_days_ago(1),
        "sellPrice": "$100.00",
        "returnPct": 0,
        "holdingDays": "-",
        "status": "손절",
    }], scenario)

    def drop_scenario(_: dict[str, Any]) -> None:
        allowed = refresh_trade_logs(
            [{"ticker": "SMOKEDROP", "name": "Smoke Drop", "market": "US", "currentPrice": "$96.00", "opinion": "매수"}],
            {"SMOKEDROP": {"entrySignalCodes": "D", "현재가": "$96.00"}},
        )
        assert_equal(allowed["meta"]["appendedOpenTrades"], 1, "10-day reentry allows -3 percent drop")

    run_trade_case("cooldown-drop", [{
        "ticker": "SMOKEDROP",
        "strategy": "D. 200일선 상방 & 상승 흐름 강화",
        "buyDate": trade_date(15),
        "buyPrice": "$100.00",
        "sellDate": trade_date(5),
        "sellTimestamp": iso_days_ago(5),
        "sellPrice": "$100.00",
        "returnPct": 0,
        "holdingDays": "-",
        "status": "손절",
    }], drop_scenario)


def check_nasdaq_peak_price_fallback() -> None:
    def scenario(_: dict[str, Any]) -> None:
        updated = refresh_trade_logs([], {}, {"peakTriggered": True})
        row = updated["rows"][0]
        assert_equal(row["sellPrice"], "$120.00", "nasdaq peak uses existing price")
        assert_equal(row["status"], "익절", "nasdaq peak closes trade")
        assert_equal(updated["meta"]["nasdaqPeakLiquidation"], True, "nasdaq peak meta")

    run_trade_case("peak-fallback", [{
        "ticker": "SMOKEPEAK",
        "strategy": "A. 200일선 상방 & 모멘텀 재가속",
        "buyDate": trade_date(8),
        "buyPrice": "$100.00",
        "currentPrice": "$120.00",
        "sellDate": "보유 중",
        "sellPrice": "-",
        "returnPct": 0,
        "holdingDays": "-",
        "status": "보유 중",
    }], scenario)


def smoke_recipient() -> notifications.Recipient:
    explicit = os.environ.get("LIVE_SMOKE_EMAIL_TO", "").strip()
    admin = next((email.strip() for email in os.environ.get("ADMIN_EMAILS", "").split(",") if email.strip()), "")
    email = explicit or admin
    if not email:
        fail("LIVE_SMOKE_EMAIL_TO or ADMIN_EMAILS is required for live email smoke test.")
    return notifications.Recipient(
        owner_id="live-smoke",
        email=email,
        is_admin=True,
        preferences={
            "opinionChangeEmail": True,
            "nasdaqPeakEmail": True,
            "weeklyTrendReport": False,
            "earningsDayBefore": False,
            "adminAutoUpdateFailureEmail": True,
        },
    )


def check_live_email_notifications() -> None:
    if os.environ.get("LIVE_SMOKE_SEND_EMAIL", "true").lower() not in {"1", "true", "yes", "y"}:
        print("[smoke] LIVE_SMOKE_SEND_EMAIL=false, email send skipped.")
        return

    recipient = smoke_recipient()
    original_load_recipients = notifications.load_recipients
    notifications.load_recipients = lambda: [recipient]
    try:
        with tempfile.TemporaryDirectory(prefix="web-smoke-email-") as temp_dir:
            temp_path = Path(temp_dir)
            previous_stocks = temp_path / "stocks.before.json"
            current_stocks = temp_path / "stocks.after.json"
            technical = temp_path / "technical.json"
            previous_trades = temp_path / "trade.before.json"
            current_trades = temp_path / "trade.after.json"

            write_json(previous_stocks, {"rows": [
                {"ticker": "SMOKEMAILBUY", "name": "Smoke Mail Buy", "opinion": "관망"},
                {"ticker": "SMOKEMAILWATCH1", "name": "Smoke Mail Buy To Watch", "opinion": "매수"},
                {"ticker": "SMOKEMAILWATCH2", "name": "Smoke Mail Sell To Watch", "opinion": "매도"},
                {"ticker": "SMOKEMAILSELLSTATE", "name": "Smoke Mail Watch To Sell", "opinion": "관망"},
            ]})
            write_json(current_stocks, {"rows": [
                {"ticker": "SMOKEMAILBUY", "name": "Smoke Mail Buy", "opinion": "매수", "currentPrice": "$100.00", "valuation": "-", "industry": "-", "strategies": ["D. 200일선 상방 & 상승 흐름 강화"]},
                {"ticker": "SMOKEMAILWATCH1", "name": "Smoke Mail Buy To Watch", "opinion": "관망", "currentPrice": "$98.00", "valuation": "-", "industry": "-"},
                {"ticker": "SMOKEMAILWATCH2", "name": "Smoke Mail Sell To Watch", "opinion": "관망", "currentPrice": "$97.00", "valuation": "-", "industry": "-"},
                {"ticker": "SMOKEMAILSELLSTATE", "name": "Smoke Mail Watch To Sell", "opinion": "매도", "currentPrice": "$90.00", "valuation": "-", "industry": "-"},
            ]})
            write_json(technical, {"rows": {
                "SMOKEMAILBUY": {"conditionSummary": "[LIVE SMOKE] 관망→매수 알림 경로 검증"},
                "SMOKEMAILWATCH1": {"conditionSummary": "[LIVE SMOKE] 매수→관망 알림 경로 검증"},
                "SMOKEMAILWATCH2": {"conditionSummary": "[LIVE SMOKE] 매도→관망 알림 경로 검증"},
                "SMOKEMAILSELLSTATE": {"conditionSummary": "[LIVE SMOKE] 관망→매도 알림 경로 검증"},
            }})
            write_json(previous_trades, {"rows": [{"slotId": "smoke-exit-slot", "ticker": "SMOKEMAILSELL", "name": "Smoke Mail Sell", "strategy": "D. 200일선 상방 & 상승 흐름 강화", "buyDate": trade_date(8), "buyPrice": "$100.00", "status": "보유 중"}]})
            write_json(current_trades, {"rows": [{"slotId": "smoke-exit-slot", "ticker": "SMOKEMAILSELL", "name": "Smoke Mail Sell", "strategy": "D. 200일선 상방 & 상승 흐름 강화", "buyDate": trade_date(8), "buyPrice": "$100.00", "sellDate": trade_date(), "sellPrice": "$115.00", "returnPct": 15.0, "status": "익절", "exitReason": "[LIVE SMOKE] 매도 전환 알림 경로 검증"}]})

            original_default_technical = notifications.DEFAULT_TECHNICAL
            notifications.DEFAULT_TECHNICAL = technical
            try:
                opinion_sent = notifications.send_opinion_notifications(previous_stocks, current_stocks)
            finally:
                notifications.DEFAULT_TECHNICAL = original_default_technical
            exit_sent = notifications.send_trade_exit_notifications(previous_trades, current_trades)

        assert_equal(opinion_sent, 1, "live opinion email sent")
        assert_equal(exit_sent, 1, "live trade exit email sent")
        print(f"[smoke] live emails sent to {recipient.email}")
    finally:
        notifications.load_recipients = original_load_recipients


def main() -> int:
    checks = [
        check_new_buy_slots,
        check_same_signal_does_not_duplicate,
        check_same_strategy_restore_reentry,
        check_exit_and_same_run_cooldown,
        check_closed_reentry_filters,
        check_nasdaq_peak_price_fallback,
        check_live_email_notifications,
    ]
    for check in checks:
        print(f"[smoke] running {check.__name__}")
        check()
    print("[smoke] all live web smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
