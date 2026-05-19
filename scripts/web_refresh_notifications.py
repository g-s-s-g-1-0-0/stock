"""Send web-only notification emails after scheduled cache refresh.

This script is intentionally stdlib-only so it can run inside GitHub Actions
without paid infrastructure. It reads:
- previous stocks cache before refresh
- current stocks cache after refresh
- Supabase user_settings/profiles for notification preferences

Email is sent through either SMTP or Brevo, selected by EMAIL_PROVIDER.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from calculator.market_regime import build_qqq_market_state, qqq_recent_ma200_min_distance
from calculator.rules import STRATEGY_RULES
from calculator.sheet_sources import calc_rsi, calc_technical_row, fetch_us_ohlcv

DEFAULT_PREVIOUS_STOCKS = ROOT_DIR / "data" / "cache" / "stocks.before-refresh.json"
DEFAULT_CURRENT_STOCKS = ROOT_DIR / "web" / "public" / "api" / "stocks.json"
DEFAULT_TECHNICAL = ROOT_DIR / "web" / "public" / "api" / "technical.json"
DEFAULT_VALUATION = ROOT_DIR / "web" / "public" / "api" / "valuation.json"
DEFAULT_MARKET_TRENDS = ROOT_DIR / "web" / "public" / "api" / "market-trends.json"
DEFAULT_PREVIOUS_TRADE_LOGS = ROOT_DIR / "data" / "cache" / "trade-logs.before-refresh.json"
DEFAULT_CURRENT_TRADE_LOGS = ROOT_DIR / "web" / "public" / "api" / "trade-logs.json"
NOTIFICATION_STATE = ROOT_DIR / "data" / "cache" / "web-notification-state.json"
KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")
VALID_OPINIONS = {"매수", "관망", "매도"}


@dataclass(frozen=True)
class Recipient:
    owner_id: str
    email: str
    is_admin: bool
    preferences: dict[str, Any]
    slack_webhook_url: str = ""
    slack_channel_name: str = ""


def read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def stock_rows_by_ticker(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("ticker", "")).strip(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("ticker", "")).strip()
    }


def valuation_rows_by_ticker(path: Path = DEFAULT_VALUATION) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    rows = payload.get("rows") if isinstance(payload, dict) else {}
    if not isinstance(rows, dict):
        return {}
    return {
        str(ticker).strip().upper(): row
        for ticker, row in rows.items()
        if isinstance(row, dict) and str(ticker).strip()
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def runtime_reset_state() -> dict[str, Any]:
    state = read_json(NOTIFICATION_STATE)
    reset = state.get("runtimeReset") if isinstance(state, dict) else None
    if isinstance(reset, dict) and reset.get("seedNextRefresh") is True:
        return reset
    return {}


def clear_runtime_reset() -> None:
    state = read_json(NOTIFICATION_STATE)
    if not isinstance(state, dict) or "runtimeReset" not in state:
        return
    state.pop("runtimeReset", None)
    write_json(NOTIFICATION_STATE, state)


def now_labels() -> tuple[str, str]:
    now = datetime.now().astimezone()
    return (
        now.astimezone(KST).strftime("%Y. %m. %d, %H:%M:%S"),
        now.astimezone(ET).strftime("%-m/%-d/%Y, %-I:%M:%S %p"),
    )


def fmt_signed(value: Any, suffix: str = "") -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "-"
    if parsed != parsed:
        return "-"
    return f"{parsed:+.2f}{suffix}"


def fmt_number(value: Any) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "-"
    if parsed != parsed:
        return "-"
    return f"{parsed:.2f}"


def technical_rows_by_ticker(path: Path = DEFAULT_TECHNICAL) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    rows = payload.get("rows") if isinstance(payload, dict) else {}
    return rows if isinstance(rows, dict) else {}


def trade_rows(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    rows = payload.get("rows") if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def trade_ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or "").strip().upper()


def is_open_trade(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "").strip() == "보유 중"


def trade_key(row: dict[str, Any]) -> tuple[str, str, str]:
    slot_id = str(row.get("slotId") or "").strip()
    if slot_id:
        return (
            trade_ticker(row),
            slot_id,
            str(row.get("strategy") or "").strip(),
        )
    return (
        trade_ticker(row),
        str(row.get("buyDate") or "").strip(),
        str(row.get("strategy") or "").strip(),
    )


def display_stock(row: dict[str, Any], ticker: str | None = None) -> str:
    symbol = str(ticker or row.get("ticker") or "").strip().upper()
    name = str(row.get("name") or symbol or "-").strip()
    if not symbol or name == symbol or name.upper().endswith(f"({symbol})"):
        return name
    return f"{name} ({symbol})"


def opinion_groups(current_path: Path, trade_logs_path: Path = DEFAULT_CURRENT_TRADE_LOGS) -> tuple[list[str], list[str], list[str]]:
    current = stock_rows_by_ticker(current_path)
    open_trade_tickers = {
        trade_ticker(row)
        for row in trade_rows(trade_logs_path)
        if is_open_trade(row)
    }
    buy_opinions: list[str] = []
    watch_holding_opinions: list[str] = []
    sell_opinions: list[str] = []
    for ticker, stock in current.items():
        normalized_ticker = str(ticker).strip().upper()
        opinion = str(stock.get("opinion") or "").strip()
        label = display_stock(stock, normalized_ticker)
        if opinion == "매수":
            buy_opinions.append(label)
        elif opinion == "관망" and normalized_ticker in open_trade_tickers:
            watch_holding_opinions.append(label)
        elif opinion == "매도":
            sell_opinions.append(label)
    return buy_opinions, watch_holding_opinions, sell_opinions


def trades_by_ticker(rows: list[dict[str, Any]], *, open_only: bool = False) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ticker = trade_ticker(row)
        if not ticker or (open_only and not is_open_trade(row)):
            continue
        grouped.setdefault(ticker, []).append(row)
    return grouped


def added_open_trades(previous_rows: list[dict[str, Any]], current_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_keys = {trade_key(row) for row in previous_rows}
    return [
        row
        for row in current_rows
        if is_open_trade(row) and trade_key(row) not in previous_keys
    ]


def first_buy_price(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        price = str(row.get("buyPrice") or "").strip()
        if price and price != "-":
            return price
    return ""


def buy_entry_note(
    *,
    old_opinion: str,
    previous_trade_rows: list[dict[str, Any]],
    current_trade_rows: list[dict[str, Any]],
    added_trades: list[dict[str, Any]],
) -> str:
    previous_open = [row for row in previous_trade_rows if is_open_trade(row)]
    current_open = [row for row in current_trade_rows if is_open_trade(row)]

    if previous_open:
        reentry_count = max(len(previous_open), 1)
        entry_price = first_buy_price(previous_open + current_open)
        return (
            f"재진입 {reentry_count}회차 — 최초 진입가 {entry_price}"
            if entry_price
            else f"재진입 {reentry_count}회차"
        )

    return "신규 진입"


def buy_reason_for_trade(trade: dict[str, Any], stock: dict[str, Any], technical_row: dict[str, Any]) -> str:
    code = strategy_code(trade.get("strategy"))
    if not code:
        return buy_reason(stock, technical_row)
    return f"{strategy_label(code, stock, technical_row)} — {buy_reason_detail(code, stock, technical_row)}"


def opinion_changes(
    previous_path: Path,
    current_path: Path,
    technical_path: Path = DEFAULT_TECHNICAL,
    previous_trade_logs_path: Path | None = None,
    current_trade_logs_path: Path | None = None,
) -> list[dict[str, Any]]:
    previous = stock_rows_by_ticker(previous_path)
    current = stock_rows_by_ticker(current_path)
    technical_rows = technical_rows_by_ticker(technical_path)
    previous_trade_rows = trade_rows(previous_trade_logs_path) if previous_trade_logs_path else []
    current_trade_rows = trade_rows(current_trade_logs_path) if current_trade_logs_path else []
    previous_trades_by_ticker = trades_by_ticker(previous_trade_rows)
    current_trades_by_ticker = trades_by_ticker(current_trade_rows)
    added_trades_by_ticker = trades_by_ticker(added_open_trades(previous_trade_rows, current_trade_rows))
    reset = runtime_reset_state()
    forced_baseline = str(reset.get("opinionBaseline") or "관망").strip()
    changes: list[dict[str, Any]] = []
    buy_transition_tickers: set[str] = set()

    for ticker, current_stock in current.items():
        previous_stock = previous.get(ticker)
        new_opinion = str(current_stock.get("opinion") or "").strip()
        if reset and forced_baseline in VALID_OPINIONS:
            previous_stock = {**current_stock, "opinion": forced_baseline}
        elif not previous_stock and new_opinion == "매수":
            previous_stock = {**current_stock, "opinion": "관망"}
        if not previous_stock:
            continue
        old_opinion = str(previous_stock.get("opinion") or "").strip()
        if not old_opinion or not new_opinion or old_opinion == new_opinion:
            continue
        if old_opinion not in VALID_OPINIONS or new_opinion not in VALID_OPINIONS:
            continue
        technical_row = technical_rows.get(ticker, {})
        normalized_ticker = str(ticker).strip().upper()
        added_for_ticker = added_trades_by_ticker.get(normalized_ticker, [])
        previous_trade_rows = previous_trades_by_ticker.get(normalized_ticker, [])
        current_trade_rows = current_trades_by_ticker.get(normalized_ticker, [])
        change = {
            "ticker": ticker,
            "name": current_stock.get("name") or ticker,
            "from": old_opinion,
            "to": new_opinion,
            "price": current_stock.get("currentPrice") or "-",
            "valuation": current_stock.get("valuation") or "-",
            "industry": current_stock.get("industry") or "-",
            "strategies": current_stock.get("strategies") or [],
            "reason": concise_opinion_reason(old_opinion, new_opinion, previous_stock, current_stock, technical_row),
        }
        if new_opinion == "매수":
            if any(is_open_trade(row) for row in previous_trade_rows):
                added_trade = added_for_ticker[0] if added_for_ticker else None
                change["fromLabel"] = "매수(보유중)"
                change["toLabel"] = "추가 매수"
                if added_trade:
                    change["reason"] = buy_reason_for_trade(added_trade, current_stock, technical_row)
            change["entryNote"] = buy_entry_note(
                old_opinion=old_opinion,
                previous_trade_rows=previous_trade_rows,
                current_trade_rows=current_trade_rows,
                added_trades=added_for_ticker,
            )
            buy_transition_tickers.add(normalized_ticker)
        changes.append(change)

    for trade in added_open_trades(previous_trade_rows, current_trade_rows):
        ticker = trade_ticker(trade)
        if not ticker or ticker in buy_transition_tickers:
            continue
        current_stock = current.get(ticker)
        previous_stock = previous.get(ticker)
        if not current_stock or not previous_stock:
            continue
        if str(current_stock.get("opinion") or "").strip() != "매수":
            continue
        if str(previous_stock.get("opinion") or "").strip() != "매수":
            continue
        technical_row = technical_rows.get(ticker, {})
        changes.append({
            "ticker": ticker,
            "name": current_stock.get("name") or trade.get("name") or ticker,
            "from": "매수",
            "to": "매수",
            "fromLabel": "매수(보유중)",
            "toLabel": "추가 매수",
            "price": current_stock.get("currentPrice") or trade.get("currentPrice") or "-",
            "valuation": current_stock.get("valuation") or "-",
            "industry": current_stock.get("industry") or "-",
            "strategies": current_stock.get("strategies") or [],
            "reason": buy_reason_for_trade(trade, current_stock, technical_row),
            "entryNote": buy_entry_note(
                old_opinion="매수",
                previous_trade_rows=previous_trades_by_ticker.get(ticker, []),
                current_trade_rows=current_trades_by_ticker.get(ticker, []),
                added_trades=added_trades_by_ticker.get(ticker, []),
            ),
        })
    return changes


def trade_exit_changes(previous_path: Path, current_path: Path) -> list[dict[str, Any]]:
    previous = {
        trade_key(row): row
        for row in trade_rows(previous_path)
        if str(row.get("status") or "") == "보유 중"
    }
    changes: list[dict[str, Any]] = []
    for current in trade_rows(current_path):
        key = trade_key(current)
        previous_trade = previous.get(key)
        if not previous_trade:
            continue
        current_status = str(current.get("status") or "").strip()
        if current_status == "보유 중":
            continue
        result = current.get("returnPct", 0)
        try:
            result_text = f"{float(result):+.2f}%"
        except (TypeError, ValueError):
            result_text = str(result or "-")
        buy_price = current.get("buyPrice") or previous_trade.get("buyPrice") or "-"
        buy_date = current.get("buyDate") or previous_trade.get("buyDate") or "-"
        changes.append({
            "ticker": current.get("ticker") or key[0],
            "name": current.get("name") or previous_trade.get("name") or key[0],
            "from": "보유 중",
            "to": "매도",
            "price": current.get("sellPrice") or current.get("currentPrice") or "-",
            "buyPrice": buy_price,
            "returnPct": current.get("returnPct", 0),
            "strategy": current.get("strategy") or previous_trade.get("strategy") or "-",
            "reason": current.get("exitReason") or current_status or "시스템 매도",
            "entryNote": f"진입가 {buy_price} ({buy_date}) · 수익률 {result_text}",
            "status": current_status,
        })
    return changes


def supabase_request(path: str) -> list[dict[str, Any]]:
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_key:
        return []

    request = urllib.request.Request(
        supabase_url + path,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def load_recipients() -> list[Recipient]:
    settings_rows = supabase_request("/rest/v1/user_settings?select=owner_id,notification_preferences")
    profile_rows = supabase_request("/rest/v1/profiles?select=id,email,is_admin")
    profiles = {row.get("id"): row for row in profile_rows}
    try:
        integration_rows = supabase_request(
            "/rest/v1/notification_integrations?provider=eq.slack&select=owner_id,webhook_url,channel_name"
        )
    except Exception as exc:
        print(f"Slack integration lookup skipped: {exc}")
        integration_rows = []
    slack_integrations = {
        str(row.get("owner_id") or ""): row
        for row in integration_rows
        if row.get("webhook_url")
    }
    recipients: list[Recipient] = []

    for row in settings_rows:
        prefs = row.get("notification_preferences") if isinstance(row.get("notification_preferences"), dict) else {}
        profile = profiles.get(row.get("owner_id"), {})
        fallback_email = str(profile.get("email") or "").strip()
        target_email = str(prefs.get("recipientEmail") or fallback_email).strip()
        owner_id = str(row.get("owner_id") or "")
        slack_integration = slack_integrations.get(owner_id, {})
        slack_webhook_url = str(slack_integration.get("webhook_url") or "").strip()
        if not target_email and not slack_webhook_url:
            continue
        recipients.append(Recipient(
            owner_id=owner_id,
            email=target_email,
            is_admin=profile.get("is_admin") is True,
            preferences=prefs,
            slack_webhook_url=slack_webhook_url,
            slack_channel_name=str(slack_integration.get("channel_name") or "").strip(),
        ))
    return dedupe_recipients(recipients)


def fallback_admin_recipients() -> list[Recipient]:
    emails = [
        email.strip()
        for email in os.environ.get("ADMIN_EMAILS", "").split(",")
        if email.strip()
    ]
    return [Recipient(owner_id="", email=email, is_admin=True, preferences={}) for email in emails]


def load_watchlists() -> dict[str, set[str]]:
    rows = supabase_request("/rest/v1/watchlists?select=owner_id,scope,tickers")
    result: dict[str, set[str]] = {}
    operator_tickers: set[str] = set()

    for row in rows:
        tickers = {
            str(ticker or "").strip().upper()
            for ticker in row.get("tickers") or []
            if str(ticker or "").strip()
        }
        if not tickers:
            continue
        if row.get("scope") == "operator":
            operator_tickers.update(tickers)
            continue
        owner_id = str(row.get("owner_id") or "")
        if owner_id:
            result.setdefault(owner_id, set()).update(tickers)

    if operator_tickers:
        result[""] = operator_tickers
    return result


def dedupe_recipients(recipients: list[Recipient]) -> list[Recipient]:
    seen: set[str] = set()
    result: list[Recipient] = []
    for recipient in recipients:
        key = recipient.owner_id or recipient.email.lower() or recipient.slack_webhook_url
        if key in seen:
            continue
        seen.add(key)
        result.append(recipient)
    return result


def enabled(recipient: Recipient, key: str, *, default: bool = True) -> bool:
    value = recipient.preferences.get(key)
    return value if isinstance(value, bool) else default


def delivery_channel(recipient: Recipient) -> str:
    requested = str(recipient.preferences.get("notificationChannel") or "email").strip()
    if requested == "slack" and recipient.preferences.get("slackConnected") is True and recipient.slack_webhook_url:
        return "slack"
    return "email"


def smtp_port() -> int:
    raw_port = os.environ.get("SMTP_PORT", "").strip()
    if not raw_port:
        return 465
    try:
        return int(raw_port)
    except ValueError as exc:
        raise RuntimeError("SMTP_PORT는 숫자여야 합니다.") from exc


def email_sender() -> tuple[str, str]:
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    from_email = os.environ.get("SMTP_FROM", smtp_user).strip()
    from_name = os.environ.get("SMTP_FROM_NAME", "공수성가").strip()
    if not from_email:
        raise RuntimeError("SMTP_FROM 설정이 필요합니다.")
    return from_email, from_name


def send_smtp_email(to_email: str, subject: str, html_body: str) -> None:
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    smtp_host = (os.environ.get("SMTP_HOST") or "smtp.gmail.com").strip()
    port = smtp_port()
    from_email, from_name = email_sender()

    if not smtp_user or not smtp_password:
        raise RuntimeError("SMTP_USER, SMTP_PASSWORD 설정이 필요합니다.")

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = to_email
    message.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(smtp_host, port, context=context, timeout=30) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(from_email, [to_email], message.as_string())
        return

    with smtplib.SMTP(smtp_host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(smtp_user, smtp_password)
        server.sendmail(from_email, [to_email], message.as_string())


def send_brevo_email(to_email: str, subject: str, html_body: str) -> None:
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("BREVO_API_KEY 설정이 필요합니다.")

    from_email, from_name = email_sender()
    payload = {
        "sender": {"email": from_email, "name": from_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
    }
    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status >= 300:
                raise RuntimeError(f"Brevo email request failed with {response.status}.")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Brevo email request failed with HTTP {exc.code}: {detail}") from exc


def html_to_text(html_body: str) -> str:
    text = str(html_body or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    compact_lines: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if not blank:
                compact_lines.append("")
            blank = True
            continue
        compact_lines.append(line)
        blank = False
    return "\n".join(compact_lines).strip()


def send_slack_message(webhook_url: str, subject: str, html_body: str) -> None:
    if not webhook_url:
        raise RuntimeError("Slack webhook URL이 설정되지 않았습니다.")
    text = f"*{subject}*\n{html_to_text(html_body)}".strip()
    if len(text) > 3500:
        text = text[:3490].rstrip() + "\n..."
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"Slack webhook request failed with {response.status}.")


def send_email(to_email: str, subject: str, html_body: str) -> None:
    provider = os.environ.get("EMAIL_PROVIDER", "").strip().lower() or "smtp"
    try:
        attempts = int(os.environ.get("EMAIL_SEND_ATTEMPTS", "3"))
    except ValueError:
        attempts = 3
    attempts = max(1, attempts)

    for attempt in range(1, attempts + 1):
        try:
            if provider == "smtp":
                send_smtp_email(to_email, subject, html_body)
                return
            if provider == "brevo":
                send_brevo_email(to_email, subject, html_body)
                return
            raise RuntimeError(f"지원하지 않는 EMAIL_PROVIDER입니다: {provider}")
        except Exception as exc:
            message = str(exc)
            is_config_error = any(
                marker in message
                for marker in (
                    "설정이 필요합니다",
                    "숫자여야 합니다",
                    "지원하지 않는 EMAIL_PROVIDER",
                    "BREVO_API_KEY 설정",
                )
            )
            if is_config_error or attempt == attempts:
                raise
            wait_seconds = min(2 ** attempt, 10)
            print(f"Email send failed for {to_email}; retrying in {wait_seconds}s ({attempt}/{attempts}): {exc}")
            time.sleep(wait_seconds)


def send_notification(recipient: Recipient, subject: str, html_body: str) -> str:
    if delivery_channel(recipient) == "slack":
        try:
            send_slack_message(recipient.slack_webhook_url, subject, html_body)
            return "slack"
        except Exception as exc:
            if not recipient.email:
                raise
            print(f"Slack send failed for {recipient.owner_id or recipient.email}: {exc}; falling back to email.")

    if not recipient.email:
        raise RuntimeError("이메일 수신처가 없어 알림을 보낼 수 없습니다.")
    send_email(recipient.email, subject, html_body)
    return "email"


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unsubscribe_secret() -> str:
    return (os.environ.get("NOTIFICATION_UNSUBSCRIBE_SECRET") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


def web_app_url() -> str:
    return (
        os.environ.get("WEB_APP_URL")
        or os.environ.get("APP_URL")
        or os.environ.get("SITE_URL")
        or ""
    ).strip().rstrip("/")


def settings_url() -> str:
    base_url = web_app_url()
    return f"{base_url}/#home?settings=notifications" if base_url else ""


def unsubscribe_token(recipient: Recipient, preference_key: str) -> str:
    secret = unsubscribe_secret()
    if not secret or not recipient.owner_id:
        return ""
    payload = {
        "ownerId": recipient.owner_id,
        "email": recipient.email.lower(),
        "key": preference_key,
        "exp": int((datetime.now().astimezone() + timedelta(days=365)).timestamp()),
    }
    encoded_payload = base64url(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{base64url(signature)}"


def notification_preference_label(preference_key: str) -> str:
    labels = {
        "opinionChangeEmail": "투자의견 변경 알림",
        "nasdaqPeakEmail": "나스닥 고점 과열 알림",
        "weeklyTrendReport": "주간 트렌드 리포트",
        "earningsDayBefore": "실적발표 전날 알림",
        "adminAutoUpdateFailureEmail": "자동 업데이트 실패 알림",
    }
    return labels.get(preference_key, "이 알림")


def append_notification_footer(html_body: str, recipient: Recipient, preference_key: str) -> str:
    base_url = web_app_url()
    account_url = settings_url()
    unsubscribe_url = ""
    token = unsubscribe_token(recipient, preference_key)
    if token and base_url:
        unsubscribe_url = f"{base_url}/api/notifications/unsubscribe?token={urllib.parse.quote(token)}"
    if not unsubscribe_url and not account_url:
        return html_body

    label = html.escape(notification_preference_label(preference_key))
    links = []
    if unsubscribe_url:
        links.append(f'<a href="{html.escape(unsubscribe_url)}" style="color:#777;text-decoration:underline;">{label} 끄기</a>')
    if account_url:
        links.append(f'<a href="{html.escape(account_url)}" style="color:#777;text-decoration:underline;">알림 설정 열기</a>')
    return html_body + f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin-top:18px;padding-top:12px;border-top:1px solid #eee;color:#888;font-size:12px;line-height:1.6;">
      이 메일은 계정 알림 설정에 따라 발송되었습니다.<br>
      {' · '.join(links)}
    </div>
    """


def list_text(values: list[str]) -> str:
    return ", ".join(values) if values else "없음"


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list) and value:
            value = value[0]
        text = str(value or "").strip()
        if text and text != "-":
            return text
    return "-"


def tech_text(row: dict[str, Any], *keys: str) -> str:
    return first_text(*(row.get(key) for key in keys))


def strategy_code(value: Any) -> str:
    text = str(value or "").strip()
    return text[:1] if text[:1] in {"A", "B", "C", "D", "E", "F"} else ""


STRATEGY_LABELS = {
    "A": "A. 200일선 상방 & 모멘텀 재가속",
    "B": "B. 200일선 하방 & 공황 저점",
    "C": "C. 200일선 상방 & 스퀴즈 거래량 돌파",
    "D": "D. 200일선 상방 & 상승 흐름 강화",
    "E": "E. 200일선 상방 & 스퀴즈 저점",
    "F": "F. 200일선 상방 & BB 극단 저점",
}


def parse_metric_number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    cleaned = re.sub(r"[^0-9.+\-]", "", text.replace(",", ""))
    if cleaned in {"", "-", "+", ".", "+.", "-."}:
        return None
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return parsed if parsed == parsed else None


def metric_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        parsed = parse_metric_number(row.get(key))
        if parsed is not None:
            return parsed
    return None


def metric_label(row: dict[str, Any], *keys: str) -> str:
    return tech_text(row, *keys)


def strategy_values(value: Any) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        values = str(value or "").replace("/", ",").split(",")
    return [str(item or "").strip() for item in values if str(item or "").strip()]


def buy_strategy_codes(stock: dict[str, Any], technical_row: dict[str, Any]) -> list[str]:
    values = (
        strategy_values(technical_row.get("entrySignalCodes"))
        + strategy_values(stock.get("strategies"))
        + strategy_values(technical_row.get("진입 전략"))
        + strategy_values(technical_row.get("entryStrategy"))
        + strategy_values(technical_row.get("entrySignals"))
    )
    codes: list[str] = []
    for value in values:
        code = strategy_code(value)
        if code and code not in codes:
            codes.append(code)
    return codes


def strategy_label(code: str, stock: dict[str, Any], technical_row: dict[str, Any]) -> str:
    for value in (
        strategy_values(stock.get("strategies"))
        + strategy_values(technical_row.get("진입 전략"))
        + strategy_values(technical_row.get("entryStrategy"))
        + strategy_values(technical_row.get("entrySignals"))
    ):
        if strategy_code(value) == code:
            return value
    return STRATEGY_LABELS.get(code, "매수 조건 충족")


def buy_reason_detail(code: str, stock: dict[str, Any], technical_row: dict[str, Any]) -> str:
    price = first_text(stock.get("currentPrice"), technical_row.get("현재가"))
    ma200 = tech_text(technical_row, "200일 이동평균선", "MA200", "ma200")
    pct_b = tech_text(technical_row, "볼린저밴드 %B (종가)", "%B", "pctB")
    pct_b_low = tech_text(technical_row, "볼린저밴드 %B (저가)", "저가%B", "pctBLow")
    rsi = tech_text(technical_row, "RSI (D)", "RSI")
    macd_hist = tech_text(technical_row, "MACD Histogram (D)", "MACD Hist", "macdHist")
    plus_di = tech_text(technical_row, "+DI (DMI, 14)", "+DI")
    minus_di = tech_text(technical_row, "-DI (DMI, 14)", "-DI")
    adx = tech_text(technical_row, "ADX (14, D)", "ADX")
    bb_width = tech_text(technical_row, "볼린저밴드 폭 (D)", "BB폭")
    bb_width_avg = tech_text(technical_row, "지난 60일 볼린저밴드 폭 평균", "60일 BB폭")
    vol_ratio = tech_text(technical_row, "거래량비", "Volume Ratio")

    if code == "A":
        detail = f"현재가 {price} / MA200 {ma200} | 종가 %B {pct_b} | RSI {rsi} | MACD Hist {macd_hist}"
    elif code == "B":
        detail = f"현재가 {price} / MA200 {ma200} | RSI {rsi}"
    elif code == "C":
        detail = f"현재가 {price} / MA200 {ma200} | BB폭 {bb_width} / 60일 {bb_width_avg} | 거래량비 {vol_ratio} | 종가 %B {pct_b} | MACD Hist {macd_hist}"
    elif code == "D":
        detail = f"현재가 {price} / MA200 {ma200} | +DI {plus_di} / -DI {minus_di} | ADX {adx} | 종가 %B {pct_b} | MACD Hist {macd_hist}"
    elif code == "E":
        detail = f"현재가 {price} / MA200 {ma200} | BB폭 {bb_width} / 60일평균 {bb_width_avg} | 저가 %B {pct_b_low}"
    elif code == "F":
        detail = f"현재가 {price} / MA200 {ma200} | 저가 %B {pct_b_low}"
    else:
        detail = f"현재가 {price} / MA200 {ma200}"
    return detail


def buy_reason(stock: dict[str, Any], technical_row: dict[str, Any]) -> str:
    codes = buy_strategy_codes(stock, technical_row)
    if not codes:
        return f"매수 조건 충족 — {buy_reason_detail('', stock, technical_row)}"

    reasons = [
        f"{strategy_label(code, stock, technical_row)} — {buy_reason_detail(code, stock, technical_row)}"
        for code in codes
    ]
    if len(reasons) == 1:
        return reasons[0]
    return "동시 충족 전략 " + str(len(reasons)) + "개\n- " + "\n- ".join(reasons)


def change_strategy_code(previous_stock: dict[str, Any], current_stock: dict[str, Any], technical_row: dict[str, Any]) -> str:
    values = (
        strategy_values(previous_stock.get("strategies"))
        + strategy_values(current_stock.get("strategies"))
        + strategy_values(technical_row.get("entryStrategy"))
        + strategy_values(technical_row.get("entrySignals"))
        + strategy_values(technical_row.get("entrySignalCodes"))
        + strategy_values(technical_row.get("진입 전략"))
    )
    for value in values:
        code = strategy_code(value)
        if code:
            return code
    return "A"


def metric_context(current_stock: dict[str, Any], technical_row: dict[str, Any]) -> dict[str, Any]:
    current_price = first_text(current_stock.get("currentPrice"), technical_row.get("현재가"), technical_row.get("currentPrice"))
    context = {
        "price": current_price,
        "price_num": parse_metric_number(current_price),
        "ma200": metric_label(technical_row, "200일 이동평균선", "MA200", "ma200"),
        "ma200_num": metric_number(technical_row, "200일 이동평균선", "MA200", "ma200"),
        "rsi": metric_label(technical_row, "RSI (D)", "RSI"),
        "rsi_num": metric_number(technical_row, "RSI (D)", "RSI"),
        "cci": metric_label(technical_row, "CCI (D)", "CCI"),
        "cci_num": metric_number(technical_row, "CCI (D)", "CCI"),
        "macd": metric_label(technical_row, "MACD Histogram (D)", "MACD Hist", "macdHist"),
        "macd_num": metric_number(technical_row, "MACD Histogram (D)", "MACD Hist", "macdHist"),
        "pct_b": metric_label(technical_row, "볼린저밴드 %B (종가)", "%B", "pctB"),
        "pct_b_num": metric_number(technical_row, "볼린저밴드 %B (종가)", "%B", "pctB"),
        "pct_b_low": metric_label(technical_row, "볼린저밴드 %B (저가)", "저가%B", "pctBLow"),
        "pct_b_low_num": metric_number(technical_row, "볼린저밴드 %B (저가)", "저가%B", "pctBLow"),
        "bb_width": metric_label(technical_row, "볼린저밴드 폭 (D)", "BB폭", "bbWidth"),
        "bb_width_num": metric_number(technical_row, "볼린저밴드 폭 (D)", "BB폭", "bbWidth"),
        "bb_width_avg": metric_label(technical_row, "지난 60일 볼린저밴드 폭 평균", "60일 BB폭", "bbWidthAvg60"),
        "bb_width_avg_num": metric_number(technical_row, "지난 60일 볼린저밴드 폭 평균", "60일 BB폭", "bbWidthAvg60"),
        "vol_ratio": metric_label(technical_row, "거래량비", "Volume Ratio", "거래량 (D)"),
        "plus_di": metric_label(technical_row, "+DI (DMI, 14)", "+DI"),
        "plus_di_num": metric_number(technical_row, "+DI (DMI, 14)", "+DI"),
        "minus_di": metric_label(technical_row, "-DI (DMI, 14)", "-DI"),
        "minus_di_num": metric_number(technical_row, "-DI (DMI, 14)", "-DI"),
        "adx": metric_label(technical_row, "ADX (14, D)", "ADX"),
        "low": metric_label(technical_row, "C - Low", "저가"),
        "lr_trendline": metric_label(technical_row, "120일 저가 회귀 추세선", "LR추세선", "lrTrendline"),
    }
    return context


def market_context(technical_row: dict[str, Any]) -> str:
    decision_log = str(technical_row.get("decisionLog") or "")
    for line in decision_log.splitlines():
        if line.startswith("시장 국면:"):
            return line
    return ""


def append_market_context(reason: str, technical_row: dict[str, Any]) -> str:
    return reason


def watch_release_detail(strategy: str, current_stock: dict[str, Any], technical_row: dict[str, Any]) -> str:
    s = STRATEGY_RULES
    c = metric_context(current_stock, technical_row)
    price_num = c["price_num"]
    ma200_num = c["ma200_num"]
    macd_num = c["macd_num"]
    pct_b_num = c["pct_b_num"]
    pct_b_low_num = c["pct_b_low_num"]
    rsi_num = c["rsi_num"]
    cci_num = c["cci_num"]
    plus_di_num = c["plus_di_num"]
    minus_di_num = c["minus_di_num"]
    bb_width_num = c["bb_width_num"]
    bb_width_avg_num = c["bb_width_avg_num"]

    if price_num is not None and ma200_num is not None and price_num <= ma200_num:
        return f"200일선 하방 이탈 (현재가 {c['price']} / MA200 {c['ma200']})"

    if strategy == "A":
        if macd_num is not None and macd_num <= 0:
            return f"MACD 골든크로스 소멸 (Hist {c['macd']} ≤ 0)"
        return (
            "모멘텀 재가속 조건 이탈 "
            f"(종가 %B {c['pct_b']} / 기준 >{s['GOLDEN_CROSS_PCTB_MIN']}, "
            f"RSI {c['rsi']} / 기준 >{s['GOLDEN_CROSS_RSI_MIN']}, MACD Hist {c['macd']})"
        )

    if strategy == "B":
        if price_num is not None and ma200_num is not None and price_num >= ma200_num:
            return f"주가가 200일선 위로 회복 (현재가 {c['price']} / MA200 {c['ma200']})"
        oversold_released = (
            (rsi_num is not None or cci_num is not None)
            and not (rsi_num is not None and rsi_num < float(s["RSI_MAX"]))
            and not (cci_num is not None and cci_num < float(s["CCI_MIN"]))
        )
        if oversold_released:
            return f"과매도 해소 (RSI {c['rsi']} / CCI {c['cci']})"
        return f"공황 저점 조건 이탈 (저가 {c['low']} / LR추세선 {c['lr_trendline']} / RSI {c['rsi']} / CCI {c['cci']})"

    if strategy == "C":
        if macd_num is not None and macd_num <= 0:
            return f"MACD 소멸 (Hist {c['macd']} ≤ 0)"
        return f"스퀴즈 거래량 돌파 조건 이탈 (거래량비 {c['vol_ratio']} / 종가 %B {c['pct_b']} / MACD Hist {c['macd']})"

    if strategy == "D":
        if plus_di_num is not None and minus_di_num is not None and plus_di_num <= minus_di_num:
            return f"DMI 방향 전환 (+DI {c['plus_di']} ≤ -DI {c['minus_di']})"
        if macd_num is not None and macd_num <= 0:
            return f"MACD 소멸 (Hist {c['macd']} ≤ 0)"
        return f"상승 흐름 조건 이탈 (+DI {c['plus_di']} / -DI {c['minus_di']} / ADX {c['adx']} / MACD Hist {c['macd']})"

    if strategy == "E":
        if bb_width_num is not None and bb_width_avg_num is not None and bb_width_avg_num > 0:
            squeeze_ratio = bb_width_num / bb_width_avg_num
            if squeeze_ratio >= float(s["SQUEEZE_RATIO"]):
                return f"BB 스퀴즈 해소 (BB폭 {c['bb_width']} / 60일평균 {c['bb_width_avg']})"
        if pct_b_low_num is not None and pct_b_low_num > float(s["SQUEEZE_PCT_B_MAX"]):
            return f"저가 %B 상승 ({c['pct_b_low']} > {s['SQUEEZE_PCT_B_MAX']})"
        return f"E그룹 저점 조건 이탈 (BB폭 {c['bb_width']} / 60일평균 {c['bb_width_avg']} / 저가 %B {c['pct_b_low']})"

    if pct_b_low_num is not None and pct_b_low_num > float(s["BB_PCT_B_LOW_MAX"]):
        return f"BB 하단 눌림 해소 (저가 %B {c['pct_b_low']} > {s['BB_PCT_B_LOW_MAX']})"
    return f"F그룹 눌림 조건 이탈 (현재가 {c['price']} / MA200 {c['ma200']} / 저가 %B {c['pct_b_low']})"


def watch_reason(
    old_opinion: str,
    previous_stock: dict[str, Any],
    current_stock: dict[str, Any],
    technical_row: dict[str, Any],
) -> str:
    if old_opinion == "매수":
        strategy = change_strategy_code(previous_stock, current_stock, technical_row)
        label = STRATEGY_LABELS.get(strategy, "매수 조건")
        detail = watch_release_detail(strategy, current_stock, technical_row)
        return append_market_context(
            f"매수 조건 해제 ({label}) — {detail} (보유 포지션 유지, 매도 조건 계속 추적)",
            technical_row,
        )
    if old_opinion == "매도":
        return "매도 후 대기 완료 → 관망 전환 (재진입 필터 유지)"
    detail = buy_reason_detail("", current_stock, technical_row)
    return f"관망 전환 — 현재 매수/매도 조건 미충족 ({detail})"


def sell_reason(current_stock: dict[str, Any], technical_row: dict[str, Any]) -> str:
    explicit_reason = first_text(
        current_stock.get("opinionReason"),
        technical_row.get("exitReason"),
        technical_row.get("매도 사유"),
    )
    if explicit_reason != "-":
        return explicit_reason
    c = metric_context(current_stock, technical_row)
    return append_market_context(
        f"매도 조건 충족 — 현재가 {c['price']} / MA200 {c['ma200']} | RSI {c['rsi']} | MACD Hist {c['macd']}",
        technical_row,
    )


def concise_opinion_reason(
    old_opinion: str,
    new_opinion: str,
    previous_stock: dict[str, Any],
    current_stock: dict[str, Any],
    technical_row: dict[str, Any],
) -> str:
    if new_opinion == "매수":
        return buy_reason(current_stock, technical_row)
    if new_opinion == "매도":
        return sell_reason(current_stock, technical_row)
    if new_opinion == "관망":
        explicit_reason = first_text(current_stock.get("opinionReason"), technical_row.get("opinionReason"))
        if explicit_reason != "-":
            return explicit_reason
        return watch_reason(old_opinion, previous_stock, current_stock, technical_row)
    return "-"


def change_reason_html(reason: Any) -> str:
    text = str(reason or "-")
    return html.escape(text).replace("\n", "<br>") or "-"


def change_display_from(change: dict[str, Any]) -> str:
    from_label = str(change.get("fromLabel") or "").strip()
    if from_label:
        return from_label
    if change.get("from") == "매수" and change.get("to") == "매수":
        return "매수(보유중)"
    return str(change.get("from") or "-")


def change_display_to(change: dict[str, Any]) -> str:
    to_label = str(change.get("toLabel") or "").strip()
    if to_label:
        return to_label
    if change.get("from") == "매수" and change.get("to") == "매수":
        return "추가 매수"
    return str(change.get("to") or "-")


def first_metric_number(value: Any) -> float | None:
    match = re.search(r"[+-]?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def market_snapshot_map(technical_path: Path = DEFAULT_TECHNICAL) -> dict[str, str]:
    payload = read_json(technical_path)
    rows = payload.get("marketSnapshot") if isinstance(payload, dict) else []
    snapshot: dict[str, str] = {}
    if not isinstance(rows, list):
        return snapshot
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        key = str(row[0] or "").strip()
        if key:
            snapshot[key] = str(row[1] or "").strip()
    return snapshot


def fmt_context_percent(value: float | None) -> str:
    return "데이터 없음" if value is None else f"{value:.2f}%"


def fmt_context_index(value: float | None) -> str:
    return "데이터 없음" if value is None else f"{value:,.2f}"


def build_macro_context_html(technical_path: Path = DEFAULT_TECHNICAL) -> str:
    snapshot = market_snapshot_map(technical_path)
    us10y = first_metric_number(snapshot.get("미국 10년물 금리"))
    dxy = first_metric_number(snapshot.get("달러 인덱스"))
    vix = first_metric_number(snapshot.get("VIX (변동성지수) 당일·전날"))
    qqq_price = first_metric_number(snapshot.get("나스닥 (QQQ, 당일)"))
    qqq_ma60 = first_metric_number(snapshot.get("나스닥 (QQQ, 60일 이동평균선)"))
    tech_weak = qqq_price is not None and qqq_ma60 is not None and qqq_price < qqq_ma60
    nasdaq_status = (
        f"{fmt_context_index(qqq_price)} / 60일선 {fmt_context_index(qqq_ma60)} ({'하회' if tech_weak else '상회'})"
        if qqq_price is not None and qqq_ma60 is not None
        else "데이터 없음"
    )

    active_flags = []
    if us10y is not None and us10y >= 4.2:
        active_flags.append("고금리")
    if dxy is not None and dxy >= 103:
        active_flags.append("강달러")
    if vix is not None and vix >= 20:
        active_flags.append("시장 불안(VIX)")
    if tech_weak:
        active_flags.append("기술주 약세")

    status_line = (
        f'현재 체크 구간: <strong style="color:#c0392b;">{html.escape(" · ".join(active_flags))}</strong>'
        if active_flags
        else '현재 체크 구간: <strong style="color:#27ae60;">해당 없음</strong>'
    )

    return f"""
      <div style="margin:12px 0 14px;padding:10px 12px;background:#fff8e8;border-left:3px solid #f39c12;font-size:13px;color:#444;">
        <strong>매크로 참고</strong><br>
        단, 고금리(미국 10년물 4.2% 이상), 강달러(달러 인덱스 103 이상), 시장 불안(VIX 20 이상), 기술주 약세(QQQ 60일선 하회) 구간에서는 적자 성장주보다 <strong>실적이 확인되는 종목</strong>을 우선할 것을 권장합니다.<br>
        현재값: 미국 10년물 <strong>{html.escape(fmt_context_percent(us10y))}</strong> · 달러 인덱스 <strong>{html.escape(fmt_context_index(dxy))}</strong> · VIX <strong>{html.escape(fmt_number(vix)) if vix is not None else "데이터 없음"}</strong> · QQQ <strong>{html.escape(nasdaq_status)}</strong><br>
        {status_line}
      </div>
    """


def build_trend_top3_html() -> str:
    trend = latest_market_trend()
    if not trend:
        return ""
    top3 = [rank for rank in market_trend_ranks(trend) if rank["rank"] <= 3]
    if not top3:
        return ""
    rows_html = "".join(
        f"""
        <div style="padding:5px 0;border-bottom:1px solid #e8f0fe;font-size:13px;">
          <span style="color:#3498db;font-weight:bold;min-width:28px;display:inline-block;">{rank['rank']}위</span>
          <strong style="color:#222;">{html.escape(str(rank['sector']))}</strong>
          <span style="color:#666;margin-left:8px;">{html.escape(str(rank['keywords']))}</span>
        </div>
        """
        for rank in top3
    )
    date = str(trend.get("date") or "").strip()
    date_html = f" (기준: {html.escape(date)})" if date else ""
    summary = str(trend.get("summary") or "").strip()
    summary_html = f'<div style="margin-top:8px;font-size:12px;color:#555;">※ {html.escape(summary)}</div>' if summary else ""
    return f"""
      <div style="margin:0 0 14px;padding:10px 12px;background:#f0f7ff;border-left:3px solid #3498db;font-size:13px;color:#444;">
        <strong>이번 주 시장 트렌드 Top 3</strong>{date_html}<br>
        <div style="margin-top:6px;">{rows_html}</div>
        {summary_html}
      </div>
    """


def opinion_email_body(
    changes: list[dict[str, Any]],
    buy_opinions: list[str] | None = None,
    watch_holding_opinions: list[str] | None = None,
    sell_opinions: list[str] | None = None,
) -> str:
    changed_html = []
    has_buy_transition = any(
        (change.get("to") == "매수" and (change.get("from") != "매수" or "추가 매수" in change_display_to(change)))
        for change in changes
    )
    for index, change in enumerate(changes, start=1):
        from_label = change_display_from(change)
        to_label = change_display_to(change)
        is_buy = change["to"] == "매수" or "매수" in to_label
        is_sell = change["to"] == "매도" or "매도" in to_label
        border = "#2ecc71" if is_buy else "#e74c3c" if is_sell else "#95a5a6"
        color = "#27ae60" if is_buy else "#c0392b" if is_sell else "#7f8c8d"
        entry_note = str(change.get("entryNote") or "").strip()
        entry_note_html = ""
        if entry_note:
            note_color = "#2980b9" if entry_note == "신규 진입" else "#e67e22" if entry_note.startswith("재진입") else "#7f8c8d"
            entry_note_html = f'<br><span style="font-size:12px;color:{note_color};">{change_reason_html(entry_note)}</span>'
        industry = str(change.get("industry") or "").strip()
        trend_badge = str(change.get("trendBadge") or "").strip()
        changed_html.append(
            f"""
            <div style="margin-bottom:8px;padding:8px;background:#f9f9f9;border-left:3px solid {border};">
              {index}. <strong>{html.escape(display_stock(change))}</strong>
              &nbsp;<span style="color:#888;">'{html.escape(from_label)}'</span>
              → <strong style="color:{color};">{html.escape(to_label)}</strong><br>
              <span style="font-size:13px;">이유: {change_reason_html(change.get('reason'))}</span><br>
              <span style="font-size:13px;">현재가: <strong>{html.escape(str(change.get('price') or '-'))}</strong></span>
              {entry_note_html}
              {f'<br><span style="font-size:12px;color:#666;">산업: {html.escape(industry)}</span>' if industry and industry != '-' else ''}
              {f'<br><span style="font-size:12px;color:#e67e22;">{html.escape(trend_badge)}</span>' if trend_badge else ''}
            </div>
            """
        )

    kst_label, et_label = now_labels()
    macro_context_html = build_macro_context_html() if has_buy_transition else ""
    trend_top3_html = build_trend_top3_html() if has_buy_transition else ""
    return f"""
    <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;max-width:600px;">
      <p style="font-size:16px;font-weight:bold;color:#333;border-bottom:2px solid #eee;padding-bottom:8px;">
        투자의견이 변경된 종목이 있습니다.
      </p>
      <div>{''.join(changed_html)}</div>
      {macro_context_html}
      {trend_top3_html}
      <p style="margin:0;"><strong>현재 매수 의견 종목:</strong> {html.escape(list_text(buy_opinions or []))}</p>
      <p style="margin:0;"><strong>보유 중 관망 종목:</strong> {html.escape(list_text(watch_holding_opinions or []))}</p>
      <p style="margin:0;"><strong>현재 매도 의견 종목:</strong> {html.escape(list_text(sell_opinions or []))}</p><br>
      <p style="color:#888;font-size:12px;">
        발송 시각 (한국): {html.escape(kst_label)}<br>
        발송 시각 (미 동부): {html.escape(et_label)}
      </p>
    </div>
    """


def trade_exit_email_body(changes: list[dict[str, Any]]) -> str:
    return opinion_email_body(changes)


def admin_failure_body(message: str) -> str:
    now = datetime.now().astimezone().strftime("%Y.%m.%d %H:%M")
    return f"""
    <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.7;max-width:600px;">
      <p style="font-size:16px;font-weight:bold;color:#d32f2f;border-bottom:2px solid #ffcdd2;padding-bottom:8px;">
        자동 업데이트 실패 알림
      </p>
      <div style="margin:16px 0;padding:12px 16px;background:#fff3e0;border-left:3px solid #ff9800;font-size:13px;color:#333;">
        <strong>실패 내용:</strong> {html.escape(message)}
      </div>
      <p style="margin:0;color:#555;">GitHub Actions 실행 로그와 환경변수/시크릿 설정을 확인해 주세요.</p>
      <p style="color:#888;font-size:12px;margin-top:18px;">발송 시각: {html.escape(now)}</p>
    </div>
    """


def latest_market_trend() -> dict[str, Any]:
    payload = read_json(DEFAULT_MARKET_TRENDS)
    rows = payload.get("rows") if isinstance(payload, dict) else []
    valid_rows = [row for row in rows if isinstance(row, dict)]
    if not valid_rows:
        return {}

    def date_key(row: dict[str, Any]) -> datetime:
        try:
            return datetime.strptime(str(row.get("date", "")), "%Y.%m.%d")
        except ValueError:
            return datetime.min

    return max(valid_rows, key=date_key)


def top_sector_text() -> str:
    trend = latest_market_trend()
    ranks = trend.get("ranks") if isinstance(trend.get("ranks"), list) else []
    if not ranks:
        return "트렌드 데이터 없음"
    labels = []
    for index, rank in enumerate(ranks[:3], start=1):
        sector = str(rank).split("|", 1)[0].strip()
        if sector:
            labels.append(f"{sector} ({index}위)")
    return ", ".join(labels) if labels else "트렌드 데이터 없음"


def market_trend_ranks(trend: dict[str, Any]) -> list[dict[str, Any]]:
    ranks = trend.get("ranks") if isinstance(trend.get("ranks"), list) else []
    result = []
    for index, raw_rank in enumerate(ranks[:10], start=1):
        parts = [part.strip() for part in str(raw_rank).split("|", 1)]
        result.append({
            "rank": index,
            "sector": parts[0] if parts else "-",
            "keywords": parts[1] if len(parts) > 1 else "",
        })
    return result


def weekly_trend_email_body(trend: dict[str, Any]) -> str:
    ranks = market_trend_ranks(trend)
    report_date = str(trend.get("date") or datetime.now(KST).strftime("%Y.%m.%d"))
    summary = str(trend.get("summary") or "시장 요약 데이터가 없습니다.")
    ranks_html = "".join(
        f"""
        <div style="padding:7px 0;border-bottom:1px solid #f0f0f0;font-size:14px;">
          <span style="color:#aaa;min-width:32px;display:inline-block;">{rank['rank']}위</span>
          <strong style="color:#222;">{html.escape(str(rank['sector']))}</strong>
          <span style="color:#666;margin-left:8px;font-size:13px;">{html.escape(str(rank['keywords']))}</span>
        </div>
        """
        for rank in ranks
    )

    return f"""
    <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.7;max-width:640px;">
      <p style="font-size:16px;font-weight:bold;color:#333;border-bottom:2px solid #eee;padding-bottom:8px;">
        주간 시장 트렌드 리포트 ({html.escape(report_date)})
      </p>
      <div style="margin:12px 0;">{ranks_html or '<p>트렌드 순위 데이터가 없습니다.</p>'}</div>
      <div style="margin-top:16px;padding:10px 14px;background:#f0f7ff;border-left:3px solid #3498db;font-size:13px;color:#333;">
        ※ {html.escape(summary)}
      </div>
      <p style="color:#bbb;font-size:11px;margin-top:20px;">시장 트렌드 갱신 완료 후 자동 발송</p>
    </div>
    """


def send_weekly_trend_notifications() -> int:
    trend = latest_market_trend()
    if not trend:
        print("No market trend data.")
        return 0

    recipients = [
        recipient
        for recipient in load_recipients()
        if enabled(recipient, "weeklyTrendReport")
    ]
    if not recipients:
        print("No recipients for weeklyTrendReport.")
        return 0

    report_date = str(trend.get("date") or datetime.now(KST).strftime("%Y.%m.%d"))
    subject = f"[주간 트렌드] 시장 트렌드 리포트 ({report_date})"
    body = weekly_trend_email_body(trend)
    sent = 0
    for recipient in recipients:
        send_notification(recipient, subject, append_notification_footer(body, recipient, "weeklyTrendReport"))
        sent += 1
    print(f"Sent weekly trend notifications: {sent}")
    return sent


def fetch_weekly_rsi(symbol: str = "QQQ") -> float:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + urllib.parse.quote(symbol)
        + "?range=2y&interval=1wk"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("chart", {}).get("result", [{}])[0]
    closes = [
        float(value)
        for value in result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if value is not None
    ]
    rsi_values = calc_rsi(closes)
    if not rsi_values:
        raise RuntimeError("QQQ 주봉 RSI를 계산할 데이터가 부족합니다.")
    return round(rsi_values[-1], 2)


def qqq_peak_snapshot() -> dict[str, Any]:
    row = calc_technical_row("QQQ")
    qqq_rows = fetch_us_ohlcv("QQQ", range_value="2y")
    weekly_rsi = fetch_weekly_rsi("QQQ")
    recent_min_dist = qqq_recent_ma200_min_distance(qqq_rows)
    snapshot = build_qqq_market_state(row, recent_min_dist=recent_min_dist, weekly_rsi=weekly_rsi)
    ma200 = float(snapshot["ma200"] or 0)
    snapshot["directThreshold"] = ma200 * (1 + float(snapshot["peakDirectDist"]) / 100) if ma200 > 0 else 0
    snapshot["confirmThreshold"] = ma200 * (1 + float(snapshot["peakConfirmDist"]) / 100) if ma200 > 0 else 0
    snapshot["resetThreshold"] = ma200 * (1 + float(snapshot["peakResetDist"]) / 100) if ma200 > 0 else 0
    snapshot["triggered"] = snapshot["peakTriggered"]
    return snapshot


def nasdaq_peak_email_body(snapshot: dict[str, Any]) -> str:
    kst_date, et_date = now_labels()
    regime = html.escape(str(snapshot.get("regimeLabel") or "-"))
    direct_dist = float(snapshot.get("peakDirectDist") or 0)
    confirm_dist = float(snapshot.get("peakConfirmDist") or 0)
    trigger_rule = (
        f"회복장에서는 QQQ가 200일선보다 +{direct_dist:.0f}% 이상 높으면 과열로 봅니다."
        if snapshot.get("isRecoveryMarket")
        else f"비회복장에서는 QQQ가 200일선보다 +{direct_dist:.0f}% 이상 높고 RSI가 꺾이거나, +{confirm_dist:.0f}% 이상에서 RSI와 MACD가 함께 식으면 과열로 봅니다."
    )
    return f"""
    <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#222;max-width:640px;">
      <p style="font-size:16px;font-weight:bold;color:#333;margin:0 0 12px 0;">
        QQQ 과열 청산 조건이 켜졌습니다.
      </p>
      <div style="border:1px solid #fde68a;background:#fffbeb;border-radius:10px;padding:12px 14px;margin:0 0 14px 0;">
        <div style="font-weight:bold;margin-bottom:6px;">핵심만 보면</div>
        <div>QQQ가 국면별 고점 청산 기준을 충족했습니다.</div>
        <div>이 알림은 시장 공통 청산 조건이 충족됐다는 뜻입니다.</div>
        <div>웹서비스는 신규 매수와 추가매수를 막고, 보유 종목은 청산 기준으로 점검합니다.</div>
        <div style="margin-top:6px;">개별 종목의 실제 청산 반영은 이어서 발송되는 투자의견 변경 메일이나 웹의 보유 현황에서 확인해 주세요.</div>
      </div>
      <div style="margin:0 0 14px 0;">
        <div style="font-weight:bold;margin-bottom:6px;">시장 위치</div>
        <div><strong>QQQ 현재가:</strong> {snapshot['currentPrice']:.2f}</div>
        <div><strong>QQQ 200일 이평선:</strong> {snapshot['ma200']:.2f}</div>
        <div><strong>200일선 대비:</strong> {fmt_signed(snapshot.get('premiumPercent'), '%')}</div>
        <div><strong>최근 60거래일 최저 이격도:</strong> {fmt_signed(snapshot.get('recent60MinPremiumPercent'), '%')}</div>
        <div><strong>시장 국면:</strong> {regime}</div>
        <div><strong>직접 청산선:</strong> +{direct_dist:.0f}% ({snapshot['directThreshold']:.2f}) - 이 위면 과열로 바로 판단</div>
        {'' if snapshot.get("isRecoveryMarket") else f'<div><strong>확인 청산선:</strong> +{confirm_dist:.0f}% ({snapshot["confirmThreshold"]:.2f}) - 이 위에서는 RSI/MACD 둔화까지 확인</div>'}
      </div>
      <div style="margin:0 0 14px 0;">
        <div style="font-weight:bold;margin-bottom:6px;">힘이 식는지 보는 지표</div>
        <div><strong>QQQ 주봉 RSI(14):</strong> {fmt_number(snapshot.get('weeklyRsi'))}</div>
        <div><strong>QQQ 일봉 RSI(14):</strong> {fmt_number(snapshot.get('dailyRsi'))}</div>
        <div><strong>QQQ 일봉 RSI 전일:</strong> {fmt_number(snapshot.get('dailyRsiPrev'))}</div>
        <div><strong>QQQ MACD Histogram (D/D-1/D-2):</strong> {fmt_signed(snapshot.get('macdHist'))} / {fmt_signed(snapshot.get('macdHistD1'))} / {fmt_signed(snapshot.get('macdHistD2'))}</div>
      </div>
      <p>
        <strong>이번 알림이 뜬 이유:</strong> {html.escape(trigger_rule)}
      </p>
      <p>
        <strong>지금 할 일:</strong> 새 매수와 추가매수는 보류하고, 보유 종목은 웹의 보유 현황 또는 이어지는 투자의견 변경 메일에서 실제 청산 반영 여부를 확인해 주세요.
      </p>
      <p style="color:#888;font-size:12px;margin:0;">
        발송 시각 (한국): {html.escape(kst_date)}<br>
        발송 시각 (미 동부): {html.escape(et_date)}
      </p>
    </div>
    """


def send_nasdaq_peak_notifications() -> int:
    state = read_json(NOTIFICATION_STATE)
    if not isinstance(state, dict):
        state = {}
    snapshot = qqq_peak_snapshot()
    peak_state = state.get("nasdaqPeak") if isinstance(state.get("nasdaqPeak"), dict) else {}
    was_sent = peak_state.get("sent") is True

    if snapshot["currentPrice"] <= snapshot["resetThreshold"] and was_sent:
        state["nasdaqPeak"] = {"sent": False, "resetAt": datetime.now().astimezone().isoformat()}
        write_json(NOTIFICATION_STATE, state)
        print("Nasdaq peak state reset.")
        return 0

    if not snapshot["triggered"]:
        print("Nasdaq peak signal not triggered.")
        return 0
    if was_sent:
        print("Nasdaq peak notification already sent.")
        return 0

    recipients = [
        recipient
        for recipient in load_recipients()
        if enabled(recipient, "nasdaqPeakEmail")
    ] or fallback_admin_recipients()
    recipients = dedupe_recipients(recipients)
    if not recipients:
        print("No recipients for nasdaq peak notification.")
        return 0

    subject = "나스닥 과열 청산 조건 알림"
    body = nasdaq_peak_email_body(snapshot)
    sent = 0
    for recipient in recipients:
        send_notification(recipient, subject, append_notification_footer(body, recipient, "nasdaqPeakEmail"))
        sent += 1

    state["nasdaqPeak"] = {
        "sent": True,
        "sentAt": datetime.now().astimezone().isoformat(),
        "snapshot": snapshot,
    }
    write_json(NOTIFICATION_STATE, state)
    print(f"Sent nasdaq peak notifications: {sent}")
    return sent


def earnings_candidates(tickers: set[str], stocks: dict[str, dict[str, Any]], valuations: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for ticker in sorted(tickers):
        metric = valuations.get(ticker)
        if not metric:
            continue
        earnings_date = str(metric.get("earningsDate") or "").strip()
        if "(D-1)" not in earnings_date:
            continue
        stock = stocks.get(ticker, {})
        candidates.append({
            "ticker": ticker,
            "name": stock.get("name") or ticker,
            "date": earnings_date.split(" ", 1)[0],
            "industry": stock.get("industry") or metric.get("industry") or "-",
            "opinion": stock.get("opinion") or "관망",
            "price": stock.get("currentPrice") or "-",
        })
    return candidates


def earnings_email_body(candidates: list[dict[str, Any]]) -> str:
    kst_date, et_date = now_labels()
    cards = []
    for stock in candidates:
        is_buy = stock["opinion"] == "매수"
        is_sell = "매도" in str(stock["opinion"])
        border = "#2ecc71" if is_buy else "#e74c3c" if is_sell else "#95a5a6"
        badge = "#27ae60" if is_buy else "#c0392b" if is_sell else "#7f8c8d"
        cons = ["현재 매수 신호 미충족"] if stock["opinion"] == "관망" else []
        if is_sell:
            cons.append("현재 매도/쿨다운 상태")
        cards.append(f"""
        <div style="margin-bottom:10px;padding:10px;background:#f9f9f9;border-left:3px solid {border};">
          <strong style="font-size:15px;">{html.escape(str(stock['ticker']))}</strong>
          <span style="font-size:12px;color:#fff;background:{badge};padding:1px 6px;border-radius:3px;">{html.escape(str(stock['opinion']))}</span><br>
          <span style="font-size:13px;">발표일: <strong>{html.escape(str(stock['date']).replace("-", "."))}</strong></span><br>
          <span style="font-size:13px;">현재가: <strong>{html.escape(str(stock['price']))}</strong></span><br>
          <span style="font-size:12px;color:#666;">산업: {html.escape(str(stock['industry']))}</span><br><br>
          <span style="font-size:13px;color:#27ae60;">▲ 우호 요인</span>
          <span style="font-size:13px;color:#444;"> 시장 이벤트 사전 확인 가능</span><br>
          <span style="font-size:13px;color:#c0392b;">▼ 주의 요인</span>
          <span style="font-size:13px;color:#444;"> {html.escape(" · ".join(cons) if cons else "실적 변동성 확대 가능")}</span><br><br>
          <span style="font-size:13px;font-weight:bold;color:#333;">발표 직후 볼 것: 매출 · EPS · 가이던스 · 컨콜 톤</span>
        </div>
        """)

    return f"""
    <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;max-width:640px;">
      <p style="font-size:16px;font-weight:bold;color:#333;border-bottom:2px solid #eee;padding-bottom:8px;">
        내일 실적발표 종목 알림
      </p>
      <div style="margin-bottom:16px;padding:8px 12px;background:#f0f7ff;border-left:3px solid #3498db;font-size:13px;color:#333;">
        이번 주 주도 섹터: {html.escape(top_sector_text())}
      </div>
      {''.join(cards)}
      <div style="padding:10px 14px;background:#fffbe6;border-left:3px solid #f39c12;font-size:13px;color:#555;">
        <strong>발표 후 공통 체크</strong><br>
        숫자(매출·EPS)보다 가이던스·컨콜 톤이 시초가를 결정하는 경우가 많습니다.
      </div>
      <p style="color:#888;font-size:12px;margin-top:14px;">
        발송 시각 (한국): {html.escape(kst_date)}<br>
        발송 시각 (미 동부): {html.escape(et_date)}
      </p>
    </div>
    """


def send_earnings_notifications(current: Path = DEFAULT_CURRENT_STOCKS, valuation: Path = DEFAULT_VALUATION) -> int:
    stocks = stock_rows_by_ticker(current)
    valuations = valuation_rows_by_ticker(valuation)
    watchlists = load_watchlists()
    recipients = [
        recipient
        for recipient in load_recipients()
        if enabled(recipient, "earningsDayBefore")
    ]
    if not recipients:
        print("No recipients for earningsDayBefore.")
        return 0

    sent = 0
    for recipient in recipients:
        tickers = watchlists.get(recipient.owner_id, set())
        candidates = earnings_candidates(tickers, stocks, valuations)
        if not candidates:
            continue
        subject = "[실적발표 D-1] " + ", ".join(stock["ticker"] for stock in candidates[:8]) + " — 내일 발표"
        send_notification(recipient, subject, append_notification_footer(earnings_email_body(candidates), recipient, "earningsDayBefore"))
        sent += 1
    print(f"Sent earnings notifications: {sent}")
    return sent


def send_opinion_notifications(
    previous: Path,
    current: Path,
    previous_trade_logs: Path | None = None,
    current_trade_logs: Path | None = None,
) -> int:
    reset_active = bool(runtime_reset_state())
    changes = opinion_changes(
        previous,
        current,
        DEFAULT_TECHNICAL,
        previous_trade_logs,
        current_trade_logs,
    )
    if not changes:
        print("No opinion changes.")
        if reset_active:
            clear_runtime_reset()
        return 0

    recipients = [
        recipient
        for recipient in load_recipients()
        if enabled(recipient, "opinionChangeEmail")
    ]
    if not recipients:
        print("No recipients for opinionChangeEmail.")
        if reset_active:
            clear_runtime_reset()
        return 0

    subject = "투자의견 변경 알림 (" + ", ".join(change["ticker"] for change in changes[:8]) + ")"
    body = opinion_email_body(changes, *opinion_groups(current))
    sent = 0
    for recipient in recipients:
        send_notification(recipient, subject, append_notification_footer(body, recipient, "opinionChangeEmail"))
        sent += 1
    if reset_active:
        clear_runtime_reset()
    print(f"Sent opinion notifications: {sent}")
    return sent


def send_trade_exit_notifications(
    previous: Path,
    current: Path,
) -> int:
    changes = trade_exit_changes(previous, current)
    if not changes:
        print("No trade exit changes.")
        return 0

    recipients = [
        recipient
        for recipient in load_recipients()
        if enabled(recipient, "opinionChangeEmail")
    ]
    if not recipients:
        print("No recipients for trade exit notifications.")
        return 0

    subject = "투자의견 변경 알림 (" + ", ".join(str(change["ticker"]) for change in changes[:8]) + ")"
    body = opinion_email_body(changes, *opinion_groups(DEFAULT_CURRENT_STOCKS, current))
    sent = 0
    for recipient in recipients:
        send_notification(recipient, subject, append_notification_footer(body, recipient, "opinionChangeEmail"))
        sent += 1
    print(f"Sent trade exit notifications: {sent}")
    return sent


def send_admin_failure(message: str) -> int:
    recipients = [
        recipient
        for recipient in load_recipients()
        if recipient.is_admin and enabled(recipient, "adminAutoUpdateFailureEmail")
    ] or fallback_admin_recipients()

    recipients = dedupe_recipients(recipients)
    if not recipients:
        print("No admin recipients.")
        return 0

    subject = "[경고] 자동 업데이트 실패"
    body = admin_failure_body(message)
    sent = 0
    for recipient in recipients:
        send_notification(recipient, subject, append_notification_footer(body, recipient, "adminAutoUpdateFailureEmail"))
        sent += 1
    print(f"Sent admin failure notifications: {sent}")
    return sent


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    opinion_parser = subparsers.add_parser("opinion")
    opinion_parser.add_argument("--previous", type=Path, default=DEFAULT_PREVIOUS_STOCKS)
    opinion_parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT_STOCKS)
    opinion_parser.add_argument("--previous-trade-logs", type=Path, default=None)
    opinion_parser.add_argument("--current-trade-logs", type=Path, default=DEFAULT_CURRENT_TRADE_LOGS)

    trade_exit_parser = subparsers.add_parser("trade-exit")
    trade_exit_parser.add_argument("--previous", type=Path, default=DEFAULT_PREVIOUS_TRADE_LOGS)
    trade_exit_parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT_TRADE_LOGS)

    earnings_parser = subparsers.add_parser("earnings")
    earnings_parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT_STOCKS)
    earnings_parser.add_argument("--valuation", type=Path, default=DEFAULT_VALUATION)

    subparsers.add_parser("nasdaq-peak")
    subparsers.add_parser("weekly-trend")

    failure_parser = subparsers.add_parser("admin-failure")
    failure_parser.add_argument("--message", default="자동 업데이트 작업이 실패했습니다.")

    args = parser.parse_args()
    if args.command == "opinion":
        send_opinion_notifications(
            args.previous,
            args.current,
            args.previous_trade_logs,
            args.current_trade_logs,
        )
        return 0
    if args.command == "trade-exit":
        send_trade_exit_notifications(args.previous, args.current)
        return 0
    if args.command == "earnings":
        send_earnings_notifications(args.current, args.valuation)
        return 0
    if args.command == "nasdaq-peak":
        send_nasdaq_peak_notifications()
        return 0
    if args.command == "weekly-trend":
        send_weekly_trend_notifications()
        return 0
    if args.command == "admin-failure":
        send_admin_failure(args.message)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
