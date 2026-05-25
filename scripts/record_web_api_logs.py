"""Record stock-level web refresh logs in Supabase api_logs."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from calculator.rules import IndicatorRow, evaluate_exit_condition, strategy_display_name


API_DIR = ROOT_DIR / "web" / "public" / "api"
PREVIOUS_STOCKS_PATH = Path(
    os.environ.get("PREVIOUS_STOCKS_PATH", str(ROOT_DIR / "data" / "cache" / "stocks.before-refresh.json"))
)
STOCK_CACHE_PATH = ROOT_DIR / "data" / "cache" / "stocks.json"
STOCK_PUBLIC_PATH = API_DIR / "stocks.json"
TECHNICAL_CACHE_PATH = ROOT_DIR / "data" / "cache" / "technical.json"
TECHNICAL_PUBLIC_PATH = API_DIR / "technical.json"
TRADE_LOG_CACHE_PATH = ROOT_DIR / "data" / "cache" / "trade-logs.json"
TRADE_LOG_PUBLIC_PATH = API_DIR / "trade-logs.json"
RUNTIME_STATE_PATH = ROOT_DIR / "data" / "cache" / "web-notification-state.json"
MAX_LOG_ROWS = 80
OPERATION_LOG_RETENTION_DAYS = int(os.environ.get("OPERATION_LOG_RETENTION_DAYS", "7"))
VALID_TASKS = {"value-analysis", "technical-analysis", "market-trends"}
KST = ZoneInfo("Asia/Seoul")
SELL_HOLD_DAYS = 2
REENTRY_DAYS = 10
REENTRY_DROP = 0.03
HOLD_RESTORE_DROP = 0.10
HOLD_RESTORE_MIN_TRADING_DAYS = 10
HOLD_RESTORE_SIGNAL_CONFIRMATIONS = 2
MAX_OPEN_PER_STRATEGY = 2
RESTORE_FAMILY_STRATEGIES = {"E", "F"}
VALUATION_LOG_FIELDS = [
    ("marketCap", "시가총액"),
    ("sales", "매출"),
    ("salesQoq", "매출 Q/Q"),
    ("salesYoyTtm", "매출 Y/Y(TTM)"),
    ("salesPastYears", "매출 3/5년"),
    ("currentRatio", "유동비율"),
    ("debtToEquity", "부채비율"),
    ("priceToFreeCashFlow", "P/FCF"),
    ("priceToSales", "P/S"),
    ("per", "PER"),
    ("pbr", "PBR"),
    ("roe", "ROE"),
    ("peg", "PEG"),
    ("sharesOutstanding", "상장주식수"),
    ("grossMargin", "매출총이익률"),
    ("operatingMargin", "영업이익률"),
    ("epsTtm", "EPS(TTM)"),
    ("epsNextYear", "EPS Next Y"),
    ("epsQoq", "EPS Q/Q"),
    ("ruleOf40", "Rule of 40"),
    ("earningsDate", "실적발표일"),
    ("valuationIndustry", "가치분석 산업"),
]


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def service_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def publish_iso(default: str | None = None) -> str:
    raw_publish_at = os.environ.get("WEB_REFRESH_PUBLISH_AT", "").strip()
    if not raw_publish_at:
        return default or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        publish_at = datetime.fromisoformat(raw_publish_at.replace("Z", "+00:00"))
    except ValueError:
        return default or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return publish_at.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def supabase_request(path: str, method: str = "GET", payload: Any | None = None) -> Any | None:
    url = supabase_url()
    key = service_key()
    if not url or not key:
        print("[api_logs] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing; skipped.")
        return None

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url + path,
        data=body,
        method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    if method == "GET" and raw:
        return json.loads(raw.decode("utf-8"))
    return None


def clean_old_logs() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=OPERATION_LOG_RETENTION_DAYS)).isoformat().replace("+00:00", "Z")
    try:
        supabase_request(f"/rest/v1/api_logs?created_at=lt.{cutoff}", method="DELETE")
    except (HTTPError, URLError, TimeoutError) as error:
        # Cleanup should never block recording the current refresh result.
        print(f"[api_logs] old-log cleanup failed; continuing: {error}")


def runtime_reset_requested() -> bool:
    state = load_json(RUNTIME_STATE_PATH, {})
    reset = state.get("runtimeReset") if isinstance(state, dict) else None
    return isinstance(reset, dict) and reset.get("seedNextRefresh") is True


def reset_api_logs() -> None:
    try:
        supabase_request("/rest/v1/api_logs?created_at=not.is.null", method="DELETE")
        print("[api_logs] runtime reset cleared existing operation logs.")
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"[api_logs] runtime reset cleanup failed; continuing: {error}")


def load_watchlist_tickers(stocks: list[dict[str, Any]]) -> list[str]:
    rows = supabase_request("/rest/v1/watchlists?select=tickers&scope=eq.operator&owner_id=is.null")
    tickers: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            values = row.get("tickers") if isinstance(row, dict) else None
            if not isinstance(values, list):
                continue
            for value in values:
                ticker = str(value or "").strip().upper()
                if ticker and ticker not in tickers:
                    tickers.append(ticker)
    if tickers:
        return tickers[:MAX_LOG_ROWS]
    if os.environ.get("SUPABASE_URL", "").strip() and os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip():
        return []

    tickers = [
        str(stock.get("ticker", "")).strip().upper()
        for stock in stocks
        if str(stock.get("ticker", "")).strip()
    ]
    return tickers[:MAX_LOG_ROWS]


def stocks_by_ticker(stocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(stock.get("ticker", "")).strip().upper(): stock
        for stock in stocks
        if str(stock.get("ticker", "")).strip()
    }


def kst_trade_date() -> str:
    return datetime.now(timezone.utc).astimezone(KST).strftime("%Y.%m.%d")


def trade_key(trade: dict[str, Any]) -> tuple[str, str, str]:
    slot_id = str(trade.get("slotId") or "").strip()
    if slot_id:
        return (
            str(trade.get("ticker") or "").strip().upper(),
            slot_id,
            strategy_code(trade.get("strategy")),
        )
    return (
        str(trade.get("ticker") or "").strip().upper(),
        str(trade.get("buyDate") or "").strip(),
        strategy_code(trade.get("strategy")),
    )


def open_trade_slots(trades: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (
            str(trade.get("ticker") or "").strip().upper(),
            strategy_code(trade.get("strategy")),
        )
        for trade in trades
        if str(trade.get("status") or "") == "보유 중"
    }


def open_trade_counts(trades: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for trade in trades:
        if str(trade.get("status") or "") != "보유 중":
            continue
        key = (
            str(trade.get("ticker") or "").strip().upper(),
            strategy_code(trade.get("strategy")),
        )
        if not key[0] or not key[1]:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def open_trades_by_slot(trades: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for trade in trades:
        if str(trade.get("status") or "") != "보유 중":
            continue
        key = (
            str(trade.get("ticker") or "").strip().upper(),
            strategy_code(trade.get("strategy")),
        )
        if not key[0] or not key[1]:
            continue
        grouped.setdefault(key, []).append(trade)
    return grouped


def open_trades_by_ticker(trades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        if str(trade.get("status") or "") != "보유 중":
            continue
        ticker = str(trade.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        grouped.setdefault(ticker, []).append(trade)
    return grouped


def parse_price(value: Any) -> float | None:
    cleaned = "".join(char for char in str(value or "") if char.isdigit() or char in ".-")
    try:
        return float(cleaned)
    except ValueError:
        return None


def return_pct(buy_price: Any, sell_price: Any) -> float:
    buy = parse_price(buy_price)
    sell = parse_price(sell_price)
    if not buy or sell is None:
        return 0.0
    return round(((sell - buy) / buy) * 100, 2)


def target_return_pct(strategy: str) -> float:
    code = strategy_code(strategy)
    if code in {"D", "G"}:
        return 12.0
    if code in {"A", "B", "C", "E", "F"}:
        return 20.0
    return 20.0


def trade_status_for_exit(trade: dict[str, Any], result: float) -> str:
    if result <= 0:
        return "손절"
    return "익절" if result >= target_return_pct(str(trade.get("strategy") or "")) else "실패 익절"


def strategy_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    first = text.split(".", 1)[0].strip().upper()
    if first in {"A", "B", "C", "D", "E", "F", "G"}:
        return first
    upper = text.upper()
    return upper[0] if upper[:1] in {"A", "B", "C", "D", "E", "F", "G"} else ""


def entry_signal_codes(row: dict[str, Any]) -> list[str]:
    raw = row.get("entrySignalCodes")
    if isinstance(raw, list):
        values = raw
    else:
        values = str(raw or row.get("entryStrategy") or "").replace("/", ",").split(",")
    codes: list[str] = []
    for value in values:
        code = strategy_code(value)
        if code and code not in codes:
            codes.append(code)
    return codes


def parse_trade_date(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_trade_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)
    except ValueError:
        parsed_date = parse_trade_date(text)
        if parsed_date is None:
            return None
        return datetime.combine(parsed_date, datetime.min.time(), tzinfo=KST)


def trading_days_since(start: Any, end: date) -> int:
    start_date = parse_trade_date(start)
    if start_date is None or start_date >= end:
        return 0
    days = 0
    current = start_date + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def latest_closed_trade(trades: list[dict[str, Any]], ticker: str, strategy: str) -> dict[str, Any] | None:
    matches = [
        trade
        for trade in trades
        if str(trade.get("status") or "") != "보유 중"
        and str(trade.get("ticker") or "").strip().upper() == ticker
        and strategy_code(trade.get("strategy")) == strategy
        and parse_trade_date(trade.get("sellDate")) is not None
    ]
    if not matches:
        return None
    return max(matches, key=lambda trade: parse_trade_date(trade.get("sellDate")) or date.min)


def sell_reentry_allowed(closed_trade: dict[str, Any] | None, current_price: float | None, today_date: date) -> bool:
    if not closed_trade:
        return True
    sell_date = parse_trade_date(closed_trade.get("sellDate"))
    if sell_date is None:
        return True
    sell_time = parse_trade_datetime(closed_trade.get("sellTimestamp")) or parse_trade_datetime(closed_trade.get("sellDate"))
    now = datetime.now(timezone.utc).astimezone(KST)
    if sell_time and (now - sell_time.astimezone(KST)).total_seconds() < SELL_HOLD_DAYS * 24 * 60 * 60:
        return False
    sell_price = parse_price(closed_trade.get("sellPrice"))
    if trading_days_since(closed_trade.get("sellDate"), today_date) <= REENTRY_DAYS:
        return bool(sell_price and current_price is not None and current_price <= sell_price * (1 - REENTRY_DROP))
    return True


def mark_restore_watch(trade: dict[str, Any], today: str) -> None:
    trade.setdefault("restoreWatchDate", today)


def hold_restore_allowed(trade: dict[str, Any], current_price: float | None, today_date: date) -> bool:
    watch_date = parse_trade_date(trade.get("restoreWatchDate"))
    entry_price = parse_price(trade.get("buyPrice"))
    drop_ok = bool(entry_price and current_price is not None and current_price <= entry_price * (1 - HOLD_RESTORE_DROP))
    days_ok = bool(
        watch_date
        and trading_days_since(trade.get("restoreWatchDate"), today_date) >= HOLD_RESTORE_MIN_TRADING_DAYS
    )
    return drop_ok and days_ok


def restore_signal_counts(trade: dict[str, Any]) -> dict[str, int]:
    raw_counts = trade.get("restoreSignalCounts")
    if not isinstance(raw_counts, dict):
        return {}
    counts: dict[str, int] = {}
    for raw_strategy, raw_count in raw_counts.items():
        strategy = strategy_code(raw_strategy)
        if not strategy:
            continue
        try:
            counts[strategy] = int(raw_count)
        except (TypeError, ValueError):
            continue
    return counts


def set_restore_signal_count(trade: dict[str, Any], strategy: str, count: int) -> None:
    counts = restore_signal_counts(trade)
    strategy = strategy_code(strategy)
    if not strategy:
        return
    if count <= 0:
        counts.pop(strategy, None)
    else:
        counts[strategy] = count
    if counts:
        trade["restoreSignalCounts"] = counts
    else:
        trade.pop("restoreSignalCounts", None)


def confirm_restore_signal(trade: dict[str, Any], strategy: str) -> bool:
    strategy = strategy_code(strategy)
    if not strategy:
        return False
    count = restore_signal_counts(trade).get(strategy, 0) + 1
    set_restore_signal_count(trade, strategy, count)
    return count >= HOLD_RESTORE_SIGNAL_CONFIRMATIONS


def clear_stale_restore_signal_counts(trade: dict[str, Any], active_codes: set[str]) -> None:
    counts = restore_signal_counts(trade)
    if not counts:
        return
    next_counts = {strategy: count for strategy, count in counts.items() if strategy in active_codes}
    if next_counts:
        trade["restoreSignalCounts"] = next_counts
    else:
        trade.pop("restoreSignalCounts", None)


def restore_family_open_trades(
    current_open_trades: dict[tuple[str, str], list[dict[str, Any]]],
    ticker: str,
    strategy: str,
) -> list[dict[str, Any]]:
    if strategy not in RESTORE_FAMILY_STRATEGIES:
        return []
    trades: list[dict[str, Any]] = []
    for family_strategy in RESTORE_FAMILY_STRATEGIES:
        if family_strategy == strategy:
            continue
        trades.extend(current_open_trades.get((ticker, family_strategy), []))
    return trades


def next_slot_id(ticker: str, strategy: str, trades: list[dict[str, Any]], today: str) -> str:
    prefix = f"{ticker}_{strategy}_{today.replace('.', '')}_"
    count = sum(1 for trade in trades if str(trade.get("slotId") or "").startswith(prefix))
    return f"{prefix}{count + 1}"


def indicator_from_trade(row: dict[str, Any], trade: dict[str, Any], current_price: Any) -> IndicatorRow | None:
    price = parse_price(current_price) or parse_price(row.get("현재가")) or parse_price(row.get("C - Close"))
    entry_price = parse_price(trade.get("buyPrice"))
    if price is None or entry_price is None:
        return None
    return IndicatorRow(
        stock_name=str(trade.get("ticker") or row.get("ticker") or ""),
        current_price=price,
        ma200=parse_price(row.get("200일 이동평균선")),
        rsi=parse_price(row.get("RSI (D)")),
        cci=parse_price(row.get("CCI (D)")),
        macd_hist=parse_price(row.get("MACD Histogram (D)")),
        macd_hist_d1=parse_price(row.get("M - H (D-1)")),
        macd_hist_d2=parse_price(row.get("M - H (D-2)")),
        pct_b=parse_price(row.get("볼린저밴드 %B (종가)")),
        pct_b_low=parse_price(row.get("볼린저밴드 %B (저가)")),
        bb_width=parse_price(row.get("볼린저밴드 폭 (D)")),
        bb_width_d1=parse_price(row.get("볼린저밴드 폭 (D-1)")),
        bb_width_avg60=parse_price(row.get("지난 60일 볼린저밴드 폭 평균")),
        plus_di=parse_price(row.get("+DI (DMI, 14)")),
        minus_di=parse_price(row.get("-DI (DMI, 14)")),
        adx=parse_price(row.get("ADX (14, D)")),
        adx_d1=parse_price(row.get("ADX (14, D-1)")),
        entry_price=entry_price,
    )


def close_trade(
    trade: dict[str, Any],
    *,
    sell_price: Any,
    today: str,
    reason: str,
) -> None:
    result = return_pct(trade.get("buyPrice"), sell_price)
    trade["sellDate"] = today
    trade["sellTimestamp"] = publish_iso()
    trade["sellPrice"] = sell_price or "-"
    trade["returnPct"] = result
    trade["holdingDays"] = "-"
    trade["status"] = trade_status_for_exit(trade, result)
    trade["exitReason"] = reason
    trade.pop("upperExitArmedDate", None)
    trade.pop("restoreWatchDate", None)


def write_trade_logs(payload: dict[str, Any]) -> None:
    for path in (TRADE_LOG_CACHE_PATH, TRADE_LOG_PUBLIC_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_stock_payload(payload: dict[str, Any]) -> None:
    for path in (STOCK_CACHE_PATH, STOCK_PUBLIC_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_technical_payload(payload: dict[str, Any]) -> None:
    for path in (TECHNICAL_CACHE_PATH, TECHNICAL_PUBLIC_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def suppress_held_buy_signal(stock: dict[str, Any], technical_row: dict[str, Any]) -> bool:
    changed = False
    if stock.get("opinion") != "관망":
        stock["opinion"] = "관망"
        changed = True
    if stock.get("opinionReason") != "보유 중 추가매수 조건 미충족":
        stock["opinionReason"] = "보유 중 추가매수 조건 미충족"
        changed = True
    if stock.get("strategies") != []:
        stock["strategies"] = []
        changed = True

    updates = {
        "opinion": "관망",
        "opinionReason": "보유 중 추가매수 조건 미충족",
        "entryStrategy": "-",
        "entrySignalCodes": "",
        "entrySignals": "",
    }
    for key, value in updates.items():
        if technical_row.get(key) != value:
            technical_row[key] = value
            changed = True
    return changed


def update_trade_logs(
    stocks: list[dict[str, Any]],
    previous_stocks: dict[str, dict[str, Any]],
    technical: dict[str, Any],
    qqq_market_state: dict[str, Any] | None = None,
) -> bool:
    existing = load_json(TRADE_LOG_PUBLIC_PATH, load_json(TRADE_LOG_CACHE_PATH, {"rows": []}))
    rows = existing.get("rows", []) if isinstance(existing, dict) else []
    trades = [row for row in rows if isinstance(row, dict)]
    stocks_by_symbol = stocks_by_ticker(stocks)
    entry_tickers = set(load_watchlist_tickers(stocks))
    today = kst_trade_date()
    today_date = parse_trade_date(today) or datetime.now(timezone.utc).astimezone(KST).date()
    nasdaq_peak_alert = bool((qqq_market_state or {}).get("peakTriggered"))
    seed_after_reset = runtime_reset_requested()
    appended = 0
    closed = 0
    signal_state_changed = False

    for trade in trades:
        ticker = str(trade.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        stock = stocks_by_symbol.get(ticker, {})
        if stock:
            trade["name"] = stock.get("name") or trade.get("name") or ticker
            trade["market"] = stock.get("market") or trade.get("market") or "-"
            trade["currentPrice"] = stock.get("currentPrice") or trade.get("currentPrice") or "-"
        if str(trade.get("status") or "") != "보유 중":
            continue
        sell_price = stock.get("currentPrice") or trade.get("currentPrice") or "-"
        row = technical.get(ticker, {}) if isinstance(technical, dict) else {}
        ind = indicator_from_trade(row, trade, sell_price) if isinstance(row, dict) else None
        if ind is None and not nasdaq_peak_alert:
            continue
        entry_codes = set(entry_signal_codes(row)) if isinstance(row, dict) else set()
        armed_date = parse_trade_date(trade.get("upperExitArmedDate"))
        upper_wait_days = trading_days_since(armed_date.strftime("%Y.%m.%d"), today_date) if armed_date else None
        exit_result = evaluate_exit_condition(
            ind or IndicatorRow(stock_name=ticker, current_price=parse_price(sell_price) or 0, entry_price=parse_price(trade.get("buyPrice"))),
            strategy_type=strategy_code(trade.get("strategy")) or "A",
            nasdaq_peak_alert=nasdaq_peak_alert,
            trading_days=trading_days_since(trade.get("buyDate"), today_date),
            upper_exit_wait_days=upper_wait_days,
        )
        if exit_result["shouldExit"]:
            close_trade(trade, sell_price=sell_price, today=today, reason=str(exit_result.get("reason") or "시스템 매도"))
            closed += 1
            continue
        strategy = strategy_code(trade.get("strategy"))
        clear_stale_restore_signal_counts(trade, entry_codes)
        buy_price = parse_price(trade.get("buyPrice"))
        current_price = parse_price(sell_price)
        if strategy in {"E", "F"} and buy_price and current_price and current_price >= buy_price * 1.20:
            trade.setdefault("upperExitArmedDate", today)
        if strategy and strategy not in entry_codes:
            mark_restore_watch(trade, today)

    current_open_counts = open_trade_counts(trades)
    current_open_trades = open_trades_by_slot(trades)
    current_open_by_ticker = open_trades_by_ticker(trades)

    for stock in stocks:
        ticker = str(stock.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        if ticker not in entry_tickers:
            continue
        current_opinion = str(stock.get("opinion") or "").strip()
        previous_opinion = str(previous_stocks.get(ticker, {}).get("opinion") or "").strip()
        row = technical.get(ticker, {}) if isinstance(technical, dict) else {}
        if not isinstance(row, dict):
            continue
        if current_opinion != "매수" or nasdaq_peak_alert:
            continue
        current_price = parse_price(stock.get("currentPrice") or tech_value(row, "현재가"))
        open_for_ticker = current_open_by_ticker.get(ticker, [])
        restore_candidates = [
            trade
            for trade in open_for_ticker
            if hold_restore_allowed(trade, current_price, today_date)
        ]
        ticker_appended = False
        if open_for_ticker and not restore_candidates:
            signal_state_changed = suppress_held_buy_signal(stock, row) or signal_state_changed
            continue
        for code in entry_signal_codes(row):
            slot_key = (ticker, code)
            open_count = current_open_counts.get(slot_key, 0)
            restore_source_trades: list[dict[str, Any]] = []
            if open_count >= MAX_OPEN_PER_STRATEGY:
                continue
            if open_for_ticker:
                restore_source_trades = restore_candidates
            closed_trade = latest_closed_trade(trades, ticker, code)
            if not seed_after_reset and open_count == 0 and closed_trade is None and previous_opinion == "매수" and not restore_source_trades:
                continue
            if not sell_reentry_allowed(closed_trade, current_price, today_date):
                continue
            new_trade = {
                "slotId": next_slot_id(ticker, code, trades, today),
                "ticker": ticker,
                "name": stock.get("name") or ticker,
                "market": stock.get("market") or "-",
                "currentPrice": stock.get("currentPrice") or tech_value(row, "현재가"),
                "strategy": strategy_display_name(code),
                "buyDate": today,
                "buyPrice": stock.get("currentPrice") or tech_value(row, "현재가"),
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
            trades.append(new_trade)
            for trade in restore_source_trades:
                trade.pop("restoreWatchDate", None)
                set_restore_signal_count(trade, code, 0)
            current_open_counts[slot_key] = open_count + 1
            current_open_trades.setdefault(slot_key, []).append(new_trade)
            current_open_by_ticker.setdefault(ticker, []).append(new_trade)
            appended += 1
            ticker_appended = True
        if open_for_ticker and not ticker_appended:
            signal_state_changed = suppress_held_buy_signal(stock, row) or signal_state_changed

    deduped = list({trade_key(trade): trade for trade in trades}.values())
    refreshed_at = publish_iso()
    payload = {
        "meta": {
            "kind": "trade-logs",
            "schedule": "auto",
            "updatedAt": refreshed_at,
            "lastSuccessfulRun": refreshed_at,
            "failedReason": None,
            "appendedOpenTrades": appended,
            "closedTrades": closed,
            "nasdaqPeakLiquidation": nasdaq_peak_alert,
        },
        "rows": deduped,
    }
    write_trade_logs(payload)
    return signal_state_changed


def parse_log_tasks(argv: list[str]) -> set[str]:
    aliases = {
        "all": {"value-analysis", "technical-analysis", "market-trends"},
        "valuation": {"value-analysis"},
        "value-analysis": {"value-analysis"},
        "technical": {"technical-analysis"},
        "technical-analysis": {"technical-analysis"},
        "market-trends": {"market-trends"},
    }
    raw_values = argv or [os.environ.get("REFRESH_TASKS", "all")]
    tasks: set[str] = set()
    for raw in raw_values:
        for value in str(raw or "").replace(",", " ").split():
            if not value:
                continue
            matched = aliases.get(value)
            if matched is None:
                # stocks and market-events do not have separate operation-log tabs.
                if value in {"stocks", "market-events"}:
                    continue
                raise SystemExit(f"unknown log task: {value}")
            tasks.update(matched)
    return tasks or set(VALID_TASKS)


def meaningful_log_value(value: Any) -> bool:
    return str(value or "").strip() not in {"", "-"}


def log_mark(passed: bool) -> str:
    return "✅" if passed else "❌"


def checked_value(value: Any) -> str:
    return f"{log_mark(meaningful_log_value(value))} {value or '-'}"


def value_log_text(row: dict[str, Any]) -> str:
    header_parts = [
        f"{row.get('ticker') or '-'}",
        str(row.get("name") or "-"),
        str(row.get("market") or "-"),
    ]
    if row.get("industry"):
        header_parts.append(str(row["industry"]))

    metric_lines = [
        f"  {label}: {checked_value(row.get(key))}"
        for key, label in VALUATION_LOG_FIELDS
    ]
    can_judge = row.get("fairPriceReason") != "loss_making" and meaningful_log_value(row.get("fairPrice"))

    return "\n".join([
        f"====== {' | '.join(header_parts)} ======",
        "[요약]",
        f"  현재가: {row.get('currentPrice') or '-'}",
        f"  적정 주가 범위: {row.get('fairPrice') or '-'}",
        f"  가치 평가: {row.get('valuation') or '-'}",
        f"  투자의견: {row.get('opinion') or '-'}",
        f"  종목 분류: {row.get('category') or '-'}",
        f"  갱신: {row.get('updatedAt') or '-'}",
        "[판단]",
        f"  적정가 산정 가능: {log_mark(can_judge)}",
        f"  저평가 여부: {log_mark(row.get('valuation') == '저평가')} {row.get('valuation') or '-'}",
        f"  매수 의견 여부: {log_mark(row.get('opinion') == '매수')} {row.get('opinion') or '-'}",
        "[가치 지표]",
        *metric_lines,
        "[원본 추출값]",
        "  " + ",".join(str(row.get(key) or "-") for key, _ in VALUATION_LOG_FIELDS),
    ])


def value_log_rows(stocks: list[dict[str, Any]], valuation: dict[str, Any], tickers: set[str]) -> list[dict[str, Any]]:
    rows = []
    for stock in stocks:
        ticker = str(stock.get("ticker", "")).upper()
        if ticker not in tickers:
            continue
        metric = valuation.get(ticker, {}) if isinstance(valuation, dict) else {}
        log_row = {
            "ticker": ticker,
            "name": stock.get("name") or "-",
            "market": stock.get("market") or "-",
            "industry": stock.get("industry") or "-",
            "category": stock.get("category") or "-",
            "currentPrice": stock.get("currentPrice") or "-",
            "fairPrice": stock.get("fairPrice") or "-",
            "fairPriceReason": stock.get("fairPriceReason") or "-",
            "valuation": stock.get("valuation") or "-",
            "opinion": "-" if stock.get("fairPriceReason") == "loss_making" else stock.get("opinion", "-"),
            "updatedAt": stock.get("updatedAt") or "-",
            **{key: metric.get(key, "-") for key, _ in VALUATION_LOG_FIELDS if key != "valuationIndustry"},
            "valuationIndustry": metric.get("industry", "-"),
        }
        log_row["logText"] = value_log_text(log_row)
        rows.append(log_row)
    return rows[:MAX_LOG_ROWS]


def tech_value(row: dict[str, Any], *candidates: str) -> Any:
    for candidate in candidates:
        if candidate in row and row[candidate]:
            return row[candidate]
        found = next((value for key, value in row.items() if candidate.lower() in str(key).lower() and value), None)
        if found:
            return found
    return "-"


TECHNICAL_GROUP_TITLES = {
    "A": "200일선 상방 & 모멘텀 재가속 (나스닥 ≥-3%)",
    "B": "200일선 하방 & 공황 저점 (나스닥 필터 미적용)",
    "C": "200일선 상방 & 스퀴즈 거래량 돌파 (나스닥 ≥-3%)",
    "D": "200일선 상방 & 상승 흐름 강화 (나스닥 ≥-3%)",
    "E": "200일선 상방 & 스퀴즈 저점 (히스테리시스+찐바닥 허용)",
    "F": "200일선 상방 & BB 극단 저점 (히스테리시스+찐바닥 허용)",
}
CIRCLED_NUMBERS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"]


def numbered_condition(index: int, detail: str) -> str:
    label, _, raw_status = detail.partition(":")
    passed = raw_status.strip() == "통과"
    prefix = CIRCLED_NUMBERS[index - 1] if index <= len(CIRCLED_NUMBERS) else str(index)
    return f"  {prefix} {label.strip()}: {log_mark(passed)}"


def formatted_technical_decision(decision: str, signal_codes: list[str]) -> list[str]:
    lines: list[str] = []
    final_label = ", ".join(signal_codes) if signal_codes else "-"

    for raw_line in str(decision or "-").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("시장 국면:"):
            lines.extend(["[시장]", f"  {line.removeprefix('시장 국면:').strip()}"])
            continue

        group_match = re.match(r"^([A-G])그룹\s+([0-9]+/[0-9]+)\s+-\s+(.+)$", line)
        if group_match:
            group, _score, details = group_match.groups()
            title = TECHNICAL_GROUP_TITLES.get(group, "전략 조건")
            lines.append(f"[{group}그룹: {title}]")
            for index, detail in enumerate(details.split(" / "), start=1):
                lines.append(numbered_condition(index, detail))
            continue

        if "최종 판단:" in line:
            continue
        if line.startswith("진입 전략:"):
            continue
        lines.append(f"  {line}")

    lines.append(f"→ 최종 매수 신호: {log_mark(bool(signal_codes))} {'충족' if signal_codes else '미충족'} [{final_label}]")
    return lines


def technical_log_text(row: dict[str, Any]) -> str:
    header_parts = [
        f"{row.get('ticker') or '-'}",
        str(row.get("name") or "-"),
        str(row.get("market") or "-"),
    ]
    if row.get("industry"):
        header_parts.append(str(row["industry"]))

    signal_codes = row.get("entrySignalCodes")
    signal_code_list = signal_codes if isinstance(signal_codes, list) else [
        code.strip()
        for code in str(signal_codes or "").split(",")
        if code.strip()
    ]

    return "\n".join([
        f"====== {' | '.join(header_parts)} ======",
        "[요약]",
        f"  변경: {row.get('change') or '-'}",
        f"  투자의견: {row.get('opinion') or '-'}",
        f"  진입 전략: {row.get('strategy') or '-'}",
        *formatted_technical_decision(str(row.get("decision") or "-"), signal_code_list),
        "[핵심 지표]",
        f"  현재가: {row.get('currentPrice') or '-'}",
        f"  RSI: {row.get('rsi') or '-'}",
        f"  종가%B: {row.get('pctB') or '-'}",
        f"  MA200: {row.get('ma200') or '-'}",
        f"  갱신: {row.get('updatedAt') or '-'}",
    ])


def technical_log_rows(
    stocks: list[dict[str, Any]],
    previous_stocks: dict[str, dict[str, Any]],
    technical: dict[str, Any],
    tickers: set[str],
) -> list[dict[str, Any]]:
    rows = []
    for stock in stocks:
        ticker = str(stock.get("ticker", "")).upper()
        if ticker not in tickers:
            continue
        row = technical.get(ticker, {}) if isinstance(technical, dict) else {}
        previous_opinion = str(previous_stocks.get(ticker, {}).get("opinion") or "-")
        current_opinion = str(stock.get("opinion") or "-")
        strategies = stock.get("strategies")
        log_row = {
            "ticker": ticker,
            "name": stock.get("name") or row.get("name") or "-",
            "market": stock.get("market") or "-",
            "industry": stock.get("industry") or "-",
            "change": "변경" if previous_opinion != current_opinion else "유지",
            "opinion": f"{previous_opinion} -> {current_opinion}",
            "strategy": ", ".join(str(v) for v in strategies) if isinstance(strategies, list) and strategies else tech_value(row, "진입 전략"),
            "entrySignalCodes": row.get("entrySignalCodes") or "",
            "decision": row.get("decisionLog") or row.get("conditionSummary") or "-",
            "currentPrice": tech_value(row, "현재가") or stock.get("currentPrice") or "-",
            "rsi": tech_value(row, "RSI"),
            "pctB": tech_value(row, "%B"),
            "ma200": tech_value(row, "MA200", "200일선"),
            "updatedAt": stock.get("updatedAt") or "-",
        }
        log_row["logText"] = technical_log_text(log_row)
        rows.append(log_row)
    return rows[:MAX_LOG_ROWS]


def market_trend_log_rows(market_trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for trend in market_trends[:12]:
        for index, rank_text in enumerate(trend.get("ranks") or [], start=1):
            parts = [part.strip() for part in str(rank_text).split("|")]
            rows.append({
                "date": trend.get("date") or "-",
                "rank": index,
                "sector": parts[0] if parts else "-",
                "keywords": parts[1] if len(parts) > 1 else "",
                "summary": trend.get("summary") or "-",
            })
    return rows


def actions_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


def update_trade_logs_for_tasks(enabled_tasks: set[str]) -> bool:
    if "technical-analysis" not in enabled_tasks:
        print("[trade_logs] no technical-analysis task; skipped.")
        return False

    stocks_payload = load_json(API_DIR / "stocks.json", {"rows": []})
    previous_stocks_payload = load_json(PREVIOUS_STOCKS_PATH, {"rows": []})
    technical_payload = load_json(API_DIR / "technical.json", {"rows": {}})

    stocks = stocks_payload.get("rows", []) if isinstance(stocks_payload, dict) else []
    previous_stocks_list = previous_stocks_payload.get("rows", []) if isinstance(previous_stocks_payload, dict) else []
    previous_stocks = stocks_by_ticker(previous_stocks_list)
    technical = technical_payload.get("rows", {}) if isinstance(technical_payload, dict) else {}
    qqq_market_state = technical_payload.get("qqqMarketState", {}) if isinstance(technical_payload, dict) else {}
    signal_state_changed = update_trade_logs(stocks, previous_stocks, technical, qqq_market_state)
    if signal_state_changed:
        write_stock_payload(stocks_payload)
        write_technical_payload(technical_payload)
        print("[trade_logs] adjusted held-position buy signals.")
    print("[trade_logs] updated trade logs.")
    return True


def build_logs(enabled_tasks: set[str], *, update_trade_logs_enabled: bool = True) -> list[dict[str, Any]]:
    stocks_payload = load_json(API_DIR / "stocks.json", {"rows": []})
    previous_stocks_payload = load_json(PREVIOUS_STOCKS_PATH, {"rows": []})
    valuation_payload = load_json(API_DIR / "valuation.json", {"rows": {}})
    technical_payload = load_json(API_DIR / "technical.json", {"rows": {}})
    trends_payload = load_json(API_DIR / "market-trends.json", {"rows": []})

    stocks = stocks_payload.get("rows", []) if isinstance(stocks_payload, dict) else []
    previous_stocks_list = previous_stocks_payload.get("rows", []) if isinstance(previous_stocks_payload, dict) else []
    previous_stocks = stocks_by_ticker(previous_stocks_list)
    valuation = valuation_payload.get("rows", {}) if isinstance(valuation_payload, dict) else {}
    technical = technical_payload.get("rows", {}) if isinstance(technical_payload, dict) else {}
    qqq_market_state = technical_payload.get("qqqMarketState", {}) if isinstance(technical_payload, dict) else {}
    market_trends = trends_payload.get("rows", []) if isinstance(trends_payload, dict) else []
    tickers = set(load_watchlist_tickers(stocks))
    base = {
        "source": "github-actions",
        "actionsUrl": actions_url(),
        "tickers": sorted(tickers),
    }

    value_rows = value_log_rows(stocks, valuation, tickers)
    technical_rows = technical_log_rows(stocks, previous_stocks, technical, tickers)
    trend_rows = market_trend_log_rows(market_trends)
    if update_trade_logs_enabled:
        update_trade_logs_for_tasks(enabled_tasks)

    logs = [
        {
            "trigger_name": "value-analysis",
            "status": "success",
            "message": f"{len(value_rows)}개 종목 가치분석 데이터를 기록했습니다.",
            "metadata": {
                **base,
                "task": "value-analysis",
                "summary": "GitHub Actions 갱신 후 종목별 가치분석 전체 지표 로그입니다.",
                "total": len(value_rows),
                "view": "logText",
                "columns": [
                    {"key": "ticker", "label": "종목"},
                    {"key": "name", "label": "종목명"},
                    {"key": "market", "label": "시장"},
                    {"key": "currentPrice", "label": "현재가"},
                    {"key": "fairPrice", "label": "적정 주가 범위"},
                    {"key": "valuation", "label": "판단"},
                    {"key": "opinion", "label": "투자의견"},
                ],
                "rows": value_rows,
            },
        },
        {
            "trigger_name": "technical-analysis",
            "status": "success",
            "message": f"{len(technical_rows)}개 종목 기술분석 데이터를 기록했습니다.",
            "metadata": {
                **base,
                "task": "technical-analysis",
                "summary": "GitHub Actions 갱신 후 종목별 매매 기준 판단 로그입니다.",
                "total": len(technical_rows),
                "view": "logText",
                "columns": [
                    {"key": "ticker", "label": "종목"},
                    {"key": "name", "label": "종목명"},
                    {"key": "market", "label": "시장"},
                    {"key": "change", "label": "변경"},
                    {"key": "opinion", "label": "투자의견"},
                    {"key": "strategy", "label": "진입 전략"},
                    {"key": "decision", "label": "판단 로그"},
                ],
                "rows": technical_rows,
            },
        },
        {
            "trigger_name": "market-trends",
            "status": "success",
            "message": f"{len(trend_rows)}개 시장 트렌드 항목을 기록했습니다.",
            "metadata": {
                **base,
                "task": "market-trends",
                "summary": "GitHub Actions 갱신 후 시장 트렌드 순위 데이터입니다.",
                "total": len(trend_rows),
                "columns": [
                    {"key": "date", "label": "기준일"},
                    {"key": "rank", "label": "순위"},
                    {"key": "sector", "label": "섹터"},
                    {"key": "keywords", "label": "키워드"},
                    {"key": "summary", "label": "요약"},
                ],
                "rows": trend_rows,
            },
        },
    ]
    return [log for log in logs if log["trigger_name"] in enabled_tasks]


def parse_runtime_args(argv: list[str]) -> tuple[bool, bool, list[str]]:
    trade_logs_only = False
    skip_trade_log_update = False
    tasks: list[str] = []
    for arg in argv:
        if arg == "--trade-logs-only":
            trade_logs_only = True
        elif arg == "--skip-trade-log-update":
            skip_trade_log_update = True
        else:
            tasks.append(arg)
    return trade_logs_only, skip_trade_log_update, tasks


def main() -> None:
    trade_logs_only, skip_trade_log_update, task_args = parse_runtime_args(sys.argv[1:])
    enabled_tasks = parse_log_tasks(task_args)
    if trade_logs_only:
        update_trade_logs_for_tasks(enabled_tasks)
        return

    if not supabase_url() or not service_key():
        print("[api_logs] Supabase service credentials are missing; skipped.")
        return
    if runtime_reset_requested():
        reset_api_logs()
    else:
        clean_old_logs()
    logs = build_logs(enabled_tasks, update_trade_logs_enabled=not skip_trade_log_update)
    if not logs:
        print("[api_logs] no matching operation-log tasks; skipped.")
        return
    supabase_request("/rest/v1/api_logs", method="POST", payload=logs)
    print(f"[api_logs] recorded {len(logs)} stock-level refresh logs.")


if __name__ == "__main__":
    main()
