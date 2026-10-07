"""Send one redesigned buy/sell opinion email, without touching send state."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUBJECT = "[미리보기] 투자의견 변경 알림"
CHANGES = [
    {
        "ticker": "NVDA",
        "name": "NVIDIA",
        "from": "관망",
        "to": "매수",
        "price": "$188.40",
        "reason": "양식 확인용 예시 · 2. 상승 추세 이평선 눌림목",
        "recommendedSellPrice": "$210.00",
        "entryNote": "신규 진입",
        "actionLabel": "계좌의 10%까지 매수",
        "industry": "반도체",
    },
    {
        "ticker": "WULF",
        "name": "TeraWulf",
        "from": "보유 중",
        "to": "매도",
        "price": "$25.84",
        "reason": "양식 확인용 예시 · 목표 수익 달성",
        "entryNote": "진입가 $22.84 · 수익률 +13.13%",
    },
]


def main() -> int:
    notifications = importlib.import_module("scripts.web_refresh_notifications")
    body = notifications.opinion_email_body(
        CHANGES,
        buy_opinions=["NVIDIA (NVDA)"],
        watch_holding_opinions=[],
        sell_opinions=[],
    )
    sent = 0
    for recipient in notifications.load_recipients():
        if not recipient.is_admin or not recipient.email:
            continue
        notifications.send_notification(
            recipient,
            SUBJECT,
            notifications.append_notification_footer(body, recipient, "opinionChangeEmail"),
        )
        sent += 1
    print(f"Sent redesigned opinion preview: {sent}")
    if sent != 1:
        print("Expected exactly one recipient.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
