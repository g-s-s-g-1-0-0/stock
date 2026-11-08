"""Build and deliver account-level investing reminders after a technical refresh."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from html import escape
from math import isfinite
from urllib.parse import quote

from scripts import web_refresh_notifications as notifications

STRATEGIES = {
    "1": "월 정기매수",
    "2": "간편 공포 매수",
    "3": "시장 공포 저점 진입",
    "4": "상승 추세 이평선 눌림목",
}


@lru_cache(maxsize=24)
def monthly_sessions(market: str, year: int, month: int) -> tuple[date, ...]:
    from exchange_calendars import get_calendar

    calendar = get_calendar("XKRX" if market == "KR" else "XNYS", start=f"{year}-01-01", end=f"{year}-12-31")
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return tuple(day for day in calendar.sessions.date if start <= day <= end)


def metric(snapshot: dict[str, str], prefix: str) -> float | None:
    value = next((value for label, value in snapshot.items() if label.startswith(prefix)), "")
    try:
        number = float(value.split("/", 1)[0].strip())
        return number if isfinite(number) else None
    except ValueError:
        return None


def date_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def buy_signals(settings, stocks, technical, snapshot, now):
    """Yield durable key suffixes and display text. Signals never create fills."""
    activated = date_time(settings.get("collectingSince"))
    if activated is None or activated > now:
        return
    vix = metric(snapshot, "VIX (변동성지수)")
    cnn = metric(snapshot, "CNN 공포·탐욕지수")
    fear = (vix is not None and vix >= 20) or (cnn is not None and 0 <= cnn <= 44)
    for account in settings.get("accounts") or []:
        account_id = account.get("id")
        timing = account.get("buyTiming")
        if not account_id or timing not in {"월초", "중순", "월말"}:
            continue
        nickname = account.get("nickname") or "계좌"
        frequency = settings.get("frequency", "monthly") if account_id == "default" else account.get("frequency", "monthly")
        deposit_month = settings.get("monthOfYear", 1) if account_id == "default" else account.get("monthOfYear", 1)
        amount = settings.get("amount", 0) if account_id == "default" else account.get("monthlyDeposit", 0)
        for target in account.get("collecting") or []:
            ticker = target.get("ticker")
            percent = target.get("percent")
            stock = stocks.get(ticker, {})
            market = stock.get("market")
            if market not in {"KR", "US"} or not isinstance(percent, int) or not 1 <= percent <= 100:
                continue
            local_now = now.astimezone(notifications.KST if market == "KR" else notifications.ET)
            today = local_now.date()
            sessions = monthly_sessions(market, today.year, today.month)
            if today not in sessions or local_now.hour < (9 if market == "KR" else 4):
                continue
            scheduled = {"월초": sessions[0], "중순": next(day for day in sessions if day.day >= 15), "월말": sessions[-1]}[timing]
            codes = []
            if today == scheduled and (frequency != "yearly" or today.month == deposit_month):
                codes.append("1")
            if fear:
                codes.append("2")
            if stock.get("opinion") == "매수":
                entry = notifications.buy_strategy_codes(stock, technical.get(ticker, {}))
                codes.extend(code for source, code in (("1", "3"), ("2", "4")) if source in entry)
            for code in codes:
                budget = f" · 계획 금액 {round(amount * percent / 100):,}원" if (
                    code == "1" and frequency in {"monthly", "yearly"} and isinstance(amount, int) and amount > 0
                ) else ""
                key = f"{today}:{account_id}:{ticker}:{code}"
                yield key, f"{nickname} · {ticker} · 전략 {code} {STRATEGIES[code]}{budget}"


def private_key(day: str, *parts: str) -> str:
    return f"{day}:{sha256(':'.join(parts).encode()).hexdigest()}"


def send_collecting_notifications(now: datetime | None = None) -> int:
    now = now or datetime.now(notifications.KST)
    recipients = {
        recipient.owner_id: recipient for recipient in notifications.load_recipients()
        if recipient.investment_type == "long_term"
        and notifications.enabled(recipient, "opinionChangeEmail")
    }
    if not recipients:
        return 0
    stocks = notifications.search_universe_rows_by_ticker(notifications.DEFAULT_CURRENT_SEARCH_UNIVERSE)
    stocks.update(notifications.stock_rows_by_ticker(notifications.DEFAULT_CURRENT_STOCKS))
    technical = notifications.technical_rows_by_ticker()
    snapshot = notifications.market_snapshot_map()
    sent = notifications.read_sent_keys("collecting")
    count = 0
    for owner_id, recipient in recipients.items():
        rows = notifications.supabase_request(
            f"/rest/v1/user_settings?select=contribution_settings,personal_trade_logs&owner_id=eq.{quote(owner_id, safe='')}"
        )
        if not rows:
            continue
        settings = rows[0].get("contribution_settings") or {}
        state = notifications.read_json(notifications.NOTIFICATION_STATE)
        active = set(state.get("collectingActive", [])) if isinstance(state, dict) else set()
        next_active = set(active)
        signals = []
        current = list(buy_signals(settings, stocks, technical, snapshot, now))
        for key, label in current:
            day, account_id, ticker, code = key.split(":")
            if code == "1":
                signals.append((private_key(day, "signal", owner_id, key), label))
                continue
            identity = private_key("active", owner_id, account_id, ticker, code)
            if identity not in active:
                signals.append((private_key(now.isoformat(), "signal", owner_id, key), label + " · 매수 조건 충족"))
            next_active.add(identity)
        current_conditions = {tuple(key.split(":")[1:]) for key, _ in current}
        for account in settings.get("accounts") or []:
            for target in account.get("collecting") or []:
                ticker = target.get("ticker")
                stock = stocks.get(ticker, {})
                market = stock.get("market")
                if market not in {"KR", "US"}:
                    continue
                local = now.astimezone(notifications.KST if market == "KR" else notifications.ET)
                if local.date() not in monthly_sessions(market, local.year, local.month) or local.hour < (9 if market == "KR" else 4):
                    continue
                for code in ("2", "3", "4"):
                    if code == "2" and (metric(snapshot, "VIX (변동성지수)") is None or metric(snapshot, "CNN 공포·탐욕지수") is None):
                        continue
                    if code in {"3", "4"} and stock.get("opinion") not in {"매수", "관망", "매도"}:
                        continue
                    account_id = account.get("id", "")
                    identity = private_key("active", owner_id, account_id, ticker, code)
                    if identity in active and (account_id, ticker, code) not in current_conditions:
                        label = f"{account.get('nickname') or '계좌'} · {ticker} · 전략 {code} {STRATEGIES[code]} · 매수 조건 해제"
                        signals.append((private_key(now.isoformat(), "release", identity), label))
                        next_active.discard(identity)
        fills = []
        for trade in rows[0].get("personal_trade_logs") or []:
            recorded = date_time(trade.get("collectingRecordedAt"))
            if not trade.get("collectingEntry") or not trade.get("slotId") or recorded is None or not now - timedelta(days=2) <= recorded <= now:
                continue
            key = private_key(recorded.date().isoformat(), "fill", owner_id, str(trade["slotId"]))
            amount = trade.get("allocationRequestedAmount", trade.get("investmentAmount"))
            if not isinstance(amount, (int, float)) or not isfinite(amount) or amount <= 0:
                continue
            strategy = trade.get("strategy") or "-"
            strategy = {"1. 시장 공포 저점 진입": "3. 시장 공포 저점 진입",
                        "2. 상승 추세 이평선 눌림목": "4. 상승 추세 이평선 눌림목"}.get(strategy, strategy)
            fills.append((key, f"{trade.get('investmentAccountName') or '계좌'} · {trade.get('ticker')} · {strategy} · {amount:,.0f}원"))
        pending_signals = {key: label for key, label in signals if key not in sent}
        pending_fills = {key: label for key, label in fills if key not in sent}
        pending = pending_signals | pending_fills
        if pending:
            sections = []
            for title, entries in (("매수 신호 변경", pending_signals), ("저장한 매수 기록", pending_fills)):
                if entries:
                    sections.append(f"<h3>{title}</h3><ul>" + "".join(f"<li>{escape(label)}</li>" for label in entries.values()) + "</ul>")
            body = "<p>계좌별 투자 알림입니다. 매수 신호를 확인한 뒤 실제 매수 내역을 기록해 주세요.</p>" + "".join(sections)
            notifications.send_notification(recipient, "가치투자 계좌별 투자 알림", notifications.append_notification_footer(body, recipient, "opinionChangeEmail"))
            notifications.record_sent_keys("collecting", set(pending), limit=20000)
            sent.update(pending)
            count += 1
        if next_active != active:
            state = notifications.read_json(notifications.NOTIFICATION_STATE)
            if not isinstance(state, dict):
                state = {}
            state["collectingActive"] = sorted(next_active)
            notifications.write_json(notifications.NOTIFICATION_STATE, state)
    return count


if __name__ == "__main__":
    print(f"Sent collecting notifications: {send_collecting_notifications()}")
