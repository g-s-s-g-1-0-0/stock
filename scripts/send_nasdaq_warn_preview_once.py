"""Send the redesigned QQQ proximity warning once, without touching send state."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SNAPSHOT = {
    "currentPrice": 761.32,
    "ma200": 670.13,
    "premiumPercent": 13.61,
    "recent60MinPremiumPercent": 2.73,
    "regimeLabel": "횡보장 고점",
    "peakWarnDist": 13,
    "peakDirectDist": 16,
    "peakConfirmDist": 14,
    "warnThreshold": 757.25,
    "directThreshold": 777.35,
    "isRecoveryMarket": False,
}
SUBJECT = "나스닥 과열 청산선 근접 경고"


def main() -> int:
    notifications = importlib.import_module("scripts.web_refresh_notifications")
    body = notifications.nasdaq_warn_email_body(SNAPSHOT)
    sent = 0
    for recipient in notifications.load_recipients():
        if recipient.preferences.get("nasdaqWarnEmail") is not True:
            continue
        if not recipient.email:
            print(f"Skipping owner={recipient.owner_id or '-'} because no email is set.")
            continue
        notifications.send_notification(
            recipient,
            SUBJECT,
            notifications.append_notification_footer(body, recipient, "nasdaqWarnEmail"),
        )
        sent += 1
    print(f"Sent redesigned nasdaq warn preview: {sent}")
    if sent != 1:
        print("Expected exactly one recipient.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
