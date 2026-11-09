"""Build and deliver account-level investing reminders after a technical refresh."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from hashlib import sha256
from html import escape
from math import isfinite
import os
from urllib.parse import quote

from calculator.leveraged_reference import is_inverse_product
from calculator.market_regime import QQQ_RECOVERY_BUY_BLOCK_MAX
from calculator.rules import STRATEGY_RULES
from scripts import web_refresh_notifications as notifications
from scripts.record_web_api_logs import REENTRY_DAYS, REENTRY_DROP, SELL_HOLD_DAYS, write_trade_logs

FEAR_VIX = 20
FEAR_CNN_MAX = 44

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


def target_conditions(settings, stocks, technical, fear, now):
    """Yield each eligible target, including those whose conditions have cleared."""
    activated = date_time(settings.get("collectingSince"))
    if activated is None or activated > now:
        return
    for account in settings.get("accounts") or []:
        account_id = account.get("id")
        timing = account.get("buyTiming")
        if not account_id or timing not in {"월초", "중순", "월말"}:
            continue
        frequency = settings.get("frequency", "monthly") if account_id == "default" else account.get("frequency", "monthly")
        deposit_month = settings.get("monthOfYear", 1) if account_id == "default" else account.get("monthOfYear", 1)
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
            budget = planned_amount(settings, account, percent)
            yield account_id, ticker, local_now, codes, budget


def planned_amount(settings, account, percent):
    default = account.get("id") == "default"
    frequency = settings.get("frequency", "monthly") if default else account.get("frequency", "monthly")
    amount = settings.get("amount") if default else account.get("monthlyDeposit")
    if frequency in {"monthly", "yearly"} and isinstance(amount, int) and amount > 0:
        return round(amount * percent / 100)
    return None


def operator_signal_row(account, ticker, stock, code, budget, now):
    day = now.astimezone(notifications.KST).date().isoformat()
    account_id = account["id"]
    ready = budget is not None and budget > 0 and positive_price(stock.get("currentPrice")) is not None
    return {
        "slotId": private_key(day, "operator-collecting", account_id, ticker),
        "investmentType": "long_term",
        "investmentAccountId": account_id,
        "investmentAccountName": account.get("nickname") or "계좌",
        "collectingSystemEntry": True,
        "ticker": ticker,
        "name": stock.get("name") or ticker,
        "market": stock.get("market"),
        "strategy": f"{int(code) - 2}. {STRATEGIES[code]}" if code in {"3", "4"} else STRATEGIES[code],
        "buyDate": day.replace("-", "."),
        "buyTimestamp": now.isoformat(),
        "buyPrice": stock.get("currentPrice") or "-",
        "currentPrice": stock.get("currentPrice") or "-",
        "investmentAmount": budget if ready else 0,
        "allocationRequestedAmount": budget,
        "status": "보유 중" if ready else "매수 보류",
        "sellDate": "보유 중" if ready else "-",
        "sellPrice": "-",
        "returnPct": 0,
        "holdingDays": "-",
        **({"allocationReason": "계획 금액 또는 신호 가격 확인 필요"} if not ready else {}),
    }


def append_operator_signals(payload, signals):
    rows = payload.setdefault("rows", [])
    known = {row.get("slotId") for row in rows}
    additions = {row["slotId"]: row for row in signals if row["slotId"] not in known}
    rows.extend(additions.values())
    return len(additions)


def private_key(day: str, *parts: str) -> str:
    return f"{day}:{sha256(':'.join(parts).encode()).hexdigest()}"


def positive_price(value):
    price = value if isinstance(value, (int, float)) else notifications.parse_metric_number(value)
    return price if price is not None and isfinite(price) and price > 0 else None


def repeat_buy_allowed(previous, price, market, now):
    if previous is None:
        return True
    sent_at, reference_price = previous
    if now.astimezone(timezone.utc) - sent_at.astimezone(timezone.utc) < timedelta(days=SELL_HOLD_DAYS):
        return False
    zone = notifications.KST if market == "KR" else notifications.ET
    start = sent_at.astimezone(zone).date()
    end = now.astimezone(zone).date()
    month = start.replace(day=1)
    sessions = 0
    while month <= end:
        sessions += sum(start < day <= end for day in monthly_sessions(market, month.year, month.month))
        if sessions > REENTRY_DAYS:
            return True
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return bool(reference_price and price and price <= reference_price * (1 - REENTRY_DROP))


def strategy_criterion(code, account, settings, stock):
    rules = STRATEGY_RULES
    if code == "1":
        default = account.get("id") == "default"
        frequency = settings.get("frequency") if default else account.get("frequency")
        month = settings.get("monthOfYear", 1) if default else account.get("monthOfYear", 1)
        period = f"매년 {month}월" if frequency == "yearly" else "매월"
        session = {"월초": "첫 거래일", "중순": "15일 이후 첫 거래일", "월말": "마지막 거래일"}
        return f"{period} 해당 시장의 {session.get(account.get('buyTiming'), '설정 거래일')}에 알립니다."
    if code == "2":
        return f"VIX {FEAR_VIX} 이상 또는 CNN 공포·탐욕지수 0~{FEAR_CNN_MAX}일 때 충족합니다."
    inverse = is_inverse_product(stock)
    short_floor = rules["NASDAQ_BUY_BLOCK_MAX"]
    if code == "3":
        market = f"+{short_floor}% 이상" if inverse else f"{rules['NASDAQ_DIST_UPPER']}% 미만"
        return (
            f"QQQ의 200일선 대비 괴리율 {market}, 종목 현재가 200일선 미만, "
            f"VIX {rules['VIX_MIN']} 이상, RSI {rules['RSI_MAX']} 미만 또는 CCI {rules['CCI_MIN']} 미만이 필요합니다. "
            f"120일 저가 회귀선은 상승 중이어야 하며 당일 저가는 회귀선의 {rules['LR_TOUCH_RATIO']:.0%} 이하여야 합니다."
        )
    market = (f"회복장이 아닌 상태, QQQ 괴리율 +{short_floor}% 이상" if inverse else
              f"회복장, QQQ 괴리율 +{QQQ_RECOVERY_BUY_BLOCK_MAX:g}% 이하")
    return (
        f"매수 시즌이 열린 상태에서 {market} 조건을 충족해야 합니다. "
        f"당일 저가가 20·60·144·200일선 중 하나의 {rules['MA_TOUCH_RATIO']:.1%} 이하에 닿고 "
        f"현재가가 같은 이평선의 {rules['MA_RECLAIM_RATIO']:.1%} 이상이어야 합니다. 시장 공포 저점 진입이 우선합니다."
    )


def strategy_values(code, stock, technical, snapshot):
    if code == "2":
        vix = metric(snapshot, "VIX (변동성지수)")
        cnn = metric(snapshot, "CNN 공포·탐욕지수")
        return f"VIX {vix if vix is not None else '-'} · CNN 공포·탐욕 {cnn if cnn is not None else '-'}"
    if code == "3":
        detail = notifications.buy_reason_detail("1", stock, technical)
        return f"{detail} | VIX {metric(snapshot, 'VIX (변동성지수)') or '-'}"
    if code == "4":
        detail = notifications.buy_reason_detail("2", stock, technical)
        ma144 = notifications.tech_text(technical, "144일 이동평균선", "MA144", "ma144")
        return f"{detail} | MA144 {ma144}"
    return ""


def collecting_email_body(cards, accounts, settings, stocks, technical, snapshot):
    sections = []
    has_buy = False
    for account_id, tickers in cards.items():
        account = accounts.get(account_id, {})
        name = account.get("nickname") or next(
            (event[2].get("investmentAccountName") for events in tickers.values()
             for event in events if event[0] == "record" and event[2].get("investmentAccountName")), "계좌"
        )
        rendered = []
        for ticker, events in tickers.items():
            stock = stocks.get(ticker, {})
            lines = []
            is_buy = any(kind == "buy" for kind, _, _ in events)
            has_buy |= is_buy
            accent = "#2ecc71" if is_buy else "#a8a29e"
            budget_shown = False
            for kind, code, value in events:
                if kind == "record":
                    buy_price = escape(str(value.get("buyPrice") or "-"))
                    lines.append(
                        f"<strong>매수 기록 저장</strong> · {escape(code)} · {value['amount']:,.0f}원"
                        f"<br>기록한 매수가 · {buy_price}"
                    )
                    continue
                label = "매수 신호" if kind == "buy" else "매수 조건 해제"
                color = "#15803d" if kind == "buy" else "#78716c"
                line = f'<strong style="color:{color};">{label}</strong> · 전략 {code} {STRATEGIES[code]}'
                if value is not None and not budget_shown:
                    line += f" · 계획 금액 {value:,}원"
                    budget_shown = True
                line += f"<br>{escape(strategy_criterion(code, account, settings, stock))}"
                observed = strategy_values(code, stock, technical.get(ticker, {}), snapshot)
                if observed:
                    line += f"<br>확인값 · {escape(observed)}"
                lines.append(line)
            details = '<div style="margin-top:8px;font-size:13px;line-height:1.55;color:#44403c;">'
            rendered.append(f"""
                <div style="margin:0 0 10px;padding:12px 14px;background:#fafaf9;border:1px solid #f0eeeb;border-left:3px solid {accent};border-radius:12px;">
                  <div style="font-size:15px;font-weight:700;color:#1c1917;">{escape(notifications.display_stock(stock, ticker))}</div>
                  <div style="margin-top:4px;font-size:13px;color:#57534e;">현재가 · <strong>{escape(str(stock.get("currentPrice") or "-"))}</strong></div>
                  {''.join(f'{details}{line}</div>' for line in lines)}
                </div>
            """)
        sections.append(f"""
            <h2 style="margin:18px 0 8px;font-size:16px;line-height:1.4;color:#1c1917;">{escape(name)}</h2>
            {''.join(rendered)}
        """)
    sections.append(f"""
        <div style="margin-top:14px;padding:12px 14px;border:1px solid #e7e5e4;border-radius:12px;font-size:13px;color:#57534e;">
          <strong>추가 매수 알림 기준</strong><br>
          같은 계좌·종목의 최근 매수 알림 또는 저장한 매수 기록 이후 {SELL_HOLD_DAYS * 24}시간이 지나야 합니다.
          그 기준 시점부터 {REENTRY_DAYS}거래일 이내에는 당시 가격보다 {REENTRY_DROP:.0%} 이상 낮고 전략 조건을 충족할 때 알립니다.
          {REENTRY_DAYS}거래일이 지나면 전략 조건을 적용합니다. 월 정기매수는 계좌 일정에 맞춰 알립니다.
        </div>
    """)
    colors = ("#15803d", "매수", "#f0fdf4", "#166534") if has_buy else ("#1d4ed8", "계좌 알림", "#eff6ff", "#1d4ed8")
    return notifications.signal_email_layout(
        "가치투자 계좌별 투자 알림", f"{len(cards)}개 계좌의 변경 내역을 확인하세요.",
        "".join(sections), *colors,
    )


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
    vix = metric(snapshot, "VIX (변동성지수)")
    cnn = metric(snapshot, "CNN 공포·탐욕지수")
    fear = (vix is not None and vix >= FEAR_VIX) or (cnn is not None and 0 <= cnn <= FEAR_CNN_MAX)
    state = notifications.read_json(notifications.NOTIFICATION_STATE)
    if not isinstance(state, dict):
        state = {}
    sent = set(state.get("collecting", {}).get("sentKeys", []))
    active = set(state.get("collectingActive", []))
    last_buy = state.get("collectingLastBuy", {})
    # Older deployments used the send timestamp in optional signal keys.
    # Their reference price was never stored, so only their timing can be recovered.
    legacy_times = sorted({
        stamp for key in sent
        if (stamp := date_time(key.rsplit(":", 1)[0])) is not None
        and now - timedelta(days=32) <= stamp <= now
    }, reverse=True)
    primary_admin = next((email.strip().lower() for email in os.environ.get("ADMIN_EMAILS", "").split(",") if email.strip()), "")
    count = 0
    for owner_id, recipient in recipients.items():
        rows = notifications.supabase_request(
            f"/rest/v1/user_settings?select=contribution_settings,personal_trade_logs&owner_id=eq.{quote(owner_id, safe='')}"
        )
        if not rows:
            continue
        settings = rows[0].get("contribution_settings") or {}
        accounts = {account["id"]: account for account in settings.get("accounts") or [] if account.get("id")}
        next_active = set(active)
        next_last_buy = dict(last_buy)
        cards = defaultdict(lambda: defaultdict(list))
        pending = set()
        actual_buys = {}
        operator = recipient.is_admin and recipient.email.lower() == primary_admin
        operator_log = notifications.read_json(notifications.DEFAULT_CURRENT_TRADE_LOGS) if operator else {}
        for trade in rows[0].get("personal_trade_logs") or []:
            recorded = date_time(trade.get("collectingRecordedAt"))
            if not trade.get("collectingEntry") or not trade.get("slotId") or recorded is None or recorded > now:
                continue
            account_id = trade.get("investmentAccountId") or "default"
            ticker = str(trade.get("ticker") or "").strip().upper()
            target = (account_id, ticker)
            previous = actual_buys.get(target)
            if previous is None or recorded > previous[0]:
                actual_buys[target] = (recorded, positive_price(trade.get("buyPrice")))
            key = private_key(recorded.date().isoformat(), "fill", owner_id, str(trade["slotId"]))
            amount = trade.get("allocationRequestedAmount", trade.get("investmentAmount"))
            if key in sent or key in pending or recorded < now - timedelta(days=2):
                continue
            if not isinstance(amount, (int, float)) or not isfinite(amount) or amount <= 0:
                continue
            strategy = trade.get("strategy") or "-"
            strategy = {"1. 시장 공포 저점 진입": "3. 시장 공포 저점 진입",
                        "2. 상승 추세 이평선 눌림목": "4. 상승 추세 이평선 눌림목"}.get(strategy, strategy)
            cards[account_id][ticker].append(("record", strategy, {**trade, "amount": amount}))
            pending.add(key)

        for account_id, ticker, local, codes, budget in target_conditions(settings, stocks, technical, fear, now):
            stock = stocks[ticker]
            market = stock["market"]
            target_key = private_key("buy", owner_id, account_id, ticker)
            last = last_buy.get(target_key, {})
            last_time = date_time(last.get("at"))
            previous = (last_time, positive_price(last.get("price"))) if last_time is not None else None
            if previous is None:
                for stamp in legacy_times:
                    day = stamp.astimezone(local.tzinfo).date()
                    if any(private_key(stamp.isoformat(), "signal", owner_id, f"{day}:{account_id}:{ticker}:{code}") in sent
                           for code in ("2", "3", "4")):
                        previous = (stamp, None)
                        next_last_buy[target_key] = {"at": stamp.isoformat(), "price": None}
                        break
            actual = actual_buys.get((account_id, ticker))
            if actual is not None and (previous is None or actual[0] >= previous[0]):
                previous = actual
            price = positive_price(stock.get("currentPrice"))
            bought = False
            if "1" in codes:
                day = local.date().isoformat()
                key = private_key(day, "signal", owner_id, f"{day}:{account_id}:{ticker}:1")
                if key not in sent and key not in pending:
                    cards[account_id][ticker].append(("buy", "1", budget))
                    pending.add(key)
                    bought = True
            optional_codes = ("2", "3", "4")
            can_repeat = any(code in codes for code in optional_codes) and repeat_buy_allowed(
                previous, price, market, now
            )
            for code in optional_codes:
                identity = private_key("active", owner_id, account_id, ticker, code)
                if code in codes:
                    if identity not in active and can_repeat:
                        key = private_key(now.isoformat(), "signal", identity)
                        if key not in sent and key not in pending:
                            cards[account_id][ticker].append(("buy", code, budget))
                            pending.add(key)
                            next_active.add(identity)
                            bought = True
                elif identity in active:
                    if code == "2" and (vix is None or cnn is None):
                        continue
                    if code in {"3", "4"} and stock.get("opinion") not in {"매수", "관망", "매도"}:
                        continue
                    key = private_key(now.isoformat(), "release", identity)
                    if key not in sent and key not in pending:
                        cards[account_id][ticker].append(("release", code, None))
                        pending.add(key)
                    next_active.discard(identity)
            if bought:
                next_last_buy[target_key] = {"at": now.isoformat(), "price": price}

        if pending:
            if operator:
                signals = [
                    operator_signal_row(accounts[account_id], ticker, stocks[ticker], entry[1], entry[2], now)
                    for account_id, tickers in cards.items()
                    for ticker, events in tickers.items()
                    if (entry := next((event for event in events if event[0] == "buy"), None))
                ]
                if signals and append_operator_signals(operator_log, signals):
                    write_trade_logs(operator_log)
            body = collecting_email_body(cards, accounts, settings, stocks, technical, snapshot)
            notifications.send_notification(
                recipient, "가치투자 계좌별 투자 알림",
                notifications.append_notification_footer(body, recipient, "opinionChangeEmail"),
            )
            sent.update(pending)
            state["collecting"] = {"sentKeys": sorted(sent)[-20000:], "updatedAt": now.isoformat()}
            count += 1
        if pending or next_active != active or next_last_buy != last_buy:
            active, last_buy = next_active, next_last_buy
            state["collectingActive"] = sorted(active)
            state["collectingLastBuy"] = last_buy
            notifications.write_json(notifications.NOTIFICATION_STATE, state)
    return count


if __name__ == "__main__":
    print(f"Sent collecting notifications: {send_collecting_notifications()}")
