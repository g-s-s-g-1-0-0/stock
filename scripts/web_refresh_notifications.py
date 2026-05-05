"""Send web-only notification emails after scheduled cache refresh.

This script is intentionally stdlib-only so it can run inside GitHub Actions
without paid infrastructure. It reads:
- previous stocks cache before refresh
- current stocks cache after refresh
- Supabase user_settings/profiles for notification preferences

Email is sent through Gmail SMTP. Sender is the Gmail/Workspace account whose
app password is stored in GitHub Secrets.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PREVIOUS_STOCKS = ROOT_DIR / "data" / "cache" / "stocks.before-refresh.json"
DEFAULT_CURRENT_STOCKS = ROOT_DIR / "web" / "public" / "api" / "stocks.json"


@dataclass(frozen=True)
class Recipient:
    email: str
    is_admin: bool
    preferences: dict[str, Any]


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


def opinion_changes(previous_path: Path, current_path: Path) -> list[dict[str, Any]]:
    previous = stock_rows_by_ticker(previous_path)
    current = stock_rows_by_ticker(current_path)
    changes: list[dict[str, Any]] = []

    for ticker, current_stock in current.items():
        previous_stock = previous.get(ticker)
        if not previous_stock:
            continue
        old_opinion = str(previous_stock.get("opinion") or "").strip()
        new_opinion = str(current_stock.get("opinion") or "").strip()
        if not old_opinion or not new_opinion or old_opinion == new_opinion:
            continue
        changes.append({
            "ticker": ticker,
            "name": current_stock.get("name") or ticker,
            "from": old_opinion,
            "to": new_opinion,
            "price": current_stock.get("currentPrice") or "-",
            "valuation": current_stock.get("valuation") or "-",
            "industry": current_stock.get("industry") or "-",
            "strategies": current_stock.get("strategies") or [],
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
    recipients: list[Recipient] = []

    for row in settings_rows:
        prefs = row.get("notification_preferences") if isinstance(row.get("notification_preferences"), dict) else {}
        profile = profiles.get(row.get("owner_id"), {})
        fallback_email = str(profile.get("email") or "").strip()
        target_email = str(prefs.get("recipientEmail") or fallback_email).strip()
        if not target_email:
            continue
        recipients.append(Recipient(
            email=target_email,
            is_admin=profile.get("is_admin") is True,
            preferences=prefs,
        ))
    return dedupe_recipients(recipients)


def fallback_admin_recipients() -> list[Recipient]:
    emails = [
        email.strip()
        for email in os.environ.get("ADMIN_EMAILS", "").split(",")
        if email.strip()
    ]
    return [Recipient(email=email, is_admin=True, preferences={}) for email in emails]


def dedupe_recipients(recipients: list[Recipient]) -> list[Recipient]:
    seen: set[str] = set()
    result: list[Recipient] = []
    for recipient in recipients:
        key = recipient.email.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(recipient)
    return result


def enabled(recipient: Recipient, key: str, *, default: bool = True) -> bool:
    value = recipient.preferences.get(key)
    return value if isinstance(value, bool) else default


def send_email(to_email: str, subject: str, html_body: str) -> None:
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    from_email = os.environ.get("SMTP_FROM", smtp_user).strip()
    from_name = os.environ.get("SMTP_FROM_NAME", "공수성가").strip()

    if not smtp_user or not smtp_password or not from_email:
        raise RuntimeError("SMTP_USER, SMTP_PASSWORD, SMTP_FROM 설정이 필요합니다.")

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = to_email
    message.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
        server.login(smtp_user, smtp_password)
        server.sendmail(from_email, [to_email], message.as_string())


def opinion_email_body(changes: list[dict[str, Any]]) -> str:
    changed_html = []
    for index, change in enumerate(changes, start=1):
        is_buy = change["to"] == "매수"
        is_sell = change["to"] == "매도"
        border = "#2ecc71" if is_buy else "#e74c3c" if is_sell else "#95a5a6"
        color = "#27ae60" if is_buy else "#c0392b" if is_sell else "#7f8c8d"
        strategies = change.get("strategies") if isinstance(change.get("strategies"), list) else []
        strategy_text = ", ".join(str(item) for item in strategies) if strategies else "-"
        changed_html.append(
            f"""
            <div style="margin-bottom:8px;padding:8px;background:#f9f9f9;border-left:3px solid {border};">
              {index}. <strong>{html.escape(str(change["name"]))}</strong>
              <span style="color:#aaa;">({html.escape(str(change["ticker"]))})</span>
              &nbsp;<span style="color:#888;">'{html.escape(str(change["from"]))}'</span>
              → <strong style="color:{color};">{html.escape(str(change["to"]))}</strong><br>
              <span style="font-size:13px;">현재가: <strong>{html.escape(str(change["price"]))}</strong></span><br>
              <span style="font-size:13px;">가치판단: {html.escape(str(change["valuation"]))}</span><br>
              <span style="font-size:12px;color:#666;">산업: {html.escape(str(change["industry"]))}</span><br>
              <span style="font-size:12px;color:#e67e22;">전략: {html.escape(strategy_text)}</span>
            </div>
            """
        )

    now = datetime.now().astimezone()
    return f"""
    <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;max-width:600px;">
      <p style="font-size:16px;font-weight:bold;color:#333;border-bottom:2px solid #eee;padding-bottom:8px;">
        투자의견이 변경된 종목이 있습니다.
      </p>
      <div>{''.join(changed_html)}</div>
      <p style="color:#888;font-size:12px;">발송 시각: {html.escape(now.strftime('%Y.%m.%d %H:%M'))}</p>
    </div>
    """


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


def send_opinion_notifications(previous: Path, current: Path) -> int:
    changes = opinion_changes(previous, current)
    if not changes:
        print("No opinion changes.")
        return 0

    recipients = [
        recipient
        for recipient in load_recipients()
        if enabled(recipient, "opinionChangeEmail")
    ]
    if not recipients:
        print("No recipients for opinionChangeEmail.")
        return 0

    subject = "투자의견 변경 알림 (" + ", ".join(change["ticker"] for change in changes[:8]) + ")"
    body = opinion_email_body(changes)
    sent = 0
    for recipient in recipients:
        send_email(recipient.email, subject, body)
        sent += 1
    print(f"Sent opinion notifications: {sent}")
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
        send_email(recipient.email, subject, body)
        sent += 1
    print(f"Sent admin failure notifications: {sent}")
    return sent


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    opinion_parser = subparsers.add_parser("opinion")
    opinion_parser.add_argument("--previous", type=Path, default=DEFAULT_PREVIOUS_STOCKS)
    opinion_parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT_STOCKS)

    failure_parser = subparsers.add_parser("admin-failure")
    failure_parser.add_argument("--message", default="자동 업데이트 작업이 실패했습니다.")

    args = parser.parse_args()
    if args.command == "opinion":
        send_opinion_notifications(args.previous, args.current)
        return 0
    if args.command == "admin-failure":
        send_admin_failure(args.message)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
