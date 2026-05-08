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
import base64
import hashlib
import hmac
import html
import json
import os
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

from calculator.sheet_sources import calc_rsi, calc_technical_row

DEFAULT_PREVIOUS_STOCKS = ROOT_DIR / "data" / "cache" / "stocks.before-refresh.json"
DEFAULT_CURRENT_STOCKS = ROOT_DIR / "web" / "public" / "api" / "stocks.json"
DEFAULT_VALUATION = ROOT_DIR / "web" / "public" / "api" / "valuation.json"
DEFAULT_MARKET_TRENDS = ROOT_DIR / "web" / "public" / "api" / "market-trends.json"
NOTIFICATION_STATE = ROOT_DIR / "data" / "cache" / "web-notification-state.json"
QQQ_PEAK_MULTIPLIER = 1.14
QQQ_PEAK_RSI_THRESHOLD = 65
KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Recipient:
    owner_id: str
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


def now_labels() -> tuple[str, str]:
    now = datetime.now().astimezone()
    return (
        now.astimezone(KST).strftime("%Y.%m.%d %H:%M"),
        now.astimezone(ET).strftime("%m/%d %H:%M ET"),
    )


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
            owner_id=str(row.get("owner_id") or ""),
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
        key = recipient.email.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(recipient)
    return result


def enabled(recipient: Recipient, key: str, *, default: bool = True) -> bool:
    value = recipient.preferences.get(key)
    return value if isinstance(value, bool) else default


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
              {index}. <strong>{html.escape(str(change['name']))}</strong>
              <span style="color:#aaa;">({html.escape(str(change['ticker']))})</span>
              &nbsp;<span style="color:#888;">'{html.escape(str(change['from']))}'</span>
              → <strong style="color:{color};">{html.escape(str(change['to']))}</strong><br>
              <span style="font-size:13px;">현재가: <strong>{html.escape(str(change['price']))}</strong></span><br>
              <span style="font-size:13px;">가치판단: {html.escape(str(change['valuation']))}</span><br>
              <span style="font-size:12px;color:#666;">산업: {html.escape(str(change['industry']))}</span><br>
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


def latest_market_trend() -> dict[str, Any]:
    payload = read_json(DEFAULT_MARKET_TRENDS)
    rows = payload.get("rows") if isinstance(payload, dict) else []
    return rows[0] if rows and isinstance(rows[0], dict) else {}


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
        send_email(recipient.email, subject, append_notification_footer(body, recipient, "weeklyTrendReport"))
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
    current_price = float(row["close"])
    ma200 = float(row["ma200"])
    daily_rsi = float(row["rsi"])
    daily_rsi_prev = float(row["rsiD1"])
    weekly_rsi = fetch_weekly_rsi("QQQ")
    threshold = ma200 * QQQ_PEAK_MULTIPLIER
    premium_percent = (current_price / ma200 - 1) * 100
    is_triggered = (
        current_price > threshold
        and weekly_rsi >= QQQ_PEAK_RSI_THRESHOLD
        and daily_rsi >= QQQ_PEAK_RSI_THRESHOLD
        and daily_rsi < daily_rsi_prev
    )
    return {
        "currentPrice": current_price,
        "ma200": ma200,
        "threshold": threshold,
        "premiumPercent": premium_percent,
        "weeklyRsi": weekly_rsi,
        "dailyRsi": daily_rsi,
        "dailyRsiPrev": daily_rsi_prev,
        "triggered": is_triggered,
    }


def nasdaq_peak_email_body(snapshot: dict[str, Any]) -> str:
    kst_date, et_date = now_labels()
    return f"""
    <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#222;max-width:640px;">
      <p style="font-size:16px;font-weight:bold;color:#333;margin:0 0 12px 0;">
        QQQ가 고점 과열 구간에 진입했으며, RSI 둔화 신호가 감지되었습니다.
      </p>
      <div style="margin:0 0 14px 0;">
        <div><strong>QQQ 현재가:</strong> {snapshot['currentPrice']:.2f}</div>
        <div><strong>QQQ 200일 이평선:</strong> {snapshot['ma200']:.2f}</div>
        <div><strong>200일선 대비:</strong> +{snapshot['premiumPercent']:.2f}%</div>
        <div><strong>기준선 (MA200 ×1.14):</strong> {snapshot['threshold']:.2f}</div>
      </div>
      <div style="margin:0 0 14px 0;">
        <div><strong>QQQ 주봉 RSI(14):</strong> {snapshot['weeklyRsi']:.2f}</div>
        <div><strong>QQQ 일봉 RSI(14):</strong> {snapshot['dailyRsi']:.2f}</div>
        <div><strong>QQQ 일봉 RSI 전일:</strong> {snapshot['dailyRsiPrev']:.2f}</div>
      </div>
      <p>
        QQQ가 200일 이동평균선 대비 ×1.14 이상 과열된 상태에서,
        주봉/일봉 RSI가 65 이상이고 일봉 RSI가 전일 대비 하락했습니다.
        이는 고점 구간에서 단기 에너지가 둔화되는 신호로 해석합니다.
      </p>
      <p>
        웹서비스는 이 시장 과열 알림을 먼저 발송합니다. 구글 시트처럼 개별 보유 종목을
        자동으로 매도 상태로 바꾸는 포지션 상태 관리는 아직 별도 이관 대상입니다.
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

    if snapshot["currentPrice"] <= snapshot["threshold"] and was_sent:
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

    subject = "나스닥 고점 구간 알림 (매도 시그널)"
    body = nasdaq_peak_email_body(snapshot)
    sent = 0
    for recipient in recipients:
        send_email(recipient.email, subject, append_notification_footer(body, recipient, "nasdaqPeakEmail"))
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
        send_email(recipient.email, subject, append_notification_footer(earnings_email_body(candidates), recipient, "earningsDayBefore"))
        sent += 1
    print(f"Sent earnings notifications: {sent}")
    return sent


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
        send_email(recipient.email, subject, append_notification_footer(body, recipient, "opinionChangeEmail"))
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
        send_email(recipient.email, subject, append_notification_footer(body, recipient, "adminAutoUpdateFailureEmail"))
        sent += 1
    print(f"Sent admin failure notifications: {sent}")
    return sent


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    opinion_parser = subparsers.add_parser("opinion")
    opinion_parser.add_argument("--previous", type=Path, default=DEFAULT_PREVIOUS_STOCKS)
    opinion_parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT_STOCKS)

    earnings_parser = subparsers.add_parser("earnings")
    earnings_parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT_STOCKS)
    earnings_parser.add_argument("--valuation", type=Path, default=DEFAULT_VALUATION)

    subparsers.add_parser("nasdaq-peak")
    subparsers.add_parser("weekly-trend")

    failure_parser = subparsers.add_parser("admin-failure")
    failure_parser.add_argument("--message", default="자동 업데이트 작업이 실패했습니다.")

    args = parser.parse_args()
    if args.command == "opinion":
        send_opinion_notifications(args.previous, args.current)
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
